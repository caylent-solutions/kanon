"""Lifecycle integration test for repo_sync().

AC-CYCLE-001: After repo_init() (via run_from_args) + repo_sync(), project
files are present in the workspace directory.

AC-CYCLE-002 (E0-F7-S1-T2): After consolidation of version_constraints.py to
delegate to kanon_cli.version, the full lifecycle with a PEP 440 version
constraint in the manifest revision still works end-to-end.

This test creates real local bare git repositories and runs the full
init + sync cycle using the kanon_cli.repo public API.
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
    declares a single project named 'content-repo' at path 'content-repo'.

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


def _create_versioned_content_repo(base: pathlib.Path, versions: list[str]) -> pathlib.Path:
    """Create a bare git repository with multiple tagged commits.

    Creates one commit per version in ``versions``, tagging each commit with
    ``refs/tags/<version>`` (a lightweight tag).

    Returns the path to the bare repository (used as the fetch URL).

    Args:
        base: Parent directory to create the repository in.
        versions: List of version strings (e.g., ['1.0.0', '1.1.0', '2.0.0']).

    Returns:
        Path to the bare git repository directory.
    """
    work_dir = base / "versioned-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", "test@example.com"], cwd=work_dir)
    _git(["config", "user.name", "Test"], cwd=work_dir)

    for version in versions:
        version_file = work_dir / "VERSION"
        version_file.write_text(f"{version}\n", encoding="utf-8")
        _git(["add", "VERSION"], cwd=work_dir)
        _git(["commit", "-m", f"Release {version}"], cwd=work_dir)
        _git(["tag", version], cwd=work_dir)

    bare_dir = base / "versioned-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir


def _create_manifest_repo_with_version_constraint(
    base: pathlib.Path,
    content_fetch_url: str,
    project_name: str,
    revision: str,
) -> pathlib.Path:
    """Create a bare manifest repo referencing a project with a version constraint.

    Args:
        base: Parent directory to create the manifest repository in.
        content_fetch_url: The fetch base URL for the remote in the manifest.
        project_name: The project name (bare repo directory name) used in the manifest.
        revision: The revision expression for the project (e.g., 'refs/tags/~=1.0.0').

    Returns:
        Path to the bare manifest git repository directory.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{content_fetch_url}" />\n'
        '  <default remote="origin" />\n'
        f'  <project name="{project_name}" path="project" revision="{revision}" />\n'
        "</manifest>\n"
    )

    work_dir = base / "vc-manifest-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", "test@example.com"], cwd=work_dir)
    _git(["config", "user.name", "Test"], cwd=work_dir)

    (work_dir / "default.xml").write_text(manifest_xml, encoding="utf-8")
    _git(["add", "default.xml"], cwd=work_dir)
    _git(["commit", "-m", "Add manifest with version constraint"], cwd=work_dir)

    bare_dir = base / "vc-manifest-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir


# ---------------------------------------------------------------------------
# AC-CYCLE-001
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_repo_init_then_sync_clones_project(tmp_path: pathlib.Path) -> None:
    """AC-CYCLE-001: repo_init() then repo_sync() clones projects from manifest.

    Creates a local file:// manifest repo and a local file:// content repo,
    runs repo init via run_from_args(), then calls repo_sync(). Verifies that
    the project directory exists under the workspace root after sync.
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

    # Run repo sync via the public API.
    repo_pkg.repo_sync(repo_dir=str(workspace))

    # Verify the project directory was created by repo sync.
    project_dir = workspace / "content-repo"
    assert project_dir.is_dir(), (
        f"Expected project directory {project_dir} to exist after repo_sync(), "
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


# ---------------------------------------------------------------------------
# AC-CYCLE-002 (E0-F7-S1-T2): version constraint lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_version_constraint_lifecycle_selects_correct_tag(tmp_path: pathlib.Path) -> None:
    """AC-CYCLE-001 (E0-F7-S1-T2): Full lifecycle with PEP 440 version constraint.

    After consolidating version_constraints.py to delegate to kanon_cli.version,
    verifies that the full repo_init -> repo_sync cycle with a version constraint
    in the manifest revision attribute correctly resolves and checks out the
    highest matching tag.

    Creates:
    - A content repo with tagged commits 1.0.0, 1.1.0, 2.0.0
    - A manifest referencing the content repo with revision='refs/tags/~=1.1'

    The ~=1.1 (two-part compatible release) constraint is equivalent to >=1.1, ==1.*,
    which matches 1.1.0 but not 2.0.0. The highest matching version is 1.1.0,
    so that tag should be checked out.

    After sync, the project directory must exist and contain the VERSION file
    with the content '1.1.0', confirming that the correct tag was checked out.
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    versions = ["1.0.0", "1.1.0", "2.0.0"]
    bare_dir = _create_versioned_content_repo(repos_base, versions)

    # The fetch URL in the manifest is the parent of the bare repo directory
    # so that repo can compose the clone URL as fetch + project_name.
    fetch_base = f"file://{repos_base}"
    project_name = bare_dir.name  # "versioned-bare"

    manifest_bare = _create_manifest_repo_with_version_constraint(
        repos_base,
        content_fetch_url=fetch_base,
        project_name=project_name,
        revision="refs/tags/~=1.1",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    manifest_url = f"file://{manifest_bare}"
    repo_dot_dir = str(workspace / ".repo")

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

    assert (workspace / ".repo").is_dir(), (
        f"Expected .repo/ directory after repo init, but it was not created at {workspace / '.repo'}"
    )

    repo_pkg.repo_sync(repo_dir=str(workspace))

    project_dir = workspace / "project"
    assert project_dir.is_dir(), (
        f"Expected project directory {project_dir} to exist after repo_sync() with version constraint, "
        f"but it was not created. Workspace contents: {list(workspace.iterdir())!r}"
    )

    version_file = project_dir / "VERSION"
    assert version_file.is_file(), (
        f"Expected VERSION file at {version_file} to exist after sync, "
        f"but it was not found. Project contents: {list(project_dir.iterdir())!r}"
    )

    checked_out_version = version_file.read_text(encoding="utf-8").strip()
    assert checked_out_version == "1.1.0", (
        f"Expected constraint 'refs/tags/~=1.1' to resolve to tag '1.1.0', "
        f"but the checked-out VERSION file contains '{checked_out_version}'. "
        f"This indicates version constraint delegation from version_constraints.py "
        f"to kanon_cli.version did not produce the correct result."
    )
