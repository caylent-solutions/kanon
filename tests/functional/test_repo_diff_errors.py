"""Functional tests for 'kanon repo diff' error paths and --help.

Verifies that:
- 'kanon repo diff --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- A value-requiring option (e.g. --jobs) supplied without its argument
  produces exit 2 with the option name in stderr (AC-TEST-003). Note: 'repo
  diff' takes only optional project-filter positionals; omitting them is
  not an error. AC-TEST-003 therefore covers the closest analogous exit-2
  scenario: value-requiring options like '--jobs' that are supplied without
  their argument value trigger the argument-parser error path (exit 2) with
  a message naming the offending option.
- Subcommand-specific precondition failure (.repo directory missing) exits 1
  with a clear, actionable message on stderr (AC-TEST-004).
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
# Module-level constants -- ALL domain literals live here.
# Zero inline literals in test bodies, f-string diagnostics, or parametrize
# tuples.
# ---------------------------------------------------------------------------

# CLI tokens
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_DIFF = "diff"
_FLAG_HELP = "--help"

# Nonexistent repo-dir name used in all tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-diff-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-diff-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-diff-option-99"

# Phrase produced by optparse when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
# The embedded repo tool writes 'repo diff' in the Usage line.
_HELP_USAGE_PHRASE = "repo diff"

# A flag name that must appear in --help output, confirming it is
# subcommand-specific (--absolute is registered in Diff._Options()).
_HELP_EXPECTED_FLAG_PHRASE = "--absolute"

# Value-requiring option used in AC-TEST-003: requires exactly one integer
# argument. Supplying it without a value triggers exit 2 with
# "--jobs option requires 1 argument" on stderr.
_OPTION_REQUIRING_VALUE = "--jobs"

# Error message substring expected in stderr when the option is supplied
# without a value (argparse-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Phrase emitted by the embedded repo tool when the .repo directory is
# absent (AC-TEST-004). The repo tool prints 'error parsing manifest'
# followed by the manifest path.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest file name that must appear in the precondition-failure error
# message (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1

# Sentinel for empty output.
_EMPTY_OUTPUT = ""

# Parametrize data for AC-TEST-002: unknown flags that must each exit 2
# and name themselves in stderr. Each tuple is (flag_token, test_id).
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo diff --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffHelp:
    """AC-TEST-001: 'kanon repo diff --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo diff' is processed before any
    .repo directory or network is consulted, exits 0, and emits the
    subcommand usage text on stdout with empty stderr.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' stdout must contain the phrase 'repo diff'.

        The embedded repo tool's help output includes 'repo diff' in the
        Usage line. Confirms the output is specific to the diff subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFF} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_SUBCMD_DIFF} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stdout_mentions_absolute_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' stdout must document the --absolute option.

        The --help output must mention the --absolute flag so users know how
        to request repository-root-relative file paths. This confirms the
        help text is specific to the diff subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFF} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_EXPECTED_FLAG_PHRASE in result.stdout, (
            f"Expected {_HELP_EXPECTED_FLAG_PHRASE!r} in stdout of "
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' must not produce any output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFF} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stdout: {result.stdout!r}"
        )
        assert result.stderr == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' produces the same stdout on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}' produced different stdout on "
            f"repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo diff' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diff' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        Parametrized over several distinct bogus flag names.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_SUBCMD_DIFF} {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_names_itself_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diff' must appear by name in stderr.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_stderr_contains_no_such_option(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diff' must produce 'no such option' in stderr.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag {bad_flag!r}.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --unknown-flag-xyzzy' stderr is stable across calls.

        Verifies that the error message is identical on repeated invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFF} {_UNKNOWN_FLAG_PRIMARY}' produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Value-requiring option without its argument produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffMissingOptionValue:
    """AC-TEST-003: Value-requiring options without their argument value exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    'repo diff' accepts only optional project-filter positionals; omitting all
    positionals is valid and results in a diff over all projects. There is no
    required positional argument. The only exit-2 scenarios for 'repo diff'
    are unknown flags (AC-TEST-002) and value-requiring options supplied
    without their argument (this class). The '--jobs' option requires exactly
    one integer value. Supplying it without a value triggers the argument-
    parser error path (exit 2) with a message naming the offending option,
    satisfying the spirit of AC-TEST-003.
    """

    def test_jobs_without_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --jobs' without a value must exit 2.

        The embedded option parser requires one argument for --jobs. Supplying
        the flag with no value must exit 2 immediately.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_SUBCMD_DIFF} {_OPTION_REQUIRING_VALUE}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --jobs' without a value must name the option in stderr.

        The error message must identify '--jobs' as the option that requires
        an argument, so users know exactly which flag needs a value.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE in result.stderr, (
            f"Expected {_OPTION_REQUIRING_VALUE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_requires_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --jobs' error message must contain 'requires'.

        The canonical embedded-repo error phrase for missing option arguments
        is '<option> requires 1 argument'. Confirms the phrase 'requires'
        appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _MISSING_ARG_PHRASE in result.stderr, (
            f"Expected {_MISSING_ARG_PHRASE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --jobs' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the option name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_jobs_without_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --jobs' (no value) produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFF} {_OPTION_REQUIRING_VALUE}' (no value) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffPreconditionFailure:
    """AC-TEST-004: Subcommand precondition failure exits 1 with a clear message.

    'repo diff' requires a valid .repo directory so the embedded repo tool
    can locate the manifest and enumerate projects. When the --repo-dir path
    does not exist, the tool exits 1 with 'error parsing manifest' on stderr.
    This class verifies that exit code 1 and the actionable error message are
    both propagated correctly by the kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' with nonexistent .repo must exit 1.

        When the .repo directory is absent, the embedded repo tool exits 1
        after emitting 'error parsing manifest'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_SUBCMD_DIFF}' (no .repo) "
            f"exited {result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_stderr_contains_error_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' without .repo must emit 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr when
        the .repo/manifest.xml file cannot be found. This clear, actionable
        message tells users the required .repo structure is absent.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_names_manifest_file(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' without .repo stderr must name the manifest file.

        The error message must include the manifest filename so users know
        exactly which file was not found.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' without .repo must not emit anything to stdout.

        The precondition-failure error must be routed to stderr only. Stdout
        must be empty (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stdout == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFF}' (no .repo) produced unexpected stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' (missing .repo) stderr is stable across calls.

        Verifies that the precondition-failure error message is identical on
        repeated invocations, confirming the determinism requirement of
        AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFF}' (no .repo) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Determinism and channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo diff' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo diff' appear on stderr only, that stdout remains clean of
    error detail, and that --help output is routed to stdout. No cross-channel
    leakage is permitted for any error class.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff --help' routes help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert result.stdout != _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}' produced empty stdout; "
            f"help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFF} {_FLAG_HELP}' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        The 'no such option' rejection must be routed to stderr. Stdout must
        be empty of error detail (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT, f"Unknown flag error leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_missing_option_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing required option argument error must appear on stderr, not stdout.

        The '--jobs requires 1 argument' rejection must be routed to stderr.
        Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Missing-value error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT, f"Missing-value error leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_precondition_failure_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Precondition-failure error must appear on stderr, not stdout.

        The 'error parsing manifest' error must be routed to stderr only.
        Stdout must be empty when the precondition failure is triggered.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Precondition failure produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT, (
            f"Precondition failure error leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo diff' error class must produce non-empty stderr output.

        Exercises the three distinct error classes (unknown flag, missing option
        argument, missing .repo directory) and confirms that each produces
        non-empty stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases: list[tuple[str, list[str]]] = [
            ("unknown flag", [_UNKNOWN_FLAG_PRIMARY]),
            ("missing option argument", [_OPTION_REQUIRING_VALUE]),
            ("missing .repo directory", []),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                _CMD_REPO,
                _FLAG_REPO_DIR,
                repo_dir,
                _SUBCMD_DIFF,
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
