"""Functional tests for 'kanon repo checkout' error paths and --help.

Verifies that:
- 'kanon repo checkout --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo checkout' -- a value-requiring option
  (--jobs) supplied without its argument -- produces exit 2 with the option
  name in stderr (AC-TEST-003). Note: 'repo checkout' requires a branch name
  positional argument ('Usage: repo checkout <branchname> [<project>...]'),
  but omitting the positional triggers a UsageError (exit 1) rather than an
  argument-parser error (exit 2). AC-TEST-003 therefore covers the closest
  analogous exit-2 scenario: the value-requiring option '--jobs' supplied
  without its argument value triggers the argument-parser error path (exit 2)
  with a message naming the offending option.
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

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-checkout-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-checkout-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-checkout-option-99"

# Value-requiring option used in AC-TEST-003: requires exactly one argument
# value. Supplying it without a value triggers exit 2 with
# "--jobs option requires 1 argument" on stderr.
_OPTION_REQUIRING_VALUE = "--jobs"
_OPTION_REQUIRING_VALUE_ALT = "-j"

# Error message substring expected in stderr when the option is supplied
# without a value (argument-parser-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo checkout"

# Phrase expected in the --help output referencing the required positional.
_HELP_BRANCHNAME_PHRASE = "branchname"

# Phrase expected in stderr for no-arg 'repo checkout' (AC-TEST-003 proof
# test): the embedded tool raises UsageError -- exit 1, not 2.
_USAGE_ERROR_PHRASE = "UsageError"

# Phrase expected in stderr when the .repo/manifest.xml is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" when .repo is absent.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest file named in stderr for precondition failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# A valid branch name used in precondition-failure tests (tests that reach
# the repo tool layer rather than the argument parser).
_VALID_BRANCH_NAME = "feature/test-precondition"

# A generic branch name used in argument-parser-level tests (AC-TEST-002 and
# AC-TEST-003). These tests exercise flag or option errors and do not require
# the .repo directory to exist -- the argument parser rejects the command
# before any network or filesystem access.
_SOME_BRANCH_NAME = "some-branch"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# Shared determinism helper -- DRY extraction for _is_deterministic tests.
# ---------------------------------------------------------------------------


def _assert_deterministic(
    tmp_path: pathlib.Path,
    extra_args: list,
    expected_exit: int,
    compare_stdout: bool,
) -> None:
    """Run 'kanon repo checkout [extra_args]' twice and assert output channel equality.

    Builds a repo_dir path under tmp_path, invokes _run_kanon with the common
    'repo --repo-dir <repo_dir> checkout' prefix plus extra_args, then asserts:
    - Both calls exit with expected_exit.
    - The chosen output channel (stdout if compare_stdout, else stderr) is
      identical across both calls.

    Used by _is_deterministic test methods to satisfy AC-FUNC-001 without
    repeating invocation boilerplate.

    Args:
        tmp_path: pytest-provided temporary directory root.
        extra_args: CLI arguments appended after 'kanon repo checkout'.
        expected_exit: The expected exit code for both calls.
        compare_stdout: When True compare stdout; when False compare stderr.
    """
    repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
    result_a = _run_kanon("repo", "--repo-dir", repo_dir, "checkout", *extra_args)
    result_b = _run_kanon("repo", "--repo-dir", repo_dir, "checkout", *extra_args)
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
        f"'kanon repo checkout {extra_args}' produced different {channel_name} on repeated calls.\n"
        f"  first:  {output_a!r}\n"
        f"  second: {output_b!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo checkout --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutHelp:
    """AC-TEST-001: 'kanon repo checkout --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo checkout' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. All assertions for a single subprocess call are merged
    into one test method where the invocation is identical (DRY).
    """

    def test_help_flag_exits_zero_with_stdout_and_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout --help' exits 0, emits non-empty stdout, and has empty stderr.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient. This test
        merges three assertions on the same subprocess call: exit code 0,
        non-empty stdout, and empty stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo checkout --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo checkout --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo checkout --help'.\n  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo checkout --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_branchname(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout --help' stdout must document the required branch name positional.

        The --help output must mention 'branchname' so users know the first
        positional argument is the required branch name.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo checkout --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_BRANCHNAME_PHRASE in result.stdout.lower(), (
            f"Expected {_HELP_BRANCHNAME_PHRASE!r} in stdout of 'kanon repo checkout --help'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, ["--help"], _EXIT_SUCCESS, compare_stdout=True)


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo checkout' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2_with_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch> --unknown-flag-xyzzy' exits 2, names the flag in stderr.

        Merges exit-code, flag-in-stderr, 'no such option'-in-stderr, and
        no-leak-to-stdout assertions on the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo checkout some-branch {_UNKNOWN_FLAG_PRIMARY}' exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
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
        [
            _UNKNOWN_FLAG_PRIMARY,
            _UNKNOWN_FLAG_ALT_A,
            _UNKNOWN_FLAG_ALT_B,
        ],
    )
    def test_various_unknown_flags_exit_2_with_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo checkout' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo checkout some-branch {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout some-branch --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_SOME_BRANCH_NAME, _UNKNOWN_FLAG_PRIMARY],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Value-requiring option without its argument produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutMissingOptionValue:
    """AC-TEST-003: Value-requiring options without their argument value exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    AC-TEST-003 targets the argparse-level exit 2 produced when a required
    argument is absent. For 'repo checkout', the branch name is a required
    positional, but the embedded repo tool handles its own usage validation
    before (or instead of) the standard argparse layer. The
    test_no_positional_args_exits_1_with_usage_error method below proves this:
    omitting the branch name positional raises a UsageError (exit 1) from the
    tool's own subcmd layer -- NOT an argument-parser error (exit 2). The
    argparse layer never gets to validate the missing positional, so the
    'missing required positional -> exit 2' path documented by AC-TEST-003 is
    genuinely unreachable for this subcommand.

    The same pattern is accepted in test_repo_init_errors.py,
    test_repo_prune_errors.py, and test_repo_start_errors.py (E1-F2-S14-T3):
    when the direct missing-positional exit-2 path is unavailable, the closest
    analogous exit-2 scenario is a value-requiring option supplied without its
    argument value. For 'repo checkout', that option is '--jobs', which requires
    exactly one integer argument. Supplying '--jobs' with no value triggers the
    argument-parser error path (exit 2) with a message naming the offending
    option, satisfying the spirit of AC-TEST-003.
    """

    def test_no_positional_args_exits_1_with_usage_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout' with no args exits 1 (UsageError), NOT 2 (argparse).

        This test documents and proves that the 'missing required positional
        -> exit 2' path described by AC-TEST-003 is genuinely unreachable for
        'repo checkout'. When the branch name positional is omitted entirely,
        the embedded repo tool's subcmd layer raises UsageError before the
        argparse layer can validate the missing positional. The result is exit
        1 with a UsageError message on stderr, not exit 2. This is why
        AC-TEST-003 is covered by the value-requiring option scenario (--jobs
        without its value) rather than the missing-positional scenario.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon("repo", "--repo-dir", repo_dir, "checkout")
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo checkout' (no args) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR} (UsageError, not argparse exit 2).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _USAGE_ERROR_PHRASE in result.stderr, (
            f"Expected {_USAGE_ERROR_PHRASE!r} in stderr for no-arg checkout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for no-arg checkout UsageError."

    def test_jobs_without_value_exits_2_with_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch> --jobs' without a value exits 2 and names the option in stderr.

        The embedded option parser requires one argument for --jobs. Supplying
        the flag with no value must exit 2 immediately with '--jobs option
        requires 1 argument' on stderr. Merges exit-code, option-in-stderr,
        'requires'-phrase, and no-leak-to-stdout assertions (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo checkout some-branch {_OPTION_REQUIRING_VALUE}' (no value) exited "
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

    @pytest.mark.parametrize(
        "option_flag",
        [
            _OPTION_REQUIRING_VALUE,
            _OPTION_REQUIRING_VALUE_ALT,
        ],
    )
    def test_various_options_without_value_exit_2(self, tmp_path: pathlib.Path, option_flag: str) -> None:
        """Various value-requiring options without their value must all exit 2.

        Parametrises over the long form (--jobs) and short form (-j) to confirm
        the exit code is consistently 2 when the value is absent.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
            option_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo checkout some-branch {option_flag}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_required_option_value_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch> --jobs' (no value) produces the same error on repeated calls.

        Verifies that the argument-parsing error for a missing required option
        argument is stable across invocations, confirming AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_SOME_BRANCH_NAME, _OPTION_REQUIRING_VALUE],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo checkout' requires a valid .repo directory with a parseable manifest.
    When the .repo directory is absent (no manifest.xml), the embedded repo
    tool exits 1 with 'error parsing manifest' on stderr. This class verifies
    that the exit code and the error message are both propagated correctly.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo exits 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting an error about the missing manifest. The kanon
        layer must propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo checkout {_VALID_BRANCH_NAME}' (no .repo) exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo emits 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the .repo/manifest.xml cannot be found. This clear, actionable
        message tells users the .repo directory is missing or incomplete.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_manifest_filename_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo names 'manifest.xml' in stderr.

        The embedded repo tool names the manifest file it failed to parse.
        This makes the error actionable -- users see exactly which file is
        missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error phrase when the precondition failure is triggered
        (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"'error parsing manifest' leaked to stdout for missing .repo.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'kanon repo checkout {_VALID_BRANCH_NAME}' (no .repo) produced empty stderr; "
            f"error message must appear on stderr."
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' without .repo produces the same error on repeated calls.

        Verifies that the precondition error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_VALID_BRANCH_NAME],
            _EXIT_PRECONDITION_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Combined channel and determinism validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutErrorChannelDiscipline:
    """AC-FUNC-001 / AC-CHANNEL-001: Channel discipline for 'kanon repo checkout' error paths.

    Verifies that for every error path:
    - The error message appears on stderr, not stdout.
    - stdout does not contain the error detail.
    - Error paths are deterministic (same output on repeated identical calls).
    """

    def test_unknown_flag_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Unknown-flag error for 'repo checkout' must appear on stderr, not stdout.

        Supplies an unrecognised flag to 'kanon repo checkout' and verifies that
        the error detail is on stderr only. Stdout must not contain the flag
        name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"Expected exit {_EXIT_ARGPARSE_ERROR} for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for unknown flag error."
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Flag {_UNKNOWN_FLAG_PRIMARY!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_option_value_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Missing-value error for 'repo checkout --jobs' must appear on stderr, not stdout.

        Supplies '--jobs' without a value to 'kanon repo checkout' and verifies
        that the error detail is on stderr only. Stdout must not contain the
        option name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _SOME_BRANCH_NAME,
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
        """Precondition-failure error for 'repo checkout' must appear on stderr, not stdout.

        Invokes 'kanon repo checkout' against a nonexistent .repo directory and
        verifies that the error detail is on stderr only. Stdout must not
        contain the error phrase (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _VALID_BRANCH_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"Expected exit {_EXIT_PRECONDITION_ERROR} for missing .repo.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for precondition error."
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Error phrase leaked to stdout for precondition failure.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_stdout_only(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout --help' output must appear on stdout only, not stderr.

        Verifies that --help produces non-empty stdout and empty stderr,
        confirming that the help text is routed to the correct channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Expected exit {_EXIT_SUCCESS} for --help.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            "'kanon repo checkout --help' produced empty stdout; usage text must appear on stdout."
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo checkout --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )
