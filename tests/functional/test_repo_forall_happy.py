"""Happy-path functional tests for 'kanon repo forall'.

Exercises the happy path of the 'repo forall' subcommand by invoking
``kanon repo forall`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo forall' subcommand runs an arbitrary shell command in each project
working directory. The required flag is ``-c <command>``, which specifies the
command (and optional arguments) to execute. An optional ``[<project>...]``
positional argument restricts execution to specific projects.

On success, 'repo forall' exits 0 and the combined stdout contains any output
produced by the per-project command. When the command is simple (e.g.
``echo HELLO``), each project produces one line of output.

Note on AC-TEST-001 wording: the AC states "'kanon repo forall' with default
args exits 0 in a valid repo". The upstream 'repo forall' command requires the
``-c`` flag to be present; invoking it with zero arguments calls ``Usage()``
and exits non-zero. The phrase "default args" is therefore interpreted as the
simplest valid invocation form -- ``repo forall -c <command>`` with no
project filter -- which is the documented default usage. All tests below
use that form and assert exit code 0.

Note on AC-TEST-002 wording: "every positional argument of 'repo forall' has
a happy-path test." The upstream 'repo forall' positional arguments are
optional ``[<project>...]`` references that restrict which projects execute
the command. Both the no-project-filter form and the project-name/project-path
forms are exercised via @pytest.mark.parametrize.

Covers:
- AC-TEST-001: 'kanon repo forall' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo forall' has a happy-path test.
- AC-FUNC-001: 'kanon repo forall' executes successfully with documented default
  behavior (exit 0, command output on stdout).
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

_GIT_USER_NAME = "Repo Forall Happy Test User"
_GIT_USER_EMAIL = "repo-forall-happy@example.com"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "forall-test-project"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_FORALL = "forall"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_COMMAND = "-c"
_CLI_FLAG_JOBS = "--jobs=1"

# The shell command executed in each project; produces a sentinel line on stdout.
_FORALL_COMMAND = "echo"
_FORALL_ARG = "HELLO"

# Phrase expected in stdout when forall runs echo HELLO in each project.
_EXPECTED_OUTPUT_PHRASE = _FORALL_ARG

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo forall with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo forall' with default args exits 0.

    Verifies that invoking 'kanon repo forall -c echo HELLO' -- the simplest,
    default-arg form of the command (no project filter) -- against a properly
    initialized and synced repo directory exits 0 and emits the command output
    to stdout.

    AC-TEST-001 wording note: 'repo forall' requires -c; "default args" is
    interpreted as the no-project-filter form with a minimal valid command.
    """

    def test_repo_forall_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo HELLO' exits 0 in a valid synced repo.

        After a successful 'kanon repo init' and 'kanon repo sync' (via
        _setup_synced_repo), invokes 'kanon repo forall -c echo HELLO' with
        no project-filter positional arguments. A valid synced repository must
        allow the command to execute in each project and exit 0.
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
            _CLI_TOKEN_FORALL,
            _CLI_FLAG_JOBS,
            _CLI_FLAG_COMMAND,
            _FORALL_COMMAND,
            _FORALL_ARG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo forall {_CLI_FLAG_COMMAND} {_FORALL_COMMAND} {_FORALL_ARG}'"
            f" exited {result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_forall_with_defaults_emits_command_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo HELLO' emits the command's stdout for each project.

        On success, 'repo forall -c echo HELLO' executes echo in each project
        working directory and captures the output. The combined stdout must
        contain the sentinel phrase produced by echo.
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
            _CLI_TOKEN_FORALL,
            _CLI_FLAG_JOBS,
            _CLI_FLAG_COMMAND,
            _FORALL_COMMAND,
            _FORALL_ARG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo forall {_CLI_FLAG_COMMAND} {_FORALL_COMMAND}"
            f" {_FORALL_ARG}' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _EXPECTED_OUTPUT_PHRASE in result.stdout, (
            f"Expected {_EXPECTED_OUTPUT_PHRASE!r} in stdout of"
            f" 'kanon repo forall {_CLI_FLAG_COMMAND} {_FORALL_COMMAND} {_FORALL_ARG}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo forall has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo forall'.

    'repo forall' accepts optional ``[<project>...]`` positional arguments that
    restrict execution to specific projects. Projects can be identified by name
    (as declared in the manifest) or by their relative path in the checkout.
    Both forms are exercised via @pytest.mark.parametrize to ensure each
    genuinely varies the subprocess invocation.
    """

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["project-by-name", "project-by-path"],
    )
    def test_repo_forall_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo forall <project_ref> -c echo HELLO' exits 0 for a valid project.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo forall <project_ref> -c echo HELLO' with the project
        reference as a positional argument. Both the project name and the
        project path are valid references; the command must exit 0 for each.
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
            _CLI_TOKEN_FORALL,
            _CLI_FLAG_JOBS,
            project_ref,
            _CLI_FLAG_COMMAND,
            _FORALL_COMMAND,
            _FORALL_ARG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo forall {project_ref} {_CLI_FLAG_COMMAND}"
            f" {_FORALL_COMMAND} {_FORALL_ARG}'"
            f" exited {result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["project-by-name", "project-by-path"],
    )
    def test_repo_forall_with_project_ref_emits_command_output(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo forall <project_ref> -c echo HELLO' emits command output on stdout.

        After a successful init and sync, running forall with a positional
        project reference must execute the command in that project's working
        directory and emit the sentinel phrase on stdout, confirming forall
        ran the command in the restricted project set.
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
            _CLI_TOKEN_FORALL,
            _CLI_FLAG_JOBS,
            project_ref,
            _CLI_FLAG_COMMAND,
            _FORALL_COMMAND,
            _FORALL_ARG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo forall {project_ref} {_CLI_FLAG_COMMAND}"
            f" {_FORALL_COMMAND} {_FORALL_ARG}' failed: {result.stderr!r}"
        )
        assert _EXPECTED_OUTPUT_PHRASE in result.stdout, (
            f"Expected {_EXPECTED_OUTPUT_PHRASE!r} in stdout of"
            f" 'kanon repo forall {project_ref} {_CLI_FLAG_COMMAND}"
            f" {_FORALL_COMMAND} {_FORALL_ARG}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo forall'.

    Verifies that successful 'kanon repo forall' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.

    All three channel assertions share a single class-scoped fixture invocation
    to avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo forall -c echo HELLO' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo forall -c echo HELLO'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
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
            _CLI_TOKEN_FORALL,
            _CLI_FLAG_JOBS,
            _CLI_FLAG_COMMAND,
            _FORALL_COMMAND,
            _FORALL_ARG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo forall {_CLI_FLAG_COMMAND} {_FORALL_COMMAND}"
            f" {_FORALL_ARG}' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_forall_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo forall' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo forall'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_forall_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo forall' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful"
                f" 'kanon repo forall': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_forall_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo forall' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception that was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo forall'.\n  stderr: {channel_result.stderr!r}"
        )
