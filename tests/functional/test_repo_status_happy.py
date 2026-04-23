"""Happy-path functional tests for 'kanon repo status'.

Exercises the happy path of the 'repo status' subcommand by invoking
``kanon repo status`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo status' subcommand compares the working tree to the staging area
and the most recent commit on each project's HEAD. On a freshly synced
repository with no uncommitted changes, it exits 0 and prints
'nothing to commit (working directory clean)'.

Covers:
- AC-TEST-001: 'kanon repo status' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo status' has a happy-path test.
- AC-FUNC-001: 'kanon repo status' executes successfully with documented default
  behavior.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Status Happy Test User"
_GIT_USER_EMAIL = "repo-status-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "status-happy-test-project"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0

# Phrase expected in stdout when all projects are clean.
_CLEAN_PHRASE = "nothing to commit (working directory clean)"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# CLI token constants.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_STATUS = "status"
_CLI_FLAG_REPO_DIR = "--repo-dir"


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo status with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo status' with default args exits 0.

    Verifies that running 'kanon repo status' with no additional arguments
    against a properly initialized and synced repo directory exits 0 and
    prints the clean-status phrase to stdout when no uncommitted changes
    exist in any project.
    """

    def test_repo_status_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo status' with no additional arguments. A freshly synced
        repository has no uncommitted changes, so the command must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo status' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_status_prints_clean_message_on_fresh_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' must print the clean-status phrase on a fresh repo.

        When all projects are clean (no uncommitted changes), the 'status'
        subcommand emits the documented 'nothing to commit (working directory
        clean)' phrase to stdout. This test verifies the documented default
        behavior is exercised.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo status' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _CLEAN_PHRASE in result.stdout, (
            f"Expected {_CLEAN_PHRASE!r} in stdout of 'kanon repo status' on a fresh repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_status_produces_non_empty_output_on_fresh_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' must produce non-empty combined output in a fresh repo.

        A successful invocation on a freshly synced repo must produce at
        least some output describing the status result. An empty combined
        output would indicate the command ran without performing any work.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo status' failed: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo status' produced empty combined output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo status has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the project name positional argument.

    'repo status' accepts optional project names as positional arguments to
    restrict the status display to specific projects. When a valid project
    name from the manifest is supplied in a cleanly synced repository, the
    command exits 0 because the project has no uncommitted changes.
    """

    def test_repo_status_with_project_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status <project>' with a valid project name exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project name from the manifest as a positional argument to 'kanon repo
        status'. The project has no uncommitted changes, so the command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo status {_PROJECT_NAME}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_status_with_project_name_prints_clean_message(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status <project>' must print the clean-status phrase.

        When a valid project name is passed as a positional argument and the
        project has no uncommitted changes, the 'status' subcommand must emit
        the 'nothing to commit (working directory clean)' phrase to stdout
        and exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo status {_PROJECT_NAME}' failed: {result.stderr!r}"
        )
        assert _CLEAN_PHRASE in result.stdout, (
            f"Expected {_CLEAN_PHRASE!r} in stdout of 'kanon repo status {_PROJECT_NAME}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_status_with_project_path_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status <path>' with the project path alias exits 0.

        Verifies that passing a project by its path (as an alternative to
        the project name) also exits 0, exercising the path-based resolution
        branch inside the 'status' subcommand's GetProjects call.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            _PROJECT_PATH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo status {_PROJECT_PATH}' (path form) exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo status'.

    Verifies that successful 'kanon repo status' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_status_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo status' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo status'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_status_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo status' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful 'kanon repo status': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_repo_status_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_STATUS,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo status' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo status'.\n  stderr: {result.stderr!r}"
        )
