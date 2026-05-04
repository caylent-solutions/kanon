"""Functional tests for flag coverage of 'kanon repo stage'.

Exercises every flag registered in ``subcmds/stage.py``'s ``_Options()`` method
by invoking ``kanon repo stage`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

``Stage._Options()`` registers one flag:

- ``-i`` / ``--interactive`` (store_true, no explicit default -- defaults to None):
  use interactive staging

The valid-value test confirms the flag is accepted without an argument-parsing
error (exit code != 2). The negative test for the boolean flag confirms that
supplying an inline value is rejected with exit code 2.

Deviation note (AC-TEST-003): When ``-i``/``--interactive`` is omitted,
``Stage.Execute()`` calls ``self.Usage()`` which raises ``UsageError``; the
CLI exits 1, not 0. This is the documented absence-default behavior for a
mandatory-in-practice boolean flag. The AC-TEST-003 tests assert the actual
behavior (exit 1, ``Usage:`` on stdout) rather than the naive "defaults to
None with no error" expectation.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/stage.py has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test for
  an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon, _setup_synced_repo

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Stage Flags Test User"
_GIT_USER_EMAIL = "repo-stage-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "stage-flags-test-project"
_GIT_BRANCH_MAIN = "main"

# Error exit code for argument-parsing errors (optparse exits 2 for bad flags).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Exit code produced when -i is omitted: Stage.Execute() calls Usage() which
# raises UsageError; the repo tool exits 1.
_USAGE_ERROR_EXIT_CODE = 1

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-stage-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# The one flag registered in Stage._Options():
# -i / --interactive (store_true): use interactive staging.
_FLAG_SHORT_INTERACTIVE = "-i"
_FLAG_LONG_INTERACTIVE = "--interactive"

# All flags from Stage._Options() as (flag, test_id) pairs for parametrize.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    (_FLAG_SHORT_INTERACTIVE, "short-interactive"),
    (_FLAG_LONG_INTERACTIVE, "long-interactive"),
]

# Long-form boolean flags for AC-TEST-002 negative tests.
# Only long-form flags can be supplied with '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_FLAG_LONG_INTERACTIVE, "interactive"),
]

# Phrase optparse emits when a store_true flag is given an inline value.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# String emitted on stdout by Usage() when -i is omitted.
_USAGE_PREFIX = "Usage:"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Message logged to stderr when no dirty projects exist (from Stage._Interactive).
_NO_DIRTY_PROJECTS_MSG = "no projects have uncommitted modifications"


# ---------------------------------------------------------------------------
# Private setup helper
# ---------------------------------------------------------------------------


def _setup_initialized_and_synced_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Delegates to :func:`tests.functional.conftest._setup_synced_repo` so that
    all bare-repo creation, ``kanon repo init``, and ``kanon repo sync`` steps
    are handled by the canonical shared helper.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init and sync.

    Raises:
        AssertionError: When kanon repo init or kanon repo sync exits non-zero.
    """
    return _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
        branch=_GIT_BRANCH_MAIN,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/stage.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/stage.py has a valid-value test.

    Exercises the one flag registered in ``Stage._Options()`` by invoking
    'kanon repo stage' with the flag against a real initialized and synced
    .repo directory. The flag is boolean (store_true), so the valid-value test
    confirms the flag is accepted without an argument-parsing error (exit != 2).

    Flags covered:
    - ``-i`` / ``--interactive`` (store_true): use interactive staging
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo stage <flag>' against a properly initialized and
        synced .repo directory and asserts that optparse does not reject the
        invocation (exit code != 2). In a clean repo with no dirty projects,
        the command exits 0 after emitting a 'no uncommitted modifications'
        message.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_interactive_flag_exits_zero_in_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'-i' flag exits 0 in a clean synced repo (no dirty projects).

        In a freshly synced repo, 'kanon repo stage -i' detects no uncommitted
        modifications and exits 0 immediately. Per the documented help text:
        'use interactive staging'. Verifies the flag is accepted and the
        command behaves per its help text.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' exited {result.returncode}, "
            f"expected 0 in a clean synced repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_interactive_flag_logs_no_modifications_message(self, tmp_path: pathlib.Path) -> None:
        """'-i' flag emits 'no projects have uncommitted modifications' to stderr in a clean repo.

        Per the documented behavior of 'use interactive staging': when no dirty
        projects exist, Stage._Interactive() logs the no-modifications message.
        Confirms the flag produces the expected output when invoked correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' exited "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_DIRTY_PROJECTS_MSG in result.stderr, (
            f"Expected {_NO_DIRTY_PROJECTS_MSG!r} in stderr of "
            f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}'.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_long_interactive_flag_exits_zero_in_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'--interactive' long-form flag exits 0 in a clean synced repo.

        Confirms the long-form alias '--interactive' is accepted and produces
        the same exit-0 behavior as the short form '-i'.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_LONG_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo stage {_FLAG_LONG_INTERACTIVE}' exited {result.returncode}, "
            f"expected 0 in a clean synced repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    ``Stage._Options()`` registers one boolean (store_true) flag:
    ``-i``/``--interactive``. Boolean flags do not accept a typed value.
    The applicable negative test is to supply an unexpected inline value using
    the ``--flag=value`` syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    This class verifies that the long-form boolean flag produces exit 2 when
    supplied with an inline value, and that the error appears on stderr, not
    stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo stage'. Since
        Stage._Options() registers the flag as store_true, optparse rejects
        the inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "stage",
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
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr only. Stdout must not contain the rejection detail (channel
        discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "stage",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_interactive_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--interactive=unexpected' error must name '--interactive' in stderr.

        The embedded optparse parser emits '--interactive option does not take
        a value' when '--interactive=unexpected' is supplied. Confirms the
        canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_INTERACTIVE + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "stage",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--interactive=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _FLAG_LONG_INTERACTIVE in result.stderr, (
            f"Expected {_FLAG_LONG_INTERACTIVE!r} in stderr for "
            f"'--interactive=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_interactive_with_inline_value_does_not_take_a_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--interactive=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses
        'option does not take a value' for store_true flags supplied with an
        inline value. Confirms this canonical phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_INTERACTIVE + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "stage",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--interactive=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Deviation note: ``Stage._Options()`` registers ``-i``/``--interactive``
    as a store_true flag with no explicit ``default=`` kwarg (defaults to None
    in optparse internals). However, ``Stage.Execute()`` checks ``opt.interactive``
    and calls ``self.Usage()`` when it is falsy. ``Usage()`` raises
    ``UsageError``, causing the CLI to exit 1. This means the absence-default
    behavior is exit 1 with a ``Usage:`` line on stdout -- not a clean exit 0.
    This class asserts that exact documented behavior.
    """

    def test_interactive_flag_omitted_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage' with -i omitted exits 1 (Usage() called by Execute()).

        When no flags are supplied, Stage.Execute() detects opt.interactive is
        falsy, calls self.Usage(), which raises UsageError. The CLI wraps this
        as exit 1. Confirms that the absence-default is exit 1, not exit 0.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            cwd=checkout_dir,
        )
        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"'kanon repo stage' (no flags) exited {result.returncode}, "
            f"expected {_USAGE_ERROR_EXIT_CODE} (UsageError from omitted -i).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_interactive_flag_omitted_emits_usage_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage' with -i omitted emits 'Usage:' on stdout.

        When opt.interactive is falsy, Stage.Execute() calls self.Usage() which
        writes the usage banner to stdout before raising UsageError. Confirms
        the 'Usage:' prefix appears on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            cwd=checkout_dir,
        )
        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage' (no flags) exited "
            f"{result.returncode}, expected {_USAGE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _USAGE_PREFIX in result.stdout, (
            f"Expected {_USAGE_PREFIX!r} in stdout when -i is omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_interactive_flag_omitted_is_not_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage' with -i omitted exits 1, not 2 (not an argparse error).

        Omitting -i is not an argument-parsing error (exit 2); optparse accepts
        the invocation without a flag. The error is a runtime UsageError from
        Stage.Execute(). Confirms the exit code is 1, not 2.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'kanon repo stage' (no flags) produced an argparse error (exit 2) "
            f"instead of a runtime UsageError (exit 1).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"'kanon repo stage' (no flags) exited {result.returncode}, "
            f"expected {_USAGE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of the flag documented in Stage._Options():
    - ``-i``/``--interactive``: 'use interactive staging'

    In a clean (no dirty files) synced repo, the interactive flag causes
    Stage._Interactive() to run, detect no dirty projects, and log a message
    before returning 0. This is the observable behavior matching the help text.
    """

    def test_interactive_flag_activates_interactive_path(self, tmp_path: pathlib.Path) -> None:
        """'-i' flag activates Stage._Interactive(); command exits 0 in a clean repo.

        Per the help text: 'use interactive staging'. When -i is supplied and
        no projects are dirty, Stage._Interactive() logs the no-modifications
        message and returns immediately with exit code 0. Confirms the flag
        activates the interactive code path.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' exited {result.returncode}, "
            f"expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_DIRTY_PROJECTS_MSG in result.stderr, (
            f"Expected {_NO_DIRTY_PROJECTS_MSG!r} in stderr (interactive path activated).\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_without_interactive_flag_does_not_activate_interactive_path(self, tmp_path: pathlib.Path) -> None:
        """Without '-i', Stage.Execute() calls Usage() -- interactive path is not activated.

        Confirms the documented flag serves as the only way to enter the
        interactive staging path. Without -i, the command exits 1 (UsageError)
        and does not emit the 'no projects have uncommitted modifications'
        message on stderr.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            cwd=checkout_dir,
        )
        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"'kanon repo stage' (no flags) exited {result.returncode}, "
            f"expected {_USAGE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_DIRTY_PROJECTS_MSG not in result.stderr, (
            f"Expected {_NO_DIRTY_PROJECTS_MSG!r} NOT in stderr when -i is omitted.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_interactive_flag_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo stage -i' must not emit Python tracebacks to stdout.

        On success (no dirty projects), stdout must not contain
        'Traceback (most recent call last)'. Tracebacks on stdout indicate an
        unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of "
            f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_valid_interactive_flag_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo stage -i' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of "
            f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_interactive_flag(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo stage -i' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_SHORT_INTERACTIVE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_SHORT_INTERACTIVE}' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of "
                f"'kanon repo stage {_FLAG_SHORT_INTERACTIVE}': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--interactive=unexpected' error must appear on stderr, not stdout.

        Confirms channel discipline: the rejection error for a boolean flag
        with an inline value must be routed to stderr only. Stdout must be
        free of argument-error details.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_INTERACTIVE + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "stage",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
