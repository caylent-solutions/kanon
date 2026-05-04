"""Happy-path functional tests for 'kanon repo help'.

Exercises the happy path of the 'repo help' subcommand by invoking
``kanon repo help`` as a subprocess. No mocking -- these tests use the
full CLI stack.

The 'repo help' subcommand displays either the list of all common commands
(when called with no positional argument) or detailed help for a specific
subcommand (when called with a subcommand name as its single positional
argument). Both forms exit 0 and write output to stdout. No .repo directory
is required because the embedded tool handles help before consulting any
.repo state.

Covers:
- AC-TEST-001: 'kanon repo help' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo help' has a happy-path test.
- AC-FUNC-001: 'kanon repo help' executes successfully with documented default
  behavior (exits 0, writes command listing to stdout).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel
  leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

# CLI token for the help subcommand
_CLI_TOKEN_HELP = "help"

# A representative subcommand name used for the positional-arg happy-path test.
# 'sync' is universally supported and always present in the command listing.
_CLI_TOKEN_SYNC = "sync"

# Composed CLI command phrase for diagnostic messages
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_HELP}"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT = 0

# Phrase that must appear in the default 'repo help' listing.
# The phrase is part of the documented usage line emitted by the embedded tool.
_HELP_LISTING_PHRASE = "repo COMMAND"

# Phrase that must appear when 'repo help <command>' is invoked for 'sync'.
_SYNC_HELP_PHRASE = "repo sync"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"

# Subdirectory name used as the --repo-dir target in all tests.
# The embedded help handler does not consult .repo state, so the directory
# need not exist.
_NONEXISTENT_REPO_SUBDIR = "nonexistent-repo"

# Parametrize variants for AC-TEST-002: the optional positional argument forms.
# Form 1: no positional argument (default) -- shows the command listing.
# Form 2: positional argument is a known subcommand name -- shows its help.
_POSITIONAL_ARG_FORMS = [
    pytest.param((), _HELP_LISTING_PHRASE, id="no-positional-arg"),
    pytest.param((_CLI_TOKEN_SYNC,), _SYNC_HELP_PHRASE, id="subcommand-name"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001 / AC-TEST-002: all positional-arg happy-path forms
# (the no-positional-arg variant also covers AC-TEST-001 / AC-FUNC-001)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for every positional argument form of 'repo help'.

    The 'repo help' subcommand has one optional positional argument: a
    subcommand name. When omitted the command listing is shown; when provided
    the detailed help for that subcommand is shown. Both forms exit 0.
    """

    @pytest.mark.parametrize("extra_args,expected_phrase", _POSITIONAL_ARG_FORMS)
    def test_repo_help_positional_form_exits_zero(
        self,
        tmp_path: pathlib.Path,
        extra_args: tuple,
        expected_phrase: str,
    ) -> None:
        """'kanon repo help [<command>]' exits 0 for each positional argument form.

        Parametrized over: (no-positional-arg) no extra argument and
        (subcommand-name) with 'sync' as the positional argument. Both
        forms must exit 0.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_SUBDIR)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_HELP,
            *extra_args,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'{_CLI_COMMAND_PHRASE} {extra_args}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("extra_args,expected_phrase", _POSITIONAL_ARG_FORMS)
    def test_repo_help_positional_form_stdout_contains_expected_phrase(
        self,
        tmp_path: pathlib.Path,
        extra_args: tuple,
        expected_phrase: str,
    ) -> None:
        """'kanon repo help [<command>]' stdout contains the expected phrase for each form.

        For the (no-positional-arg) form the listing phrase 'repo COMMAND' must
        appear. For the (subcommand-name) form the phrase 'repo sync' must appear,
        confirming that the subcommand-specific help was emitted.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_SUBDIR)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_HELP,
            *extra_args,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {extra_args}' failed: {result.stderr!r}"
        )
        assert expected_phrase in result.stdout, (
            f"Expected {expected_phrase!r} in stdout of '{_CLI_COMMAND_PHRASE} {extra_args}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo help'.

    Verifies that successful 'kanon repo help' invocations do not write
    Python tracebacks or 'Error:'-prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.

    All channel assertions share a single class-scoped fixture invocation to
    avoid redundant subprocess overhead.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo help' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture so that the subprocess
        executes once and all channel assertions share the result.

        Returns:
            The CompletedProcess from 'kanon repo help' with default args.

        Raises:
            AssertionError: When the prerequisite invocation exits non-zero.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_SUBDIR)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_HELP,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_help_success_stdout_is_non_empty(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo help' must produce non-empty stdout.

        The command listing is written to stdout. Empty stdout would indicate
        that no output was produced, which violates the documented behavior.
        """
        assert len(channel_result.stdout) > 0, (
            f"Expected non-empty stdout from successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {channel_result.stdout!r}\n"
            f"  stderr: {channel_result.stderr!r}"
        )

    def test_repo_help_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo help' must not emit Python tracebacks to stdout.

        A Python traceback on stdout of a successful run indicates that an
        unhandled exception was printed to the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_help_success_has_no_error_prefix_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo help' must not emit 'Error:'-prefixed lines to stdout.

        'Error:' prefixed messages are a stderr-only concern. Any such line on
        stdout indicates cross-channel leakage of error output.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful '{_CLI_COMMAND_PHRASE}': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_repo_help_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo help' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr alongside a zero exit code would indicate an
        unhandled exception escaped alongside the expected output.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
