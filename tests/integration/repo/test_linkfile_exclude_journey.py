"""Lifecycle integration tests for the linkfile exclude attribute.

Tests exercise the full repo sync lifecycle with real git repos created in
tmp_path. The exclude attribute allows a manifest to link all children of a
directory except specified names. This is a Caylent addition to the upstream
repo tool.

AC-FUNC-001: File exists at tests/integration/repo/test_linkfile_exclude_journey.py
AC-FUNC-002: At least 12 test functions defined
AC-FUNC-003: All tests use real git repos created in tmp_path (no mocks)
AC-FUNC-004: No Caylent-specific references in test code
AC-FUNC-005: Tests cover single, multiple, whitespace, nonexistent, empty excludes
AC-FUNC-006: Tests cover always-excluded entries (.git, .packages, .repo* prefixes)
AC-FUNC-007: Tests cover error paths: glob src + exclude raises, file src + exclude raises
AC-FUNC-008: Tests cover absolute dest path with exclude
AC-FUNC-009: Tests cover no-exclude case (single directory symlink)
AC-FUNC-010: Tests cover full kanon install lifecycle with exclude on marketplace linkfile
"""

import os
import pathlib
import subprocess

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.main import run_from_args


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Exclude Journey Test User"
_GIT_USER_EMAIL = "exclude-journey-test@example.com"
_MANIFEST_FILENAME = "default.xml"


# ---------------------------------------------------------------------------
# Shared git helpers
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


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _make_bare_clone(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> None:
    """Clone work_dir into a bare repository at bare_dir."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)


# ---------------------------------------------------------------------------
# Repo setup helpers
# ---------------------------------------------------------------------------


def _create_content_repo_with_pkg_dir(
    base: pathlib.Path,
    name: str,
    children: list[str],
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a named content repo with a pkg/ directory containing named children.

    Each entry in children is created as a subdirectory under pkg/ with a
    marker file inside it.  A README.md is also created directly in pkg/.

    Args:
        base: Parent directory for all repos.
        name: Logical name used as directory prefix for work and bare repos.
        children: Names of subdirectories to create under pkg/.

    Returns:
        Tuple of (work_dir, bare_dir).
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    pkg_dir = work_dir / "pkg"
    pkg_dir.mkdir()

    (pkg_dir / "README.md").write_text(f"# {name} package\n", encoding="utf-8")
    for child in children:
        child_dir = pkg_dir / child
        child_dir.mkdir()
        (child_dir / "marker.txt").write_text(f"{child} content\n", encoding="utf-8")

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", f"Initial commit for {name}"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return work_dir, bare_dir


def _write_manifest_repo(
    base: pathlib.Path,
    name: str,
    manifest_xml: str,
) -> pathlib.Path:
    """Write manifest_xml into a fresh bare git repo named name.

    Args:
        base: Parent directory for the repositories.
        name: Logical name used as directory prefix.
        manifest_xml: Full XML content for the default.xml manifest.

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
    """Run repo init then repo sync in workspace using manifest_url.

    Args:
        workspace: Directory in which to initialise the repo client.
        manifest_url: file:// URL of the bare manifest repository.
    """
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
    repo_pkg.repo_sync(str(workspace))


def _build_manifest_xml(
    fetch_base_url: str,
    project_name: str,
    project_path: str,
    linkfile_src: str,
    linkfile_dest: str,
    exclude: str | None,
) -> str:
    """Build a manifest XML string for a single project with one linkfile element.

    Args:
        fetch_base_url: file:// URL of the directory containing bare project repos.
        project_name: Name of the project in the manifest (basename of bare repo).
        project_path: Path attribute for the project in the workspace.
        linkfile_src: src attribute for the linkfile element.
        linkfile_dest: dest attribute for the linkfile element.
        exclude: Optional exclude attribute value. Omitted from XML when None.

    Returns:
        Complete manifest XML as a string.
    """
    exclude_attr = f' exclude="{exclude}"' if exclude is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{project_name}" path="{project_path}">\n'
        f'    <linkfile src="{linkfile_src}" dest="{linkfile_dest}"{exclude_attr} />\n'
        "  </project>\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sync_linkfile_exclude_single(tmp_path: pathlib.Path) -> None:
    """Manifest with exclude="tests" links src/ and README.md but not tests/.

    Creates a content repo with pkg/ containing src/, tests/, and README.md.
    After sync, linked-pkg/ must contain symlinks to src/ and README.md,
    but must NOT contain a symlink for tests/.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-single", children=["src", "tests"])
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-single-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude="tests",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-single-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert linked_pkg.is_dir(), (
        f"Expected linked-pkg/ to exist as a directory at {linked_pkg} after sync, but it was not found."
    )
    assert os.path.islink(str(linked_pkg / "src")), (
        f"Expected a symlink for 'src' at {linked_pkg / 'src'} after exclude sync, but it was not found."
    )
    assert os.path.islink(str(linked_pkg / "README.md")), (
        f"Expected a symlink for 'README.md' at {linked_pkg / 'README.md'} after exclude sync, but it was not found."
    )
    assert not (linked_pkg / "tests").exists(), (
        f"Expected 'tests' to be absent from {linked_pkg} because it is in exclude='tests', but it was found."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_multiple(tmp_path: pathlib.Path) -> None:
    """exclude="tests,docs,__pycache__" excludes all three; others are linked.

    Creates a content repo with pkg/ containing src/, tests/, docs/,
    __pycache__/, and README.md. After sync, linked-pkg/ must have symlinks
    for src/ and README.md, but must NOT contain tests/, docs/, or __pycache__/.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    children = ["src", "tests", "docs", "__pycache__"]
    _create_content_repo_with_pkg_dir(repos_base, name="pkg-multi", children=children)
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-multi-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude="tests,docs,__pycache__",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-multi-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert linked_pkg.is_dir(), f"Expected linked-pkg/ directory at {linked_pkg} after sync."
    assert os.path.islink(str(linked_pkg / "src")), (
        f"Expected 'src' symlink in {linked_pkg} after exclude='tests,docs,__pycache__'."
    )
    assert os.path.islink(str(linked_pkg / "README.md")), f"Expected 'README.md' symlink in {linked_pkg}."
    for excluded_name in ("tests", "docs", "__pycache__"):
        assert not (linked_pkg / excluded_name).exists(), (
            f"Expected '{excluded_name}' to be absent from {linked_pkg} because it is excluded, but it was found."
        )


@pytest.mark.integration
def test_sync_linkfile_exclude_with_spaces(tmp_path: pathlib.Path) -> None:
    """exclude=" tests , docs " trims whitespace; tests and docs are excluded.

    Verifies that leading and trailing spaces around each name in the
    comma-separated exclude list are stripped before the exclude set is built.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-spaces", children=["src", "tests", "docs"])
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-spaces-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude=" tests , docs ",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-spaces-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert linked_pkg.is_dir(), f"Expected linked-pkg/ at {linked_pkg} after sync."
    assert os.path.islink(str(linked_pkg / "src")), "Expected 'src' symlink after whitespace-trimmed exclude."
    assert not (linked_pkg / "tests").exists(), (
        "Expected 'tests' excluded even with surrounding spaces in exclude attribute."
    )
    assert not (linked_pkg / "docs").exists(), (
        "Expected 'docs' excluded even with surrounding spaces in exclude attribute."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_nonexistent(tmp_path: pathlib.Path) -> None:
    """exclude="nonexistent" causes no error; all children are linked normally.

    When the excluded name does not match any child of the source directory,
    the exclude list is simply a no-op for that name and all children appear
    in the destination.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-noexcl", children=["src", "lib"])
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-noexcl-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude="nonexistent",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-noexcl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert linked_pkg.is_dir(), f"Expected linked-pkg/ at {linked_pkg} after sync."
    assert os.path.islink(str(linked_pkg / "src")), "Expected 'src' symlink when exclude name does not match any child."
    assert os.path.islink(str(linked_pkg / "lib")), "Expected 'lib' symlink when exclude name does not match any child."
    assert os.path.islink(str(linked_pkg / "README.md")), (
        "Expected 'README.md' symlink when exclude name does not match any child."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_empty_string(tmp_path: pathlib.Path) -> None:
    """exclude="" behaves as if no exclude attribute; creates a single directory symlink.

    An empty exclude string is treated the same as no exclude attribute,
    so a single symlink pointing to the entire directory is created.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-empty-excl", children=["src"])
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-empty-excl-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude="",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-empty-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert os.path.islink(str(linked_pkg)), (
        f"Expected linked-pkg to be a single directory symlink when exclude is empty string, "
        f"but {linked_pkg} is not a symlink."
    )


@pytest.mark.integration
def test_sync_linkfile_no_exclude_creates_dir_symlink(tmp_path: pathlib.Path) -> None:
    """No exclude attribute creates a single symlink to the entire source directory.

    When the linkfile element has no exclude attribute, the src must be linked
    as a single entity (one symlink pointing to the entire src directory).

    AC-FUNC-009
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-no-excl", children=["src", "tests"])
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-no-excl-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest="linked-pkg",
        exclude=None,
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-no-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    linked_pkg = workspace / "linked-pkg"
    assert os.path.islink(str(linked_pkg)), (
        f"Expected linked-pkg to be a single symlink to the pkg directory when no "
        f"exclude attribute is given, but {linked_pkg} is not a symlink."
    )
    assert (linked_pkg / "src").is_dir(), (
        f"Expected the 'src' child to be accessible through the directory symlink at {linked_pkg}."
    )
    assert (linked_pkg / "tests").is_dir(), (
        f"Expected the 'tests' child to be accessible through the directory symlink at {linked_pkg}."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_with_absolute_dest(tmp_path: pathlib.Path) -> None:
    """exclude="tests" with an absolute dest path creates per-child symlinks at the absolute path.

    When the linkfile dest is an absolute path and exclude is given, the
    per-child symlinks are created under the absolute destination directory.

    AC-FUNC-008
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(repos_base, name="pkg-abs", children=["src", "tests"])
    fetch_base_url = f"file://{repos_base}"

    abs_dest = str(tmp_path / "absolute-dest")

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="pkg-abs-bare",
        project_path="project-pkg",
        linkfile_src="pkg",
        linkfile_dest=abs_dest,
        exclude="tests",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-abs-excl", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    abs_dest_path = pathlib.Path(abs_dest)
    assert abs_dest_path.is_dir(), (
        f"Expected directory at absolute dest {abs_dest_path} after exclude sync, but it was not found."
    )
    assert os.path.islink(str(abs_dest_path / "src")), (
        f"Expected 'src' symlink at {abs_dest_path / 'src'} after exclude sync with absolute dest."
    )
    assert not (abs_dest_path / "tests").exists(), (
        f"Expected 'tests' to be absent from {abs_dest_path} because it is in exclude='tests'."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_always_skips_git_and_packages(tmp_path: pathlib.Path) -> None:
    """.git and .packages are always excluded from per-child linking, even without explicit exclude.

    The implementation always skips _LINKFILE_EXCLUDE_ALWAYS entries (.git,
    .packages) regardless of the user-supplied exclude list. This test confirms
    that behaviour by physically adding .git/ and .packages/ to the source
    directory via post-clone injection (since git will not track .git/
    directly, we add a file named .packages to simulate the scenario).

    AC-FUNC-006
    """
    from kanon_cli.repo.project import _LinkFile

    src_dir = tmp_path / "src-dir"
    src_dir.mkdir()
    top_dir = tmp_path / "top-dir"
    top_dir.mkdir()
    dest_dir = tmp_path / "dest-dir"

    (src_dir / "normal-file.txt").write_text("normal\n", encoding="utf-8")
    (src_dir / ".packages").write_text("packages-marker\n", encoding="utf-8")
    git_dir = src_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    link = _LinkFile(str(src_dir), ".", str(top_dir), str(dest_dir), exclude="something-else")
    link._Link()

    assert os.path.islink(str(dest_dir / "normal-file.txt")), (
        f"Expected 'normal-file.txt' symlink at {dest_dir / 'normal-file.txt'} after _LinkFile._Link()."
    )
    assert not (dest_dir / ".packages").exists(), (
        f"Expected '.packages' to be absent from {dest_dir}: it is in _LINKFILE_EXCLUDE_ALWAYS."
    )
    assert not (dest_dir / ".git").exists(), (
        f"Expected '.git' to be absent from {dest_dir}: it is in _LINKFILE_EXCLUDE_ALWAYS."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_always_skips_repo_prefix(tmp_path: pathlib.Path) -> None:
    """.repo* entries are always excluded from per-child linking.

    The implementation always skips entries whose names begin with '.repo'
    regardless of the user-supplied exclude list. This test uses _LinkFile
    directly with a synthesised source directory containing .repo, .repo-data,
    and a normal file.

    AC-FUNC-006
    """
    from kanon_cli.repo.project import _LinkFile

    src_dir = tmp_path / "src-repo-prefix"
    src_dir.mkdir()
    top_dir = tmp_path / "top-repo-prefix"
    top_dir.mkdir()
    dest_dir = tmp_path / "dest-repo-prefix"

    (src_dir / "plugin.py").write_text("# plugin\n", encoding="utf-8")
    repo_dir = src_dir / ".repo"
    repo_dir.mkdir()
    (repo_dir / "manifest.xml").write_text("<manifest />\n", encoding="utf-8")
    repo_data_dir = src_dir / ".repo-data"
    repo_data_dir.mkdir()
    (repo_data_dir / "config").write_text("data\n", encoding="utf-8")

    link = _LinkFile(str(src_dir), ".", str(top_dir), str(dest_dir), exclude="unrelated")
    link._Link()

    assert os.path.islink(str(dest_dir / "plugin.py")), (
        f"Expected 'plugin.py' symlink at {dest_dir / 'plugin.py'} after _LinkFile._Link()."
    )
    assert not (dest_dir / ".repo").exists(), (
        f"Expected '.repo' to be absent from {dest_dir}: names starting with '.repo' are always excluded."
    )
    assert not (dest_dir / ".repo-data").exists(), (
        f"Expected '.repo-data' to be absent from {dest_dir}: names starting with '.repo' are always excluded."
    )


@pytest.mark.integration
def test_sync_linkfile_exclude_with_glob_raises(tmp_path: pathlib.Path) -> None:
    """exclude combined with a glob src raises ManifestInvalidPathError.

    The implementation rejects the combination of a glob pattern in src and
    an exclude attribute because their semantics are incompatible.

    AC-FUNC-007
    """
    from kanon_cli.repo.project import _LinkFile

    src_dir = tmp_path / "glob-src"
    src_dir.mkdir()
    top_dir = tmp_path / "glob-top"
    top_dir.mkdir()

    (src_dir / "pkg-a").mkdir()
    (src_dir / "pkg-b").mkdir()

    glob_src = str(src_dir / "pk*")

    link = _LinkFile(str(src_dir), glob_src, str(top_dir), "dest", exclude="tests")
    with pytest.raises(ManifestInvalidPathError, match="exclude attribute cannot be combined with glob"):
        link._Link()


@pytest.mark.integration
def test_sync_linkfile_exclude_on_file_raises(tmp_path: pathlib.Path) -> None:
    """exclude on a file src (not directory) raises ManifestInvalidPathError.

    The exclude attribute is only meaningful when src points to a directory
    whose children will be individually linked. Pointing src at a file with
    exclude set is an error.

    AC-FUNC-007
    """
    from kanon_cli.repo.project import _LinkFile

    git_worktree = tmp_path / "worktree-file"
    git_worktree.mkdir()
    top_dir = tmp_path / "top-file"
    top_dir.mkdir()

    (git_worktree / "single.py").write_text("# single file\n", encoding="utf-8")

    link = _LinkFile(str(git_worktree), "single.py", str(top_dir), "dest-file", exclude="tests")
    with pytest.raises(ManifestInvalidPathError, match="exclude attribute requires src to be a directory"):
        link._Link()


@pytest.mark.integration
def test_full_lifecycle_install_with_exclude(tmp_path: pathlib.Path) -> None:
    """Full kanon install lifecycle with exclude="tests" on a marketplace linkfile.

    Sets up a content repo that represents a marketplace plugin, where the
    repository root contains a pkg/ directory with src/, tests/, and README.md.
    The manifest uses a linkfile element with exclude="tests" to link the
    marketplace content directory into the workspace. After init and sync,
    the linked directory contains the plugin content (src/, README.md) but
    does NOT contain the tests/ directory.

    AC-FUNC-010
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo_with_pkg_dir(
        repos_base,
        name="marketplace-plugin",
        children=["src", "tests", "lib"],
    )
    fetch_base_url = f"file://{repos_base}"

    manifest_xml = _build_manifest_xml(
        fetch_base_url=fetch_base_url,
        project_name="marketplace-plugin-bare",
        project_path="marketplace-project",
        linkfile_src="pkg",
        linkfile_dest="marketplace-dir",
        exclude="tests",
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-lifecycle", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Run the full init+sync lifecycle (mirrors what kanon install does for each source).
    _repo_init_and_sync(workspace, f"file://{manifest_bare}")

    marketplace_dir = workspace / "marketplace-dir"
    assert marketplace_dir.is_dir(), (
        f"Expected marketplace-dir/ to exist as a directory at {marketplace_dir} after install lifecycle, "
        f"but it was not found."
    )

    # Plugin content (src, lib, README.md) must be linked.
    assert os.path.islink(str(marketplace_dir / "src")), (
        f"Expected 'src' symlink inside {marketplace_dir} after lifecycle install with exclude='tests'."
    )
    assert os.path.islink(str(marketplace_dir / "lib")), (
        f"Expected 'lib' symlink inside {marketplace_dir} after lifecycle install with exclude='tests'."
    )
    assert os.path.islink(str(marketplace_dir / "README.md")), (
        f"Expected 'README.md' symlink inside {marketplace_dir} after lifecycle install with exclude='tests'."
    )

    # Tests folder must be absent.
    assert not (marketplace_dir / "tests").exists(), (
        f"Expected 'tests' to be absent from {marketplace_dir} because exclude='tests', but it was found."
    )
