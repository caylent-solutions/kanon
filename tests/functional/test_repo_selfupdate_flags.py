"""Functional tests for flag coverage of 'kanon repo selfupdate'.

Exercises every flag registered in ``subcmds/selfupdate.py``'s ``_Options()``
method by invoking ``kanon repo selfupdate`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior
when flags are omitted.

``Selfupdate._Options()`` registers two boolean flags in the "repo Version
options" group:

- ``--no-repo-verify`` (store_false, dest=repo_verify, default=True):
  do not verify repo source code
- ``--repo-upgraded`` (store_true, help=SUPPRESS): internal flag indicating
  repo has already been upgraded (hidden from help output)

Both flags are boolean; they accept no value. Valid-value tests confirm that
each flag is accepted without an argument-parsing error (exit code != 2).
Negative tests confirm that supplying a boolean flag with an inline value is
rejected with exit code 2. Because ``kanon repo selfupdate`` always enters
embedded-mode detection before any flag-dependent logic, all valid-flag
invocations exit 0 and emit ``SELFUPDATE_EMBEDDED_MESSAGE`` to stderr.

AC wording note: AC-TEST-002 states "every flag that accepts enumerated values
has a negative test." ``Selfupdate._Options()`` has no flags that accept
enumerated or typed values -- both flags are boolean (store_false / store_true).
The applicable negative test for a boolean flag is to supply it with an
unexpected inline value using the ``--flag=value`` syntax. optparse exits 2
with ``--<flag> option does not take a value`` for such inputs.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/selfupdate.py has a
  valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test.
  For boolean flags, the negative test verifies that supplying an inline value
  to a boolean flag (store_false / store_true) is rejected with exit code 2.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified (no
  cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _TRACEBACK_MARKER,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Selfupdate Flags Test User"
_GIT_USER_EMAIL = "repo-selfupdate-flags@example.com"
_PROJECT_PATH = "selfupdate-flags-test-project"

# CLI token for the selfupdate subcommand.
_CLI_TOKEN_SELFUPDATE = "selfupdate"

# Composed CLI command phrase for diagnostic messages (no inline literals).
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_SELFUPDATE}"

# Error exit code for invalid argument values (optparse argument-parsing error).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for all valid-flag invocations in embedded mode.
_EXPECTED_EXIT_ZERO = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests that do
# not require a real initialized repository (negative tests that fail at parse
# time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-selfupdate-flags-repo-dir"

# Inline-value token for boolean-flag negative tests (store_false / store_true
# flags reject inline values). optparse exits 2 with '--<flag> option does not
# take a value' when a boolean flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Canonical optparse phrase emitted when a boolean flag receives an inline value.
_OPTPARSE_NO_VALUE_PHRASE = "does not take a value"

# Expected stdout for all valid selfupdate invocations in embedded mode.
_EXPECTED_STDOUT = ""

# ---------------------------------------------------------------------------
# Flag-list constants for parametrize lists.
#
# Flags from Selfupdate._Options():
#   --no-repo-verify   (store_false, dest=repo_verify, default=True):
#                      do not verify repo source code
#   --repo-upgraded    (store_true, help=SUPPRESS):
#                      internal flag; indicates repo is already upgraded
#
# Both flags are boolean. Short forms: none registered in _Options().
# Only long-form flags can be supplied with '--flag=value' syntax in optparse;
# they are also the only forms tested in negative tests.
# ---------------------------------------------------------------------------

# Individual flag constants to avoid inline literals outside the parametrize lists.
_CLI_FLAG_NO_REPO_VERIFY = "--no-repo-verify"
_CLI_FLAG_REPO_UPGRADED = "--repo-upgraded"

_BOOL_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_NO_REPO_VERIFY, "no-repo-verify"),
    (_CLI_FLAG_REPO_UPGRADED, "repo-upgraded"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every ``_Options()`` flag in subcmds/selfupdate.py has a valid-value test.

    Exercises each boolean flag registered in ``Selfupdate._Options()`` by
    invoking ``kanon repo selfupdate`` with the flag against a real synced
    .repo directory. Both flags are boolean (store_false / store_true), so
    valid-value tests confirm the flag is accepted without an
    argument-parsing error (exit code != 2).

    Because ``kanon repo selfupdate`` always enters embedded-mode detection
    before any flag-dependent logic, every valid-flag invocation exits 0 and
    emits ``SELFUPDATE_EMBEDDED_MESSAGE`` to stderr.

    Flags covered:
    - ``--no-repo-verify`` (store_false, dest=repo_verify, default=True):
      do not verify repo source code
    - ``--repo-upgraded``  (store_true, help=SUPPRESS): already-upgraded marker
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_boolean_flag_exits_zero_in_embedded_mode(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag causes exit 0 in embedded mode.

        Embedded-mode detection fires before any flag-dependent logic. Both
        boolean flags must produce exit 0 in a valid synced repo.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"'{_CLI_COMMAND_PHRASE} {flag}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_ZERO}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_boolean_flag_emits_embedded_message_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag invocation emits SELFUPDATE_EMBEDDED_MESSAGE to stderr.

        Because embedded-mode detection fires before any flag-dependent logic,
        ``SELFUPDATE_EMBEDDED_MESSAGE`` must appear in stderr for every
        valid-flag invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {flag}' failed with exit "
            f"{result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} in stderr of "
            f"'{_CLI_COMMAND_PHRASE} {flag}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Both flags in ``Selfupdate._Options()`` are boolean (store_false /
    store_true). Neither accepts a typed or enumerated value. The applicable
    negative test for a boolean flag is to supply it with an unexpected inline
    value using the ``--flag=value`` syntax. optparse exits 2 with ``--<flag>
    option does not take a value`` for such inputs.

    This class verifies that every long-form boolean flag produces exit 2
    when supplied with an inline value, that the error appears on stderr and
    not stdout, and that stderr names the flag and contains the canonical
    optparse rejection phrase.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies ``--<flag>=unexpected`` to ``kanon repo selfupdate``. Since
        all ``Selfupdate._Options()`` flags are store_false / store_true,
        optparse rejects the inline value with exit code 2 and emits
        ``--<flag> option does not take a value`` on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_bool_flag_with_inline_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for ``--<flag>=unexpected`` must appear on
        stderr only. stdout must not contain the rejection detail (channel
        discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _OPTPARSE_NO_VALUE_PHRASE in result.stderr, (
            f"Expected {_OPTPARSE_NO_VALUE_PHRASE!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_bool_flag_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must name the flag in stderr.

        The embedded optparse parser emits ``--<flag> option does not take
        a value`` when ``--<flag>=unexpected`` is supplied. Confirms the
        canonical flag name appears in the error message on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert flag in result.stderr, (
            f"Expected flag {flag!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS],
        ids=[test_id for _, test_id in _BOOL_FLAGS],
    )
    def test_bool_flag_with_inline_value_uses_no_value_phrase_in_stderr(
        self, tmp_path: pathlib.Path, flag: str
    ) -> None:
        """Each long-form boolean flag with inline value must emit the canonical no-value phrase.

        The embedded optparse parser consistently uses ``option does not take
        a value`` for store_false / store_true flags supplied with an inline
        value. Confirms this canonical phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SELFUPDATE,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _OPTPARSE_NO_VALUE_PHRASE in result.stderr, (
            f"Expected {_OPTPARSE_NO_VALUE_PHRASE!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each ``Selfupdate._Options()`` flag uses the documented
    default when omitted:

    - ``--no-repo-verify``: when absent, ``repo_verify`` defaults to True
      (explicit ``default=True`` in ``_Options()``).
    - ``--repo-upgraded``: when absent, ``repo_upgraded`` defaults to None
      (no explicit default; optparse uses None for store_true flags without
      a declared default).

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation. Because embedded-mode detection fires before
    flag-dependent logic, all invocations exit 0 and emit the embedded message.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """``kanon repo selfupdate`` with all optional flags omitted exits 0.

        When no optional flags are supplied, embedded-mode detection fires
        and the command exits 0. Verifies that no flag is required and all
        documented defaults produce a successful invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"'{_CLI_COMMAND_PHRASE}' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_ZERO}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_emits_embedded_message(self, tmp_path: pathlib.Path) -> None:
        """``kanon repo selfupdate`` with all flags omitted emits the embedded message.

        When no optional flags are supplied, embedded-mode detection emits
        ``SELFUPDATE_EMBEDDED_MESSAGE`` to stderr. This confirms the
        default ``repo_verify=True`` path (no ``--no-repo-verify``) and the
        default ``repo_upgraded=None`` path (no ``--repo-upgraded``) both
        reach the embedded-mode branch.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} in stderr of "
            f"'{_CLI_COMMAND_PHRASE}' with all flags omitted.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """``kanon repo selfupdate`` with all flags omitted produces empty stdout.

        In embedded mode all output routes to stderr. stdout must equal the
        empty string when all optional flags are omitted -- any non-empty
        stdout indicates output leaked to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EXPECTED_STDOUT, (
            f"Expected empty stdout from '{_CLI_COMMAND_PHRASE}' with all flags omitted.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or ``Error:``-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.

    stdout discipline: successful invocations must produce empty stdout.
    stderr discipline: successful invocations must not contain Python tracebacks.
    Error discipline: argument-parsing errors must appear on stderr, not stdout.

    All channel assertions share a single class-scoped fixture invocation to
    avoid redundant git setup for the success-path channel tests.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> "pytest.FixtureResult":
        """Run ``kanon repo selfupdate --no-repo-verify`` once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations. Uses ``--no-repo-verify``
        to cover a non-default flag value in the channel-discipline assertions.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            _CLI_FLAG_NO_REPO_VERIFY,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_ZERO, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_NO_REPO_VERIFY}' failed "
            f"with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_valid_flag_invocation_stdout_is_empty(self, channel_result: object) -> None:
        """Successful ``kanon repo selfupdate --no-repo-verify`` must produce empty stdout.

        In embedded mode all output routes to stderr. stdout must equal the
        empty string -- any non-empty stdout indicates output leaked to the
        wrong channel.
        """
        assert channel_result.stdout == _EXPECTED_STDOUT, (
            f"Expected empty stdout from '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_NO_REPO_VERIFY}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_valid_flag_invocation_has_no_traceback_on_stderr(self, channel_result: object) -> None:
        """Successful ``kanon repo selfupdate --no-repo-verify`` must not emit tracebacks to stderr.

        On success, stderr must not contain ``Traceback (most recent call last)``.
        The embedded message is the only expected content on stderr; a traceback
        alongside it would indicate an unhandled exception escaped alongside
        the expected output.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_NO_REPO_VERIFY}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
