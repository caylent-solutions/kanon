"""Happy-path functional tests for 'kanon repo info'.

Exercises the happy path of the 'repo info' subcommand by invoking
``kanon repo info`` as a subprocess against a real initialized repo directory
created in a temporary directory. No mocking -- these tests use the full CLI
stack against actual git operations.

Covers:
- AC-TEST-001: 'kanon repo info' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo info' has a happy-path test.
- AC-FUNC-001: 'kanon repo info' executes successfully with documented default behavior.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _create_bare_content_repo,
    _create_manifest_repo,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Info Happy Test User"
_GIT_USER_EMAIL = "repo-info-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-info-happy test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "info-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _create_bare_content_repo, _create_manifest_repo, _setup_synced_repo,
# and _git are imported from tests.functional.conftest (canonical definitions).
# ---------------------------------------------------------------------------


def _setup_initialized_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
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

    bare_content = _create_bare_content_repo(
        repos_dir,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        content_file_name=_CONTENT_FILE_NAME,
        content_file_text=_CONTENT_FILE_TEXT,
    )
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(
        repos_dir,
        fetch_base,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
        manifest_bare_dir_name=_MANIFEST_BARE_DIR_NAME,
    )
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
        "main",
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
# AC-TEST-001 / AC-FUNC-001: kanon repo info with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo info' with default args exits 0.

    Verifies that running 'kanon repo info' with no additional arguments
    against a properly initialized repo directory exits 0 and prints manifest
    metadata to the combined output.
    """

    def test_repo_info_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info' with no extra args must exit 0.

        After a successful 'kanon repo init', invokes 'kanon repo info' with
        no project arguments. Verifies the process exits 0.
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
            f"'kanon repo info' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_info_prints_manifest_branch(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info' must print the manifest branch in combined output.

        The 'info' subcommand always prints a 'Manifest branch:' heading when
        the repo is properly initialized. This test verifies that text appears
        in the combined stdout + stderr output.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info' failed: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "Manifest branch" in combined, (
            f"Expected 'Manifest branch' in 'kanon repo info' output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_info_output_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info' must produce non-empty combined output.

        A successful invocation must produce at least some output describing
        the manifest state. An empty output would indicate the command ran
        without performing any work.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info' failed: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo info' produced empty combined output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo info has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoPositionalArgHappyPath:
    """AC-TEST-002: happy-path test for the project name positional argument.

    'repo info' accepts optional project names as positional arguments.
    When a project name from the manifest is supplied, 'repo info' prints
    per-project details. This class verifies that passing a valid project
    name exits 0 and produces project-specific output.

    Note: 'repo info <project>' requires the project worktree to exist on
    disk (i.e. after 'repo sync'), because GetProjects checks project.Exists.
    These tests therefore run 'repo init' followed by 'repo sync' as setup.
    """

    def test_repo_info_with_project_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info <project>' with a valid project name exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project name from the manifest as a positional argument to 'kanon repo
        info'. Verifies the process exits 0.
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
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo info {_PROJECT_NAME}' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_info_with_project_name_prints_project_heading(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info <project>' must print the 'Project:' heading for that project.

        When a valid project name is passed as a positional argument, the
        'info' subcommand must include a 'Project:' heading in the output.
        This verifies that the per-project info rendering path is exercised.
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
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info {_PROJECT_NAME}' failed: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "Project" in combined, (
            f"Expected 'Project' in 'kanon repo info {_PROJECT_NAME}' output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_info_with_project_path_alias_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo info <path>' with the project path alias exits 0.

        Verifies that passing a project by its path alias (as an alternative
        to the project name) also exits 0, exercising the path-based resolution
        branch inside the 'info' subcommand's GetProjects call.
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
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            _PROJECT_PATH,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo info {_PROJECT_PATH}' (path form) exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInfoChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo info'.

    Verifies that successful 'kanon repo info' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_info_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo info' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info' failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo info'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_info_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo info' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_initialized_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "info",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of successful 'kanon repo info': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repo_info_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo info' must not emit Python tracebacks to stderr.

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
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite 'kanon repo info' failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo info'.\n  stderr: {result.stderr!r}"
        )
