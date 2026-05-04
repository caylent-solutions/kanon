"""Functional tests for 'kanon repo init' error paths and --help.

Verifies that:
- 'kanon repo init --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- Named options supplied without their required argument value produce exit 2
  (AC-TEST-003). Note: 'repo init' declares [manifest url] as an optional
  positional in its parser (see 'Usage: repo init [options] [manifest url]'),
  so omitting it does not produce exit 2 -- it produces exit 1 (covered by
  AC-TEST-004). AC-TEST-003 therefore covers the closest analogous exit-2
  scenario: named options like '--manifest-url' that require exactly one
  argument value but are supplied with no value trigger the argument-parser
  error path (exit 2) with a message naming the offending option.
- Subcommand-specific precondition failures (manifest URL absent) exit 1
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
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper is needed because all tests here exercise
# argument-parsing and subcommand precondition failures that do not require
# a real .repo directory or git repositories.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path component used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-init-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-init-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-init-option-99"

# Named option exercised in AC-TEST-003: requires exactly one argument value.
# Supplying it without a value triggers exit 2 with "option requires 1 argument".
_OPTION_REQUIRING_VALUE = "--manifest-url"
_OPTION_REQUIRING_VALUE_ALT = "--manifest-name"
_OPTION_REQUIRING_VALUE_DEPTH = "--manifest-depth"

# Error message substring expected in stderr when the URL option is supplied
# without a value (argparse-level missing-argument error).
_MISSING_ARG_PHRASE = "requires"

# Phrase expected in stderr when the manifest URL is absent (AC-TEST-004).
# The embedded repo tool prints 'manifest url is required.' to stderr.
_MISSING_URL_PHRASE = "manifest url is required"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo init"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo init --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitHelp:
    """AC-TEST-001: 'kanon repo init --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo init' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo init --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo init --help' failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo init --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' stdout must contain the phrase 'repo init'.

        The embedded repo tool's help output includes 'repo init' in the
        Usage line. Confirms the output is specific to the init subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo init --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo init --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo init --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo init --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_manifest_url_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' stdout must document the manifest URL option.

        The --help output must mention the -u/--manifest-url flag so users
        know how to supply the required manifest URL.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo init --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert "--manifest-url" in result.stdout, (
            f"Expected '--manifest-url' documented in stdout of 'kanon repo init --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'kanon repo init --help' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo init' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo init {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
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
    def test_various_unknown_flags_exit_2(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo init' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo init {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [
            _UNKNOWN_FLAG_PRIMARY,
            _UNKNOWN_FLAG_ALT_A,
            _UNKNOWN_FLAG_ALT_B,
        ],
    )
    def test_various_unknown_flags_name_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo init' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo init {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Missing required argument to a named option produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitMissingRequiredArg:
    """AC-TEST-003: Named options without their required argument value exit 2.

    Options like '--manifest-url', '--manifest-name', and '--manifest-depth'
    each require exactly one argument value. Supplying them without a value
    triggers an argument-parser error (exit 2) with a message that names the
    offending option.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo init' parser declares the manifest URL as an optional positional
    ('Usage: repo init [options] [manifest url]'), so omitting the positional
    entirely causes a precondition failure (exit 1, covered by AC-TEST-004) --
    not an argument-parser error (exit 2). The only exit-2 scenarios available
    for 'repo init' are unknown flags (AC-TEST-002) and named options supplied
    without their required value (this class). These tests verify that the
    argument-parser error path (exit 2) is reached and produces an actionable
    message naming the offending option, satisfying the spirit of AC-TEST-003.
    """

    def test_manifest_url_without_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-url' without a value must exit 2.

        The embedded option parser requires one argument for --manifest-url.
        Supplying the flag with no value must exit 2 immediately.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo init {_OPTION_REQUIRING_VALUE}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_manifest_url_without_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-url' without a value must name the option in stderr.

        The error message must identify '--manifest-url' as the option that
        requires an argument, so users know exactly which flag needs a value.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE in result.stderr, (
            f"Expected {_OPTION_REQUIRING_VALUE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_manifest_url_without_value_requires_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-url' error message must contain 'requires'.

        The canonical embedded-repo error phrase for missing option arguments
        is '<option> requires 1 argument'. Confirms the phrase 'requires'
        appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _MISSING_ARG_PHRASE in result.stderr, (
            f"Expected {_MISSING_ARG_PHRASE!r} in stderr for missing-value error.\n  stderr: {result.stderr!r}"
        )

    def test_manifest_url_without_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-url' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the option name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE not in result.stdout, (
            f"Option {_OPTION_REQUIRING_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_manifest_depth_without_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-depth' without a value must exit 2.

        The --manifest-depth option requires an integer argument. Supplying
        the flag with no value must exit 2 with an argument-parsing error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE_DEPTH,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo init {_OPTION_REQUIRING_VALUE_DEPTH}' (no value) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_manifest_depth_without_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-depth' without a value must name the option in stderr.

        Verifies the error message identifies '--manifest-depth' as the option
        requiring a value.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE_DEPTH,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _OPTION_REQUIRING_VALUE_DEPTH in result.stderr, (
            f"Expected {_OPTION_REQUIRING_VALUE_DEPTH!r} in stderr for missing-value error.\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "option_flag",
        [
            _OPTION_REQUIRING_VALUE,
            _OPTION_REQUIRING_VALUE_ALT,
            _OPTION_REQUIRING_VALUE_DEPTH,
        ],
    )
    def test_various_options_without_value_exit_2(self, tmp_path: pathlib.Path, option_flag: str) -> None:
        """Various options without their required value must all exit 2.

        Parametrises over multiple options that require a value to confirm
        the exit code is consistently 2 when the value is absent.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            option_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo init {option_flag}' (no value) exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_required_arg_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --manifest-url' (no value) produces the same error on repeated calls.

        Verifies that the argument-parsing error for a missing required option
        argument is stable across invocations, confirming AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo init {_OPTION_REQUIRING_VALUE}' (no value) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo init' requires a manifest URL (-u/--manifest-url or as positional).
    When the URL is absent, the embedded repo tool exits 1 with the message
    'manifest url is required.' on stderr. This class verifies that the exit
    code and the error message are both propagated correctly by the kanon layer.
    """

    def test_missing_manifest_url_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' without -u must exit with code 1.

        When the manifest URL is absent, the embedded repo tool exits 1 after
        emitting 'manifest url is required.' The kanon layer must propagate
        this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo init' (no -u) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_manifest_url_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' without -u must emit 'manifest url is required' on stderr.

        The embedded repo tool prints 'manifest url is required.' to stderr
        when no URL is supplied. This clear, actionable message tells users
        exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_URL_PHRASE in result.stderr, (
            f"Expected {_MISSING_URL_PHRASE!r} in stderr for missing manifest URL.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_manifest_url_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' without -u must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stdout) == 0, (
            f"'kanon repo init' (no -u) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_manifest_url_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' without -u must produce non-empty stderr output.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'kanon repo init' (no -u) produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_manifest_url_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' without -u produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo init' (no -u) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo init' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo init' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'kanon repo init --help' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo init --help' produced unexpected stderr.\n  stderr: {result.stderr!r}"
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
            "init",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'no such option' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_required_arg_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing required option argument error must appear on stderr, not stdout.

        Confirms channel discipline: the 'requires 1 argument' rejection must
        be routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _OPTION_REQUIRING_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Missing-value error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _MISSING_ARG_PHRASE not in result.stdout, (
            f"'{_MISSING_ARG_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_url_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'manifest url is required' must appear on stderr, not stdout.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_URL_PHRASE in result.stderr, (
            f"Expected {_MISSING_URL_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_URL_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_URL_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo init' error class must produce non-empty stderr output.

        Exercises the three distinct error classes (unknown flag, missing option
        argument, missing manifest URL) and confirms that each produces non-empty
        stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases = [
            ("unknown flag", [_UNKNOWN_FLAG_PRIMARY]),
            ("missing option argument", [_OPTION_REQUIRING_VALUE]),
            ("missing manifest URL", []),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                "repo",
                "--repo-dir",
                repo_dir,
                "init",
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
