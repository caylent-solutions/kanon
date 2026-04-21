"""Happy-path functional tests for 'kanon repo cherry-pick'.

Exercises the happy path of the 'repo cherry-pick' subcommand by invoking
``kanon repo cherry-pick`` as a subprocess against a real initialized, synced,
and started repo directory created in a temporary directory. No mocking --
these tests use the full CLI stack against actual git operations.

The 'repo cherry-pick' subcommand cherry-picks a single commit (identified by
its SHA1) from the current git repository into the current branch. It rewrites
the commit message to remove any existing Change-Id and appends a reference to
the original commit. Since the command operates via ``GitCommand(None, ...)``
(i.e. with no project scope), the process CWD must be a git working tree.

The happy-path setup:
1. Run ``kanon repo init``, ``kanon repo sync``, and ``kanon repo start`` to
   place the project worktree on a topic branch.
2. In the project worktree, create a temporary local branch and commit one new
   file on that branch to produce a cherry-pickable SHA1.
3. Switch back to the topic branch and invoke ``kanon repo cherry-pick <sha1>``
   from the project worktree directory.

Covers:
- AC-TEST-001: 'kanon repo cherry-pick' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo cherry-pick' has a happy-path test.
- AC-FUNC-001: 'kanon repo cherry-pick' executes successfully with documented
  default behavior (exit 0 when cherry-picking a valid commit into the current
  branch without conflicts).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _DEFAULT_GIT_BRANCH,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Cherry Pick Happy Test User"
_GIT_USER_EMAIL = "repo-cherry-pick-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "cherry-pick-test-project"

# Branch names used in cherry-pick tests -- each test uses a unique name to
# avoid cross-test interference when the same started repo is reused.
_BRANCH_DEFAULT = "feature/default-cherry-pick"
_BRANCH_CHANNEL_DISCIPLINE = "feature/channel-cherry-pick"

# Local branch used to produce a cherry-pickable commit in the project worktree
_CHERRY_SOURCE_BRANCH = "local/cherry-source"

# File added on the cherry source branch -- unique name to avoid conflicts
_CHERRY_SOURCE_FILE = "cherry-source-content.txt"
_CHERRY_SOURCE_TEXT = "added by cherry-pick source branch"

# Commit message for the cherry-pick source commit
_CHERRY_COMMIT_MSG = "Add cherry source file"

# Flag name constant
_FLAG_ALL = "--all"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _setup_started_repo(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Delegate to _setup_synced_repo, then run 'kanon repo start', return (checkout_dir, repo_dir).

    Calls :func:`tests.functional.conftest._setup_synced_repo` to handle all
    bare-repo creation, ``kanon repo init``, and ``kanon repo sync`` steps, then
    appends the ``kanon repo start`` invocation so that the named branch exists
    in all project worktrees on disk. The 'cherry-pick' subcommand requires the
    project to be on a topic branch before cherry-picking.

    Args:
        tmp_path: pytest-provided temporary directory root.
        branch_name: The branch name to create with 'repo start'.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init, sync, and start.

    Raises:
        AssertionError: When kanon repo start exits with a non-zero code.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
        branch=_DEFAULT_GIT_BRANCH,
    )

    start_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "start",
        branch_name,
        _FLAG_ALL,
        cwd=checkout_dir,
    )
    assert start_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo start {branch_name} {_FLAG_ALL}' failed with exit "
        f"{start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )

    return checkout_dir, repo_dir


def _create_cherry_pick_sha(project_dir: pathlib.Path) -> str:
    """Create a cherry-pickable commit in project_dir and return its full SHA1.

    Creates a local branch ``_CHERRY_SOURCE_BRANCH``, adds a unique new file
    ``_CHERRY_SOURCE_FILE`` and commits it, then switches back to the branch
    that was current when this function was called. Returns the full 40-character
    SHA1 of the newly created commit so that the caller can pass it to
    ``kanon repo cherry-pick``.

    The cherry-pick source commit adds a file that does not exist in the
    current branch, so applying it will never produce a merge conflict.

    Args:
        project_dir: Path to the project's git working tree.

    Returns:
        The full 40-character SHA1 of the cherry-pick source commit.

    Raises:
        RuntimeError: When any git command exits with a non-zero code.
    """
    current_branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if current_branch_result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse --abbrev-ref HEAD failed in {project_dir!r}:\n"
            f"  stdout: {current_branch_result.stdout!r}\n"
            f"  stderr: {current_branch_result.stderr!r}"
        )
    original_branch = current_branch_result.stdout.strip()

    _git_in_project(["checkout", "-b", _CHERRY_SOURCE_BRANCH], project_dir)
    (project_dir / _CHERRY_SOURCE_FILE).write_text(_CHERRY_SOURCE_TEXT, encoding="utf-8")
    _git_in_project(["add", _CHERRY_SOURCE_FILE], project_dir)
    _git_in_project(["commit", "-m", _CHERRY_COMMIT_MSG], project_dir)

    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if sha_result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse HEAD failed in {project_dir!r}:\n"
            f"  stdout: {sha_result.stdout!r}\n"
            f"  stderr: {sha_result.stderr!r}"
        )
    cherry_sha = sha_result.stdout.strip()

    _git_in_project(["checkout", original_branch], project_dir)

    return cherry_sha


def _git_in_project(args: list[str], project_dir: pathlib.Path) -> None:
    """Run a git command in project_dir, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        project_dir: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} failed in {project_dir!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo cherry-pick with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo cherry-pick' with default args exits 0.

    Verifies that 'kanon repo cherry-pick <sha1>' invoked from a project
    worktree on a topic branch exits 0 when cherry-picking a valid commit that
    introduces a new file without conflicts.
    """

    def test_repo_cherry_pick_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' must exit 0 for a valid commit.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start', creates a cherry-pickable local commit, then
        invokes 'kanon repo cherry-pick <sha1>' from the project worktree.
        Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo cherry-pick {cherry_sha[:8]}...' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_cherry_pick_leaves_commit_in_branch(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' must result in the commit being present in the branch.

        After a successful cherry-pick, the cherry-picked commit's file must
        exist in the project worktree, confirming that the commit was applied.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo cherry-pick' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

        cherry_file = project_dir / _CHERRY_SOURCE_FILE
        assert cherry_file.exists(), (
            f"Expected cherry-picked file {cherry_file!r} to exist in the project "
            f"worktree after 'kanon repo cherry-pick', but it was not found."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo cherry-pick has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickPositionalArgHappyPath:
    """AC-TEST-002: happy-path test for the positional argument of 'repo cherry-pick'.

    'repo cherry-pick' accepts exactly one positional argument: the SHA1 of the
    commit to cherry-pick. This class exercises the SHA1 positional argument
    with a full SHA1 reference obtained from a real local commit.
    """

    def test_repo_cherry_pick_with_full_sha1_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <full-sha1>' exits 0 for a valid full SHA1.

        Creates a cherry-pickable commit and passes its full 40-character SHA1
        as the positional argument to 'kanon repo cherry-pick'. Verifies the
        process exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        assert len(cherry_sha) == 40, (
            f"Expected a 40-character full SHA1 from git rev-parse HEAD, "
            f"got {len(cherry_sha)!r} characters: {cherry_sha!r}"
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo cherry-pick {cherry_sha[:8]}...' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo cherry-pick'.

    Verifies that successful 'kanon repo cherry-pick' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo cherry-pick <sha1>' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo cherry-pick <sha1>'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync/start/cherry-pick)
                fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_DISCIPLINE)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo cherry-pick' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_cherry_pick_success_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo cherry-pick' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo cherry-pick'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_cherry_pick_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo cherry-pick' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo cherry-pick': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_cherry_pick_success_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo cherry-pick' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo cherry-pick'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
