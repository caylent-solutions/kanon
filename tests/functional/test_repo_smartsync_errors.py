"""Functional tests for 'kanon repo smartsync' error paths and --help.

Verifies that:
- 'kanon repo smartsync --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo smartsync' -- an option supplied without
  its required argument value (e.g. '--manifest-name' with no value) -- produces
  exit 2 (AC-TEST-003). Note: 'repo smartsync' accepts only optional positional
  arguments (project references), so omitting them entirely is valid and causes
  no argument-parser error. The analogous exit-2 path is a named option that
  requires exactly one argument value (e.g. '--manifest-name', '--jobs-network')
  supplied without that value, which the optparse parser rejects with exit 2
  and a message naming the offending option.
- Subcommand-specific precondition failure (missing .repo directory) exits 1
  with a clear, actionable message on stderr (AC-TEST-004).
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

AC-TEST-003 wording note: AC-TEST-003 states 'Missing required positional
produces exit 2.' The 'repo smartsync' parser declares all positional arguments
as optional project references, so omitting them entirely triggers a
precondition failure (exit 1, covered by AC-TEST-004) rather than an
argument-parser error (exit 2). The exit-2 path is reached when a named option
that requires one argument value is supplied without a value (e.g.
'--manifest-name' with no following token). These tests assert exact actual
behavior and disclose the distinction here.

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _CLI_COMMAND_PHRASE,
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _CLI_TOKEN_SMARTSYNC,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals must appear here only.
# No inline literals in test bodies, f-string diagnostics, or parametrize
# data tuples.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path component used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-smartsync-errors-repo-dir"

# CLI flag for the help option.
_CLI_FLAG_HELP = "--help"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-smartsync-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-smartsync-option-99"

# Named option exercised in AC-TEST-003: requires exactly one argument value.
# Supplying it without a value triggers exit 2 with "option requires 1 argument".
# 'repo smartsync' does not have required positional arguments; the exit-2 path
# is reached via named options with required values supplied without those values.
_OPTION_REQUIRING_VALUE = "--manifest-name"
_OPTION_REQUIRING_VALUE_ALT_A = "--jobs-network"
_OPTION_REQUIRING_VALUE_ALT_B = "--jobs-checkout"

# Error message substring expected in stderr when an option is supplied
# without its required value (argparse-level missing-argument error).
_MISSING_ARG_PHRASE = "requires 1 argument"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
# The smartsync help header contains "repo smartsync".
_HELP_USAGE_PHRASE = "repo smartsync"

# Flag expected to be documented in --help output (AC-TEST-001 detail assertion).
_HELP_DOCUMENTED_FLAG = "--fail-fast"

# Phrase expected in stderr when the .repo directory is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" to stderr.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest filename expected in the stderr error message for AC-TEST-004.
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1

# Parametrize data for AC-TEST-002: (bad_flag, test_id)
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary-unknown-flag"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a-not-real-flag"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b-bogus-option"),
]

# Parametrize data for AC-TEST-003: (option_flag, test_id)
_OPTIONS_REQUIRING_VALUE: list[tuple[str, str]] = [
    (_OPTION_REQUIRING_VALUE, "manifest-name"),
    (_OPTION_REQUIRING_VALUE_ALT_A, "jobs-network"),
    (_OPTION_REQUIRING_VALUE_ALT_B, "jobs-checkout"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo smartsync --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncHelp:
    """AC-TEST-001: 'kanon repo smartsync --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo smartsync' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --help' stdout must contain the phrase 'repo smartsync'.

        The embedded repo tool's help output includes 'repo smartsync' in the
        Usage line. Confirms the output is specific to the smartsync subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_fail_fast_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --help' stdout must document the --fail-fast option.

        The --help output must mention the --fail-fast flag so users know how
        to stop syncing after the first error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_DOCUMENTED_FLAG in result.stdout, (
            f"Expected {_HELP_DOCUMENTED_FLAG!r} documented in stdout of '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_HELP,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
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
class TestRepoSmartSyncUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo smartsync' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
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
        """Various unknown 'repo smartsync' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        Each bad_flag value drives a genuinely distinct subprocess invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
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
        """Various unknown 'repo smartsync' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        Each bad_flag value drives a genuinely distinct subprocess invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Named option without its required value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncMissingRequiredArg:
    """AC-TEST-003: Named options without their required argument value exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo smartsync' parser declares all positional arguments as optional
    project references, so omitting them entirely causes a precondition failure
    (exit 1, covered by AC-TEST-004) rather than an argument-parser error (exit
    2). The only exit-2 scenarios available for 'repo smartsync' are unknown
    flags (AC-TEST-002) and named options that require exactly one argument value
    supplied without that value (this class). Options like '--manifest-name',
    '--jobs-network', and '--jobs-checkout' each require exactly one argument
    value. Supplying them without a value triggers an argument-parser error (exit
    2) with a message that names the offending option, satisfying the spirit of
    AC-TEST-003.
    """

    def test_manifest_name_without_value_requires_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --manifest-name' error message must contain 'requires 1 argument'.

        The canonical embedded-repo error phrase for missing option arguments
        is '<option> requires 1 argument'. Confirms the phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _MISSING_ARG_PHRASE in result.stderr, (
            f"Expected {_MISSING_ARG_PHRASE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_without_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --manifest-name' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the option name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "option_flag",
        [flag for flag, _ in _OPTIONS_REQUIRING_VALUE],
        ids=[test_id for _, test_id in _OPTIONS_REQUIRING_VALUE],
    )
    def test_various_options_without_value_exit_2(self, tmp_path: pathlib.Path, option_flag: str) -> None:
        """Various options without their required value must all exit 2.

        Parametrises over multiple options that require a value to confirm
        the exit code is consistently 2 when the value is absent.
        Each option_flag drives a genuinely distinct 'kanon repo smartsync
        <option>' subprocess invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            option_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {option_flag}' (no value) exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "option_flag",
        [flag for flag, _ in _OPTIONS_REQUIRING_VALUE],
        ids=[test_id for _, test_id in _OPTIONS_REQUIRING_VALUE],
    )
    def test_various_options_without_value_name_option_in_stderr(
        self, tmp_path: pathlib.Path, option_flag: str
    ) -> None:
        """Various options without their required value must each appear by name in stderr.

        Confirms that the error message is specific to the option that was
        supplied without its value, giving users a precise, actionable diagnostic.
        Each option_flag drives a genuinely distinct subprocess invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            option_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert option_flag in result.stderr, (
            f"Expected {option_flag!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_missing_required_arg_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync --manifest-name' (no value) produces the same error on repeated calls.

        Verifies that the argument-parsing error for a missing required option
        argument is stable across invocations, confirming AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _OPTION_REQUIRING_VALUE,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _OPTION_REQUIRING_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_OPTION_REQUIRING_VALUE}' (no value) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo smartsync' requires a valid .repo directory with a readable manifest.xml
    to load project configurations. When the .repo directory is absent or the
    manifest cannot be parsed, the embedded repo tool exits 1 with
    'error parsing manifest' on stderr. This class verifies that the exit
    code and the error message are both propagated correctly by the kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync' with a nonexistent .repo directory must exit with code 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting 'error parsing manifest'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync' without .repo must emit 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the manifest file is absent. This clear, actionable message
        tells users exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo dir.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stdout == "", (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_names_manifest_file_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync' without .repo must name the manifest file in stderr.

        The error message must identify the missing manifest file path so
        users know exactly which file to create or where to run repo init.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} path in stderr for missing .repo dir.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo smartsync' without .repo produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo dir) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo smartsync' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo smartsync' appear on stderr only, and that stdout remains
    clean of error detail. The unique orthogonal channel property verified here
    is the combined view across all three error classes (unknown flag, missing
    option argument, precondition failure) -- each must route its diagnostic to
    stderr and leave stdout empty.

    The precondition_failure_result fixture runs a single invocation once for
    the class and the channel test for the precondition scenario shares the
    result.
    """

    @pytest.fixture(scope="class")
    def precondition_failure_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo smartsync' without .repo once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture so setup and CLI
        invocation execute once and all channel assertions share the result.

        Returns:
            The CompletedProcess from 'kanon repo smartsync' with no .repo directory.

        Raises:
            AssertionError: When the invocation does not produce a precondition error.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_errors_channel")
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"Prerequisite: expected precondition failure exit {_EXIT_PRECONDITION_ERROR}, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

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
            _CLI_TOKEN_SMARTSYNC,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != "", (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'{_UNKNOWN_OPTION_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_required_arg_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing required option argument error must appear on stderr, not stdout.

        Confirms channel discipline: the 'requires 1 argument' rejection must
        be routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != "", (
            f"Missing-value error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _MISSING_ARG_PHRASE not in result.stdout, (
            f"'{_MISSING_ARG_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_precondition_failure_stderr_is_non_empty(
        self, precondition_failure_result: subprocess.CompletedProcess
    ) -> None:
        """Precondition failure must produce non-empty stderr output.

        Confirms channel discipline for the precondition failure scenario:
        the diagnostic must be present on stderr (non-empty), orthogonal to
        the phrase-level assertion already in TestRepoSmartSyncPreconditionFailure.
        """
        assert precondition_failure_result.stderr != "", (
            f"Precondition failure produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {precondition_failure_result.stdout!r}"
        )
