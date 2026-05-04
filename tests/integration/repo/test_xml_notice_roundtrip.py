"""Integration tests for <notice> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <notice> element,
verify the parsed model reflects the notice content, and confirm round-trip
serialization via ToXml preserves the expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <notice> parses without error and the parsed
model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


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


def _build_notice_manifest(
    notice_text: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <notice> element containing the given text.

    Args:
        notice_text: The text content for the <notice> element.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the declared remote.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f"  <notice>{notice_text}</notice>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_notice_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <notice> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_notice_manifest(notice_text="Important project notice.")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_notice_is_set_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, manifest.notice is a non-None string with the notice content.

    AC-FUNC-001, AC-FINAL-010
    """
    expected_text = "Important project notice."
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_notice_manifest(notice_text=expected_text)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
    assert manifest.notice == expected_text, f"Expected notice={expected_text!r} but got: {manifest.notice!r}"


@pytest.mark.integration
def test_notice_none_when_element_absent(tmp_path: pathlib.Path) -> None:
    """When no <notice> element is present, manifest.notice is None.

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

    assert manifest.notice is None, f"Expected manifest.notice=None when element absent but got: {manifest.notice!r}"


@pytest.mark.integration
def test_notice_roundtrip_preserves_notice_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <notice> element when notice is set.

    Parses a manifest with a <notice> element, calls ToXml(), and verifies
    the resulting XML document contains exactly one <notice> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_notice_manifest(notice_text="Project notice text here.")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    notice_elements = [n for n in root.childNodes if n.nodeName == "notice"]
    assert len(notice_elements) == 1, (
        f"Expected exactly 1 <notice> element in round-trip XML but found: {len(notice_elements)}"
    )


@pytest.mark.integration
def test_notice_roundtrip_content_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the text content of <notice> is preserved in ToXml output.

    The round-trip XML must include the notice text content inside the
    <notice> element. The exact whitespace may vary due to indentation
    normalization, but the core notice text must be present.

    AC-FUNC-001, AC-FINAL-010
    """
    notice_text = "Project notice text here."
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_notice_manifest(notice_text=notice_text)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    notice_elements = [n for n in root.childNodes if n.nodeName == "notice"]
    assert len(notice_elements) == 1, (
        f"Expected exactly 1 <notice> element in round-trip XML but found: {len(notice_elements)}"
    )
    notice_node = notice_elements[0]
    notice_content = "".join(child.data for child in notice_node.childNodes if child.nodeType == child.TEXT_NODE)
    assert notice_text in notice_content, (
        f"Expected notice text {notice_text!r} to appear in round-trip XML notice content but got: {notice_content!r}"
    )


@pytest.mark.integration
def test_notice_roundtrip_no_notice_element_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: no <notice> element in ToXml output when none was parsed.

    A manifest without a <notice> element must produce ToXml output that
    also has no <notice> element.

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

    notice_elements = [n for n in root.childNodes if n.nodeName == "notice"]
    assert len(notice_elements) == 0, (
        f"Expected no <notice> elements in round-trip XML when none was present but found: {len(notice_elements)}"
    )


@pytest.mark.integration
def test_notice_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model notice matches what was written to disk.

    Writes a manifest with a specific notice text, parses it, and asserts
    that the parsed model attribute matches the XML. Then confirms round-trip
    via ToXml.

    AC-FUNC-001, AC-FINAL-010
    """
    notice_text = "Review the contributing guide before submitting patches."

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_notice_manifest(notice_text=notice_text)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
    assert manifest.notice == notice_text, f"Expected notice={notice_text!r} but got: {manifest.notice!r}"

    doc = manifest.ToXml()
    root = doc.documentElement
    notice_elements = [n for n in root.childNodes if n.nodeName == "notice"]
    assert len(notice_elements) == 1, (
        f"Expected exactly 1 <notice> element in round-trip XML but found: {len(notice_elements)}"
    )


@pytest.mark.integration
def test_notice_roundtrip_multiline_content(tmp_path: pathlib.Path) -> None:
    """Round-trip: a multi-line <notice> parses and round-trips preserving content.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        "  <notice>\n"
        "    Line one of notice.\n"
        "    Line two of notice.\n"
        "  </notice>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
    assert "Line one of notice." in manifest.notice, (
        f"Expected 'Line one of notice.' in manifest.notice but got: {manifest.notice!r}"
    )
    assert "Line two of notice." in manifest.notice, (
        f"Expected 'Line two of notice.' in manifest.notice but got: {manifest.notice!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    notice_elements = [n for n in root.childNodes if n.nodeName == "notice"]
    assert len(notice_elements) == 1, (
        f"Expected exactly 1 <notice> element in round-trip XML but found: {len(notice_elements)}"
    )


@pytest.mark.integration
def test_notice_duplicate_raises_parse_error(tmp_path: pathlib.Path) -> None:
    """A manifest with two <notice> elements raises ManifestParseError.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        "  <notice>First notice.</notice>\n"
        "  <notice>Second notice.</notice>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
