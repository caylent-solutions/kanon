"""Unit tests for the <extend-project> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <extend-project> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that default
attribute values behave as documented.

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.

The <extend-project> element allows one manifest to extend a project
already declared in a parent or included manifest. Documented attributes:
  Required: name (name of existing project to extend)
  Optional: path, dest-path, groups, revision, remote, dest-branch,
            upstream, base-rev
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_manifest_happy.py
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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content to a manifest file and load it.

    Args:
        tmp_path: Pytest tmp_path for isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <extend-project> with minimum required attributes parses
#              correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectMinimumAttributes:
    """Verify that <extend-project> with only the minimum required attribute (name)
    parses correctly.

    The minimum valid <extend-project> requires only a name attribute referencing
    an already-declared project. With only the name, no modifications are applied
    to the project but the element is valid and parsed without error.
    """

    def test_extend_project_minimum_name_only_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> with only the name attribute parses without error.

        The named project must already exist in the manifest. With no modification
        attributes, the element is a no-op that parses successfully.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" />\n'
            "</manifest>\n",
        )

        assert manifest is not None, "Expected XmlManifest instance but got None"
        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' in manifest.projects after extend-project but got: {project_names!r}"
        )

    def test_extend_project_name_references_existing_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The <extend-project name="..."> attribute references a project that was parsed.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <extend-project name="platform/tools" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/tools" in projects, (
            f"Expected 'platform/tools' in manifest projects but got: {list(projects.keys())!r}"
        )

    def test_extend_project_nonexistent_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> naming a non-existent project raises ManifestParseError.

        AC-TEST-001
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="platform/does-not-exist" />\n'
                "</manifest>\n",
            )
        assert "platform/does-not-exist" in str(exc_info.value), (
            f"Expected error message to mention 'platform/does-not-exist' but got: {exc_info.value!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/core",
            "vendor/library",
            "tools/build",
        ],
    )
    def test_extend_project_name_with_various_project_names(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: extend-project name attribute works for various project name formats.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{project_name}" path="proj" />\n'
            f'  <extend-project name="{project_name}" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert project_name in project_names, (
            f"Expected '{project_name}' in manifest.projects after extend-project but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <extend-project> with all documented attributes parses
#              correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectAllDocumentedAttributes:
    """Verify that <extend-project> using all documented attributes parses correctly.

    Covers: name (required), groups, revision, remote, dest-branch, upstream, path.
    """

    def test_extend_project_groups_attribute_appends_to_project_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project groups="..."> appends the listed groups to the named project.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="pdk" />\n'
            '  <extend-project name="platform/core" groups="extra,tools" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "pdk" in core.groups, (
            f"Expected original group 'pdk' to remain in project.groups but got: {core.groups!r}"
        )
        assert "extra" in core.groups, (
            f"Expected appended group 'extra' in project.groups after extend-project but got: {core.groups!r}"
        )
        assert "tools" in core.groups, (
            f"Expected appended group 'tools' in project.groups after extend-project but got: {core.groups!r}"
        )

    def test_extend_project_revision_attribute_updates_project_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project revision="..."> updates the named project's revisionExpr.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <extend-project name="platform/tools" revision="refs/tags/v2.0.0" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v2.0.0", (
            f"Expected revisionExpr='refs/tags/v2.0.0' after extend-project revision but got: {tools.revisionExpr!r}"
        )

    def test_extend_project_dest_branch_attribute_sets_project_dest_branch(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project dest-branch="..."> sets dest_branch on the named project.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" dest-branch="refs/heads/stable" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.dest_branch == "refs/heads/stable", (
            f"Expected dest_branch='refs/heads/stable' after extend-project but got: {core.dest_branch!r}"
        )

    def test_extend_project_upstream_attribute_sets_project_upstream(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project upstream="..."> sets upstream on the named project.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" upstream="refs/heads/upstream-branch" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.upstream == "refs/heads/upstream-branch", (
            f"Expected upstream='refs/heads/upstream-branch' after extend-project but got: {core.upstream!r}"
        )

    def test_extend_project_path_attribute_filters_project_by_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project path="..."> limits the extension to projects at that relpath.

        When a name matches multiple projects and a path is specified, only the
        project at the given relpath is extended. With a single project, the filter
        still works -- the single project matching the path is extended.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" path="core" groups="filtered" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "filtered" in core.groups, (
            f"Expected 'filtered' in project.groups after path-filtered extend-project but got: {core.groups!r}"
        )

    def test_extend_project_remote_attribute_updates_project_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project remote="..."> updates the named project's remote.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" remote="mirror" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.remote is not None, "Expected project.remote to be set after extend-project remote attribute"
        assert "mirror" in core.remote.name, (
            f"Expected project.remote.name to contain 'mirror' after extend-project but got: {core.remote.name!r}"
        )

    def test_extend_project_multiple_groups_added_at_once(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project groups="a,b,c"> appends all three groups to the project.

        AC-TEST-002
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="alpha,beta,gamma" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        for group_name in ("alpha", "beta", "gamma"):
            assert group_name in core.groups, (
                f"Expected group '{group_name}' in project.groups after extend-project but got: {core.groups!r}"
            )

    def test_extend_project_revision_and_groups_together(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> with both revision and groups applies both modifications.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" revision="refs/tags/v1.5.0" groups="release" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.revisionExpr == "refs/tags/v1.5.0", (
            f"Expected revisionExpr='refs/tags/v1.5.0' after extend-project but got: {core.revisionExpr!r}"
        )
        assert "release" in core.groups, (
            f"Expected 'release' in project.groups after extend-project but got: {core.groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <extend-project> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectDefaultAttributeValues:
    """Verify that default attribute behavior on <extend-project> behaves as documented.

    When optional attributes are omitted from <extend-project>:
    - groups: not modified (existing groups preserved unchanged)
    - revision: not modified (existing revisionExpr preserved)
    - dest-branch: not modified (existing dest_branch unchanged)
    - upstream: not modified (existing upstream unchanged)
    - path: no relpath filter applied (all projects with the given name extended)
    - remote: not modified if remote attribute is absent (uses default remote for
              path updates only; project remote not changed by omission)
    """

    def test_extend_project_omitting_groups_preserves_existing_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When groups is omitted from <extend-project>, existing groups are unchanged.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="pdk,sdk" />\n'
            '  <extend-project name="platform/core" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "pdk" in core.groups, (
            f"Expected 'pdk' group to be preserved when extend-project omits groups but got: {core.groups!r}"
        )
        assert "sdk" in core.groups, (
            f"Expected 'sdk' group to be preserved when extend-project omits groups but got: {core.groups!r}"
        )

    def test_extend_project_omitting_revision_preserves_existing_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When revision is omitted from <extend-project>, existing revisionExpr is unchanged.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
            '  <extend-project name="platform/tools" groups="extra" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v1.0.0", (
            f"Expected revisionExpr='refs/tags/v1.0.0' to be unchanged when "
            f"extend-project omits revision but got: {tools.revisionExpr!r}"
        )

    def test_extend_project_omitting_dest_branch_preserves_existing_dest_branch(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When dest-branch is omitted from <extend-project>, dest_branch is unchanged.

        A project with a pre-existing dest_branch from the <project> element
        retains that value when <extend-project> does not specify dest-branch.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" dest-branch="refs/heads/stable" />\n'
            '  <extend-project name="platform/core" groups="extra" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.dest_branch == "refs/heads/stable", (
            f"Expected dest_branch='refs/heads/stable' to be unchanged when "
            f"extend-project omits dest-branch but got: {core.dest_branch!r}"
        )

    def test_extend_project_omitting_upstream_preserves_existing_upstream(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When upstream is omitted from <extend-project>, upstream is unchanged.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" upstream="refs/heads/upstream" />\n'
            '  <extend-project name="platform/core" groups="extra" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.upstream == "refs/heads/upstream", (
            f"Expected upstream='refs/heads/upstream' to be unchanged when "
            f"extend-project omits upstream but got: {core.upstream!r}"
        )

    def test_extend_project_path_filter_skips_project_at_different_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When path filter does not match a project's relpath, that project is not modified.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="original" />\n'
            '  <extend-project name="platform/core" path="other-path" groups="should-not-appear" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "should-not-appear" not in core.groups, (
            f"Expected 'should-not-appear' NOT in project.groups when path filter "
            f"does not match relpath but got: {core.groups!r}"
        )
        assert "original" in core.groups, (
            f"Expected 'original' group to remain when path filter skips project but got: {core.groups!r}"
        )

    @pytest.mark.parametrize(
        "additional_group",
        ["sdk", "platform", "release", "debug"],
    )
    def test_extend_project_single_group_appended_correctly(
        self,
        tmp_path: pathlib.Path,
        additional_group: str,
    ) -> None:
        """Parameterized: a single group is appended correctly for various group names.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            f'  <extend-project name="platform/core" groups="{additional_group}" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert additional_group in core.groups, (
            f"Expected group '{additional_group}' in project.groups after extend-project but got: {core.groups!r}"
        )

    def test_multiple_extend_project_elements_for_same_project_accumulate(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <extend-project> elements targeting the same project all apply.

        Groups and other attributes from each successive <extend-project> are
        accumulated on the project.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="first-group" />\n'
            '  <extend-project name="platform/core" groups="second-group" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "first-group" in core.groups, (
            f"Expected 'first-group' in project.groups after first extend-project but got: {core.groups!r}"
        )
        assert "second-group" in core.groups, (
            f"Expected 'second-group' in project.groups after second extend-project but got: {core.groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <extend-project> parser must report errors exclusively through
    exceptions; it must not write error information to stdout. Tests here
    verify that a parse error is surfaced as a ManifestParseError and not
    silently swallowed or written to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_extend_project_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <extend-project> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        try:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="platform/core" groups="extra" />\n'
                "</manifest>\n",
            )
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid extend-project to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_extend_project_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> naming a non-existent project raises ManifestParseError.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="no-such-project" />\n'
                "</manifest>\n",
            )

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_invalid_extend_project_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An invalid <extend-project> raises an exception, not silently writing to stdout.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="no-such-project" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout output for extend-project error but got: {captured.out!r}"
