"""Unit tests for the <submanifest> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <submanifest> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <submanifest> element declares a sub-manifest for multi-manifest checkouts.
Documented attributes:
  Required: name (unique identifier for this submanifest)
  Optional: remote (remote name; only valid together with project)
  Optional: project (project name on the remote; required if remote is given)
  Optional: revision (commitish to check out; defaults to name.split('/')[-1])
  Optional: manifest-name (submanifest file name; defaults to "default.xml")
  Optional: groups (comma-separated group list applied to all submanifest projects)
  Optional: default-groups (comma-separated default group list)
  Optional: path (relative path for the submanifest checkout)

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_superproject_happy.py
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


def _build_submanifest_manifest(
    submanifest_name: str,
    extra_attrs: str = "",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build manifest XML that includes a <submanifest> element.

    Args:
        submanifest_name: The name attribute for the <submanifest> element.
        extra_attrs: Extra attributes string for the <submanifest> element.
        remote_name: Name of the remote to define.
        fetch_url: Fetch URL for the remote.
        default_revision: The revision for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    sm_attrs = f'name="{submanifest_name}"'
    if extra_attrs:
        sm_attrs = f"{sm_attrs} {extra_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <submanifest {sm_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <submanifest> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestMinimumAttributes:
    """Verify that a <submanifest> element with only the required name attribute parses correctly.

    The minimum valid <submanifest> requires only the name attribute. All other
    attributes are optional and have documented defaults.
    """

    def test_submanifest_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <submanifest name="..."> parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_submanifest_is_in_submanifests_dict_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing a manifest with <submanifest>, the name appears in manifest.submanifests.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "platform/sub" in manifest.submanifests, (
            f"Expected 'platform/sub' in manifest.submanifests but got keys: {list(manifest.submanifests.keys())}"
        )

    def test_submanifest_name_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed submanifest object has a name matching the XML name attribute.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.name == "platform/sub", f"Expected submanifest.name='platform/sub' but got: {sm.name!r}"

    def test_submanifests_empty_when_no_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <submanifest> element is present, manifest.submanifests is empty.

        AC-TEST-001: verifies the absence case to make the presence case meaningful.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert not manifest.submanifests, (
            f"Expected manifest.submanifests to be empty when element absent but got: {manifest.submanifests!r}"
        )

    def test_submanifest_remote_is_none_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no remote attribute is given, the parsed submanifest remote is None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.remote is None, f"Expected submanifest.remote=None when attribute absent but got: {sm.remote!r}"

    @pytest.mark.parametrize(
        "submanifest_name",
        [
            "platform/sub",
            "android/child",
            "org/nested-manifest",
        ],
    )
    def test_submanifest_name_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        submanifest_name: str,
    ) -> None:
        """Parameterized: various submanifest name values are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name=submanifest_name)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert submanifest_name in manifest.submanifests, (
            f"Expected '{submanifest_name}' in manifest.submanifests but got keys: {list(manifest.submanifests.keys())}"
        )
        sm = manifest.submanifests[submanifest_name]
        assert sm.name == submanifest_name, f"Expected submanifest.name='{submanifest_name}' but got: {sm.name!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <submanifest> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestAllDocumentedAttributes:
    """Verify that a <submanifest> element with all documented attributes parses correctly.

    The <submanifest> element documents these optional attributes alongside name:
    - revision: the commitish to check out
    - manifest-name: the submanifest manifest file name (defaults to "default.xml")
    - groups: comma-separated groups applied to all projects in the submanifest
    - default-groups: comma-separated default groups
    - path: relative checkout path (defaults to revision or name suffix)
    - remote + project: together define the remote source for the submanifest
    """

    def test_submanifest_with_explicit_revision_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> element with an explicit revision attribute parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs='revision="refs/heads/stable"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.revision == "refs/heads/stable", (
            f"Expected submanifest.revision='refs/heads/stable' but got: {sm.revision!r}"
        )

    def test_submanifest_with_explicit_manifest_name_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with an explicit manifest-name attribute parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs='manifest-name="custom.xml"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.manifestName == "custom.xml", (
            f"Expected submanifest.manifestName='custom.xml' but got: {sm.manifestName!r}"
        )

    def test_submanifest_with_explicit_path_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with an explicit path attribute parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs='path="mypath"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.path == "mypath", f"Expected submanifest.path='mypath' but got: {sm.path!r}"

    def test_submanifest_with_explicit_groups_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with an explicit groups attribute parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs='path="sub" groups="group1,group2"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert "group1" in sm.groups, f"Expected 'group1' in submanifest.groups but got: {sm.groups!r}"
        assert "group2" in sm.groups, f"Expected 'group2' in submanifest.groups but got: {sm.groups!r}"

    def test_submanifest_with_explicit_default_groups_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with an explicit default-groups attribute parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs='path="sub" default-groups="default,mygroup"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert "default" in sm.default_groups, (
            f"Expected 'default' in submanifest.default_groups but got: {sm.default_groups!r}"
        )
        assert "mygroup" in sm.default_groups, (
            f"Expected 'mygroup' in submanifest.default_groups but got: {sm.default_groups!r}"
        )

    def test_submanifest_with_remote_and_project_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with both remote and project attributes parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" project="sub/manifest" path="sub" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.remote == "origin", f"Expected submanifest.remote='origin' but got: {sm.remote!r}"
        assert sm.project == "sub/manifest", f"Expected submanifest.project='sub/manifest' but got: {sm.project!r}"

    def test_submanifest_remote_without_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> with remote but without project raises ManifestParseError.

        AC-TEST-002: the remote+project constraint is verified.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" path="sub" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/main",
            "refs/heads/stable",
            "refs/tags/v1.0.0",
        ],
    )
    def test_submanifest_explicit_revision_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: various explicit revision values are parsed and stored correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/sub",
            extra_attrs=f'revision="{revision}" path="sub"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/sub"]
        assert sm.revision == revision, f"Expected submanifest.revision='{revision}' but got: {sm.revision!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: <submanifest> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestDefaultAttributeValues:
    """Verify that default attribute values on <submanifest> behave as documented.

    The <submanifest> element documents:
    - When no revision is given, relpath defaults to name.split('/')[-1]
    - When no path is given and revision is given, relpath defaults to revision.split('/')[-1]
    - When no path is given and no revision is given, relpath defaults to name.split('/')[-1]
    - When no manifest-name is given, manifestName is None (ToSubmanifestSpec defaults it to "default.xml")
    - When no groups are given, groups is an empty list
    - When no default-groups are given, default_groups is an empty list
    - When no remote is given, remote is None
    - When no project is given, project is None
    """

    def test_submanifest_relpath_defaults_to_last_segment_of_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no path or revision is given, relpath defaults to last segment of name.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/child")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.relpath == "child", (
            f"Expected submanifest.relpath='child' (last segment of 'platform/child') but got: {sm.relpath!r}"
        )

    def test_submanifest_relpath_uses_explicit_path_when_given(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When path is given, relpath equals path.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/child",
            extra_attrs='path="explicit-path"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.relpath == "explicit-path", (
            f"Expected submanifest.relpath='explicit-path' when path is given but got: {sm.relpath!r}"
        )

    def test_submanifest_relpath_uses_last_segment_of_revision_when_no_path(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When revision is given but path is not, relpath defaults to last segment of revision.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(
            submanifest_name="platform/child",
            extra_attrs='revision="refs/heads/stable"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.relpath == "stable", (
            f"Expected submanifest.relpath='stable' (last segment of 'refs/heads/stable') but got: {sm.relpath!r}"
        )

    def test_submanifest_manifest_name_is_none_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no manifest-name is given, submanifest.manifestName is None.

        AC-TEST-003: manifestName=None is the stored default; callers default it to "default.xml".
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/child")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.manifestName is None, (
            f"Expected submanifest.manifestName=None when attribute absent but got: {sm.manifestName!r}"
        )

    def test_submanifest_groups_empty_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no groups attribute is given, submanifest.groups is an empty list.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/child")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.groups == [], f"Expected submanifest.groups=[] when attribute absent but got: {sm.groups!r}"

    def test_submanifest_default_groups_empty_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no default-groups attribute is given, submanifest.default_groups is an empty list.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/child")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests["platform/child"]
        assert sm.default_groups == [], (
            f"Expected submanifest.default_groups=[] when attribute absent but got: {sm.default_groups!r}"
        )

    def test_submanifest_name_required_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> missing the required name attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    @pytest.mark.parametrize(
        "name,expected_relpath",
        [
            ("simple", "simple"),
            ("platform/child", "child"),
            ("org/team/leaf", "leaf"),
        ],
    )
    def test_submanifest_relpath_default_for_various_name_structures(
        self,
        tmp_path: pathlib.Path,
        name: str,
        expected_relpath: str,
    ) -> None:
        """Parameterized: relpath defaults to last segment of name for various name structures.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name=name)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        sm = manifest.submanifests[name]
        assert sm.relpath == expected_relpath, (
            f"Expected submanifest.relpath='{expected_relpath}' for name='{name}' but got: {sm.relpath!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <submanifest> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_submanifest_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <submanifest> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <submanifest> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_submanifest_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <submanifest> with missing name raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
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
