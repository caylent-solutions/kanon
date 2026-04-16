"""Integration tests for <linkfile> and <copyfile> manifest elements.

Tests cover:
- Symlink creation via _LinkFile._Link()
- File copying via _CopyFile._Copy()
- Absolute path handling for linkfile dest
- Overwrite behavior for existing targets
- Nested directory creation
- Error cases: missing source, directory source, invalid paths

AC-FUNC-003: symlink creation via <linkfile>
AC-FUNC-004: file copying via <copyfile>
AC-FUNC-005: absolute path handling
AC-FUNC-006: overwrite behavior when target already exists
AC-FUNC-007: nested directory creation
AC-FUNC-008: error cases
AC-TEST-001: all tests pass
"""

import os
import pathlib
import subprocess

import pytest

from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.project import _CopyFile, _LinkFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


_GIT_USER_NAME = "Linkfile Test User"
_GIT_USER_EMAIL = "linkfile-test@example.com"
_MANIFEST_FILENAME = "default.xml"


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _make_bare_clone(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> None:
    """Clone work_dir into a bare repository at bare_dir."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)


def _create_content_repo(base: pathlib.Path, name: str = "content") -> tuple[pathlib.Path, pathlib.Path]:
    """Create a named working and bare content repo with one committed file.

    Returns:
        Tuple of (work_dir, bare_dir).
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    readme = work_dir / "README.md"
    readme.write_text(f"# {name}\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", f"Initial commit for {name}"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return work_dir, bare_dir


def _write_manifest_repo(base: pathlib.Path, name: str, manifest_xml: str) -> pathlib.Path:
    """Write manifest_xml into a fresh bare git repo named `name`.

    Returns:
        Absolute path to the bare manifest repository.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return bare_dir


def _repo_init_and_sync(
    workspace: pathlib.Path,
    manifest_url: str,
) -> None:
    """Run repo init then repo sync in workspace using manifest_url."""
    from kanon_cli.repo import repo_sync
    from kanon_cli.repo.main import run_from_args

    repo_dot_dir = str(workspace / ".repo")
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
        ],
        repo_dir=repo_dot_dir,
    )
    repo_sync(str(workspace))


# ---------------------------------------------------------------------------
# Tests: <linkfile> symlink creation (AC-FUNC-003)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_creates_symlink(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() creates a symlink at the destination path.

    AC-FUNC-003: symlink creation via <linkfile>
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "source.txt"
    src_file.write_text("content", encoding="utf-8")

    link = _LinkFile(str(git_worktree), "source.txt", str(topdir), "dest.txt")
    link._Link()

    dest = topdir / "dest.txt"
    assert dest.exists() or os.path.lexists(str(dest)), (
        f"Expected symlink at {dest} after _LinkFile._Link(), but it was not created."
    )
    assert os.path.islink(str(dest)), f"Expected {dest} to be a symlink, but it is not a symlink."


@pytest.mark.integration
def test_linkfile_symlink_points_to_correct_target(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() creates a symlink whose resolved target is the source file.

    AC-FUNC-003: symlink target integrity
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "data.txt"
    src_content = "symlink target content"
    src_file.write_text(src_content, encoding="utf-8")

    link = _LinkFile(str(git_worktree), "data.txt", str(topdir), "link.txt")
    link._Link()

    dest = topdir / "link.txt"
    assert os.path.islink(str(dest)), f"Expected {dest} to be a symlink."
    resolved_content = dest.read_text(encoding="utf-8")
    assert resolved_content == src_content, (
        f"Expected symlink content {src_content!r} but got {resolved_content!r}. "
        f"Symlink target: {os.readlink(str(dest))!r}"
    )


@pytest.mark.integration
def test_linkfile_creates_nested_parent_directory(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() creates intermediate parent directories for the destination.

    AC-FUNC-007: nested directory creation for linkfile
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "tool.sh"
    src_file.write_text("#!/bin/sh\n", encoding="utf-8")

    link = _LinkFile(str(git_worktree), "tool.sh", str(topdir), "bin/scripts/tool.sh")
    link._Link()

    dest = topdir / "bin" / "scripts" / "tool.sh"
    assert os.path.islink(str(dest)), (
        f"Expected {dest} to be a symlink after nested directory creation, but it was not found."
    )


@pytest.mark.integration
def test_linkfile_overwrites_existing_symlink(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() replaces an existing symlink pointing to a stale target.

    AC-FUNC-006: overwrite behavior for linkfile
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "current.txt"
    src_file.write_text("current", encoding="utf-8")

    stale_target = tmp_path / "stale.txt"
    stale_target.write_text("stale", encoding="utf-8")
    dest = topdir / "link.txt"
    os.symlink(str(stale_target), str(dest))
    assert os.path.islink(str(dest)), "Pre-condition: stale symlink must exist."

    link = _LinkFile(str(git_worktree), "current.txt", str(topdir), "link.txt")
    link._Link()

    assert os.path.islink(str(dest)), f"Expected {dest} to remain a symlink after overwrite."
    resolved_content = dest.read_text(encoding="utf-8")
    assert resolved_content == "current", (
        f"Expected symlink to point to 'current' content after overwrite, but got: {resolved_content!r}"
    )


@pytest.mark.integration
def test_linkfile_absolute_dest_path_accepted(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() accepts and uses an absolute destination path.

    AC-FUNC-005: absolute path handling -- absolute dest is allowed per spec 17.1
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "config.yaml"
    src_file.write_text("key: value\n", encoding="utf-8")

    abs_dest = str(tmp_path / "abs_link.yaml")

    link = _LinkFile(str(git_worktree), "config.yaml", str(topdir), abs_dest)
    link._Link()

    assert os.path.islink(abs_dest), f"Expected a symlink at absolute path {abs_dest!r} after _LinkFile._Link()."
    resolved = pathlib.Path(abs_dest).read_text(encoding="utf-8")
    assert resolved == "key: value\n", f"Expected symlink to resolve to source content, but got {resolved!r}."


@pytest.mark.integration
def test_linkfile_absolute_dest_with_dotdot_raises(tmp_path: pathlib.Path) -> None:
    """_LinkFile._Link() rejects absolute dest containing '..' path components.

    AC-FUNC-005: absolute path handling -- path traversal rejected
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "safe.txt"
    src_file.write_text("safe content\n", encoding="utf-8")

    abs_dest_with_traversal = str(tmp_path / "subdir" / ".." / "traversal.txt")

    link = _LinkFile(str(git_worktree), "safe.txt", str(topdir), abs_dest_with_traversal)
    with pytest.raises(ManifestInvalidPathError, match=r'"\.\." not allowed in absolute dest'):
        link._Link()


# ---------------------------------------------------------------------------
# Tests: <copyfile> file copying (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_copies_file_content(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() copies source file content to destination path.

    AC-FUNC-004: file copying via <copyfile>
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "schema.json"
    src_content = '{"version": 1}\n'
    src_file.write_text(src_content, encoding="utf-8")

    copy = _CopyFile(str(git_worktree), "schema.json", str(topdir), "schema.json")
    copy._Copy()

    dest = topdir / "schema.json"
    assert dest.is_file(), f"Expected copied file at {dest} after _CopyFile._Copy(), but it was not found."
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    dest_content = dest.read_text(encoding="utf-8")
    assert dest_content == src_content, f"Expected dest content {src_content!r} but got {dest_content!r}."


@pytest.mark.integration
def test_copyfile_creates_nested_parent_directory(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() creates intermediate parent directories for the destination.

    AC-FUNC-007: nested directory creation for copyfile
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "values.yaml"
    src_file.write_text("env: prod\n", encoding="utf-8")

    copy = _CopyFile(str(git_worktree), "values.yaml", str(topdir), "helm/charts/values.yaml")
    copy._Copy()

    dest = topdir / "helm" / "charts" / "values.yaml"
    assert dest.is_file(), f"Expected {dest} to exist after nested directory creation in _CopyFile._Copy()."
    assert dest.read_text(encoding="utf-8") == "env: prod\n", "Expected copied content to match source."


@pytest.mark.integration
def test_copyfile_overwrites_existing_file(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() replaces an existing destination file with the updated source.

    AC-FUNC-006: overwrite behavior for copyfile
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "version.txt"
    src_file.write_text("v2.0.0\n", encoding="utf-8")

    dest = topdir / "version.txt"
    dest.write_text("v1.0.0\n", encoding="utf-8")
    assert dest.read_text(encoding="utf-8") == "v1.0.0\n", "Pre-condition: stale file must exist."

    copy = _CopyFile(str(git_worktree), "version.txt", str(topdir), "version.txt")
    copy._Copy()

    assert dest.is_file(), f"Expected {dest} to be a regular file after overwrite."
    updated_content = dest.read_text(encoding="utf-8")
    assert updated_content == "v2.0.0\n", (
        f"Expected destination to contain 'v2.0.0' after overwrite, but got: {updated_content!r}"
    )


@pytest.mark.integration
def test_copyfile_src_is_directory_raises_error(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() raises ManifestInvalidPathError when source is a directory.

    AC-FUNC-008: error case -- copying from directory not supported
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_dir = git_worktree / "adir"
    src_dir.mkdir()

    copy = _CopyFile(str(git_worktree), "adir", str(topdir), "dest.txt")
    with pytest.raises(ManifestInvalidPathError, match="copying from directory not supported"):
        copy._Copy()


@pytest.mark.integration
def test_copyfile_dest_is_directory_raises_error(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() raises ManifestInvalidPathError when destination is a directory.

    AC-FUNC-008: error case -- copying to directory not allowed
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    src_file = git_worktree / "file.txt"
    src_file.write_text("content\n", encoding="utf-8")

    dest_dir = topdir / "existing_dir"
    dest_dir.mkdir()

    copy = _CopyFile(str(git_worktree), "file.txt", str(topdir), "existing_dir")
    with pytest.raises(ManifestInvalidPathError, match="copying to directory not allowed"):
        copy._Copy()


@pytest.mark.integration
def test_copyfile_missing_source_does_not_create_dest(tmp_path: pathlib.Path) -> None:
    """_CopyFile._Copy() with missing source file does not create the destination.

    AC-FUNC-008: error case -- source file does not exist
    """
    git_worktree = tmp_path / "project"
    git_worktree.mkdir()
    topdir = tmp_path / "topdir"
    topdir.mkdir()

    # Source file intentionally absent.
    copy = _CopyFile(str(git_worktree), "nonexistent.txt", str(topdir), "output.txt")
    copy._Copy()

    dest = topdir / "output.txt"
    assert not dest.exists(), f"Expected {dest} to NOT exist when source is missing, but it was created."


# ---------------------------------------------------------------------------
# End-to-end pipeline test (AC-TEST-001 combined with AC-FUNC-003, AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_pipeline_with_linkfile_and_copyfile(tmp_path: pathlib.Path) -> None:
    """Full init -> sync pipeline creates linkfile symlink and copyfile copy.

    Uses real local file:// git repos. After repo sync, verifies that:
    - <linkfile> produces a symlink at the declared dest path
    - <copyfile> produces a regular file copy at the declared dest path

    AC-FUNC-003, AC-FUNC-004, AC-TEST-001
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    content_work, content_bare = _create_content_repo(repos_base, name="pkg")
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="pkg-bare" path="project-pkg">\n'
        '    <linkfile src="README.md" dest="links/pkg-readme.md" />\n'
        '    <copyfile src="README.md" dest="copies/pkg-readme.md" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-lf-cf", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    link_dest = workspace / "links" / "pkg-readme.md"
    assert os.path.islink(str(link_dest)), (
        f"Expected a symlink at {link_dest} created by <linkfile> after sync, "
        f"but it was not found. Workspace: {sorted(str(p) for p in workspace.iterdir())!r}"
    )
    link_content = link_dest.read_text(encoding="utf-8")
    assert "pkg" in link_content, f"Expected symlink to resolve to pkg README content but got: {link_content!r}"

    copy_dest = workspace / "copies" / "pkg-readme.md"
    assert copy_dest.is_file(), (
        f"Expected a regular file at {copy_dest} created by <copyfile> after sync, "
        f"but it was not found. Workspace: {sorted(str(p) for p in workspace.iterdir())!r}"
    )
    assert not os.path.islink(str(copy_dest)), (
        f"Expected {copy_dest} to be a regular file (not symlink) after <copyfile>."
    )
    copy_content = copy_dest.read_text(encoding="utf-8")
    assert "pkg" in copy_content, f"Expected copied file to contain pkg README content but got: {copy_content!r}"
