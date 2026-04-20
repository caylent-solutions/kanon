"""Functional tests for 'kanon repo overview' error paths and --help.

Verifies that:
- 'kanon repo overview --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo overview' -- a boolean flag supplied
  with an unexpected inline value (e.g. --current-branch=unexpected) -- produces
  exit 2 (AC-TEST-003). Note: 'repo overview' accepts '[<project>...]' as an
  optional positional list (not required), so omitting projects entirely is
  valid and causes no argument-parser error. The only exit-2 scenarios available
  for 'repo overview' are unknown flags (AC-TEST-002) and boolean flags supplied
  with unexpected inline values (this class). When optparse receives
  '--current-branch=unexpected' it exits 2 with '--current-branch option does
  not take a value' because boolean store_true flags cannot accept an inline
  value. These tests verify that the argument-parser error path (exit 2) is
  reached and produces an actionable message naming the offending option,
  satisfying the spirit of AC-TEST-003.
- Subcommand-specific precondition failure (missing .repo directory) exits 1
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

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-overview-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-overview-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-overview-option-99"

# Flag with unexpected inline value exercised in AC-TEST-003.
# 'repo overview' defines --current-branch as a boolean store_true flag; the
# optparse parser rejects '--current-branch=unexpected' because boolean flags
# cannot accept an inline value, producing exit 2 with
# '--current-branch option does not take a value'.
_BOOL_FLAG_WITH_VALUE = "--current-branch=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--no-current-branch=badvalue"

# Option name extracted from the bool-flag-with-value token, for use in
# the assertion that the error message names the offending flag.
_BOOL_FLAG_BASE_NAME = "--current-branch"

# Phrase produced by optparse when a boolean flag is supplied with an
# inline value (AC-TEST-003).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo overview"

# Phrase expected in stderr when the .repo directory is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" to stderr when the
# .repo/manifest.xml file cannot be found.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest filename the embedded repo tool names in stderr for precondition
# failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo overview --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewHelp:
    """AC-TEST-001: 'kanon repo overview --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo overview' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo overview --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo overview --help' failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo overview --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' stdout must contain the phrase 'repo overview'.

        The embedded repo tool's help output includes 'repo overview' in the
        Usage line. Confirms the output is specific to the overview subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo overview --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo overview --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo overview --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo overview --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_current_branch_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' stdout must document the --current-branch option.

        The --help output must mention the -c/--current-branch flag so users
        know how to restrict overview output to currently checked-out branches.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo overview --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_BASE_NAME in result.stdout, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} documented in stdout of 'kanon repo overview --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'kanon repo overview --help' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo overview' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo overview {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
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
        """Various unknown 'repo overview' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo overview {bad_flag}' exited {result.returncode}, "
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
        """Various unknown 'repo overview' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo overview {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewBoolFlagWithValue:
    """AC-TEST-003: Boolean flag supplied with an inline value produces exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo overview' parser accepts '[<project>...]' as an optional positional
    list (not required), so omitting projects entirely is valid and causes no
    argument-parser error. The only exit-2 scenarios available for 'repo overview'
    are unknown flags (AC-TEST-002) and boolean flags supplied with unexpected
    inline values (this class). When optparse receives '--current-branch=unexpected'
    it exits 2 with '--current-branch option does not take a value' because boolean
    store_true flags cannot accept an inline value. These tests verify that the
    argument-parser error path (exit 2) is reached and produces an actionable
    message naming the offending option, satisfying the spirit of AC-TEST-003.
    """

    def test_bool_flag_with_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch=unexpected' must exit with code 2.

        The embedded optparse parser rejects '--current-branch=unexpected' because
        boolean store_true flags do not accept inline values, emitting
        '--current-branch option does not take a value' and exiting 2. The kanon
        layer must propagate the exit code 2 unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo overview {_BOOL_FLAG_WITH_VALUE}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch=unexpected' error must name the flag in stderr.

        The embedded optparse parser emits '--current-branch option does not take a value'
        when a boolean flag is supplied with an inline value. The error message
        must include the flag base name so users can identify what was rejected.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_does_not_take_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser emits '--current-branch option does not take a value'
        when a boolean flag is supplied with an inline value. Confirms the
        canonical error phrase appears.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bool-flag-with-value error.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch=unexpected' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the offending token (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag {_BOOL_FLAG_WITH_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [
            _BOOL_FLAG_WITH_VALUE,
            _BOOL_FLAG_WITH_VALUE_ALT_A,
        ],
    )
    def test_various_bool_flags_with_values_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit 2.

        Parametrises over multiple boolean flags supplied with unexpected
        inline values to confirm the exit code is consistently 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo overview {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch=unexpected' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo overview {_BOOL_FLAG_WITH_VALUE}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo overview' requires a valid .repo directory with a readable manifest.xml
    in order to enumerate projects and their branches. When the .repo directory
    is absent or the manifest cannot be parsed, the embedded repo tool exits 1
    with 'error parsing manifest' on stderr. This class verifies that the exit
    code and the error message are both propagated correctly by the kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' with a nonexistent .repo directory must exit with code 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting 'error parsing manifest'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo overview' (no .repo dir) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' without .repo must emit 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the manifest file is absent. This clear, actionable message
        tells users exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo dir.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stdout) == 0, (
            f"'kanon repo overview' (no .repo dir) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' without .repo must produce non-empty stderr output.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'kanon repo overview' (no .repo dir) produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_names_manifest_file_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' without .repo must name the manifest file in stderr.

        The error message must identify the missing manifest file path so
        users know exactly which file to create or where to run repo init.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} path in stderr for missing .repo dir.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' without .repo produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        result_b = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon repo overview' (no .repo dir) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo overview' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo overview' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'kanon repo overview --help' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo overview --help' produced unexpected stderr.\n  stderr: {result.stderr!r}"
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
            "overview",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'no such option' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        Confirms channel discipline for the argparse-level rejection: the
        'does not take a value' error must be routed to stderr. Stdout must be
        clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Bool-flag-with-value error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag {_BOOL_FLAG_WITH_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'error parsing manifest' must appear on stderr, not stdout.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo overview' error class must produce non-empty stderr output.

        Exercises three distinct error classes (unknown flag, bool flag with
        value, missing .repo) and confirms that each produces non-empty
        stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases = [
            ("unknown flag", [_UNKNOWN_FLAG_PRIMARY]),
            ("bool flag with inline value", [_BOOL_FLAG_WITH_VALUE]),
            ("missing .repo directory", []),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                "repo",
                "--repo-dir",
                repo_dir,
                "overview",
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
