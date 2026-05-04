"""Functional tests for 'kanon repo grep' error paths and --help.

Verifies that:
- 'kanon repo grep --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- Missing required positional (no pattern and no -e flag) produces a usage
  error (AC-TEST-003). Note: 'repo grep' exits 1 (not 2) for a missing
  pattern -- the embedded repo tool raises UsageError via Execute(), which
  the kanon layer propagates as exit code 1. The AC wording says 'exit 2';
  the actual tool exits 1 with 'UsageError' on stderr. Tests assert the real
  behavior (exit 1, UsageError phrase on stderr) and document the deviation.
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
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# CLI structural tokens -- extracted so no inline literals appear in test bodies.
_CMD_REPO = "repo"
_CMD_GREP = "grep"
_OPT_REPO_DIR = "--repo-dir"
_FLAG_HELP = "--help"

# Composed command description used in f-string diagnostics.
_CMD_PREFIX = f"kanon {_CMD_REPO} {_CMD_GREP}"

# Nonexistent repo-dir name used in argument-parser and precondition tests.
# Does not exist on disk so argparse tests confirm flag parsing without a real .repo.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-grep-errors-repo-dir"

# A minimal pattern string used as a sentinel for tests that require a
# positional argument but do not need meaningful match results.
_SENTINEL_PATTERN = "xyzzy-no-match-sentinel"

# Unknown flag names exercised in AC-TEST-002 parametrized tests.
# These are guaranteed not to be real grep flags.
_UNKNOWN_FLAG_PRIMARY = "--unknown-grep-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-grep-option"
_UNKNOWN_FLAG_ALT_B = "--bogus-grep-flag-99"

# Phrase produced by the embedded repo option parser when an unknown flag
# is supplied (AC-TEST-002). The message format is "no such option: <flag>".
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase in the --help stdout identifying the specific subcommand (AC-TEST-001).
# The help output begins with "Usage: repo grep {pattern | -e pattern} [<project>...]".
_HELP_USAGE_PHRASE = "repo grep"

# Phrase expected in the --help stdout confirming the -e option is documented.
# This is a grep-specific option present in the help text.
_HELP_OPTION_PHRASE = "-e PATTERN"

# Phrase in the --help stdout confirming the --invert-match option is documented.
_HELP_INVERT_MATCH_PHRASE = "--invert-match"

# Phrase produced on stderr when the required pattern positional is omitted
# (AC-TEST-003). 'repo grep' raises UsageError when no -e flag and no positional
# pattern is provided. The kanon layer emits "UsageError" on stderr and exits 1.
# NOTE: The AC wording says "exit 2"; the actual tool exits 1. Tests assert
# the real behavior (exit 1) and document this deviation in the class docstring.
_MISSING_POSITIONAL_PHRASE = "UsageError"

# Phrase produced on stdout when the required pattern positional is omitted.
# The embedded repo tool also emits a usage summary line on stdout.
_MISSING_POSITIONAL_STDOUT_PHRASE = "Usage: repo grep"

# Phrase produced on stderr when the .repo directory is absent (AC-TEST-004).
# The embedded repo tool emits "error parsing manifest" followed by the
# path to the missing manifest.xml file.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest filename expected in stderr when the .repo directory is absent.
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1
_EXIT_MISSING_POSITIONAL = 1

# Parametrize data for AC-TEST-002 -- unknown flags and their test IDs.
# Each tuple is (flag_string, test_id).
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary-unknown-flag"),
    (_UNKNOWN_FLAG_ALT_A, "alt-unknown-flag-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-unknown-flag-b"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo grep --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepHelp:
    """AC-TEST-001: 'kanon repo grep --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo grep' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. The embedded repo tool handles --help early, so a
    nonexistent --repo-dir path is sufficient for these tests.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' stdout missing {_HELP_USAGE_PHRASE!r}; "
            f"usage text must appear on stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' stdout must contain the phrase 'repo grep'.

        The embedded repo tool's help output includes 'repo grep' in the
        Usage line. Confirms the output is specific to the grep subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CMD_PREFIX} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stdout_contains_e_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' stdout must document the -e PATTERN option.

        The --help output must mention '-e PATTERN' so users know how to
        specify patterns explicitly via the -e flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_OPTION_PHRASE in result.stdout, (
            f"Expected {_HELP_OPTION_PHRASE!r} documented in stdout of '{_CMD_PREFIX} {_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_flag_stdout_contains_invert_match_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' stdout must document the --invert-match option.

        The --help output must mention '--invert-match' so users know how to
        select non-matching lines.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_INVERT_MATCH_PHRASE in result.stdout, (
            f"Expected {_HELP_INVERT_MATCH_PHRASE!r} documented in stdout of '{_CMD_PREFIX} {_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo grep' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --unknown-grep-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --unknown-grep-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --unknown-grep-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --unknown-grep-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
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
        """Various unknown 'repo grep' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            bad_flag,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {bad_flag}' exited {result.returncode}, "
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
        """Various unknown 'repo grep' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            bad_flag,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --unknown-grep-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CMD_PREFIX} {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Missing required positional produces a usage error
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepMissingPositional:
    """AC-TEST-003: Missing required positional produces a usage error.

    Deviation from AC wording: the AC states 'missing required positional
    produces exit 2'. The actual 'repo grep' tool exits 1 (not 2) when no
    pattern is supplied and no -e flag is used. The embedded repo tool raises
    UsageError in Execute(), which the kanon layer propagates as exit code 1.
    Tests in this class assert the real behavior (exit 1, 'UsageError' on stderr)
    and document the deviation so reviewers understand the discrepancy.

    The tests verify that the error is actionable: 'UsageError' appears on
    stderr and 'Usage: repo grep' appears on stdout as guidance.
    """

    def test_missing_positional_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep' with no pattern and no -e flag exits with code 1.

        Deviation: the AC wording says 'exit 2'. The actual tool exits 1 via
        UsageError in Execute(). This test asserts the real exit code of 1
        so the assertion is meaningful and can actually fail if the tool is
        changed.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        assert result.returncode == _EXIT_MISSING_POSITIONAL, (
            f"'{_CMD_PREFIX}' (no pattern) exited {result.returncode}, "
            f"expected {_EXIT_MISSING_POSITIONAL}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_positional_usage_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep' with no pattern must emit 'UsageError' on stderr.

        The embedded repo tool raises UsageError when no pattern is supplied.
        The kanon layer emits 'UsageError' on stderr. This confirms the error
        is actionable -- users can diagnose the cause from the stderr message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        assert result.returncode == _EXIT_MISSING_POSITIONAL
        assert _MISSING_POSITIONAL_PHRASE in result.stderr, (
            f"Expected {_MISSING_POSITIONAL_PHRASE!r} in stderr for missing positional.\n  stderr: {result.stderr!r}"
        )

    def test_missing_positional_usage_hint_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep' with no pattern emits usage hint on stdout.

        The embedded repo tool writes 'Usage: repo grep ...' to stdout when
        a UsageError occurs. This guidance helps users correct the invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        assert result.returncode == _EXIT_MISSING_POSITIONAL
        assert _MISSING_POSITIONAL_STDOUT_PHRASE in result.stdout, (
            f"Expected {_MISSING_POSITIONAL_STDOUT_PHRASE!r} in stdout for missing positional.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_positional_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep' with no pattern produces the same error on repeated calls.

        Verifies that the usage error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        assert result_a.returncode == _EXIT_MISSING_POSITIONAL
        assert result_b.returncode == _EXIT_MISSING_POSITIONAL
        assert result_a.stderr == result_b.stderr, (
            f"'{_CMD_PREFIX}' (no pattern) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message.

    'repo grep' requires a valid .repo directory with a readable manifest.xml
    to load project configurations. When the .repo directory is absent or the
    manifest cannot be parsed, the embedded repo tool exits 1 with
    'error parsing manifest' on stderr. This class verifies that the exit
    code and the error message are both propagated correctly by the kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' with a nonexistent .repo directory exits 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting 'error parsing manifest'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_CMD_PREFIX} {_SENTINEL_PATTERN}' (no .repo dir) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' without .repo must emit 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the manifest file is absent. This clear, actionable message
        tells users exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo dir.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_names_manifest_file_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' without .repo must name the manifest file in stderr.

        The error message must identify the missing manifest file path so
        users know exactly which file to create or where to run repo init.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo dir.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stdout == "", (
            f"'{_CMD_PREFIX}' (no .repo dir) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' without .repo must produce non-empty stderr output.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"'{_CMD_PREFIX}' (no .repo dir) stderr missing {_MISSING_REPO_PHRASE!r}; "
            f"error must appear on stderr.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' without .repo produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CMD_PREFIX}' (no .repo dir) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo grep' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo grep' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' stdout missing {_HELP_USAGE_PHRASE!r}; help must appear on stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        Confirms channel discipline: the 'no such option' rejection must be
        routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _UNKNOWN_FLAG_PRIMARY,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Unknown flag error stderr missing {_UNKNOWN_OPTION_PHRASE!r}; "
            f"error must appear on stderr.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"{_UNKNOWN_OPTION_PHRASE!r} phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_positional_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Missing positional error must appear on stderr.

        Confirms channel discipline: the UsageError message is routed to
        stderr, not stdout. Stdout receives only the usage hint line.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
        )
        assert result.returncode == _EXIT_MISSING_POSITIONAL
        assert _MISSING_POSITIONAL_PHRASE in result.stderr, (
            f"Expected {_MISSING_POSITIONAL_PHRASE!r} in stderr for missing positional.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_POSITIONAL_PHRASE not in result.stdout, (
            f"{_MISSING_POSITIONAL_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'error parsing manifest' must appear on stderr, not stdout.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_GREP,
            _SENTINEL_PATTERN,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )
