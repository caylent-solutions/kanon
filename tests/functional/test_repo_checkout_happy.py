"""Happy-path functional tests for 'kanon repo checkout'.

Exercises the happy path of the 'repo checkout' subcommand by invoking
``kanon repo checkout`` as a subprocess against a real initialized, synced,
and started repo directory created in a temporary directory. No mocking --
these tests use the full CLI stack against actual git operations.

The 'repo checkout' subcommand checks out an existing branch that was
previously created by 'repo start'. The first positional argument is the
required branch name; the remaining positional arguments are optional project
references (project name or project path) that restrict checkout to specific
projects.

Covers:
- AC-TEST-001: 'kanon repo checkout' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo checkout' has a happy-path test.
- AC-FUNC-001: 'kanon repo checkout' executes successfully with documented
  default behavior (exit 0 when checking out an existing started branch).
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

_GIT_USER_NAME = "Repo Checkout Happy Test User"
_GIT_USER_EMAIL = "repo-checkout-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "checkout-test-project"

# Branch names used in checkout tests -- each test uses a unique name to avoid
# cross-test interference when the same synced repo is reused.
_BRANCH_DEFAULT = "feature/default-checkout"
_BRANCH_WITH_PROJECT_NAME = "feature/checkout-by-name"
_BRANCH_WITH_PROJECT_PATH = "feature/checkout-by-path"

# Flag name constants
_FLAG_ALL = "--all"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


def _setup_started_repo(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Delegate to _setup_synced_repo, then run 'kanon repo start', return (checkout_dir, repo_dir).

    Calls :func:`tests.functional.conftest._setup_synced_repo` to handle all
    bare-repo creation, ``kanon repo init``, and ``kanon repo sync`` steps, then
    appends the ``kanon repo start`` invocation so that the named branch exists
    in all project worktrees on disk. The 'checkout' subcommand requires the
    branch to have been created by 'repo start' before it can be checked out.

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
# AC-TEST-001 / AC-FUNC-001: kanon repo checkout with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo checkout' with default args exits 0.

    Verifies that 'kanon repo checkout <branchname>' with only the mandatory
    branch name argument against a properly initialized, synced, and started
    repo directory exits 0. 'checkout' checks out the named branch in all
    projects when no project references are specified.
    """

    def test_repo_checkout_with_branch_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' must exit 0 in a started repo.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start', invokes 'kanon repo checkout <branch>' with
        only the mandatory branch name argument. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {_BRANCH_DEFAULT}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_checkout_with_branch_name_leaves_project_on_branch(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' places the project worktree on the branch.

        After a successful 'kanon repo checkout <branch>', the project worktree
        must be on the named branch. Verifies that 'git branch' in the project
        directory lists the branch as current (marked with '*').
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo checkout {_BRANCH_DEFAULT}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        current_branch = _git_current_branch(project_dir)
        assert current_branch == _BRANCH_DEFAULT, (
            f"Expected project dir {project_dir!r} to be on branch "
            f"{_BRANCH_DEFAULT!r} after 'kanon repo checkout', "
            f"but current branch is {current_branch!r}."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo checkout has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo checkout'.

    'repo checkout' requires the branch name as the first positional argument.
    Subsequent positional arguments are optional project references (name or path).
    Both forms (by project name and by project path) are exercised via
    @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_checkout_with_branch_and_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo checkout <branch> <project_ref>' exits 0 for a valid reference.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start', passes the project reference (name or path) as the
        second positional argument to 'kanon repo checkout'. Verifies the
        process exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {branch_name} {project_ref}' exited "
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
    def test_repo_checkout_with_branch_and_project_ref_leaves_project_on_branch(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo checkout <branch> <project_ref>' places the project on the branch.

        After a successful 'kanon repo checkout <branch> <project_ref>',
        verifies that 'git branch' in the project's worktree shows the branch
        as the current HEAD.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo checkout {branch_name} {project_ref}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        current_branch = _git_current_branch(project_dir)
        assert current_branch == branch_name, (
            f"Expected project dir {project_dir!r} to be on branch "
            f"{branch_name!r} after 'kanon repo checkout {branch_name} {project_ref}', "
            f"but current branch is {current_branch!r}."
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo checkout'.

    Verifies that successful 'kanon repo checkout' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo checkout <branch>' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo checkout <branch>'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync/start) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo checkout {_BRANCH_DEFAULT}' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_checkout_success_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo checkout' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo checkout'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_checkout_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo checkout' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo checkout': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_checkout_success_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo checkout' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo checkout'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _git_current_branch(project_dir: pathlib.Path) -> str:
    """Return the current branch name in project_dir.

    Runs ``git rev-parse --abbrev-ref HEAD`` in project_dir and returns the
    branch name as a string (stripped of whitespace).

    Args:
        project_dir: Path to a git working directory.

    Returns:
        The current branch name string.

    Raises:
        RuntimeError: When git exits with a non-zero code.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse --abbrev-ref HEAD failed in {project_dir!r}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    return result.stdout.strip()
