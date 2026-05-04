"""Happy-path functional tests for 'kanon repo start'.

Exercises the happy path of the 'repo start' subcommand by invoking
``kanon repo start`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo start' subcommand begins a new branch of development, starting from
the revision specified in the manifest. The first positional argument is the
required new branch name; the remaining positional arguments are optional
project references (defaulting to the current project if omitted). The
--all flag can be used to start the branch in all projects.

Covers:
- AC-TEST-001: 'kanon repo start' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo start' has a happy-path test.
- AC-FUNC-001: 'kanon repo start' executes successfully with documented default
  behavior (exit 0 when a valid branch name is supplied).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _git, _git_branch_list, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Start Happy Test User"
_GIT_USER_EMAIL = "repo-start-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-start-happy test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "start-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"

# Branch names used in start tests -- each test uses a unique name to avoid
# cross-test interference when the same synced repo is reused in parametrize.
_BRANCH_DEFAULT = "feature/default-start"
_BRANCH_WITH_PROJECT_NAME = "feature/start-by-name"
_BRANCH_WITH_PROJECT_PATH = "feature/start-by-path"

# Flag name constants
_FLAG_ALL = "--all"

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
# as in test_repo_overview_happy.py and test_repo_prune_happy.py.
# Consolidating them into a shared module requires touching those files,
# which is outside this task's Changes Manifest. This duplication is tracked
# in proposal E1-F2-S12-T4 as a follow-up DRY cleanup.
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
    worktrees exist on disk. The 'start' subcommand operates on project
    worktrees and requires them to be present before creating new branches.

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
# AC-TEST-001 / AC-FUNC-001: kanon repo start with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo start' with default args exits 0.

    Verifies that 'kanon repo start <branchname>' with only the mandatory
    branch name argument against a properly initialized and synced repo
    directory exits 0. When no project is specified, 'start' defaults to the
    project in the current working directory. Using --all starts the branch in
    every project in the manifest.
    """

    def test_repo_start_with_branch_name_all_projects_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo start <branch> --all' must exit 0 in a synced repo.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo start <branch> --all' to start the branch in every project
        in the manifest. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_DEFAULT,
            _FLAG_ALL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_DEFAULT} {_FLAG_ALL}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_start_with_branch_name_all_creates_branch_in_project(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo start <branch> --all' creates the new branch in each project.

        After a successful 'kanon repo start <branch> --all', the new branch
        must exist in the project worktree on disk. Verifies that git reports
        the branch was created by checking git branch output in the project dir.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_DEFAULT,
            _FLAG_ALL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo start {_BRANCH_DEFAULT} {_FLAG_ALL}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        branch_list = _git_branch_list(project_dir)
        assert _BRANCH_DEFAULT in branch_list, (
            f"Expected branch {_BRANCH_DEFAULT!r} to exist in project dir "
            f"{project_dir!r} after 'kanon repo start {_BRANCH_DEFAULT} {_FLAG_ALL}'.\n"
            f"  git branch output: {branch_list!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo start has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo start'.

    'repo start' requires the new branch name as the first positional argument.
    Subsequent positional arguments are optional project references (name or path).
    Both forms (by project name and by project path) are exercised via
    @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_start_with_branch_and_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo start <branch> <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project reference (name or path) as the second positional argument to
        'kanon repo start'. Verifies the process exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {branch_name} {project_ref}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "branch_name,project_ref",
        [
            (_BRANCH_WITH_PROJECT_NAME, _PROJECT_NAME),
            (_BRANCH_WITH_PROJECT_PATH, _PROJECT_PATH),
        ],
    )
    def test_repo_start_with_branch_and_project_ref_creates_branch(
        self,
        tmp_path: pathlib.Path,
        branch_name: str,
        project_ref: str,
    ) -> None:
        """'kanon repo start <branch> <project_ref>' creates the branch in the project dir.

        After a successful 'kanon repo start <branch> <project_ref>', verifies
        that git reports the new branch exists in the project's worktree.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            branch_name,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo start {branch_name} {project_ref}' failed: {result.stderr!r}"
        )

        project_dir = checkout_dir / _PROJECT_PATH
        branch_list = _git_branch_list(project_dir)
        assert branch_name in branch_list, (
            f"Expected branch {branch_name!r} to exist in project dir "
            f"{project_dir!r} after 'kanon repo start {branch_name} {project_ref}'.\n"
            f"  git branch output: {branch_list!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo start'.

    Verifies that successful 'kanon repo start' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo start <branch> --all' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo start <branch> --all'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_DEFAULT,
            _FLAG_ALL,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo start {_BRANCH_DEFAULT} {_FLAG_ALL}' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_start_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo start' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo start'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_start_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo start' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo start': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_start_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo start' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo start'.\n  stderr: {channel_result.stderr!r}"
        )
