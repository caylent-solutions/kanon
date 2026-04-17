"""Lifecycle integration test for repo_run().

AC-CYCLE-001: After repo_init() (via run_from_args) + repo_run(["sync"]),
project files are present in the workspace directory.

This test creates a pair of real local bare git repositories:
  - A manifest repo containing a default.xml that references a content repo
    via a file:// URL.
  - A content repo with a committed file.

It then runs the full init + sync cycle using repo_run() for the sync step
and verifies that the project directory is created under the workspace root.
"""

import pathlib
import subprocess

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo.main import run_from_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _create_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repository with one committed file.

    Returns the path to the bare repository (used as the fetch URL).
    """
    work_dir = base / "content-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", "test@example.com"], cwd=work_dir)
    _git(["config", "user.name", "Test"], cwd=work_dir)

    readme = work_dir / "README.md"
    readme.write_text("# content-repo\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    bare_dir = base / "content-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir


def _create_manifest_repo(base: pathlib.Path, content_fetch_url: str) -> pathlib.Path:
    """Create a bare git repository containing a manifest XML.

    The manifest references content_fetch_url as the remote fetch base and
    declares a single project named 'content-bare' at path 'content-repo'.

    Returns the path to the bare manifest repository.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{content_fetch_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="content-bare" path="content-repo" />\n'
        "</manifest>\n"
    )

    work_dir = base / "manifest-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", "test@example.com"], cwd=work_dir)
    _git(["config", "user.name", "Test"], cwd=work_dir)

    (work_dir / "default.xml").write_text(manifest_xml, encoding="utf-8")
    _git(["add", "default.xml"], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / "manifest-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir


# ---------------------------------------------------------------------------
# AC-CYCLE-001
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_repo_init_then_repo_run_sync_clones_project(tmp_path: pathlib.Path) -> None:
    """AC-CYCLE-001: repo_init() then repo_run(dir, ["sync"]) clones projects from manifest.

    Creates a local file:// manifest repo and a local file:// content repo,
    runs repo init via run_from_args(), then calls repo_run() with ["sync"].
    Verifies that the project directory exists under the workspace root after
    the sync and that the committed file from the content repo is present.
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base)
    # The manifest fetch URL is the parent directory of the bare repo.
    # repo uses fetch + project name to compose the clone URL, so the
    # fetch base must be the directory containing the bare repo directory.
    fetch_base = f"file://{repos_base}"
    manifest_bare = _create_manifest_repo(repos_base, fetch_base)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    manifest_url = f"file://{manifest_bare}"
    repo_dot_dir = str(workspace / ".repo")

    # Run repo init to set up the .repo directory.
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            "default.xml",
        ],
        repo_dir=repo_dot_dir,
    )

    repo_dot_path = workspace / ".repo"
    assert repo_dot_path.is_dir(), (
        f"Expected .repo/ directory at {repo_dot_path} after repo init, but it was not created."
    )

    # Run repo sync via repo_run() -- this is the AC-CYCLE-001 requirement.
    exit_code = repo_pkg.repo_run(["sync"], repo_dir=repo_dot_dir)

    assert exit_code == 0, f"repo_run(['sync'], repo_dir=...) must return 0 on success, got {exit_code!r}"

    # Verify the project directory was created by repo sync.
    project_dir = workspace / "content-repo"
    assert project_dir.is_dir(), (
        f"Expected project directory {project_dir} to exist after repo_run(['sync']), "
        f"but it was not created. "
        f"Workspace contents: {list(workspace.iterdir())!r}"
    )

    # Verify the committed file from the content repo is present.
    readme = project_dir / "README.md"
    assert readme.is_file(), (
        f"Expected {readme} to exist inside the cloned project directory, "
        f"but it was not found. "
        f"Project directory contents: {list(project_dir.iterdir())!r}"
    )
    readme_content = readme.read_text(encoding="utf-8")
    assert "content-repo" in readme_content, (
        f"Expected 'content-repo' to appear in {readme} but got: {readme_content!r}"
    )
