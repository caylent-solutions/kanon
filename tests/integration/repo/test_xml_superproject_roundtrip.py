"""Integration tests for <superproject> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <superproject>
element, verify the parsed model reflects the superproject configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <superproject> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_manifest_roundtrip.py
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


def _build_superproject_manifest(
    superproject_name: str = "platform/superproject",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_sp_attrs: str = "",
) -> str:
    """Build a manifest XML string with a <superproject> element.

    Args:
        superproject_name: The name attribute for the <superproject> element.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the declared remote.
        default_revision: The revision on the <default> element.
        extra_sp_attrs: Additional attributes string for the <superproject> element.

    Returns:
        Full XML string for the manifest.
    """
    sp_attrs = f'name="{superproject_name}"'
    if extra_sp_attrs:
        sp_attrs = f"{sp_attrs} {extra_sp_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <superproject {sp_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_superproject_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <superproject> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_superproject_is_set_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, manifest.superproject is a non-None Superproject object.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.superproject is not None, "Expected manifest.superproject to be set but got None"
    assert manifest.superproject.name == "platform/superproject", (
        f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
    )


@pytest.mark.integration
def test_superproject_revision_inherits_from_default(tmp_path: pathlib.Path) -> None:
    """After parsing with no explicit revision, superproject.revision matches <default>.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(
        superproject_name="platform/superproject",
        default_revision="refs/heads/main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.superproject.revision == "refs/heads/main", (
        f"Expected superproject.revision='refs/heads/main' from <default> but got: {manifest.superproject.revision!r}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_preserves_superproject_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <superproject> element.

    Parses a manifest with a <superproject> element, calls ToXml(), and verifies
    the resulting XML document contains exactly one <superproject> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    superproject_elements = [n for n in root.childNodes if n.nodeName == "superproject"]
    assert len(superproject_elements) == 1, (
        f"Expected exactly 1 <superproject> element in round-trip XML but found: {len(superproject_elements)}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_name_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the name attribute on <superproject> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    superproject_elements = [n for n in root.childNodes if n.nodeName == "superproject"]
    assert len(superproject_elements) == 1, (
        f"Expected exactly 1 <superproject> element in round-trip XML but found: {len(superproject_elements)}"
    )
    assert superproject_elements[0].getAttribute("name") == "platform/superproject", (
        f"Expected name='platform/superproject' in round-trip XML but got: "
        f"{superproject_elements[0].getAttribute('name')!r}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_no_superproject_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: no <superproject> element in ToXml output when none was parsed.

    A manifest without a <superproject> element must produce ToXml output that
    also has no <superproject> element.

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

    superproject_elements = [n for n in root.childNodes if n.nodeName == "superproject"]
    assert len(superproject_elements) == 0, (
        f"Expected no <superproject> elements in round-trip XML when none was present "
        f"but found: {len(superproject_elements)}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_with_explicit_revision(tmp_path: pathlib.Path) -> None:
    """Round-trip: an explicit revision attribute on <superproject> appears in ToXml output.

    When a superproject has an explicit revision that differs from the default,
    the round-trip serialization must include the revision attribute.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(
        superproject_name="platform/superproject",
        extra_sp_attrs='revision="refs/tags/v1.0.0"',
        default_revision="main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    superproject_elements = [n for n in root.childNodes if n.nodeName == "superproject"]
    assert len(superproject_elements) == 1, (
        f"Expected exactly 1 <superproject> element in round-trip XML but found: {len(superproject_elements)}"
    )
    revision_attr = superproject_elements[0].getAttribute("revision")
    assert revision_attr == "refs/tags/v1.0.0", (
        f"Expected revision='refs/tags/v1.0.0' in round-trip XML but got: {revision_attr!r}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model superproject matches what was written to disk.

    Writes a manifest with a specific superproject name and revision, parses it,
    and asserts that the parsed model attributes match the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    sp_name = "android/platform-superproject"
    sp_revision = "refs/heads/android-stable"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_superproject_manifest(
        superproject_name=sp_name,
        extra_sp_attrs=f'revision="{sp_revision}"',
        default_revision="main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.superproject is not None, "Expected manifest.superproject to be set but got None"
    assert manifest.superproject.name == sp_name, (
        f"Expected superproject.name='{sp_name}' but got: {manifest.superproject.name!r}"
    )
    assert manifest.superproject.revision == sp_revision, (
        f"Expected superproject.revision='{sp_revision}' but got: {manifest.superproject.revision!r}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_with_multiple_remotes(tmp_path: pathlib.Path) -> None:
    """Round-trip: superproject with explicit non-default remote parses and round-trips.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <superproject name="platform/superproject" remote="upstream" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.superproject is not None, "Expected manifest.superproject to be set but got None"
    assert manifest.superproject.name == "platform/superproject", (
        f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    superproject_elements = [n for n in root.childNodes if n.nodeName == "superproject"]
    assert len(superproject_elements) == 1, (
        f"Expected exactly 1 <superproject> element in round-trip XML but found: {len(superproject_elements)}"
    )


@pytest.mark.integration
def test_superproject_roundtrip_none_when_absent_from_manifest(tmp_path: pathlib.Path) -> None:
    """Round-trip: manifest.superproject is None when parsed from a manifest without it.

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

    assert manifest.superproject is None, (
        f"Expected manifest.superproject=None when <superproject> was absent but got: {manifest.superproject!r}"
    )
