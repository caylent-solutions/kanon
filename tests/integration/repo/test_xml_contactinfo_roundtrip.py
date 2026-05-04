"""Integration tests for <contactinfo> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <contactinfo>
element, verify the parsed model reflects the contactinfo configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <contactinfo> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.wrapper import Wrapper


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


def _build_contactinfo_manifest(
    bugurl: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <contactinfo> element.

    Args:
        bugurl: The bugurl attribute for the <contactinfo> element.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the declared remote.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <contactinfo bugurl="{bugurl}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_contactinfo_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <contactinfo> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_contactinfo_manifest(bugurl="https://bugs.example.com/issues")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_contactinfo_bugurl_is_set_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, manifest.contactinfo.bugurl equals the bugurl attribute from XML.

    AC-FUNC-001, AC-FINAL-010
    """
    expected_url = "https://bugs.example.com/issues"
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_contactinfo_manifest(bugurl=expected_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.contactinfo is not None, "Expected manifest.contactinfo to be set but got None"
    assert manifest.contactinfo.bugurl == expected_url, (
        f"Expected contactinfo.bugurl='{expected_url}' but got: {manifest.contactinfo.bugurl!r}"
    )


@pytest.mark.integration
def test_contactinfo_default_when_element_absent(tmp_path: pathlib.Path) -> None:
    """When no <contactinfo> element is present, contactinfo.bugurl is Wrapper().BUG_URL.

    AC-FUNC-001, AC-FINAL-010
    """
    default_bugurl = Wrapper().BUG_URL
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

    assert manifest.contactinfo.bugurl == default_bugurl, (
        f"Expected contactinfo.bugurl='{default_bugurl}' (default) when element absent "
        f"but got: {manifest.contactinfo.bugurl!r}"
    )


@pytest.mark.integration
def test_contactinfo_roundtrip_emits_element_when_bugurl_differs_from_default(
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip: ToXml emits a <contactinfo> element when bugurl differs from the default.

    Parses a manifest with a custom <contactinfo bugurl="...">, calls ToXml(), and
    verifies the resulting XML document contains exactly one <contactinfo> element
    with the correct bugurl.

    AC-FUNC-001, AC-FINAL-010
    """
    custom_url = "https://bugs.example.com/issues"
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_contactinfo_manifest(bugurl=custom_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    contactinfo_elements = [n for n in root.childNodes if n.nodeName == "contactinfo"]
    assert len(contactinfo_elements) == 1, (
        f"Expected exactly 1 <contactinfo> element in round-trip XML but found: {len(contactinfo_elements)}"
    )
    assert contactinfo_elements[0].getAttribute("bugurl") == custom_url, (
        f"Expected bugurl='{custom_url}' in round-trip XML but got: {contactinfo_elements[0].getAttribute('bugurl')!r}"
    )


@pytest.mark.integration
def test_contactinfo_roundtrip_omits_element_when_bugurl_is_default(
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip: ToXml omits <contactinfo> when the bugurl equals the default BUG_URL.

    When no <contactinfo> element is in the manifest, the parsed bugurl is the default
    Wrapper().BUG_URL value. ToXml only serializes a <contactinfo> element when the
    value differs from the default, so no element is expected in the output.

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

    contactinfo_elements = [n for n in root.childNodes if n.nodeName == "contactinfo"]
    assert len(contactinfo_elements) == 0, (
        f"Expected no <contactinfo> elements in round-trip XML when bugurl equals default "
        f"but found: {len(contactinfo_elements)}"
    )


@pytest.mark.integration
def test_contactinfo_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model contactinfo matches what was written to disk.

    Writes a manifest with a specific contactinfo bugurl, parses it, and asserts
    that the parsed model attribute matches the XML. Then confirms round-trip via ToXml.

    AC-FUNC-001, AC-FINAL-010
    """
    custom_url = "https://jira.company.com/browse/PROJ-1234"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_contactinfo_manifest(bugurl=custom_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.contactinfo is not None, "Expected manifest.contactinfo to be set but got None"
    assert manifest.contactinfo.bugurl == custom_url, (
        f"Expected contactinfo.bugurl='{custom_url}' but got: {manifest.contactinfo.bugurl!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    contactinfo_elements = [n for n in root.childNodes if n.nodeName == "contactinfo"]
    assert len(contactinfo_elements) == 1, (
        f"Expected exactly 1 <contactinfo> element in round-trip XML but found: {len(contactinfo_elements)}"
    )
    assert contactinfo_elements[0].getAttribute("bugurl") == custom_url, (
        f"Expected bugurl='{custom_url}' in round-trip XML element but got: "
        f"{contactinfo_elements[0].getAttribute('bugurl')!r}"
    )


@pytest.mark.integration
def test_contactinfo_roundtrip_duplicate_last_wins_and_roundtrips(tmp_path: pathlib.Path) -> None:
    """Round-trip: when <contactinfo> is duplicated, the last entry is stored and round-trips.

    Parses a manifest with two <contactinfo> elements, confirms the last entry's bugurl
    is used, and verifies the round-trip ToXml output contains exactly one <contactinfo>
    element with the last bugurl.

    AC-FUNC-001, AC-FINAL-010
    """
    first_url = "https://first.example.com/issues"
    last_url = "https://last.example.com/issues"

    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <contactinfo bugurl="{first_url}" />\n'
        f'  <contactinfo bugurl="{last_url}" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.contactinfo.bugurl == last_url, (
        f"Expected last <contactinfo> bugurl='{last_url}' to win but got: {manifest.contactinfo.bugurl!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    contactinfo_elements = [n for n in root.childNodes if n.nodeName == "contactinfo"]
    assert len(contactinfo_elements) == 1, (
        f"Expected exactly 1 <contactinfo> element in round-trip XML but found: {len(contactinfo_elements)}"
    )
    assert contactinfo_elements[0].getAttribute("bugurl") == last_url, (
        f"Expected bugurl='{last_url}' in round-trip XML but got: {contactinfo_elements[0].getAttribute('bugurl')!r}"
    )


@pytest.mark.integration
def test_contactinfo_contactinfo_is_never_none(tmp_path: pathlib.Path) -> None:
    """manifest.contactinfo is always a ContactInfo object -- never None.

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

    assert manifest.contactinfo is not None, "Expected manifest.contactinfo to always be set (not None) but got None"
    assert hasattr(manifest.contactinfo, "bugurl"), (
        "Expected manifest.contactinfo to have a bugurl attribute but it does not"
    )
