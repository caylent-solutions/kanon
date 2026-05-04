"""Happy-path functional tests for 'kanon repo prune'.

Exercises the happy path of the 'repo prune' subcommand by invoking
``kanon repo prune`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo prune' subcommand deletes local topic branches that have already
been merged into the upstream. In a freshly synced repository no local
branches have been created, so no branches are prunable and the command
exits 0 with no output. This file verifies that contract.

Covers:
- AC-TEST-001: 'kanon repo prune' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo prune' has a happy-path test.
- AC-FUNC-001: 'kanon repo prune' executes successfully with documented default
  behavior (exit 0, no output when no merged local branches exist).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Prune Happy Test User"
_GIT_USER_EMAIL = "repo-prune-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-prune-happy test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "prune-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"

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
# as in test_repo_overview_happy.py and test_repo_info_happy.py.
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
    worktrees exist on disk. The 'prune' subcommand requires project
    worktrees to be present because it calls PruneHeads() on each project.

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
# AC-TEST-001 / AC-FUNC-001: kanon repo prune with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo prune' with default args exits 0.

    Verifies that 'kanon repo prune' with no additional arguments against a
    properly initialized and synced repo directory exits 0. In a freshly synced
    repository no local branches have been created, so no branches are prunable
    and the command exits 0 -- this is the documented default behavior.
    """

    def test_repo_prune_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo prune' with no additional arguments. A freshly synced
        repository has no local merged branches, so the command exits 0
        without producing output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo prune' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_prune_empty_output_when_no_merged_branches(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune' produces empty combined output in a clean repo.

        The prune subcommand only emits output when there are remaining
        (un-pruned) local branches -- branches that could not be deleted or are
        pending review. A freshly synced repository has no local branches at
        all, so both stdout and stderr must be empty on a successful invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo prune' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo prune' produced unexpected output in a clean repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo prune has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPrunePositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional project-ref argument.

    'repo prune' accepts optional project names or project paths as positional
    arguments to restrict pruning to specific projects. When a valid project
    reference from the manifest is supplied in a cleanly synced repository, the
    command exits 0 (no merged branches exist for that project either).

    Both the project name (_PROJECT_NAME) and the project path (_PROJECT_PATH)
    forms are exercised via @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize("project_ref", [_PROJECT_NAME, _PROJECT_PATH])
    def test_repo_prune_with_project_ref_exits_zero(self, tmp_path: pathlib.Path, project_ref: str) -> None:
        """'kanon repo prune <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project reference (name or path) as a positional argument to 'kanon repo
        prune'. The project has no local merged branches, so the command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo prune {project_ref}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("project_ref", [_PROJECT_NAME, _PROJECT_PATH])
    def test_repo_prune_with_project_ref_produces_no_output_in_clean_repo(
        self, tmp_path: pathlib.Path, project_ref: str
    ) -> None:
        """'kanon repo prune <project_ref>' produces no output in a cleanly synced repo.

        When a valid project reference (name or path) is passed as a positional
        argument and that project has no local merged branches, the 'prune'
        subcommand must produce no output on stdout or stderr.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo prune {project_ref}' failed: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo prune {project_ref}' produced unexpected output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo prune'.

    Verifies that successful 'kanon repo prune' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_prune_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' must not emit Python tracebacks to stdout.

        On success, stdout must not contain '{marker}'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo prune' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo prune'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_prune_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' must not emit '{prefix}' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with '{prefix}' on stdout.
        """.format(prefix=_ERROR_PREFIX)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo prune' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo prune': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repo_prune_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' must not emit Python tracebacks to stderr.

        On success, stderr must not contain '{marker}'. A traceback on stderr
        during a successful run indicates an unhandled exception was swallowed
        rather than propagated correctly.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo prune' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo prune'.\n  stderr: {result.stderr!r}"
        )
