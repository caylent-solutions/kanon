"""Functional tests for 'kanon repo rebase' error paths and --help.

Verifies that:
- 'kanon repo rebase --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo rebase' -- a value-requiring option
  (--whitespace) supplied without its argument -- produces exit 2 with the
  option name in stderr (AC-TEST-003). Note: 'repo rebase' has no required
  positional argument ('Usage: repo rebase {[<project>...] | -i <project>...}');
  all positionals are optional. Omitting positionals does not trigger a
  UsageError -- instead the command proceeds to manifest loading and exits 1
  when .repo is absent. There is therefore no argparse-unreachable missing-
  positional path to document. AC-TEST-003 is satisfied directly by the
  value-requiring option '--whitespace' supplied without its argument, which
  triggers the argument-parser error path (exit 2) with a message naming the
  offending option. This is the same pattern accepted in test_repo_init_errors.py,
  test_repo_prune_errors.py, test_repo_start_errors.py, and
  test_repo_checkout_errors.py when the direct missing-positional exit-2 path
  is unavailable.
- Subcommand-specific precondition failure (e.g. .repo missing) exits 1 with
  clear message on stderr (AC-TEST-004).
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
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-rebase-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-rebase-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-rebase-option-99"

# Value-requiring option used in AC-TEST-003: requires exactly one argument
# value. Supplying it without a value triggers exit 2 with
# "--whitespace option requires 1 argument" on stderr.
_OPTION_REQUIRING_VALUE = "--whitespace"

# Error message substring expected in stderr when the option is supplied
# without a value (argument-parser-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo rebase"

# Phrase expected in stderr when the .repo/manifest.xml is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" when .repo is absent.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest file named in stderr for precondition failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# A generic project reference used in argument-parser-level tests (AC-TEST-002
# and AC-TEST-003). These tests exercise flag or option errors and do not
# require the .repo directory to exist -- the argument parser rejects the
# command before any filesystem access.
_SOME_PROJECT_NAME = "some-project"

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
    """Run 'kanon repo rebase [extra_args]' twice and assert output channel equality.

    Builds a repo_dir path under tmp_path, invokes _run_kanon with the common
    'repo --repo-dir <repo_dir> rebase' prefix plus extra_args, then asserts:
    - Both calls exit with expected_exit.
    - The chosen output channel (stdout if compare_stdout, else stderr) is
      identical across both calls.

    Used by _is_deterministic test methods to satisfy AC-FUNC-001 without
    repeating invocation boilerplate.

    Args:
        tmp_path: pytest-provided temporary directory root.
        extra_args: CLI arguments appended after 'kanon repo rebase'.
        expected_exit: The expected exit code for both calls.
        compare_stdout: When True compare stdout; when False compare stderr.
    """
    repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
    result_a = _run_kanon("repo", "--repo-dir", repo_dir, "rebase", *extra_args)
    result_b = _run_kanon("repo", "--repo-dir", repo_dir, "rebase", *extra_args)
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
        f"'kanon repo rebase {extra_args}' produced different {channel_name} on repeated calls.\n"
        f"  first:  {output_a!r}\n"
        f"  second: {output_b!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo rebase --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseHelp:
    """AC-TEST-001: 'kanon repo rebase --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo rebase' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. All assertions for a single subprocess call are merged
    into one test method where the invocation is identical (DRY).
    """

    def test_help_flag_exits_zero_with_stdout_and_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --help' exits 0, emits non-empty stdout, and has empty stderr.

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
            "rebase",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo rebase --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo rebase --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo rebase --help'.\n  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo rebase --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, ["--help"], _EXIT_SUCCESS, compare_stdout=True)


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo rebase' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2_with_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --unknown-flag-xyzzy' exits 2, names the flag in stderr.

        Merges exit-code, flag-in-stderr, 'no such option'-in-stderr, and
        no-leak-to-stdout assertions on the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo rebase {_UNKNOWN_FLAG_PRIMARY}' exited "
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
        """Various unknown 'repo rebase' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo rebase {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --unknown-flag-xyzzy' produces the same error on repeated calls.

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
# AC-TEST-003: Value-requiring option without its argument produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseMissingOptionValue:
    """AC-TEST-003: Value-requiring options without their argument value exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    AC-TEST-003 targets the argparse-level exit 2 produced when a required
    argument is absent. For 'repo rebase', all positional arguments (project
    references) are optional -- the subcommand signature is:
    'Usage: repo rebase {[<project>...] | -i <project>...}'. Omitting
    positionals does not trigger a UsageError or argument-parser error;
    instead the command proceeds to manifest loading and exits 1 when the
    .repo directory is absent. There is therefore no argparse-unreachable
    missing-positional path to document for 'repo rebase'.

    The natural exit-2 scenario for AC-TEST-003 is the value-requiring option
    '--whitespace' (action='store', metavar=WS) supplied without its required
    argument. Supplying '--whitespace' at the end of the command (with no value
    following it) triggers the argument-parser error path (exit 2) with a
    message naming the offending option, satisfying the spirit and letter of
    AC-TEST-003. This is the same pattern accepted in test_repo_init_errors.py,
    test_repo_prune_errors.py, test_repo_start_errors.py, and
    test_repo_checkout_errors.py.
    """

    def test_whitespace_without_value_exits_2_with_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --whitespace' without a value exits 2 and names the option in stderr.

        The embedded option parser requires one argument for --whitespace
        (action='store', metavar=WS). Supplying the flag with no value must
        exit 2 immediately with '--whitespace option requires 1 argument' on
        stderr. Merges exit-code, option-in-stderr, 'requires'-phrase, and
        no-leak-to-stdout assertions (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo rebase {_OPTION_REQUIRING_VALUE}' (no value) exited "
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

    def test_whitespace_without_value_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --whitespace' (no value) must produce non-empty stderr.

        The argument-parser error for missing '--whitespace' value must always
        produce a non-empty diagnostic message on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo rebase {_OPTION_REQUIRING_VALUE}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}."
        )
        assert len(result.stderr) > 0, (
            f"'kanon repo rebase {_OPTION_REQUIRING_VALUE}' (no value) produced empty stderr; "
            f"error message must appear on stderr."
        )

    def test_missing_required_option_value_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --whitespace' (no value) produces the same error on repeated calls.

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
class TestRepoRebasePreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo rebase' requires a valid .repo directory with a parseable manifest.
    When the .repo directory is absent (no manifest.xml), the embedded repo
    tool exits 1 with 'error parsing manifest' on stderr. This class verifies
    that the exit code and the error message are both propagated correctly.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo exits 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting an error about the missing manifest. The kanon
        layer must propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo rebase' (no .repo) exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo emits 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the .repo/manifest.xml cannot be found. This clear, actionable
        message tells users the .repo directory is missing or incomplete.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_manifest_filename_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo names 'manifest.xml' in stderr.

        The embedded repo tool names the manifest file it failed to parse.
        This makes the error actionable -- users see exactly which file is
        missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error phrase when the precondition failure is triggered
        (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"'error parsing manifest' leaked to stdout for missing .repo.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            "'kanon repo rebase' (no .repo) produced empty stderr; error message must appear on stderr."
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' without .repo produces the same error on repeated calls.

        Verifies that the precondition error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [],
            _EXIT_PRECONDITION_ERROR,
            compare_stdout=False,
        )

    def test_missing_repo_dir_with_project_ref_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase <project>' without .repo exits 1 with manifest error.

        When a project reference is supplied but .repo is absent, the embedded
        repo tool exits 1 after emitting an error about the missing manifest.
        Confirms the precondition check happens before project-ref validation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _SOME_PROJECT_NAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo rebase {_SOME_PROJECT_NAME}' (no .repo) exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Combined channel and determinism validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseErrorChannelDiscipline:
    """AC-FUNC-001 / AC-CHANNEL-001: Channel discipline for 'kanon repo rebase' error paths.

    Verifies that for every error path:
    - The error message appears on stderr, not stdout.
    - stdout does not contain the error detail.
    - Error paths are deterministic (same output on repeated identical calls).
    """

    def test_unknown_flag_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Unknown-flag error for 'repo rebase' must appear on stderr, not stdout.

        Supplies an unrecognised flag to 'kanon repo rebase' and verifies that
        the error detail is on stderr only. Stdout must not contain the flag
        name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
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
        """Missing-value error for 'repo rebase --whitespace' must appear on stderr, not stdout.

        Supplies '--whitespace' without a value to 'kanon repo rebase' and
        verifies that the error detail is on stderr only. Stdout must not
        contain the option name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
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
        """Precondition-failure error for 'repo rebase' must appear on stderr, not stdout.

        Invokes 'kanon repo rebase' against a nonexistent .repo directory and
        verifies that the error detail is on stderr only. Stdout must not
        contain the error phrase (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"Expected exit {_EXIT_PRECONDITION_ERROR} for missing .repo.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for precondition error."
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Error phrase leaked to stdout for precondition failure.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_stdout_only(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase --help' output must appear on stdout only, not stderr.

        Verifies that --help produces non-empty stdout and empty stderr,
        confirming that the help text is routed to the correct channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Expected exit {_EXIT_SUCCESS} for --help.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            "'kanon repo rebase --help' produced empty stdout; usage text must appear on stdout."
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo rebase --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )
