"""Happy-path functional tests for 'kanon repo abandon'.

Exercises the happy path of the 'repo abandon' subcommand by invoking
``kanon repo abandon`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo abandon' subcommand permanently abandons a development branch by
deleting it (and all its history) from the local repository. The first
positional argument is the required branch name; the remaining positional
arguments are optional project references (defaulting to all projects when
omitted). The --all flag abandons all local branches in every project.

Covers:
- AC-TEST-001: 'kanon repo abandon' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo abandon' has a happy-path test.
- AC-FUNC-001: 'kanon repo abandon' executes successfully with documented default
  behavior (exit 0 when a valid branch name is supplied and the branch exists).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _git_branch_list, _run_kanon, _setup_synced_repo

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Abandon Happy Test User"
_GIT_USER_EMAIL = "repo-abandon-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "abandon-test-project"

# Branch names used in abandon tests -- unique per test class to avoid
# cross-test interference.
_BRANCH_DEFAULT = "feature/abandon-default"
_BRANCH_WITH_PROJECT_NAME = "feature/abandon-by-name"
_BRANCH_WITH_PROJECT_PATH = "feature/abandon-by-path"
_BRANCH_ALL = "feature/abandon-all"
_BRANCH_CHANNEL = "feature/abandon-channel"

# Flag name constants
_FLAG_ALL = "--all"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Text expected in stdout on a successful abandon of one or more branches
_ABANDONED_BRANCHES_HEADER = "Abandoned branches:"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


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
    manifest. The returned (checkout_dir, repo_dir) pair is ready for an
    'abandon' invocation.

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
        project_path=_PROJECT_PATH,
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
        f"Prerequisite 'kanon repo start {branch_name} {_FLAG_ALL}' failed with "
        f"exit {start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo abandon with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo abandon' with default args exits 0.

    Verifies that 'kanon repo abandon <branchname>' against a properly
    initialized and synced repo directory exits 0 when the named branch exists
    in at least one project. Uses 'kanon repo start' to create the branch
    before invoking 'kanon repo abandon'.
    """

    def test_repo_abandon_with_branch_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' must exit 0 when the branch exists.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start <branch> --all', invokes 'kanon repo abandon <branch>'
        with no additional arguments. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo abandon {_BRANCH_DEFAULT}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_abandon_branch_is_deleted_from_project(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' removes the branch from the project worktree.

        After a successful 'kanon repo abandon <branch>', the branch must no
        longer exist in the project's local git repository. Verifies via
        'git branch' output in the project directory.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo abandon {_BRANCH_DEFAULT}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        branch_list = _git_branch_list(project_dir)
        assert _BRANCH_DEFAULT not in branch_list, (
            f"Branch {_BRANCH_DEFAULT!r} still exists in project dir {project_dir!r} "
            f"after 'kanon repo abandon {_BRANCH_DEFAULT}'.\n"
            f"  git branch output: {branch_list!r}"
        )

    def test_repo_abandon_success_prints_abandoned_branches_header(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' prints 'Abandoned branches:' header on success.

        A successful 'kanon repo abandon' invocation prints 'Abandoned branches:'
        followed by the abandoned branch name(s) to stdout. This verifies
        the documented default behavior of the subcommand.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _BRANCH_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo abandon {_BRANCH_DEFAULT}' failed: {result.stderr!r}"
        )
        assert _ABANDONED_BRANCHES_HEADER in result.stdout, (
            f"Expected {_ABANDONED_BRANCHES_HEADER!r} in stdout of "
            f"'kanon repo abandon {_BRANCH_DEFAULT}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo abandon has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for all positional arguments of 'repo abandon'.

    'repo abandon' accepts the branch name as the first required positional
    argument. Subsequent positional arguments are optional project references
    (name or path) to restrict which projects the branch is abandoned from.
    The --all flag abandons every local branch in every project.

    Tests cover:
    - Branch name + project name
    - Branch name + project path
    - --all flag (abandons all local branches)

    Note: branch-name-only coverage (all projects implicitly) is provided by
    TestRepoAbandonHappyPathDefaultArgs.
    """

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_abandon_with_branch_and_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo abandon <branch> <project_ref>' exits 0 for a valid project reference.

        After a successful init, sync, and 'kanon repo start <branch> --all',
        passes the project reference (name or path) as the second positional
        argument to 'kanon repo abandon'. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo abandon {branch_name} {project_ref}' exited "
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
    def test_repo_abandon_with_branch_and_project_ref_deletes_branch(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo abandon <branch> <project_ref>' deletes the branch from that project.

        After a successful 'kanon repo abandon <branch> <project_ref>', the
        branch must no longer exist in the project's local git repository.
        Verifies via 'git branch' output in the project directory.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo abandon {branch_name} {project_ref}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        branch_list = _git_branch_list(project_dir)
        assert branch_name not in branch_list, (
            f"Branch {branch_name!r} still exists in project dir {project_dir!r} "
            f"after 'kanon repo abandon {branch_name} {project_ref}'.\n"
            f"  git branch output: {branch_list!r}"
        )

    def test_repo_abandon_with_all_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --all' exits 0 when local branches exist.

        After a successful init, sync, and 'kanon repo start <branch> --all',
        invokes 'kanon repo abandon --all' to delete all local branches in
        every project. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_ALL)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _FLAG_ALL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo abandon {_FLAG_ALL}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_abandon_with_all_flag_deletes_all_branches(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --all' removes all local branches from every project.

        After 'kanon repo abandon --all', no local branches should remain
        in the project worktree. Verifies via 'git branch' output that the
        branch list is empty (the --all contract removes every local branch).
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_ALL)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _FLAG_ALL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo abandon {_FLAG_ALL}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        branch_list = _git_branch_list(project_dir)
        assert branch_list == [], (
            f"Expected no local branches to remain in project dir {project_dir!r} "
            f"after 'kanon repo abandon {_FLAG_ALL}', but found: {branch_list!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo abandon'.

    Verifies that successful 'kanon repo abandon' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo abandon <branch>' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo abandon <branch>'.

        Raises:
            AssertionError: When any prerequisite step fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_CHANNEL)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "abandon",
            _BRANCH_CHANNEL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo abandon {_BRANCH_CHANNEL}' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_abandon_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo abandon' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo abandon'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_abandon_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo abandon' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo abandon': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_abandon_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo abandon' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo abandon'.\n  stderr: {channel_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Helper-function error path coverage
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGitBranchListErrorPath:
    """Exercises the error path of the _git_branch_list helper.

    _git_branch_list raises RuntimeError when 'git branch' exits with a
    non-zero code (e.g. the directory is not a git repository). This test
    verifies the RuntimeError is raised and contains the expected context
    so that the error path is covered for AC-FINAL-014.
    """

    def test_git_branch_list_raises_runtime_error_for_non_git_dir(self, tmp_path: pathlib.Path) -> None:
        """_git_branch_list raises RuntimeError when given a non-git directory.

        Passes a plain temporary directory (not a git repo) to _git_branch_list.
        'git branch' exits non-zero inside a non-git directory, which must
        cause _git_branch_list to raise RuntimeError with the directory path
        included in the message.
        """
        non_git_dir = tmp_path / "not-a-repo"
        non_git_dir.mkdir()

        with pytest.raises(RuntimeError, match=str(non_git_dir)):
            _git_branch_list(non_git_dir)
