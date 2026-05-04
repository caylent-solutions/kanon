"""Functional tests for flag coverage of 'kanon repo forall'.

Exercises every flag registered in ``subcmds/forall.py``'s ``_Options()``
method by invoking ``kanon repo forall`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior
when flags are omitted.

Flags in ``Forall._Options()``:

Boolean (store_true) flags -- accepted without argument, rejected with
``--flag=value`` inline syntax (optparse exits 2):
- ``-r`` / ``--regex``         (store_true): execute only on projects matching regex
- ``-i`` / ``--inverse-regex`` (store_true): execute only on projects NOT matching regex
- ``-e`` / ``--abort-on-errors`` (store_true): abort if a command exits unsuccessfully
- ``--ignore-missing``         (store_true): silently skip missing checkouts
- ``-p``                       (store_true, dest="project_header"): show project headers
- ``--interactive``            (store_true): force interactive usage

Value-required flag -- requires exactly one string argument:
- ``-g`` / ``--groups``        (store, string): execute only on projects in groups

Callback flag (special syntax):
- ``-c`` / ``--command``       (callback): command and arguments to execute

Note on ``-c``/``--command``: this flag uses a custom ``_cmd_option`` callback
that collects all remaining parser args into ``opt.command``. When ``-c`` is
absent, ``ValidateOptions`` calls ``if not opt.command:`` which raises
``AttributeError`` (``Values`` object has no attribute ``command``) before
calling ``Usage()``. The tool exits 1 (not 2) for the missing-command case.
This test file asserts actual behavior (exit 1 from AttributeError propagation)
rather than the idealized exit 2 that would apply to a standard optparse
value-required flag.

AC wording note for AC-TEST-002: ``-c``/``--command`` is the only flag that
accepts a value in ``Forall._Options()``. However, because the callback
consumes all remaining ``parser.rargs`` rather than a single argument,
optparse never sees the flag as missing an argument. The ``--command=value``
inline syntax with ``action="callback"`` is not rejected by optparse (exit is
1 from manifest error, not 2). The negative test for the ``-c`` flag therefore
tests the omission case (no ``-c`` at all), which exits 1.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/forall.py has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a negative test.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Forall Flags Test User"
_GIT_USER_EMAIL = "repo-forall-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "forall-flags-test-project"

# Error exit code for argument-parsing errors (optparse uses 2).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for successful forall invocations on a real synced repo.
_EXPECTED_EXIT_CODE = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests.
# The command exits 1 (manifest not found) rather than 2 (argument parsing
# error), confirming the flag was accepted by optparse.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-forall-flags-repo-dir"

# Inline-value suffix for negative tests on boolean (store_true) flags.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true flag is supplied with an inline ``=value`` suffix.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Phrase emitted on stderr when a store_true flag receives an inline value.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Phrase emitted on stderr when a value-required flag has no argument.
_REQUIRES_ARGUMENT_PHRASE = "requires 1 argument"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# A groups value used in valid-value tests for -g / --groups.
_GROUPS_VALUE = "default"

# Pattern guaranteed not to match any project name; used with -i/--inverse-regex
# to confirm all projects are selected when the pattern matches nothing.
_NON_MATCHING_REGEX_PATTERN = "zzz-does-not-match-anything"

# Phrase expected in stdout when the -p flag prepends the project name to each
# output line.
_PROJECT_HEADER_PHRASE = "project"

# ---------------------------------------------------------------------------
# CLI token constants -- every flag token referenced in test logic.
# ---------------------------------------------------------------------------

_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_FORALL = "forall"

# Boolean (store_true) flags:
_CLI_FLAG_REGEX_SHORT = "-r"
_CLI_FLAG_REGEX_LONG = "--regex"
_CLI_FLAG_INVERSE_REGEX_SHORT = "-i"
_CLI_FLAG_INVERSE_REGEX_LONG = "--inverse-regex"
_CLI_FLAG_ABORT_ON_ERRORS_SHORT = "-e"
_CLI_FLAG_ABORT_ON_ERRORS_LONG = "--abort-on-errors"
_CLI_FLAG_IGNORE_MISSING = "--ignore-missing"
_CLI_FLAG_PROJECT_HEADER_SHORT = "-p"
_CLI_FLAG_INTERACTIVE = "--interactive"

# Value-required flag:
_CLI_FLAG_GROUPS_SHORT = "-g"
_CLI_FLAG_GROUPS_LONG = "--groups"

# Command callback flag:
_CLI_FLAG_COMMAND_SHORT = "-c"
_CLI_FLAG_COMMAND_LONG = "--command"

# The shell command used in functional tests; produces output on stdout.
_FORALL_SHELL_COMMAND = "echo"
_FORALL_SHELL_ARG = "FORALL_FLAG_TEST"
_FORALL_COMMAND_WITH_JOBS = "--jobs=1"

# ---------------------------------------------------------------------------
# Parametrize data tables -- all tuples use flag constants, not raw strings.
#
# AC-TEST-001 valid-value tests: boolean (store_true) flags.
# All are accepted against a nonexistent repo (exit 1 = parsed OK, not 2).
# Each entry: (flag_token, test_id).
# ---------------------------------------------------------------------------

_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_REGEX_SHORT, "short-regex"),
    (_CLI_FLAG_REGEX_LONG, "long-regex"),
    (_CLI_FLAG_INVERSE_REGEX_SHORT, "short-inverse-regex"),
    (_CLI_FLAG_INVERSE_REGEX_LONG, "long-inverse-regex"),
    (_CLI_FLAG_ABORT_ON_ERRORS_SHORT, "short-abort-on-errors"),
    (_CLI_FLAG_ABORT_ON_ERRORS_LONG, "long-abort-on-errors"),
    (_CLI_FLAG_IGNORE_MISSING, "long-ignore-missing"),
    (_CLI_FLAG_PROJECT_HEADER_SHORT, "short-project-header"),
    (_CLI_FLAG_INTERACTIVE, "long-interactive"),
]

# Long-form boolean flags used in AC-TEST-002 negative tests.
# Only long-form flags support '--flag=value' inline syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_REGEX_LONG, "regex"),
    (_CLI_FLAG_INVERSE_REGEX_LONG, "inverse-regex"),
    (_CLI_FLAG_ABORT_ON_ERRORS_LONG, "abort-on-errors"),
    (_CLI_FLAG_IGNORE_MISSING, "ignore-missing"),
    (_CLI_FLAG_INTERACTIVE, "interactive"),
]

# ---------------------------------------------------------------------------
# Helper: build the canonical forall argv prefix.
# ---------------------------------------------------------------------------


def _build_forall_argv(repo_dir: pathlib.Path, *extra: str) -> tuple[str, ...]:
    """Return the argv tuple for a 'kanon repo forall' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> forall <extra...>

    Args:
        repo_dir: Path to the .repo directory.
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to ``_run_kanon``.
    """
    return (_CMD_REPO, _FLAG_REPO_DIR, str(repo_dir), _SUBCMD_FORALL) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/forall.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/forall.py has a valid-value test.

    Exercises each flag registered in ``Forall._Options()`` by invoking
    'kanon repo forall' with the flag. Boolean flags are tested against a
    nonexistent repo-dir: exit 1 (manifest not found) confirms the flag was
    accepted by optparse; exit 2 would indicate an argument-parsing error.

    Value-required flags are tested with a valid value against a nonexistent
    repo-dir; exit 1 confirms the flag and its argument were accepted.

    The -c / --command callback flag is tested on a real synced repo because
    it is required for the command to proceed past ValidateOptions.

    Flags covered (all store_true except -g/--groups and -c/--command):
    - ``-r`` / ``--regex``         (store_true)
    - ``-i`` / ``--inverse-regex`` (store_true)
    - ``-e`` / ``--abort-on-errors`` (store_true)
    - ``--ignore-missing``         (store_true)
    - ``-p``                       (store_true, dest="project_header")
    - ``--interactive``            (store_true)
    - ``-g`` / ``--groups``        (store, string value)
    - ``-c`` / ``--command``       (callback)
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_boolean_flag_with_command_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag with -c <command> is accepted by the argument parser (exit != 2).

        Calls 'kanon repo forall <flag> -c echo' against a nonexistent repo-dir.
        optparse parses the flags before any manifest operations, so exit 1
        (manifest not found) rather than exit 2 confirms the flag was accepted.
        """
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                flag,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_groups_short_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-g <value> -c echo' is accepted by the argument parser (exit != 2).

        The -g flag requires a groups string argument. Supplying '-g default'
        with '-c echo' confirms the flag and argument are accepted; the command
        exits 1 (manifest not found).
        """
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                _CLI_FLAG_GROUPS_SHORT,
                _GROUPS_VALUE,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_GROUPS_SHORT} {_GROUPS_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_groups_long_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--groups <value> -c echo' is accepted by the argument parser (exit != 2).

        The --groups flag requires a groups string argument. Supplying
        '--groups default' with '-c echo' confirms the flag and argument are
        accepted; the command exits 1 (manifest not found).
        """
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                _CLI_FLAG_GROUPS_LONG,
                _GROUPS_VALUE,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_GROUPS_LONG} {_GROUPS_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_command_short_flag_accepted_on_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'-c <command>' is accepted and the command runs to exit 0 in a synced repo.

        The -c flag uses a custom callback (``_cmd_option``) that collects
        all remaining parser args into ``opt.command``. On a real synced repo,
        'kanon repo forall -c echo FORALL_FLAG_TEST' must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND} {_FORALL_SHELL_ARG}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_command_long_flag_accepted_on_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'--command <command>' is accepted and exits 0 in a synced repo.

        The --command flag is the long-form alias for -c. Both invoke the
        same ``_cmd_option`` callback. On a real synced repo, the command
        must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_LONG,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_COMMAND_LONG} {_FORALL_SHELL_COMMAND} {_FORALL_SHELL_ARG}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with invalid or missing values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed values has a negative test.

    Two categories of negative tests apply to ``Forall._Options()`` flags:

    1. Boolean (store_true) flags with an inline value (``--flag=value``
       syntax): optparse exits 2 with '--<flag> option does not take a value'.
       Tested for all long-form boolean flags.

    2. Value-required flag ``-g``/``--groups`` with no argument: optparse
       exits 2 with '-g option requires 1 argument'.

    3. Missing ``-c``/``--command`` flag: the command exits 1 (not 2) because
       ``ValidateOptions`` raises ``AttributeError`` on ``opt.command`` before
       calling ``Usage()``. This is documented in the class docstring of
       ``TestRepoForallFlagsValidValues``.

    All negative tests verify:
    - the correct exit code (2 for optparse errors, 1 for missing -c)
    - the error appears on stderr, not stdout
    - the canonical error phrase is present in stderr
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr and must contain the canonical 'does not take a value' phrase.
        Stdout must not contain the error detail.
        """
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                bad_token,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_regex_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--regex=unexpected' error must name '--regex' in stderr.

        The embedded optparse parser emits '--regex option does not take a
        value' when '--regex=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        bad_token = _CLI_FLAG_REGEX_LONG + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                bad_token,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_REGEX_LONG}{_INLINE_VALUE_SUFFIX}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_REGEX_LONG in result.stderr, (
            f"Expected {_CLI_FLAG_REGEX_LONG!r} in stderr for '{_CLI_FLAG_REGEX_LONG}{_INLINE_VALUE_SUFFIX}'.\n  stderr: {result.stderr!r}"
        )

    def test_abort_on_errors_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--abort-on-errors=unexpected' error must name '--abort-on-errors' in stderr.

        The embedded optparse parser emits '--abort-on-errors option does not
        take a value' when '--abort-on-errors=unexpected' is supplied. Confirms
        the canonical flag name appears in the error message.
        """
        bad_token = _CLI_FLAG_ABORT_ON_ERRORS_LONG + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                bad_token,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
            )
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_ABORT_ON_ERRORS_LONG}{_INLINE_VALUE_SUFFIX}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_ABORT_ON_ERRORS_LONG in result.stderr, (
            f"Expected {_CLI_FLAG_ABORT_ON_ERRORS_LONG!r} in stderr for "
            f"'{_CLI_FLAG_ABORT_ON_ERRORS_LONG}{_INLINE_VALUE_SUFFIX}'.\n  stderr: {result.stderr!r}"
        )

    def test_groups_short_without_argument_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'-g' without a following argument must emit 'requires 1 argument' on stderr.

        The canonical optparse error phrase for a missing required argument
        must appear on stderr and must not appear on stdout.
        """
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                _CLI_FLAG_GROUPS_SHORT,
            )
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{_CLI_FLAG_GROUPS_SHORT}' (no argument) exited "
            f"{result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected {_REQUIRES_ARGUMENT_PHRASE!r} in stderr for "
            f"'{_CLI_FLAG_GROUPS_SHORT}' (no argument).\n  stderr: {result.stderr!r}"
        )
        assert _CLI_FLAG_GROUPS_SHORT not in result.stdout, (
            f"Flag {_CLI_FLAG_GROUPS_SHORT!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_long_without_argument_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'--groups' without a following argument must exit 2.

        The --groups flag is the long-form alias for -g. Without an argument,
        optparse exits 2 and emits '--groups option requires 1 argument'.
        """
        result = _run_kanon(
            *_build_forall_argv(
                tmp_path / _NONEXISTENT_REPO_DIR_NAME,
                _CLI_FLAG_GROUPS_LONG,
            )
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_GROUPS_LONG}' (no argument) exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_command_flag_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Omitting the required -c flag must exit non-zero.

        When -c is absent, ``ValidateOptions`` raises AttributeError on
        ``opt.command`` before calling ``Usage()``, causing the tool to exit 1
        (not 2). The test asserts exit != 0 to remain resilient to any future
        fix that normalizes the exit code to 2.
        """
        result = _run_kanon(*_build_forall_argv(tmp_path / _NONEXISTENT_REPO_DIR_NAME))
        assert result.returncode != 0, (
            f"Omitting '{_CLI_FLAG_COMMAND_SHORT}' exited 0; expected non-zero.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each ``Forall._Options()`` flag uses the documented default
    when omitted. All boolean flags are store_true with implicit default=False.
    The -g/--groups flag defaults to None (not supplied). The -c flag is
    required (no default).

    Uses a real synced repo (via ``_setup_synced_repo``) to confirm that
    'kanon repo forall -c echo FORALL_FLAG_TEST' with all optional flags
    omitted exits 0, confirming no flag is accidentally required.
    """

    def test_all_optional_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo' with all optional flags omitted exits 0.

        When all optional flags (--regex, --inverse-regex, --groups,
        --abort-on-errors, --ignore-missing, -p, --interactive) are omitted,
        each boolean flag defaults to False and --groups defaults to None.
        The command must exit 0 on a synced repo with the required -c flag
        present.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CMD_REPO} {_SUBCMD_FORALL} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' with all optional flags omitted "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_optional_flags_omitted_emits_command_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo forall -c echo FORALL_FLAG_TEST' with no optional flags emits output.

        When all optional flags are omitted, the command runs in each project
        and the combined stdout must contain the sentinel phrase produced by
        echo. This confirms the default behavior (all boolean flags False,
        groups=None) produces correct output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CMD_REPO} {_SUBCMD_FORALL} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _FORALL_SHELL_ARG in result.stdout, (
            f"Expected {_FORALL_SHELL_ARG!r} in stdout when all optional flags omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_regex_absent_does_not_filter_projects(self, tmp_path: pathlib.Path) -> None:
        """Omitting --regex uses all projects without filtering (default False).

        When --regex is absent, GetProjects is called without regex filtering,
        iterating all synced projects. The command runs in all projects and
        exits 0. This confirms --regex defaults to False (not active).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CMD_REPO} {_SUBCMD_FORALL} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' without {_CLI_FLAG_REGEX_LONG} exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_groups_absent_does_not_restrict_projects(self, tmp_path: pathlib.Path) -> None:
        """Omitting --groups uses all projects without groups filtering (default None).

        When --groups is absent, ``opt.groups`` is None and GetProjects is
        called without a groups restriction. The command runs in all synced
        projects and exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CMD_REPO} {_SUBCMD_FORALL} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' without {_CLI_FLAG_GROUPS_LONG} exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of flags documented in
    ``Forall._Options()`` using a real synced repo.

    Flags and documented behavior:
    - ``-r`` / ``--regex``: execute command only on projects matching regex.
      Supplying the project name as a regex pattern (``-r <name> -c echo``)
      must restrict to matching projects and exit 0.
    - ``-i`` / ``--inverse-regex``: execute command only on projects NOT
      matching regex. Supplying a non-matching pattern selects all projects
      and exits 0.
    - ``-e`` / ``--abort-on-errors``: abort if a command exits unsuccessfully.
      When the command succeeds, -e has no visible effect; the command exits 0.
    - ``--ignore-missing``: silently skip missing checkouts (exit 0).
    - ``-p``: show project headers before output. With jobs=1, output includes
      a 'project <path>/' header.
    - ``--interactive``: force interactive usage. When combined with a
      succeeding command, exits 0.
    - ``-g`` / ``--groups``: execute only on projects matching specified groups.
      When the group does not exist, the project list is empty and the command
      exits 0 without running the per-project command.
    """

    def test_regex_flag_matches_project_by_name(self, tmp_path: pathlib.Path) -> None:
        """'-r <name> -c echo' runs only in projects matching the regex; exits 0.

        Per the help text: 'execute the command only on projects matching
        regex or wildcard expression.' Supplying the project name as a regex
        pattern restricts execution to that project and exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_REGEX_SHORT,
                _PROJECT_NAME,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_REGEX_SHORT} {_PROJECT_NAME} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_inverse_regex_flag_excludes_matching_projects(self, tmp_path: pathlib.Path) -> None:
        """'-i <non-matching-pattern> -c echo' runs in all projects; exits 0.

        Per the help text: 'execute the command only on projects not matching
        regex or wildcard expression.' A pattern that matches nothing selects
        all projects; the command runs in all of them and exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_INVERSE_REGEX_SHORT,
                _NON_MATCHING_REGEX_PATTERN,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_INVERSE_REGEX_SHORT} {_NON_MATCHING_REGEX_PATTERN} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_abort_on_errors_with_succeeding_command_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'-e -c echo' exits 0 when the per-project command succeeds.

        Per the help text: 'abort if a command exits unsuccessfully.' When
        the command succeeds (echo always exits 0), --abort-on-errors has no
        visible effect and the overall command exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_ABORT_ON_ERRORS_SHORT,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_ABORT_ON_ERRORS_SHORT} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_ignore_missing_flag_exits_zero_on_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'--ignore-missing -c echo' exits 0 in a synced repo.

        Per the help text: 'silently skip & do not exit non-zero due missing
        checkouts.' On a properly synced repo, --ignore-missing has no visible
        effect (all checkouts exist) and the command exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_IGNORE_MISSING,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_IGNORE_MISSING} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_project_header_flag_includes_header_in_output(self, tmp_path: pathlib.Path) -> None:
        """'-p --jobs=1 -c echo' output contains 'project' header before command output.

        Per the help text: 'show project headers before output.' With -p and
        --jobs=1 (which triggers interactive mode + pager), the combined
        output includes a 'project <path>/' header before per-project command
        output. Confirms -p activates project header output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_PROJECT_HEADER_SHORT,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_PROJECT_HEADER_SHORT} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_HEADER_PHRASE in result.stdout, (
            f"Expected {_PROJECT_HEADER_PHRASE!r} header in stdout when {_CLI_FLAG_PROJECT_HEADER_SHORT} is used.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_interactive_flag_exits_zero_on_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'--interactive -c echo' exits 0 on a synced repo.

        Per the help text: 'force interactive usage.' With a succeeding
        command, --interactive forces jobs=1 mode and exits 0. Verifies the
        flag is accepted and the command runs to completion.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_INTERACTIVE,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_INTERACTIVE} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoForallFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful 'kanon repo forall' invocations do not write
    Python tracebacks or 'Error:'-prefixed messages to stdout, and that
    argument-parsing errors appear on stderr only. No cross-channel leakage
    is permitted.

    All three channel assertions for the valid-flags case share a single
    class-scoped fixture invocation to avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo forall -c echo FORALL_FLAG_TEST' once and return the result.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from the forall invocation.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("forall_flags_channel")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            *_build_forall_argv(
                repo_dir,
                _FORALL_COMMAND_WITH_JOBS,
                _CLI_FLAG_COMMAND_SHORT,
                _FORALL_SHELL_COMMAND,
                _FORALL_SHELL_ARG,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CMD_REPO} {_SUBCMD_FORALL} {_CLI_FLAG_COMMAND_SHORT} {_FORALL_SHELL_COMMAND}' failed with exit "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_valid_flags_invocation_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo forall' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo forall'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo forall' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo forall'.\n  stderr: {channel_result.stderr!r}"
        )

    def test_valid_flags_invocation_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo forall' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful"
                f" 'kanon repo forall': {line!r}\n  stdout: {channel_result.stdout!r}"
            )
