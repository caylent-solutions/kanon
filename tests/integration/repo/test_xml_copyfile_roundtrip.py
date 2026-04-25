"""Integration tests for <copyfile> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <copyfile>
element nested inside a <project>, verify the parsed model reflects the
configured src and dest attributes, and confirm round-trip serialization
via ToXml preserves the expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <copyfile> parses without error and the parsed
model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_project_roundtrip.py
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


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name of the project to retrieve.

    Returns:
        The Project object with the given name.
    """
    projects_by_name = {p.name: p for p in manifest.projects}
    return projects_by_name[project_name]


# ---------------------------------------------------------------------------
# Fixture XML content for <copyfile> round-trip tests
# ---------------------------------------------------------------------------

_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core">\n'
    '    <copyfile src="VERSION" dest="out/VERSION" />\n'
    "  </project>\n"
    "</manifest>\n"
)

_FIXTURE_MULTI_COPYFILE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core">\n'
    '    <copyfile src="VERSION" dest="out/VERSION" />\n'
    '    <copyfile src="LICENSE" dest="THIRD_PARTY/LICENSE" />\n'
    "  </project>\n"
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Real parse + model verification
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_manifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest containing a <copyfile> element parses into a valid XmlManifest.

    Writes the fixture XML to a real .repo directory structure and loads it.
    No exception must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading copyfile manifest"


@pytest.mark.integration
def test_copyfile_project_is_visible_in_manifest(tmp_path: pathlib.Path) -> None:
    """After parsing, the project containing the <copyfile> is visible in manifest.projects.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/core" in project_names, (
        f"Expected 'platform/core' in manifest.projects after parsing but got: {project_names!r}"
    )


@pytest.mark.integration
def test_copyfile_appears_on_parsed_project(tmp_path: pathlib.Path) -> None:
    """After parsing, the <copyfile> element is accessible on the project's copyfiles list.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    assert len(project.copyfiles) == 1, (
        f"Expected exactly 1 copyfile on platform/core but got: {len(project.copyfiles)}"
    )


@pytest.mark.integration
def test_copyfile_src_matches_xml_attribute(tmp_path: pathlib.Path) -> None:
    """The parsed copyfile model's src attribute equals the src attribute in the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    copyfile = project.copyfiles[0]
    assert copyfile.src == "VERSION", (
        f"Expected copyfile.src='VERSION' matching XML attribute but got: {copyfile.src!r}"
    )


@pytest.mark.integration
def test_copyfile_dest_matches_xml_attribute(tmp_path: pathlib.Path) -> None:
    """The parsed copyfile model's dest attribute equals the dest attribute in the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    copyfile = project.copyfiles[0]
    assert copyfile.dest == "out/VERSION", (
        f"Expected copyfile.dest='out/VERSION' matching XML attribute but got: {copyfile.dest!r}"
    )


@pytest.mark.integration
def test_copyfile_model_matches_xml_fully(tmp_path: pathlib.Path) -> None:
    """The parsed copyfile model matches both src and dest from the XML completely.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    assert len(project.copyfiles) == 1, f"Expected 1 copyfile but got: {len(project.copyfiles)}"
    copyfile = project.copyfiles[0]
    assert copyfile.src == "VERSION", f"Expected copyfile.src='VERSION' but got: {copyfile.src!r}"
    assert copyfile.dest == "out/VERSION", f"Expected copyfile.dest='out/VERSION' but got: {copyfile.dest!r}"


# ---------------------------------------------------------------------------
# Round-trip: parse + ToXml preserves structural elements
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_copyfile_project_present_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains the <project> that owns the <copyfile>.

    Parses the fixture, calls ToXml(), and verifies the resulting XML document
    contains the expected <project> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) >= 1, (
        f"Expected at least 1 <project> element in round-trip XML but found: {len(project_elements)}"
    )
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_copyfile_element_present_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <copyfile> element as child of the project.

    Parses the fixture, calls ToXml(), and verifies the resulting XML document
    contains a <copyfile> element nested inside the owning <project>.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, "Expected <project name='platform/core'> in round-trip XML but not found"

    core_element = core_elements[0]
    copyfile_children = [n for n in core_element.childNodes if n.nodeName == "copyfile"]
    assert len(copyfile_children) == 1, (
        f"Expected 1 <copyfile> child on platform/core in round-trip XML but found: {len(copyfile_children)}"
    )


@pytest.mark.integration
def test_roundtrip_copyfile_src_preserved_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the src attribute of <copyfile> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    assert "VERSION" in xml_text, "Expected 'VERSION' (copyfile src) to appear in round-trip XML but it was absent"


@pytest.mark.integration
def test_roundtrip_copyfile_dest_preserved_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the dest attribute of <copyfile> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    assert "out/VERSION" in xml_text, (
        "Expected 'out/VERSION' (copyfile dest) to appear in round-trip XML but it was absent"
    )


@pytest.mark.integration
def test_roundtrip_multiple_copyfiles_all_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: multiple <copyfile> elements are all preserved in ToXml output.

    Parses a manifest with two <copyfile> children, calls ToXml(), and verifies
    both are present in the resulting XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_MULTI_COPYFILE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, "Expected <project name='platform/core'> in round-trip XML but not found"

    core_element = core_elements[0]
    copyfile_children = [n for n in core_element.childNodes if n.nodeName == "copyfile"]
    assert len(copyfile_children) == 2, (
        f"Expected 2 <copyfile> children on platform/core in round-trip XML but found: {len(copyfile_children)}"
    )


@pytest.mark.integration
def test_roundtrip_multiple_copyfiles_src_attributes_present(tmp_path: pathlib.Path) -> None:
    """Round-trip: src values from multiple <copyfile> elements appear in serialized XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_MULTI_COPYFILE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    for expected in ("VERSION", "LICENSE"):
        assert expected in xml_text, (
            f"Expected '{expected}' (copyfile src) to appear in round-trip XML but it was absent"
        )


@pytest.mark.integration
def test_inline_copyfile_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """Inline scenario: manifest with <copyfile> is parsed and model matches expectations.

    Writes a manifest directly to tmp_path, parses, and verifies the parsed
    model reflects all copyfile src and dest attributes accurately.

    AC-FUNC-001, AC-FINAL-010
    """
    inline_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://inline.example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="vendor/sdk">\n'
        '    <copyfile src="include/sdk.h" dest="output/include/sdk.h" />\n'
        "  </project>\n"
        "</manifest>\n"
    )

    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, inline_xml)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "vendor/sdk")
    assert len(project.copyfiles) == 1, (
        f"Expected 1 copyfile on vendor/sdk after parse but got: {len(project.copyfiles)}"
    )
    copyfile = project.copyfiles[0]
    assert copyfile.src == "include/sdk.h", f"Expected copyfile.src='include/sdk.h' but got: {copyfile.src!r}"
    assert copyfile.dest == "output/include/sdk.h", (
        f"Expected copyfile.dest='output/include/sdk.h' but got: {copyfile.dest!r}"
    )
