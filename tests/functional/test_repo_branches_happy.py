"""Happy-path functional tests for 'kanon repo branches'.

Exercises the happy path of the 'repo branches' subcommand by invoking
``kanon repo branches`` as a subprocess against a real initialized, synced,
and started repo directory created in a temporary directory. No mocking --
these tests use the full CLI stack against actual git operations.

The 'repo branches' subcommand summarizes the currently available topic
branches across all projects in the manifest. It accepts an optional list of
positional project references to restrict output to specific projects.

Covers:
- AC-TEST-001: 'kanon repo branches' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo branches' has a happy-path test.
- AC-FUNC-001: 'kanon repo branches' executes successfully with documented
  default behavior (exit 0 when topic branches exist).
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

_GIT_USER_NAME = "Repo Branches Happy Test User"
_GIT_USER_EMAIL = "repo-branches-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "branches-test-project"

# Branch names used in branches tests -- each test class uses a unique name to
# avoid cross-test interference.
_BRANCH_DEFAULT = "feature/branches-default"
_BRANCH_WITH_PROJECT_NAME = "feature/branches-by-name"
_BRANCH_WITH_PROJECT_PATH = "feature/branches-by-path"
_BRANCH_CHANNEL = "feature/branches-channel"

# Flag name constants
_FLAG_ALL = "--all"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_BRANCHES = "branches"
_CLI_FLAG_REPO_DIR = "--repo-dir"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _setup_repo_with_branch(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> "tuple[pathlib.Path, pathlib.Path]":
    """Set up a synced repo and create a local branch using 'kanon repo start'.

    Runs 'kanon repo init', 'kanon repo sync', and 'kanon repo start
    <branch_name> --all' so that the branch exists in every project in the
    manifest. The returned (checkout_dir, repo_dir) pair is ready for a
    'branches' invocation that will list the created branch.

    Args:
        tmp_path: pytest-provided temporary directory root.
        branch_name: The name of the branch to create via 'kanon repo start'.

    Returns:
        A tuple of (checkout_dir, repo_dir) after init, sync, and start.

    Raises:
        AssertionError: When kanon repo init, sync, or start exits non-zero.
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
        _CLI_TOKEN_REPO,
        _CLI_FLAG_REPO_DIR,
        str(repo_dir),
        "start",
        branch_name,
        _FLAG_ALL,
        cwd=checkout_dir,
    )
    assert start_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo start {branch_name} {_FLAG_ALL}' failed with "
        f"exit {start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo branches with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo branches' with default args exits 0.

    Verifies that 'kanon repo branches' with no additional arguments against
    a properly initialized, synced, and started repo directory exits 0 and
    lists the topic branch in its output.
    """

    def test_repo_branches_with_no_args_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo branches' with no extra args must exit 0.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start <branch> --all', invokes 'kanon repo branches' with
        no additional arguments. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_BRANCHES,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_branches_with_no_args_lists_topic_branch(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo branches' with no extra args lists the created topic branch.

        After a successful 'kanon repo start <branch> --all', 'kanon repo
        branches' must include the branch name in its output. The branches
        subcommand writes branch listings to stdout; the branch name must
        appear there.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_BRANCHES,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo branches' failed: {result.stderr!r}"

        combined_output = result.stdout + result.stderr
        assert _BRANCH_DEFAULT in combined_output, (
            f"Expected branch {_BRANCH_DEFAULT!r} to appear in 'kanon repo branches' output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo branches has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo branches'.

    'repo branches' accepts an optional list of project references as positional
    arguments to restrict the branch listing to specific projects. Both forms
    of project reference (name and path) are exercised via
    @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_branches_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo branches <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start <branch> --all', passes the project reference (name
        or path) as a positional argument to 'kanon repo branches'. Verifies
        the process exits 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, branch_name)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_BRANCHES,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches {project_ref}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_branches_with_project_ref_lists_topic_branch(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo branches <project_ref>' lists the topic branch for that project.

        After a successful 'kanon repo branches <project_ref>', the topic
        branch name must appear in the command output for the referenced
        project.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, branch_name)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_BRANCHES,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo branches {project_ref}' failed: {result.stderr!r}"
        )

        combined_output = result.stdout + result.stderr
        assert branch_name in combined_output, (
            f"Expected branch {branch_name!r} to appear in 'kanon repo branches "
            f"{project_ref}' output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo branches'.

    Verifies that successful 'kanon repo branches' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo branches' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo branches'.

        Raises:
            AssertionError: When any prerequisite step fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_CHANNEL)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_BRANCHES,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo branches' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_branches_success_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo branches' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo branches'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_branches_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo branches' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo branches': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_branches_success_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo branches' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo branches'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
