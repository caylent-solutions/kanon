"""Happy-path functional tests for 'kanon repo overview'.

Exercises the happy path of the 'repo overview' subcommand by invoking
``kanon repo overview`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo overview' subcommand displays an overview of unmerged project
branches. In a freshly synced repository no unmerged branches exist, so
the command exits 0 with no output. This file verifies that contract.

Covers:
- AC-TEST-001: 'kanon repo overview' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo overview' has a happy-path test.
- AC-FUNC-001: 'kanon repo overview' executes successfully with documented
  default behavior (exit 0, no output when no unmerged branches).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Overview Happy Test User"
_GIT_USER_EMAIL = "repo-overview-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-overview-happy test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "overview-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"

# Flag name constants -- referenced by assertions, never as bare strings inside logic
_FLAG_CURRENT_BRANCH = "--current-branch"
_FLAG_NO_CURRENT_BRANCH = "--no-current-branch"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo) follow the same pattern
# as in test_repo_info_happy.py and test_repo_passthrough.py. Consolidating
# them into a shared module requires touching those files, which is outside
# this task's Changes Manifest. This duplication is tracked as a follow-up
# DRY cleanup.
# ---------------------------------------------------------------------------


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
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
        '  <default revision="main" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / _MANIFEST_BARE_DIR_NAME)


def _setup_synced_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Runs 'kanon repo init' followed by 'kanon repo sync' so that project
    worktrees exist on disk. The 'overview' subcommand requires project
    worktrees to be present because it calls GetBranches() on each project.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init and sync.

    Raises:
        AssertionError: When kanon repo init or repo sync exits with a non-zero code.
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

    init_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        "main",
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )
    assert init_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo init' failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )

    sync_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        "--jobs=1",
        cwd=checkout_dir,
    )
    assert sync_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo sync' failed with exit {sync_result.returncode}.\n"
        f"  stdout: {sync_result.stdout!r}\n"
        f"  stderr: {sync_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo overview with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo overview' with default args exits 0.

    Verifies that 'kanon repo overview' with no additional arguments against a
    properly initialized and synced repo directory exits 0. In a freshly synced
    repository no local unmerged branches exist, so the command exits 0 with
    empty output -- this is the documented default behavior.
    """

    def test_repo_overview_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo overview' with no additional arguments. A freshly synced
        repository has no local unmerged branches, so the command exits 0
        without producing output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_empty_output_when_no_unmerged_branches(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview' produces empty combined output in a clean repo.

        The 'overview' subcommand only emits output when there are unmerged
        local branches. A freshly synced repository has no such branches, so
        both stdout and stderr must be empty on a successful invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo overview' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo overview' produced unexpected output in a clean repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_with_no_current_branch_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --no-current-branch' exits 0 in a clean repo.

        The {flag} flag instructs the 'overview' subcommand to consider all
        local branches (not just the checked-out one). In a freshly synced
        repository there are no local unmerged branches regardless of this
        flag, so the command must still exit 0.
        """.format(flag=_FLAG_NO_CURRENT_BRANCH)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _FLAG_NO_CURRENT_BRANCH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview {_FLAG_NO_CURRENT_BRANCH}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_with_current_branch_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch' exits 0 in a clean repo.

        The {flag} flag restricts output to branches currently checked out in
        each project. In a freshly synced repository the checked-out branch
        has no unmerged commits, so the command exits 0 with no output.
        """.format(flag=_FLAG_CURRENT_BRANCH)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _FLAG_CURRENT_BRANCH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview {_FLAG_CURRENT_BRANCH}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo overview has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewPositionalArgHappyPath:
    """AC-TEST-002: happy-path test for the project name positional argument.

    'repo overview' accepts optional project names as positional arguments to
    restrict output to specific projects. When a valid project name from the
    manifest is supplied in a cleanly synced repository, the command exits 0
    (no unmerged branches exist for that project either).
    """

    def test_repo_overview_with_project_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview <project>' with a valid project name exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project name from the manifest as a positional argument to 'kanon repo
        overview'. The project has no unmerged branches, so the command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview {_PROJECT_NAME}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_with_project_name_produces_no_output_in_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview <project>' produces no output in a cleanly synced repo.

        When a valid project name is passed as a positional argument and that
        project has no local unmerged branches, the 'overview' subcommand must
        produce no output on stdout or stderr.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo overview {_PROJECT_NAME}' failed: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo overview {_PROJECT_NAME}' produced unexpected output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_with_project_path_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview <path>' with the project path alias exits 0.

        Verifies that passing a project by its path alias (as an alternative
        to the project name) also exits 0, exercising the path-based resolution
        branch inside the 'overview' subcommand's GetProjects call.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _PROJECT_PATH,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview {_PROJECT_PATH}' (path form) exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_overview_with_project_name_and_current_branch_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo overview --current-branch <project>' exits 0 for a synced project.

        Combines the {flag} flag with a positional project name argument.
        In a cleanly synced repository the checked-out branch for the named
        project has no unmerged commits, so the command must exit 0.
        """.format(flag=_FLAG_CURRENT_BRANCH)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            _FLAG_CURRENT_BRANCH,
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo overview {_FLAG_CURRENT_BRANCH} {_PROJECT_NAME}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoOverviewChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo overview'.

    Verifies that successful 'kanon repo overview' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_overview_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo overview' must not emit Python tracebacks to stdout.

        On success, stdout must not contain '{marker}'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo overview' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo overview'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_overview_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo overview' must not emit '{prefix}' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with '{prefix}' on stdout.
        """.format(prefix=_ERROR_PREFIX)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo overview' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo overview': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repo_overview_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo overview' must not emit Python tracebacks to stderr.

        On success, stderr must not contain '{marker}'. A traceback on stderr
        during a successful run indicates an unhandled exception was swallowed
        rather than propagated correctly.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "overview",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo overview' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo overview'.\n  stderr: {result.stderr!r}"
        )
