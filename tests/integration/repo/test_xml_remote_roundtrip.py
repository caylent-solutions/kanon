"""Integration tests for <remote> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <remote>
element, verify the parsed model reflects the remote configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <remote> parses without error and the
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


def _build_remote_manifest(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    extra_remote_attrs: str = "",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a single <remote> element.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        extra_remote_attrs: Additional attributes string for the <remote> element.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    remote_attrs = f'name="{remote_name}" fetch="{fetch_url}"'
    if extra_remote_attrs:
        remote_attrs = f"{remote_attrs} {extra_remote_attrs}"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f"  <remote {remote_attrs} />\n"
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_remote_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <remote> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_remote_is_registered_in_manifest_remotes(tmp_path: pathlib.Path) -> None:
    """After parsing, the named remote is registered in manifest.remotes.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert "origin" in manifest.remotes, "Expected 'origin' in manifest.remotes after parsing but it was not found"
    assert manifest.remotes["origin"].fetchUrl == "https://example.com", (
        f"Expected fetchUrl='https://example.com' but got: {manifest.remotes['origin'].fetchUrl!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_preserves_remote_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <remote> element with the correct name and fetch.

    Parses a manifest with a <remote> element, calls ToXml(), and verifies
    the resulting XML document contains at least one <remote> element with
    the expected name and fetch attributes.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    assert len(remote_elements) >= 1, (
        f"Expected at least 1 <remote> element in round-trip XML but found: {len(remote_elements)}"
    )
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    assert origin_elements[0].getAttribute("fetch") == "https://example.com", (
        f"Expected fetch='https://example.com' in round-trip XML but got: {origin_elements[0].getAttribute('fetch')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_with_alias_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: an alias attribute on <remote> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
        extra_remote_attrs='alias="upstream"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    assert origin_elements[0].getAttribute("alias") == "upstream", (
        f"Expected alias='upstream' in round-trip XML but got: {origin_elements[0].getAttribute('alias')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_with_revision_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: a revision attribute on <remote> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
        extra_remote_attrs='revision="refs/heads/stable"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    assert origin_elements[0].getAttribute("revision") == "refs/heads/stable", (
        f"Expected revision='refs/heads/stable' in round-trip XML but got: "
        f"{origin_elements[0].getAttribute('revision')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_with_pushurl_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: a pushurl attribute on <remote> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://fetch.example.com",
        extra_remote_attrs='pushurl="https://push.example.com"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    assert origin_elements[0].getAttribute("pushurl") == "https://push.example.com", (
        f"Expected pushurl='https://push.example.com' in round-trip XML but got: "
        f"{origin_elements[0].getAttribute('pushurl')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_with_review_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: a review attribute on <remote> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
        extra_remote_attrs='review="review.example.com"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    assert origin_elements[0].getAttribute("review") == "review.example.com", (
        f"Expected review='review.example.com' in round-trip XML but got: {origin_elements[0].getAttribute('review')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_all_optional_attributes_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: all optional attributes on <remote> appear in ToXml output.

    Parses a manifest with a <remote> element that has all optional attributes set,
    and confirms round-trip ToXml preserves all of them.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://fetch.example.com",
        extra_remote_attrs=(
            'alias="upstream" '
            'pushurl="https://push.example.com" '
            'review="review.example.com" '
            'revision="refs/heads/stable"'
        ),
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    elem = origin_elements[0]
    assert elem.getAttribute("fetch") == "https://fetch.example.com", (
        f"Expected fetch='https://fetch.example.com' in round-trip but got: {elem.getAttribute('fetch')!r}"
    )
    assert elem.getAttribute("alias") == "upstream", (
        f"Expected alias='upstream' in round-trip but got: {elem.getAttribute('alias')!r}"
    )
    assert elem.getAttribute("pushurl") == "https://push.example.com", (
        f"Expected pushurl='https://push.example.com' in round-trip but got: {elem.getAttribute('pushurl')!r}"
    )
    assert elem.getAttribute("review") == "review.example.com", (
        f"Expected review='review.example.com' in round-trip but got: {elem.getAttribute('review')!r}"
    )
    assert elem.getAttribute("revision") == "refs/heads/stable", (
        f"Expected revision='refs/heads/stable' in round-trip but got: {elem.getAttribute('revision')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_optional_attrs_absent_when_not_set(tmp_path: pathlib.Path) -> None:
    """Round-trip: optional attributes are absent in ToXml output when not set in the manifest.

    A <remote> with only name and fetch should produce a round-trip XML element
    that does not contain alias, pushurl, review, or revision attributes.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name="origin",
        fetch_url="https://example.com",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    origin_elements = [e for e in remote_elements if e.getAttribute("name") == "origin"]
    assert len(origin_elements) == 1, (
        f"Expected exactly 1 <remote name='origin'> in round-trip XML but found: {len(origin_elements)}"
    )
    elem = origin_elements[0]
    assert elem.getAttribute("alias") == "", (
        f"Expected alias attribute to be absent in round-trip but got: {elem.getAttribute('alias')!r}"
    )
    assert elem.getAttribute("pushurl") == "", (
        f"Expected pushurl attribute to be absent in round-trip but got: {elem.getAttribute('pushurl')!r}"
    )
    assert elem.getAttribute("review") == "", (
        f"Expected review attribute to be absent in round-trip but got: {elem.getAttribute('review')!r}"
    )
    assert elem.getAttribute("revision") == "", (
        f"Expected revision attribute to be absent in round-trip but got: {elem.getAttribute('revision')!r}"
    )


@pytest.mark.integration
def test_remote_roundtrip_multiple_remotes_all_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: multiple <remote> elements are all preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://origin.example.com" />\n'
        '  <remote name="upstream" fetch="https://upstream.example.com" revision="refs/heads/main" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    remote_names = {e.getAttribute("name") for e in remote_elements}
    assert "origin" in remote_names, f"Expected 'origin' in round-trip remote names but found: {remote_names!r}"
    assert "upstream" in remote_names, f"Expected 'upstream' in round-trip remote names but found: {remote_names!r}"


@pytest.mark.integration
def test_remote_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model remote matches what was written to disk.

    Writes a manifest with a specific remote name and fetch URL, parses it,
    and asserts that the parsed model attributes match the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    remote_name = "caylent-platform"
    fetch_url = "https://git.caylent.com/platform"
    revision = "refs/heads/release"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_remote_manifest(
        remote_name=remote_name,
        fetch_url=fetch_url,
        extra_remote_attrs=f'revision="{revision}"',
        default_revision="main",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert remote_name in manifest.remotes, f"Expected '{remote_name}' in manifest.remotes but not found"
    remote = manifest.remotes[remote_name]
    assert remote.name == remote_name, f"Expected remote.name='{remote_name}' but got: {remote.name!r}"
    assert remote.fetchUrl == fetch_url, f"Expected remote.fetchUrl='{fetch_url}' but got: {remote.fetchUrl!r}"
    assert remote.revision == revision, f"Expected remote.revision='{revision}' but got: {remote.revision!r}"
