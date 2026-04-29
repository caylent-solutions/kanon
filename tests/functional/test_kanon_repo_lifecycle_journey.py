"""Comprehensive kanon repo subcommand lifecycle journey tests.

Each test creates real bare git repositories in tmp_path, runs kanon repo
subcommands via subprocess, and asserts on output/filesystem state. No
mocking -- these tests exercise the full CLI stack against real git operations.

Tests in this module are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Journey Test User"
_GIT_USER_EMAIL = "journey-test@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from journey content repo"
_LINK_SOURCE_FILE = "link-source.txt"
_LINK_SOURCE_TEXT = "link source content"
_COPY_SOURCE_FILE = "copy-source.txt"
_COPY_SOURCE_TEXT = "copy source content"
_TAG_VERSION = "1.0.5"
_TAG_CONSTRAINT = "refs/tags/~=1.0.0"

# ---------------------------------------------------------------------------
# Low-level git helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Shared git repo creation helpers
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
    """Clone work_dir into bare_dir and return bare_dir resolved.

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

    return _clone_as_bare(work_dir, base / "content-bare.git")


def _create_bare_content_repo_with_tag(base: pathlib.Path, tag: str) -> pathlib.Path:
    """Create a bare git repo with an annotated tag on the initial commit.

    Args:
        base: Parent directory under which repos are created.
        tag: The annotated tag name to create (e.g., "1.2.3").

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "tagged-content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Tagged commit"], cwd=work_dir)
    _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "tagged-content-bare.git")


def _create_bare_content_repo_with_linkfile(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing a file that will be used as a linkfile source.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "link-content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    link_src = work_dir / _LINK_SOURCE_FILE
    link_src.write_text(_LINK_SOURCE_TEXT, encoding="utf-8")
    _git(["add", _LINK_SOURCE_FILE], cwd=work_dir)
    _git(["commit", "-m", "Add link source file"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "link-content-bare.git")


def _create_bare_content_repo_with_copyfile(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing a file that will be used as a copyfile source.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "copy-content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    copy_src = work_dir / _COPY_SOURCE_FILE
    copy_src.write_text(_COPY_SOURCE_TEXT, encoding="utf-8")
    _git(["add", _COPY_SOURCE_FILE], cwd=work_dir)
    _git(["commit", "-m", "Add copy source file"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "copy-content-bare.git")


def _write_manifest_xml(
    work_dir: pathlib.Path,
    fetch_base: str,
    projects: list[dict],
    default_revision: str = "main",
) -> None:
    """Write a manifest XML file to work_dir/default.xml.

    Each project dict must have 'name' and 'path' keys. Optional keys:
    - 'revision': overrides the default revision for this project.
    - 'copyfile_src': triggers a <copyfile src=... dest=...> child element.
    - 'copyfile_dest': destination for copyfile (required if copyfile_src set).
    - 'linkfile_src': triggers a <linkfile src=... dest=...> child element.
    - 'linkfile_dest': destination for linkfile (required if linkfile_src set).

    Args:
        work_dir: Directory in which to write the manifest.
        fetch_base: Value for the remote fetch attribute.
        projects: List of project descriptor dicts.
        default_revision: Default revision for the <default> element.
    """
    project_elements = []
    for proj in projects:
        revision_attr = f' revision="{proj["revision"]}"' if "revision" in proj else ""
        project_open = f'  <project name="{proj["name"]}" path="{proj["path"]}"{revision_attr}>'
        children = []
        if "copyfile_src" in proj:
            children.append(f'    <copyfile src="{proj["copyfile_src"]}" dest="{proj["copyfile_dest"]}" />')
        if "linkfile_src" in proj:
            children.append(f'    <linkfile src="{proj["linkfile_src"]}" dest="{proj["linkfile_dest"]}" />')
        if children:
            project_elements.append(project_open)
            project_elements.extend(children)
            project_elements.append("  </project>")
        else:
            project_elements.append(f'  <project name="{proj["name"]}" path="{proj["path"]}"{revision_attr} />')

    projects_xml = "\n".join(project_elements)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        f'  <default revision="{default_revision}" remote="local" />\n'
        f"{projects_xml}\n"
        "</manifest>\n"
    )
    manifest_path = work_dir / _MANIFEST_FILENAME
    manifest_path.write_text(manifest_xml, encoding="utf-8")


def _create_manifest_repo(
    base: pathlib.Path,
    fetch_base: str,
    projects: list[dict],
    default_revision: str = "main",
    subdir_name: str = "manifest",
) -> pathlib.Path:
    """Create a bare manifest git repo with the given projects in its manifest.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: Value for the remote fetch attribute (e.g., a file:// parent URL).
        projects: List of project descriptors passed to _write_manifest_xml.
        default_revision: Default revision for the <default> element.
        subdir_name: Unique subdirectory prefix to avoid name collisions.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / f"{subdir_name}-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    _write_manifest_xml(work_dir, fetch_base, projects, default_revision=default_revision)
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / f"{subdir_name}-bare.git")


def _create_minimal_repo_dir(base: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory sufficient for the embedded repo tool.

    The .repo/repo/ git repository must have at least one tagged commit so
    that the embedded tool's version subcommand succeeds. The .repo/manifests/
    directory must contain a valid manifest XML file.

    Args:
        base: The directory in which to create .repo/.

    Returns:
        The path to the created .repo directory.
    """
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    (manifests_dir / _MANIFEST_FILENAME).write_text(manifest_content, encoding="utf-8")
    (repo_dot_dir / "manifest.xml").symlink_to(manifests_dir / _MANIFEST_FILENAME)

    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir()
    _init_git_work_dir(repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    return repo_dot_dir


def _init_checkout(
    tmp_path: pathlib.Path,
    manifest_bare: pathlib.Path,
    subdir: str = "checkout",
) -> tuple[pathlib.Path, pathlib.Path]:
    """Run kanon repo init and return (checkout_dir, repo_dir).

    Args:
        tmp_path: pytest-provided temporary directory root.
        manifest_bare: Absolute path to the bare manifest repository.
        subdir: Name of the checkout subdirectory inside tmp_path.

    Returns:
        Tuple of (checkout_dir, repo_dir) after a successful init.

    Raises:
        AssertionError: If kanon repo init fails.
    """
    checkout_dir = tmp_path / subdir
    checkout_dir.mkdir()
    repo_dir = checkout_dir / ".repo"
    manifest_url = f"file://{manifest_bare}"

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
        f"Prerequisite kanon repo init failed with exit {result.returncode}.\n"
        f"  stdout: {result.stdout!r}\n"
        f"  stderr: {result.stderr!r}"
    )
    return checkout_dir, repo_dir


def _sync_checkout(checkout_dir: pathlib.Path, repo_dir: pathlib.Path) -> subprocess.CompletedProcess:
    """Run kanon repo sync in checkout_dir and return the completed process.

    Args:
        checkout_dir: The checkout root directory.
        repo_dir: The .repo directory path.

    Returns:
        The CompletedProcess from the sync invocation.
    """
    return _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        "--jobs=1",
        cwd=checkout_dir,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: test_repo_init_sync_lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitSyncLifecycle:
    """AC-TEST-001: kanon repo init -> sync -> verify projects cloned with correct files."""

    def test_repo_init_sync_lifecycle(self, tmp_path: pathlib.Path) -> None:
        """Full init/sync lifecycle creates the project directory with committed files.

        Steps:
        1. Create a bare content git repo and bare manifest git repo.
        2. Run kanon repo init with file:// manifest URL.
        3. Run kanon repo sync.
        4. Assert the project directory and committed README exist on disk.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "my-project"}],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, (
            f"kanon repo sync failed with exit {sync_result.returncode}.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

        project_dir = checkout_dir / "my-project"
        assert project_dir.is_dir(), f"Project directory {project_dir!r} was not created after kanon repo sync."

        readme = project_dir / _CONTENT_FILE_NAME
        assert readme.is_file(), f"Expected {readme!r} to exist after sync."
        content = readme.read_text(encoding="utf-8").strip()
        assert content == _CONTENT_FILE_TEXT, f"Content of {readme!r} was {content!r}, expected {_CONTENT_FILE_TEXT!r}."


# ---------------------------------------------------------------------------
# AC-TEST-002: test_repo_init_envsubst_sync_lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitEnvsubstSyncLifecycle:
    """AC-TEST-002: init -> set env var -> envsubst -> sync -> verify substitution worked."""

    def test_repo_init_envsubst_sync_lifecycle(self, tmp_path: pathlib.Path) -> None:
        """Envsubst expands ${KANON_JOURNEY_FETCH} in the manifest before sync.

        Steps:
        1. Create bare content repo and bare manifest repo with ${KANON_JOURNEY_FETCH}
           placeholder in the remote fetch attribute.
        2. Run kanon repo init.
        3. Run kanon repo envsubst with KANON_JOURNEY_FETCH set to the real URL.
        4. Verify placeholder is replaced in the on-disk manifest.
        5. Run kanon repo sync.
        6. Assert the project directory exists.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        real_fetch_base = f"file://{bare_content.parent}"

        # Manifest with placeholder
        envsubst_work_dir = repos_dir / "envsubst-manifest-work"
        envsubst_work_dir.mkdir()
        _init_git_work_dir(envsubst_work_dir)
        manifest_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="local" fetch="${KANON_JOURNEY_FETCH}" />\n'
            '  <default revision="main" remote="local" />\n'
            '  <project name="content-bare" path="my-project" />\n'
            "</manifest>\n"
        )
        (envsubst_work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
        _git(["add", _MANIFEST_FILENAME], cwd=envsubst_work_dir)
        _git(["commit", "-m", "Add envsubst manifest"], cwd=envsubst_work_dir)
        manifest_bare = _clone_as_bare(envsubst_work_dir, repos_dir / "envsubst-manifest-bare.git")

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        envsubst_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "envsubst",
            cwd=checkout_dir,
            extra_env={"KANON_JOURNEY_FETCH": real_fetch_base},
        )
        assert envsubst_result.returncode == 0, (
            f"kanon repo envsubst failed with exit {envsubst_result.returncode}.\n"
            f"  stdout: {envsubst_result.stdout!r}\n"
            f"  stderr: {envsubst_result.stderr!r}"
        )

        manifest_on_disk = repo_dir / "manifests" / _MANIFEST_FILENAME
        manifest_text = manifest_on_disk.read_text(encoding="utf-8")
        assert "${KANON_JOURNEY_FETCH}" not in manifest_text, (
            f"Placeholder was not substituted.\n  manifest: {manifest_text!r}"
        )
        assert real_fetch_base in manifest_text, (
            f"Expected fetch URL {real_fetch_base!r} in manifest after envsubst.\n  manifest: {manifest_text!r}"
        )

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, (
            f"kanon repo sync after envsubst failed with exit {sync_result.returncode}.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

        project_dir = checkout_dir / "my-project"
        assert project_dir.is_dir(), f"Project directory {project_dir!r} was not created after envsubst + sync."


# ---------------------------------------------------------------------------
# AC-TEST-003: test_repo_init_sync_status
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitSyncStatus:
    """AC-TEST-003: after sync, kanon repo status verifies project names in output."""

    def test_repo_init_sync_status(self, tmp_path: pathlib.Path) -> None:
        """After sync, kanon repo status exits 0 and outputs the project path.

        Steps:
        1. Create bare repos and run init + sync.
        2. Run kanon repo status.
        3. Assert exit code is 0 and project path appears in combined output.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "status-project"}],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, f"Prerequisite sync failed: {sync_result.stderr!r}"

        # Modify a tracked file in the project so that status reports it as
        # dirty -- this causes the project header line ("project status-project/")
        # to appear in the output, which is what "verify project names in output"
        # requires.
        tracked_file = checkout_dir / "status-project" / _CONTENT_FILE_NAME
        original_content = tracked_file.read_text(encoding="utf-8")
        tracked_file.write_text(original_content + "\nmodified for status test\n", encoding="utf-8")

        status_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "status",
            cwd=checkout_dir,
        )
        assert status_result.returncode == 0, (
            f"kanon repo status exited {status_result.returncode}, expected 0.\n"
            f"  stdout: {status_result.stdout!r}\n"
            f"  stderr: {status_result.stderr!r}"
        )
        combined = status_result.stdout + status_result.stderr
        assert "status-project" in combined, (
            f"Project path 'status-project' not found in status output.\n"
            f"  stdout: {status_result.stdout!r}\n"
            f"  stderr: {status_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: test_repo_init_sync_list
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitSyncList:
    """AC-TEST-004: after sync, kanon repo list verifies project names listed."""

    def test_repo_init_sync_list(self, tmp_path: pathlib.Path) -> None:
        """After sync, kanon repo list exits 0 and lists the project path.

        Steps:
        1. Create bare repos and run init + sync.
        2. Run kanon repo list.
        3. Assert exit code is 0 and project path appears in combined output.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "list-project"}],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, f"Prerequisite sync failed: {sync_result.stderr!r}"

        list_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert list_result.returncode == 0, (
            f"kanon repo list exited {list_result.returncode}, expected 0.\n"
            f"  stdout: {list_result.stdout!r}\n"
            f"  stderr: {list_result.stderr!r}"
        )
        combined = list_result.stdout + list_result.stderr
        assert "list-project" in combined, (
            f"Project path 'list-project' not found in list output.\n"
            f"  stdout: {list_result.stdout!r}\n"
            f"  stderr: {list_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-005: test_repo_init_sync_forall
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitSyncForall:
    """AC-TEST-005: after sync, kanon repo forall -c 'echo hello' produces output from each project."""

    def test_repo_init_sync_forall(self, tmp_path: pathlib.Path) -> None:
        """After sync, forall -c 'echo hello' exits 0 and emits output from the project.

        Steps:
        1. Create bare repos and run init + sync.
        2. Run kanon repo forall -c 'echo hello'.
        3. Assert exit code 0 and 'hello' appears in combined output.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "forall-project"}],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, f"Prerequisite sync failed: {sync_result.stderr!r}"

        forall_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "forall",
            "-c",
            "echo hello",
            cwd=checkout_dir,
        )
        assert forall_result.returncode == 0, (
            f"kanon repo forall exited {forall_result.returncode}, expected 0.\n"
            f"  stdout: {forall_result.stdout!r}\n"
            f"  stderr: {forall_result.stderr!r}"
        )
        combined = forall_result.stdout + forall_result.stderr
        assert "hello" in combined, (
            f"Expected 'hello' in forall output but got:\n"
            f"  stdout: {forall_result.stdout!r}\n"
            f"  stderr: {forall_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-006: test_repo_sync_with_linkfile
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncWithLinkfile:
    """AC-TEST-006: manifest with <linkfile> elements -> sync -> verify symlinks exist."""

    def test_repo_sync_with_linkfile(self, tmp_path: pathlib.Path) -> None:
        """After sync a manifest with <linkfile>, the symlink exists at the dest path.

        Steps:
        1. Create a bare content repo containing _LINK_SOURCE_FILE.
        2. Create a manifest with <linkfile src=... dest=...>.
        3. Run init + sync.
        4. Assert a symlink exists at the dest path in the checkout root.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo_with_linkfile(repos_dir)
        fetch_base = f"file://{bare_content.parent}"

        link_dest = "linked-file.txt"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [
                {
                    "name": "link-content-bare",
                    "path": "link-project",
                    "linkfile_src": _LINK_SOURCE_FILE,
                    "linkfile_dest": link_dest,
                }
            ],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, (
            f"kanon repo sync failed with exit {sync_result.returncode}.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

        link_path = checkout_dir / link_dest
        assert link_path.exists() or link_path.is_symlink(), (
            f"Expected symlink or file at {link_path!r} after sync with <linkfile>."
        )


# ---------------------------------------------------------------------------
# AC-TEST-007: test_repo_sync_with_copyfile
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncWithCopyfile:
    """AC-TEST-007: manifest with <copyfile> elements -> sync -> verify files copied."""

    def test_repo_sync_with_copyfile(self, tmp_path: pathlib.Path) -> None:
        """After sync a manifest with <copyfile>, the file exists at the dest path.

        Steps:
        1. Create a bare content repo containing _COPY_SOURCE_FILE.
        2. Create a manifest with <copyfile src=... dest=...>.
        3. Run init + sync.
        4. Assert the dest file exists in the checkout root with the expected content.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo_with_copyfile(repos_dir)
        fetch_base = f"file://{bare_content.parent}"

        copy_dest = "copied-file.txt"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [
                {
                    "name": "copy-content-bare",
                    "path": "copy-project",
                    "copyfile_src": _COPY_SOURCE_FILE,
                    "copyfile_dest": copy_dest,
                }
            ],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, (
            f"kanon repo sync failed with exit {sync_result.returncode}.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

        dest_path = checkout_dir / copy_dest
        assert dest_path.is_file(), f"Expected copied file at {dest_path!r} after sync with <copyfile>."
        content = dest_path.read_text(encoding="utf-8").strip()
        assert content == _COPY_SOURCE_TEXT, f"Copied file content was {content!r}, expected {_COPY_SOURCE_TEXT!r}."


# ---------------------------------------------------------------------------
# AC-TEST-008: test_repo_sync_with_version_constraint
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncWithVersionConstraint:
    """AC-TEST-008: manifest with revision='refs/tags/~=1.0.0' -> sync -> correct tag checked out."""

    def test_repo_sync_with_version_constraint(self, tmp_path: pathlib.Path) -> None:
        """Sync with a PEP 440 version constraint resolves and checks out the correct tag.

        Steps:
        1. Create a bare content repo with an annotated tag _TAG_VERSION.
        2. Create a manifest with revision=_TAG_CONSTRAINT for that project.
        3. Run init + sync.
        4. Assert sync exits 0 (the constraint resolved successfully).
        5. Assert the project directory exists on disk.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo_with_tag(repos_dir, _TAG_VERSION)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [
                {
                    "name": "tagged-content-bare",
                    "path": "versioned-project",
                    "revision": _TAG_CONSTRAINT,
                }
            ],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        sync_result = _sync_checkout(checkout_dir, repo_dir)
        assert sync_result.returncode == 0, (
            f"kanon repo sync with version constraint failed with exit {sync_result.returncode}.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

        project_dir = checkout_dir / "versioned-project"
        assert project_dir.is_dir(), (
            f"Project directory {project_dir!r} was not created after sync with version constraint."
        )


# ---------------------------------------------------------------------------
# AC-TEST-009: test_repo_sync_idempotent
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncIdempotent:
    """AC-TEST-009: sync twice -> second sync succeeds with no errors."""

    def test_repo_sync_idempotent(self, tmp_path: pathlib.Path) -> None:
        """Running sync twice produces identical outcomes without errors.

        Steps:
        1. Create bare repos, init, and first sync.
        2. Run sync again.
        3. Assert the second sync exits 0.
        4. Assert the project directory still exists after the second sync.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "idempotent-project"}],
        )

        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare)

        first_sync = _sync_checkout(checkout_dir, repo_dir)
        assert first_sync.returncode == 0, f"First sync failed: {first_sync.stderr!r}"

        second_sync = _sync_checkout(checkout_dir, repo_dir)
        assert second_sync.returncode == 0, (
            f"Second sync (idempotency check) failed with exit {second_sync.returncode}.\n"
            f"  stdout: {second_sync.stdout!r}\n"
            f"  stderr: {second_sync.stderr!r}"
        )

        project_dir = checkout_dir / "idempotent-project"
        assert project_dir.is_dir(), f"Project directory {project_dir!r} missing after second sync."


# ---------------------------------------------------------------------------
# AC-TEST-010: test_repo_reinit_different_manifest
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoReinitDifferentManifest:
    """AC-TEST-010: init with manifest A, then init with manifest B -> second init works."""

    def test_repo_reinit_different_manifest(self, tmp_path: pathlib.Path) -> None:
        """Re-running init with a different manifest URL succeeds without error.

        Steps:
        1. Create two independent bare content repos and their manifests.
        2. Run kanon repo init with manifest A.
        3. Run kanon repo init with manifest B in the same checkout directory.
        4. Assert the second init exits 0.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        # Manifest A: references content-bare with path project-a
        bare_content_a = _create_bare_content_repo(repos_dir)
        fetch_base_a = f"file://{bare_content_a.parent}"
        manifest_bare_a = _create_manifest_repo(
            repos_dir,
            fetch_base_a,
            [{"name": "content-bare", "path": "project-a"}],
            subdir_name="manifest-a",
        )

        # Manifest B: references a second content repo with path project-b
        repos_dir_b = tmp_path / "repos-b"
        repos_dir_b.mkdir()
        bare_content_b_work = repos_dir_b / "content-b-work"
        bare_content_b_work.mkdir()
        _init_git_work_dir(bare_content_b_work)
        (bare_content_b_work / "fileB.txt").write_text("content b", encoding="utf-8")
        _git(["add", "fileB.txt"], cwd=bare_content_b_work)
        _git(["commit", "-m", "Repo B initial commit"], cwd=bare_content_b_work)
        bare_content_b = _clone_as_bare(bare_content_b_work, repos_dir_b / "content-b-bare.git")

        fetch_base_b = f"file://{bare_content_b.parent}"
        manifest_bare_b = _create_manifest_repo(
            repos_dir_b,
            fetch_base_b,
            [{"name": "content-b-bare", "path": "project-b"}],
            subdir_name="manifest-b",
        )

        # First init with manifest A
        checkout_dir, repo_dir = _init_checkout(tmp_path, manifest_bare_a)

        # Second init with manifest B in the same checkout directory
        manifest_url_b = f"file://{manifest_bare_b}"
        reinit_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url_b,
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert reinit_result.returncode == 0, (
            f"Re-init with manifest B failed with exit {reinit_result.returncode}.\n"
            f"  stdout: {reinit_result.stdout!r}\n"
            f"  stderr: {reinit_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-011: test_repo_selfupdate_embedded_message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateEmbeddedMessage:
    """AC-TEST-011: kanon repo selfupdate output contains the embedded-mode message."""

    def test_repo_selfupdate_embedded_message(self, tmp_path: pathlib.Path) -> None:
        """kanon repo selfupdate emits the 'not available' message and exits 1.

        The selfupdate subcommand in embedded mode prints a message to stderr
        that tells users to use 'pipx upgrade kanon-cli' instead of running
        selfupdate. This test verifies:
        - The command exits with code 1 (updated per E2-F2-S2-T2).
        - The combined output contains 'not available'.
        - The combined output contains 'pipx upgrade kanon-cli'.

        A minimal .repo directory is required for kanon repo to locate the
        embedded repo tool. This test creates one inline.
        """
        from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE

        repo_dot_dir = _create_minimal_repo_dir(tmp_path)

        selfupdate_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "selfupdate",
            cwd=tmp_path,
        )

        assert selfupdate_result.returncode == 1, (
            f"kanon repo selfupdate exited {selfupdate_result.returncode}, expected 1.\n"
            f"  stdout: {selfupdate_result.stdout!r}\n"
            f"  stderr: {selfupdate_result.stderr!r}"
        )

        combined = selfupdate_result.stdout + selfupdate_result.stderr
        assert "not available" in combined, (
            f"Expected 'not available' in selfupdate output.\n"
            f"  stdout: {selfupdate_result.stdout!r}\n"
            f"  stderr: {selfupdate_result.stderr!r}"
        )
        assert "pipx upgrade kanon-cli" in combined, (
            f"Expected 'pipx upgrade kanon-cli' in selfupdate output.\n"
            f"  stdout: {selfupdate_result.stdout!r}\n"
            f"  stderr: {selfupdate_result.stderr!r}"
        )

        # Verify against the authoritative constant
        assert SELFUPDATE_EMBEDDED_MESSAGE in combined, (
            f"Expected the full SELFUPDATE_EMBEDDED_MESSAGE constant {SELFUPDATE_EMBEDDED_MESSAGE!r} "
            f"to appear in output, but got:\n"
            f"  stdout: {selfupdate_result.stdout!r}\n"
            f"  stderr: {selfupdate_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-012: test_repo_invalid_subcommand
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInvalidSubcommand:
    """AC-TEST-012: kanon repo nonexistent -> non-zero exit."""

    def test_repo_invalid_subcommand(self, tmp_path: pathlib.Path) -> None:
        """An unrecognised repo subcommand exits with a non-zero exit code.

        Steps:
        1. Create a minimal .repo directory for the embedded tool.
        2. Run kanon repo nonexistent-subcommand-xyz.
        3. Assert the exit code is non-zero.
        """
        repo_dot_dir = _create_minimal_repo_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "nonexistent-subcommand-xyz",
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"kanon repo nonexistent-subcommand-xyz exited {result.returncode}, expected non-zero.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
