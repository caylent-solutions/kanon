"""Functional tests for flag coverage of 'kanon repo help'.

Exercises every flag registered in ``subcmds/help.py``'s ``_Options()``
method by invoking ``kanon repo help`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior
when flags are omitted.

Flags in ``Help._Options()``:

Boolean (store_true) flags -- accepted without argument, rejected with
``--flag=value`` inline syntax (optparse exits 2):
- ``-a`` / ``--all``        (store_true, dest="show_all"): show the complete list of commands
- ``--help-all``            (store_true, dest="show_all_help"): show the --help of all commands

Note on absence behavior: because the 'help' subcommand does not consult
.repo state, both flags and the no-flag case exit 0 even against a
nonexistent --repo-dir. The absence-default test verifies that 'kanon repo
help' with all optional flags omitted exits 0 and emits the common-commands
listing (not the full list that -a/--all would produce).

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/help.py has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test
  for an invalid value. For boolean flags the negative test supplies an
  inline value (``--flag=value`` syntax) and expects optparse to exit 2.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded domain literals extracted here;
# no literals in test logic, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

# Subcommand token for 'help'.
_SUBCMD_HELP = "help"

# Composed CLI command phrase used in diagnostic messages.
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_SUBCMD_HELP}"

# Expected exit code for all successful invocations.
_EXPECTED_EXIT_CODE = 0

# Argument-parsing error exit code (optparse exits 2).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name. 'help' does not consult .repo state, so all
# valid-flag tests can use this directory without any setup overhead.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-help-flags-repo-dir"

# Inline-value suffix for negative tests on boolean (store_true) flags.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true flag is supplied with an inline ``=value`` suffix.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Phrase emitted on stderr when a store_true flag receives an inline value.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# CLI flag token constants for Help._Options() flags.
# ---------------------------------------------------------------------------

_CLI_FLAG_ALL_SHORT = "-a"
_CLI_FLAG_ALL_LONG = "--all"
_CLI_FLAG_HELP_ALL = "--help-all"

# ---------------------------------------------------------------------------
# Expected output phrases for each flag variant.
# These phrases confirm that the correct branch of Help.Execute() ran.
# ---------------------------------------------------------------------------

# Phrase emitted when -a/--all is supplied (full command listing).
_ALL_COMMANDS_PHRASE = "The complete list of recognized repo commands is:"

# Phrase emitted when --help-all is supplied (per-command help blocks).
_HELP_ALL_PHRASE = "[abandon] Summary"

# Phrase emitted when no flags are supplied (common commands listing).
_COMMON_COMMANDS_PHRASE = "The most commonly used repo commands are:"

# Subcommand name used to verify the full listing (COMMON=False in forall.py).
_FORALL_SUBCMD_NAME = "forall"

# ---------------------------------------------------------------------------
# Parametrize data tables for AC-TEST-001 valid-value tests.
# Each entry: (flag_token, expected_phrase, test_id).
# 'help' exits 0 for all valid-flag invocations (no .repo state required).
# ---------------------------------------------------------------------------

_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str, str]] = [
    (_CLI_FLAG_ALL_SHORT, _ALL_COMMANDS_PHRASE, "short-all"),
    (_CLI_FLAG_ALL_LONG, _ALL_COMMANDS_PHRASE, "long-all"),
    (_CLI_FLAG_HELP_ALL, _HELP_ALL_PHRASE, "long-help-all"),
]

# Long-form boolean flags used in AC-TEST-002 negative tests.
# Only long-form flags support '--flag=value' inline syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_ALL_LONG, "all"),
    (_CLI_FLAG_HELP_ALL, "help-all"),
]


# ---------------------------------------------------------------------------
# Helper: build the canonical help argv prefix.
# ---------------------------------------------------------------------------


def _build_help_argv(repo_dir: pathlib.Path, *extra: str) -> tuple[str, ...]:
    """Return the argv tuple for a 'kanon repo help' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> help <extra...>

    Args:
        repo_dir: Path to the repo-dir value (need not exist for 'help').
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to ``_run_kanon``.
    """
    return (_CLI_TOKEN_REPO, _CLI_FLAG_REPO_DIR, str(repo_dir), _SUBCMD_HELP) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/help.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/help.py has a valid-value test.

    Exercises each flag registered in ``Help._Options()`` by invoking
    'kanon repo help' with the flag. Both flags are boolean (store_true), and
    because the 'help' subcommand does not consult .repo state, all invocations
    use a nonexistent repo-dir and exit 0.

    Valid-value tests confirm:
    - The flag is accepted by optparse (exit 0, not exit 2).
    - The expected output phrase for that flag variant is present in stdout.

    Flags covered:
    - ``-a`` / ``--all``  (store_true, dest="show_all"): show complete command listing
    - ``--help-all``      (store_true, dest="show_all_help"): show --help for all commands
    """

    @pytest.mark.parametrize(
        "flag,expected_phrase",
        [(flag, phrase) for flag, phrase, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_boolean_flag_stdout_contains_expected_phrase(
        self, tmp_path: pathlib.Path, flag: str, expected_phrase: str
    ) -> None:
        """Each boolean flag produces the expected output phrase in stdout.

        Confirms that the correct branch of ``Help.Execute()`` ran by
        checking for the canonical phrase associated with each flag variant.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, flag))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: flag {flag!r} exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert expected_phrase in result.stdout, (
            f"Expected {expected_phrase!r} in stdout for flag {flag!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with invalid values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Both flags in ``Help._Options()`` are boolean (store_true). None accept a
    typed or enumerated value. The applicable negative test for a boolean flag
    is to supply it with an unexpected inline value using the ``--flag=value``
    syntax. optparse exits 2 with '--<flag> option does not take a value' for
    such inputs.

    This class verifies that every long-form boolean flag produces exit 2 when
    supplied with an inline value, that the canonical 'does not take a value'
    phrase is present in stderr, and that the error does not leak to stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr and must contain the canonical 'does not take a value' phrase.
        Stdout must not contain the error detail.
        """
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_token))
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_all_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--all=unexpected' error must name '--all' in stderr.

        The embedded optparse parser emits '--all option does not take a value'
        when '--all=unexpected' is supplied. Confirms the canonical flag name
        appears in the error message.
        """
        bad_token = _CLI_FLAG_ALL_LONG + _INLINE_VALUE_SUFFIX
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_token))
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_ALL_LONG in result.stderr, (
            f"Expected {_CLI_FLAG_ALL_LONG!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )

    def test_help_all_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--help-all=unexpected' error must name '--help-all' in stderr.

        The embedded optparse parser emits '--help-all option does not take
        a value' when '--help-all=unexpected' is supplied. Confirms the
        canonical flag name appears in the error message.
        """
        bad_token = _CLI_FLAG_HELP_ALL + _INLINE_VALUE_SUFFIX
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_token))
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_HELP_ALL in result.stderr, (
            f"Expected {_CLI_FLAG_HELP_ALL!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each ``Help._Options()`` flag uses the documented default
    when omitted. Both flags are store_true with implicit default=False:

    - ``show_all`` defaults to False: the common-commands listing is shown
      (not the full list that -a/--all produces).
    - ``show_all_help`` defaults to False: per-command --help blocks are not
      shown.

    When all optional flags are omitted 'kanon repo help' exits 0 and emits
    the common-commands listing (distinguished by the canonical phrase
    'The most commonly used repo commands are:').
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help' with all optional flags omitted exits 0.

        When neither -a/--all nor --help-all is supplied, both boolean flags
        default to False and the command displays the common-commands listing.
        Verifies that no flag is required and the defaults produce a successful
        exit 0 invocation.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' with all flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_emits_common_commands_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo help' with all flags omitted emits the common-commands phrase.

        When both flags default to False, the 'help' subcommand calls
        ``_PrintCommonCommands()`` which emits the canonical phrase
        'The most commonly used repo commands are:'. Verifies the correct
        default branch of ``Help.Execute()`` is taken.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _COMMON_COMMANDS_PHRASE in result.stdout, (
            f"Expected {_COMMON_COMMANDS_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE}' "
            f"with all flags omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flag_absent_does_not_emit_full_listing_phrase(self, tmp_path: pathlib.Path) -> None:
        """Omitting -a/--all means the full-listing phrase is absent from stdout.

        When --all is absent (default False), ``Help.Execute()`` does not call
        ``_PrintAllCommands()`` and the full-listing phrase
        'The complete list of recognized repo commands is:' must not appear.
        This distinguishes the default-False behavior from the --all case.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _ALL_COMMANDS_PHRASE not in result.stdout, (
            f"Unexpected full-listing phrase {_ALL_COMMANDS_PHRASE!r} found in stdout "
            f"when -a/--all was omitted.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_all_flag_absent_does_not_emit_per_command_help_phrase(self, tmp_path: pathlib.Path) -> None:
        """Omitting --help-all means the per-command help phrase is absent from stdout.

        When --help-all is absent (default False), ``Help.Execute()`` does not
        call ``_PrintAllCommandHelp()`` and the per-command block phrase
        '[abandon] Summary' must not appear in stdout.
        This distinguishes the default-False behavior from the --help-all case.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_ALL_PHRASE not in result.stdout, (
            f"Unexpected per-command help phrase {_HELP_ALL_PHRASE!r} found in stdout "
            f"when --help-all was omitted.\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of flags documented in
    ``Help._Options()``:

    - ``-a`` / ``--all``: show the complete list of commands. Per the help
      text: 'show the complete list of commands'. Supplying --all must emit
      the full listing (all commands, not only common ones).

    - ``--help-all``: show the --help of all commands. Per the help text:
      'show the --help of all commands'. Supplying --help-all must emit
      per-command help blocks for every subcommand.
    """

    def test_all_flag_listing_contains_forall(self, tmp_path: pathlib.Path) -> None:
        """--all listing includes 'forall' (a non-COMMON command absent from the default listing).

        The 'forall' subcommand has COMMON = False so it does not appear in
        the default common-commands listing. Supplying --all must include it,
        confirming the full listing (not the filtered common listing) is shown.
        """
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, _CLI_FLAG_ALL_LONG))
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _FORALL_SUBCMD_NAME in result.stdout, (
            f"Expected {_FORALL_SUBCMD_NAME!r} in stdout for '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}'.\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful 'kanon repo help' invocations do not write Python
    tracebacks or 'Error:'-prefixed messages to stdout, and that
    argument-parsing errors appear on stderr only. No cross-channel leakage
    is permitted.

    The three channel assertions for the valid-flags case share a single
    class-scoped fixture invocation to avoid redundant subprocess overhead.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo help --all' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture so the subprocess
        executes once and all channel assertions share the result.

        Returns:
            The CompletedProcess from 'kanon repo help --all'.

        Raises:
            AssertionError: When the prerequisite invocation exits non-zero.
        """
        tmp_path = tmp_path_factory.mktemp("help_flags_channel")
        result = _run_kanon(
            *_build_help_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                _CLI_FLAG_ALL_LONG,
            )
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}' failed "
            f"with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_valid_flags_invocation_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo help --all' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo help --all' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception that escaped alongside the expected output.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )

    def test_valid_flags_invocation_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo help --all' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_LONG}': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--all=unexpected' must be routed to
        stderr only. Stdout must remain clean of the error detail.
        """
        bad_token = _CLI_FLAG_ALL_LONG + _INLINE_VALUE_SUFFIX
        result = _run_kanon(*_build_help_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME, bad_token))
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
