"""Integration tests for `kanon list --all-versions` malformed-revision resilience.

Covers DEFECT-006: `_walk_all_versions` aborts on the first malformed
historical revision (raises CatalogMetadataParseError and exits 1) instead of
skipping that revision with a stderr warning and continuing.

TestAllVersionsResilience asserts the resilience contract:
- exit 0 even when one historical revision has genuinely non-well-formed XML
- stdout contains rows for every parseable (entry, revision) pair
- stdout does NOT contain any row referencing the malformed revision
- stderr contains a WARNING line naming the malformed (entry, revision) pair

TestAllVersionsLegacyExclusion asserts the legacy-metadata exclusion contract:
- revisions lacking <catalog-metadata><name> are EXCLUDED (not listed with derived name)
- a NOTE is emitted to stderr naming the count of skipped legacy-metadata XMLs
- when ALL revisions are legacy-flat-metadata, the walk exits 1 (fail-fast)
- genuinely unparseable (non-well-formed XML) revisions are still skipped with WARNING

Autouse fixtures from tests/integration/conftest.py are inherited:
- _mock_resolve_ref_to_sha
- _mock_check_sha_reachable
- _auto_create_manifest_on_walk
- _default_allow_insecure_remotes

AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-FUNC-005
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Well-formed marketplace XML template -- all required fields present.
_WELL_FORMED_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# Malformed marketplace XML -- <name> element is omitted so _parse_catalog_metadata
# raises CatalogMetadataParseError("... <name> is missing or whitespace-only ...").
_MALFORMED_XML_NO_NAME_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# Genuinely non-well-formed XML -- the parser raises XMLParseError (not just a
# missing-name validation error). This template triggers the skip-with-warning
# path regardless of any name-derivation logic.
_UNPARSEABLE_XML_CONTENT = "<catalog-metadata><<not valid xml at all>>"


# ---------------------------------------------------------------------------
# Low-level git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _write_xml(repo_specs: pathlib.Path, name: str, version: str, xml_template: str) -> None:
    """Write a *-marketplace.xml file under repo_specs/<name>/ using the given template."""
    entry_dir = repo_specs / name
    entry_dir.mkdir(parents=True, exist_ok=True)
    xml_path = entry_dir / f"{name}-marketplace.xml"
    xml_path.write_text(xml_template.format(name=name, version=version))


def _commit_and_tag(work_dir: pathlib.Path, tag: str, message: str) -> None:
    """Stage all changes, commit with message, and apply an annotated tag."""
    _git(["add", "-A"], cwd=work_dir)
    _git(["commit", "--allow-empty", "-m", message], cwd=work_dir)
    _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_three_tag_repo_middle_malformed(
    tmp_path: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Build a bare git repo with 3 per-commit tags; the middle tag (2.0.0) is unparseable.

    Each tag corresponds to a distinct commit so that cloning at a specific
    tag yields the XML state as of that commit.

    - Tag 1.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 2.0.0: genuinely non-well-formed XML (parser raises XMLParseError).
    - Tag 3.0.0: well-formed XML with <name>{entry_name}</name> present.

    Args:
        tmp_path: Temporary directory root.
        entry_name: Catalog entry name used across all three tags.

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    repo_specs = work_dir / "repo-specs"

    _write_xml(repo_specs, entry_name, "1.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "1.0.0", "release 1.0.0")

    entry_dir = repo_specs / entry_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / f"{entry_name}-marketplace.xml").write_text(_UNPARSEABLE_XML_CONTENT)
    _commit_and_tag(work_dir, "2.0.0", "release 2.0.0 -- unparseable XML")

    _write_xml(repo_specs, entry_name, "3.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "3.0.0", "release 3.0.0")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _build_three_tag_repo_latest_malformed(
    tmp_path: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Build a bare git repo with 3 per-commit tags; the latest tag (3.0.0) is unparseable.

    - Tag 1.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 2.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 3.0.0: genuinely non-well-formed XML (parser raises XMLParseError).

    Args:
        tmp_path: Temporary directory root.
        entry_name: Catalog entry name used across all three tags.

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    repo_specs = work_dir / "repo-specs"

    _write_xml(repo_specs, entry_name, "1.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "1.0.0", "release 1.0.0")

    _write_xml(repo_specs, entry_name, "2.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "2.0.0", "release 2.0.0")

    entry_dir = repo_specs / entry_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / f"{entry_name}-marketplace.xml").write_text(_UNPARSEABLE_XML_CONTENT)
    _commit_and_tag(work_dir, "3.0.0", "release 3.0.0 -- unparseable XML")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _build_three_tag_repo_all_no_name(
    tmp_path: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Build a bare git repo with 3 tags; every tag lacks <catalog-metadata><name>.

    The directory convention ``repo-specs/<entry_name>/<entry_name>-marketplace.xml``
    makes the name derivable even though no <name> element is present.

    - Tag 1.0.0: well-formed XML structure, <name> element absent.
    - Tag 2.0.0: well-formed XML structure, <name> element absent.
    - Tag 3.0.0: well-formed XML structure, <name> element absent.

    Args:
        tmp_path: Temporary directory root.
        entry_name: Directory name used in repo-specs/<entry_name>/; this is
            the name that should be derived by the fixed implementation.

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    repo_specs = work_dir / "repo-specs"
    for tag_version in ("1.0.0", "2.0.0", "3.0.0"):
        _write_xml(repo_specs, entry_name, tag_version, _MALFORMED_XML_NO_NAME_TEMPLATE)
        _commit_and_tag(work_dir, tag_version, f"release {tag_version}")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _build_two_tag_repo_one_unparseable(
    tmp_path: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Build a bare git repo with 2 tags; tag 1.0.0 is valid, tag 2.0.0 is unparseable XML.

    - Tag 1.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 2.0.0: genuinely non-well-formed XML (parser raises XMLParseError).

    Args:
        tmp_path: Temporary directory root.
        entry_name: Catalog entry name for the parseable revision.

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    repo_specs = work_dir / "repo-specs"

    _write_xml(repo_specs, entry_name, "1.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "1.0.0", "release 1.0.0")

    entry_dir = repo_specs / entry_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / f"{entry_name}-marketplace.xml").write_text(_UNPARSEABLE_XML_CONTENT)
    _commit_and_tag(work_dir, "2.0.0", "release 2.0.0 -- unparseable XML")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _run_list_all_versions(
    bare_repo: pathlib.Path,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `kanon list --all-versions` against a bare repo and return the process.

    KANON_ALLOW_INSECURE_REMOTES is set by the autouse fixture
    _default_allow_insecure_remotes so it is not set here.

    Args:
        bare_repo: Path to the bare git repository.
        extra_args: Additional CLI arguments appended after the base command.

    Returns:
        The completed subprocess result with captured stdout and stderr.
    """
    catalog_source = f"file://{bare_repo}@main"
    cmd = [
        sys.executable,
        "-m",
        "kanon_cli",
        "list",
        "--all-versions",
        "--no-limit",
        "--catalog-source",
        catalog_source,
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(bare_repo.parent),
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsResilience:
    """DEFECT-006: `kanon list --all-versions` must tolerate genuinely unparseable revisions.

    A revision is considered malformed only when its XML is non-well-formed
    (the parser raises XMLParseError). Missing <name> is no longer malformed;
    the name is derived from the directory convention instead.

    Both tests assert the fixed (desired) contract. They use genuinely
    unparseable XML (not just missing-name XML) for the malformed revision.
    """

    @pytest.mark.parametrize("parseable_tag", ["1.0.0", "3.0.0"])
    def test_walk_continues_past_malformed_revision(
        self,
        tmp_path: pathlib.Path,
        parseable_tag: str,
    ) -> None:
        """Walk continues past the genuinely unparseable middle revision (2.0.0).

        Three-tag repo: 1.0.0 (well-formed), 2.0.0 (non-well-formed XML),
        3.0.0 (well-formed).

        Expected fixed behaviour:
        - exit 0
        - stdout contains a row for every parseable tag (1.0.0 and 3.0.0)
        - stdout does NOT contain any row for the malformed tag (2.0.0)
        - stderr contains a warning naming the malformed revision (2.0.0)
        """
        entry_name = "resilience-entry"
        bare_repo = _build_three_tag_repo_middle_malformed(tmp_path, entry_name)

        result = _run_list_all_versions(bare_repo)

        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert f"{entry_name}@{parseable_tag}" in result.stdout, (
            f"Expected stdout to contain '{entry_name}@{parseable_tag}'.\nstdout: {result.stdout!r}"
        )
        assert f"{entry_name}@2.0.0" not in result.stdout, (
            f"Expected stdout to NOT contain '{entry_name}@2.0.0' (malformed).\nstdout: {result.stdout!r}"
        )
        assert "2.0.0" in result.stderr, (
            f"Expected stderr to contain a warning naming the malformed revision '2.0.0'.\nstderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("parseable_tag", ["1.0.0", "2.0.0"])
    def test_walk_continues_when_latest_revision_is_malformed(
        self,
        tmp_path: pathlib.Path,
        parseable_tag: str,
    ) -> None:
        """Walk continues even when the latest revision (3.0.0) is unparseable.

        Three-tag repo: 1.0.0 (well-formed), 2.0.0 (well-formed), 3.0.0
        (non-well-formed XML).

        Expected fixed behaviour:
        - exit 0
        - stdout contains a row for every parseable tag (1.0.0 and 2.0.0)
        - stdout does NOT contain any row for the malformed latest tag (3.0.0)
        - stderr contains a warning naming the malformed revision (3.0.0)
        """
        entry_name = "resilience-entry"
        bare_repo = _build_three_tag_repo_latest_malformed(tmp_path, entry_name)

        result = _run_list_all_versions(bare_repo)

        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert f"{entry_name}@{parseable_tag}" in result.stdout, (
            f"Expected stdout to contain '{entry_name}@{parseable_tag}'.\nstdout: {result.stdout!r}"
        )
        assert f"{entry_name}@3.0.0" not in result.stdout, (
            f"Expected stdout to NOT contain '{entry_name}@3.0.0' (malformed).\nstdout: {result.stdout!r}"
        )
        assert "3.0.0" in result.stderr, (
            f"Expected stderr to contain a warning naming the malformed revision '3.0.0'.\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Tests: legacy flat-metadata exclusion and unparseable XML handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsLegacyExclusion:
    """Legacy flat-metadata exclusion contract for kanon list --all-versions (E58-F1-S1-T1).

    Old-scheme XMLs (lacking <catalog-metadata><name>) are SKIPPED from the per-entry
    version list.  A single diagnostic NOTE is emitted to stderr for each revision that
    has old-scheme XMLs, naming the count.  New-scheme-only: when ALL walked revisions are
    old-scheme, the walk yields no canonical entries and exits 0 with an empty result plus
    a clear "no new-scheme version tags" note (not an error -- the old flat-attribute
    scheme is simply unsupported, so there is nothing to list).

    AC-FUNC-003/AC-FUNC-004: genuinely unparseable (non-well-formed XML) revisions are
    still skipped with the existing stderr WARNING (behavior unchanged).
    """

    @pytest.mark.parametrize("excluded_version", ["1.0.0", "2.0.0", "3.0.0"])
    def test_all_legacy_repo_exits_zero_empty_with_note(
        self,
        tmp_path: pathlib.Path,
        excluded_version: str,
    ) -> None:
        """Three tags, none carrying <catalog-metadata><name>; all revisions skipped.

        New-scheme-only: when every walked revision uses the unsupported old scheme
        (no <name>), no canonical entries can be emitted.  This is NOT an error -- the
        walk exits 0 with an empty result and a clear "no new-scheme version tags" note.

        Expected contract:
        - exit 0 (no new-scheme version tags found)
        - stdout is empty
        - stderr contains a per-revision skipped NOTE and the "no new-scheme" note
        - stdout does NOT contain the old-scheme entry's directory name as an entry name
        """
        entry_name = "derived-name-entry"
        bare_repo = _build_three_tag_repo_all_no_name(tmp_path, entry_name)

        result = _run_list_all_versions(bare_repo)

        assert result.returncode == 0, (
            f"Expected exit 0 (all-old-scheme repo) but got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stdout == "", f"Expected empty stdout for all-old-scheme repo, got: {result.stdout!r}"
        assert excluded_version in result.stderr, (
            f"Expected stderr to contain a NOTE referencing '{excluded_version}'.\nstderr: {result.stderr!r}"
        )
        assert "no new-scheme" in result.stderr.lower(), (
            f"Expected the 'no new-scheme version tags' note in stderr.\nstderr: {result.stderr!r}"
        )
        assert f"{entry_name}@{excluded_version}" not in result.stdout, (
            f"Old-scheme entry '{entry_name}@{excluded_version}' must NOT appear in stdout.\nstdout: {result.stdout!r}"
        )

    def test_unparseable_revision_skipped_with_warning(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A genuinely non-well-formed XML revision is skipped with a stderr warning.

        Two-tag repo: 1.0.0 (well-formed with <name>), 2.0.0 (broken XML).

        Expected contract (unchanged):
        - exit 0 (one revision is parseable)
        - stdout contains the row for 1.0.0
        - stdout does NOT contain a row for 2.0.0
        - stderr contains a WARNING referencing 2.0.0
        """
        entry_name = "parseable-entry"
        bare_repo = _build_two_tag_repo_one_unparseable(tmp_path, entry_name)

        result = _run_list_all_versions(bare_repo)

        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert f"{entry_name}@1.0.0" in result.stdout, (
            f"Expected stdout to contain '{entry_name}@1.0.0'.\nstdout: {result.stdout!r}"
        )
        assert f"{entry_name}@2.0.0" not in result.stdout, (
            f"Expected stdout to NOT contain '{entry_name}@2.0.0' (unparseable).\nstdout: {result.stdout!r}"
        )
        assert "2.0.0" in result.stderr, (
            f"Expected stderr to contain a warning referencing '2.0.0'.\nstderr: {result.stderr!r}"
        )
