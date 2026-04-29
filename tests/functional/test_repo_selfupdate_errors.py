"""Functional tests for 'kanon repo selfupdate' error paths and --help.

Verifies that:
- 'kanon repo selfupdate --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo selfupdate' -- a boolean flag
  supplied with an unexpected inline value (e.g. --no-repo-verify=unexpected)
  -- produces exit 2 (AC-TEST-003). Note: 'repo selfupdate' accepts no
  required positional arguments (helpUsage is '%%prog' with no tokens), so
  there is no literal "missing required positional" exit-2 path. AC-TEST-003
  therefore covers the analogous exit-2 scenario: a boolean flag supplied
  with an unexpected inline value using '--flag=value' syntax, which the
  embedded optparse parser rejects with exit 2.
- Subcommand-specific precondition failure (AC-TEST-004). AC-TEST-004 AC
  wording states that '.repo missing exits 1 with clear message.' The actual
  behaviour matches this wording: embedded-mode detection fires before any
  .repo lookup, so the command exits 1 with SELFUPDATE_EMBEDDED_MESSAGE even
  when .repo is absent (updated per E2-F2-S2-T2, declared in E2-F2-S2-T3). The tests in
  TestRepoSelfupdatePreconditionFailure assert this actual behaviour.
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _TRACEBACK_MARKER,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals extracted here;
# no inline literals in test bodies, f-string diagnostics, or parametrize
# tuples.
# ---------------------------------------------------------------------------

# CLI token for the selfupdate subcommand.
_CLI_TOKEN_SELFUPDATE = "selfupdate"

# Composed CLI command phrase for diagnostic messages (no inline literals).
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_SELFUPDATE}"

# CLI flag for --help.
_CLI_FLAG_HELP = "--help"

# Nonexistent repo-dir path used in tests that do not require a real .repo
# directory (argument-parsing tests fire before .repo is consulted).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-selfupdate-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-selfupdate-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-selfupdate-option-99"

# Boolean flag supplied with an unexpected inline value (AC-TEST-003).
# 'repo selfupdate' defines --no-repo-verify as store_false; the optparse
# parser rejects '--no-repo-verify=unexpected' with exit 2.
_CLI_FLAG_NO_REPO_VERIFY = "--no-repo-verify"
_CLI_FLAG_REPO_UPGRADED = "--repo-upgraded"
_BOOL_FLAG_WITH_VALUE = _CLI_FLAG_NO_REPO_VERIFY + "=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = _CLI_FLAG_REPO_UPGRADED + "=badval"
_BOOL_FLAG_BASE_NAME = _CLI_FLAG_NO_REPO_VERIFY

# Phrase produced by optparse when a boolean flag is supplied with an
# inline value (AC-TEST-003 / AC-TEST-002 negative tests).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo selfupdate"

# A subcommand-specific option that appears in the --help output, used to
# verify the help text is specific to selfupdate (not a generic fallback).
_HELP_OPTION_PHRASE = _CLI_FLAG_NO_REPO_VERIFY

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2

# Parametrize tuples for unknown-flag multi-variant tests.
# Tuples are (flag, test_id); no inline literals appear in test bodies.
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b"),
]

# Parametrize tuples for bool-flag-with-value multi-variant tests.
_BOOL_FLAGS_WITH_VALUES: list[tuple[str, str]] = [
    (_BOOL_FLAG_WITH_VALUE, "no-repo-verify"),
    (_BOOL_FLAG_WITH_VALUE_ALT_A, "repo-upgraded"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo selfupdate --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateHelp:
    """AC-TEST-001: 'kanon repo selfupdate --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo selfupdate' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage text on
    stdout. The embedded repo tool processes '--help' at option-parse time, so a
    nonexistent --repo-dir path is sufficient for all tests in this class.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed "
            f"with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' stdout must contain 'repo selfupdate'.

        The embedded repo tool's help output includes 'repo selfupdate' in the
        Usage line. Confirms the output is specific to the selfupdate subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' must produce no error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_no_repo_verify_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' stdout must document the --no-repo-verify option.

        The --help output must mention the --no-repo-verify flag so users
        know how to skip source code verification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_OPTION_PHRASE in result.stdout, (
            f"Expected {_HELP_OPTION_PHRASE!r} documented in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo selfupdate' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _UNKNOWN_FLAG_PRIMARY,
        )
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
        """Various unknown 'repo selfupdate' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_flag,
        )
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
        """Various unknown 'repo selfupdate' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateBoolFlagWithValue:
    """AC-TEST-003: Boolean flag supplied with an inline value produces exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo selfupdate' parser accepts no required positional arguments
    (helpUsage is '%%prog' with no tokens), so omitting positionals entirely
    is valid and causes no argument-parser error. The only exit-2 scenarios
    available for 'repo selfupdate' are unknown flags (AC-TEST-002) and boolean
    flags supplied with unexpected inline values (this class). When optparse
    receives '--no-repo-verify=unexpected' it exits 2 with '--no-repo-verify
    option does not take a value' because boolean store_false flags cannot
    accept an inline value. These tests verify that the argument-parser error
    path (exit 2) is reached and produces an actionable message naming the
    offending option, satisfying the spirit of AC-TEST-003.
    """

    def test_bool_flag_with_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --no-repo-verify=unexpected' error must name the flag base name in stderr.

        The embedded optparse parser emits '--no-repo-verify option does not take a value'
        when a boolean flag is supplied with an inline value. The error message
        must include the flag base name so users can identify what was rejected.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_does_not_take_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --no-repo-verify=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser emits '--no-repo-verify option does not take a value'
        when a boolean flag is supplied with an inline value. Confirms the
        canonical error phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bool-flag-with-value error.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --no-repo-verify=unexpected' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the offending token (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag {_BOOL_FLAG_WITH_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [token for token, _ in _BOOL_FLAGS_WITH_VALUES],
        ids=[test_id for _, test_id in _BOOL_FLAGS_WITH_VALUES],
    )
    def test_various_bool_flags_with_values_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit 2.

        Parametrises over multiple boolean flags supplied with unexpected
        inline values to confirm the exit code is consistently 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --no-repo-verify=unexpected' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_BOOL_FLAG_WITH_VALUE}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdatePreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failure behavior.

    AC wording: '.repo missing exits 1 with clear message.' Updated per
    E2-F2-S2-T2 and formally declared in E2-F2-S2-T3: 'kanon repo selfupdate'
    now exits 1 in embedded mode.
    The embedded-mode detection fires before any .repo lookup. The command
    prints SELFUPDATE_EMBEDDED_MESSAGE to stderr and exits 1, matching both
    the AC wording and the new exit-code contract. The tests below assert
    this actual behaviour and confirm the message is deterministic, clear,
    and actionable.
    """

    _EXIT_DISABLED = 1

    def test_no_repo_dir_exits_disabled(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' without a .repo directory exits 1.

        Embedded-mode detection fires before .repo lookup. The command exits 1
        with SELFUPDATE_EMBEDDED_MESSAGE on stderr even when .repo is absent.
        Updated per E2-F2-S2-T2, declared in E2-F2-S2-T3: selfupdate exits 1
        in embedded mode to signal that selfupdate is unavailable (disabled).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        assert result.returncode == self._EXIT_DISABLED, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) exited {result.returncode}, "
            f"expected {self._EXIT_DISABLED}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_repo_dir_emits_embedded_message_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' without a .repo directory emits the embedded message on stderr.

        Even without a valid .repo directory, embedded-mode detection emits
        SELFUPDATE_EMBEDDED_MESSAGE to stderr. This is the clear, actionable
        message that tells users to upgrade kanon-cli instead of using selfupdate.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} in stderr of '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_repo_dir_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' without a .repo directory produces empty stdout.

        In embedded mode all output routes to stderr. stdout must be empty so
        no output leaks to the wrong channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        assert result.stdout == "", (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_no_repo_dir_embedded_message_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' without .repo produces the same output on repeated calls.

        Verifies that the embedded-mode message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        assert result_a.returncode == self._EXIT_DISABLED
        assert result_b.returncode == self._EXIT_DISABLED
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo selfupdate' errors.

    Verifies that all argument-parsing errors produced by 'kanon repo selfupdate'
    appear on stderr only, and that stdout remains clean of error detail. Also
    verifies that help output is routed to stdout and that successful embedded-mode
    invocations do not emit tracebacks on stderr.

    Orthogonal channel properties only: no exit-code or phrase assertions are
    duplicated here from sibling test classes.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced no stdout; "
            f"help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        Confirms channel discipline: the 'no such option' rejection must be
        routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'{_UNKNOWN_OPTION_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        Confirms channel discipline: the 'does not take a value' rejection must
        be routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Bool-flag-with-value error produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _BOOL_FLAG_VALUE_PHRASE not in result.stdout, (
            f"'{_BOOL_FLAG_VALUE_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_embedded_mode_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Embedded-mode 'kanon repo selfupdate' must not emit tracebacks to stderr.

        Updated per E2-F2-S2-T2, declared in E2-F2-S2-T3: selfupdate exits 1
        in embedded mode. Even with exit code 1, stderr must not contain a
        Python traceback.
        The embedded message and the kanon error suffix are the only expected
        content on stderr; a traceback indicates an unhandled exception.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
