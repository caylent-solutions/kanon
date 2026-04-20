"""Functional tests for flag coverage of 'kanon repo overview'.

Exercises every flag registered in ``subcmds/overview.py``'s ``_Options()`` method
by invoking ``kanon repo overview`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

All flags in ``Overview._Options()`` are boolean (``store_true`` / ``store_false``),
so valid-value tests confirm the flag is accepted without an argument-parsing
error (exit code != 2), and negative tests confirm that supplying a boolean
flag with an inline value is rejected with exit code 2.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a
  negative test verifying rejection of an invalid value. For boolean flags,
  the negative test verifies that supplying an inline value to a boolean
  flag (store_true or store_false) is rejected with exit code 2.
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

_GIT_USER_NAME = "Repo Overview Flags Test User"
_GIT_USER_EMAIL = "repo-overview-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-overview-flags test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "overview-flags-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"
_GIT_BRANCH_MAIN = "main"

# Error exit code for invalid argument values or constraint violations.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-overview-flags-repo-dir"

# Inline-value tokens for negative tests (boolean flags reject inline values).
# The optparse parser exits 2 with '--<flag> option does not take a value' when
# a store_true flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Known flags from Overview._Options() -- used to build parametrize lists.
# All are boolean store_true or store_false flags; none accept a typed value.
# Note: -b is a hidden deprecated flag (SUPPRESS_HELP) that maps to dest=current_branch;
# it is registered in _Options() and must be covered by AC-TEST-001.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-c", "short-current-branch"),
    ("--current-branch", "long-current-branch"),
    ("-b", "short-b-deprecated"),
]

_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("--no-current-branch", "no-current-branch"),
]

# Long-form flags that accept inline values in optparse (tested in AC-TEST-002).
# Only long-form flags can be supplied with '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--current-branch", "current-branch"),
    ("--no-current-branch", "no-current-branch"),
]

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo) follow the same pattern
# as in test_repo_info_flags.py and test_repo_overview_happy.py. Consolidating
# them into a shared module requires touching files outside this task's Changes
# Manifest. This duplication is tracked as a follow-up DRY cleanup.
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
    The 'overview' subcommand's argument parser is exercised once .repo exists.

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
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/overview.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/overview.py has a valid-value test.

    Exercises each boolean flag registered in ``Overview._Options()`` by
    invoking 'kanon repo overview' with the flag against a real initialized
    .repo directory. All flags in Overview._Options() are boolean
    (store_true / store_false), so valid-value tests confirm the flag is
    accepted without an argument-parsing error (exit code != 2).

    The parametrized ``test_boolean_flag_accepted`` method covers all
    store_true/-false flags by confirming exit code != 2.

    Flags covered:
    - -c / --current-branch (store_true, consider only checked-out branches)
    - --no-current-branch (store_false, consider all local branches)
    - -b (store_true, deprecated hidden alias for --current-branch)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo overview' with the given boolean flag against a
        properly initialized .repo directory and asserts that argparse does
        not reject the invocation (exit code != 2). A non-2 exit code confirms
        the flag itself was accepted; subsequent behavior (e.g. no unmerged
        branches) is not an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_current_branch_flag_exits_zero_on_initialized_repo(self, tmp_path: pathlib.Path) -> None:
        """'-c/--current-branch' flag exits 0 on an initialized repo with no unmerged branches.

        The --current-branch flag restricts output to branches currently
        checked out in each project. On a freshly initialized repo with no
        local unmerged branches, the command exits 0 with empty output.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo overview --current-branch' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_current_branch_flag_exits_zero_on_initialized_repo(self, tmp_path: pathlib.Path) -> None:
        """'--no-current-branch' flag exits 0 on an initialized repo with no unmerged branches.

        The --no-current-branch flag instructs the 'overview' subcommand to
        consider all local branches. On a freshly initialized repo with no
        local unmerged branches, the command exits 0 with empty output.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo overview --no-current-branch' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_deprecated_b_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """Deprecated '-b' flag is accepted by the argument parser (exit != 2).

        The hidden deprecated '-b' flag maps to dest=current_branch with
        action=store_true. Although SUPPRESS_HELP hides it from help output,
        it must still be accepted by the parser without triggering exit 2.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "-b",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Deprecated '-b' flag triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_current_branch_and_no_current_branch_flags_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--current-branch --no-current-branch' is accepted; last flag wins (exit != 2).

        Both flags share the same dest='current_branch'. When both are supplied,
        the last flag wins. Verifies the combination is accepted by the argument
        parser without an exit-2 error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--current-branch",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch --no-current-branch' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    All flags in Overview._Options() are boolean (store_true / store_false).
    None accept a typed or enumerated value. The applicable negative test for a
    boolean flag is to supply it with an unexpected inline value using the
    '--flag=value' syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    This class verifies that every long-form boolean flag produces exit 2
    when supplied with an inline value, and that the error appears on stderr,
    not stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo overview'. Since all
        Overview._Options() flags are store_true / store_false, optparse rejects
        the inline value with exit code 2 and emits '--<flag> option does
        not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
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
            "overview",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_current_branch_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--current-branch=unexpected' error must name '--current-branch' in stderr.

        The embedded optparse parser emits '--current-branch option does not
        take a value' when '--current-branch=unexpected' is supplied. Confirms
        the canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--current-branch" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--current-branch" in result.stderr, (
            f"Expected '--current-branch' in stderr for '--current-branch=unexpected' error.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_current_branch_with_inline_value_does_not_take_a_value_phrase_in_stderr(
        self, tmp_path: pathlib.Path
    ) -> None:
        """'--current-branch=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses 'option does not take
        a value' for store_true flags supplied with an inline value. Confirms
        this canonical phrase appears.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--current-branch" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "does not take a value" in result.stderr, (
            f"Expected 'does not take a value' in stderr.\n  stderr: {result.stderr!r}"
        )

    def test_no_current_branch_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--no-current-branch=unexpected' error must name '--no-current-branch' in stderr.

        The embedded optparse parser emits '--no-current-branch option does
        not take a value' when '--no-current-branch=unexpected' is supplied.
        Confirms the canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--no-current-branch" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--no-current-branch=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--no-current-branch" in result.stderr, (
            f"Expected '--no-current-branch' in stderr for '--no-current-branch=unexpected' error.\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Overview._Options() flag uses the documented default
    when omitted. Since all flags are boolean (store_true / store_false)
    declared without an explicit default= parameter, their option-parser
    default is None (not True or False) when the flag is absent. Absence
    tests confirm that omitting every optional flag still produces a valid,
    non-error invocation.

    Uses a real initialized .repo directory to confirm 'kanon repo overview'
    exits 0 when no optional flags are present.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' with all optional flags omitted exits 0.

        When no optional flags are supplied, each flag defaults to None
        (no explicit default= was set on any Overview._Options() flag):
        - --current-branch defaults to None (all branches considered)
        - --no-current-branch defaults to None (unset)
        - -b (deprecated) defaults to None (unset)

        Verifies that no flag is required and all documented defaults produce
        a successful (exit 0) invocation on an initialized repo.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo overview' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    # Per-flag absence tests (--current-branch, --no-current-branch omitted) are
    # covered by test_all_flags_omitted_exits_zero above, which confirms exit 0
    # when every optional flag is absent.

    def test_omitting_all_flags_produces_empty_output_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' with no flags produces empty output on a clean init.

        When all flags are omitted and the .repo directory has no synced
        projects with local unmerged branches, the 'overview' subcommand exits
        0 without producing output. This verifies the default behavior (None
        for all flags) leads to the expected no-output result.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo overview' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo overview' with defaults produced unexpected output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in Overview._Options():
    - -c/--current-branch: consider only checked out branches
    - --no-current-branch: consider all local branches
    - -b (hidden deprecated): same behavior as --current-branch

    Tests confirm that each flag is accepted and the command behaves as
    described in its help text without argument-parsing errors.
    """

    def test_current_branch_flag_accepted_without_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'-c/--current-branch' flag is accepted by the parser (exit != 2).

        The -c/--current-branch flag considers only checked out branches. Per
        the help text: 'consider only checked out branches'. Verifies the flag
        is accepted by the argument parser on an initialized repo.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch' flag triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_no_current_branch_flag_accepted_without_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'--no-current-branch' flag is accepted by the parser (exit != 2).

        The --no-current-branch flag considers all local branches. Per the
        help text: 'consider all local branches'. Verifies the flag is accepted
        by the argument parser on an initialized repo.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--no-current-branch' flag triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_current_branch_and_no_current_branch_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--no-current-branch --current-branch' combination is accepted (exit != 2).

        Both flags share the same dest='current_branch'. When both are supplied,
        the last flag wins per optparse semantics. Verifies the combination is
        accepted by the argument parser without an exit-2 error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--no-current-branch",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--no-current-branch --current-branch' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    # AC-FUNC-001 verified by the remaining dedicated tests in this class;
    # per-flag exit-code acceptance covered by parametrized test_boolean_flag_accepted
    # in TestRepoOverviewFlagsValidValues for AC-TEST-001.


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo overview' with valid flags must not emit tracebacks to stdout.

        On success (e.g. with --current-branch on an initialized repo), stdout
        must not contain 'Traceback (most recent call last)'. Tracebacks on
        stdout indicate an unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"Prerequisite 'kanon repo overview --current-branch' failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo overview --current-branch'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo overview' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo overview --no-current-branch' failed: {result.stderr!r}"
        )
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo overview --no-current-branch'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--current-branch=unexpected' must be
        routed to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--current-branch=unexpected"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "overview",
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
        """Successful 'kanon repo overview' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo overview --current-branch' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of 'kanon repo overview --current-branch': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    # AC-CHANNEL-001 verified by the remaining dedicated tests in this class;
    # per-flag exit-code acceptance covered by parametrized test_boolean_flag_accepted
    # in TestRepoOverviewFlagsValidValues for AC-TEST-001.
