"""Unit tests for the <include> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <include> XML elements parse correctly when given
the minimum required attributes, all documented attributes, and that default
attribute values behave as documented.

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.

The <include> element allows a manifest to include another manifest file.
Documented attributes:
  Required: name (path to included manifest, relative to manifest repo root)
  Optional: groups (list of groups applied to all projects in included manifest)
  Optional: revision (default revision applied to projects in included manifest
            that do not already specify one)
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


def _write_included_manifest(repodir: pathlib.Path, filename: str, xml_content: str) -> pathlib.Path:
    """Write xml_content to a named manifest file inside the manifests directory.

    The manifests directory is the include_root. Included manifests are resolved
    relative to it.

    Args:
        repodir: The .repo directory.
        filename: Filename (no path components) for the included manifest.
        xml_content: Full XML content for the included manifest file.

    Returns:
        Absolute path to the written included manifest file.
    """
    included_file = repodir / "manifests" / filename
    included_file.write_text(xml_content, encoding="utf-8")
    return included_file


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


def _setup_include_scenario(
    tmp_path: pathlib.Path,
    primary_xml: str,
    included_filename: str,
    included_xml: str,
) -> manifest_xml.XmlManifest:
    """Write a primary manifest that includes a secondary manifest file and load it.

    The primary manifest references the included manifest by filename. The
    included manifest must be a standalone manifest (with <remote> and <default>
    elements).

    Args:
        tmp_path: Pytest tmp_path for isolation.
        primary_xml: Full XML content for the primary manifest file.
        included_filename: Filename for the included manifest (no path separators).
        included_xml: Full XML content for the included manifest.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    # The include_root for XmlManifest is the manifests/ directory.
    # The primary manifest.xml lives one level up in .repo/.
    # We write included manifests into manifests/ so they are found by
    # os.path.join(include_root, name).
    _write_included_manifest(repodir, included_filename, included_xml)
    manifest_file = _write_manifest(repodir, primary_xml)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <include> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeMinimumAttributes:
    """Verify that <include> with only the required name attribute parses correctly.

    The minimum valid <include> requires only the name attribute. The name must
    point to an existing manifest file on disk. With only name specified, the
    included projects are pulled in with no additional group or revision overrides.
    """

    def test_include_minimum_name_only_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> with only the name attribute parses without error.

        The included manifest file must exist. With no other attributes, the
        element is valid and the included projects are visible in the result.

        AC-TEST-001, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="included/project" path="proj" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_include_name_only_makes_included_projects_visible(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Projects declared in the included manifest are visible after loading.

        AC-TEST-001, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/build" path="build" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="included.xml" />\n</manifest>\n'
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "included.xml", included_xml)

        project_names = [p.name for p in manifest.projects]
        assert "tools/build" in project_names, (
            f"Expected 'tools/build' from included manifest to be visible after <include> but got: {project_names!r}"
        )

    def test_include_name_required_missing_raises_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> without a name attribute raises ManifestParseError.

        The name attribute is required. If it is absent the parser raises
        ManifestParseError.

        AC-TEST-001
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

    def test_include_nonexistent_file_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> referencing a non-existent file raises ManifestParseError.

        AC-TEST-001
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="does-not-exist.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "does-not-exist.xml" in str(exc_info.value), (
            f"Expected error message to mention 'does-not-exist.xml' but got: {exc_info.value!r}"
        )

    @pytest.mark.parametrize(
        "included_filename",
        [
            "sub.xml",
            "extra-projects.xml",
            "vendor-manifest.xml",
        ],
    )
    def test_include_name_with_various_filenames(
        self,
        tmp_path: pathlib.Path,
        included_filename: str,
    ) -> None:
        """Parameterized: <include name="..."> works for various valid filenames.

        AC-TEST-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <include name="{included_filename}" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, included_filename, included_xml)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' to be visible after <include name='{included_filename}'> "
            f"but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <include> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeAllDocumentedAttributes:
    """Verify that <include> using all documented attributes parses correctly.

    Documented attributes: name (required), groups (optional), revision (optional).
    """

    def test_include_groups_attribute_applies_groups_to_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include groups="..."> propagates the listed groups to all included projects.

        AC-TEST-002, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="sdk,release" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "sdk" in core.groups, (
            f"Expected group 'sdk' from <include groups='sdk,release'> to be applied to "
            f"included project but got: {core.groups!r}"
        )
        assert "release" in core.groups, (
            f"Expected group 'release' from <include groups='sdk,release'> to be applied to "
            f"included project but got: {core.groups!r}"
        )

    def test_include_revision_attribute_applies_revision_to_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include revision="..."> sets the default revision for included projects.

        Projects in the included manifest that do not specify their own revision
        receive the revision from the <include> element.

        AC-TEST-002, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" revision="refs/tags/v2.0.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v2.0.0", (
            f"Expected revisionExpr='refs/tags/v2.0.0' from <include revision='...'> to be "
            f"applied to included project without own revision but got: {tools.revisionExpr!r}"
        )

    def test_include_groups_and_revision_together(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> with both groups and revision applies both to included projects.

        AC-TEST-002, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="external" revision="refs/tags/v1.5.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        lib = projects["vendor/lib"]
        assert "external" in lib.groups, (
            f"Expected group 'external' from <include groups='external'> but got: {lib.groups!r}"
        )
        assert lib.revisionExpr == "refs/tags/v1.5.0", (
            f"Expected revisionExpr='refs/tags/v1.5.0' from <include revision='...'> but got: {lib.revisionExpr!r}"
        )

    def test_include_multiple_groups_applied_to_all_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple groups from <include groups="a,b,c"> are applied to all included projects.

        AC-TEST-002
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/alpha" path="alpha" />\n'
            '  <project name="platform/beta" path="beta" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="multi.xml" groups="a,b,c" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "multi.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        for proj_name in ("platform/alpha", "platform/beta"):
            proj = projects[proj_name]
            for group_name in ("a", "b", "c"):
                assert group_name in proj.groups, (
                    f"Expected group '{group_name}' on project '{proj_name}' after "
                    f"<include groups='a,b,c'> but got: {proj.groups!r}"
                )

    def test_include_groups_does_not_affect_non_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Groups from <include groups="..."> are not applied to projects in the primary manifest.

        AC-TEST-002
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="included/proj" path="iprojpath" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="primary/proj" path="pprojpath" />\n'
            '  <include name="sub.xml" groups="included-only-group" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        primary_proj = projects["primary/proj"]
        assert "included-only-group" not in primary_proj.groups, (
            f"Expected 'included-only-group' NOT in primary project's groups "
            f"(groups from <include> only apply to included projects) but got: {primary_proj.groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <include> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeDefaultAttributeValues:
    """Verify that default attribute behavior on <include> behaves as documented.

    When optional attributes are omitted from <include>:
    - groups: projects in the included manifest receive no additional groups
    - revision: projects in the included manifest keep their own revision (from
      the included manifest's <default> or <project> revision attributes)
    """

    def test_include_omitting_groups_leaves_included_project_groups_unchanged(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When groups is omitted from <include>, included project groups are unchanged.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="pdk,sdk" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "pdk" in core.groups, (
            f"Expected original group 'pdk' to be preserved when <include> omits groups but got: {core.groups!r}"
        )
        assert "sdk" in core.groups, (
            f"Expected original group 'sdk' to be preserved when <include> omits groups but got: {core.groups!r}"
        )

    def test_include_omitting_revision_preserves_included_project_own_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When revision is omitted from <include>, included projects keep their own revision.

        A project in the included manifest that specifies its own revision retains
        that revision regardless of whether <include> specifies a revision.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v1.0.0", (
            f"Expected revisionExpr='refs/tags/v1.0.0' from included manifest project's own "
            f"revision to be unchanged when <include> omits revision but got: {tools.revisionExpr!r}"
        )

    def test_include_revision_does_not_override_included_project_own_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When <include revision="..."> is set but a project has its own revision, the project wins.

        The <include revision="..."> only provides a default for projects that do not
        declare their own revision. A project with an explicit revision attribute keeps
        its own value.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" revision="refs/tags/v3.0.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        # The project explicitly sets revision="refs/tags/v1.0.0" so the
        # <include revision="refs/tags/v3.0.0"> must not override it.
        assert tools.revisionExpr == "refs/tags/v1.0.0", (
            f"Expected revisionExpr='refs/tags/v1.0.0' (project's own revision) to win "
            f"over <include revision='refs/tags/v3.0.0'> but got: {tools.revisionExpr!r}"
        )

    def test_include_default_revision_applies_to_projects_without_own_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<include revision="..."> acts as a default for projects that have no revision.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" />\n'
            '  <project name="platform/norev" path="norev" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" revision="refs/tags/v5.0.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        norev = projects["platform/norev"]
        assert norev.revisionExpr == "refs/tags/v5.0.0", (
            f"Expected revisionExpr='refs/tags/v5.0.0' from <include revision='...'> for "
            f"project with no own revision but got: {norev.revisionExpr!r}"
        )

    @pytest.mark.parametrize(
        "group_name",
        ["pdk", "sdk", "vendor", "release", "debug"],
    )
    def test_include_single_group_applied_to_included_projects(
        self,
        tmp_path: pathlib.Path,
        group_name: str,
    ) -> None:
        """Parameterized: a single group from <include groups="..."> is applied to included projects.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <include name="sub.xml" groups="{group_name}" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert group_name in core.groups, (
            f"Expected group '{group_name}' on included project from "
            f"<include groups='{group_name}'> but got: {core.groups!r}"
        )

    def test_include_groups_appends_to_existing_project_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Groups from <include> are appended to, not replacing, existing project groups.

        A project in the included manifest that already has groups retains them
        and also receives the groups from the <include> element.

        AC-TEST-003
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="existing-group" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="added-group" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "existing-group" in core.groups, (
            f"Expected 'existing-group' to be preserved after <include groups='added-group'> but got: {core.groups!r}"
        )
        assert "added-group" in core.groups, (
            f"Expected 'added-group' to be appended from <include groups='added-group'> but got: {core.groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <include> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    parse error is surfaced as a ManifestParseError and not silently swallowed
    or written to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_include_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <include> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        try:
            _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <include> to parse without ManifestParseError but got: {exc!r}")

    def test_missing_include_file_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> referencing a non-existent file raises ManifestParseError.

        AC-CHANNEL-001
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="no-such-file.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_missing_include_file_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An invalid <include> raises an exception, not silently writing to stdout.

        AC-CHANNEL-001
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="missing.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout output for <include> error but got: {captured.out!r}"
