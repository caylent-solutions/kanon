"""E2E tests for kanon repo init/sync/envsubst/status with real local git repos.

Each test creates real bare git repositories in tmp_path, writes manifest XML,
and invokes kanon CLI subcommands via subprocess. No mocking -- these tests
exercise the full stack against actual git operations.

Tests in this module are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from content repo"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_PATH = "my-project"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo with one committed file and return its path.

    Initialises a temporary non-bare working directory, commits one file,
    then clones it as a bare repo so the bare URL can be used for repo init.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare git repository directory.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    bare_dir = base / "content-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir.resolve()


def _create_manifest_repo(base: pathlib.Path, content_repo_url: str) -> pathlib.Path:
    """Create a bare manifest git repo containing a default.xml manifest.

    The manifest references one project pointing to content_repo_url with
    path _PROJECT_PATH. The manifest also includes an environment variable
    placeholder so that envsubst has something to substitute.

    Args:
        base: Parent directory under which repos are created.
        content_repo_url: file:// URL of the bare content repository to reference.

    Returns:
        The absolute path to the bare manifest repository directory.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repo_url}/../" />\n'
        '  <default revision="main" remote="local" />\n'
        f'  <project name="content-bare" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    manifest_path = work_dir / _MANIFEST_FILENAME
    manifest_path.write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / "manifest-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir.resolve()


def _create_envsubst_manifest_repo(base: pathlib.Path, content_repo_url: str) -> pathlib.Path:
    """Create a bare manifest repo with an ${ENV_VAR} placeholder in the manifest.

    The placeholder ${KANON_TEST_FETCH_URL} is used as the remote fetch
    attribute so that envsubst can substitute it with the actual URL.

    Args:
        base: Parent directory under which repos are created.
        content_repo_url: file:// URL of the bare content repository to reference.

    Returns:
        The absolute path to the bare manifest repository directory.
    """
    work_dir = base / "manifest-envsubst-work"
    work_dir.mkdir()

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

    parent_url = str(pathlib.Path(content_repo_url.replace("file://", "")).parent)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="local" fetch="${KANON_TEST_FETCH_URL}" />\n'
        '  <default revision="main" remote="local" />\n'
        f'  <project name="content-bare" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    manifest_path = work_dir / _MANIFEST_FILENAME
    manifest_path.write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest with placeholder"], cwd=work_dir)

    bare_dir = base / "manifest-envsubst-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)

    return bare_dir.resolve(), parent_url


# ---------------------------------------------------------------------------
# AC-TEST-001: kanon repo init with real git repo
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestKanonRepoInitRealGit:
    """AC-TEST-001: kanon repo init -u file://... -b main -m manifest.xml succeeds."""

    def test_kanon_repo_init_real_git(self, tmp_path: pathlib.Path) -> None:
        """Verify repo init exits 0 and creates a .repo directory.

        Creates a bare manifest git repo in tmp_path, then runs:
            kanon repo init -u file://<manifest-bare-url> -b main -m default.xml
        with --repo-dir pointing into a checkout directory. Asserts that the
        process exits 0 and that the .repo directory is created.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        content_url = f"file://{bare_content}"

        bare_manifest = _create_manifest_repo(repos_dir, content_url)
        manifest_url = f"file://{bare_manifest}"

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
            f"kanon repo init exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert repo_dir.is_dir(), (
            f".repo directory was not created at {repo_dir!r} after kanon repo init.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_kanon_repo_init_creates_manifests_directory(self, tmp_path: pathlib.Path) -> None:
        """After a successful repo init the .repo/manifests/ directory must exist."""
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        content_url = f"file://{bare_content}"
        bare_manifest = _create_manifest_repo(repos_dir, content_url)
        manifest_url = f"file://{bare_manifest}"
        repo_dir = checkout_dir / ".repo"

        _run_kanon(
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

        manifests_dir = repo_dir / "manifests"
        assert manifests_dir.is_dir(), f".repo/manifests/ was not created at {manifests_dir!r} after kanon repo init."


# ---------------------------------------------------------------------------
# AC-TEST-002: kanon repo sync with real git repos
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestKanonRepoSyncRealGit:
    """AC-TEST-002: kanon repo sync clones projects and files exist on disk."""

    def _init_checkout(self, tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
        """Run kanon repo init and return (checkout_dir, repo_dir).

        Args:
            tmp_path: pytest-provided temporary directory root.

        Returns:
            Tuple of (checkout_dir, repo_dir) after a successful init.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        content_url = f"file://{bare_content}"
        bare_manifest = _create_manifest_repo(repos_dir, content_url)
        manifest_url = f"file://{bare_manifest}"
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
            f"Prerequisite kanon repo init failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        return checkout_dir, repo_dir

    def test_kanon_repo_sync_real_git(self, tmp_path: pathlib.Path) -> None:
        """kanon repo sync must exit 0 and clone the project into checkout_dir."""
        checkout_dir, repo_dir = self._init_checkout(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"kanon repo sync exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_kanon_repo_sync_clones_project_directory(self, tmp_path: pathlib.Path) -> None:
        """After sync the project directory defined in the manifest must exist."""
        checkout_dir, repo_dir = self._init_checkout(tmp_path)

        _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        project_dir = checkout_dir / _PROJECT_PATH
        assert project_dir.is_dir(), f"Project directory {project_dir!r} was not created after kanon repo sync."

    def test_kanon_repo_sync_files_exist_in_cloned_project(self, tmp_path: pathlib.Path) -> None:
        """After sync the committed file from the content repo must exist inside the project."""
        checkout_dir, repo_dir = self._init_checkout(tmp_path)

        _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        readme = checkout_dir / _PROJECT_PATH / _CONTENT_FILE_NAME
        assert readme.is_file(), f"Expected {readme!r} to exist after kanon repo sync."
        content = readme.read_text(encoding="utf-8").strip()
        assert content == _CONTENT_FILE_TEXT, f"Content of {readme!r} was {content!r}, expected {_CONTENT_FILE_TEXT!r}."


# ---------------------------------------------------------------------------
# AC-TEST-003: kanon repo envsubst processes manifest XML with env var substitution
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestKanonRepoEnvsubstRealGit:
    """AC-TEST-003: kanon repo envsubst substitutes ${VAR} placeholders in manifest XML."""

    def test_kanon_repo_envsubst_real_git(self, tmp_path: pathlib.Path) -> None:
        """envsubst replaces ${KANON_TEST_FETCH_URL} in the manifest with the real URL.

        Sets up a manifest that contains a ${KANON_TEST_FETCH_URL} placeholder in
        the remote fetch attribute, runs kanon repo init, then kanon repo envsubst
        with the env var set. Verifies the placeholder is replaced in the
        on-disk manifest XML file.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        content_url = f"file://{bare_content}"

        bare_manifest, parent_url = _create_envsubst_manifest_repo(repos_dir, content_url)
        manifest_url = f"file://{bare_manifest}"
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
        assert init_result.returncode == 0, f"kanon repo init failed: {init_result.stderr!r}"

        fetch_url = f"file://{parent_url}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "envsubst",
            cwd=checkout_dir,
            extra_env={"KANON_TEST_FETCH_URL": fetch_url},
        )

        assert result.returncode == 0, (
            f"kanon repo envsubst exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

        manifest_on_disk = repo_dir / "manifests" / _MANIFEST_FILENAME
        assert manifest_on_disk.is_file(), f"Manifest file {manifest_on_disk!r} not found after envsubst."
        manifest_text = manifest_on_disk.read_text(encoding="utf-8")
        assert "${KANON_TEST_FETCH_URL}" not in manifest_text, (
            f"Placeholder ${{KANON_TEST_FETCH_URL}} was not substituted in {manifest_on_disk!r}.\n"
            f"  manifest content: {manifest_text!r}"
        )
        assert fetch_url in manifest_text, (
            f"Expected fetch URL {fetch_url!r} to appear in manifest after envsubst.\n"
            f"  manifest content: {manifest_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: kanon repo status after sync
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestKanonRepoStatusAfterSync:
    """AC-TEST-004: kanon repo status reports clean state after a fresh sync."""

    def test_kanon_repo_status_after_sync(self, tmp_path: pathlib.Path) -> None:
        """After a fresh sync, repo status must exit 0 with no modified files.

        Runs kanon repo init followed by kanon repo sync, then invokes
        kanon repo status. Verifies the command exits 0, indicating a clean
        working tree state (no uncommitted changes in any project).
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        content_url = f"file://{bare_content}"
        bare_manifest = _create_manifest_repo(repos_dir, content_url)
        manifest_url = f"file://{bare_manifest}"
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
        assert init_result.returncode == 0, f"kanon repo init failed: {init_result.stderr!r}"

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )
        assert sync_result.returncode == 0, f"kanon repo sync failed: {sync_result.stderr!r}"

        status_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )

        assert status_result.returncode == 0, (
            f"kanon repo status exited {status_result.returncode} after a fresh sync, expected 0.\n"
            f"  stdout: {status_result.stdout!r}\n"
            f"  stderr: {status_result.stderr!r}"
        )
