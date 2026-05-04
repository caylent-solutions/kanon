"""Happy-path functional tests for 'kanon repo list'.

Exercises the happy path of the 'repo list' subcommand by invoking
``kanon repo list`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo list' subcommand prints all projects in the manifest, one per line,
in the format ``<project-path> : <project-name>``. On a freshly synced
repository it exits 0 and at least one project line appears in stdout.

Covers:
- AC-TEST-001: 'kanon repo list' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo list' has a happy-path test.
- AC-FUNC-001: 'kanon repo list' executes successfully with documented default behavior.
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

_GIT_USER_NAME = "Repo List Happy Test User"
_GIT_USER_EMAIL = "repo-list-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "list-happy-test-project"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0

# Separator between project path and project name in 'repo list' output.
_LIST_SEPARATOR = " : "

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# CLI token constants.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_LIST = "list"
_CLI_FLAG_REPO_DIR = "--repo-dir"


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo list with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo list' with default args exits 0.

    Verifies that running 'kanon repo list' with no additional arguments
    against a properly initialized and synced repo directory exits 0 and
    prints at least one project entry to stdout.
    """

    def test_repo_list_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo list' with no additional arguments. The command must exit 0.
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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo list' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_prints_project_entry_on_fresh_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list' must print at least one project entry to stdout.

        The 'list' subcommand prints each manifest project as
        ``<path> : <name>`` on stdout. A freshly synced repository has at least
        the one project defined in the manifest, so at least one entry must
        appear.
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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo list' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _LIST_SEPARATOR in result.stdout, (
            f"Expected at least one 'path : name' entry in 'kanon repo list' stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_output_contains_manifest_project_path(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list' must include the manifest project path in stdout.

        The 'list' subcommand outputs each project as ``<path> : <name>``.
        The project path configured in the manifest must appear in that output
        so callers can locate projects on disk.
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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo list' failed: {result.stderr!r}"
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in 'kanon repo list' stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_output_contains_manifest_project_name(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list' must include the manifest project name in stdout.

        The 'list' subcommand outputs each project as ``<path> : <name>``.
        The project name configured in the manifest must appear after the
        separator in the output.
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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo list' failed: {result.stderr!r}"
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in 'kanon repo list' stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo list has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for positional arguments of 'repo list'.

    'repo list' accepts optional project names or paths as positional arguments
    to filter the listing to specific projects. When a valid project name or
    path from the manifest is supplied in a synced repository, the command exits
    0 and lists only the matching project.
    """

    def test_repo_list_with_project_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list <project-name>' with a valid project name exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project name from the manifest as a positional argument to 'kanon repo
        list'. The command must exit 0.
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
            _CLI_TOKEN_LIST,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo list {_PROJECT_NAME}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_with_project_name_shows_that_project(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list <project-name>' must include that project in stdout.

        When a valid project name is passed as a positional argument, the
        'list' subcommand must include the project path and name in stdout,
        confirming the filter resolved to the correct project entry.
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
            _CLI_TOKEN_LIST,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo list {_PROJECT_NAME}' failed: {result.stderr!r}"
        )
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in 'kanon repo list {_PROJECT_NAME}' stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_with_project_path_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list <project-path>' with the project path alias exits 0.

        Verifies that passing a project by its manifest path (as an alternative
        to the project name) also exits 0, exercising the path-based filter
        branch inside the 'list' subcommand.
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
            _CLI_TOKEN_LIST,
            _PROJECT_PATH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo list {_PROJECT_PATH}' (path form) exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_list_with_project_path_shows_that_project(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list <project-path>' must include that project in stdout.

        When a valid project path is passed as a positional argument, the
        'list' subcommand must include the project path and name in stdout.
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
            _CLI_TOKEN_LIST,
            _PROJECT_PATH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo list {_PROJECT_PATH}' failed: {result.stderr!r}"
        )
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in 'kanon repo list {_PROJECT_PATH}' stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo list'.

    Verifies that successful 'kanon repo list' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_list_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list' must not emit Python tracebacks to stdout.

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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo list' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo list'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_list_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list' must not emit 'Error:' prefix to stdout.

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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo list' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful 'kanon repo list': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_repo_list_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list' must not emit Python tracebacks to stderr.

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
            _CLI_TOKEN_LIST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo list' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo list'.\n  stderr: {result.stderr!r}"
        )
