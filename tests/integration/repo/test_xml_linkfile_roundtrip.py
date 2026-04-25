"""Integration tests for <linkfile> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <linkfile>
element nested inside a <project>, verify the parsed model reflects the
configured src, dest, and exclude attributes, and confirm round-trip
serialization via ToXml preserves the expected structural elements.

The <linkfile> element creates a symlink from the project worktree into
the workspace. Differences from <copyfile>:
- src may be "." (link the entire worktree directory)
- dest may be an absolute path
- An optional exclude attribute provides comma-separated child names to
  omit when linking a directory source

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <linkfile> parses without error and the parsed
model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_copyfile_roundtrip.py
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
# Fixture XML content for <linkfile> round-trip tests
# ---------------------------------------------------------------------------

_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core">\n'
    '    <linkfile src="scripts" dest="tools/scripts" />\n'
    "  </project>\n"
    "</manifest>\n"
)

_FIXTURE_MULTI_LINKFILE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core">\n'
    '    <linkfile src="scripts" dest="tools/scripts" />\n'
    '    <linkfile src="include" dest="sdk/include" />\n'
    "  </project>\n"
    "</manifest>\n"
)

_FIXTURE_LINKFILE_WITH_EXCLUDE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core">\n'
    '    <linkfile src="tools" dest="workspace/tools" exclude=".git,build" />\n'
    "  </project>\n"
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Real parse + model verification
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_manifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest containing a <linkfile> element parses into a valid XmlManifest.

    Writes the fixture XML to a real .repo directory structure and loads it.
    No exception must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading linkfile manifest"


@pytest.mark.integration
def test_linkfile_project_is_visible_in_manifest(tmp_path: pathlib.Path) -> None:
    """After parsing, the project containing the <linkfile> is visible in manifest.projects.

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
def test_linkfile_appears_on_parsed_project(tmp_path: pathlib.Path) -> None:
    """After parsing, the <linkfile> element is accessible on the project's linkfiles list.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    assert len(project.linkfiles) == 1, (
        f"Expected exactly 1 linkfile on platform/core but got: {len(project.linkfiles)}"
    )


@pytest.mark.integration
def test_linkfile_src_matches_xml_attribute(tmp_path: pathlib.Path) -> None:
    """The parsed linkfile model's src attribute equals the src attribute in the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    linkfile = project.linkfiles[0]
    assert linkfile.src == "scripts", (
        f"Expected linkfile.src='scripts' matching XML attribute but got: {linkfile.src!r}"
    )


@pytest.mark.integration
def test_linkfile_dest_matches_xml_attribute(tmp_path: pathlib.Path) -> None:
    """The parsed linkfile model's dest attribute equals the dest attribute in the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    linkfile = project.linkfiles[0]
    assert linkfile.dest == "tools/scripts", (
        f"Expected linkfile.dest='tools/scripts' matching XML attribute but got: {linkfile.dest!r}"
    )


@pytest.mark.integration
def test_linkfile_model_matches_xml_fully(tmp_path: pathlib.Path) -> None:
    """The parsed linkfile model matches both src and dest from the XML completely.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    assert len(project.linkfiles) == 1, f"Expected 1 linkfile but got: {len(project.linkfiles)}"
    linkfile = project.linkfiles[0]
    assert linkfile.src == "scripts", f"Expected linkfile.src='scripts' but got: {linkfile.src!r}"
    assert linkfile.dest == "tools/scripts", f"Expected linkfile.dest='tools/scripts' but got: {linkfile.dest!r}"


@pytest.mark.integration
def test_linkfile_without_exclude_has_empty_frozenset(tmp_path: pathlib.Path) -> None:
    """A parsed <linkfile> with no exclude attribute has an empty frozenset for exclude.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    linkfile = project.linkfiles[0]
    assert linkfile.exclude == frozenset(), (
        f"Expected linkfile.exclude=frozenset() when no exclude attribute but got: {linkfile.exclude!r}"
    )


@pytest.mark.integration
def test_linkfile_with_exclude_stores_correct_members(tmp_path: pathlib.Path) -> None:
    """A parsed <linkfile> with exclude attribute stores each member in the frozenset.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_LINKFILE_WITH_EXCLUDE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    linkfile = project.linkfiles[0]
    assert ".git" in linkfile.exclude, f"Expected '.git' in linkfile.exclude but got: {linkfile.exclude!r}"
    assert "build" in linkfile.exclude, f"Expected 'build' in linkfile.exclude but got: {linkfile.exclude!r}"


# ---------------------------------------------------------------------------
# Round-trip: parse + ToXml preserves structural elements
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_linkfile_project_present_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains the <project> that owns the <linkfile>.

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
def test_roundtrip_linkfile_element_present_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <linkfile> element as child of the project.

    Parses the fixture, calls ToXml(), and verifies the resulting XML document
    contains a <linkfile> element nested inside the owning <project>.

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
    linkfile_children = [n for n in core_element.childNodes if n.nodeName == "linkfile"]
    assert len(linkfile_children) == 1, (
        f"Expected 1 <linkfile> child on platform/core in round-trip XML but found: {len(linkfile_children)}"
    )


@pytest.mark.integration
def test_roundtrip_linkfile_src_preserved_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the src attribute of <linkfile> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    assert "scripts" in xml_text, "Expected 'scripts' (linkfile src) to appear in round-trip XML but it was absent"


@pytest.mark.integration
def test_roundtrip_linkfile_dest_preserved_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the dest attribute of <linkfile> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    assert "tools/scripts" in xml_text, (
        "Expected 'tools/scripts' (linkfile dest) to appear in round-trip XML but it was absent"
    )


@pytest.mark.integration
def test_roundtrip_multiple_linkfiles_all_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: multiple <linkfile> elements are all preserved in ToXml output.

    Parses a manifest with two <linkfile> children, calls ToXml(), and verifies
    both are present in the resulting XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_MULTI_LINKFILE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, "Expected <project name='platform/core'> in round-trip XML but not found"

    core_element = core_elements[0]
    linkfile_children = [n for n in core_element.childNodes if n.nodeName == "linkfile"]
    assert len(linkfile_children) == 2, (
        f"Expected 2 <linkfile> children on platform/core in round-trip XML but found: {len(linkfile_children)}"
    )


@pytest.mark.integration
def test_roundtrip_multiple_linkfiles_src_attributes_present(tmp_path: pathlib.Path) -> None:
    """Round-trip: src values from multiple <linkfile> elements appear in serialized XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _FIXTURE_MULTI_LINKFILE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    for expected in ("scripts", "include"):
        assert expected in xml_text, (
            f"Expected '{expected}' (linkfile src) to appear in round-trip XML but it was absent"
        )


@pytest.mark.integration
def test_inline_linkfile_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """Inline scenario: manifest with <linkfile> is parsed and model matches expectations.

    Writes a manifest directly to tmp_path, parses, and verifies the parsed
    model reflects all linkfile src and dest attributes accurately.

    AC-FUNC-001, AC-FINAL-010
    """
    inline_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://inline.example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="vendor/sdk">\n'
        '    <linkfile src="include" dest="output/include" />\n'
        "  </project>\n"
        "</manifest>\n"
    )

    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, inline_xml)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "vendor/sdk")
    assert len(project.linkfiles) == 1, (
        f"Expected 1 linkfile on vendor/sdk after parse but got: {len(project.linkfiles)}"
    )
    linkfile = project.linkfiles[0]
    assert linkfile.src == "include", f"Expected linkfile.src='include' but got: {linkfile.src!r}"
    assert linkfile.dest == "output/include", f"Expected linkfile.dest='output/include' but got: {linkfile.dest!r}"


@pytest.mark.integration
def test_linkfile_dot_src_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """A <linkfile src='.'> parses correctly and stores src as '.'.

    The src='.' form creates a stable link to the whole project worktree
    directory. This is a documented special case per the linkfile spec.

    AC-FUNC-001, AC-FINAL-010
    """
    dot_src_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        '    <linkfile src="." dest="link/platform-core" />\n'
        "  </project>\n"
        "</manifest>\n"
    )

    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, dot_src_xml)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, "platform/core")
    assert len(project.linkfiles) == 1, (
        f"Expected 1 linkfile on platform/core after parse but got: {len(project.linkfiles)}"
    )
    linkfile = project.linkfiles[0]
    assert linkfile.src == ".", f"Expected linkfile.src='.' but got: {linkfile.src!r}"
    assert linkfile.dest == "link/platform-core", (
        f"Expected linkfile.dest='link/platform-core' but got: {linkfile.dest!r}"
    )
