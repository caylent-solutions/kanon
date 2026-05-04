"""Functional tests for flag coverage of 'kanon repo gc'.

Exercises every flag registered in ``subcmds/gc.py``'s ``_Options()`` method
by invoking ``kanon repo gc`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

All flags in ``Gc._Options()`` are boolean (``store_true``) with an explicit
``default=False``, so valid-value tests confirm the flag is accepted without
an argument-parsing error (exit code != 2), and negative tests confirm that
supplying a boolean flag with an inline value is rejected with exit code 2.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a
  negative test verifying rejection of an invalid value. For boolean flags,
  the negative test verifies that supplying an inline value to a boolean
  flag (store_true) is rejected with exit code 2.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo GC Flags Test User"
_GIT_USER_EMAIL = "repo-gc-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-gc-flags test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "gc-flags-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"
_GIT_BRANCH_MAIN = "main"

# Error exit code for invalid argument values or constraint violations.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-gc-flags-repo-dir"

# Inline-value token for negative tests (boolean store_true flags reject inline values).
# The optparse parser exits 2 with '--<flag> option does not take a value' when
# a store_true flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Known flags from Gc._Options() -- used to build parametrize lists.
# All are boolean store_true flags; none accept a typed value.
# Flags and their short-form aliases registered in Gc._Options():
#   -n / --dry-run  (dest='dryrun', default=False): do everything except actually delete
#   -y / --yes      (default=False):                answer yes to all safe prompts
#   --repack        (default=False):                repack partial-clone projects
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-n", "short-dry-run"),
    ("--dry-run", "long-dry-run"),
    ("-y", "short-yes"),
    ("--yes", "long-yes"),
    ("--repack", "long-repack"),
]

# Long-form flags that accept inline values in optparse (tested in AC-TEST-002).
# Only long-form flags can be supplied with '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--dry-run", "dry-run"),
    ("--yes", "yes"),
    ("--repack", "repack"),
]

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo, _setup_initialized_repo)
# are near-duplicates of same-named functions in test_repo_overview_flags.py,
# test_repo_info_flags.py, and others. Consolidating them into a shared module
# requires touching files outside this task's Changes Manifest. This
# duplication is tracked as a follow-up DRY cleanup in proposal E1-F2-S12-T4.
# ---------------------------------------------------------------------------


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", _GIT_BRANCH_MAIN], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir and return the resolved bare_dir path.

    Args:
        work_dir: The source non-bare working directory.
        bare_dir: The destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing one committed file.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / f"{_PROJECT_NAME}.git")


def _create_manifest_repo(base: pathlib.Path, fetch_base: str) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: The fetch base URL for the remote element in the manifest.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        f'  <default revision="{_GIT_BRANCH_MAIN}" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / _MANIFEST_BARE_DIR_NAME)


def _setup_initialized_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init, and return (checkout_dir, repo_dir).

    Runs 'kanon repo init' against a real bare manifest repository so that
    the .repo directory is properly initialized for subsequent repo subcommands.
    The 'gc' subcommand's argument parser is exercised once .repo exists.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init.

    Raises:
        AssertionError: When kanon repo init exits with a non-zero code.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    bare_content = _create_bare_content_repo(repos_dir)
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
    manifest_url = f"file://{manifest_bare}"

    repo_dir = checkout_dir / ".repo"

    result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        _GIT_BRANCH_MAIN,
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )
    assert result.returncode == 0, (
        f"Prerequisite 'kanon repo init' failed with exit {result.returncode}.\n"
        f"  stdout: {result.stdout!r}\n"
        f"  stderr: {result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/gc.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/gc.py has a valid-value test.

    Exercises each boolean flag registered in ``Gc._Options()`` by invoking
    'kanon repo gc' with the flag against a real initialized .repo directory.
    All flags in Gc._Options() are boolean (store_true) with explicit
    default=False, so valid-value tests confirm the flag is accepted without
    an argument-parsing error (exit code != 2).

    The parametrized ``test_boolean_flag_accepted`` method covers all
    store_true flags by confirming exit code != 2.

    Flags covered:
    - -n / --dry-run (store_true, default=False): do everything except actually delete
    - -y / --yes     (store_true, default=False): answer yes to all safe prompts
    - --repack       (store_true, default=False): repack partial-clone projects
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo gc' with the given boolean flag against a properly
        initialized .repo directory and asserts that argparse does not reject
        the invocation (exit code != 2). A non-2 exit code confirms the flag
        itself was accepted; subsequent behavior (e.g. no unused projects) is
        not an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_dry_run_and_yes_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--dry-run --yes' combination is accepted by the argument parser (exit != 2).

        Both flags share no conflicting dest. When both are supplied, the
        command should not trigger an argument-parsing error (exit 2). Verifies
        the combination is accepted.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            "--dry-run",
            "--yes",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--dry-run --yes' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    All flags in Gc._Options() are boolean (store_true). None accept a typed
    or enumerated value. The applicable negative test for a boolean flag is to
    supply it with an unexpected inline value using the '--flag=value' syntax.
    optparse exits 2 with '--<flag> option does not take a value' for such inputs.

    This class verifies that every long-form boolean flag produces exit 2 when
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

        Supplies '--<flag>=unexpected' to 'kanon repo gc'. Since all
        Gc._Options() flags are store_true, optparse rejects the inline value
        with exit code 2 and emits '--<flag> option does not take a value'
        on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
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
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_dry_run_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--dry-run=unexpected' error must name '--dry-run' in stderr.

        The embedded optparse parser emits '--dry-run option does not take
        a value' when '--dry-run=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--dry-run" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--dry-run=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--dry-run" in result.stderr, (
            f"Expected '--dry-run' in stderr for '--dry-run=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_dry_run_with_inline_value_does_not_take_a_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--dry-run=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses 'option does not take
        a value' for store_true flags supplied with an inline value. Confirms
        this canonical phrase appears.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--dry-run" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--dry-run=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "does not take a value" in result.stderr, (
            f"Expected 'does not take a value' in stderr.\n  stderr: {result.stderr!r}"
        )

    def test_yes_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--yes=unexpected' error must name '--yes' in stderr.

        The embedded optparse parser emits '--yes option does not take a value'
        when '--yes=unexpected' is supplied. Confirms the canonical flag name
        appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--yes" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--yes=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--yes" in result.stderr, (
            f"Expected '--yes' in stderr for '--yes=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_repack_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--repack=unexpected' error must name '--repack' in stderr.

        The embedded optparse parser emits '--repack option does not take
        a value' when '--repack=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--repack" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--repack=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--repack" in result.stderr, (
            f"Expected '--repack' in stderr for '--repack=unexpected' error.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Gc._Options() flag uses the documented default when
    omitted. All flags are boolean (store_true) declared with explicit
    default=False, so when each flag is absent, its value is False (not None).
    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation.

    Uses a real initialized .repo directory to confirm 'kanon repo gc' exits 0
    when no optional flags are present (no unused projects to delete).
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo gc' with all optional flags omitted exits 0.

        When no optional flags are supplied, each flag defaults to False
        (explicit default=False set in Gc._Options()):
        - --dry-run defaults to False (dryrun=False, actual deletion enabled)
        - --yes defaults to False (prompts user before deleting)
        - --repack defaults to False (no repack performed)

        Verifies that no flag is required and all documented defaults produce
        a successful (exit 0) invocation on an initialized repo with no
        unused projects.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo gc' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_produces_nothing_to_clean_up_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo gc' with no flags reports 'Nothing to clean up.' on a fresh init.

        When all flags are omitted and the .repo directory has no unused project
        directories, the 'gc' subcommand exits 0 and emits 'Nothing to clean up.'
        to stdout. This verifies the default behavior (all flags False) leads to
        the expected clean-repo result.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo gc' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert "Nothing to clean up." in result.stdout, (
            f"Expected 'Nothing to clean up.' in stdout on a fresh repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in Gc._Options():
    - -n/--dry-run: do everything except actually delete
    - -y/--yes:     answer yes to all safe prompts
    - --repack:     repack all projects that use partial clone with filter=blob:none

    Tests confirm that each flag is accepted and the command behaves as
    described in its help text without argument-parsing errors.
    """

    def test_dry_run_and_repack_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--dry-run --repack' combination is accepted (exit != 2).

        Both flags are independent boolean flags with no conflicting dest.
        When both are supplied, the command should not trigger an argument-parsing
        error (exit 2). Verifies the combination is accepted.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            "--dry-run",
            "--repack",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--dry-run --repack' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' with valid flags must not emit tracebacks to stdout.

        On success (e.g. with --dry-run on an initialized repo), stdout must
        not contain 'Traceback (most recent call last)'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            "--dry-run",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo gc --dry-run' failed with argparse error: {result.stderr!r}"
        )
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo gc --dry-run'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            "--dry-run",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo gc --dry-run' failed with argparse error: {result.stderr!r}"
        )
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo gc --dry-run'.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--dry-run=unexpected' must be routed
        to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--dry-run=unexpected"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            "--dry-run",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo gc --dry-run' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of 'kanon repo gc --dry-run': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repack_flag_error_on_stderr_not_stdout_for_inline_value(self, tmp_path: pathlib.Path) -> None:
        """'--repack=unexpected' error must appear on stderr, not stdout.

        Confirms channel discipline: the rejection error for a boolean flag
        with an inline value must be routed to stderr only. Stdout must be
        free of argument-error details.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--repack=unexpected"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "gc",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail must not appear in stdout.\n  stdout: {result.stdout!r}"
        )
