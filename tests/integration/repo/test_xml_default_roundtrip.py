"""Integration tests for <default> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <default>
element, verify the parsed model reflects the default configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <default> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_remote_roundtrip.py
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


def _build_manifest_with_default(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_attrs: str = "",
) -> str:
    """Build a manifest XML string with a <remote> and a <default> element.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_attrs: Attribute string for the <default> element. If empty,
            the default element has no attributes.

    Returns:
        Full XML string for the manifest.
    """
    default_elem = f"  <default {default_attrs} />\n" if default_attrs else "  <default />\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"{default_elem}"
        "</manifest>\n"
    )


def _build_manifest_with_remote_and_default(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    revision: str = "main",
    extra_default_attrs: str = "",
) -> str:
    """Build a manifest XML string with <remote> and a <default> that references the remote.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        revision: The revision attribute on the <default> element.
        extra_default_attrs: Any additional attributes for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    default_attrs = f'remote="{remote_name}" revision="{revision}"'
    if extra_default_attrs:
        default_attrs = f"{default_attrs} {extra_default_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"  <default {default_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_default_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with an empty <default /> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_default()
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_default_with_remote_and_revision_model_matches_xml(tmp_path: pathlib.Path) -> None:
    """After parsing, the default model reflects the remote and revision from the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.default.remote is not None, "Expected default.remote to be set but got None"
    assert manifest.default.remote.name == "origin", (
        f"Expected default.remote.name='origin' but got: {manifest.default.remote.name!r}"
    )
    assert manifest.default.revisionExpr == "main", (
        f"Expected default.revisionExpr='main' but got: {manifest.default.revisionExpr!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_default_element_with_remote(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <default> element with the correct remote attribute.

    Parses a manifest with a <default remote="origin" revision="main" />,
    calls ToXml(), and verifies the resulting XML document contains a <default>
    element with the expected remote attribute.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("remote") == "origin", (
        f"Expected default element remote='origin' in round-trip XML but got: "
        f"{default_elements[0].getAttribute('remote')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_revision(tmp_path: pathlib.Path) -> None:
    """Round-trip: a revision attribute on <default> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="refs/heads/stable",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("revision") == "refs/heads/stable", (
        f"Expected default element revision='refs/heads/stable' in round-trip XML but got: "
        f"{default_elements[0].getAttribute('revision')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_dest_branch(tmp_path: pathlib.Path) -> None:
    """Round-trip: a dest-branch attribute on <default> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
        extra_default_attrs='dest-branch="release"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("dest-branch") == "release", (
        f"Expected default element dest-branch='release' in round-trip XML but got: "
        f"{default_elements[0].getAttribute('dest-branch')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_sync_j(tmp_path: pathlib.Path) -> None:
    """Round-trip: a sync-j attribute on <default> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
        extra_default_attrs='sync-j="4"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("sync-j") == "4", (
        f"Expected default element sync-j='4' in round-trip XML but got: {default_elements[0].getAttribute('sync-j')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_sync_c_true(tmp_path: pathlib.Path) -> None:
    """Round-trip: sync-c="true" on <default> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
        extra_default_attrs='sync-c="true"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("sync-c") == "true", (
        f"Expected default element sync-c='true' in round-trip XML but got: "
        f"{default_elements[0].getAttribute('sync-c')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_preserves_sync_tags_false(tmp_path: pathlib.Path) -> None:
    """Round-trip: sync-tags="false" on <default> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="main",
        extra_default_attrs='sync-tags="false"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("sync-tags") == "false", (
        f"Expected default element sync-tags='false' in round-trip XML but got: "
        f"{default_elements[0].getAttribute('sync-tags')!r}"
    )


@pytest.mark.integration
def test_default_roundtrip_all_documented_attributes_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: all documented attributes on <default> appear in ToXml output.

    Parses a manifest with a <default> element that has all documented attributes
    set, and confirms round-trip ToXml preserves all of them.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision="refs/heads/main",
        extra_default_attrs=('dest-branch="release" upstream="main" sync-j="8" sync-c="true" sync-tags="false"'),
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    elem = default_elements[0]
    assert elem.getAttribute("remote") == "origin", (
        f"Expected default element remote='origin' in round-trip but got: {elem.getAttribute('remote')!r}"
    )
    assert elem.getAttribute("revision") == "refs/heads/main", (
        f"Expected default element revision='refs/heads/main' in round-trip but got: {elem.getAttribute('revision')!r}"
    )
    assert elem.getAttribute("dest-branch") == "release", (
        f"Expected default element dest-branch='release' in round-trip but got: {elem.getAttribute('dest-branch')!r}"
    )
    assert elem.getAttribute("upstream") == "main", (
        f"Expected default element upstream='main' in round-trip but got: {elem.getAttribute('upstream')!r}"
    )
    assert elem.getAttribute("sync-j") == "8", (
        f"Expected default element sync-j='8' in round-trip but got: {elem.getAttribute('sync-j')!r}"
    )
    assert elem.getAttribute("sync-c") == "true", (
        f"Expected default element sync-c='true' in round-trip but got: {elem.getAttribute('sync-c')!r}"
    )
    assert elem.getAttribute("sync-tags") == "false", (
        f"Expected default element sync-tags='false' in round-trip but got: {elem.getAttribute('sync-tags')!r}"
    )


@pytest.mark.integration
def test_default_empty_element_not_included_in_roundtrip_when_no_values(tmp_path: pathlib.Path) -> None:
    """Round-trip: an empty <default /> with no set values produces no <default> in ToXml output.

    Per the ToXml implementation, a <default> element is only emitted when at
    least one attribute has a non-default value (have_default flag). An empty
    <default /> with all class defaults does not cause a <default> element in
    the round-trip output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_default()
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) == 0, (
        f"Expected no <default> element in round-trip XML when all values are class defaults "
        f"but found: {len(default_elements)}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "revision,expected_in_output",
    [
        ("main", "main"),
        ("refs/heads/stable", "refs/heads/stable"),
        ("refs/tags/v1.0", "refs/tags/v1.0"),
    ],
)
def test_default_roundtrip_revision_variations(
    tmp_path: pathlib.Path,
    revision: str,
    expected_in_output: str,
) -> None:
    """Round-trip: various revision expressions on <default> are preserved by ToXml.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_remote_and_default(
        remote_name="origin",
        fetch_url="https://example.com",
        revision=revision,
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) >= 1, (
        f"Expected at least 1 <default> element in round-trip XML for revision='{revision}' "
        f"but found: {len(default_elements)}"
    )
    actual_revision = default_elements[0].getAttribute("revision")
    assert actual_revision == expected_in_output, (
        f"Expected default element revision='{expected_in_output}' in round-trip but got: {actual_revision!r}"
    )
