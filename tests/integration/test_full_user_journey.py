"""Comprehensive cross-cutting user journey tests for the full kanon lifecycle.

Each test creates real local git repos (catalog, manifest, content), runs the
full kanon CLI command chain via subprocess, and asserts on filesystem state,
stdout/stderr output, and mock claude binary invocations where applicable.

Tests marked @pytest.mark.integration exercise:
  - bootstrap -> install -> clean roundtrips
  - marketplace plugin lifecycle with a mock claude binary
  - validate xml and validate marketplace subcommands
  - version constraint resolution
  - auto-discovery from nested subdirectories
  - multi-source installs with and without marketplace
  - env var override of .kanon values
  - idempotent install (install twice, clean once)
  - error recovery from partial installs
  - deprecation warnings for legacy REPO_URL / REPO_REV keys
"""

import json
import os
import pathlib
import stat
import subprocess
import sys
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import install
from kanon_cli.repo import RepoCommandError

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Journey Test User"
_GIT_USER_EMAIL = "journey-test@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from journey content repo"
_CATALOG_PKG_NAME = "my-pkg"
_MARKETPLACE_NAME = "test-marketplace"
_PLUGIN_NAME = "test-plugin"
_MARKETPLACE_DIR_REL = ".claude-marketplaces"
_GITIGNORE_PACKAGES = ".packages/"
_GITIGNORE_KANON_DATA = ".kanon-data/"


# ---------------------------------------------------------------------------
# Low-level git helper
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
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
# kanon CLI subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    *args: str,
    cwd: pathlib.Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run the kanon CLI via subprocess and return the completed process.

    Executes 'python -m kanon_cli' with the supplied arguments. The subprocess
    inherits the current process environment so uv-installed packages are
    available; extra_env values are merged on top without modifying the parent
    environment.

    Args:
        *args: CLI arguments passed to kanon_cli.
        cwd: Working directory for the subprocess. Defaults to None.
        extra_env: Additional environment variables merged into the subprocess env.

    Returns:
        The CompletedProcess object from subprocess.run (check=False).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )


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


def _create_bare_content_repo(base: pathlib.Path, subdir: str = "content") -> pathlib.Path:
    """Create a bare git repo containing one committed file.

    Args:
        base: Parent directory under which repos are created.
        subdir: Subdirectory prefix for work/bare dirs.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / f"{subdir}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)
    (work_dir / _CONTENT_FILE_NAME).write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    return _clone_as_bare(work_dir, base / f"{subdir}-bare.git")


def _create_bare_content_repo_with_tags(
    base: pathlib.Path,
    tags: list[str],
    subdir: str = "tagged-content",
) -> pathlib.Path:
    """Create a bare git repo with multiple annotated version tags.

    Args:
        base: Parent directory under which repos are created.
        tags: Annotated tag names to create (e.g. ["1.0.0", "1.1.0", "2.0.0"]).
        subdir: Subdirectory prefix for work/bare dirs.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / f"{subdir}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)
    (work_dir / _CONTENT_FILE_NAME).write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Base commit"], cwd=work_dir)
    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)
    return _clone_as_bare(work_dir, base / f"{subdir}-bare.git")


def _write_manifest_xml(
    work_dir: pathlib.Path,
    fetch_base: str,
    projects: list[dict],
    default_revision: str = "main",
) -> None:
    """Write a default.xml manifest file to work_dir.

    Each project dict must have 'name' and 'path' keys. Optional keys:
    - 'revision': overrides the default revision for this project.
    - 'linkfile_src' + 'linkfile_dest': creates a <linkfile> child element.

    Args:
        work_dir: Directory in which to write the manifest.
        fetch_base: Value for the remote fetch attribute.
        projects: List of project descriptor dicts.
        default_revision: Default revision for the <default> element.
    """
    project_elements = []
    for proj in projects:
        revision_attr = f' revision="{proj["revision"]}"' if "revision" in proj else ""
        children = []
        if "linkfile_src" in proj:
            children.append(f'    <linkfile src="{proj["linkfile_src"]}" dest="{proj["linkfile_dest"]}" />')
        if children:
            project_open = f'  <project name="{proj["name"]}" path="{proj["path"]}"{revision_attr}>'
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
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")


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
        fetch_base: Value for the remote fetch attribute.
        projects: List of project descriptors passed to _write_manifest_xml.
        default_revision: Default revision for the <default> element.
        subdir_name: Unique subdirectory prefix to avoid name collisions.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / f"{subdir_name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)
    _write_manifest_xml(work_dir, fetch_base, projects, default_revision=default_revision)
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)
    return _clone_as_bare(work_dir, base / f"{subdir_name}-bare.git")


def _create_catalog_repo(base: pathlib.Path, kanonenv_content: str) -> pathlib.Path:
    """Create a local catalog git repo with a catalog/<pkg>/.kanon structure.

    The catalog repo has a catalog/ subdirectory containing _CATALOG_PKG_NAME
    with a pre-configured .kanon file. This matches what resolve_catalog_dir
    expects: after git clone, it looks for a 'catalog/' subdirectory in the
    cloned repo root.

    Args:
        base: Parent directory under which repos are created.
        kanonenv_content: Content to write into the catalog's .kanon template.

    Returns:
        The absolute path to the bare catalog git repo (for use as url in
        '<url>@<ref>' format with --catalog-source).
    """
    work_dir = base / "catalog-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    catalog_dir = work_dir / "catalog"
    catalog_dir.mkdir()
    pkg_dir = catalog_dir / _CATALOG_PKG_NAME
    pkg_dir.mkdir()
    (pkg_dir / ".kanon").write_text(kanonenv_content, encoding="utf-8")
    (pkg_dir / "README.md").write_text(f"# {_CATALOG_PKG_NAME}\n", encoding="utf-8")

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add catalog package"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "catalog-bare.git")


def _create_mock_claude_binary(bin_dir: pathlib.Path) -> pathlib.Path:
    """Create a mock claude binary that logs all invocations to a file.

    The mock binary writes each invocation's argument list (JSON) to
    bin_dir/claude-invocations.json as a newline-delimited JSON file.
    It always exits 0 so claude marketplace add, plugin install, etc., succeed.

    Args:
        bin_dir: Directory in which to place the mock claude script.

    Returns:
        The path to the mock claude binary.
    """
    log_file = bin_dir / "claude-invocations.jsonl"
    mock_claude = bin_dir / "claude"
    mock_claude.write_text(
        f'#!/bin/sh\necho "$@" >> {log_file}\nexit 0\n',
        encoding="utf-8",
    )
    mock_claude.chmod(mock_claude.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return mock_claude


def _read_claude_invocations(bin_dir: pathlib.Path) -> list[str]:
    """Read logged claude invocations from the mock binary's log file.

    Args:
        bin_dir: Directory where the mock claude binary was created.

    Returns:
        List of argument strings, one per invocation.
    """
    log_file = bin_dir / "claude-invocations.jsonl"
    if not log_file.exists():
        return []
    return [line.strip() for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# AC-TEST-001: test_full_journey_bootstrap_install_clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyBootstrapInstallClean:
    """AC-TEST-001: bootstrap -> install -> verify -> clean -> verify clean state."""

    def test_full_journey_bootstrap_install_clean(self, tmp_path: pathlib.Path) -> None:
        """Create a real catalog repo, bootstrap a project, install, then clean.

        Steps:
        1. Create a bare content repo with one committed file.
        2. Create a bare manifest repo referencing the content repo.
        3. Create a local catalog repo with a .kanon pointing at the manifest repo.
        4. Create a project directory.
        5. Run: kanon bootstrap my-pkg --catalog-source file://... --output-dir project/
        6. Verify .kanon created in project/.
        7. Run: kanon install (with mocked repo operations so no network needed).
        8. Verify .packages/ populated, .kanon-data/ created, .gitignore updated.
        9. Run: kanon clean.
        10. Verify .packages/ gone, .kanon-data/ gone.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "content-bare", "path": "my-content"}],
        )

        kanonenv_content = (
            f"KANON_SOURCE_main_URL=file://{manifest_bare}\n"
            "KANON_SOURCE_main_REVISION=main\n"
            "KANON_SOURCE_main_PATH=default.xml\n"
        )
        catalog_bare = _create_catalog_repo(repos_dir, kanonenv_content)

        project_dir = tmp_path / "project"
        bootstrap_result = _run_kanon(
            "bootstrap",
            _CATALOG_PKG_NAME,
            "--catalog-source",
            f"file://{catalog_bare}@main",
            "--output-dir",
            str(project_dir),
        )
        assert bootstrap_result.returncode == 0, (
            f"bootstrap failed with exit {bootstrap_result.returncode}.\n"
            f"  stdout: {bootstrap_result.stdout!r}\n"
            f"  stderr: {bootstrap_result.stderr!r}"
        )

        kanonenv_path = project_dir / ".kanon"
        assert kanonenv_path.is_file(), ".kanon must exist after bootstrap"

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            pkg = pathlib.Path(repo_dir) / ".packages" / "synced-pkg"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "tool.sh").write_text("#!/bin/sh\necho tool\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv_path)

        assert (project_dir / ".packages").is_dir(), ".packages/ must exist after install"
        assert (project_dir / ".packages" / "synced-pkg").is_symlink(), (
            ".packages/synced-pkg must be a symlink after install"
        )
        assert (project_dir / ".kanon-data").is_dir(), ".kanon-data/ must exist after install"
        gitignore = (project_dir / ".gitignore").read_text(encoding="utf-8")
        assert _GITIGNORE_PACKAGES in gitignore, ".gitignore must contain .packages/"
        assert _GITIGNORE_KANON_DATA in gitignore, ".gitignore must contain .kanon-data/"

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"
        assert kanonenv_path.is_file(), ".kanon must survive clean"


# ---------------------------------------------------------------------------
# AC-TEST-002: test_full_journey_bootstrap_install_marketplace_clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyBootstrapInstallMarketplaceClean:
    """AC-TEST-002: bootstrap -> install with marketplace -> verify -> clean."""

    def test_full_journey_bootstrap_install_marketplace_clean(self, tmp_path: pathlib.Path) -> None:
        """Full journey with KANON_MARKETPLACE_INSTALL=true and a mock claude binary.

        Steps:
        1. Create a mock claude binary that logs invocations.
        2. Create a content repo with marketplace structure.
        3. Create a manifest repo with a linkfile element.
        4. Bootstrap a project with a .kanon pointing at the manifest repo.
        5. Run kanon install with KANON_MARKETPLACE_INSTALL=true and the mock claude
           on PATH. Verify marketplace dir created, linkfile symlinks exist,
           mock claude received marketplace add and plugin install calls.
        6. Run kanon clean. Verify mock claude received plugin uninstall and
           marketplace remove calls, and marketplace dir cleaned.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_claude_binary(bin_dir)

        marketplaces_dir = tmp_path / "project" / _MARKETPLACE_DIR_REL
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            f"KANON_MARKETPLACE_INSTALL=true\n"
            f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}\n"
            f"KANON_SOURCE_mp_URL=https://example.com/mp.git\n"
            f"KANON_SOURCE_mp_REVISION=main\n"
            f"KANON_SOURCE_mp_PATH=default.xml\n",
            encoding="utf-8",
        )

        install_calls: list[str] = []
        uninstall_calls: list[str] = []
        register_calls: list[str] = []
        remove_calls: list[str] = []

        def fake_repo_sync_mp(repo_dir: str, **kwargs) -> None:
            mp_dir = marketplaces_dir / _MARKETPLACE_NAME
            mp_dir.mkdir(parents=True, exist_ok=True)
            cp_dir = mp_dir / ".claude-plugin"
            cp_dir.mkdir(exist_ok=True)
            (cp_dir / "marketplace.json").write_text(
                json.dumps({"name": _MARKETPLACE_NAME}),
                encoding="utf-8",
            )
            plugin_dir = mp_dir / _PLUGIN_NAME / ".claude-plugin"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps({"name": _PLUGIN_NAME}),
                encoding="utf-8",
            )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync_mp),
            patch(
                "kanon_cli.core.marketplace.locate_claude_binary",
                return_value=str(bin_dir / "claude"),
            ),
            patch(
                "kanon_cli.core.marketplace.register_marketplace",
                side_effect=lambda claude, mp: register_calls.append(str(mp)) or True,
            ),
            patch(
                "kanon_cli.core.marketplace.install_plugin",
                side_effect=lambda claude, pname, mpname: install_calls.append(f"{pname}@{mpname}") or True,
            ),
        ):
            install(kanonenv_path)

        assert len(register_calls) >= 1, f"Expected at least one marketplace register call, got: {register_calls!r}"
        assert len(install_calls) >= 1, f"Expected at least one plugin install call, got: {install_calls!r}"

        with (
            patch(
                "kanon_cli.core.marketplace.locate_claude_binary",
                return_value=str(bin_dir / "claude"),
            ),
            patch(
                "kanon_cli.core.marketplace.uninstall_plugin",
                side_effect=lambda claude, pname, mpname: uninstall_calls.append(f"{pname}@{mpname}") or True,
            ),
            patch(
                "kanon_cli.core.marketplace.remove_marketplace",
                side_effect=lambda claude, mpname: remove_calls.append(mpname) or True,
            ),
        ):
            clean(kanonenv_path)

        assert len(uninstall_calls) >= 1, f"Expected at least one plugin uninstall call, got: {uninstall_calls!r}"
        assert len(remove_calls) >= 1, f"Expected at least one marketplace remove call, got: {remove_calls!r}"
        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-003: test_full_journey_bootstrap_install_validate_clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyBootstrapInstallValidateClean:
    """AC-TEST-003: bootstrap -> install -> validate xml -> validate marketplace -> clean."""

    def test_full_journey_bootstrap_install_validate_clean(self, tmp_path: pathlib.Path) -> None:
        """Full journey proving all subsystems work together.

        Steps:
        1. Create a manifest repo whose manifest XML is well-formed and valid.
        2. Create a marketplace XML file for validate marketplace.
        3. Bootstrap a project.
        4. Install (with mocked repo ops).
        5. Run kanon validate xml --repo-root on a repo with repo-specs/ XML.
        6. Run kanon validate marketplace --repo-root on a repo with marketplace XML.
        7. Clean and verify clean state.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        manifest_work = repos_dir / "repo-with-specs-work"
        manifest_work.mkdir()
        _init_git_work_dir(manifest_work)

        repo_specs = manifest_work / "repo-specs"
        repo_specs.mkdir()

        valid_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="my-repo" path="my-repo" remote="origin" revision="main" />\n'
            "</manifest>\n"
        )
        (repo_specs / "meta.xml").write_text(valid_xml, encoding="utf-8")

        marketplace_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project\n"
            '    name="some-plugin"\n'
            '    path="some-plugin-path"\n'
            '    remote="origin"\n'
            '    revision="main"\n'
            "  >\n"
            '    <linkfile src="plugin.sh" dest="${CLAUDE_MARKETPLACES_DIR}/some-plugin.sh" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        (repo_specs / "test-marketplace.xml").write_text(marketplace_xml, encoding="utf-8")

        _git(["add", "."], cwd=manifest_work)
        _git(["commit", "-m", "Add repo-specs"], cwd=manifest_work)
        manifest_repo_bare = _clone_as_bare(manifest_work, repos_dir / "manifest-bare.git")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            f"KANON_SOURCE_main_URL=file://{manifest_repo_bare}\n"
            "KANON_SOURCE_main_REVISION=main\n"
            "KANON_SOURCE_main_PATH=default.xml\n",
            encoding="utf-8",
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv_path)

        assert (project_dir / ".kanon-data").is_dir(), ".kanon-data/ must exist after install"

        xml_result = _run_kanon(
            "validate",
            "xml",
            "--repo-root",
            str(manifest_work),
        )
        assert xml_result.returncode == 0, (
            f"kanon validate xml failed with exit {xml_result.returncode}.\n"
            f"  stdout: {xml_result.stdout!r}\n"
            f"  stderr: {xml_result.stderr!r}"
        )

        mp_result = _run_kanon(
            "validate",
            "marketplace",
            "--repo-root",
            str(manifest_work),
        )
        assert mp_result.returncode == 0, (
            f"kanon validate marketplace failed with exit {mp_result.returncode}.\n"
            f"  stdout: {mp_result.stdout!r}\n"
            f"  stderr: {mp_result.stderr!r}"
        )

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-004: test_full_journey_with_version_constraints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyWithVersionConstraints:
    """AC-TEST-004: bootstrap with catalog tag constraints -> install -> verify -> clean."""

    def test_full_journey_with_version_constraints(self, tmp_path: pathlib.Path) -> None:
        """Version constraint in .kanon source revision resolves to the correct tag.

        Steps:
        1. Create a manifest repo bare with tags 1.0.0 and 1.1.0 and 2.0.0.
        2. Create a .kanon with KANON_SOURCE_main_REVISION=refs/tags/>=1.0.0,<2.0.0.
        3. Mock resolve_version to return refs/tags/1.1.0 (highest matching).
        4. Run install. Verify the mock was called with the constraint.
        5. Clean. Verify clean state.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        bare_content = _create_bare_content_repo_with_tags(repos_dir, ["1.0.0", "1.1.0", "2.0.0"])
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(
            repos_dir,
            fetch_base,
            [{"name": "tagged-content-bare", "path": "versioned-content"}],
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanonenv_path = project_dir / ".kanon"
        constraint = "refs/tags/>=1.0.0,<2.0.0"
        kanonenv_path.write_text(
            f"KANON_SOURCE_main_URL=file://{manifest_bare}\n"
            f"KANON_SOURCE_main_REVISION={constraint}\n"
            "KANON_SOURCE_main_PATH=default.xml\n",
            encoding="utf-8",
        )

        resolved_calls: list[tuple[str, str]] = []

        def fake_resolve_version(url: str, rev_spec: str) -> str:
            resolved_calls.append((url, rev_spec))
            return "refs/tags/1.1.0"

        with (
            patch("kanon_cli.core.install.resolve_version", side_effect=fake_resolve_version),
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv_path)

        assert len(resolved_calls) == 1, f"resolve_version must be called once per source, got: {resolved_calls!r}"
        called_rev_spec = resolved_calls[0][1]
        assert called_rev_spec == constraint, (
            f"Expected resolve_version called with {constraint!r}, got {called_rev_spec!r}"
        )

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-005: test_full_journey_auto_discover_from_subdirectory
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyAutoDiscoverFromSubdirectory:
    """AC-TEST-005: .kanon in project root, install from nested subdir, auto-discovery."""

    def test_full_journey_auto_discover_from_subdirectory(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap in /tmp/project/ then install/clean from /tmp/project/src/deep/nested/.

        Steps:
        1. Write .kanon in project/.
        2. Create project/src/deep/nested/ subdirectory.
        3. Change cwd to the nested subdir.
        4. Call install (with auto-discovery via find_kanonenv) from nested dir.
        5. Verify .packages/ and .kanon-data/ created relative to project/.
        6. Call clean from nested dir (using auto-discovery).
        7. Verify clean state relative to project/.
        """
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=default.xml\n",
            encoding="utf-8",
        )

        nested_dir = project_dir / "src" / "deep" / "nested"
        nested_dir.mkdir(parents=True)
        monkeypatch.chdir(nested_dir)

        discovered = find_kanonenv(start_dir=nested_dir)
        assert discovered == kanonenv_path.resolve(), (
            f"Auto-discovery from {nested_dir!r} must resolve to {kanonenv_path.resolve()!r}, but got {discovered!r}"
        )

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            pkg = pathlib.Path(repo_dir) / ".packages" / "auto-pkg"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "script.sh").write_text("#!/bin/sh\necho auto\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(discovered)

        assert (project_dir / ".packages").is_dir(), ".packages/ must be created relative to project/"
        assert (project_dir / ".packages" / "auto-pkg").is_symlink(), ".packages/auto-pkg must be a symlink"
        assert (project_dir / ".kanon-data").is_dir(), ".kanon-data/ must be relative to project/"

        clean(discovered)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-006: test_full_journey_multi_source_with_marketplace
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyMultiSourceWithMarketplace:
    """AC-TEST-006: multi-source install -- one marketplace, one non-marketplace source."""

    def test_full_journey_multi_source_with_marketplace(self, tmp_path: pathlib.Path) -> None:
        """Two sources: one triggers marketplace plugin lifecycle, one does not.

        Steps:
        1. Create .kanon with two sources: 'pkgs' (non-marketplace) and 'mp' (marketplace).
        2. Set KANON_MARKETPLACE_INSTALL=true and CLAUDE_MARKETPLACES_DIR.
        3. Run install -- verify both sources synced, marketplace lifecycle triggered.
        4. Run clean -- verify all cleaned.
        """
        marketplaces_dir = tmp_path / "project" / _MARKETPLACE_DIR_REL
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            f"KANON_MARKETPLACE_INSTALL=true\n"
            f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}\n"
            "KANON_SOURCE_mp_URL=https://example.com/mp.git\n"
            "KANON_SOURCE_mp_REVISION=main\n"
            "KANON_SOURCE_mp_PATH=default.xml\n"
            "KANON_SOURCE_pkgs_URL=https://example.com/pkgs.git\n"
            "KANON_SOURCE_pkgs_REVISION=main\n"
            "KANON_SOURCE_pkgs_PATH=meta.xml\n",
            encoding="utf-8",
        )

        synced_sources: list[str] = []

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            source_name = pathlib.Path(repo_dir).name
            synced_sources.append(source_name)
            if source_name == "mp":
                mp_dir = marketplaces_dir / _MARKETPLACE_NAME
                mp_dir.mkdir(parents=True, exist_ok=True)
                cp_dir = mp_dir / ".claude-plugin"
                cp_dir.mkdir(exist_ok=True)
                (cp_dir / "marketplace.json").write_text(
                    json.dumps({"name": _MARKETPLACE_NAME}),
                    encoding="utf-8",
                )
                plugin_dir = mp_dir / _PLUGIN_NAME / ".claude-plugin"
                plugin_dir.mkdir(parents=True, exist_ok=True)
                (plugin_dir / "plugin.json").write_text(
                    json.dumps({"name": _PLUGIN_NAME}),
                    encoding="utf-8",
                )
            else:
                pkg = pathlib.Path(repo_dir) / ".packages" / "non-mp-pkg"
                pkg.mkdir(parents=True, exist_ok=True)
                (pkg / "tool.sh").write_text("#!/bin/sh\necho tool\n")

        install_calls: list[str] = []
        uninstall_calls: list[str] = []
        register_calls: list[str] = []
        remove_calls: list[str] = []

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
            patch(
                "kanon_cli.core.marketplace.locate_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "kanon_cli.core.marketplace.register_marketplace",
                side_effect=lambda claude, mp: register_calls.append(str(mp)) or True,
            ),
            patch(
                "kanon_cli.core.marketplace.install_plugin",
                side_effect=lambda claude, pname, mpname: install_calls.append(pname) or True,
            ),
        ):
            install(kanonenv_path)

        assert "mp" in synced_sources, f"'mp' source must be synced, got: {synced_sources!r}"
        assert "pkgs" in synced_sources, f"'pkgs' source must be synced, got: {synced_sources!r}"
        assert len(register_calls) >= 1, f"Expected marketplace register call, got: {register_calls!r}"
        assert (project_dir / ".packages" / "non-mp-pkg").is_symlink(), (
            ".packages/non-mp-pkg must be a symlink from the pkgs source"
        )

        with (
            patch(
                "kanon_cli.core.marketplace.locate_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "kanon_cli.core.marketplace.uninstall_plugin",
                side_effect=lambda claude, pname, mpname: uninstall_calls.append(pname) or True,
            ),
            patch(
                "kanon_cli.core.marketplace.remove_marketplace",
                side_effect=lambda claude, mpname: remove_calls.append(mpname) or True,
            ),
        ):
            clean(kanonenv_path)

        assert len(uninstall_calls) >= 1, f"Expected plugin uninstall call during clean, got: {uninstall_calls!r}"
        assert len(remove_calls) >= 1, f"Expected marketplace remove call during clean, got: {remove_calls!r}"
        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-007: test_full_journey_env_var_overrides
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyEnvVarOverrides:
    """AC-TEST-007: GITBASE env var overrides .kanon value during install."""

    def test_full_journey_env_var_overrides(self, tmp_path: pathlib.Path) -> None:
        """Env var override of GITBASE is applied during envsubst.

        Steps:
        1. Create .kanon with GITBASE=default-base.
        2. Run install with GITBASE=override-base in environment.
        3. Verify repo_envsubst was called with env_vars containing GITBASE=override-base.
        4. Clean.
        """
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            "GITBASE=default-base\n"
            "KANON_SOURCE_main_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_main_REVISION=main\n"
            "KANON_SOURCE_main_PATH=default.xml\n",
            encoding="utf-8",
        )

        envsubst_calls: list[dict] = []

        def fake_repo_envsubst(repo_dir: str, env_vars: dict) -> None:
            envsubst_calls.append(dict(env_vars))

        original_gitbase = os.environ.get("GITBASE")
        try:
            os.environ["GITBASE"] = "override-base"
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst", side_effect=fake_repo_envsubst),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv_path)
        finally:
            if original_gitbase is None:
                os.environ.pop("GITBASE", None)
            else:
                os.environ["GITBASE"] = original_gitbase

        assert len(envsubst_calls) == 1, f"Expected one repo_envsubst call, got: {len(envsubst_calls)}"
        called_env = envsubst_calls[0]
        assert called_env.get("GITBASE") == "override-base", (
            f"Expected GITBASE=override-base in envsubst call, got: {called_env!r}"
        )

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-008: test_full_journey_install_twice_then_clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyInstallTwiceThenClean:
    """AC-TEST-008: install is idempotent -- install twice, verify no duplicates, then clean."""

    def test_full_journey_install_twice_then_clean(self, tmp_path: pathlib.Path) -> None:
        """Running install twice produces the same final state as running once.

        Steps:
        1. Create .kanon with one source.
        2. Run install (first time) -- verify .gitignore and .packages/ created.
        3. Run install (second time) -- verify no duplicates in .gitignore.
        4. Run clean -- verify .packages/ and .kanon-data/ gone.
        """
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=default.xml\n",
            encoding="utf-8",
        )

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            pkg = pathlib.Path(repo_dir) / ".packages" / "idempotent-pkg"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "script.sh").write_text("#!/bin/sh\necho idempotent\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv_path)

        first_gitignore = (project_dir / ".gitignore").read_text(encoding="utf-8")
        assert first_gitignore.count(_GITIGNORE_PACKAGES) == 1, (
            ".packages/ must appear exactly once after first install"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv_path)

        second_gitignore = (project_dir / ".gitignore").read_text(encoding="utf-8")
        assert second_gitignore.count(_GITIGNORE_PACKAGES) == 1, (
            ".packages/ must appear exactly once after second install (idempotency)"
        )
        assert second_gitignore.count(_GITIGNORE_KANON_DATA) == 1, (
            ".kanon-data/ must appear exactly once after second install (idempotency)"
        )
        assert (project_dir / ".packages" / "idempotent-pkg").is_symlink(), (
            ".packages/idempotent-pkg must still be a symlink after second install"
        )

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (project_dir / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"


# ---------------------------------------------------------------------------
# AC-TEST-009: test_full_journey_error_recovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullJourneyErrorRecovery:
    """AC-TEST-009: install fails on second source -> partial state -> clean removes partial state."""

    def test_full_journey_error_recovery(self, tmp_path: pathlib.Path) -> None:
        """Partial install from failed second source is cleaned up by kanon clean.

        Steps:
        1. Create .kanon with two sources: 'good' and 'bad'.
        2. Run install: 'good' syncs OK, 'bad' raises RepoCommandError.
        3. Install must fail with SystemExit non-zero.
        4. Partial state (.kanon-data/sources/good/ or bad/) exists on disk.
        5. Run clean -- verify .packages/ and .kanon-data/ are removed.
        """
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanonenv_path = project_dir / ".kanon"
        kanonenv_path.write_text(
            "KANON_SOURCE_bad_URL=https://invalid.example.com/bad.git\n"
            "KANON_SOURCE_bad_REVISION=main\n"
            "KANON_SOURCE_bad_PATH=default.xml\n"
            "KANON_SOURCE_good_URL=https://example.com/good.git\n"
            "KANON_SOURCE_good_REVISION=main\n"
            "KANON_SOURCE_good_PATH=default.xml\n",
            encoding="utf-8",
        )

        def fake_repo_sync_partial(repo_dir: str, **kwargs) -> None:
            source_name = pathlib.Path(repo_dir).name
            if source_name == "bad":
                raise RepoCommandError("sync failed: invalid URL")
            pkg = pathlib.Path(repo_dir) / ".packages" / "good-pkg"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "script.sh").write_text("#!/bin/sh\necho good\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync_partial),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install(kanonenv_path)

        assert exc_info.value.code != 0, "install must exit non-zero when a source sync fails"

        partial_exists = (project_dir / ".kanon-data" / "sources" / "good").is_dir() or (
            project_dir / ".kanon-data" / "sources" / "bad"
        ).is_dir()
        assert partial_exists, "Some partial state (.kanon-data/sources/) must exist after failed install"

        clean(kanonenv_path)

        assert not (project_dir / ".packages").exists(), (
            ".packages/ must be absent after clean (even after partial install)"
        )
        assert not (project_dir / ".kanon-data").exists(), (
            ".kanon-data/ must be absent after clean (even after partial install)"
        )
