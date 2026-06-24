"""Integration tests: `kanon search -A/--all` is new-scheme-only.

New-scheme-only contract for ``kanon search -A/--all``:
- Only canonical ``<catalog-metadata><name>`` values are emitted; the distinct
  entry-name set is a subset of the names from ``kanon search`` (AC-1).
- Old-scheme (flat-attribute / no ``<name>``) tags are SKIPPED, so the output contains
  none of the directory-path component names ``code-review``, ``idp``, ``cli``,
  ``microservice`` (AC-2); canonical entries ``security-code-review`` and
  ``spec-driven-dev-idp`` appear (AC-3).
- When EVERY version tag is old-scheme (zero new-scheme tags -- the real catalog's
  current state), the walk exits 0 with an empty result and a clear
  "no new-scheme version tags" note (TestAllVersionsAllOldScheme), NOT an error.
- ``kanon search --help`` is unchanged (AC-14).

The tests use local synthetic bare-git fixtures (not a remote network catalog):
- ``_build_all_old_scheme_fixture``: every tag uses the real old flat-attribute scheme.
- ``_build_canonical_names_fixture``: a mixed history (old-scheme + new-scheme tags),
  asserting old-scheme tags are skipped and only canonical names are emitted.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# XML templates
# ---------------------------------------------------------------------------

_MODERN_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{display_name}</display-name>
        <description>Integration test entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# Legacy flat-metadata: well-formed XML but lacks <catalog-metadata><name>.
# Mirrors the historical catalog format (pre-nested-name contract).
# The directory name is the known-bad path-component that must NOT appear in output.
_LEGACY_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <display-name>{display_name}</display-name>
        <description>Legacy integration test entry.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Canonical Names Test User"
_GIT_USER_EMAIL = "canonical-names-test@example.com"

# Known-bad path-component names that legacy directory layouts produce when
# _derive_entry_name_from_xml_path() is used as a fallback.
_KNOWN_BAD_NAMES: frozenset[str] = frozenset({"code-review", "idp", "cli", "microservice"})

# Canonical entry names that mirror the real catalog (nested <name> values).
# The directory names for legacy versions use the corresponding bad path-component names.
_CANONICAL_ENTRIES: list[tuple[str, str, str]] = [
    # (canonical_name, legacy_dir_name, display_name)
    ("security-code-review", "code-review", "Security Code Review"),
    ("spec-driven-dev-idp", "idp", "Spec Driven Dev IDP"),
]

# Additional canonical entry not mirroring a legacy bad name (sanity control).
_EXTRA_CANONICAL_ENTRY: tuple[str, str] = ("platform-bootstrap", "Platform Bootstrap")


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


def _write_modern_xml(
    repo_specs: pathlib.Path,
    dir_name: str,
    canonical_name: str,
    display_name: str,
    version: str,
) -> None:
    """Write a modern *-marketplace.xml with nested <catalog-metadata><name>."""
    entry_dir = repo_specs / dir_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    xml_path = entry_dir / f"{dir_name}-marketplace.xml"
    xml_path.write_text(
        _MODERN_MARKETPLACE_XML_TEMPLATE.format(
            name=canonical_name,
            display_name=display_name,
            version=version,
        )
    )


def _write_legacy_xml(
    repo_specs: pathlib.Path,
    dir_name: str,
    display_name: str,
    version: str,
) -> None:
    """Write a legacy flat *-marketplace.xml lacking <catalog-metadata><name>."""
    entry_dir = repo_specs / dir_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    xml_path = entry_dir / f"{dir_name}-marketplace.xml"
    xml_path.write_text(
        _LEGACY_MARKETPLACE_XML_TEMPLATE.format(
            display_name=display_name,
            version=version,
        )
    )


def _commit_and_tag(work_dir: pathlib.Path, tag: str, message: str) -> None:
    """Stage all changes, commit with message, and apply a lightweight tag."""
    _git(["add", "-A"], cwd=work_dir)
    _git(["commit", "--allow-empty", "-m", message], cwd=work_dir)
    _git(["tag", tag], cwd=work_dir)


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _build_canonical_names_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a bare git repo that mirrors the real catalog's mixed-metadata history.

    Tag structure (oldest to newest):
    - ``1.0.0``: legacy flat-metadata -- directory names are known-bad path components
      (``code-review``, ``idp``); no ``<name>`` element present.
    - ``2.13.0``: modern nested ``<catalog-metadata><name>`` -- canonical names
      (``security-code-review``, ``spec-driven-dev-idp``, ``platform-bootstrap``).
    - ``2.14.0``: modern nested ``<catalog-metadata><name>`` -- same canonical names.

    The test drives ``kanon search`` (plain) and ``kanon search -A/--all`` against this
    fixture and asserts the canonical-name-subset and excluded-name properties.

    Args:
        tmp_path: Temporary directory root provided by pytest.

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    # Tag 1.0.0: legacy flat-metadata versions -- directory names are bad path-components.
    repo_specs = work_dir / "repo-specs"
    for canonical_name, legacy_dir, display_name in _CANONICAL_ENTRIES:
        _write_legacy_xml(repo_specs, legacy_dir, display_name, "1.0.0")
    _commit_and_tag(work_dir, "1.0.0", "release 1.0.0 (legacy flat-metadata)")

    # Tag 2.13.0: modern nested <name> -- canonical entry names.
    for canonical_name, legacy_dir, display_name in _CANONICAL_ENTRIES:
        _write_modern_xml(repo_specs, legacy_dir, canonical_name, display_name, "2.13.0")
    extra_name, extra_display = _EXTRA_CANONICAL_ENTRY
    _write_modern_xml(repo_specs, extra_name, extra_name, extra_display, "2.13.0")
    _commit_and_tag(work_dir, "2.13.0", "release 2.13.0 (canonical nested names)")

    # Tag 2.14.0: modern nested <name> -- same canonical entry names, incremented version.
    for canonical_name, legacy_dir, display_name in _CANONICAL_ENTRIES:
        _write_modern_xml(repo_specs, legacy_dir, canonical_name, display_name, "2.14.0")
    _write_modern_xml(repo_specs, extra_name, extra_name, extra_display, "2.14.0")
    _commit_and_tag(work_dir, "2.14.0", "release 2.14.0 (canonical nested names)")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------


def _run_kanon(
    bare_repo: pathlib.Path,
    extra_args: list[str],
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``kanon search`` with given args against bare_repo and return the process.

    Args:
        bare_repo: Path to the bare git repository.
        extra_args: Arguments appended after ``kanon search``.
        env_overrides: Optional environment variable overrides.

    Returns:
        The completed subprocess result with captured stdout and stderr.
    """
    catalog_source = f"file://{bare_repo}@main"
    cmd = [
        sys.executable,
        "-m",
        "kanon_cli",
        "search",
        "--catalog-source",
        catalog_source,
    ] + extra_args

    env = os.environ.copy()
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(bare_repo.parent),
        env=env,
    )


def _parse_entry_names_from_stdout(stdout: str) -> frozenset[str]:
    """Parse the set of distinct entry names from ``kanon search`` output lines.

    ``kanon search`` prints ``<name>`` per line; ``kanon search -A/--all``
    prints ``<name>@<version>`` per line.  Both formats yield the entry name
    as the part before the first ``@`` (or the entire line when there is no
    ``@``).

    Args:
        stdout: Captured stdout string from a kanon search invocation.

    Returns:
        Frozenset of distinct entry names found in the output.
    """
    names: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        names.add(line.split("@")[0])
    return frozenset(names)


# ---------------------------------------------------------------------------
# New-scheme-only: real old flat-attribute fixture (metadata as ATTRIBUTES on
# <catalog-metadata>, the actual historical catalog format e.g. tag 2.14.0).
# ---------------------------------------------------------------------------

_OLD_FLAT_ATTRIBUTE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata display-name="{display_name}"
                        description="Old flat-attribute integration test entry."
                        version="{version}"
                        type="plugin"
                        owner-name="Integration Tester"
                        owner-email="integration@example.com"
                        keywords="integration,test" />
    </manifest>
""")


def _write_old_flat_xml(
    repo_specs: pathlib.Path,
    dir_name: str,
    display_name: str,
    version: str,
) -> None:
    """Write a real old flat-attribute *-marketplace.xml (metadata as attributes)."""
    entry_dir = repo_specs / dir_name
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / f"{dir_name}-marketplace.xml").write_text(
        _OLD_FLAT_ATTRIBUTE_XML_TEMPLATE.format(display_name=display_name, version=version)
    )


def _build_all_old_scheme_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Bare repo whose ENTIRE tag history is old flat-attribute (zero new-scheme tags).

    Mirrors the real catalog where every release tag (1.3.0-2.14.0) is flat-attribute and
    only the untagged HEAD carries the new nested scheme.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)
    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)
    repo_specs = work_dir / "repo-specs"
    for tag in ("1.3.0", "2.13.0", "2.14.0"):
        for _canonical_name, legacy_dir, display_name in _CANONICAL_ENTRIES:
            _write_old_flat_xml(repo_specs, legacy_dir, display_name, tag)
        _commit_and_tag(work_dir, tag, f"release {tag} (old flat-attribute)")
    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


@pytest.mark.integration
class TestAllVersionsAllOldScheme:
    """New-scheme-only: when EVERY version tag is old flat-attribute (zero new-scheme tags),
    ``kanon search -A/--all`` exits 0 with an empty result + a clear note (NOT exit 1)."""

    def test_all_old_scheme_exits_0_empty_with_note(self, tmp_path: pathlib.Path) -> None:
        bare_repo = _build_all_old_scheme_fixture(tmp_path)
        result = _run_kanon(bare_repo, ["--all", "--no-limit"])
        assert result.returncode == 0, (
            f"expected exit 0 for all-old-scheme history, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert _parse_entry_names_from_stdout(result.stdout) == frozenset(), (
            f"expected empty result for all-old-scheme history.\nstdout: {result.stdout!r}"
        )
        assert "no new-scheme" in result.stderr.lower(), (
            f"expected a 'no new-scheme version tags' note in stderr.\nstderr: {result.stderr!r}"
        )

    def test_all_old_scheme_format_json_exits_0_valid_empty(self, tmp_path: pathlib.Path) -> None:
        import json

        bare_repo = _build_all_old_scheme_fixture(tmp_path)
        result = _run_kanon(bare_repo, ["--all", "--no-limit", "--format", "json"])
        assert result.returncode == 0, f"expected exit 0, got {result.returncode}.\nstderr: {result.stderr!r}"
        parsed = json.loads(result.stdout)
        assert parsed == [], f"expected empty JSON array, got {parsed!r}"

    def test_plain_list_against_old_scheme_is_clean_error_no_traceback(self, tmp_path: pathlib.Path) -> None:
        """Plain ``kanon search`` against an old flat-attribute catalog exits non-zero with a
        clean explicit error (the migration message), NOT a raw Python traceback."""
        bare_repo = _build_all_old_scheme_fixture(tmp_path)
        result = _run_kanon(bare_repo, [])
        assert result.returncode != 0, (
            f"expected non-zero exit for an old-scheme catalog, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "flat-attribute" in combined, f"expected the old-flat-attribute migration error.\n{combined}"
        assert "Traceback" not in combined, (
            f"expected a clean error, not a raw Python traceback.\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Tests: canonical-name-subset and excluded-name properties (AC-1, AC-2, AC-3, AC-14)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsCanonicalNames:
    """FR-1: ``kanon search -A/--all`` must emit only canonical catalog-metadata names.

    AC-1: the set of distinct entry names in ``-A/--all`` output is a subset of the
          names from ``kanon search``.
    AC-2: the ``-A/--all`` output contains none of the known-bad path-component names:
          ``code-review``, ``idp``, ``cli``, ``microservice``.
    AC-3: canonical entries ``security-code-review`` and ``spec-driven-dev-idp`` appear in
          the ``-A/--all`` output.
    AC-13: genuine RED->GREEN is recorded; this test file is the operator-path subprocess test.
    AC-14: ``kanon search --help`` snapshot is unchanged after the fix.
    """

    def test_all_versions_name_set_is_subset_of_plain_list_names(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-1: ``-A/--all`` entry names subset of ``kanon search`` names.

        The fixture has one legacy tag (1.0.0) and two modern tags (2.13.0, 2.14.0).
        Pre-fix: ``-A/--all`` emits ``code-review`` / ``idp`` (from legacy tag),
        which are NOT in ``kanon search`` output (plain list uses only canonical names).
        Post-fix: legacy versions are excluded; all emitted names are canonical and form
        a subset of the plain-list name set.
        """
        bare_repo = _build_canonical_names_fixture(tmp_path)

        plain_result = _run_kanon(bare_repo, [])
        assert plain_result.returncode == 0, (
            f"kanon search failed with exit {plain_result.returncode}.\n"
            f"stdout: {plain_result.stdout!r}\nstderr: {plain_result.stderr!r}"
        )
        plain_names = _parse_entry_names_from_stdout(plain_result.stdout)

        av_result = _run_kanon(bare_repo, ["--all", "--no-limit"])
        assert av_result.returncode == 0, (
            f"kanon search -A/--all failed with exit {av_result.returncode}.\n"
            f"stdout: {av_result.stdout!r}\nstderr: {av_result.stderr!r}"
        )
        av_names = _parse_entry_names_from_stdout(av_result.stdout)

        assert av_names <= plain_names, (
            f"-A/--all name set is NOT a subset of plain-list names.\n"
            f"Names in -A/--all but not in kanon search: {av_names - plain_names!r}\n"
            f"plain_names={plain_names!r}\nav_names={av_names!r}"
        )

    def test_all_versions_excludes_known_bad_path_component_names(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-2: ``-A/--all`` output contains none of the known-bad names.

        Pre-fix: the legacy tag (1.0.0) causes ``code-review`` and ``idp`` to appear.
        Post-fix: legacy versions are excluded; these directory-path-derived names never
        appear in any output row.
        """
        bare_repo = _build_canonical_names_fixture(tmp_path)

        av_result = _run_kanon(bare_repo, ["--all", "--no-limit"])
        assert av_result.returncode == 0, (
            f"kanon search -A/--all failed with exit {av_result.returncode}.\n"
            f"stdout: {av_result.stdout!r}\nstderr: {av_result.stderr!r}"
        )
        av_names = _parse_entry_names_from_stdout(av_result.stdout)

        bad_names_present = av_names & _KNOWN_BAD_NAMES
        assert not bad_names_present, (
            f"-A/--all output contains known-bad path-component names: {bad_names_present!r}.\n"
            f"Full -A/--all stdout:\n{av_result.stdout}"
        )

    def test_all_versions_contains_canonical_entries(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-3: canonical entries ``security-code-review`` and ``spec-driven-dev-idp`` appear.

        The fixture places these at modern tags (2.13.0, 2.14.0) with nested
        ``<catalog-metadata><name>`` values.  After the fix they must appear in the
        ``-A/--all`` output (not their legacy directory-path counterparts).
        """
        bare_repo = _build_canonical_names_fixture(tmp_path)

        av_result = _run_kanon(bare_repo, ["--all", "--no-limit"])
        assert av_result.returncode == 0, (
            f"kanon search -A/--all failed with exit {av_result.returncode}.\n"
            f"stdout: {av_result.stdout!r}\nstderr: {av_result.stderr!r}"
        )

        assert "security-code-review@" in av_result.stdout, (
            f"Expected 'security-code-review' in -A/--all output.\nstdout: {av_result.stdout!r}"
        )
        assert "spec-driven-dev-idp@" in av_result.stdout, (
            f"Expected 'spec-driven-dev-idp' in -A/--all output.\nstdout: {av_result.stdout!r}"
        )

    def test_legacy_versions_excluded_with_skipped_count_note(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """DR-1 / Section 7: legacy flat-metadata versions are excluded with a diagnostic note.

        The fixture has one legacy tag (1.0.0) with 2 legacy entries (``code-review``,
        ``idp``).  After the fix, those 2 legacy XMLs are excluded and a single diagnostic
        line is emitted to stderr noting the count of skipped legacy-metadata versions.
        No corresponding rows appear in stdout.
        """
        bare_repo = _build_canonical_names_fixture(tmp_path)

        av_result = _run_kanon(bare_repo, ["--all", "--no-limit"])
        assert av_result.returncode == 0, (
            f"kanon search -A/--all failed with exit {av_result.returncode}.\n"
            f"stdout: {av_result.stdout!r}\nstderr: {av_result.stderr!r}"
        )

        # Verify no legacy directory-path names appear in stdout as standalone entry names.
        # Parse entry names from the output to avoid substring false positives
        # (e.g. "security-code-review" contains "code-review" as a substring).
        av_names = _parse_entry_names_from_stdout(av_result.stdout)
        for bad_name in _KNOWN_BAD_NAMES:
            assert bad_name not in av_names, (
                f"Known-bad name '{bad_name}' found as an entry name in -A/--all stdout.\n"
                f"av_names={av_names!r}\nstdout: {av_result.stdout!r}"
            )

        # A diagnostic note about skipped legacy-metadata versions must appear in stderr.
        assert "skipped" in av_result.stderr.lower(), (
            f"Expected a 'skipped' diagnostic note in stderr for legacy-metadata versions.\n"
            f"stderr: {av_result.stderr!r}"
        )

    def test_help_text_unchanged(self) -> None:
        """AC-14: ``kanon search --help`` snapshot is unchanged after the fix.

        The help text documents the surface contract; any accidental drift in flags,
        defaults, or description text is a regression.
        """
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "search", "--help"],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, (
            f"kanon search --help failed with exit {result.returncode}.\nstderr: {result.stderr!r}"
        )

        help_text = result.stdout

        # Verify key surface contracts are present (flag names, positional argument).
        expected_fragments = [
            "--all",
            "--catalog-source",
            "--limit N",
            "--no-limit",
            "--since-version",
            "--format",
            "--detail",
            "--tree",
            "kanon search",
        ]
        for fragment in expected_fragments:
            assert fragment in help_text, (
                f"Expected '{fragment}' in 'kanon search --help' output.\nhelp_text:\n{help_text}"
            )
