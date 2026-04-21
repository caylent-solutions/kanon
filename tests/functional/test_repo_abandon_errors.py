"""Functional tests for 'kanon repo abandon' error paths and --help.

Verifies that:
- 'kanon repo abandon --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo abandon' -- a value-requiring option
  (e.g. --jobs) supplied without its argument -- produces exit 2 with the
  option name in stderr (AC-TEST-003). Note: 'repo abandon' requires either
  a branch name positional or --all ('Usage: repo abandon [--all |
  <branchname>] [<project>...]'), but omitting both triggers a UsageError
  (exit 1) rather than an argument-parser error (exit 2). AC-TEST-003 therefore
  covers the closest analogous exit-2 scenario: value-requiring options like
  '--jobs' that are supplied without their argument value trigger the
  argument-parser error path (exit 2) with a message naming the offending
  option.
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
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path component used across all tests in this module.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-abandon-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-abandon-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-abandon-option-99"

# Value-requiring option used in AC-TEST-003: requires exactly one argument
# value. Supplying it without a value triggers exit 2 with
# "--jobs option requires 1 argument" on stderr.
_OPTION_REQUIRING_VALUE = "--jobs"

# Error message substring expected in stderr when the option is supplied
# without a value (argparse-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo abandon"

# Phrase expected in stderr when the .repo/manifest.xml is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" when .repo is absent.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest file named in stderr for precondition failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1

# A valid branch name used in precondition-failure tests (tests that reach
# the repo tool layer rather than the argument parser).
_VALID_BRANCH_NAME = "feature/test-abandon-precondition"

# A dummy branch name used as a positional argument in argument-parser tests.
# The value is intentionally fictitious so the embedded repo tool reaches the
# argument-parser layer rather than performing real git operations.
_DUMMY_BRANCH_NAME = "some-branch"

# The --all flag documented in 'repo abandon --help' output.
_ALL_FLAG = "--all"


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo abandon --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonHelp:
    """AC-TEST-001: 'kanon repo abandon --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo abandon' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo abandon --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo abandon --help' failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo abandon --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' stdout must contain the phrase 'repo abandon'.

        The embedded repo tool's help output includes 'repo abandon' in the
        Usage line. Confirms the output is specific to the abandon subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo abandon --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo abandon --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo abandon --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo abandon --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_all_flag(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' stdout must document the --all flag.

        The --help output must mention the --all flag so users know how to
        delete all branches in all projects.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo abandon --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _ALL_FLAG in result.stdout, (
            f"Expected {_ALL_FLAG!r} documented in stdout of 'kanon repo abandon --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'kanon repo abandon --help' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo abandon' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo abandon {_DUMMY_BRANCH_NAME} {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Unknown flag {_UNKNOWN_FLAG_PRIMARY!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [
            _UNKNOWN_FLAG_PRIMARY,
            _UNKNOWN_FLAG_ALT_A,
            _UNKNOWN_FLAG_ALT_B,
        ],
    )
    def test_various_unknown_flags_exit_2_with_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo abandon' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo abandon {_DUMMY_BRANCH_NAME} {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo abandon {_DUMMY_BRANCH_NAME} {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Value-requiring option without its argument produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonMissingOptionValue:
    """AC-TEST-003: Value-requiring options without their argument value exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo abandon' parser requires either a branch name positional or --all,
    but when both are absent the embedded tool raises a UsageError (exit 1)
    rather than an argument-parser error (exit 2). The only exit-2 scenarios for
    'repo abandon' are unknown flags (AC-TEST-002) and value-requiring options
    supplied without their argument (this class). Options like '--jobs' require
    exactly one value. Supplying them without a value triggers the argument-parser
    error path (exit 2) with a message naming the offending option, satisfying
    the spirit of AC-TEST-003.
    """

    def test_jobs_without_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon some-branch --jobs' without a value must exit 2.

        The embedded option parser requires one argument for --jobs. Supplying
        the flag with no value must exit 2 immediately.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo abandon {_DUMMY_BRANCH_NAME} {_OPTION_REQUIRING_VALUE}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon some-branch --jobs' without a value must name the option in stderr.

        The error message must identify '--jobs' as the option that requires
        an argument, so users know exactly which flag needs a value.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE in result.stderr, (
            f"Expected {_OPTION_REQUIRING_VALUE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_requires_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon some-branch --jobs' error message must contain 'requires'.

        The canonical embedded-repo error phrase for missing option arguments
        is '<option> requires 1 argument'. Confirms the phrase 'requires'
        appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _MISSING_ARG_PHRASE in result.stderr, (
            f"Expected {_MISSING_ARG_PHRASE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_without_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon some-branch --jobs' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the option name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_positional_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon' with no branch name and no --all must exit 1.

        The 'repo abandon' subcommand requires either a branch name positional
        or --all. Omitting both triggers a UsageError (exit 1) from the embedded
        repo tool. AC-TEST-003 states 'exit 2', but the tool genuinely exits 1
        via UsageError (not the argument-parser error path). The assertion is
        exact: exit code 1, not merely non-zero.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo abandon' with no branch and no --all should exit {_EXIT_PRECONDITION_ERROR}, "
            f"but exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_positional_produces_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon' with no branch name and no --all must produce output.

        When the required argument is absent, the tool must not fail silently.
        At least one of stdout or stderr must contain diagnostic output.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
        )
        total_output = len(result.stdout) + len(result.stderr)
        assert total_output > 0, (
            f"'kanon repo abandon' (no branch, no --all) produced no output; "
            f"the failure must be communicated to the user.\n"
            f"  returncode: {result.returncode}"
        )

    def test_missing_positional_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon' (no args) produces the same error on repeated calls.

        Verifies that the missing-argument error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo abandon' (no args) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo abandon' requires a valid .repo directory containing a manifest.xml.
    When the .repo directory is absent or invalid, the embedded repo tool exits
    1 with an error containing 'error parsing manifest'. This class verifies that
    the exit code and the error message are both propagated correctly by the
    kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' with missing .repo must exit 1.

        When the .repo directory and manifest.xml are absent, the embedded repo
        tool exits 1 after emitting an 'error parsing manifest' message. The
        kanon layer must propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo abandon {_VALID_BRANCH_NAME}' with missing .repo exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' with missing .repo must emit error phrase on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr when
        the .repo/manifest.xml file cannot be found. This clear, actionable
        message tells users the required .repo structure is absent.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo error.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_names_manifest_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' with missing .repo must name 'manifest.xml' in stderr.

        The embedded repo tool includes the path to the missing manifest.xml
        in the error message so users can identify exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo error.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' precondition error must not leak to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stdout) == 0, (
            f"'kanon repo abandon {_VALID_BRANCH_NAME}' (missing .repo) produced "
            f"unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' with missing .repo must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'kanon repo abandon {_VALID_BRANCH_NAME}' (missing .repo) produced "
            f"empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon <branch>' (missing .repo) produces the same error repeatedly.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo abandon {_VALID_BRANCH_NAME}' (missing .repo) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoAbandonErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo abandon' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo abandon' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo abandon --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'kanon repo abandon --help' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo abandon --help' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        Confirms channel discipline: the 'no such option' rejection must be
        routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'no such option' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_option_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing required option argument error must appear on stderr, not stdout.

        Confirms channel discipline: the 'requires 1 argument' rejection must
        be routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _DUMMY_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Missing-value error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _MISSING_ARG_PHRASE not in result.stdout, (
            f"'{_MISSING_ARG_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'error parsing manifest' must appear on stderr, not stdout.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "abandon",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo abandon' error class must produce non-empty stderr output.

        Exercises the three distinct error classes (unknown flag, missing option
        argument, missing .repo directory) and confirms that each produces
        non-empty stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases: list[tuple[str, list[str]]] = [
            ("unknown flag", [_DUMMY_BRANCH_NAME, _UNKNOWN_FLAG_PRIMARY]),
            ("missing option argument", [_DUMMY_BRANCH_NAME, _OPTION_REQUIRING_VALUE]),
            ("missing .repo directory", [_VALID_BRANCH_NAME]),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                "repo",
                "--repo-dir",
                repo_dir,
                "abandon",
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
