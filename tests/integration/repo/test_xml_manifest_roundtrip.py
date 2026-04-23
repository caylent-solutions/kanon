"""Integration tests for <manifest> round-trip parsing.

Tests parse a real manifest XML file from disk, verify the parsed model
matches the XML, then serialize back to XML (via ToXml) and confirm the
key structural elements are preserved.

All tests use real manifest files written to tmp_path or the
on-disk fixture at tests/unit/repo/fixtures/sample-manifest.xml.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <manifest> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip against a real on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Location of the on-disk fixture
# ---------------------------------------------------------------------------

_FIXTURE_DIR = pathlib.Path(__file__).parents[2] / "unit" / "repo" / "fixtures"
_SAMPLE_MANIFEST = _FIXTURE_DIR / "sample-manifest.xml"

# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_manifest_parsing.py
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


# ---------------------------------------------------------------------------
# AC-FINAL-010: Real on-disk fixture parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sample_fixture_exists_on_disk() -> None:
    """The on-disk fixture file exists at the expected path.

    AC-FINAL-010
    """
    assert _SAMPLE_MANIFEST.exists(), f"Expected fixture file at '{_SAMPLE_MANIFEST}' but it does not exist"
    assert _SAMPLE_MANIFEST.is_file(), f"Expected '{_SAMPLE_MANIFEST}' to be a regular file but it is not"


@pytest.mark.integration
def test_sample_fixture_parses_without_error(tmp_path: pathlib.Path) -> None:
    """The on-disk sample-manifest.xml fixture parses into a valid XmlManifest.

    Copies the fixture into a real .repo structure and loads it. No exception
    must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading fixture"


@pytest.mark.integration
def test_sample_fixture_remote_origin_present(tmp_path: pathlib.Path) -> None:
    """The fixture's <remote name='origin'> is parsed and accessible in manifest.remotes.

    The fixture defines a remote named 'origin' with fetch='https://example.com'.
    After loading, the remote must be present in manifest.remotes.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    assert "origin" in manifest.remotes, (
        f"Expected remote 'origin' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
    )
    remote = manifest.remotes["origin"]
    assert "https://example.com" in remote.fetchUrl, (
        f"Expected 'https://example.com' in remote.fetchUrl but got: {remote.fetchUrl!r}"
    )


@pytest.mark.integration
def test_sample_fixture_default_revision_main(tmp_path: pathlib.Path) -> None:
    """The fixture's <default revision='main'> is parsed into manifest.default.revisionExpr.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.default.revisionExpr == "main", (
        f"Expected default.revisionExpr='main' from fixture but got: {manifest.default.revisionExpr!r}"
    )


@pytest.mark.integration
def test_sample_fixture_default_sync_j(tmp_path: pathlib.Path) -> None:
    """The fixture's <default sync-j='4'> is parsed as integer 4 in manifest.default.sync_j.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.default.sync_j == 4, f"Expected default.sync_j=4 from fixture but got: {manifest.default.sync_j!r}"


@pytest.mark.integration
def test_sample_fixture_projects_loaded(tmp_path: pathlib.Path) -> None:
    """Both projects defined in the fixture are loaded into manifest.projects.

    The fixture defines 'platform/build' (path='build', groups='pdk') and
    'platform/tools' (path='tools', revision='refs/tags/v1.0.0').

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/build" in project_names, (
        f"Expected 'platform/build' in manifest.projects but got: {project_names!r}"
    )
    assert "platform/tools" in project_names, (
        f"Expected 'platform/tools' in manifest.projects but got: {project_names!r}"
    )


@pytest.mark.integration
def test_sample_fixture_project_paths_match(tmp_path: pathlib.Path) -> None:
    """The parsed project relpath values match the 'path' attributes in the fixture.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    assert projects["platform/build"].relpath == "build", (
        f"Expected 'platform/build' relpath='build' but got: {projects['platform/build'].relpath!r}"
    )
    assert projects["platform/tools"].relpath == "tools", (
        f"Expected 'platform/tools' relpath='tools' but got: {projects['platform/tools'].relpath!r}"
    )


@pytest.mark.integration
def test_sample_fixture_platform_tools_pinned_revision(tmp_path: pathlib.Path) -> None:
    """The fixture's 'platform/tools' project uses the explicit revision 'refs/tags/v1.0.0'.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    assert projects["platform/tools"].revisionExpr == "refs/tags/v1.0.0", (
        f"Expected 'platform/tools' revisionExpr='refs/tags/v1.0.0' "
        f"but got: {projects['platform/tools'].revisionExpr!r}"
    )


@pytest.mark.integration
def test_sample_fixture_platform_build_groups(tmp_path: pathlib.Path) -> None:
    """The fixture's 'platform/build' project has the 'pdk' group.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    assert "pdk" in projects["platform/build"].groups, (
        f"Expected 'pdk' in 'platform/build'.groups but got: {projects['platform/build'].groups!r}"
    )


@pytest.mark.integration
def test_sample_fixture_roundtrip_remote_count(tmp_path: pathlib.Path) -> None:
    """Round-trip: the manifest serialized via ToXml preserves the remote count.

    Parses the fixture, calls ToXml(), and verifies the resulting XML document
    contains the correct number of <remote> elements.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    root = doc.documentElement
    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    original_remote_count = len(manifest.remotes)
    assert len(remote_elements) == original_remote_count, (
        f"Expected {original_remote_count} <remote> elements in round-trip XML but found: {len(remote_elements)}"
    )


@pytest.mark.integration
def test_sample_fixture_roundtrip_project_count(tmp_path: pathlib.Path) -> None:
    """Round-trip: the manifest serialized via ToXml preserves the project count.

    Parses the fixture, calls ToXml(), and verifies the resulting XML document
    contains the correct number of <project> elements.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(_SAMPLE_MANIFEST.read_bytes())

    manifest = _load_manifest(repodir, manifest_file)
    original_project_count = len(manifest.projects)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) == original_project_count, (
        f"Expected {original_project_count} <project> elements in round-trip XML but found: {len(project_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_inline_manifest_remote_fetch_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the fetch URL on a <remote> survives parse + serialize.

    Writes an inline manifest, parses it, serializes via ToXml(), and verifies
    that the fetch URL attribute on the remote element is unchanged.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    fetch_url = "https://roundtrip.example.com"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)
    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    root = doc.documentElement
    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    assert len(remote_elements) == 1, (
        f"Expected exactly 1 <remote> element in round-trip XML but found: {len(remote_elements)}"
    )
    assert remote_elements[0].getAttribute("fetch") == fetch_url, (
        f"Expected round-trip fetch='{fetch_url}' but got: {remote_elements[0].getAttribute('fetch')!r}"
    )


@pytest.mark.integration
def test_roundtrip_inline_manifest_project_name_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the project name survives parse + serialize.

    Writes an inline manifest with one project, parses it, serializes via
    ToXml(), and verifies the project name attribute is preserved.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    project_name = "platform/roundtrip"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{project_name}" path="roundtrip" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)
    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) == 1, (
        f"Expected exactly 1 <project> element in round-trip XML but found: {len(project_elements)}"
    )
    assert project_elements[0].getAttribute("name") == project_name, (
        f"Expected round-trip project name='{project_name}' but got: {project_elements[0].getAttribute('name')!r}"
    )


@pytest.mark.integration
def test_roundtrip_default_revision_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the <default> revision survives parse + serialize.

    Writes an inline manifest, parses it, serializes via ToXml(), and verifies
    the default revision attribute is present in the resulting XML.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    revision = "refs/heads/feature"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        f'  <default revision="{revision}" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)
    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    root = doc.documentElement
    default_elements = [n for n in root.childNodes if n.nodeName == "default"]
    assert len(default_elements) == 1, (
        f"Expected exactly 1 <default> element in round-trip XML but found: {len(default_elements)}"
    )
    assert default_elements[0].getAttribute("revision") == revision, (
        f"Expected round-trip default revision='{revision}' but got: {default_elements[0].getAttribute('revision')!r}"
    )
