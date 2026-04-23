"""Functional tests for 'kanon repo status' error paths and --help.

Verifies that:
- 'kanon repo status --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo status' -- a value-requiring option
  (e.g. --jobs) supplied without its argument, or a boolean flag supplied
  with an unexpected inline value (e.g. --orphans=unexpected) -- produces
  exit 2 (AC-TEST-003). Note: 'repo status' accepts only optional project
  names as positional arguments ('Usage: repo status [<project>...]'), so
  there is no literal "missing required positional" exit-2 path. AC-TEST-003
  covers the analogous exit-2 scenarios: value-requiring options supplied
  without their argument value ('--jobs' with no value) and boolean flags
  supplied with an unexpected inline value ('--orphans=unexpected'). Both
  trigger the optparse argument-parser error path (exit 2).
- Subcommand-specific precondition failure (.repo directory missing) exits 1
  with a clear, actionable message on stderr (AC-TEST-004). 'repo status' is
  a PagedCommand that parses manifest.xml at startup; when the .repo
  directory is absent, the command exits 1 with 'error parsing manifest' on
  stderr, naming the manifest file path.
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-status-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-status-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-status-option-99"

# Parametrize table for AC-TEST-002 tests.
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "unknown-flag-xyzzy"),
    (_UNKNOWN_FLAG_ALT_A, "not-a-real-status-flag"),
    (_UNKNOWN_FLAG_ALT_B, "bogus-status-option-99"),
]

# Value-requiring option used in AC-TEST-003 primary test.
# 'repo status' passes --jobs through to the parallel execution runner;
# the optparse parser requires exactly one argument for --jobs. Supplying
# it with no value triggers exit 2 with '--jobs option requires 1 argument'.
_OPTION_REQUIRING_VALUE = "--jobs"

# Error message substring expected in stderr when a value-requiring option
# is supplied without its argument (optparse-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Boolean flag with unexpected inline value for AC-TEST-003 secondary test.
# 'repo status' defines --orphans as a boolean store_true flag; the optparse
# parser rejects '--orphans=unexpected' because boolean flags cannot accept
# an inline value, producing exit 2 with '--orphans option does not take a
# value'.
_BOOL_FLAG_WITH_VALUE = "--orphans=unexpected"
_BOOL_FLAG_BASE_NAME = "--orphans"
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Parametrize table for AC-TEST-003 boolean-flag-with-value tests.
_BOOL_FLAGS_WITH_VALUE: list[tuple[str, str]] = [
    (_BOOL_FLAG_WITH_VALUE, "orphans-with-value"),
]

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
# The embedded repo tool writes "repo status" in its Usage line.
_HELP_USAGE_PHRASE = "repo status"

# Flag mentioned in the --help output to confirm subcommand-specific help.
_HELP_ORPHANS_OPTION = "--orphans"

# Phrase expected in stderr when .repo/manifest.xml is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" when .repo is absent.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest file name that must appear in the stderr message for AC-TEST-004.
_MANIFEST_FILE_NAME = "manifest.xml"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# CLI token constants.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_STATUS = "status"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_HELP = "--help"

# Composed CLI command phrase for diagnostic messages.
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_STATUS}"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# Shared determinism helper (DRY extraction for _is_deterministic tests).
# ---------------------------------------------------------------------------


def _assert_deterministic(
    tmp_path: pathlib.Path,
    extra_args: list,
    expected_exit: int,
    compare_stdout: bool,
) -> None:
    """Run 'kanon repo status [extra_args]' twice and assert output-channel equality.

    Builds a repo_dir path under tmp_path, invokes _run_kanon with the common
    'repo --repo-dir <repo_dir> status' prefix plus extra_args, then asserts:
    - Both calls exit with expected_exit.
    - The chosen output channel (stdout if compare_stdout, else stderr) is
      identical across both calls.

    Used by _is_deterministic test methods to satisfy AC-FUNC-001 without
    repeating invocation boilerplate.

    Args:
        tmp_path: pytest-provided temporary directory root.
        extra_args: CLI arguments appended after 'kanon repo status'.
        expected_exit: The expected exit code for both calls.
        compare_stdout: When True compare stdout; when False compare stderr.
    """
    repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
    result_a = _run_kanon(_CLI_TOKEN_REPO, _CLI_FLAG_REPO_DIR, repo_dir, _CLI_TOKEN_STATUS, *extra_args)
    result_b = _run_kanon(_CLI_TOKEN_REPO, _CLI_FLAG_REPO_DIR, repo_dir, _CLI_TOKEN_STATUS, *extra_args)
    assert result_a.returncode == expected_exit, (
        f"First call exited {result_a.returncode}, expected {expected_exit}.\n"
        f"  stdout: {result_a.stdout!r}\n"
        f"  stderr: {result_a.stderr!r}"
    )
    assert result_b.returncode == expected_exit, (
        f"Second call exited {result_b.returncode}, expected {expected_exit}.\n"
        f"  stdout: {result_b.stdout!r}\n"
        f"  stderr: {result_b.stderr!r}"
    )
    channel_name = "stdout" if compare_stdout else "stderr"
    output_a = result_a.stdout if compare_stdout else result_a.stderr
    output_b = result_b.stdout if compare_stdout else result_b.stderr
    assert output_a == output_b, (
        f"'{_CLI_COMMAND_PHRASE} {extra_args}' produced different {channel_name} on repeated calls.\n"
        f"  first:  {output_a!r}\n"
        f"  second: {output_b!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo status --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusHelp:
    """AC-TEST-001: 'kanon repo status --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo status' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage text
    on stdout with empty stderr. A nonexistent --repo-dir is sufficient
    because the embedded repo tool processes '--help' before reading any
    .repo directory contents.
    """

    def test_help_flag_exits_zero_with_usage_on_stdout_and_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --help' exits 0, emits usage text on stdout, and has empty stderr.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir is sufficient. Merges exit-code,
        non-empty stdout, usage-phrase, and empty-stderr assertions on the same
        subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) == 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_orphans_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --help' stdout must document the --orphans option.

        The --help output must mention the --orphans flag so users know how
        to request orphan detection from the status subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_ORPHANS_OPTION in result.stdout, (
            f"Expected {_HELP_ORPHANS_OPTION!r} documented in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, [_CLI_FLAG_HELP], _EXIT_SUCCESS, compare_stdout=True)


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo status' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2_with_flag_in_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --unknown-flag-xyzzy' exits 2, names the flag in stderr, not stdout.

        Merges exit-code, flag-in-stderr, 'no such option'-in-stderr, and
        no-leak-to-stdout assertions on the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Unknown flag {_UNKNOWN_FLAG_PRIMARY!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [flag for flag, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_various_unknown_flags_exit_2_with_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo status' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_UNKNOWN_FLAG_PRIMARY],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Closest exit-2 path -- missing required option value or
#              boolean flag with inline value
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusMissingRequiredPositional:
    """AC-TEST-003: Closest exit-2 path for 'repo status' argument-parser errors.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo status' parser accepts only optional project-name positionals
    ('Usage: repo status [<project>...]'), so there is no literal "missing
    required positional" exit-2 path. The exit-2 scenarios available are:

    1. Value-requiring options supplied without their argument: '--jobs'
       requires exactly one integer value; supplying '--jobs' with no value
       triggers exit 2 with '--jobs option requires 1 argument' on stderr.
    2. Boolean flags supplied with unexpected inline values: '--orphans' is a
       store_true flag; '--orphans=unexpected' triggers exit 2 with
       '--orphans option does not take a value' on stderr.

    These tests verify that both argument-parser error paths exit 2 and
    produce actionable messages naming the offending option, satisfying the
    spirit of AC-TEST-003.
    """

    def test_jobs_without_value_exits_2_with_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --jobs' without a value exits 2 and names the option in stderr.

        The embedded optparse parser requires one integer argument for --jobs.
        Supplying '--jobs' with no value triggers exit 2 immediately with
        '--jobs option requires 1 argument' on stderr. Merges exit-code,
        option-in-stderr, 'requires'-phrase, and no-leak-to-stdout assertions.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_OPTION_REQUIRING_VALUE}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OPTION_REQUIRING_VALUE in result.stderr, (
            f"Expected {_OPTION_REQUIRING_VALUE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_ARG_PHRASE in result.stderr, (
            f"Expected {_MISSING_ARG_PHRASE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_orphans_with_inline_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --orphans=unexpected' exits 2 with option name in stderr.

        The embedded optparse parser rejects '--orphans=unexpected' because
        boolean store_true flags cannot accept an inline value, emitting
        '--orphans option does not take a value' and exiting 2. Merges
        exit-code, flag-name-in-stderr, does-not-take-value-phrase, and
        no-leak-to-stdout assertions.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_BOOL_FLAG_WITH_VALUE}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag token {_BOOL_FLAG_WITH_VALUE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [token for token, _ in _BOOL_FLAGS_WITH_VALUE],
        ids=[test_id for _, test_id in _BOOL_FLAGS_WITH_VALUE],
    )
    def test_various_bool_flags_with_value_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Boolean flags supplied with inline values must all exit 2.

        Parametrises over boolean flags to confirm the exit code is
        consistently 2 when optparse receives '--flag=value' for a store_true
        flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_required_option_value_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --jobs' (no value) produces the same error on repeated calls.

        Verifies that the argument-parsing error for a missing required option
        argument is stable across invocations, confirming AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_OPTION_REQUIRING_VALUE],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo status' is a PagedCommand that parses manifest.xml at startup.
    When the .repo directory is absent (no manifest.xml), the embedded repo
    tool exits 1 with 'error parsing manifest' on stderr, naming the manifest
    file path. This satisfies AC-TEST-004: the precondition failure exits 1
    and produces a clear, actionable message.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo exits 1.

        When .repo/manifest.xml is absent, the embedded repo tool exits 1
        after emitting an error about the missing manifest. The kanon layer
        must propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo emits 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when .repo/manifest.xml cannot be found. This clear, actionable
        message tells users the .repo directory is missing or incomplete.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_manifest_filename_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo names 'manifest.xml' in stderr.

        The embedded repo tool names the manifest file it failed to parse.
        This makes the error actionable -- users see exactly which file is
        missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error phrase when the precondition failure is triggered
        (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"'error parsing manifest' leaked to stdout for missing .repo.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'{_CLI_COMMAND_PHRASE}' (no .repo) produced empty stderr; error message must appear on stderr."
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' without .repo produces the same error on repeated calls.

        Verifies that the precondition error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [],
            _EXIT_PRECONDITION_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Combined channel and determinism validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusErrorChannelDiscipline:
    """AC-FUNC-001 / AC-CHANNEL-001: Channel discipline for 'kanon repo status' error paths.

    Verifies that for every error path:
    - The error message appears on stderr, not stdout.
    - stdout does not contain the error detail.
    - Error paths are deterministic (same output on repeated identical calls).
    - No Python traceback appears on either channel for any error case.
    """

    def test_unknown_flag_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Unknown-flag error for 'repo status' must appear on stderr, not stdout.

        Supplies an unrecognised flag to 'kanon repo status' and verifies that
        the error detail is on stderr only. Stdout must not contain the flag
        name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"Expected exit {_EXIT_ARGPARSE_ERROR} for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for unknown-flag error."
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Flag {_UNKNOWN_FLAG_PRIMARY!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_option_value_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Missing-value error for 'repo status --jobs' must appear on stderr, not stdout.

        Supplies '--jobs' without a value to 'kanon repo status' and verifies
        that the error detail is on stderr only. Stdout must not contain the
        option name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"Expected exit {_EXIT_ARGPARSE_ERROR} for missing-value.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for missing-value error."
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_precondition_failure_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Precondition-failure error for 'repo status' must appear on stderr, not stdout.

        Invokes 'kanon repo status' against a nonexistent .repo directory and
        verifies that the error detail is on stderr only. Stdout must not
        contain the error phrase (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"Expected exit {_EXIT_PRECONDITION_ERROR} for missing .repo.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for precondition error."
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Error phrase leaked to stdout for precondition failure.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_stdout_only(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status --help' output must appear on stdout only, not stderr.

        Verifies that --help produces non-empty stdout and empty stderr,
        confirming that the help text is routed to the correct channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Expected exit {_EXIT_SUCCESS} for --help.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced empty stdout; usage text must appear on stdout."
        )
        assert len(result.stderr) == 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Unknown-flag error must not emit a Python traceback on stderr.

        The embedded repo parser exits 2 cleanly for unknown flags. No Python
        traceback should appear on stderr; a traceback would indicate an
        unhandled exception instead of a clean argument-parser error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_precondition_failure_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Precondition-failure error must not emit a Python traceback on stderr.

        The embedded repo tool exits 1 with a clean error message for a missing
        .repo directory. No Python traceback should appear on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_STATUS,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr for precondition failure.\n  stderr: {result.stderr!r}"
        )
