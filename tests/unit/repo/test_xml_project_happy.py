"""Unit tests for the <project> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <project> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <project> element declares a Git project to checkout. Documented attributes:
  Required: name (unique project identifier and git path on remote)
  Optional: path (local checkout path; defaults to name)
  Optional: remote (remote name; defaults to the <default> remote)
  Optional: revision (branch/tag/sha1; falls back to remote or default revision)
  Optional: groups (comma-separated group membership)
  Optional: rebase (bool; default True)
  Optional: sync-c (bool; default False -- sync current branch only)
  Optional: sync-s (bool; default False -- sync submodules)
  Optional: sync-tags (bool; default True)
  Optional: clone-depth (positive int; shallow clone depth)
  Optional: dest-branch (branch for push-to-review)
  Optional: upstream (upstream tracking branch)
  Children: <copyfile>, <linkfile>, <annotation>, <project> (subproject)

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_remote_happy.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/    (the include_root / worktree)
    - <tmp>/.repo/manifests.git/config  (remote origin URL for GitConfig)

    Args:
        tmp_path: Pytest tmp_path for isolation.

    Returns:
        The absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file path and return it.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML content for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate and load an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _build_project_manifest(
    project_name: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_project_attrs: str = "",
    project_children: str = "",
) -> str:
    """Build manifest XML containing one <project> element.

    Args:
        project_name: The name attribute for the <project> element.
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_revision: The revision for the <default> element.
        extra_project_attrs: Extra attributes string for the <project> element.
        project_children: Optional child elements as raw XML for the <project>.

    Returns:
        Full XML string for the manifest.
    """
    project_attrs = f'name="{project_name}"'
    if extra_project_attrs:
        project_attrs = f"{project_attrs} {extra_project_attrs}"

    if project_children:
        project_elem = f"  <project {project_attrs}>\n{project_children}  </project>\n"
    else:
        project_elem = f"  <project {project_attrs} />\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"{project_elem}"
        "</manifest>\n"
    )


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name of the project to retrieve.

    Returns:
        The Project object with the given name.

    Raises:
        KeyError: If the project is not found.
    """
    projects_by_name = {p.name: p for p in manifest.projects}
    return projects_by_name[project_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <project> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectMinimumAttributes:
    """Verify that a <project> element with only the required attributes parses correctly.

    The minimum valid <project> requires name only; revision and remote come
    from the <default> element and <remote> element respectively. Optional
    attributes (path, groups, dest-branch, upstream, clone-depth, etc.) must
    be at their defaults.
    """

    def test_project_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <project name="..."> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_project_is_registered_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, the named project appears in manifest.projects.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' in manifest.projects after parsing but not found. Got: {project_names!r}"
        )

    def test_project_name_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """project.name equals the name attribute on the <project> element.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.name == "platform/core", f"Expected project.name='platform/core' but got: {project.name!r}"

    def test_project_path_defaults_to_name_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When path is omitted, project.relpath equals project.name.

        AC-TEST-001: the path attribute defaults to name per the manifest spec.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.relpath == "platform/core", (
            f"Expected project.relpath='platform/core' (defaulting to name) but got: {project.relpath!r}"
        )

    def test_project_revision_inherits_from_default_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When revision is omitted, project.revisionExpr equals the <default> revision.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            default_revision="refs/heads/main",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.revisionExpr == "refs/heads/main", (
            f"Expected project.revisionExpr='refs/heads/main' from <default> but got: {project.revisionExpr!r}"
        )

    def test_project_remote_inherits_from_default_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When remote is omitted, project uses the <default> remote.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            remote_name="origin",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.remote is not None, "Expected project.remote to be set but got None"
        assert project.remote.orig_name == "origin", (
            f"Expected project.remote.orig_name='origin' from <default> but got: {project.remote.orig_name!r}"
        )

    def test_project_default_rebase_is_true(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When rebase is omitted, project.rebase defaults to True.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.rebase is True, f"Expected project.rebase=True when omitted but got: {project.rebase!r}"

    def test_project_default_sync_c_is_false(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-c is omitted, project.sync_c defaults to False.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_c is False, f"Expected project.sync_c=False when omitted but got: {project.sync_c!r}"

    def test_project_default_sync_s_is_false(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-s is omitted, project.sync_s defaults to False.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_s is False, f"Expected project.sync_s=False when omitted but got: {project.sync_s!r}"

    def test_project_default_sync_tags_is_true(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-tags is omitted, project.sync_tags defaults to True.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_tags is True, f"Expected project.sync_tags=True when omitted but got: {project.sync_tags!r}"

    def test_project_default_clone_depth_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When clone-depth is omitted, project.clone_depth is None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.clone_depth is None, (
            f"Expected project.clone_depth=None when omitted but got: {project.clone_depth!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/core",
            "infra/networking",
            "tools/linter",
        ],
    )
    def test_project_name_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: various project name values are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name=project_name)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert project_name in project_names, (
            f"Expected '{project_name}' in manifest.projects but not found. Got: {project_names!r}"
        )
        project = _get_project(manifest, project_name)
        assert project.name == project_name, f"Expected project.name='{project_name}' but got: {project.name!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <project> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectAllDocumentedAttributes:
    """Verify that a <project> element with all documented attributes parses correctly.

    The <project> element documents these optional attributes in addition to
    the required name: path, revision, groups, rebase, sync-c, sync-s,
    sync-tags, clone-depth, dest-branch, upstream.
    """

    def test_project_with_explicit_path_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with an explicit path attribute parses the relpath correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='path="src/core"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.relpath == "src/core", f"Expected project.relpath='src/core' but got: {project.relpath!r}"

    def test_project_with_explicit_revision_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with an explicit revision attribute parses the revisionExpr correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='revision="refs/heads/stable"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.revisionExpr == "refs/heads/stable", (
            f"Expected project.revisionExpr='refs/heads/stable' but got: {project.revisionExpr!r}"
        )

    def test_project_with_groups_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with a groups attribute has the specified groups in project.groups.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='groups="platform,infra"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert "platform" in project.groups, f"Expected 'platform' in project.groups but got: {project.groups!r}"
        assert "infra" in project.groups, f"Expected 'infra' in project.groups but got: {project.groups!r}"

    def test_project_with_rebase_false_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with rebase='false' has project.rebase=False after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='rebase="false"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.rebase is False, f"Expected project.rebase=False but got: {project.rebase!r}"

    def test_project_with_sync_c_true_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with sync-c='true' has project.sync_c=True after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='sync-c="true"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_c is True, f"Expected project.sync_c=True but got: {project.sync_c!r}"

    def test_project_with_sync_s_true_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with sync-s='true' has project.sync_s=True after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='sync-s="true"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_s is True, f"Expected project.sync_s=True but got: {project.sync_s!r}"

    def test_project_with_sync_tags_false_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with sync-tags='false' has project.sync_tags=False after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='sync-tags="false"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.sync_tags is False, f"Expected project.sync_tags=False but got: {project.sync_tags!r}"

    def test_project_with_clone_depth_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with clone-depth='1' has project.clone_depth=1 after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='clone-depth="1"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.clone_depth == 1, f"Expected project.clone_depth=1 but got: {project.clone_depth!r}"

    def test_project_with_dest_branch_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with dest-branch attribute has project.dest_branch set after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='dest-branch="refs/heads/release"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.dest_branch == "refs/heads/release", (
            f"Expected project.dest_branch='refs/heads/release' but got: {project.dest_branch!r}"
        )

    def test_project_with_upstream_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with upstream attribute has project.upstream set after parsing.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='upstream="refs/heads/main"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.upstream == "refs/heads/main", (
            f"Expected project.upstream='refs/heads/main' but got: {project.upstream!r}"
        )

    def test_project_with_annotation_child_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> element with an <annotation> child parses the annotation correctly.

        AC-TEST-002: <project> may contain annotation child elements.
        """
        repodir = _make_repo_dir(tmp_path)
        annotation_xml = '    <annotation name="team" value="platform-eng" keep="true" />\n'
        xml_content = _build_project_manifest(
            project_name="platform/core",
            project_children=annotation_xml,
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 1, f"Expected 1 annotation on project but got: {len(project.annotations)}"
        annotation = project.annotations[0]
        assert annotation.name == "team", f"Expected annotation.name='team' but got: {annotation.name!r}"
        assert annotation.value == "platform-eng", (
            f"Expected annotation.value='platform-eng' but got: {annotation.value!r}"
        )

    def test_project_with_copyfile_child_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> element with a <copyfile> child parses the copyfile correctly.

        AC-TEST-002: <project> may contain copyfile child elements.
        """
        repodir = _make_repo_dir(tmp_path)
        copyfile_xml = '    <copyfile src="Makefile" dest="Makefile" />\n'
        xml_content = _build_project_manifest(
            project_name="platform/core",
            project_children=copyfile_xml,
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, f"Expected 1 copyfile on project but got: {len(project.copyfiles)}"

    def test_multiple_projects_parse_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with multiple <project> elements parses all into manifest.projects.

        AC-TEST-002: multiple projects can coexist in one manifest.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" />\n'
            '  <project name="platform/tools" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' in manifest.projects but not found. Got: {project_names!r}"
        )
        assert "platform/tools" in project_names, (
            f"Expected 'platform/tools' in manifest.projects but not found. Got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/main",
            "refs/heads/stable",
            "refs/tags/v1.0.0",
        ],
    )
    def test_project_revision_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: various revision values on <project> are parsed and stored correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs=f'revision="{revision}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.revisionExpr == revision, (
            f"Expected project.revisionExpr='{revision}' but got: {project.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <project> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectDefaultAttributeValues:
    """Verify that default attribute values on <project> behave as documented.

    The <project> element documents:
    - When path is omitted, relpath equals name
    - When revision is omitted, revisionExpr falls through to <default>
    - When remote is omitted, the <default> remote is used
    - rebase defaults to True
    - sync-c defaults to False
    - sync-s defaults to False
    - sync-tags defaults to True
    - clone-depth defaults to None (full clone)
    - dest-branch defaults to None
    - upstream defaults to None
    - A <project> missing the required name attribute raises ManifestParseError
    - clone-depth=0 raises ManifestParseError (must be > 0)
    """

    def test_project_path_defaults_to_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When path is omitted, project.relpath equals project.name.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="infra/network")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "infra/network")
        assert project.relpath == project.name, (
            f"Expected project.relpath='{project.name}' (same as name) but got: {project.relpath!r}"
        )

    def test_project_upstream_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When upstream is not specified, project.upstream is falsy.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert not project.upstream, f"Expected project.upstream to be falsy when omitted but got: {project.upstream!r}"

    def test_project_dest_branch_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When dest-branch is not specified, project.dest_branch is None.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.dest_branch is None, (
            f"Expected project.dest_branch=None when omitted but got: {project.dest_branch!r}"
        )

    def test_project_annotations_empty_when_no_children(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <annotation> children are present, project.annotations is empty.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.annotations == [], (
            f"Expected project.annotations=[] when no annotation children but got: {project.annotations!r}"
        )

    def test_project_copyfiles_empty_when_no_children(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <copyfile> children are present, project.copyfiles is empty.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.copyfiles == [], (
            f"Expected project.copyfiles=[] when no copyfile children but got: {project.copyfiles!r}"
        )

    def test_project_missing_name_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> missing the required name attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing name but got empty string"
        )

    def test_project_clone_depth_zero_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with clone-depth='0' raises ManifestParseError (must be > 0).

        AC-TEST-003: clone-depth must be a positive integer.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs='clone-depth="0"',
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for clone-depth=0 but got empty string"
        )
        assert "clone-depth" in str(exc_info.value), (
            f"Expected 'clone-depth' in error message but got: {str(exc_info.value)!r}"
        )

    def test_project_groups_includes_default_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> always includes the 'all', 'name:<name>', and 'path:<relpath>' groups.

        AC-TEST-003: the parser adds default group membership automatically.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert "all" in project.groups, f"Expected 'all' in project.groups but got: {project.groups!r}"
        assert "name:platform/core" in project.groups, (
            f"Expected 'name:platform/core' in project.groups but got: {project.groups!r}"
        )
        assert "path:platform/core" in project.groups, (
            f"Expected 'path:platform/core' in project.groups but got: {project.groups!r}"
        )

    @pytest.mark.parametrize(
        "clone_depth",
        [1, 5, 100],
    )
    def test_project_clone_depth_parsed_for_various_positive_values(
        self,
        tmp_path: pathlib.Path,
        clone_depth: int,
    ) -> None:
        """Parameterized: various positive clone-depth values are parsed correctly.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(
            project_name="platform/core",
            extra_project_attrs=f'clone-depth="{clone_depth}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.clone_depth == clone_depth, (
            f"Expected project.clone_depth={clone_depth} but got: {project.clone_depth!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <project> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_project_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <project> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_project_manifest(project_name="platform/core")
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <project> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_project_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <project> with missing name raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
