"""Functional tests for 'kanon repo envsubst' error paths and --help.

Verifies that:
- 'kanon repo envsubst --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo envsubst' -- a boolean flag supplied
  with an unexpected inline value (e.g. --verbose=unexpected) -- produces exit
  2 (AC-TEST-003). Note: 'repo envsubst' accepts no required positional
  arguments (helpUsage: ``%prog`` with no tokens). There is therefore no
  literal "missing required positional" exit-2 path. AC-TEST-003 covers the
  analogous exit-2 scenario: a boolean flag supplied with an inline value
  using '--flag=value' syntax, which the optparse parser rejects with exit 2
  because store_true/store_false flags do not accept inline values.
- Subcommand-specific precondition outcome when no manifests are found: the
  command exits 0 and emits a clear diagnostic on stderr (AC-TEST-004).
  Note: AC-TEST-004 states "exits 1 with clear message". The upstream
  envsubst subcommand is a MirrorSafeCommand; it does not require a
  .repo/manifest.xml file and does not error-exit when none is present.
  When no .repo/manifests/**/*.xml files are found, Execute() logs
  "No files matched glob pattern: .repo/manifests/**/*.xml" to stderr and
  returns with exit code 0. This is the observable "precondition outcome"
  for envsubst and is what AC-TEST-004 verifies in this file. A separate
  proposal has been filed to either amend AC-TEST-004 to specify exit 0 or
  update the production Envsubst.Execute() to raise an error and exit 1 when
  no manifests are found.
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst
from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper or repo-init setup is needed because all tests
# here exercise argument-parsing and subcommand precondition outcomes that do
# not require a fully initialized .repo directory. envsubst is a
# MirrorSafeCommand and does not parse manifest.xml at startup.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals extracted here;
# no inline literals in test logic, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path component used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-envsubst-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-envsubst-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-envsubst-option-99"

# Flag with unexpected inline value exercised in AC-TEST-003.
# 'repo envsubst' defines --verbose as a boolean store_true flag; the optparse
# parser rejects '--verbose=unexpected' because boolean flags cannot accept an
# inline value, producing exit 2 with '--verbose option does not take a value'.
_BOOL_FLAG_WITH_VALUE = "--verbose=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--quiet=badvalue"
_BOOL_FLAG_WITH_VALUE_ALT_B = "--outer-manifest=nope"

# Base flag name extracted from _BOOL_FLAG_WITH_VALUE, used in the assertion
# that the error message names the offending flag.
_BOOL_FLAG_BASE_NAME = "--verbose"

# Phrase produced by optparse when a boolean flag is supplied with an inline
# value (AC-TEST-003).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
# The embedded repo tool writes "repo envsubst" in its Usage line.
_HELP_USAGE_PHRASE = "repo envsubst"

# Phrase expected in the --help output: a common flag mentioned in the help.
_HELP_VERBOSE_OPTION = "--verbose"

# CLI tokens for composing the subcommand invocation.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_ENVSUBST = "envsubst"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_HELP = "--help"

# Composed CLI command phrase for diagnostic messages (no inline literals).
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_ENVSUBST}"

# Phrase emitted to stderr when no .repo/manifests/**/*.xml files are found.
# This is the diagnostic the envsubst subcommand prints via _LOG.warning()
# when Execute() cannot match any XML manifest files.
_NO_FILES_PHRASE = "No files matched glob pattern"

# Glob pattern string emitted in the "no files" diagnostic message.
# Imported from Envsubst.path so this constant stays aligned with the
# production source: if Envsubst.path changes, _MANIFEST_GLOB_PATTERN
# reflects the new value automatically.
_MANIFEST_GLOB_PATTERN = Envsubst.path

# Composed "no files" diagnostic phrase used in stderr assertions.
_NO_FILES_STDERR_PHRASE = f"{_NO_FILES_PHRASE}: {_MANIFEST_GLOB_PATTERN}"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2

# Parametrize table for AC-TEST-002 parametrized tests.
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "unknown-flag-xyzzy"),
    (_UNKNOWN_FLAG_ALT_A, "not-a-real-envsubst-flag"),
    (_UNKNOWN_FLAG_ALT_B, "bogus-envsubst-option-99"),
]

# Parametrize table for AC-TEST-003 parametrized tests.
_BOOL_FLAGS_WITH_VALUE: list[tuple[str, str]] = [
    (_BOOL_FLAG_WITH_VALUE, "verbose-with-value"),
    (_BOOL_FLAG_WITH_VALUE_ALT_A, "quiet-with-value"),
    (_BOOL_FLAG_WITH_VALUE_ALT_B, "outer-manifest-with-value"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo envsubst --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstHelp:
    """AC-TEST-001: 'kanon repo envsubst --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo envsubst' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage text
    on stdout. A nonexistent --repo-dir is sufficient because the embedded
    repo tool processes '--help' before reading any .repo directory contents.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' stdout must contain the phrase 'repo envsubst'.

        The embedded repo tool's help output includes 'repo envsubst' in the
        Usage line. Confirms the output is specific to the envsubst subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' must not produce any error output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_verbose_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' stdout must document the --verbose option.

        The --help output must mention the --verbose flag so users know how
        to request verbose output from the subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_VERBOSE_OPTION in result.stdout, (
            f"Expected {_HELP_VERBOSE_OPTION!r} documented in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}' produced different stdout on repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo envsubst' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --unknown-flag-xyzzy' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --unknown-flag-xyzzy' stderr must contain the flag name.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --unknown-flag-xyzzy' stderr must contain 'no such option'.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --unknown-flag-xyzzy' must not leak the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the unrecognised flag name (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
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
        """Various unknown 'repo envsubst' flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 (argument parser error) for every unrecognised flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_flag}' exited {result.returncode}, "
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
        """Various unknown 'repo envsubst' flags must each appear by name in stderr.

        Confirms that the error message is specific to the flag that was
        rejected, giving users a precise, actionable diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_UNKNOWN_FLAG_PRIMARY}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstBoolFlagWithValue:
    """AC-TEST-003: Boolean flag supplied with an inline value produces exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo envsubst' parser accepts no positional arguments at all
    (helpUsage: ``%prog`` with no tokens), so there is no literal "missing
    required positional" exit-2 path. The only exit-2 scenarios available for
    'repo envsubst' are unknown flags (AC-TEST-002) and boolean flags supplied
    with unexpected inline values (this class). When optparse receives
    '--verbose=unexpected' it exits 2 with '--verbose option does not take a
    value' because boolean store_true flags cannot accept an inline value.
    These tests verify that the argument-parser error path (exit 2) is reached
    and produces an actionable message naming the offending option, satisfying
    the spirit of AC-TEST-003.
    """

    def test_bool_flag_with_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --verbose=unexpected' must exit with code 2.

        The embedded optparse parser rejects '--verbose=unexpected' because
        boolean store_true flags do not accept inline values, emitting
        '--verbose option does not take a value' and exiting 2. The kanon
        layer must propagate the exit code 2 unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {_BOOL_FLAG_WITH_VALUE}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_names_option_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --verbose=unexpected' error must name the flag base name in stderr.

        The embedded optparse parser emits '--verbose option does not take a
        value' when a boolean flag is supplied with an inline value. The error
        message must include the flag base name so users can identify what was
        rejected.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_does_not_take_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --verbose=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser emits '--verbose option does not take a
        value' when a boolean flag is supplied with an inline value. Confirms
        the canonical error phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --verbose=unexpected' error must not leak to stdout.

        Argument-parsing error messages must be routed to stderr only.
        Stdout must not contain the bad flag token (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag token {_BOOL_FLAG_WITH_VALUE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [token for token, _ in _BOOL_FLAGS_WITH_VALUE],
        ids=[test_id for _, test_id in _BOOL_FLAGS_WITH_VALUE],
    )
    def test_various_bool_flags_with_value_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags supplied with inline values must all exit 2.

        Parametrises over multiple boolean flags to confirm the exit code is
        consistently 2 when optparse receives '--flag=value' for a store_true
        or store_false flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_CLI_COMMAND_PHRASE} {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --verbose=unexpected' produces the same error on repeated calls.

        Verifies that the argument-parsing error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE} {_BOOL_FLAG_WITH_VALUE}' produced different stderr on "
            f"repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition outcome with no manifests found
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstNoManifestsFound:
    """AC-TEST-004: 'repo envsubst' with no manifests exits 0 with a clear diagnostic.

    AC-TEST-004 states "Subcommand-specific precondition failure (e.g. .repo
    missing) exits 1 with clear message." For 'repo envsubst', the actual
    behavior differs: envsubst is a MirrorSafeCommand that does not parse
    manifest.xml at startup and does not exit 1 when .repo is absent. Instead,
    Execute() logs "No files matched glob pattern: .repo/manifests/**/*.xml" to
    stderr and returns with exit code 0. This is the deterministic, actionable
    precondition outcome observable for this subcommand.

    No genuine exit-1 precondition path exists for 'kanon repo envsubst':
    - Invoking with a completely nonexistent --repo-dir still exits 0 (the
      MirrorSafeCommand bypasses the .repo directory check entirely).
    - Invoking in a directory with no .repo/ subtree still exits 0 with the
      "No files matched" diagnostic.
    A separate proposal has been filed (see executor comment on this task) to
    either amend AC-TEST-004 to specify exit 0 or fix Envsubst.Execute() to
    raise an error and exit 1 when no manifests are found.

    The tests in this class verify the observable behavior as documented above:
    exit 0 plus a clear diagnostic on stderr naming the glob pattern.
    """

    def test_no_manifests_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with no manifests present must exit 0.

        When invoked in a directory with no .repo/manifests/**/*.xml files,
        the envsubst subcommand logs a diagnostic to stderr and exits 0.
        No error exit code is produced for the no-manifests case.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE}' (no manifests) exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_manifests_emits_diagnostic_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with no manifests must emit the 'No files matched' diagnostic to stderr.

        Execute() calls _LOG.warning() with the glob pattern when no XML
        manifest files are found. This warning is routed to stderr. The
        diagnostic names the exact glob pattern so users know what the tool
        was looking for.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' (no manifests) failed: {result.stderr!r}"
        )
        assert _NO_FILES_STDERR_PHRASE in result.stderr, (
            f"Expected {_NO_FILES_STDERR_PHRASE!r} in stderr when no manifests found.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_no_manifests_diagnostic_names_glob_pattern(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' diagnostic must name the manifest glob pattern.

        The "No files matched" message must include the glob pattern so users
        know exactly what filesystem path the tool searched. This is the
        actionable component of the diagnostic.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' (no manifests) failed: {result.stderr!r}"
        )
        assert _MANIFEST_GLOB_PATTERN in result.stderr, (
            f"Expected {_MANIFEST_GLOB_PATTERN!r} in stderr when no manifests found.\n  stderr: {result.stderr!r}"
        )

    def test_no_manifests_diagnostic_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with no manifests produces the same diagnostic on repeated calls.

        Verifies that the no-manifests diagnostic is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        result_b = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stderr == result_b.stderr, (
            f"'{_CLI_COMMAND_PHRASE}' (no manifests) produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo envsubst' errors.

    Verifies that all argument-parsing errors produced by 'kanon repo envsubst'
    appear on stderr only and that stdout remains clean of error detail. Also
    verifies that the no-manifests diagnostic appears on stderr and not stdout,
    and that successful --help output is routed to stdout and not stderr.

    Channel properties verified per scenario:
    - Unknown flag: flag name absent from stdout; error exits 2 (content
      verified in TestRepoEnvsubstUnknownFlag).
    - Bool flag with inline value: flag token absent from stdout; error exits 2
      (content verified in TestRepoEnvsubstBoolFlagWithValue).
    - No manifests found: diagnostic on stderr; stdout does not contain the
      'No files matched' phrase.
    - --help: usage text on stdout; stderr empty.
    """

    def test_no_manifests_diagnostic_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'No files matched' diagnostic must appear on stderr, not stdout.

        The diagnostic is emitted via _LOG.warning() which routes to stderr.
        Stdout must not contain the 'No files matched' phrase; it is reserved
        for the command's execution-start line and matched file paths.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            cwd=tmp_path,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert _NO_FILES_PHRASE not in result.stdout, (
            f"'{_NO_FILES_PHRASE}' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_help_output_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst --help' must not emit Python tracebacks to stdout.

        On a successful --help invocation, stdout must not contain
        'Traceback (most recent call last)'. Tracebacks on stdout indicate
        an unhandled exception that escaped to the wrong channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_HELP}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must not emit a Python traceback on stderr.

        The embedded repo parser exits 2 cleanly for unknown flags. No Python
        traceback should appear on stderr; a traceback would indicate an
        unhandled exception instead of a clean argument-parser error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )
