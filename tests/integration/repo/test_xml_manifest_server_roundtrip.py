"""Integration tests for <manifest-server> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <manifest-server>
element, verify the parsed model reflects the manifest server URL, and confirm
round-trip serialization via ToXml preserves the expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <manifest-server> parses without error and the
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


def _build_manifest_server_manifest(
    server_url: str = "https://manifest.example.com/sync",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <manifest-server> element.

    Args:
        server_url: The url attribute for the <manifest-server> element.
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
        f'  <manifest-server url="{server_url}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_manifest_server_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <manifest-server> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_server_manifest(server_url="https://manifest.example.com/sync")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_manifest_server_url_is_set_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, manifest.manifest_server is a non-None string matching the url.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    expected_url = "https://manifest.example.com/sync"
    xml_content = _build_manifest_server_manifest(server_url=expected_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.manifest_server is not None, "Expected manifest.manifest_server to be set but got None"
    assert manifest.manifest_server == expected_url, (
        f"Expected manifest_server={expected_url!r} but got: {manifest.manifest_server!r}"
    )


@pytest.mark.integration
def test_manifest_server_roundtrip_preserves_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <manifest-server> element.

    Parses a manifest with a <manifest-server> element, calls ToXml(), and
    verifies the resulting XML document contains exactly one <manifest-server>
    element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_server_manifest(server_url="https://manifest.example.com/sync")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    server_elements = [n for n in root.childNodes if n.nodeName == "manifest-server"]
    assert len(server_elements) == 1, (
        f"Expected exactly 1 <manifest-server> element in round-trip XML but found: {len(server_elements)}"
    )


@pytest.mark.integration
def test_manifest_server_roundtrip_url_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the url attribute on <manifest-server> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    expected_url = "https://manifest.example.com/sync"
    xml_content = _build_manifest_server_manifest(server_url=expected_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    server_elements = [n for n in root.childNodes if n.nodeName == "manifest-server"]
    assert len(server_elements) == 1, (
        f"Expected exactly 1 <manifest-server> element in round-trip XML but found: {len(server_elements)}"
    )
    url_attr = server_elements[0].getAttribute("url")
    assert url_attr == expected_url, f"Expected url={expected_url!r} in round-trip XML but got: {url_attr!r}"


@pytest.mark.integration
def test_manifest_server_roundtrip_no_element_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: no <manifest-server> element in ToXml output when none was parsed.

    A manifest without a <manifest-server> element must produce ToXml output
    that also has no <manifest-server> element.

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

    server_elements = [n for n in root.childNodes if n.nodeName == "manifest-server"]
    assert len(server_elements) == 0, (
        f"Expected no <manifest-server> elements in round-trip XML when none was present "
        f"but found: {len(server_elements)}"
    )


@pytest.mark.integration
def test_manifest_server_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model manifest_server matches what was written to disk.

    Writes a manifest with a specific server url, parses it, and asserts that
    the parsed model attribute matches the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    server_url = "https://sync.corp.internal/manifest/v2/stable"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_server_manifest(server_url=server_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.manifest_server is not None, "Expected manifest.manifest_server to be set but got None"
    assert manifest.manifest_server == server_url, (
        f"Expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
    )


@pytest.mark.integration
def test_manifest_server_roundtrip_none_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: manifest.manifest_server is None when parsed from manifest without it.

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

    assert manifest.manifest_server is None, (
        f"Expected manifest.manifest_server=None when <manifest-server> was absent "
        f"but got: {manifest.manifest_server!r}"
    )


@pytest.mark.integration
def test_manifest_server_roundtrip_url_verbatim_in_toxml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the url value in ToXml matches the original XML attribute verbatim.

    Verifies that the parse + serialise cycle does not modify the url value.

    AC-FUNC-001, AC-FINAL-010
    """
    server_url = "https://manifest-server.example.com/api/v3/manifest/"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_server_manifest(server_url=server_url)
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.manifest_server == server_url, (
        f"Expected manifest_server={server_url!r} after parse but got: {manifest.manifest_server!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    server_elements = [n for n in root.childNodes if n.nodeName == "manifest-server"]
    assert len(server_elements) == 1, f"Expected exactly 1 <manifest-server> in ToXml but found: {len(server_elements)}"
    url_in_xml = server_elements[0].getAttribute("url")
    assert url_in_xml == server_url, f"Expected url={server_url!r} in ToXml output but got: {url_in_xml!r}"


@pytest.mark.integration
def test_manifest_server_roundtrip_with_projects(tmp_path: pathlib.Path) -> None:
    """Round-trip: <manifest-server> coexists with <project> elements in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    server_url = "https://manifest.example.com/sync"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <manifest-server url="{server_url}" />\n'
        '  <project name="tools/example" path="example" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.manifest_server == server_url, (
        f"Expected manifest_server={server_url!r} alongside projects but got: {manifest.manifest_server!r}"
    )
    assert len(manifest.projects) == 1, (
        f"Expected exactly 1 project in manifest alongside <manifest-server> but got: {len(manifest.projects)}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement
    server_elements = [n for n in root.childNodes if n.nodeName == "manifest-server"]
    assert len(server_elements) == 1, (
        f"Expected exactly 1 <manifest-server> element in round-trip XML but found: {len(server_elements)}"
    )
