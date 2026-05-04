"""Integration tests: full init -> envsubst -> sync pipeline.

These tests verify the complete kanon_cli.repo pipeline end-to-end using
file:// URLs for all git remotes so no network access is required.

Coverage:
- Full pipeline (single project manifest)
- Full pipeline (multi-project manifest)
- Variable substitution in the pipeline
- Pipeline failure at each stage (init, envsubst, sync)

All tests are marked @pytest.mark.integration.
"""

import pathlib
import subprocess

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo import RepoCommandError
from kanon_cli.repo.main import run_from_args


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Pipeline Test User"
_GIT_USER_EMAIL = "pipeline-test@example.com"
_MANIFEST_FILENAME = "default.xml"


# ---------------------------------------------------------------------------
# Shared helpers
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


def _create_content_repo(base: pathlib.Path, name: str = "content") -> pathlib.Path:
    """Create a named bare content repo with one committed file.

    Args:
        base: Parent directory for all repos created by this helper.
        name: Logical name prefix used to distinguish multiple repos.

    Returns:
        Absolute path to the bare repository directory.
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
    return bare_dir


def _create_single_project_manifest_repo(
    base: pathlib.Path,
    fetch_base_url: str,
    project_name: str = "content-bare",
    project_path: str = "project-a",
) -> pathlib.Path:
    """Create a bare manifest repo referencing a single project.

    Args:
        base: Parent directory for all repos.
        fetch_base_url: file:// URL of the directory containing bare project repos.
        project_name: Name of the project in the manifest (basename of bare repo).
        project_path: Path attribute for the project in the workspace.

    Returns:
        Absolute path to the bare manifest repository.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{project_name}" path="{project_path}" />\n'
        "</manifest>\n"
    )
    return _write_manifest_repo(base, "manifest-single", manifest_xml)


def _create_multi_project_manifest_repo(
    base: pathlib.Path,
    fetch_base_url: str,
) -> pathlib.Path:
    """Create a bare manifest repo referencing two projects.

    Args:
        base: Parent directory for all repos.
        fetch_base_url: file:// URL of the directory containing bare project repos.

    Returns:
        Absolute path to the bare manifest repository.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="alpha-bare" path="project-alpha" />\n'
        '  <project name="beta-bare" path="project-beta" />\n'
        "</manifest>\n"
    )
    return _write_manifest_repo(base, "manifest-multi", manifest_xml)


def _create_envsubst_manifest_repo(
    base: pathlib.Path,
    project_name: str = "content-bare",
    project_path: str = "project-envsubst",
    fetch_var: str = "KANON_PIPELINE_FETCH_URL",
) -> pathlib.Path:
    """Create a bare manifest repo with a ${VAR} placeholder in the remote fetch.

    The placeholder is left unresolved; a call to repo_envsubst() must inject
    the actual fetch URL before repo sync can succeed.

    Args:
        base: Parent directory for all repos.
        project_name: Name of the project in the manifest.
        project_path: Path attribute for the project in the workspace.
        fetch_var: Name of the environment variable to use as a placeholder.

    Returns:
        Absolute path to the bare manifest repository.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="${{{fetch_var}}}" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{project_name}" path="{project_path}" />\n'
        "</manifest>\n"
    )
    return _write_manifest_repo(base, "manifest-envsubst", manifest_xml)


def _write_manifest_repo(base: pathlib.Path, name: str, manifest_xml: str) -> pathlib.Path:
    """Write manifest_xml into a fresh bare git repo named `name`.

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


def _repo_init(workspace: pathlib.Path, manifest_url: str) -> None:
    """Run repo init in workspace using manifest_url.

    Args:
        workspace: Directory in which to run repo init. The .repo/ directory
            will be created here.
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_pipeline_single_project(tmp_path: pathlib.Path) -> None:
    """Full init -> envsubst -> sync pipeline succeeds for a single-project manifest.

    Creates a local file:// manifest repo referencing one content repo. Runs
    repo_init(), repo_envsubst() (no substitutions needed because the manifest
    has no placeholders), and repo_sync(). Verifies the project directory and
    its README are present after sync.

    AC-FUNC-003, AC-FUNC-004
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="content")
    fetch_base_url = f"file://{repos_base}"

    manifest_bare = _create_single_project_manifest_repo(
        repos_base,
        fetch_base_url,
        project_name="content-bare",
        project_path="project-a",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_url = f"file://{manifest_bare}"

    # Stage 1: init
    _repo_init(workspace, manifest_url)
    repo_dot_path = workspace / ".repo"
    assert repo_dot_path.is_dir(), f"Expected .repo/ directory at {repo_dot_path} after init, but it was not created."

    # Stage 2: envsubst (manifest has no placeholders; should be a no-op)
    repo_pkg.repo_envsubst(str(workspace), {})

    # Stage 3: sync
    repo_pkg.repo_sync(str(workspace))

    project_dir = workspace / "project-a"
    assert project_dir.is_dir(), (
        f"Expected project directory {project_dir} after sync, "
        f"but it was not created. Workspace: {list(workspace.iterdir())!r}"
    )
    readme = project_dir / "README.md"
    assert readme.is_file(), (
        f"Expected {readme} in cloned project but it was not found. Project contents: {list(project_dir.iterdir())!r}"
    )


@pytest.mark.integration
def test_full_pipeline_multi_project(tmp_path: pathlib.Path) -> None:
    """Full init -> envsubst -> sync pipeline succeeds for a multi-project manifest.

    Creates two content repos (alpha and beta) and a manifest that references
    both. Runs the full pipeline and verifies both project directories and their
    README files exist after sync.

    AC-FUNC-003, AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="alpha")
    _create_content_repo(repos_base, name="beta")
    fetch_base_url = f"file://{repos_base}"

    manifest_bare = _create_multi_project_manifest_repo(repos_base, fetch_base_url)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_url = f"file://{manifest_bare}"

    # Stage 1: init
    _repo_init(workspace, manifest_url)
    assert (workspace / ".repo").is_dir(), "Expected .repo/ to exist after init for multi-project manifest."

    # Stage 2: envsubst (no-op for static manifest)
    repo_pkg.repo_envsubst(str(workspace), {})

    # Stage 3: sync
    repo_pkg.repo_sync(str(workspace))

    for project_path, content_name in [("project-alpha", "alpha"), ("project-beta", "beta")]:
        project_dir = workspace / project_path
        assert project_dir.is_dir(), (
            f"Expected project directory {project_dir} after sync, "
            f"but it was not created. Workspace: {list(workspace.iterdir())!r}"
        )
        readme = project_dir / "README.md"
        assert readme.is_file(), f"Expected {readme} in cloned project, but it was not found."
        content = readme.read_text(encoding="utf-8")
        assert content_name in content, f"Expected {content_name!r} in README content but got: {content!r}"


@pytest.mark.integration
def test_pipeline_with_variable_substitution(tmp_path: pathlib.Path) -> None:
    """Pipeline succeeds when envsubst resolves a ${VAR} placeholder before sync.

    The manifest repo is created with a ${KANON_PIPELINE_FETCH_URL} placeholder
    in the remote fetch attribute. After init, repo_envsubst() injects the real
    fetch URL. Then repo_sync() clones the project. Verifies the project
    directory exists after sync.

    AC-FUNC-003, AC-FUNC-007
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="content")
    fetch_base_url = f"file://{repos_base}"

    manifest_bare = _create_envsubst_manifest_repo(
        repos_base,
        project_name="content-bare",
        project_path="project-envsubst",
        fetch_var="KANON_PIPELINE_FETCH_URL",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_url = f"file://{manifest_bare}"

    # Stage 1: init
    _repo_init(workspace, manifest_url)
    assert (workspace / ".repo").is_dir(), "Expected .repo/ to exist after init."

    # Stage 2: envsubst -- inject the actual fetch URL
    repo_pkg.repo_envsubst(str(workspace), {"KANON_PIPELINE_FETCH_URL": fetch_base_url})

    # Verify the manifest was updated by envsubst
    manifests_dir = workspace / ".repo" / "manifests"
    manifest_files = list(manifests_dir.glob("*.xml"))
    assert manifest_files, (
        f"Expected at least one XML manifest file under {manifests_dir} after envsubst, "
        f"but none were found. Directory contents: {list(manifests_dir.iterdir())!r}"
    )
    processed_xml = manifest_files[0].read_text(encoding="utf-8")
    assert "${KANON_PIPELINE_FETCH_URL}" not in processed_xml, (
        f"Expected the placeholder to be resolved in the manifest after envsubst, "
        f"but it is still present. Manifest content: {processed_xml!r}"
    )
    assert fetch_base_url in processed_xml, (
        f"Expected {fetch_base_url!r} to appear in the manifest after envsubst, "
        f"but it was not found. Manifest content: {processed_xml!r}"
    )

    # Stage 3: sync
    repo_pkg.repo_sync(str(workspace))

    project_dir = workspace / "project-envsubst"
    assert project_dir.is_dir(), (
        f"Expected project directory {project_dir} after sync, "
        f"but it was not created. Workspace: {list(workspace.iterdir())!r}"
    )


@pytest.mark.integration
def test_pipeline_init_failure_bad_url(tmp_path: pathlib.Path) -> None:
    """Pipeline fails fast at the init stage when the manifest URL does not exist.

    A nonexistent file:// URL is given to _repo_init(). run_from_args() must
    surface the failure as RepoCommandError with a non-zero exit code. The
    workspace must not contain an initialized manifest checkout
    (.repo/manifests/) after the failed init.

    AC-FUNC-006
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    bad_manifest_url = f"file://{tmp_path}/does-not-exist.git"

    with pytest.raises(RepoCommandError) as exc_info:
        _repo_init(workspace, bad_manifest_url)

    assert exc_info.value.exit_code not in (0, None), (
        f"RepoCommandError from a bad manifest URL must carry a non-zero exit_code, got {exc_info.value.exit_code!r}"
    )
    manifests_dir = workspace / ".repo" / "manifests"
    assert not manifests_dir.is_dir(), (
        f"repo init must not leave a populated .repo/manifests/ checkout on failure, but {manifests_dir} exists. "
        f"Raised: {exc_info.value!r}"
    )


@pytest.mark.integration
def test_pipeline_envsubst_failure_no_repo_dir(tmp_path: pathlib.Path) -> None:
    """Pipeline fails fast at the envsubst stage when .repo/ does not exist.

    Calls repo_envsubst() on a workspace directory where repo init has not been
    run. Verifies that RepoCommandError is raised immediately (fail-fast), not
    silently ignored.

    AC-FUNC-006
    """
    workspace = tmp_path / "workspace-no-init"
    workspace.mkdir()

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_envsubst(str(workspace), {"SOME_VAR": "value"})

    assert exc_info.value.exit_code != 0, (
        f"Expected a non-zero exit_code on envsubst failure, but got: {exc_info.value.exit_code!r}"
    )


@pytest.mark.integration
def test_pipeline_sync_failure_no_repo_dir(tmp_path: pathlib.Path) -> None:
    """Pipeline fails fast at the sync stage when .repo/ does not exist.

    Calls repo_sync() on a workspace directory where repo init has not been
    run. Verifies that RepoCommandError is raised immediately (fail-fast), not
    silently ignored.

    AC-FUNC-006
    """
    workspace = tmp_path / "workspace-no-init"
    workspace.mkdir()

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_sync(str(workspace))

    assert exc_info.value.exit_code != 0, (
        f"Expected a non-zero exit_code on sync failure, but got: {exc_info.value.exit_code!r}"
    )


@pytest.mark.integration
def test_pipeline_init_creates_repo_directory(tmp_path: pathlib.Path) -> None:
    """repo_init() creates the .repo/ directory in the workspace.

    Verifies that running the init stage of the pipeline produces the .repo/
    subdirectory and that it contains the manifests/ subdirectory populated by
    the manifest clone.

    AC-FUNC-003, AC-FUNC-004
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="content")
    fetch_base_url = f"file://{repos_base}"
    manifest_bare = _create_single_project_manifest_repo(
        repos_base,
        fetch_base_url,
        project_name="content-bare",
        project_path="project-a",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init(workspace, f"file://{manifest_bare}")

    repo_dot = workspace / ".repo"
    assert repo_dot.is_dir(), f"Expected .repo/ directory at {repo_dot} after init, but it was not created."
    manifests_dir = repo_dot / "manifests"
    assert manifests_dir.is_dir(), (
        f"Expected .repo/manifests/ directory at {manifests_dir} after init, "
        f"but it was not created. .repo contents: {list(repo_dot.iterdir())!r}"
    )
    default_xml = manifests_dir / _MANIFEST_FILENAME
    assert default_xml.is_file() or any(manifests_dir.iterdir()), (
        f"Expected at least one file in {manifests_dir} after init, but it is empty."
    )


@pytest.mark.integration
def test_pipeline_sync_clones_all_declared_projects(tmp_path: pathlib.Path) -> None:
    """repo_sync() creates a directory for every project declared in the manifest.

    Uses the multi-project manifest (alpha + beta) to verify that sync creates
    both project directories in the workspace. No envsubst is needed because
    the manifest URLs are static.

    AC-FUNC-003, AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="alpha")
    _create_content_repo(repos_base, name="beta")
    fetch_base_url = f"file://{repos_base}"

    manifest_bare = _create_multi_project_manifest_repo(repos_base, fetch_base_url)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init(workspace, f"file://{manifest_bare}")
    repo_pkg.repo_sync(str(workspace))

    expected_project_paths = ["project-alpha", "project-beta"]
    for expected_path in expected_project_paths:
        project_dir = workspace / expected_path
        assert project_dir.is_dir(), (
            f"Expected project directory {project_dir} after sync, "
            f"but it was not created. Workspace contents: {sorted(str(p) for p in workspace.iterdir())!r}"
        )


@pytest.mark.integration
def test_pipeline_variable_substitution_resolves_placeholders(tmp_path: pathlib.Path) -> None:
    """repo_envsubst() replaces ${VAR} placeholders with injected environment values.

    After init, verifies the manifest XML still contains the placeholder. After
    envsubst with the variable injected, verifies the placeholder is gone and
    the real value is present. Does not run sync -- this test focuses solely on
    the envsubst stage.

    AC-FUNC-007
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="content")
    fetch_base_url = f"file://{repos_base}"
    fetch_var = "KANON_PIPELINE_VERIFY_VAR"

    manifest_bare = _create_envsubst_manifest_repo(
        repos_base,
        project_name="content-bare",
        project_path="project-verify",
        fetch_var=fetch_var,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init(workspace, f"file://{manifest_bare}")

    # Confirm the placeholder is present before envsubst
    manifests_dir = workspace / ".repo" / "manifests"
    xml_files_before = list(manifests_dir.glob("*.xml"))
    placeholder_present = any(f"${{{fetch_var}}}" in p.read_text(encoding="utf-8") for p in xml_files_before)
    assert placeholder_present, (
        f"Expected the placeholder ${{{fetch_var}}} to be present in at least one "
        f"manifest XML before envsubst. Files checked: {xml_files_before!r}"
    )

    # Run envsubst
    repo_pkg.repo_envsubst(str(workspace), {fetch_var: fetch_base_url})

    # Confirm the placeholder is resolved after envsubst
    xml_files_after = list(manifests_dir.glob("*.xml"))
    assert xml_files_after, (
        f"Expected at least one XML manifest after envsubst in {manifests_dir}, but none were found."
    )
    placeholder_still_present = any(f"${{{fetch_var}}}" in p.read_text(encoding="utf-8") for p in xml_files_after)
    assert not placeholder_still_present, (
        f"Expected the placeholder ${{{fetch_var}}} to be resolved after envsubst, "
        f"but it is still present in: {xml_files_after!r}"
    )
    url_present = any(fetch_base_url in p.read_text(encoding="utf-8") for p in xml_files_after)
    assert url_present, (
        f"Expected {fetch_base_url!r} to appear in at least one manifest XML after envsubst, "
        f"but it was not found. Files: {xml_files_after!r}"
    )


@pytest.mark.integration
def test_pipeline_multi_project_envsubst_sync_all_cloned(tmp_path: pathlib.Path) -> None:
    """Full init -> envsubst -> sync pipeline for a multi-project manifest with variable substitution.

    Creates two content repos and a manifest with a ${VAR} placeholder in the
    remote fetch URL. Runs the full pipeline: init, envsubst (to resolve the
    URL), sync. Verifies that all projects declared in the manifest are cloned.

    AC-FUNC-003, AC-FUNC-005, AC-FUNC-007
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    _create_content_repo(repos_base, name="gamma")
    _create_content_repo(repos_base, name="delta")
    fetch_base_url = f"file://{repos_base}"
    fetch_var = "KANON_MULTI_FETCH_URL"

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="${{{fetch_var}}}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="gamma-bare" path="project-gamma" />\n'
        '  <project name="delta-bare" path="project-delta" />\n'
        "</manifest>\n"
    )
    manifest_bare = _write_manifest_repo(repos_base, "manifest-multi-envsubst", manifest_xml)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Stage 1: init
    _repo_init(workspace, f"file://{manifest_bare}")
    assert (workspace / ".repo").is_dir(), "Expected .repo/ directory to exist after init."

    # Stage 2: envsubst -- resolve the fetch URL placeholder
    repo_pkg.repo_envsubst(str(workspace), {fetch_var: fetch_base_url})

    # Stage 3: sync
    repo_pkg.repo_sync(str(workspace))

    for project_path, content_name in [("project-gamma", "gamma"), ("project-delta", "delta")]:
        project_dir = workspace / project_path
        assert project_dir.is_dir(), (
            f"Expected project directory {project_dir} after full pipeline, "
            f"but it was not created. Workspace: {sorted(str(p) for p in workspace.iterdir())!r}"
        )
        readme = project_dir / "README.md"
        assert readme.is_file(), f"Expected {readme} to exist in cloned project, but it was not found."
        content = readme.read_text(encoding="utf-8")
        assert content_name in content, f"Expected {content_name!r} in README content but got: {content!r}"
