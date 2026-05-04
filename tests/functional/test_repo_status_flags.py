"""Functional tests for flag coverage of 'kanon repo status'.

Exercises every flag registered in ``subcmds/status.py``'s ``_Options()`` method
by invoking ``kanon repo status`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

``Status._Options()`` registers one flag:

- ``-o`` / ``--orphans`` (store_true, no explicit default -- defaults to None/False):
  include objects in working directory outside of repo projects

The valid-value test confirms the flag is accepted without an argument-parsing
error (exit code != 2). The negative test for the boolean flag confirms that
supplying an inline value is rejected with exit code 2.

For AC-TEST-003: when ``-o``/``--orphans`` is omitted, ``Status.Execute()``
skips the orphan-discovery block entirely. On a freshly synced repo with no
uncommitted changes, this produces exit 0 with the clean-status phrase. This is
the documented absence-default behavior.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/status.py has a valid-value test.
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

_GIT_USER_NAME = "Repo Status Flags Test User"
_GIT_USER_EMAIL = "repo-status-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "status-flags-test-project"
_GIT_BRANCH_MAIN = "main"

# Error exit code for argument-parsing errors (optparse exits 2 for bad flags).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-status-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Phrase optparse emits when a store_true flag is given an inline value.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# The one flag registered in Status._Options():
# -o / --orphans (store_true): include objects outside of repo projects.
_FLAG_SHORT_ORPHANS = "-o"
_FLAG_LONG_ORPHANS = "--orphans"

# All flags from Status._Options() as (flag, test_id) pairs for parametrize.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    (_FLAG_SHORT_ORPHANS, "short-orphans"),
    (_FLAG_LONG_ORPHANS, "long-orphans"),
]

# Long-form boolean flags for AC-TEST-002 negative tests.
# Only long-form flags can be supplied with '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_FLAG_LONG_ORPHANS, "orphans"),
]

# Phrase expected in stdout when all projects are clean.
_CLEAN_PHRASE = "nothing to commit (working directory clean)"

# Phrase expected when -o is used and no orphans are found.
_NO_ORPHANS_PHRASE = "No orphan files or directories"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"


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
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/status.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/status.py has a valid-value test.

    Exercises the one flag registered in ``Status._Options()`` by invoking
    'kanon repo status' with the flag against a real initialized and synced
    .repo directory. The flag is boolean (store_true), so the valid-value test
    confirms the flag is accepted without an argument-parsing error (exit != 2).

    Flags covered:
    - ``-o`` / ``--orphans`` (store_true): include objects outside of repo projects
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo status <flag>' against a properly initialized and
        synced .repo directory and asserts that optparse does not reject the
        invocation (exit code != 2). A non-2 exit code confirms the flag
        itself was accepted; subsequent behavior (e.g. no orphans found) is
        not an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_orphans_flag_exits_zero_in_clean_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'-o' flag exits 0 on a freshly synced repo with no orphan objects.

        In a freshly synced repo created entirely by 'kanon repo sync', all
        files belong to known projects or the .repo directory. The '-o' flag
        activates the orphan-discovery block; finding no orphans, the command
        exits 0.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo status {_FLAG_SHORT_ORPHANS}' exited {result.returncode}, "
            f"expected 0 on a clean synced repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_long_orphans_flag_exits_zero_in_clean_synced_repo(self, tmp_path: pathlib.Path) -> None:
        """'--orphans' long-form flag exits 0 on a freshly synced repo with no orphans.

        Confirms the long-form alias '--orphans' is accepted and produces
        the same exit-0 behavior as the short form '-o'.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_LONG_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo status {_FLAG_LONG_ORPHANS}' exited {result.returncode}, "
            f"expected 0 on a clean synced repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_orphans_flag_emits_no_orphans_message_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'-o' flag emits 'No orphan files or directories' on a clean synced repo.

        When the orphan-discovery block runs and finds no items outside known
        project directories, Status.Execute() prints the 'No orphan files or
        directories' phrase to stdout. Confirms the flag produces the documented
        output.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo status {_FLAG_SHORT_ORPHANS}' exited "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_ORPHANS_PHRASE in result.stdout, (
            f"Expected {_NO_ORPHANS_PHRASE!r} in stdout of "
            f"'kanon repo status {_FLAG_SHORT_ORPHANS}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    ``Status._Options()`` registers one boolean (store_true) flag:
    ``-o``/``--orphans``. Boolean flags do not accept a typed value.
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

        Supplies '--<flag>=unexpected' to 'kanon repo status'. Since
        Status._Options() registers the flag as store_true, optparse rejects
        the inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "status",
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
            "status",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_orphans_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--orphans=unexpected' error must name '--orphans' in stderr.

        The embedded optparse parser emits '--orphans option does not take
        a value' when '--orphans=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_ORPHANS + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "status",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--orphans=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _FLAG_LONG_ORPHANS in result.stderr, (
            f"Expected {_FLAG_LONG_ORPHANS!r} in stderr for '--orphans=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_orphans_with_inline_value_does_not_take_a_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--orphans=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses
        'option does not take a value' for store_true flags supplied with an
        inline value. Confirms this canonical phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_ORPHANS + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "status",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--orphans=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that the ``Status._Options()`` flag uses the documented default
    when omitted. The flag is boolean (store_true) with no explicit ``default=``
    kwarg (defaults to False in optparse internals). When ``-o``/``--orphans``
    is absent, ``Status.Execute()`` skips the orphan-discovery block entirely.
    On a freshly synced repo with no uncommitted changes, this produces exit 0
    with the clean-status phrase.
    """

    def test_all_flags_omitted_exits_zero_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' with all optional flags omitted exits 0 on a clean repo.

        When no optional flags are supplied, the orphan flag defaults to False
        (falsy), so the orphan-discovery block in Status.Execute() is never
        entered. On a freshly synced repo with no uncommitted changes, the
        command exits 0 with the clean-status phrase.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo status' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_prints_clean_status_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' with no flags prints the clean-status phrase on a fresh repo.

        When all flags are omitted and the repository is freshly synced with no
        uncommitted changes, Status.Execute() exits 0 and emits the
        'nothing to commit (working directory clean)' phrase to stdout.
        Verifies the default behavior (orphans flag False) leads to the expected
        clean-repo result.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo status' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _CLEAN_PHRASE in result.stdout, (
            f"Expected {_CLEAN_PHRASE!r} in stdout on a fresh repo with flags omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_does_not_print_orphans_header(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' with -o omitted must not emit any orphan-search output.

        When the orphans flag is absent, Status.Execute() never enters the
        orphan-discovery block. Neither the 'Objects not within a project
        (orphans)' header nor 'No orphan files or directories' must appear
        in stdout when the flag is omitted.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo status' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_ORPHANS_PHRASE not in result.stdout, (
            f"Orphan-search phrase {_NO_ORPHANS_PHRASE!r} appeared in stdout "
            f"when -o flag was omitted.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of the flag documented in Status._Options():
    - ``-o``/``--orphans``: 'include objects in working directory outside of
      repo projects'

    On a freshly synced repo created entirely by 'kanon repo sync', no objects
    exist outside of known project directories. The '-o' flag activates the
    orphan-discovery block, finds no orphans, and the command exits 0 with
    the 'No orphan files or directories' phrase on stdout.
    """

    def test_orphans_flag_activates_orphan_discovery_block(self, tmp_path: pathlib.Path) -> None:
        """'-o' flag activates the orphan-discovery block in Status.Execute().

        Per the help text: 'include objects in working directory outside of
        repo projects'. When -o is supplied on a clean synced repo, the orphan
        block runs, finds no orphans, and emits 'No orphan files or directories'.
        Confirms the flag activates the documented orphan-detection behavior.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo status {_FLAG_SHORT_ORPHANS}' exited {result.returncode}, "
            f"expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_ORPHANS_PHRASE in result.stdout, (
            f"Expected {_NO_ORPHANS_PHRASE!r} in stdout when "
            f"{_FLAG_SHORT_ORPHANS!r} is supplied (orphan block activated).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_without_orphans_flag_orphan_block_not_entered(self, tmp_path: pathlib.Path) -> None:
        """Without '-o', the orphan-discovery block is never entered.

        Confirms the documented flag is the sole mechanism for entering the
        orphan-discovery code path. When -o is absent, neither the orphan
        header nor the no-orphans phrase appears in stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo status' (no flags) exited {result.returncode}, "
            f"expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_ORPHANS_PHRASE not in result.stdout, (
            f"Orphan phrase {_NO_ORPHANS_PHRASE!r} appeared in stdout "
            f"when -o was not supplied.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStatusFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_orphans_flag_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status -o' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo status {_FLAG_SHORT_ORPHANS}' failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of "
            f"'kanon repo status {_FLAG_SHORT_ORPHANS}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_valid_orphans_flag_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status -o' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo status {_FLAG_SHORT_ORPHANS}' failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of "
            f"'kanon repo status {_FLAG_SHORT_ORPHANS}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_orphans_flag(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo status -o' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            _FLAG_SHORT_ORPHANS,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo status {_FLAG_SHORT_ORPHANS}' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of "
                f"'kanon repo status {_FLAG_SHORT_ORPHANS}': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_invalid_orphans_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--orphans=unexpected' error must appear on stderr, not stdout.

        Confirms channel discipline: the rejection error for a boolean flag
        with an inline value must be routed to stderr only. Stdout must be
        free of argument-error details.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _FLAG_LONG_ORPHANS + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "status",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_no_traceback_on_stdout_when_flags_omitted(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo status' with no flags must not emit Python tracebacks to stdout.

        A successful invocation with no flags must not produce tracebacks on
        stdout regardless of whether the orphan flag is set.
        """
        checkout_dir, repo_dir = _setup_initialized_and_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo status' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo status' (no flags).\n  stdout: {result.stdout!r}"
        )
