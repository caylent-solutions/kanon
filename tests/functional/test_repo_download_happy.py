"""Happy-path functional tests for 'kanon repo download'.

Exercises the happy path of the 'repo download' subcommand by invoking
``kanon repo download`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo download' subcommand downloads a change (patch set) from a
Gerrit-style review system and checks it out in the project's local working
directory. Arguments are of the form ``{[project] change[/patchset]}...``.

To exercise the happy path without a real Gerrit server, the test suite:

1. Creates a synced repo via ``kanon repo init`` and ``kanon repo sync``.
2. Commits a new file to the bare content repository, creating a downloadable
   commit that is not yet present in the project worktree.
3. Creates a Gerrit-style ref (``refs/changes/XX/CHANGEID/PATCHSET``) in the
   bare content repository pointing to that commit, so that
   ``git fetch <remote> refs/changes/XX/CHANGEID/PATCHSET`` succeeds.
4. Invokes ``kanon repo download`` with various positional argument forms and
   verifies the process exits 0.

Positional arguments exercised (AC-TEST-002):

- ``PROJECT_NAME CHANGE_ID/PATCHSET`` -- project identified by manifest name.
- ``PROJECT_PATH CHANGE_ID/PATCHSET`` -- project identified by checkout path.
- ``CHANGE_ID`` -- change ID only with no explicit patchset; auto-detection
  falls back to patchset 1 when ls-remote finds no matching refs.
- ``CHANGE_ID/PATCHSET`` -- explicit patchset (via cwd = project worktree).

Covers:
- AC-TEST-001: 'kanon repo download' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo download' has a happy-path test.
- AC-FUNC-001: 'kanon repo download' executes successfully with documented
  default behavior (exit 0, change checked out).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _git, _run_kanon, _setup_synced_repo

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Download Happy Test User"
_GIT_USER_EMAIL = "repo-download-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "download-test-project"

# Gerrit-style change ID and patch set used across all tests.
# Change 123 maps to refs/changes/23/123/1 (change_id % 100 == 23).
_CHANGE_ID = 123
_PATCH_SET_ID = 1
_CHANGE_DIR_BUCKET = _CHANGE_ID % 100  # 23

# The downloadable file content committed to the bare repo to create the
# change that will be fetched.
_DOWNLOAD_CONTENT_FILE = "download-change.txt"
_DOWNLOAD_CONTENT_TEXT = "content for download happy-path test"
_DOWNLOAD_COMMIT_MSG = "Add downloadable change for functional test"

# Gerrit-style ref name that maps change ID 123 / patchset 1.
_GERRIT_REF = f"refs/changes/{_CHANGE_DIR_BUCKET:02d}/{_CHANGE_ID}/{_PATCH_SET_ID}"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# CLI token constants.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_DOWNLOAD = "download"
_CLI_FLAG_REPO_DIR = "--repo-dir"

# Formatted positional change argument strings for diagnostics.
_CHANGE_WITH_PATCHSET = f"{_CHANGE_ID}/{_PATCH_SET_ID}"
_CHANGE_ONLY = str(_CHANGE_ID)


# ---------------------------------------------------------------------------
# Helper: create a Gerrit-style change ref in the bare content repo
# ---------------------------------------------------------------------------


def _add_gerrit_change_to_bare_repo(
    bare_repo: pathlib.Path,
    project_worktree: pathlib.Path,
) -> str:
    """Commit a new file to the bare repo and create a Gerrit-style ref.

    Creates a new commit in a temporary working clone of ``bare_repo``,
    pushes it to the bare repo as ``_GERRIT_REF``, and returns the commit
    SHA1. After this call, ``git fetch <remote> _GERRIT_REF`` from a synced
    project worktree will succeed.

    Args:
        bare_repo: Absolute path to the bare content git repository.
        project_worktree: Absolute path to the project working directory
            (used only to configure git user identity for the new commit).

    Returns:
        The full SHA1 of the newly created commit.

    Raises:
        RuntimeError: When any git operation fails.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as work_str:
        work = pathlib.Path(work_str)

        # Clone the bare repo into a temporary working directory.
        _git(["clone", str(bare_repo), str(work / "work")], cwd=work)
        work_dir = work / "work"

        # Configure identity for the new commit.
        _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
        _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

        # Commit a new file on a detached branch from the current HEAD.
        (work_dir / _DOWNLOAD_CONTENT_FILE).write_text(_DOWNLOAD_CONTENT_TEXT, encoding="utf-8")
        _git(["add", _DOWNLOAD_CONTENT_FILE], cwd=work_dir)
        _git(["commit", "-m", _DOWNLOAD_COMMIT_MSG], cwd=work_dir)

        # Push the new commit to the bare repo as the Gerrit-style ref.
        _git(["push", "origin", f"HEAD:{_GERRIT_REF}"], cwd=work_dir)

        # Retrieve and return the new commit SHA1.
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git rev-parse HEAD failed in {work_dir!r}:\n  stderr: {result.stderr!r}")
        return result.stdout.strip()


def _locate_bare_content_repo(repos_dir: pathlib.Path) -> pathlib.Path:
    """Return the absolute path to the bare content repo under repos_dir.

    The canonical bare content repo is named ``<_PROJECT_NAME>.git`` and is
    created by ``_create_bare_content_repo`` in conftest. This helper
    reconstructs that path deterministically.

    Args:
        repos_dir: Parent directory that contains the bare repos.

    Returns:
        The absolute path to the bare content git repository.

    Raises:
        FileNotFoundError: When the expected bare content repo does not exist.
    """
    bare_path = repos_dir / f"{_PROJECT_NAME}.git"
    if not bare_path.exists():
        raise FileNotFoundError(
            f"Bare content repo not found at {bare_path!r}. "
            f"Ensure _setup_synced_repo was called with project_name={_PROJECT_NAME!r}."
        )
    return bare_path


def _setup_download_repo(
    tmp_path: pathlib.Path,
) -> "tuple[pathlib.Path, pathlib.Path, str]":
    """Create a synced repo with a Gerrit-style change ref in the bare repo.

    Performs the shared setup steps required by all download happy-path tests:

    1. Creates bare repos and runs ``kanon repo init`` + ``kanon repo sync``
       via ``_setup_synced_repo``.
    2. Locates the bare content repository.
    3. Commits a new file to the bare content repo and creates
       ``_GERRIT_REF`` pointing to it.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A 3-tuple of ``(checkout_dir, repo_dir, change_commit_sha)`` where
        ``checkout_dir`` is the worktree root, ``repo_dir`` is the ``.repo``
        directory, and ``change_commit_sha`` is the SHA1 of the downloadable
        commit.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` fails.
    """
    repos_dir = tmp_path / "repos"

    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
    )

    project_worktree = checkout_dir / _PROJECT_PATH
    bare_repo = _locate_bare_content_repo(repos_dir)
    change_sha = _add_gerrit_change_to_bare_repo(bare_repo, project_worktree)

    return checkout_dir, repo_dir, change_sha


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo download with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo download' with default args exits 0.

    Verifies that 'kanon repo download <change_id>/<patchset>' against a
    properly initialized and synced repo with a Gerrit-style ref in the
    bare content repository exits 0.
    """

    def test_repo_download_with_explicit_patchset_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo download PROJECT CHANGE/PATCHSET' exits 0 in a valid repo.

        After 'kanon repo init', 'kanon repo sync', and creation of the
        Gerrit-style ref in the bare content repo, invokes
        'kanon repo download <project_name> <change_id>/<patchset>' and
        verifies the process exits 0.
        """
        checkout_dir, repo_dir, _sha = _setup_download_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_download_with_explicit_patchset_checks_out_commit(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo download PROJECT CHANGE/PATCHSET' checks out the downloaded commit.

        After 'kanon repo download', the project worktree HEAD must point at
        the downloaded commit SHA1. Verifies the documented default behavior
        of the subcommand (checkout mode without --cherry-pick, --revert, or
        --ff-only flags).
        """
        checkout_dir, repo_dir, change_sha = _setup_download_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

        # The download command checks out the fetched commit, leaving the
        # project worktree in detached HEAD state at the change commit.
        project_dir = checkout_dir / _PROJECT_PATH
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        assert head_result.returncode == 0, (
            f"git rev-parse HEAD failed in {project_dir!r}:\n  stderr: {head_result.stderr!r}"
        )
        actual_head = head_result.stdout.strip()
        assert actual_head == change_sha, (
            f"Expected project HEAD to be the downloaded commit {change_sha!r}, "
            f"but got {actual_head!r} after "
            f"'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}'."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo download has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for positional arguments of 'repo download'.

    'repo download' accepts optional ``[project]`` followed by
    ``change[/patchset]``. Projects may be referenced by manifest name or by
    their relative checkout path. Both forms plus the implicit-project form
    (change ID only, run from the project worktree) are exercised here.
    """

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["by-project-name", "by-project-path"],
    )
    def test_repo_download_with_explicit_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo download <project_ref> <change_id>/<patchset>' exits 0.

        After setup (init, sync, Gerrit ref creation), passes the project
        reference (name or path) as the first positional argument to
        'kanon repo download'. Verifies the process exits 0 for each valid
        reference form.
        """
        checkout_dir, repo_dir, _sha = _setup_download_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            project_ref,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download {project_ref} {_CHANGE_WITH_PATCHSET}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_download_change_id_only_from_project_cwd_exits_zero(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """'kanon repo download <change_id>' from the project worktree exits 0.

        When only a numeric change ID is supplied (no explicit project), the
        download command defaults to the project in the current working
        directory. Invokes 'kanon repo download <change_id>' with cwd set to
        the project worktree and verifies the process exits 0.
        """
        checkout_dir, repo_dir, _sha = _setup_download_repo(tmp_path)
        project_dir = checkout_dir / _PROJECT_PATH

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _CHANGE_ONLY,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download {_CHANGE_ONLY}' from project cwd "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo download'.

    Verifies that successful 'kanon repo download' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.

    All channel assertions share a single class-scoped fixture invocation to
    avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo download PROJECT CHANGE/PATCHSET' once and return the result.

        Uses tmp_path_factory for a class-scoped fixture so the setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo download'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) or the
                download itself exits with a non-zero code.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir, _sha = _setup_download_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_download_success_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo download' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo download'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_download_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo download' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo download': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_repo_download_success_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo download' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo download'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
