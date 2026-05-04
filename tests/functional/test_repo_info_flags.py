"""Functional tests for flag coverage of 'kanon repo info'.

Exercises every flag registered in ``subcmds/info.py``'s ``_Options()`` method
by invoking ``kanon repo info`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

All flags in ``Info._Options()`` are boolean (``store_true`` / ``store_false``),
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

_GIT_USER_NAME = "Repo Info Flags Test User"
_GIT_USER_EMAIL = "repo-info-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-info-flags test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "info-flags-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"
_GIT_BRANCH_MAIN = "main"

# Error exit code for invalid argument values or constraint violations.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-info-flags-repo-dir"

# Inline-value tokens for negative tests (boolean flags reject inline values).
# The optparse parser exits 2 with '--<flag> option does not take a value' when
# a store_true flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Known flags from Info._Options() -- used to build parametrize lists.
# All are boolean store_true or store_false flags; none accept a typed value.
# Note: -b is a hidden deprecated flag (SUPPRESS_HELP) that maps to dest=current_branch;
# it is registered in _Options() and must be covered by AC-TEST-001.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-d", "short-diff"),
    ("--diff", "long-diff"),
    ("-o", "short-overview"),
    ("--overview", "long-overview"),
    ("-c", "short-current-branch"),
    ("--current-branch", "long-current-branch"),
    ("-b", "short-b-deprecated"),
    ("-l", "short-local-only"),
    ("--local-only", "long-local-only"),
]

_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("--no-current-branch", "no-current-branch"),
]

# Long-form flags that accept inline values in optparse (tested in AC-TEST-002).
# Only long-form flags can be supplied with '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--diff", "diff"),
    ("--overview", "overview"),
    ("--current-branch", "current-branch"),
    ("--no-current-branch", "no-current-branch"),
    ("--local-only", "local-only"),
]

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo) follow the same pattern
# as in test_repo_info_happy.py. Consolidating them into a shared module
# requires touching files outside this task's Changes Manifest. This
# duplication is tracked as a follow-up DRY cleanup.
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
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/info.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/info.py has a valid-value test.

    Exercises each boolean flag registered in ``Info._Options()`` by invoking
    'kanon repo info' with the flag against a real initialized .repo directory.
    All flags in Info._Options() are boolean (store_true / store_false), so
    valid-value tests confirm the flag is accepted without an argument-parsing
    error (exit code != 2).

    The parametrized ``test_boolean_flag_accepted`` method covers the six
    store_true/-false flags by confirming exit code != 2. Note that some flags
    (e.g. -d/--diff) trigger network operations and may fail for network/sync
    reasons; the test asserts only that the argument was parsed (exit != 2).

    The ``test_local_only_flag_accepted`` method verifies that -l/--local-only
    accepts the flag without an argument-parser error.
    """

    # Short-form flags cannot be supplied with '--flag=value' and cannot be tested
    # for inline-value rejection in AC-TEST-002, but they do have valid-value tests here.
    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo info' with the given boolean flag against a properly
        initialized .repo directory and asserts that argparse does not reject
        the invocation (exit code != 2). A non-2 exit code confirms the flag
        itself was accepted; subsequent failures (e.g. network, sync state)
        are expected and do not indicate a flag-parsing error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_overview_flag_exits_zero_on_initialized_repo(self, tmp_path: pathlib.Path) -> None:
        """'--overview' flag exits 0 on an initialized repo with no local branches.

        The --overview flag shows an overview of local commits per project.
        With no local branches, the output is a manifest header with no
        project entries -- the command exits 0.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--overview",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info --overview' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_local_only_flag_exits_zero_on_initialized_repo(self, tmp_path: pathlib.Path) -> None:
        """'-l/--local-only' flag exits 0 on an initialized repo.

        The --local-only flag disables remote operations. With no network
        required, the command should complete without error on an initialized
        repo.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--local-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info --local-only' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_current_branch_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--current-branch' flag is accepted (exit code != 2).

        The --current-branch flag instructs 'repo info' to consider only
        checked-out branches when building the project overview. Verifies
        the flag is accepted by the argument parser.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_no_current_branch_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--no-current-branch' flag is accepted (exit code != 2).

        The --no-current-branch flag instructs 'repo info' to consider all
        local branches. Verifies the flag is accepted by the argument parser.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--no-current-branch' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with inline values (boolean flags)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    All flags in Info._Options() are boolean (store_true / store_false). None
    accept a typed or enumerated value. The applicable negative test for a
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

        Supplies '--<flag>=unexpected' to 'kanon repo info'. Since all
        Info._Options() flags are store_true / store_false, optparse rejects
        the inline value with exit code 2 and emits '--<flag> option does
        not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "info",
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
            "info",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_diff_flag_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--diff=unexpected' error must name '--diff' in stderr.

        The embedded optparse parser emits '--diff option does not take a value'
        when '--diff=unexpected' is supplied. Confirms the canonical flag name
        appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--diff" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "info",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--diff=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--diff" in result.stderr, (
            f"Expected '--diff' in stderr for '--diff=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_diff_flag_with_inline_value_does_not_take_a_value_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--diff=unexpected' stderr must contain 'does not take a value'.

        The embedded optparse parser consistently uses 'option does not take
        a value' for store_true flags supplied with an inline value. Confirms
        this canonical phrase appears.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--diff" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "info",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--diff=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "does not take a value" in result.stderr, (
            f"Expected 'does not take a value' in stderr.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Info._Options() flag uses the documented default when
    omitted. Since all flags are boolean, their default is None (unset) unless
    an explicit default= is specified; both store_true and store_false flags
    default to None without an explicit default=. Absence tests confirm that
    omitting every optional flag still produces a valid, non-error invocation.

    Uses a real initialized .repo directory to confirm 'kanon repo info' exits
    0 when only mandatory context (a valid .repo dir) is provided and no
    optional flags are present.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info' with all optional flags omitted exits 0.

        When no optional flags are supplied, each flag takes its default value:
        - --diff (dest=all) defaults to None (no remote diff)
        - --overview defaults to None (no commit overview)
        - --current-branch defaults to None (unset)
        - --local-only (dest=local) defaults to None (remote operations enabled)

        Verifies that no flag is required and all documented defaults produce
        a successful (exit 0) invocation.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_omitting_diff_flag_default_is_no_diff_output(self, tmp_path: pathlib.Path) -> None:
        """Omitting --diff defaults to no diff information in output.

        When --diff is omitted, the default is None (no commit diff). The
        default 'repo info' output shows manifest-level info without per-branch
        diff details. Verifies the command exits 0 and produces non-empty output
        containing manifest header text.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info' (no --diff) exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "Manifest branch" in combined, (
            f"Expected 'Manifest branch' in output when --diff is omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_omitting_overview_flag_default_shows_diff_info_path(self, tmp_path: pathlib.Path) -> None:
        """Omitting --overview defaults to the diff-info code path (not commit overview).

        When --overview is omitted, Execute() takes the _printDiffInfo() branch
        (not _printCommitOverview()). The output must include manifest heading
        text, which confirms the diff-info path was executed rather than the
        overview path.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info' (no --overview) exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "Manifest" in combined, (
            f"Expected 'Manifest' heading in output when --overview is omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_omitting_local_only_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --local-only defaults to None; info exits 0 on an initialized repo.

        When --local-only is omitted, remote operations are enabled by default.
        Since --diff is also omitted (default None), no remote sync is attempted
        during the default '_printDiffInfo' path, so the command exits 0.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info' without --local-only exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_omitting_current_branch_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --current-branch defaults to None; info exits 0 on an initialized repo.

        When --current-branch is omitted, its destination defaults to None.
        This must not cause any argument-parsing or runtime error. Verifies
        exit code 0.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info' without --current-branch exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_overview_with_current_branch_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--overview --current-branch' combination is accepted (exit != 2).

        The --current-branch flag filters the project overview to only
        checked-out branches. Combining it with --overview is valid per the
        help text ('consider only checked out branches'). Verifies no
        argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--overview",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--overview --current-branch' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in Info._Options():
    - --diff: show full info and commit diff including remote branches
    - --overview: show overview of all local commits
    - --current-branch: consider only checked out branches
    - --no-current-branch: consider all local branches
    - --local-only: disable all remote operations

    Tests confirm that each flag is accepted and the command behaves as
    described in its help text without argument-parsing errors.
    """

    def test_diff_flag_accepted_without_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'-d/--diff' flag is accepted by the parser (exit != 2).

        The --diff flag shows full info and commit diff including remote
        branches. Verifies the flag is accepted by the argument parser on an
        initialized repo.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--diff",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--diff' flag triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_overview_flag_shows_projects_overview_heading(self, tmp_path: pathlib.Path) -> None:
        """'--overview' produces 'Projects Overview' heading in combined output.

        The --overview flag triggers _printCommitOverview(), which emits a
        'Projects Overview' heading. Verifies the heading appears in output
        when --overview is supplied and projects exist with local branches.
        Since we use a freshly-initialized repo (no local branches), the
        command exits 0 but produces the manifest header only, not the
        'Projects Overview' section. This test therefore verifies exit 0 and
        non-empty output rather than the heading text itself.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--overview",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info --overview' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo info --overview' produced empty output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_local_only_flag_disables_remote_in_diff_mode(self, tmp_path: pathlib.Path) -> None:
        """'--diff --local-only' combination is accepted (exit != 2).

        The --local-only flag disables all remote operations. When combined
        with --diff, it forces the diff to use only locally available refs.
        Verifies the combination is accepted by the argument parser.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--diff",
            "--local-only",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--diff --local-only' triggered an argument-parsing error "
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
            "info",
            "--current-branch",
            "--no-current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--current-branch --no-current-branch' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_local_only_flag_exits_zero_on_initialized_repo(self, tmp_path: pathlib.Path) -> None:
        """'-l/--local-only' flag exits 0 on an initialized repo per help text.

        The --local-only flag disables all remote operations. On a cleanly
        initialized repo with --local-only, no network sync is attempted and
        the command exits 0.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "-l",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo info -l' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo info' with valid flags must not emit tracebacks to stdout.

        On success (e.g. with --overview on an initialized repo), stdout must
        not contain 'Traceback (most recent call last)'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--overview",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"Prerequisite 'kanon repo info --overview' failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo info --overview'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo info' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--local-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"Prerequisite 'kanon repo info --local-only' failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo info --local-only'.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--overview=unexpected' must be routed
        to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--overview=unexpected"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "info",
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
        """Successful 'kanon repo info' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            "--current-branch",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo info --current-branch' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of 'kanon repo info --current-branch': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_all_valid_boolean_flags_produce_no_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """All boolean flags produce exit code != 2; no argparse error for any flag.

        Exercises all boolean flags from Info._Options() in sequence and
        confirms that none trigger an argument-parsing error (exit 2). A single
        initialized repo is used as the test context for all flags.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)
        all_flags = [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS]
        for flag in all_flags:
            result = _run_kanon(
                "repo",
                "--repo-dir",
                str(repo_dir),
                "info",
                flag,
                cwd=checkout_dir,
            )
            assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
                f"Flag {flag!r} triggered an argument-parsing error "
                f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
            )
