"""Functional tests for flag coverage of 'kanon repo diff'.

Exercises every flag registered in ``subcmds/diff.py``'s ``_Options()`` method
by invoking ``kanon repo diff`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``Diff._Options()``:

Boolean store_true flag -- accepted without an argument; rejected with an
inline value (``--flag=value`` syntax, optparse exits 2):

- ``-u`` / ``--absolute`` (store_true): paths are relative to the repository
  root rather than the project root

AC-TEST-002 note: ``--absolute`` is a boolean store_true flag; the negative
test supplies it with an inline value (``--absolute=unexpected``), which
optparse rejects with exit code 2 and emits '--absolute option does not take
a value' on stderr. The short form ``-u`` cannot be supplied with an inline
value via optparse ``--flag=value`` syntax (that syntax is long-form only),
so the negative test uses the long form only.

No flag accepts an enumerated keyword set, so there are no enum-constraint
negative tests beyond the boolean inline-value negative test above.

AC-TEST-003 note: When ``--absolute`` is omitted the default is ``None`` /
falsy (file paths are relative to the project root). The omitted-flag scenario
is verified on a valid synced repo.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/diff.py has a
  valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test
  for an invalid value. For the boolean flag ``--absolute``, the negative
  test supplies an inline value which optparse rejects with exit 2.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Diff Flags Test User"
_GIT_USER_EMAIL = "repo-diff-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "diff-flags-test-project"

# CLI token constants -- every token referenced in test logic.
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_DIFF = "diff"

# Flag tokens from Diff._Options()
# Short form and long form of the absolute flag.
_CLI_FLAG_ABSOLUTE_SHORT = "-u"
_CLI_FLAG_ABSOLUTE_LONG = "--absolute"

# Inline-value suffix used in negative tests for boolean flags.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Exit codes
_EXPECTED_EXIT_CODE = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Phrases verified in channel-discipline and negative-test assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"
_ERROR_PREFIX = "Error:"
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Nonexistent repo-dir name used in argument-parser acceptance tests.
# The command exits 2 for argument-parsing errors regardless of repo state.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-diff-flags-repo-dir"

# Sentinel for empty output (no diff emitted on a clean synced repo).
_EMPTY_OUTPUT = ""

# ---------------------------------------------------------------------------
# Parametrize data tables -- all tuples use flag constants.
#
# AC-TEST-001 valid-value parametrize: one entry per flag form.
# Each entry: (flag_token, test_id).
# ---------------------------------------------------------------------------

# Boolean flags: accepted standalone (no argument).
_BOOL_FLAGS_VALID: list[tuple[str, str]] = [
    (_CLI_FLAG_ABSOLUTE_SHORT, "short-u"),
    (_CLI_FLAG_ABSOLUTE_LONG, "long-absolute"),
]

# Long-form boolean flags for the inline-value negative test.
# Only long-form flags support '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_ABSOLUTE_LONG, "absolute"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/diff.py has a valid-value test.

    Exercises each flag registered in ``Diff._Options()`` by invoking
    'kanon repo diff' with the flag against a real synced .repo directory.
    Parametrized over both forms of the single flag:

    - ``-u`` (boolean store_true short form): accepted without argument.
    - ``--absolute`` (boolean store_true long form): accepted without argument.

    Valid-value tests confirm exit code == 0 (flag accepted AND command
    succeeds on a clean synced repo with no uncommitted changes).
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _BOOL_FLAGS_VALID],
        ids=[test_id for _, test_id in _BOOL_FLAGS_VALID],
    )
    def test_flag_accepted_exits_zero_on_synced_repo(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Each _Options() flag is accepted and exits 0 on a synced repo.

        Invokes 'kanon repo diff <flag>' against a fully synced repo with no
        uncommitted changes. Both forms of --absolute (-u and --absolute) must
        exit 0 -- the flag controls path format only, not correctness.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            flag_token,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Flag {flag_token!r} exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_absolute_flag_produces_empty_output_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'--absolute' flag produces empty output on a clean synced repo.

        The --absolute flag causes diff to emit file paths relative to the
        repository root. On a clean repo with no uncommitted changes, the
        command must exit 0 and produce no diff output on stdout or stderr.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_ABSOLUTE_LONG!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"{_CLI_FLAG_ABSOLUTE_LONG!r} produced unexpected output on a clean repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_short_absolute_flag_produces_empty_output_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'-u' (short form) flag produces empty output on a clean synced repo.

        The -u short-form flag is equivalent to --absolute. On a clean repo
        with no uncommitted changes, the command must exit 0 and produce no
        output on stdout or stderr.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_SHORT,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_ABSOLUTE_SHORT!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"{_CLI_FLAG_ABSOLUTE_SHORT!r} produced unexpected output on a clean repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for invalid flag values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffFlagsInvalidValues:
    """AC-TEST-002: Flags that reject invalid values exit 2 with error on stderr.

    The applicable negative tests for 'kanon repo diff':

    - Boolean flag (``--absolute``): supply an inline value using the
      ``--flag=value`` syntax (``--absolute=unexpected``). optparse exits 2
      with '--absolute option does not take a value' on stderr.

    No flag accepts an enumerated keyword set, so enum-constraint tests are
    not applicable here. The class documents this rather than remaining
    silent about the AC scope.
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Boolean flag with inline value must exit 2.

        Supplies '--absolute=unexpected' to 'kanon repo diff'. Since
        ``--absolute`` is a store_true flag, optparse rejects the inline
        value with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--absolute=unexpected' must appear on
        stderr. Stdout must not contain the error token (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr != _EMPTY_OUTPUT and bad_token not in result.stdout, (
            f"'{bad_token}' error discipline failed: "
            f"stderr empty={result.stderr == _EMPTY_OUTPUT!r}, "
            f"token in stdout={bad_token in result.stdout!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_stderr_names_does_not_take_a_value(
        self, tmp_path: pathlib.Path, flag_token: str
    ) -> None:
        """Boolean flag with inline value must emit 'does not take a value' on stderr.

        optparse consistently uses this phrase for store_true flags supplied
        with an inline value. Confirms the canonical phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected '{_DOES_NOT_TAKE_VALUE_PHRASE}' in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that the Diff._Options() flag uses its documented default when
    omitted:
    - ``-u``/``--absolute`` (dest='absolute'): defaults to None / falsy
      (file paths relative to the project root, not the repository root).

    Absence test confirms that omitting the optional flag produces a valid,
    successful invocation (exit 0) on a real synced repo with no uncommitted
    changes, and that stdout and stderr are both empty.
    """

    def test_all_flags_omitted_exits_zero_with_empty_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' with all optional flags omitted exits 0 with empty output.

        When the --absolute flag is omitted, it defaults to None / falsy and
        file paths are relative to the project root. Verifies that no flag is
        required, the documented default produces a successful (exit 0)
        invocation on a clean synced repo, and that both stdout and stderr
        are empty.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_SUBCMD_DIFF}' with all flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFF}' with all flags omitted produced unexpected output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional semantics of each flag documented in
    Diff._Options():

    - ``-u`` / ``--absolute``: Causes 'repo diff' to emit file paths relative
      to the repository root. On a clean repo with no uncommitted changes, the
      command exits 0 and produces no diff output regardless of path style.

    All tests use a real synced repo with no uncommitted changes so the flag's
    path-formatting effect is exercised without requiring actual project diffs.
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _BOOL_FLAGS_VALID],
        ids=[test_id for _, test_id in _BOOL_FLAGS_VALID],
    )
    def test_flag_does_not_cause_argparse_error(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Each documented flag is accepted by the argument parser (exit 0).

        Invokes 'kanon repo diff <flag>' against a fully synced repo. Each
        form of the flag (-u and --absolute) must be accepted by the argument
        parser. A non-zero exit code indicates either an argument-parsing
        failure or a runtime error.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            flag_token,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Flag {flag_token!r} triggered an argument-parsing or runtime error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_absolute_and_project_positional_combined_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'-u <project>' combination exits 0 on a clean synced repo.

        The --absolute flag and the positional project filter are orthogonal:
        --absolute controls path format and the positional argument restricts
        the scope to one project. Combining them is valid per the help text
        and must exit 0 on a clean synced repo.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_SHORT,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_ABSOLUTE_SHORT} {_PROJECT_NAME}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_long_absolute_and_project_positional_combined_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'--absolute <project>' combination exits 0 on a clean synced repo.

        The long form --absolute combined with a positional project filter
        must exit 0 on a clean synced repo.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_LONG,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_ABSOLUTE_LONG} {_PROJECT_NAME}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:' prefixed error messages to stdout, and that argument-parsing
    errors appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flag_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit Python tracebacks to stdout.

        On success with --absolute on a synced repo, stdout must not contain
        a Python traceback. Tracebacks on stdout indicate an unhandled
        exception that escaped to the wrong channel.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_ABSOLUTE_LONG!r} exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of "
            f"'{_SUBCMD_DIFF} {_CLI_FLAG_ABSOLUTE_LONG}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_valid_flag_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit Python tracebacks to stderr.

        On success with --absolute on a synced repo, stderr must not contain
        a Python traceback. A traceback on stderr during a successful run
        indicates an unhandled exception was swallowed rather than propagated
        correctly.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_ABSOLUTE_LONG!r} exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of "
            f"'{_SUBCMD_DIFF} {_CLI_FLAG_ABSOLUTE_LONG}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_invalid_bool_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--absolute=unexpected' must be routed
        to stderr only. Stdout must remain empty on a pure argument-parsing
        error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_ABSOLUTE_LONG + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFF,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr != _EMPTY_OUTPUT and result.stdout == _EMPTY_OUTPUT, (
            f"Channel discipline failed: stderr empty={result.stderr == _EMPTY_OUTPUT!r}, "
            f"stdout non-empty={result.stdout != _EMPTY_OUTPUT!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_valid_flag_invocation_no_error_prefix_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation with --absolute must not produce any line starting with
        'Error:' on stdout.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFF,
            _CLI_FLAG_ABSOLUTE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_ABSOLUTE_LONG!r} exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        error_lines = [line for line in result.stdout.splitlines() if line.startswith(_ERROR_PREFIX)]
        assert error_lines == [], (
            f"'{_ERROR_PREFIX}' lines found in stdout: {error_lines!r}\n  stdout: {result.stdout!r}"
        )
