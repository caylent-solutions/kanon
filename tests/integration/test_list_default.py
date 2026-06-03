"""Integration tests for the default output mode of 'kanon list'.

Builds a temporary local file:// manifest-repo fixture (committed git repo
with *-marketplace.xml files) and invokes 'kanon list --catalog-source
<file>@<ref>' via subprocess.run.

Covers:
- Happy path: three XML files, exit 0, stdout sorted names, no error in stderr.
- Empty-catalog path: zero XML files, exit 0, empty stdout, stderr note.
- Missing-catalog-source path: no flag, no env var, exit non-zero, stderr error.
- KANON_CATALOG_SOURCE env var path: no flag, env var set, exit 0, sorted names.

AC-TEST-002, AC-TEST-003, AC-CYCLE-001
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

# Minimal *-marketplace.xml for a named entry. Owner fields included to avoid
# recommended-field warnings polluting stderr assertions.
_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


# ---------------------------------------------------------------------------
# Low-level git helpers (independent copies, not imported from other tests)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path.

    Args:
        work_dir: Non-bare working directory to clone from.
        bare_dir: Destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Fixture: manifest repo with marketplace XML files
# ---------------------------------------------------------------------------


def _create_manifest_repo(
    base: pathlib.Path,
    entry_names: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo with *-marketplace.xml files under repo-specs/.

    The repo-specs/ directory follows the structure that 'kanon list' reads.
    Each entry in entry_names gets its own <name>-marketplace.xml.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_names: Catalog entry names. Each gets a marketplace XML.

    Returns:
        The file:// URL (without the scheme) pointing at the bare repo.
        Callers prepend 'file://' and append '@main' for catalog-source.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()

    # Git does not track empty directories; a .gitkeep ensures the directory
    # is always committed even when entry_names is empty.
    (repo_specs_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir


def _create_manifest_repo_with_legacy_catalog(
    base: pathlib.Path,
    entry_names: list[str],
    legacy_names: list[str],
) -> pathlib.Path:
    """Create a manifest repo that has BOTH repo-specs/ and a legacy catalog/ dir.

    The legacy catalog/ directory contains XML files that must NOT appear in
    'kanon list' output per spec Section 4.1.

    Args:
        base: Parent directory.
        entry_names: Names in repo-specs/ (should appear in output).
        legacy_names: Names in catalog/<n>/ (must NOT appear in output).

    Returns:
        The absolute path to the bare repo.
    """
    work_dir = base / "manifest-legacy-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    # Legacy catalog directory -- must NOT be read by kanon list
    for name in legacy_names:
        legacy_dir = work_dir / "catalog" / name
        legacy_dir.mkdir(parents=True, exist_ok=True)
        xml_path = legacy_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add entries and legacy catalog"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-legacy-bare.git")


# ---------------------------------------------------------------------------
# Subprocess runner for kanon
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Uses sys.executable -m kanon_cli so no separate installation is needed.
    The base env inherits os.environ; extra_env values are overlaid on top.

    Args:
        args: Arguments to pass after 'kanon' (e.g. ["list", "--catalog-source", ...]).
        extra_env: Extra environment variables to set (merged onto os.environ).

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Integration test: happy path -- three entries
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDefaultHappyPath:
    """kanon list with three marketplace XMLs: exit 0, sorted names, clean stderr."""

    def test_exits_0(self, tmp_path: pathlib.Path) -> None:
        """kanon list exits 0 when catalog has three entries."""
        bare = _create_manifest_repo(tmp_path, ["gamma", "alpha", "beta"])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_stdout_contains_three_sorted_entry_names(self, tmp_path: pathlib.Path) -> None:
        """kanon list stdout lists the three entry names sorted lexicographically."""
        bare = _create_manifest_repo(tmp_path, ["gamma", "alpha", "beta"])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        lines = result.stdout.strip().splitlines()
        assert lines == ["alpha", "beta", "gamma"], (
            f"Expected ['alpha', 'beta', 'gamma']; got {lines!r}.\n  stderr: {result.stderr!r}"
        )

    def test_stderr_has_no_error_lines(self, tmp_path: pathlib.Path) -> None:
        """kanon list writes no ERROR: lines to stderr on happy path."""
        bare = _create_manifest_repo(tmp_path, ["gamma", "alpha", "beta"])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "ERROR:" not in result.stderr, f"Unexpected ERROR in stderr: {result.stderr!r}"

    def test_env_var_sets_catalog_source(self, tmp_path: pathlib.Path) -> None:
        """KANON_CATALOG_SOURCE env var (no CLI flag) selects the catalog source.

        AC-CYCLE-001: run kanon list with KANON_CATALOG_SOURCE set (no flag).
        """
        bare = _create_manifest_repo(tmp_path, ["gamma", "alpha", "beta"])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list"],  # No --catalog-source flag
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with KANON_CATALOG_SOURCE set; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        lines = result.stdout.strip().splitlines()
        assert lines == ["alpha", "beta", "gamma"], f"Expected sorted names via env var; got {lines!r}"

    def test_catalog_source_flag_wins_over_env_var(self, tmp_path: pathlib.Path) -> None:
        """CLI --catalog-source takes precedence over KANON_CATALOG_SOURCE env var."""
        # Create two repos: one with "correct" entry, one with "wrong" entry.
        bare_correct = _create_manifest_repo(tmp_path / "correct", ["correct-entry"])
        bare_wrong = _create_manifest_repo(tmp_path / "wrong", ["wrong-entry"])

        result = _run_kanon(
            ["list", "--catalog-source", f"file://{bare_correct}@main"],
            extra_env={
                "KANON_CATALOG_SOURCE": f"file://{bare_wrong}@main",
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )
        assert result.returncode == 0
        assert "correct-entry" in result.stdout
        assert "wrong-entry" not in result.stdout


# ---------------------------------------------------------------------------
# Integration test: empty catalog
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDefaultEmptyCatalog:
    """kanon list with zero marketplace XMLs: exit 0, empty stdout, stderr note."""

    def test_exits_0_for_empty_catalog(self, tmp_path: pathlib.Path) -> None:
        """kanon list exits 0 when the manifest repo has zero marketplace XMLs."""
        bare = _create_manifest_repo(tmp_path, [])  # No entries
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for empty catalog; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_stdout_empty_for_empty_catalog(self, tmp_path: pathlib.Path) -> None:
        """kanon list stdout is empty when the manifest repo has zero entries."""
        bare = _create_manifest_repo(tmp_path, [])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.stdout.strip() == "", f"Expected empty stdout for empty catalog; got {result.stdout!r}"

    def test_stderr_note_for_empty_catalog(self, tmp_path: pathlib.Path) -> None:
        """kanon list writes 'manifest repo contains 0 entries' to stderr."""
        bare = _create_manifest_repo(tmp_path, [])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "manifest repo contains 0 entries" in result.stderr, (
            f"Expected '0 entries' note in stderr; got {result.stderr!r}"
        )

    def test_empty_catalog_via_env_var(self, tmp_path: pathlib.Path) -> None:
        """Empty catalog path also works via KANON_CATALOG_SOURCE env var."""
        bare = _create_manifest_repo(tmp_path, [])
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list"],
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )
        assert result.returncode == 0
        assert "manifest repo contains 0 entries" in result.stderr


# ---------------------------------------------------------------------------
# Integration test: missing catalog source
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDefaultMissingCatalogSource:
    """kanon list with no --catalog-source and no env var: exit non-zero, error on stderr."""

    def test_exits_nonzero_when_no_source(self) -> None:
        """kanon list exits non-zero when neither flag nor env var is set."""
        # Remove KANON_CATALOG_SOURCE from the environment
        clean_env = {k: v for k, v in os.environ.items() if k != "KANON_CATALOG_SOURCE"}

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "list"],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit when no catalog source; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_stderr_contains_error_when_no_source(self) -> None:
        """kanon list writes an ERROR: line to stderr when no source is set."""
        clean_env = {k: v for k, v in os.environ.items() if k != "KANON_CATALOG_SOURCE"}

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "list"],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert "ERROR:" in result.stderr, f"Expected 'ERROR:' in stderr; got {result.stderr!r}"

    def test_stdout_empty_when_no_source(self) -> None:
        """kanon list writes nothing to stdout when no catalog source is set."""
        clean_env = {k: v for k, v in os.environ.items() if k != "KANON_CATALOG_SOURCE"}

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "list"],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert result.stdout == "", f"Expected empty stdout when no catalog source; got {result.stdout!r}"

    def test_error_mentions_catalog_source_flag(self) -> None:
        """kanon list error text mentions --catalog-source."""
        clean_env = {k: v for k, v in os.environ.items() if k != "KANON_CATALOG_SOURCE"}

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "list"],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert "--catalog-source" in result.stderr, f"Expected '--catalog-source' hint in stderr; got {result.stderr!r}"


# ---------------------------------------------------------------------------
# Integration test: legacy catalog/ directory is ignored
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListLegacyCatalogIgnored:
    """kanon list reads ONLY repo-specs/ and ignores the legacy catalog/ directory."""

    def test_legacy_catalog_entries_not_in_output(self, tmp_path: pathlib.Path) -> None:
        """Entries in catalog/<name>/ do NOT appear in 'kanon list' output."""
        bare = _create_manifest_repo_with_legacy_catalog(
            tmp_path,
            entry_names=["modern-entry"],
            legacy_names=["legacy-entry"],
        )
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0
        assert "modern-entry" in result.stdout
        assert "legacy-entry" not in result.stdout, f"Legacy catalog entry leaked into output: {result.stdout!r}"
