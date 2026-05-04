"""Happy-path functional tests for 'kanon repo sync'.

Exercises the happy path of the 'repo sync' subcommand by invoking
``kanon repo sync`` as a subprocess against a real initialized repo directory
created in a temporary directory. No mocking -- these tests use the full CLI
stack against actual git operations.

The 'repo sync' subcommand synchronizes local project directories with the
remote repositories specified in the manifest.  With no positional arguments
it syncs all projects; with one or more project name/path arguments it limits
the sync to those projects.

On success with no ``--quiet`` flag, 'repo sync' prints
"repo sync has finished successfully." to stdout and exits 0.

AC wording note: AC-TEST-002 states "every positional argument of 'repo sync'
has a happy-path test."  The upstream 'repo sync' positional arguments are
optional ``[<project>...]`` references -- project names or relative paths that
restrict which projects are synced.  Both the no-argument form (sync all) and
the single project-name form are exercised below.  There are no required
positional arguments, so the "default args" test (AC-TEST-001) and
"positional argument" test (AC-TEST-002) cover distinct forms of the same
underlying command.

Covers:
- AC-TEST-001: 'kanon repo sync' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo sync' has a happy-path test.
- AC-FUNC-001: 'kanon repo sync' executes successfully with documented default
  behavior (exit 0, "repo sync has finished successfully." on stdout).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Sync Happy Test User"
_GIT_USER_EMAIL = "repo-sync-happy@example.com"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "sync-test-project"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_SYNC = "sync"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_JOBS = "--jobs=1"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT = 0

# Phrase expected in stdout when sync completes without --quiet
_SUCCESS_PHRASE = "repo sync has finished successfully."

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo sync with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo sync' with default args exits 0.

    Verifies that 'kanon repo sync' with no project-name arguments against a
    properly initialized repo directory exits 0 and emits the documented
    completion message.  The conftest _setup_synced_repo helper runs init +
    sync once; these tests call sync a second time to exercise the idempotent
    re-sync path.
    """

    def test_repo_sync_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' with no extra args must exit 0 in a valid repo.

        After a successful 'kanon repo init' and first 'kanon repo sync' (via
        _setup_synced_repo), re-runs 'kanon repo sync' with no positional
        arguments.  A valid initialized repository must allow a second sync
        to complete with exit code 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo sync' exited {result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_sync_with_defaults_emits_success_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' with no extra args must emit the documented completion message.

        On success, 'repo sync' prints "repo sync has finished successfully."
        to stdout.  Verifies this phrase appears after a re-sync of an already
        initialized repository.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo sync' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout of 'kanon repo sync' with default args.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_sync_with_defaults_creates_project_worktree(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' with default args must create the project worktree on disk.

        After a successful 'kanon repo init' and first sync, the project
        directory must exist in the checkout directory.  This verifies that
        sync actually clones/checks-out the manifest project.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        project_dir = checkout_dir / _PROJECT_PATH
        assert project_dir.is_dir(), (
            f"Expected project worktree at {project_dir!r} after 'kanon repo sync', but it does not exist."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo sync has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo sync'.

    'repo sync' accepts optional ``[<project>...]`` positional arguments that
    restrict the sync to specific projects.  Projects can be specified by name
    or by their relative path in the checkout.  Both forms are exercised via
    @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
    )
    def test_repo_sync_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo sync <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init' and first 'kanon repo sync' (via
        _setup_synced_repo), runs 'kanon repo sync <project_ref>' with the
        project reference as a positional argument.  Both the project name
        and the project path are valid references; the command must exit 0
        for each.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo sync {project_ref}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
    )
    def test_repo_sync_with_project_ref_emits_success_phrase(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo sync <project_ref>' emits the success phrase on stdout.

        After a successful init and first sync, re-syncing with a positional
        project reference must produce "repo sync has finished successfully."
        on stdout, confirming the sync completed normally.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo sync {project_ref}' failed: {result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout of 'kanon repo sync {project_ref}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo sync'.

    Verifies that successful 'kanon repo sync' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.

    All three channel assertions share a single class-scoped fixture invocation
    to avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo sync' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo sync' with no positional args.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo sync' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_sync_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo sync' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo sync'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_sync_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo sync' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern.  A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo sync': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_sync_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo sync' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception that was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo sync'.\n  stderr: {channel_result.stderr!r}"
        )
