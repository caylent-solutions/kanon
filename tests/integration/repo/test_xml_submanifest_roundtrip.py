"""Integration tests for <submanifest> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <submanifest>
element, verify the parsed model reflects the submanifest configuration, and
confirm round-trip serialization via ToXml preserves the expected structural
elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <submanifest> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_superproject_roundtrip.py
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
    submanifest_name: str = "platform/sub",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_sm_attrs: str = "",
) -> str:
    """Build a manifest XML string with a <submanifest> element.

    Args:
        submanifest_name: The name attribute for the <submanifest> element.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the declared remote.
        default_revision: The revision on the <default> element.
        extra_sm_attrs: Additional attributes string for the <submanifest> element.

    Returns:
        Full XML string for the manifest.
    """
    sm_attrs = f'name="{submanifest_name}"'
    if extra_sm_attrs:
        sm_attrs = f"{sm_attrs} {extra_sm_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <submanifest {sm_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_submanifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <submanifest> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_submanifest_is_in_submanifests_dict_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, the submanifest name appears as a key in manifest.submanifests.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert "platform/sub" in manifest.submanifests, (
        f"Expected 'platform/sub' in manifest.submanifests but got keys: {list(manifest.submanifests.keys())}"
    )
    sm = manifest.submanifests["platform/sub"]
    assert sm.name == "platform/sub", f"Expected submanifest.name='platform/sub' but got: {sm.name!r}"


@pytest.mark.integration
def test_submanifest_roundtrip_preserves_submanifest_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <submanifest> element.

    Parses a manifest with a <submanifest> element, calls ToXml(), and verifies
    the resulting XML document contains exactly one <submanifest> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_name_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the name attribute on <submanifest> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(submanifest_name="platform/sub")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )
    assert submanifest_elements[0].getAttribute("name") == "platform/sub", (
        f"Expected name='platform/sub' in round-trip XML but got: {submanifest_elements[0].getAttribute('name')!r}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_no_submanifest_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: no <submanifest> element in ToXml output when none was parsed.

    A manifest without a <submanifest> element must produce ToXml output that
    also has no <submanifest> element.

    AC-FUNC-001, AC-FINAL-010
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
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 0, (
        f"Expected no <submanifest> elements in round-trip XML when none was present "
        f"but found: {len(submanifest_elements)}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_with_explicit_revision(tmp_path: pathlib.Path) -> None:
    """Round-trip: an explicit revision attribute on <submanifest> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(
        submanifest_name="platform/sub",
        extra_sm_attrs='revision="refs/tags/v1.0.0" path="sub"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )
    revision_attr = submanifest_elements[0].getAttribute("revision")
    assert revision_attr == "refs/tags/v1.0.0", (
        f"Expected revision='refs/tags/v1.0.0' in round-trip XML but got: {revision_attr!r}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_with_explicit_path(tmp_path: pathlib.Path) -> None:
    """Round-trip: an explicit path attribute on <submanifest> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(
        submanifest_name="platform/sub",
        extra_sm_attrs='path="mysubpath"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )
    path_attr = submanifest_elements[0].getAttribute("path")
    assert path_attr == "mysubpath", f"Expected path='mysubpath' in round-trip XML but got: {path_attr!r}"


@pytest.mark.integration
def test_submanifest_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model submanifest matches what was written to disk.

    Writes a manifest with a specific submanifest name and revision, parses it,
    and asserts that the parsed model attributes match the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    sm_name = "android/platform-sub"
    sm_revision = "refs/heads/android-stable"
    sm_path = "androidsub"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(
        submanifest_name=sm_name,
        extra_sm_attrs=f'revision="{sm_revision}" path="{sm_path}"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert sm_name in manifest.submanifests, (
        f"Expected '{sm_name}' in manifest.submanifests but got keys: {list(manifest.submanifests.keys())}"
    )
    sm = manifest.submanifests[sm_name]
    assert sm.name == sm_name, f"Expected submanifest.name='{sm_name}' but got: {sm.name!r}"
    assert sm.revision == sm_revision, f"Expected submanifest.revision='{sm_revision}' but got: {sm.revision!r}"
    assert sm.path == sm_path, f"Expected submanifest.path='{sm_path}' but got: {sm.path!r}"


@pytest.mark.integration
def test_submanifest_roundtrip_with_manifest_name(tmp_path: pathlib.Path) -> None:
    """Round-trip: manifest-name attribute on <submanifest> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(
        submanifest_name="platform/sub",
        extra_sm_attrs='manifest-name="custom.xml"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )
    manifest_name_attr = submanifest_elements[0].getAttribute("manifest-name")
    assert manifest_name_attr == "custom.xml", (
        f"Expected manifest-name='custom.xml' in round-trip XML but got: {manifest_name_attr!r}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_none_when_absent_from_manifest(tmp_path: pathlib.Path) -> None:
    """Round-trip: manifest.submanifests is empty when parsed from a manifest without it.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert not manifest.submanifests, (
        f"Expected manifest.submanifests to be empty when <submanifest> was absent but got: {manifest.submanifests!r}"
    )


@pytest.mark.integration
def test_submanifest_roundtrip_with_groups(tmp_path: pathlib.Path) -> None:
    """Round-trip: groups attribute on <submanifest> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_submanifest_manifest(
        submanifest_name="platform/sub",
        extra_sm_attrs='path="sub" groups="group1,group2"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    sm = manifest.submanifests["platform/sub"]
    assert "group1" in sm.groups, f"Expected 'group1' in submanifest.groups but got: {sm.groups!r}"
    assert "group2" in sm.groups, f"Expected 'group2' in submanifest.groups but got: {sm.groups!r}"

    doc = manifest.ToXml()
    root = doc.documentElement
    submanifest_elements = [n for n in root.childNodes if n.nodeName == "submanifest"]
    assert len(submanifest_elements) == 1, (
        f"Expected exactly 1 <submanifest> element in round-trip XML but found: {len(submanifest_elements)}"
    )
    groups_attr = submanifest_elements[0].getAttribute("groups")
    assert groups_attr, f"Expected non-empty groups attribute in round-trip XML but got: {groups_attr!r}"
    assert "group1" in groups_attr, f"Expected 'group1' in groups attribute but got: {groups_attr!r}"
    assert "group2" in groups_attr, f"Expected 'group2' in groups attribute but got: {groups_attr!r}"
