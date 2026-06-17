"""Integration tests for branch-pinned 'kanon outdated' drift detection.

Builds real file:// fixture git repos with a ``main`` branch that advances
from an older commit (SHA A) to a newer commit (SHA B), writes a .kanon.lock
pinning the source to SHA A, and asserts that 'kanon outdated' emits a row
with:

  current=<A-12-char>, latest-matching-spec=<B-12-char>,
  latest-available=<B-12-char>, upgrade-type=drift

AC-TEST-002, AC-CYCLE-001
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Minimal .kanon file content for a branch-pinned source.
# {name_upper} -- uppercased source name for env-var key
# {name_lower} -- lowercased source name for path
# {url} -- file:// URL to the bare project repo
# {revision} -- branch name (e.g. "main")
_KANON_BRANCH_TEMPLATE = textwrap.dedent("""\
    GITBASE=file:///unused
    CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=false
    KANON_SOURCE_{name_upper}_URL={url}
    KANON_SOURCE_{name_upper}_REVISION={revision}
    KANON_SOURCE_{name_upper}_PATH=./{name_lower}
""")


# ---------------------------------------------------------------------------
# Git helpers
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


def _git_output(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command in cwd and return stdout, raising RuntimeError on failure."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")
    return result.stdout.strip()


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _create_project_repo_with_two_commits(
    base: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, str, str]:
    """Create a bare project repo with a ``main`` branch at two commits.

    Returns (bare_path, sha_a, sha_b) where sha_a is the first commit and
    sha_b is the second (HEAD). Both SHAs are full 40-character hex strings.

    Args:
        base: Parent directory for the work and bare repos.
        name: Name used for directory naming.

    Returns:
        A tuple of (bare_path, sha_a, sha_b).
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    # First commit -- SHA A
    (work_dir / "README.md").write_text(f"# {name} initial\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    sha_a = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    # Second commit -- SHA B (HEAD)
    (work_dir / "README.md").write_text(f"# {name} second\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Second commit"], cwd=work_dir)
    sha_b = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{name}-bare.git")
    return bare_dir.resolve(), sha_a, sha_b


def _create_manifest_repo(
    base: pathlib.Path,
    entry_name: str,
) -> pathlib.Path:
    """Create a bare manifest (catalog) repo with one marketplace XML.

    The marketplace XML format is required for the catalog resolver to accept
    the repo. The 'kanon outdated' command only needs the catalog for
    validation of the --catalog-source argument; the actual tag resolution for
    branch-pinned sources uses git ls-remote directly, not the catalog.

    Args:
        base: Parent directory for the repo.
        entry_name: Name of the catalog entry.

    Returns:
        Absolute path to the bare manifest repo.
    """
    xml_content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <manifest>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>{entry_name} Display</display-name>
            <description>Integration test entry for {entry_name}.</description>
            <version>1.0.0</version>
            <type>plugin</type>
            <owner-name>Integration Tester</owner-name>
            <owner-email>integration@example.com</owner-email>
            <keywords>integration, test</keywords>
          </catalog-metadata>
        </manifest>
    """)

    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")
    (repo_specs_dir / f"{entry_name}-marketplace.xml").write_text(xml_content)

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entry"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the same Python interpreter."""
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCE", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOutdatedBranchDrift:
    """End-to-end tests for branch-pinned 'kanon outdated' drift detection.

    AC-TEST-002, AC-CYCLE-001
    """

    def test_branch_pinned_drift_row(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: full cycle -- SHA A in lockfile, HEAD at SHA B, expect drift.

        Build a fixture project repo with a ``main`` branch advancing from
        commit SHA A to SHA B. Write a lockfile pinning the source to SHA A.
        Assert that 'kanon outdated' emits one row with:
          current=<A-12>, latest-matching-spec=<B-12>, latest-available=<B-12>,
          upgrade-type=drift.
        Assert exit code 0.
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare, sha_a, sha_b = _create_project_repo_with_two_commits(project_base, "mylib")
        project_url = f"file://{project_bare}"

        sha_a_12 = sha_a[:12]
        sha_b_12 = sha_b[:12]

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, "mylib")
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_BRANCH_TEMPLATE.format(
                name_upper="MYLIB",
                name_lower="mylib",
                url=project_url,
                revision="main",
            )
        )
        kanon_file.chmod(0o644)

        # Write a lockfile with SHA A (the older commit)
        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "MYLIB"\n'
            'name = "MYLIB"\n'
            f"url = {project_url!r}\n"
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{sha_a}"\n'
            'path = "./mylib"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "MYLIB" in result.stdout, f"Expected source name 'MYLIB' in output:\n{result.stdout}"
        assert sha_a_12 in result.stdout, f"Expected current={sha_a_12!r} (locked old SHA) in output:\n{result.stdout}"
        assert sha_b_12 in result.stdout, (
            f"Expected latest-matching-spec={sha_b_12!r} (HEAD SHA) in output:\n{result.stdout}"
        )
        assert "drift" in result.stdout, f"Expected upgrade-type=drift in output:\n{result.stdout}"

    def test_branch_pinned_no_drift_row(self, tmp_path: pathlib.Path) -> None:
        """Branch-pinned source where locked SHA equals HEAD -> upgrade-type=none.

        AC-FUNC-003: locked SHA == branch HEAD.
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare, _sha_a, sha_b = _create_project_repo_with_two_commits(project_base, "stable")
        project_url = f"file://{project_bare}"

        sha_b_12 = sha_b[:12]

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, "stable")
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_BRANCH_TEMPLATE.format(
                name_upper="STABLE",
                name_lower="stable",
                url=project_url,
                revision="main",
            )
        )
        kanon_file.chmod(0o644)

        # Write lockfile with the current HEAD SHA (no drift)
        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "STABLE"\n'
            'name = "STABLE"\n'
            f"url = {project_url!r}\n"
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{sha_b}"\n'
            'path = "./stable"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert sha_b_12 in result.stdout, f"Expected HEAD SHA {sha_b_12!r} in output:\n{result.stdout}"
        assert "none" in result.stdout, f"Expected upgrade-type=none in output:\n{result.stdout}"
        assert "drift" not in result.stdout, f"Expected no drift when locked SHA == HEAD:\n{result.stdout}"

    def test_branch_pinned_no_lockfile_live_resolve(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-003: no lockfile -- current is live-resolved HEAD, upgrade-type=none."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare, _sha_a, sha_b = _create_project_repo_with_two_commits(project_base, "fresh")
        project_url = f"file://{project_bare}"

        sha_b_12 = sha_b[:12]

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, "fresh")
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_BRANCH_TEMPLATE.format(
                name_upper="FRESH",
                name_lower="fresh",
                url=project_url,
                revision="main",
            )
        )
        kanon_file.chmod(0o644)

        # No lockfile -- live resolve should pick current HEAD
        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert sha_b_12 in result.stdout, f"Expected HEAD SHA {sha_b_12!r} (live-resolved) in output:\n{result.stdout}"
        assert "none" in result.stdout, f"Expected upgrade-type=none for no-lockfile branch-pinned:\n{result.stdout}"

    def test_latest_matching_spec_equals_latest_available_for_branch(self, tmp_path: pathlib.Path) -> None:
        """For branch-pinned sources, latest-matching-spec == latest-available (spec Section 4.4)."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare, sha_a, sha_b = _create_project_repo_with_two_commits(project_base, "equal")
        project_url = f"file://{project_bare}"
        sha_b_12 = sha_b[:12]

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, "equal")
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_BRANCH_TEMPLATE.format(
                name_upper="EQUAL",
                name_lower="equal",
                url=project_url,
                revision="main",
            )
        )
        kanon_file.chmod(0o644)

        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "EQUAL"\n'
            'name = "EQUAL"\n'
            f"url = {project_url!r}\n"
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{sha_a}"\n'
            'path = "./equal"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # Both latest-matching-spec and latest-available must be the same HEAD SHA
        # Count occurrences of sha_b_12 -- should appear at least twice (both columns)
        count = result.stdout.count(sha_b_12)
        assert count >= 2, (
            f"Expected {sha_b_12!r} to appear in both latest-matching-spec and "
            f"latest-available columns (at least 2 times), got {count} occurrences.\n"
            f"Output:\n{result.stdout}"
        )
