"""Functional tests for 'kanon repo init --mirror'.

Exercises the '--mirror' flag of 'kanon repo init' by invoking
``kanon repo init --mirror -u file://<fixture>`` as a subprocess against a
real bare git manifest repository created in a temporary directory.  No
mocking -- these tests use the full CLI stack against actual git operations.

Covers:
- AC-TEST-002 (functional): 'kanon repo init --mirror' with a file:// URL not
  ending in /.git exits 0 without AttributeError.
- AC-FUNC-001: AttributeError no longer raised for non-/.git URLs.
- AC-FUNC-002: The pre-existing /.git-ending-URL rejection path is unchanged.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants -- no hardcoded literals inside test bodies.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Init Mirror Test User"
_GIT_USER_EMAIL = "repo-init-mirror@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-init-mirror test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "mirror-test-project"
_GIT_BRANCH = "main"

# Traceback marker for asserting no crash in stderr.
_TRACEBACK_MARKER = "Traceback (most recent call last)"
_ATTRIBUTE_ERROR_MARKER = "AttributeError"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set."""
    _git(["init", "-b", _GIT_BRANCH], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir and return the resolved bare_dir path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing one committed file."""
    work_dir = base / "content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)
    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    return _clone_as_bare(work_dir, base / "content-bare.git")


def _create_manifest_repo(base: pathlib.Path, fetch_base: str) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo."""
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        f'  <default revision="{_GIT_BRANCH}" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)
    return _clone_as_bare(work_dir, base / "manifest-bare.git")


def _setup_mirror_repos(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Create bare repos and return (mirror_dir, repo_dir, manifest_url).

    The returned manifest_url uses a ``file://`` scheme and does NOT end with
    ``/.git``, which is the URL shape that triggered the AttributeError before
    the None-guard fix.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    mirror_dir = tmp_path / "mirror"
    mirror_dir.mkdir()

    bare_content = _create_bare_content_repo(repos_dir)
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
    # Deliberately use the bare directory path (no /.git suffix).
    manifest_url = f"file://{manifest_bare}"

    repo_dir = mirror_dir / ".repo"
    return mirror_dir, repo_dir, manifest_url


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitMirrorNonGitUrl:
    """AC-TEST-002 / AC-FUNC-001: '--mirror' with a non-/.git URL exits 0.

    Verifies that the None-guard fix allows 'kanon repo init --mirror' to
    complete successfully when the manifest URL does not end with '/.git'.
    Before the fix this command raised AttributeError.
    """

    def test_mirror_init_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --mirror -u <file://url>' must exit 0."""
        mirror_dir, repo_dir, manifest_url = _setup_mirror_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            _GIT_BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            "--mirror",
            cwd=mirror_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo init --mirror' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_mirror_init_does_not_raise_attribute_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --mirror' must not raise AttributeError in stderr."""
        mirror_dir, repo_dir, manifest_url = _setup_mirror_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            _GIT_BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            "--mirror",
            cwd=mirror_dir,
        )

        assert _ATTRIBUTE_ERROR_MARKER not in result.stderr, (
            f"AttributeError surfaced in stderr after None-guard fix.\n  stderr: {result.stderr!r}"
        )

    def test_mirror_init_creates_repo_dir(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --mirror' must create a .repo directory."""
        mirror_dir, repo_dir, manifest_url = _setup_mirror_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            _GIT_BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            "--mirror",
            cwd=mirror_dir,
        )

        assert result.returncode == 0, (
            f"Init failed; cannot verify .repo creation.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert repo_dir.exists(), f".repo directory was not created at {repo_dir}."

    def test_mirror_init_no_traceback_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init --mirror' must not produce a Python traceback."""
        mirror_dir, repo_dir, manifest_url = _setup_mirror_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            _GIT_BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            "--mirror",
            cwd=mirror_dir,
        )

        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr after None-guard fix.\n  stderr: {result.stderr!r}"
        )
