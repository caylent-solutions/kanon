"""Happy-path functional tests for 'kanon repo rebase'.

Exercises the happy path of the 'repo rebase' subcommand by invoking
``kanon repo rebase`` as a subprocess against a real initialized, synced,
and started repo directory created in a temporary directory. No mocking --
these tests use the full CLI stack against actual git operations.

The 'repo rebase' subcommand uses git rebase to move local changes in the
current topic branch onto the HEAD of the upstream history. After 'repo start'
creates a topic branch that already points at the upstream revision, running
'repo rebase' is a no-op that exits 0.

Covers:
- AC-TEST-001: 'kanon repo rebase' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo rebase' has a happy-path test.
- AC-FUNC-001: 'kanon repo rebase' executes successfully with documented default
  behavior (exit 0 when the topic branch is already up to date with upstream).
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

_GIT_USER_NAME = "Repo Rebase Happy Test User"
_GIT_USER_EMAIL = "repo-rebase-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "rebase-test-project"

# Branch names used in rebase tests -- each test uses a unique name to avoid
# cross-test interference when the same started repo is reused in parametrize.
_BRANCH_DEFAULT = "feature/default-rebase"
_BRANCH_WITH_PROJECT_NAME = "feature/rebase-by-name"
_BRANCH_WITH_PROJECT_PATH = "feature/rebase-by-path"

# Flag name constant
_FLAG_ALL = "--all"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Local setup helper -- delegates to conftest._setup_synced_repo
# ---------------------------------------------------------------------------


def _setup_started_repo(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Delegate to _setup_synced_repo, then run 'kanon repo start', return (checkout_dir, repo_dir).

    Calls :func:`tests.functional.conftest._setup_synced_repo` to handle all
    bare-repo creation, ``kanon repo init``, and ``kanon repo sync`` steps, then
    appends the ``kanon repo start`` invocation so that the named branch exists
    in all project worktrees on disk. The 'rebase' subcommand requires the
    project to be on a topic branch that tracks an upstream before rebasing.

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


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo rebase with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo rebase' with default args exits 0.

    Verifies that 'kanon repo rebase' with no additional arguments against
    a properly initialized, synced, and started repo directory exits 0. When
    the topic branch is already at the upstream HEAD (no divergent commits),
    git rebase is a no-op and the command exits 0.
    """

    def test_repo_rebase_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' with no extra args must exit 0.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start', invokes 'kanon repo rebase' with no additional
        arguments. A topic branch just created by 'repo start' is already at
        the upstream revision, so rebase exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_rebase_with_defaults_produces_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' must produce non-empty combined output in a started repo.

        A successful invocation on a started repo produces at least some
        output describing the rebase operation (the project name and branch
        rebasing line). An empty combined output would indicate the command
        ran without performing any reporting.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo rebase' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo rebase' produced empty combined output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo rebase has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebasePositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional argument of 'repo rebase'.

    'repo rebase' accepts optional project references as positional arguments
    to restrict the rebase operation to specific projects. Both project name
    and project path forms are exercised via @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_rebase_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo rebase <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start', passes the project reference (name or path) as a
        positional argument to 'kanon repo rebase'. The topic branch is already
        at the upstream HEAD, so rebase exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase {project_ref}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo rebase'.

    Verifies that successful 'kanon repo rebase' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo rebase' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo rebase'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync/start) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo rebase' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_rebase_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo rebase' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo rebase'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_rebase_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo rebase' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo rebase': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_rebase_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo rebase' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo rebase'.\n  stderr: {channel_result.stderr!r}"
        )
