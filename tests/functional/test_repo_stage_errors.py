"""Functional tests for 'kanon repo stage' error paths and --help.

Verifies that:
- 'kanon repo stage --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo stage' -- a boolean flag supplied
  with an unexpected inline value (e.g. --interactive=unexpected) -- produces
  exit 2 (AC-TEST-003). Note: 'repo stage' accepts only optional positional
  project arguments (no required positional), so there is no literal
  "missing required positional" exit-2 path. AC-TEST-003 therefore covers the
  analogous exit-2 scenario: a boolean flag supplied with an unexpected inline
  value using '--flag=value' syntax, which the optparse parser rejects with
  exit 2 because store_true flags do not accept inline values.
- Subcommand-specific precondition failure (missing .repo directory when -i
  is supplied) exits 1 with a clear, actionable message on stderr (AC-TEST-004).
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

Deviation notes (documented here for reviewer clarity):

AC-TEST-003 deviation: the AC wording says "missing required positional
produces exit 2". The 'repo stage' subcommand declares all project args as
optional positionals, so omitting them does not produce exit 2. Instead,
omitting '-i' causes Stage.Execute() to call Usage() and raise UsageError
(exit 1). The closest analogous exit-2 path is a boolean flag supplied with
an unexpected inline value. This class asserts that exact behavior.

AC-TEST-004 deviation: the AC wording says "e.g. .repo missing". When
'-i' is omitted entirely, the subcommand exits 1 due to a UsageError
(Usage() called by Execute()), not due to a missing .repo directory.
AC-TEST-004 tests the precondition failure that arises when '-i' is supplied
against a nonexistent repo-dir, triggering "error parsing manifest" on stderr.

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper or repo-init setup is needed because all tests
# here exercise argument-parsing and subcommand precondition failures that do
# not require a fully initialized .repo directory.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# CLI structural tokens -- extracted so no inline literals appear in test bodies.
_CMD_REPO = "repo"
_CMD_STAGE = "stage"
_OPT_REPO_DIR = "--repo-dir"
_FLAG_HELP = "--help"

# Composed command prefix used in f-string diagnostics.
_CMD_PREFIX = f"kanon {_CMD_REPO} {_CMD_STAGE}"

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-stage-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-stage-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-stage-option-99"

# Flag with unexpected inline value exercised in AC-TEST-003.
# 'repo stage' defines --interactive as a boolean store_true flag; the optparse
# parser rejects '--interactive=unexpected' because boolean flags cannot accept
# an inline value, producing exit 2 with '--interactive option does not take a value'.
_BOOL_FLAG_WITH_VALUE = "--interactive=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--outer-manifest=badvalue"
_BOOL_FLAG_WITH_VALUE_ALT_B = "--this-manifest-only=nope"

# Option name extracted from the bool-flag-with-value token, for use in
# the assertion that the error message names the offending flag.
_BOOL_FLAG_BASE_NAME = "--interactive"

# Phrase produced by optparse when a boolean flag is supplied with an
# inline value (AC-TEST-003).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo stage"

# Phrase expected in stderr when the .repo directory is absent and '-i' is
# supplied (AC-TEST-004). The embedded repo tool prints "error parsing manifest"
# to stderr when the .repo/manifest.xml file cannot be found.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest filename the embedded repo tool names in stderr for precondition
# failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# The '-i' / '--interactive' flag required to exercise the precondition path.
_FLAG_INTERACTIVE = "-i"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo stage --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageHelp:
    """AC-TEST-001: 'kanon repo stage --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo stage' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. No .repo directory is needed -- the embedded repo tool
    handles '--help' at parse time before consulting the filesystem.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_produces_output_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' must produce non-empty output on stdout.

        The embedded repo tool writes its help to stdout. Verifies that the
        passthrough mechanism does not suppress stdout.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed with exit {result.returncode}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' stdout must contain the phrase 'repo stage'.

        The embedded repo tool's help output includes 'repo stage' in the
        Usage line. Confirms the output is specific to the stage subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CMD_PREFIX} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_interactive_flag(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' stdout must document the --interactive flag.

        The --help output must mention '--interactive' (or '-i') so users know
        how to invoke interactive staging.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CMD_PREFIX} {_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_BASE_NAME in result.stdout, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} documented in stdout of "
            f"'{_CMD_PREFIX} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
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
class TestRepoStageUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo stage' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
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
        """Various unknown 'repo stage' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {bad_flag}' exited {result.returncode}, "
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
        """Various unknown 'repo stage' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
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
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageMissingRequiredArg:
    """AC-TEST-003: Boolean flag with inline value produces exit 2.

    Deviation from AC wording: AC-TEST-003 says "missing required positional
    produces exit 2". The 'repo stage' subcommand declares all project args as
    optional positionals (no required positional), so there is no literal
    "missing required positional" exit-2 path. The closest analogous exit-2
    scenario is a boolean flag supplied with an unexpected inline value.

    'repo stage' defines '--interactive' as a store_true flag; the optparse
    parser rejects '--interactive=unexpected' with exit 2 and the message
    '--interactive option does not take a value'. This class asserts that
    exact behavior and satisfies the spirit of AC-TEST-003 (argument-parser
    error path is exercised and produces an actionable message naming the
    offending flag).
    """

    def test_bool_flag_with_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --interactive=unexpected' must exit with code 2.

        The optparse parser rejects a boolean (store_true) flag supplied with
        an inline value. The kanon layer propagates the exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {_BOOL_FLAG_WITH_VALUE}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --interactive=unexpected' stderr must name '--interactive'.

        The error message must identify the flag that was rejected so users
        receive an actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for "
            f"'{_BOOL_FLAG_WITH_VALUE}' error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --interactive=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses the phrase
        'option does not take a value' for store_true flags supplied with an
        inline value. Confirms this canonical phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for "
            f"'{_BOOL_FLAG_WITH_VALUE}' error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --interactive=unexpected' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME not in result.stdout, (
            f"Flag {_BOOL_FLAG_BASE_NAME!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [
            _BOOL_FLAG_WITH_VALUE,
            _BOOL_FLAG_WITH_VALUE_ALT_A,
            _BOOL_FLAG_WITH_VALUE_ALT_B,
        ],
    )
    def test_various_bool_flags_with_value_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit with code 2.

        Parametrises over multiple store_true flags supplied with inline
        values to confirm the exit code is consistently 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CMD_PREFIX} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --interactive=unexpected' produces the same error on repeated calls.

        Verifies that the argument-parsing error for a boolean flag with an
        inline value is stable across invocations, confirming AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CMD_PREFIX} {_BOOL_FLAG_WITH_VALUE}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message.

    Deviation from AC wording: the AC says "e.g. .repo missing". When '-i' is
    omitted entirely, the subcommand exits 1 due to a UsageError (Usage() called
    by Execute()), not due to a missing .repo directory. This class tests the
    precondition failure triggered when '-i' is supplied against a nonexistent
    repo-dir: the embedded repo tool exits 1 with "error parsing manifest" on
    stderr because the .repo/manifest.xml file cannot be found.

    This is the genuine subcommand-level precondition failure for 'repo stage':
    the argument parser succeeds (exit != 2), but the subcommand cannot proceed
    because the .repo structure is absent.
    """

    def test_missing_repo_dir_with_interactive_flag_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with a nonexistent repo-dir must exit with code 1.

        When '-i' is supplied but the .repo directory does not exist, the
        embedded repo tool exits 1 after emitting an error parsing manifest.
        The kanon layer must propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_CMD_PREFIX} {_FLAG_INTERACTIVE}' (no .repo) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with nonexistent repo-dir must emit 'error parsing manifest' on stderr.

        The embedded repo tool emits 'error parsing manifest' followed by the
        manifest.xml path when the .repo directory is absent. This clear,
        actionable message tells users exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_names_manifest_file(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with nonexistent repo-dir stderr must name the manifest file.

        The embedded repo tool names 'manifest.xml' in the error message so
        users know precisely which file is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with nonexistent repo-dir must not emit error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stdout) == 0, (
            f"'{_CMD_PREFIX} {_FLAG_INTERACTIVE}' (no .repo) produced unexpected stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with nonexistent repo-dir must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            f"'{_CMD_PREFIX} {_FLAG_INTERACTIVE}' (no .repo) produced empty stderr; "
            f"error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' with nonexistent repo-dir produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CMD_PREFIX} {_FLAG_INTERACTIVE}' (no .repo) produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo stage' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo stage' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'{_CMD_PREFIX} {_FLAG_HELP}' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
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
            _CMD_STAGE,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"{_UNKNOWN_OPTION_PHRASE!r} phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        Confirms channel discipline: the 'does not take a value' rejection
        must be routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            repo_dir,
            _CMD_STAGE,
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
            _CMD_STAGE,
            _FLAG_INTERACTIVE,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo stage' error class must produce non-empty stderr output.

        Exercises the three distinct error classes (unknown flag, boolean flag
        with inline value, missing .repo with -i) and confirms that each
        produces non-empty stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases = [
            ("unknown flag", [_UNKNOWN_FLAG_PRIMARY]),
            ("bool flag with inline value", [_BOOL_FLAG_WITH_VALUE]),
            ("missing .repo with -i", [_FLAG_INTERACTIVE]),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                _CMD_REPO,
                _OPT_REPO_DIR,
                repo_dir,
                _CMD_STAGE,
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
