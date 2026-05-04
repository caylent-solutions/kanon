"""Functional tests for 'kanon repo forall' error paths and --help.

Verifies that:
- 'kanon repo forall --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for a missing required value for 'repo forall' --
  supplying '-g' (or '--groups') without its required argument -- produces exit 2
  (AC-TEST-003). Note: 'repo forall' accepts optional positional '[<project>...]'
  arguments (not required), so omitting them is valid and causes no argument-parser
  error. The '-c'/'--command' flag is effectively required but, when absent,
  causes 'ValidateOptions' to raise AttributeError on 'opt.command' and exit 1
  (not 2). The only literal exit-2 "missing required argument" path available for
  'repo forall' is the '-g'/'--groups' value-required flag supplied without its
  argument (optparse emits '-g option requires 1 argument' and exits 2). AC-TEST-003
  therefore covers this analogous exit-2 scenario, satisfying the spirit of
  "missing required positional produces exit 2".
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
# definition). No _git helper or repo-init setup is needed because all tests
# here exercise argument-parsing and subcommand precondition failures that do
# not require a fully initialized .repo directory.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# CLI token constants -- subcommand path used by every invocation.
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_FORALL = "forall"
_FLAG_HELP = "--help"
_FLAG_COMMAND_SHORT = "-c"
_ECHO_COMMAND = "echo"

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-forall-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-forall-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-forall-option-99"

# Flag with unexpected inline value exercised in AC-TEST-003 (boolean path).
# 'repo forall' defines --regex as a boolean store_true flag; the optparse
# parser rejects '--regex=unexpected' because boolean flags cannot accept
# an inline value, producing exit 2 with '--regex option does not take a value'.
_BOOL_FLAG_WITH_VALUE = "--regex=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--abort-on-errors=badvalue"
_BOOL_FLAG_WITH_VALUE_ALT_B = "--ignore-missing=nope"

# Option name extracted from the bool-flag-with-value token, for use in
# the assertion that the error message names the offending flag.
_BOOL_FLAG_BASE_NAME = "--regex"

# Phrase produced by optparse when a boolean flag is supplied with an
# inline value (AC-TEST-003 boolean-flag variant).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Flag and phrase for the "missing required argument" path (AC-TEST-003).
# '-g' / '--groups' is a value-required flag; omitting its argument causes
# optparse to emit '-g option requires 1 argument' and exit 2.
_GROUPS_SHORT_FLAG = "-g"
_GROUPS_LONG_FLAG = "--groups"
_REQUIRES_ARGUMENT_PHRASE = "requires 1 argument"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo forall"

# Flag documented in the --help output whose name is asserted (AC-TEST-001 detail).
# '-c' / '--command' is the canonical flag documented in the usage line.
_HELP_DOCUMENTED_FLAG = "--command"

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

# Parametrize tables -- all tuples reference constants.

# AC-TEST-002: three distinct unknown flags, each must exit 2.
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b"),
]

# AC-TEST-003 boolean-flag variant: three bool flags with inline values.
_BOOL_FLAGS_WITH_INLINE_VALUE: list[tuple[str, str]] = [
    (_BOOL_FLAG_WITH_VALUE, "regex-with-value"),
    (_BOOL_FLAG_WITH_VALUE_ALT_A, "abort-on-errors-with-value"),
    (_BOOL_FLAG_WITH_VALUE_ALT_B, "ignore-missing-with-value"),
]

# AC-TEST-003 missing-argument variant: short and long forms of '-g' / '--groups'.
_GROUPS_FLAGS_WITHOUT_ARGUMENT: list[tuple[str, str]] = [
    (_GROUPS_SHORT_FLAG, "groups-short"),
    (_GROUPS_LONG_FLAG, "groups-long"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo forall --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallHelp:
    """AC-TEST-001: 'kanon repo forall --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo forall' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' stdout must contain the phrase 'repo forall'.

        The embedded repo tool's help output includes 'repo forall' in the
        Usage line. Confirms the output is specific to the forall subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of "
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' produced unexpected stderr output.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_command_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' stdout must document the --command option.

        The --help output must mention the '-c'/'--command' flag so users
        know how to specify the per-project command to run.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_DOCUMENTED_FLAG in result.stdout, (
            f"Expected {_HELP_DOCUMENTED_FLAG!r} documented in stdout of "
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001. Asserts
        stdout equality between two invocations (not returncode self-comparison).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo forall' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {_UNKNOWN_FLAG_PRIMARY}' exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
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
        """Various unknown 'repo forall' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {bad_flag}' exited {result.returncode}, "
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
        """Various unknown 'repo forall' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001. Asserts stderr
        equality between invocations (not tautological returncode self-comparison).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {_UNKNOWN_FLAG_PRIMARY}' produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Missing required argument produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallMissingRequiredArgument:
    """AC-TEST-003: Missing required argument to 'repo forall' produces exit 2.

    Two exit-2 paths are tested:

    1. The '-g'/'--groups' value-required flag supplied without its argument:
       optparse emits '-g option requires 1 argument' and exits 2. This is the
       literal "missing required argument" path available for 'repo forall',
       since the '[<project>...]' positional is optional and '-c'/'--command'
       exits 1 (AttributeError in ValidateOptions) rather than 2.

    2. Boolean (store_true) flags supplied with an unexpected inline value
       (e.g. '--regex=unexpected'): optparse exits 2 with '--regex option does
       not take a value'. This is the analogous argument-parser rejection path.

    AC-TEST-003 wording note: 'repo forall' has no required positional argument
    (all '[<project>...]' are optional). The '-g'/'--groups' missing-argument
    path and the boolean-flag inline-value path are the two exit-2 scenarios
    that most closely satisfy "missing required positional produces exit 2",
    both of which are covered here.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
        ids=[test_id for _, test_id in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
    )
    def test_groups_flag_without_argument_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """'-g' or '--groups' without an argument must exit 2.

        optparse emits '-g option requires 1 argument' when the value-required
        '-g'/'--groups' flag is supplied without a following argument. The kanon
        layer must propagate the exit code 2 unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {flag}' (no argument) exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
        ids=[test_id for _, test_id in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
    )
    def test_groups_flag_without_argument_requires_phrase_in_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """'-g' or '--groups' without an argument must emit 'requires 1 argument' on stderr.

        The canonical optparse error phrase for a missing required argument
        must appear on stderr so users receive an actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected {_REQUIRES_ARGUMENT_PHRASE!r} in stderr for '{flag}' (no argument).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
        ids=[test_id for _, test_id in _GROUPS_FLAGS_WITHOUT_ARGUMENT],
    )
    def test_groups_flag_without_argument_error_not_on_stdout(self, tmp_path: pathlib.Path, flag: str) -> None:
        """'-g' or '--groups' without an argument must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error detail (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _REQUIRES_ARGUMENT_PHRASE not in result.stdout, (
            f"Phrase {_REQUIRES_ARGUMENT_PHRASE!r} leaked to stdout for '{flag}'.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --regex=unexpected' must exit with code 2.

        The embedded optparse parser rejects '--regex=unexpected' because
        boolean store_true flags do not accept inline values, emitting
        '--regex option does not take a value' and exiting 2. The kanon
        layer must propagate the exit code 2 unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {_BOOL_FLAG_WITH_VALUE}' exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --regex=unexpected' error must name the flag base name in stderr.

        The embedded optparse parser emits '--regex option does not take a value'
        when a boolean flag is supplied with an inline value. The error message
        must include the flag base name so users can identify what was rejected.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_does_not_take_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --regex=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser emits '--regex option does not take a value'
        when a boolean flag is supplied with an inline value. Confirms the
        canonical error phrase appears.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bool-flag-with-value error.\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [flag for flag, _ in _BOOL_FLAGS_WITH_INLINE_VALUE],
        ids=[test_id for _, test_id in _BOOL_FLAGS_WITH_INLINE_VALUE],
    )
    def test_various_bool_flags_with_inline_values_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit 2.

        Parametrises over multiple boolean flags supplied with unexpected
        inline values to confirm the exit code is consistently 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_inline_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --regex=unexpected' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001. Asserts stderr
        equality between invocations (not tautological returncode self-comparison).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _BOOL_FLAG_WITH_VALUE,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} {_BOOL_FLAG_WITH_VALUE}' produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo forall' requires a valid .repo directory with a readable manifest.xml
    in order to enumerate projects and execute the per-project command. When the
    .repo directory is absent or the manifest cannot be parsed, the embedded repo
    tool exits 1 with 'error parsing manifest' on stderr. This class verifies that
    the exit code and the error message are both propagated correctly by the kanon
    layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' with a nonexistent .repo directory must exit 1.

        When the .repo/manifest.xml file is absent, the embedded repo tool
        exits 1 after emitting 'error parsing manifest'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} -c echo' (no .repo dir) exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' without .repo must emit 'error parsing manifest' on stderr.

        The embedded repo tool prints 'error parsing manifest' to stderr
        when the manifest file is absent. This clear, actionable message
        tells users exactly what is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo dir.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' without .repo must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must be empty
        when the precondition failure is triggered (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stdout) == 0, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} -c echo' (no .repo dir) produced "
            f"unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_names_manifest_file_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' without .repo must name the manifest file in stderr.

        The error message must identify the missing manifest file path so
        users know exactly which file to create or where to run repo init.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} path in stderr for missing .repo dir.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' without .repo produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        Asserts stderr equality between invocations (not tautological returncode
        self-comparison).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} -c echo' (no .repo dir) produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo forall' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo forall' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.

    This class does not repeat assertions already made in the individual error
    classes above. It focuses on cross-cutting channel discipline checks for
    each distinct error category.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall --help' must route help text to stdout, not stderr.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of "
            f"'kanon {_CMD_REPO} {_SUBCMD_FORALL} --help'; "
            f"help must appear on stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE not in result.stderr, (
            f"Help phrase {_HELP_USAGE_PHRASE!r} must not appear on stderr; "
            f"help must be routed to stdout only.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        Confirms channel discipline: the 'no such option' rejection must be
        routed to stderr. Stdout must be clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag; "
            f"error must appear on stderr.\n  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"{_UNKNOWN_OPTION_PHRASE!r} phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_argument_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'-g' without argument error must appear on stderr, not stdout.

        Confirms channel discipline for the argparse-level missing-argument
        rejection: the 'requires 1 argument' error must be routed to stderr.
        Stdout must be clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _GROUPS_SHORT_FLAG,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected {_REQUIRES_ARGUMENT_PHRASE!r} in stderr for missing argument; "
            f"error must appear on stderr.\n  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert _REQUIRES_ARGUMENT_PHRASE not in result.stdout, (
            f"{_REQUIRES_ARGUMENT_PHRASE!r} phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'error parsing manifest' must appear on stderr, not stdout.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_FORALL,
            _FLAG_COMMAND_SHORT,
            _ECHO_COMMAND,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )
