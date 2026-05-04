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

Shared helpers for smartsync test modules (imported by
``test_repo_smartsync_happy.py`` and ``test_repo_smartsync_flags.py``):

- :func:`_find_free_port` -- allocate a free TCP port for the XMLRPC server.
- :func:`_resolve_fetch_base` -- extract the fetch-base URL from the manifest.
- :func:`_patch_manifest_with_server` -- patch the manifest with a
  manifest-server element.
- :func:`_start_xmlrpc_server` -- start a ``SimpleXMLRPCServer`` in a daemon
  thread.
- :func:`_build_smartsync_state` -- construct a fully patched smartsync repo
  with a live XMLRPC server and return
  ``(checkout_dir, repo_dir, rpc_server)``.

Shared constants for smartsync test modules:

- ``_XMLRPC_HOST`` -- loopback address for XMLRPC bind.
- ``_MANIFEST_SERVER_URL_TEMPLATE`` -- URL template formatted with host+port.
- ``_REPO_MANIFESTS_SUBPATH`` -- path within ``.repo/`` to the manifest file.
- ``_MANIFEST_XML_TEMPLATE`` -- manifest XML template with manifest-server.
- ``_SUCCESS_PHRASE`` -- documented completion phrase emitted by repo sync.
- ``_CLI_TOKEN_REPO`` -- first positional token for kanon repo commands.
- ``_CLI_TOKEN_SMARTSYNC`` -- second positional token for smartsync.
- ``_CLI_FLAG_REPO_DIR`` -- ``--repo-dir`` flag token.
- ``_CLI_FLAG_JOBS_ONE`` -- ``--jobs=1`` flag shared between smartsync test modules.
- ``_CLI_COMMAND_PHRASE`` -- human-readable command phrase for diagnostics.
- ``_TRACEBACK_MARKER`` -- sentinel string indicating a Python traceback.
- ``_ERROR_PREFIX`` -- ``"Error:"`` prefix that must not appear on stdout.
- ``_GIT_BRANCH`` -- default branch name for bare repos.
- ``_MANIFEST_FILENAME`` -- manifest XML file name.
- ``_PROJECT_NAME`` -- project name used in manifest.
- ``_PROJECT_PATH`` -- project path used in manifest.
- ``_GIT_USER_EMAIL`` -- git user email for bare repo commits.
- ``_GIT_USER_NAME`` -- git user name for bare repo commits.

Shared constants for upload test modules (imported by
``test_repo_upload_happy.py`` and ``test_repo_upload_flags.py``):

- ``_FAKE_REVIEW_BASE_URL`` -- fake Gerrit review base URL used as
  ``remote.local.review`` config value.
- ``_OK_MARKER`` -- success marker written to stderr on successful upload.
- ``_UPLOAD_PROJECT_PHRASE`` -- phrase expected in stdout when upload finds a
  reviewable branch.
- ``_ENV_IGNORE_SSH_INFO`` -- environment variable that suppresses SSH-info
  fetching in ReviewUrl.
- ``_GIT_CONFIG_REMOTE_REVIEW`` -- git config key for the review remote URL.

Shared helpers for upload test modules:

- :func:`_setup_upload_repo` -- create a synced repo with a reviewable topic
  branch and Gerrit-redirect config; return
  ``(checkout_dir, repo_dir, review_bare)``.
"""

import os
import pathlib
import socket
import subprocess
import sys
import threading
import xmlrpc.server
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

# ---------------------------------------------------------------------------
# Shared constants for smartsync test modules
# ---------------------------------------------------------------------------

# Localhost bind address for the XMLRPC manifest server fixture.
_XMLRPC_HOST = "127.0.0.1"

# Manifest-server URL template (formatted with the port at fixture time).
_MANIFEST_SERVER_URL_TEMPLATE = "http://{host}:{port}"

# Path within the .repo directory to the checked-out manifest file.
_REPO_MANIFESTS_SUBPATH = "manifests"

# Manifest XML template that includes a manifest-server element.
# Used both to patch the checked-out manifest and as the approved-manifest
# response returned by the XMLRPC server.
_MANIFEST_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <manifest-server url="{manifest_server_url}" />\n'
    '  <remote name="local" fetch="{fetch_base}" />\n'
    '  <default revision="{branch}" remote="local" />\n'
    '  <project name="{project_name}" path="{project_path}" />\n'
    "</manifest>\n"
)

# Phrase expected in the success output of 'kanon repo smartsync'.
_SUCCESS_PHRASE = "repo sync has finished successfully."

# CLI token constants shared between smartsync test modules.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_SMARTSYNC = "smartsync"
_CLI_FLAG_REPO_DIR = "--repo-dir"

# Jobs flag shared between smartsync happy-path and flag-coverage test modules.
_CLI_FLAG_JOBS_ONE = "--jobs=1"

# Composed CLI command phrase (no inline literals in diagnostic messages).
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_SMARTSYNC}"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error-prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Default branch name for bare repos used in smartsync tests.
_GIT_BRANCH = "main"

# Manifest XML file name for smartsync tests.
_MANIFEST_FILENAME = "default.xml"

# Project name used in the manifest for smartsync tests.
_PROJECT_NAME = "content-bare"

# Project path used in the manifest for smartsync tests.
_PROJECT_PATH = "smartsync-test-project"

# Git user email for bare repo commits in smartsync tests.
_GIT_USER_EMAIL = "repo-smartsync@example.com"

# Git user name for bare repo commits in smartsync tests.
_GIT_USER_NAME = "Repo Smartsync Test User"


# ---------------------------------------------------------------------------
# Shared constants for upload test modules
# ---------------------------------------------------------------------------

# Fake Gerrit review base URL (not a real server -- redirected via git insteadOf).
_FAKE_REVIEW_BASE_URL = "http://fake.gerrit.example.com/"

# Success marker expected in stderr when 'kanon repo upload' completes normally.
_OK_MARKER = "[OK    ]"

# Phrase expected in stdout when upload finds a reviewable branch.
_UPLOAD_PROJECT_PHRASE = "Upload project"

# Environment variable that suppresses SSH-info fetching in ReviewUrl.
_ENV_IGNORE_SSH_INFO = "REPO_IGNORE_SSH_INFO"

# Git config key for the review remote URL.
_GIT_CONFIG_REMOTE_REVIEW = "remote.local.review"

# ---------------------------------------------------------------------------
# Upload-specific internal defaults used by _setup_upload_repo.
# Consumer test modules supply project_name and project_path explicitly or
# rely on these defaults when their repo uses identical settings.
# ---------------------------------------------------------------------------

_UPLOAD_DEFAULT_GIT_USER_NAME = "Repo Upload Test User"
_UPLOAD_DEFAULT_GIT_USER_EMAIL = "repo-upload@example.com"
_UPLOAD_DEFAULT_MANIFEST_FILENAME = "default.xml"
_UPLOAD_DEFAULT_PROJECT_NAME = "content-bare"
_UPLOAD_DEFAULT_PROJECT_PATH = "upload-test-project"
_UPLOAD_DEFAULT_TOPIC_BRANCH = "feature/upload-default"
_UPLOAD_CONTENT_FILE = "upload-test-content.txt"
_UPLOAD_CONTENT_TEXT = "upload test content"
_UPLOAD_COMMIT_MSG = "Add upload test content file"
_UPLOAD_REVIEW_BARE_DIR_NAME = "review.git"
_UPLOAD_CLI_TOKEN_START = "start"
_UPLOAD_CLI_FLAG_ALL = "--all"
_UPLOAD_EXPECTED_EXIT_CODE = 0


def _build_upload_insteadof_config_key(review_bare: "pathlib.Path") -> str:
    """Return the git config key for the insteadOf URL rewrite used in upload tests.

    Formats the ``url.<local-path>.insteadOf`` key that redirects git push
    operations from the fake Gerrit URL to the local bare repository.

    Args:
        review_bare: Absolute path to the local bare git repository used as
            the Gerrit push target.

    Returns:
        A git config key string of the form ``url.file://<path>.insteadOf``.
    """
    return f"url.file://{review_bare}.insteadOf"


def _full_upload_review_url(project_name: str) -> str:
    """Return the full fake Gerrit review URL for the given project name.

    ReviewUrl appends the remote project name to the base review URL.
    This function constructs the full URL that the insteadOf rewrite must
    match so that git pushes are redirected to the local bare repo.

    Args:
        project_name: The manifest project name (used as the Gerrit project path).

    Returns:
        The concatenation of ``_FAKE_REVIEW_BASE_URL`` and ``project_name``.
    """
    return _FAKE_REVIEW_BASE_URL + project_name


def _setup_upload_repo(
    tmp_path: "pathlib.Path",
    branch_name: str,
    project_name: str = _UPLOAD_DEFAULT_PROJECT_NAME,
    project_path: str = _UPLOAD_DEFAULT_PROJECT_PATH,
) -> "tuple[pathlib.Path, pathlib.Path, pathlib.Path]":
    """Create a synced repo with a reviewable topic branch and review config.

    Performs the shared setup steps required by all upload test modules:

    1. Calls ``_setup_synced_repo`` to create bare repos, run
       ``kanon repo init`` and ``kanon repo sync``, and return
       ``(checkout_dir, repo_dir)``.
    2. Runs ``kanon repo start <branch_name> --all`` to create the topic
       branch across all manifest projects.
    3. Commits one new file to the project worktree so the topic branch has
       uploadable commits.
    4. Creates a local bare git repository at
       ``tmp_path / _UPLOAD_REVIEW_BARE_DIR_NAME`` to act as the Gerrit push
       target.
    5. Configures ``remote.local.review`` (``_GIT_CONFIG_REMOTE_REVIEW``) in
       the project git config to ``_FAKE_REVIEW_BASE_URL`` so that
       ``repo upload`` picks up the review URL.
    6. Configures the ``url.<local-bare>.insteadOf`` rewrite in the project
       git config so that git redirects pushes from the fake Gerrit URL to
       the local bare repo.

    Args:
        tmp_path: pytest-provided temporary directory root.
        branch_name: Name of the topic branch to create via
            ``kanon repo start``.
        project_name: Manifest project name (default
            ``_UPLOAD_DEFAULT_PROJECT_NAME``).
        project_path: Manifest project path inside the checkout (default
            ``_UPLOAD_DEFAULT_PROJECT_PATH``).

    Returns:
        A 3-tuple of ``(checkout_dir, repo_dir, review_bare)`` where
        ``checkout_dir`` is the worktree root, ``repo_dir`` is the
        ``.repo`` directory, and ``review_bare`` is the local bare repo
        acting as the Gerrit push target.

    Raises:
        AssertionError: When any prerequisite step (init, sync, start)
            exits with a non-zero code.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_UPLOAD_DEFAULT_GIT_USER_NAME,
        git_user_email=_UPLOAD_DEFAULT_GIT_USER_EMAIL,
        project_name=project_name,
        project_path=project_path,
        manifest_filename=_UPLOAD_DEFAULT_MANIFEST_FILENAME,
    )
    project_dir = checkout_dir / project_path

    start_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        _UPLOAD_CLI_TOKEN_START,
        branch_name,
        _UPLOAD_CLI_FLAG_ALL,
        cwd=checkout_dir,
    )
    assert start_result.returncode == _UPLOAD_EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo start {branch_name} {_UPLOAD_CLI_FLAG_ALL}' failed "
        f"with exit {start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )

    (project_dir / _UPLOAD_CONTENT_FILE).write_text(_UPLOAD_CONTENT_TEXT, encoding="utf-8")
    _git(["add", _UPLOAD_CONTENT_FILE], cwd=project_dir)
    _git(["commit", "-m", _UPLOAD_COMMIT_MSG], cwd=project_dir)

    review_bare = tmp_path / _UPLOAD_REVIEW_BARE_DIR_NAME
    _git(["init", "--bare", str(review_bare)], cwd=tmp_path)

    subprocess.run(
        ["git", "-C", str(project_dir), "config", _GIT_CONFIG_REMOTE_REVIEW, _FAKE_REVIEW_BASE_URL],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project_dir),
            "config",
            _build_upload_insteadof_config_key(review_bare),
            _full_upload_review_url(project_name),
        ],
        check=True,
        capture_output=True,
    )

    return checkout_dir, repo_dir, review_bare


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


def _find_free_port() -> int:
    """Return a free TCP port on localhost by binding and immediately releasing.

    Uses the OS port-assignment mechanism to discover a free port, then
    releases the socket so the XMLRPC server can bind to it.

    Returns:
        An integer port number that is currently free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_XMLRPC_HOST, 0))
        return sock.getsockname()[1]


def _resolve_fetch_base(repo_dir: pathlib.Path) -> str:
    """Derive the fetch-base URL from the manifest file in a synced .repo dir.

    Reads ``.repo/manifests/default.xml`` to extract the ``fetch`` attribute
    from the first ``<remote>`` element.

    Args:
        repo_dir: Path to the ``.repo`` directory created by ``kanon repo init``.

    Returns:
        The fetch base URL string, e.g. ``"file:///tmp/.../repos"``.

    Raises:
        ValueError: When no ``<remote fetch="...">`` element is found in the
            manifest.
    """
    import xml.etree.ElementTree as ET

    manifest_path = repo_dir / _REPO_MANIFESTS_SUBPATH / _MANIFEST_FILENAME
    tree = ET.parse(str(manifest_path))
    root = tree.getroot()
    for remote in root.findall("remote"):
        fetch = remote.get("fetch")
        if fetch:
            return fetch
    raise ValueError(f"No <remote fetch='...'> element found in {manifest_path!r}")


def _patch_manifest_with_server(
    repo_dir: pathlib.Path,
    manifest_server_url: str,
    fetch_base: str,
) -> None:
    """Overwrite the checked-out manifest to include a <manifest-server> element.

    Writes a new manifest XML string (with the manifest-server element added)
    over ``.repo/manifests/default.xml``.

    Args:
        repo_dir: Path to the ``.repo`` directory.
        manifest_server_url: URL of the local XMLRPC server.
        fetch_base: The fetch base URL from the original manifest remote element.
    """
    manifest_path = repo_dir / _REPO_MANIFESTS_SUBPATH / _MANIFEST_FILENAME
    new_xml = _MANIFEST_XML_TEMPLATE.format(
        manifest_server_url=manifest_server_url,
        fetch_base=fetch_base,
        branch=_GIT_BRANCH,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
    )
    manifest_path.write_text(new_xml, encoding="utf-8")


def _start_xmlrpc_server(port: int, approved_manifest_xml: str) -> xmlrpc.server.SimpleXMLRPCServer:
    """Start a SimpleXMLRPCServer in a daemon thread and return it.

    Registers a ``GetApprovedManifest`` function that returns
    ``[True, approved_manifest_xml]`` for any call arguments.

    Args:
        port: The TCP port to bind to on localhost.
        approved_manifest_xml: The manifest XML string to return from the
            ``GetApprovedManifest`` XMLRPC method.

    Returns:
        The running ``SimpleXMLRPCServer`` instance.
    """
    rpc_server = xmlrpc.server.SimpleXMLRPCServer(
        (_XMLRPC_HOST, port),
        logRequests=False,
        allow_none=False,
    )

    def get_approved_manifest(*_args: object) -> list:
        return [True, approved_manifest_xml]

    rpc_server.register_function(get_approved_manifest, "GetApprovedManifest")

    server_thread = threading.Thread(target=rpc_server.serve_forever, daemon=True)
    server_thread.start()
    return rpc_server


def _build_smartsync_state(
    tmp_path: pathlib.Path,
) -> "tuple[pathlib.Path, pathlib.Path, xmlrpc.server.SimpleXMLRPCServer]":
    """Construct a synced kanon repo with manifest-server patched and XMLRPC server started.

    Performs the shared setup steps required by the class-scoped smartsync
    fixtures:
      1. Creates bare repos and runs ``kanon repo init`` + ``kanon repo sync``
         via ``_setup_synced_repo``.
      2. Allocates a free TCP port and formats the manifest-server URL.
      3. Reads the fetch-base URL from the synced manifest.
      4. Builds the approved-manifest XML string using ``_MANIFEST_XML_TEMPLATE``.
      5. Starts a ``SimpleXMLRPCServer`` in a daemon thread.
      6. Patches ``.repo/manifests/default.xml`` to include the
         ``<manifest-server>`` element.

    Args:
        tmp_path: A unique temporary directory used for bare repos and the checkout.

    Returns:
        A 3-tuple of ``(checkout_dir, repo_dir, rpc_server)`` where
        ``checkout_dir`` is the worktree root, ``repo_dir`` is the ``.repo``
        parent, and ``rpc_server`` is the running XMLRPC server instance.
        Callers are responsible for calling ``rpc_server.shutdown()`` when done.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
    )

    port = _find_free_port()
    server_url = _MANIFEST_SERVER_URL_TEMPLATE.format(host=_XMLRPC_HOST, port=port)

    fetch_base = _resolve_fetch_base(repo_dir)
    approved_manifest_xml = _MANIFEST_XML_TEMPLATE.format(
        manifest_server_url=server_url,
        fetch_base=fetch_base,
        branch=_GIT_BRANCH,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
    )

    rpc_server = _start_xmlrpc_server(port, approved_manifest_xml)
    _patch_manifest_with_server(repo_dir, server_url, fetch_base)

    return checkout_dir, repo_dir, rpc_server


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
