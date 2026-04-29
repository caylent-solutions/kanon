"""Functional tests for 'kanon repo selfupdate' in embedded (disabled) mode.

Verifies that:
- 'kanon repo selfupdate' exits non-zero (exit code 1) in embedded mode.
- The documented message is emitted on stderr, not stdout.
- stdout is empty on all invocations.
- No Python tracebacks appear on stderr.

These tests capture stdout and stderr separately via subprocess.run with
capture_output=True, asserting exact channel discipline per AC-TEST-001.

AC-FUNC-001: 'kanon repo selfupdate' exits non-zero (exit code 1).
AC-FUNC-002: stderr contains the literal string
    'selfupdate is not available -- upgrade kanon-cli instead'.
AC-TEST-001: captures stdout and stderr separately; asserts documented message
    is on stderr and exit code is 1.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Selfupdate Disabled Test User"
_GIT_USER_EMAIL = "repo-selfupdate-disabled@example.com"
_PROJECT_PATH = "selfupdate-disabled-test-project"

# CLI token for the selfupdate subcommand
_CLI_TOKEN_SELFUPDATE = "selfupdate"

# Expected exit code for the disabled (embedded-mode) selfupdate
_EXPECTED_EXIT_CODE = 1

# Expected stdout for the disabled selfupdate (must be empty)
_EXPECTED_STDOUT = ""

# Traceback indicator for channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Composed CLI command phrase for diagnostic messages
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_SELFUPDATE}"


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: 'kanon repo selfupdate' exits 1 in embedded mode
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateDisabledExitCode:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo selfupdate' exits 1 in embedded mode.

    Verifies that the disabled selfupdate subcommand exits non-zero (code 1)
    when invoked through the kanon CLI (EMBEDDED=True).
    """

    def test_repo_selfupdate_disabled_exits_one(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' exits 1 when selfupdate is disabled in embedded mode."""
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
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-002: message appears on stderr, not stdout
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateDisabledChannelDiscipline:
    """AC-TEST-001 / AC-FUNC-002: channel discipline for the disabled selfupdate.

    Verifies that the documented selfupdate-disabled message appears on stderr
    and NOT on stdout, and that stdout is empty.

    Uses a class-scoped fixture so the CLI invocation runs once and all
    assertions share the same CompletedProcess result.
    """

    @pytest.fixture(scope="class")
    def selfupdate_result(self, tmp_path_factory: pytest.TempPathFactory):
        """Run 'kanon repo selfupdate' once and return the CompletedProcess."""
        tmp_path = tmp_path_factory.mktemp("selfupdate_disabled_channel")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        return _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )

    def test_disabled_message_appears_on_stderr(self, selfupdate_result) -> None:
        """The embedded-disabled message must appear on stderr."""
        assert SELFUPDATE_EMBEDDED_MESSAGE in selfupdate_result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} to appear on stderr.\n"
            f"  stderr: {selfupdate_result.stderr!r}\n"
            f"  stdout: {selfupdate_result.stdout!r}"
        )

    def test_disabled_message_not_on_stdout(self, selfupdate_result) -> None:
        """The embedded-disabled message must NOT appear on stdout."""
        assert SELFUPDATE_EMBEDDED_MESSAGE not in selfupdate_result.stdout, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} to be absent from stdout.\n"
            f"  stdout: {selfupdate_result.stdout!r}"
        )

    def test_disabled_stdout_is_empty(self, selfupdate_result) -> None:
        """stdout must be empty for the disabled selfupdate."""
        assert selfupdate_result.stdout == _EXPECTED_STDOUT, (
            f"Expected empty stdout from '{_CLI_COMMAND_PHRASE}'.\n  stdout: {selfupdate_result.stdout!r}"
        )

    def test_disabled_no_traceback_on_stderr(self, selfupdate_result) -> None:
        """stderr must not contain a Python traceback on exit 1."""
        assert _TRACEBACK_MARKER not in selfupdate_result.stderr, (
            f"Unexpected Python traceback on stderr for '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {selfupdate_result.stderr!r}"
        )
