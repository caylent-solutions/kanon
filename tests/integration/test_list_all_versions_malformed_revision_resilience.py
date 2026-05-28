"""Integration tests for `kanon list --all-versions` malformed-revision resilience.

Covers DEFECT-006: `_walk_all_versions` currently aborts on the first malformed
historical revision (raises CatalogMetadataParseError and exits 1) instead of
skipping that revision with a stderr warning and continuing.

These tests assert the FIXED contract and are RED against unfixed code:
- exit 0 even when one historical revision has a malformed <catalog-metadata>
- stdout contains rows for every parseable (entry, revision) pair
- stdout does NOT contain any row referencing the malformed revision
- stderr contains a warning line naming the malformed (entry, revision) pair

Autouse fixtures from tests/integration/conftest.py are inherited:
- _mock_resolve_ref_to_sha
- _mock_check_sha_reachable
- _auto_create_manifest_on_walk
- _default_allow_insecure_remotes

AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-FUNC-005
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
        raise RuntimeError(
            f"git {args!r} failed in {cwd!r}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


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
    """Build a bare git repo with 3 per-commit tags; the middle tag (2.0.0) is malformed.

    Each tag corresponds to a distinct commit so that cloning at a specific
    tag yields the XML state as of that commit.

    - Tag 1.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 2.0.0: malformed XML with <name> element omitted.
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

    _write_xml(repo_specs, entry_name, "2.0.0", _MALFORMED_XML_NO_NAME_TEMPLATE)
    _commit_and_tag(work_dir, "2.0.0", "release 2.0.0 -- malformed")

    _write_xml(repo_specs, entry_name, "3.0.0", _WELL_FORMED_XML_TEMPLATE)
    _commit_and_tag(work_dir, "3.0.0", "release 3.0.0")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _build_three_tag_repo_latest_malformed(
    tmp_path: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Build a bare git repo with 3 per-commit tags; the latest tag (3.0.0) is malformed.

    - Tag 1.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 2.0.0: well-formed XML with <name>{entry_name}</name> present.
    - Tag 3.0.0: malformed XML with <name> element omitted.

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

    _write_xml(repo_specs, entry_name, "3.0.0", _MALFORMED_XML_NO_NAME_TEMPLATE)
    _commit_and_tag(work_dir, "3.0.0", "release 3.0.0 -- malformed")

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
    """DEFECT-006: `kanon list --all-versions` must tolerate malformed historical revisions.

    Both tests assert the fixed (desired) contract. Against unfixed code both
    tests FAIL because _walk_all_versions raises CatalogMetadataParseError and
    the CLI exits 1 (malformed-latest case) or emits no warning and includes
    the malformed revision in stdout (middle-malformed case).
    """

    @pytest.mark.parametrize("parseable_tag", ["1.0.0", "3.0.0"])
    def test_walk_continues_past_malformed_revision(
        self,
        tmp_path: pathlib.Path,
        parseable_tag: str,
    ) -> None:
        """Walk continues past the malformed middle revision (2.0.0).

        Three-tag repo: 1.0.0 (well-formed), 2.0.0 (malformed -- <name>
        missing), 3.0.0 (well-formed).

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
            f"Expected exit 0 but got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
        assert f"{entry_name}@{parseable_tag}" in result.stdout, (
            f"Expected stdout to contain '{entry_name}@{parseable_tag}'.\n"
            f"stdout: {result.stdout!r}"
        )
        assert f"{entry_name}@2.0.0" not in result.stdout, (
            f"Expected stdout to NOT contain '{entry_name}@2.0.0' (malformed).\n"
            f"stdout: {result.stdout!r}"
        )
        assert "2.0.0" in result.stderr, (
            f"Expected stderr to contain a warning naming the malformed revision '2.0.0'.\n"
            f"stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("parseable_tag", ["1.0.0", "2.0.0"])
    def test_walk_continues_when_latest_revision_is_malformed(
        self,
        tmp_path: pathlib.Path,
        parseable_tag: str,
    ) -> None:
        """Walk continues even when the latest revision (3.0.0) is malformed.

        Three-tag repo: 1.0.0 (well-formed), 2.0.0 (well-formed), 3.0.0
        (malformed -- <name> missing).

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
            f"Expected exit 0 but got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
        assert f"{entry_name}@{parseable_tag}" in result.stdout, (
            f"Expected stdout to contain '{entry_name}@{parseable_tag}'.\n"
            f"stdout: {result.stdout!r}"
        )
        assert f"{entry_name}@3.0.0" not in result.stdout, (
            f"Expected stdout to NOT contain '{entry_name}@3.0.0' (malformed).\n"
            f"stdout: {result.stdout!r}"
        )
        assert "3.0.0" in result.stderr, (
            f"Expected stderr to contain a warning naming the malformed revision '3.0.0'.\n"
            f"stderr: {result.stderr!r}"
        )
