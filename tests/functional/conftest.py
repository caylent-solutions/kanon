"""Shared fixtures for functional tests.

Provides session-scoped infrastructure required for end-to-end CLI tests,
including a minimal .repo directory that satisfies the embedded repo tool's
version subcommand requirements, and a shared subprocess helper for invoking
the kanon CLI.

Also provides shared git helper functions used by multiple happy-path test
modules:

- :func:`_init_git_work_dir` -- initialise a working git repo with user config.
- :func:`_clone_as_bare` -- clone a working repo into a bare repo.
- :func:`_create_bare_content_repo` -- create a bare repo with one committed file.
- :func:`_create_manifest_repo` -- create a bare manifest repo pointing at a
  content repo.
- :func:`_setup_synced_repo` -- run ``kanon repo init`` + ``kanon repo sync``
  and return ``(checkout_dir, repo_dir)``.
- :func:`_git_branch_list` -- return a list of local branch names in a git
  working directory.
"""

import os
import subprocess
import sys
import pathlib
from typing import Union

import pytest

# ---------------------------------------------------------------------------
# Default values for the shared git helpers.  Consumer test modules supply
# their own constants via keyword arguments to keep test isolation.
# ---------------------------------------------------------------------------

_DEFAULT_GIT_USER_NAME = "Shared Helper Test User"
_DEFAULT_GIT_USER_EMAIL = "shared-helper@example.com"
_DEFAULT_PROJECT_NAME = "content-bare"
_DEFAULT_PROJECT_PATH = "shared-test-project"
_DEFAULT_MANIFEST_FILENAME = "default.xml"
_DEFAULT_CONTENT_FILE_NAME = "README.md"
_DEFAULT_CONTENT_FILE_TEXT = "hello from shared conftest helper"
_DEFAULT_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"
_DEFAULT_GIT_BRANCH = "main"


def _run_kanon(
    *args: str,
    cwd: Union[pathlib.Path, str, None] = None,
    env: "dict[str, str] | None" = None,
    extra_env: "dict | None" = None,
) -> subprocess.CompletedProcess:
    """Invoke kanon_cli in a subprocess and return the completed process.

    Executes ``python -m kanon_cli`` with the supplied arguments.

    Args:
        *args: CLI arguments passed after ``python -m kanon_cli``.
        cwd: Working directory for the subprocess. Accepts a :class:`pathlib.Path`
            or a plain string. Defaults to ``None`` (inherits the caller's cwd).
        env: Full replacement environment for the subprocess. When provided,
            the subprocess receives exactly this dict rather than inheriting the
            parent environment. Mutually exclusive with ``extra_env``.
        extra_env: Additional environment variables merged on top of the current
            :data:`os.environ`. Mutually exclusive with ``env``.

    Returns:
        The :class:`subprocess.CompletedProcess` object from :func:`subprocess.run`
        (``check=False``).

    Raises:
        ValueError: When both ``env`` and ``extra_env`` are provided at once.
    """
    if env is not None and extra_env is not None:
        raise ValueError("Provide either 'env' or 'extra_env', not both.")

    resolved_env: "dict[str, str] | None"
    if env is not None:
        resolved_env = env
    elif extra_env is not None:
        resolved_env = dict(os.environ)
        resolved_env.update(extra_env)
    else:
        resolved_env = None

    resolved_cwd: "str | None" = str(cwd) if cwd is not None else None

    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=resolved_cwd,
        env=resolved_env,
    )


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _git_branch_list(project_dir: pathlib.Path) -> list[str]:
    """Return a list of local branch names in project_dir.

    Runs ``git branch`` in project_dir and parses the output into a flat list
    of branch names (stripping the leading ``*`` and whitespace from git output).
    Git status indicators enclosed in parentheses (e.g. ``(no branch)``,
    ``(HEAD detached at <hash>)``) are excluded because they are not real branch
    names.

    Args:
        project_dir: Path to a git working directory.

    Returns:
        A list of local branch name strings. Empty when no real branches exist.

    Raises:
        RuntimeError: When git exits with a non-zero code.
    """
    result = subprocess.run(
        ["git", "branch"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git branch failed in {project_dir!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    branches = []
    for line in result.stdout.splitlines():
        name = line.strip().lstrip("* ")
        if name and not name.startswith("("):
            branches.append(name)
    return branches


def _init_git_work_dir(
    work_dir: pathlib.Path,
    *,
    git_user_name: str = _DEFAULT_GIT_USER_NAME,
    git_user_email: str = _DEFAULT_GIT_USER_EMAIL,
    branch: str = _DEFAULT_GIT_BRANCH,
) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
        git_user_name: Git ``user.name`` config value.
        git_user_email: Git ``user.email`` config value.
        branch: Initial branch name (default ``"main"``).
    """
    _git(["init", "-b", branch], cwd=work_dir)
    _git(["config", "user.name", git_user_name], cwd=work_dir)
    _git(["config", "user.email", git_user_email], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir and return the resolved bare_dir path.

    Args:
        work_dir: The source non-bare working directory.
        bare_dir: The destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_content_repo(
    base: pathlib.Path,
    *,
    git_user_name: str = _DEFAULT_GIT_USER_NAME,
    git_user_email: str = _DEFAULT_GIT_USER_EMAIL,
    project_name: str = _DEFAULT_PROJECT_NAME,
    content_file_name: str = _DEFAULT_CONTENT_FILE_NAME,
    content_file_text: str = _DEFAULT_CONTENT_FILE_TEXT,
) -> pathlib.Path:
    """Create a bare git repo containing one committed file.

    Args:
        base: Parent directory under which repos are created.
        git_user_name: Git ``user.name`` for commits.
        git_user_email: Git ``user.email`` for commits.
        project_name: Base name for the bare repo directory (``<project_name>.git``).
        content_file_name: File name for the committed content file.
        content_file_text: Text written to the content file.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir, git_user_name=git_user_name, git_user_email=git_user_email)

    readme = work_dir / content_file_name
    readme.write_text(content_file_text, encoding="utf-8")
    _git(["add", content_file_name], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / f"{project_name}.git")


def _create_manifest_repo(
    base: pathlib.Path,
    fetch_base: str,
    *,
    git_user_name: str = _DEFAULT_GIT_USER_NAME,
    git_user_email: str = _DEFAULT_GIT_USER_EMAIL,
    project_name: str = _DEFAULT_PROJECT_NAME,
    project_path: str = _DEFAULT_PROJECT_PATH,
    manifest_filename: str = _DEFAULT_MANIFEST_FILENAME,
    manifest_bare_dir_name: str = _DEFAULT_MANIFEST_BARE_DIR_NAME,
    branch: str = _DEFAULT_GIT_BRANCH,
) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: The fetch base URL for the remote element in the manifest.
        git_user_name: Git ``user.name`` for commits.
        git_user_email: Git ``user.email`` for commits.
        project_name: Project name in the manifest ``<project>`` element.
        project_path: Project path in the manifest ``<project>`` element.
        manifest_filename: File name for the manifest XML file.
        manifest_bare_dir_name: Directory name for the bare manifest clone.
        branch: Default revision branch in the manifest.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir, git_user_name=git_user_name, git_user_email=git_user_email)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        f'  <default revision="{branch}" remote="local" />\n'
        f'  <project name="{project_name}" path="{project_path}" />\n'
        "</manifest>\n"
    )
    (work_dir / manifest_filename).write_text(manifest_xml, encoding="utf-8")
    _git(["add", manifest_filename], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / manifest_bare_dir_name)


def _setup_synced_repo(
    tmp_path: pathlib.Path,
    *,
    git_user_name: str = _DEFAULT_GIT_USER_NAME,
    git_user_email: str = _DEFAULT_GIT_USER_EMAIL,
    project_name: str = _DEFAULT_PROJECT_NAME,
    project_path: str = _DEFAULT_PROJECT_PATH,
    manifest_filename: str = _DEFAULT_MANIFEST_FILENAME,
    branch: str = _DEFAULT_GIT_BRANCH,
) -> "tuple[pathlib.Path, pathlib.Path]":
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Runs ``kanon repo init`` followed by ``kanon repo sync`` so that project
    worktrees exist on disk. This is the canonical setup helper for tests that
    exercise subcommands requiring a fully synced repository (e.g.
    ``repo info``, ``repo overview``, ``repo gc``).

    Args:
        tmp_path: pytest-provided temporary directory root.
        git_user_name: Git ``user.name`` used when creating bare repos.
        git_user_email: Git ``user.email`` used when creating bare repos.
        project_name: Project name in the manifest.
        project_path: Project path in the manifest.
        manifest_filename: Manifest XML file name.
        branch: Branch name used for the manifest default revision.

    Returns:
        A tuple of ``(checkout_dir, repo_dir)`` after a successful init and sync.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` exits
            with a non-zero code.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    bare_content = _create_bare_content_repo(
        repos_dir,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        project_name=project_name,
    )
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(
        repos_dir,
        fetch_base,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        project_name=project_name,
        project_path=project_path,
        manifest_filename=manifest_filename,
        branch=branch,
    )
    manifest_url = f"file://{manifest_bare}"

    repo_dir = checkout_dir / ".repo"

    init_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        branch,
        "-m",
        manifest_filename,
        cwd=checkout_dir,
    )
    assert init_result.returncode == 0, (
        f"Prerequisite 'kanon repo init' failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )

    sync_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        "--jobs=1",
        cwd=checkout_dir,
    )
    assert sync_result.returncode == 0, (
        f"Prerequisite 'kanon repo sync' failed with exit {sync_result.returncode}.\n"
        f"  stdout: {sync_result.stdout!r}\n"
        f"  stderr: {sync_result.stderr!r}"
    )
    return checkout_dir, repo_dir


@pytest.fixture(scope="session", autouse=True)
def functional_repo_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Create a minimal .repo directory for the session and export KANON_REPO_DIR.

    The embedded repo tool's subcommands (init, envsubst, sync, etc.) expect
    a .repo/repo/ git repository with at least one tagged commit. This fixture
    creates that minimal structure so functional tests invoking `kanon repo`
    subcommands have a well-formed baseline.

    The fixture sets os.environ[KANON_REPO_DIR] so that subprocess calls made
    by functional tests inherit the configured .repo path without requiring
    an explicit --repo-dir argument on the command line.

    Yields:
        The path to the created .repo directory.
    """
    from kanon_cli.constants import KANON_REPO_DIR_ENV

    base = tmp_path_factory.mktemp("functional_repo")
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    manifest_link = repo_dot_dir / "manifest.xml"
    manifest_link.symlink_to(manifest_path)

    # The version subcommand calls git describe HEAD inside .repo/repo/,
    # so .repo/repo/ must be a git repository with at least one tagged commit.
    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=repo_tool_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_tool_dir)
    _git(["config", "user.name", "Test"], cwd=repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    previous = os.environ.get(KANON_REPO_DIR_ENV)
    os.environ[KANON_REPO_DIR_ENV] = str(repo_dot_dir)
    yield repo_dot_dir
    if previous is None:
        del os.environ[KANON_REPO_DIR_ENV]
    else:
        os.environ[KANON_REPO_DIR_ENV] = previous
