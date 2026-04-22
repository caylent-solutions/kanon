"""Functional tests for 'kanon repo help' error paths and --help.

Verifies that:
- 'kanon repo help --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo help' -- supplying a boolean flag
  with an unexpected inline value (e.g. '--all=unexpected') -- produces exit 2
  (AC-TEST-003). Note: 'repo help' accepts an optional positional '[--all|command]'
  argument (not required), so omitting it is valid and causes no argument-parser
  error. There is no required positional argument for this subcommand. The boolean
  flag inline-value path (e.g. '--all=unexpected') is the exit-2 "argument-parser
  rejection" path that most closely satisfies AC-TEST-003's intent. AC-TEST-003
  therefore covers this analogous exit-2 scenario.
- Subcommand-specific precondition failure (invalid command name passed as the
  positional argument to 'repo help') exits 1 with a clear, actionable message
  on stderr (AC-TEST-004). The '--repo-dir' path need not exist because 'repo help'
  does not consult .repo state; the failure is triggered by passing an unrecognised
  subcommand name.
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals extracted here;
# no inline literals in test logic, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

# CLI token constants -- subcommand path used by every invocation.
_SUBCMD_HELP = "help"
_FLAG_HELP = "--help"

# Composed CLI command phrase for diagnostic messages.
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_SUBCMD_HELP}"

# Nonexistent repo-dir path used in tests.
# 'help' does not consult .repo state, so the directory need not exist.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-help-errors-repo-dir"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1

# Phrase that must appear in the '--help' output (AC-TEST-001).
# The Usage line 'repo help [--all|command]' is present in the help output.
_HELP_USAGE_PHRASE = "repo help"

# Flag documented in the '--help' output (AC-TEST-001 detail).
# The '-a' / '--all' flag is listed in the options block.
_HELP_DOCUMENTED_FLAG = "--all"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-help-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-help-option-99"

# Phrase produced by optparse when an unrecognised option is supplied.
_UNKNOWN_OPTION_PHRASE = "no such option"

# Boolean flags with unexpected inline values exercised in AC-TEST-003.
# optparse rejects '--<flag>=<value>' for store_true flags with
# '--<flag> option does not take a value' and exits 2.
_BOOL_FLAG_WITH_VALUE = "--all=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--help-all=badvalue"

# Base name of the boolean flag used in the single-invocation AC-TEST-003 tests.
# Used to assert the flag name appears in the error message.
_BOOL_FLAG_BASE_NAME = "--all"

# Phrase produced by optparse when a boolean flag receives an inline value.
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Invalid subcommand name passed as the positional argument (AC-TEST-004).
# When this is supplied, the embedded repo tool emits "is not a repo command"
# on stderr and exits 1.
_INVALID_COMMAND_NAME = "notavalidhelpcommand"

# Phrase expected in stderr when an invalid command name is passed (AC-TEST-004).
_INVALID_COMMAND_PHRASE = "is not a repo command"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Parametrize tables -- all tuples reference constants; no inline literals.

# AC-TEST-002: three distinct unknown flags, each must exit 2.
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b"),
]

# AC-TEST-003: boolean flags with inline values, each must exit 2.
_BOOL_FLAGS_WITH_INLINE_VALUE: list[tuple[str, str]] = [
    (_BOOL_FLAG_WITH_VALUE, "all-with-value"),
    (_BOOL_FLAG_WITH_VALUE_ALT_A, "help-all-with-value"),
]


# ---------------------------------------------------------------------------
# Helper: build the canonical 'repo help' argv prefix.
# ---------------------------------------------------------------------------


def _build_help_argv(repo_dir: pathlib.Path, *extra: str) -> tuple[str, ...]:
    """Return the argv tuple for a 'kanon repo help' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> help <extra...>

    Args:
        repo_dir: Path to the repo-dir value (need not exist for 'help').
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to ``_run_kanon``.
    """
    return (_CLI_TOKEN_REPO, _CLI_FLAG_REPO_DIR, str(repo_dir), _SUBCMD_HELP) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo help --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpWithHelpFlag:
    """AC-TEST-001: 'kanon repo help --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo help' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. stderr must be empty on success.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _FLAG_HELP))
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' stdout must contain 'repo help'.

        The embedded repo tool includes the subcommand usage line in its
        --help output. The phrase 'repo help' identifies the specific subcommand.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _FLAG_HELP))
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stdout_documents_all_flag(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' stdout must document the '--all' option.

        The --help output must list the '--all' flag so users can discover
        how to show the complete command listing.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _FLAG_HELP))
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_DOCUMENTED_FLAG in result.stdout, (
            f"Expected {_HELP_DOCUMENTED_FLAG!r} documented in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help run.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _FLAG_HELP))
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001. Asserts
        stdout equality between two invocations.
        """
        repo_dir = tmp_path / _NONEXISTENT_REPO_DIR_NAME
        result_a = _run_kanon(*_build_help_argv(repo_dir, _FLAG_HELP))
        result_b = _run_kanon(*_build_help_argv(repo_dir, _FLAG_HELP))
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_HELP}' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo help' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present and actionable.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _UNKNOWN_FLAG_PRIMARY))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _UNKNOWN_FLAG_PRIMARY))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Unknown flag {_UNKNOWN_FLAG_PRIMARY!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [flag for flag, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_various_unknown_flags_exit_2(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo help' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_flag))
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [flag for flag, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_various_unknown_flags_name_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo help' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_flag))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001. Asserts stderr
        equality between invocations.
        """
        repo_dir = tmp_path / _NONEXISTENT_REPO_DIR_NAME
        result_a = _run_kanon(*_build_help_argv(repo_dir, _UNKNOWN_FLAG_PRIMARY))
        result_b = _run_kanon(*_build_help_argv(repo_dir, _UNKNOWN_FLAG_PRIMARY))
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpBoolFlagInlineValue:
    """AC-TEST-003: Argument-parser rejection produces exit 2.

    'repo help' has no required positional argument -- the '[--all|command]'
    argument is entirely optional. Omitting it is valid and exits 0.

    The closest available exit-2 path is supplying a boolean (store_true) flag
    with an unexpected inline value using '--flag=value' syntax. optparse
    rejects this with '--<flag> option does not take a value' and exits 2.
    AC-TEST-003 covers this analogous exit-2 argument-parser rejection scenario.

    Two boolean flags are tested: '--all=unexpected' and '--help-all=badvalue'.
    """

    def test_bool_flag_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --all=unexpected' error must name '--all' in stderr.

        The embedded optparse parser emits '--all option does not take a value'
        when a boolean flag is supplied with an inline value. The error message
        must include the flag base name so users can identify what was rejected.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _BOOL_FLAG_WITH_VALUE))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bool-flag-with-value error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_does_not_take_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --all=unexpected' stderr must contain 'does not take a value'.

        The canonical optparse phrase for a boolean flag supplied with an inline
        value must appear on stderr to give users an actionable error message.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _BOOL_FLAG_WITH_VALUE))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bool-flag-with-value error.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --all=unexpected' error must not leak to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error detail (channel discipline).
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _BOOL_FLAG_WITH_VALUE))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE not in result.stdout, (
            f"Error phrase {_BOOL_FLAG_VALUE_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [flag for flag, _ in _BOOL_FLAGS_WITH_INLINE_VALUE],
        ids=[test_id for _, test_id in _BOOL_FLAGS_WITH_INLINE_VALUE],
    )
    def test_various_bool_flags_with_inline_values_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit 2.

        Parametrises over multiple boolean flags supplied with unexpected
        inline values to confirm the exit code is consistently 2.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_token))
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --all=unexpected' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001. Asserts stderr
        equality between invocations.
        """
        repo_dir = tmp_path / _NONEXISTENT_REPO_DIR_NAME
        result_a = _run_kanon(*_build_help_argv(repo_dir, _BOOL_FLAG_WITH_VALUE))
        result_b = _run_kanon(*_build_help_argv(repo_dir, _BOOL_FLAG_WITH_VALUE))
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_BOOL_FLAG_WITH_VALUE}' produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpInvalidCommandName:
    """AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message.

    'repo help <command>' looks up the named command in the registry. When an
    unrecognised command name is supplied, the embedded repo tool prints
    "repo: '<name>' is not a repo command." to stderr and exits 1. This class
    verifies that the exit code and the error message are both propagated
    correctly by the kanon layer.

    Note: the '--repo-dir' path need not exist because 'repo help' does not
    consult .repo state for this path. The precondition failure is triggered
    solely by passing an unrecognised command name as the positional argument.
    """

    def test_invalid_command_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help notavalidhelpcommand' must exit with code 1.

        When the positional argument is not a recognised repo subcommand name,
        the embedded tool exits 1. The kanon layer must propagate this
        exit code without modification.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_INVALID_COMMAND_NAME}' exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_invalid_command_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help notavalidhelpcommand' stderr must contain 'is not a repo command'.

        The embedded repo tool emits "'<name>' is not a repo command." when
        the positional argument is unrecognised. This actionable message tells
        users exactly which command name was rejected.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _INVALID_COMMAND_PHRASE in result.stderr, (
            f"Expected {_INVALID_COMMAND_PHRASE!r} in stderr for invalid command.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_invalid_command_names_the_command_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help notavalidhelpcommand' stderr must name the invalid command.

        The error message must include the exact command name that was rejected
        so users receive a precise, actionable diagnostic.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _INVALID_COMMAND_NAME in result.stderr, (
            f"Expected {_INVALID_COMMAND_NAME!r} in stderr for invalid command.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_command_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help notavalidhelpcommand' must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error phrase when a precondition failure occurs (channel discipline).
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _INVALID_COMMAND_PHRASE not in result.stdout, (
            f"Error phrase {_INVALID_COMMAND_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_invalid_command_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help notavalidhelpcommand' produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001. Asserts stderr
        equality between invocations.
        """
        repo_dir = tmp_path / _NONEXISTENT_REPO_DIR_NAME
        result_a = _run_kanon(*_build_help_argv(repo_dir, _INVALID_COMMAND_NAME))
        result_b = _run_kanon(*_build_help_argv(repo_dir, _INVALID_COMMAND_NAME))
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_INVALID_COMMAND_NAME}' produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo help' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo help' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies that --help output is routed to stdout.

    This class asserts orthogonal channel properties not duplicated in the
    individual error classes above: it confirms stdout emptiness for error
    cases and ensures no traceback appears on either channel.
    """

    def test_unknown_flag_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error invocation must produce empty stdout.

        Argument-parser errors are routed to stderr. Stdout must be empty
        when optparse rejects an unrecognised flag.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _UNKNOWN_FLAG_PRIMARY))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stdout == "", f"stdout must be empty for unknown-flag error.\n  stdout: {result.stdout!r}"

    def test_bool_flag_with_value_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag inline-value error invocation must produce empty stdout.

        Argument-parser errors are routed to stderr. Stdout must be empty
        when optparse rejects a boolean flag supplied with an inline value.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _BOOL_FLAG_WITH_VALUE))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stdout == "", f"stdout must be empty for bool-flag-with-value error.\n  stdout: {result.stdout!r}"

    def test_invalid_command_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """Invalid command name invocation must produce empty stdout.

        Precondition failures are routed to stderr. Stdout must be empty
        when an invalid command name is passed to 'repo help'.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stdout == "", f"stdout must be empty for invalid-command error.\n  stdout: {result.stdout!r}"

    def test_unknown_flag_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must not emit a Python traceback on stderr.

        A Python traceback on stderr for a flag-parsing error indicates an
        unhandled exception escaped the error-handling layer.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _UNKNOWN_FLAG_PRIMARY))
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr for unknown-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_command_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Invalid command name error must not emit a Python traceback on stderr.

        A Python traceback on stderr for a precondition failure indicates an
        unhandled exception escaped the error-handling layer.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _INVALID_COMMAND_NAME))
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr for invalid-command error.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _FLAG_HELP))
        assert result.returncode == _EXIT_SUCCESS
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE} {_FLAG_HELP}'; "
            f"help must appear on stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE not in result.stderr, (
            f"Help phrase {_HELP_USAGE_PHRASE!r} must not appear on stderr; "
            f"help must be routed to stdout only.\n  stderr: {result.stderr!r}"
        )
