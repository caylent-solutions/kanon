"""Integration tests for <include> round-trip parsing.

Tests parse a real manifest XML file from disk containing an <include>
element, verify the parsed model reflects the included projects and applied
attributes, and confirm round-trip serialization via ToXml preserves the
expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <include> parses without error and the parsed
model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_extend_project_roundtrip.py
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


def _write_included_manifest(repodir: pathlib.Path, filename: str, xml_content: str) -> pathlib.Path:
    """Write xml_content to a named manifest file inside the manifests directory.

    The manifests directory is the include_root for XmlManifest. Included
    manifests must reside there to be found by os.path.join(include_root, name).

    Args:
        repodir: The .repo directory.
        filename: Filename (no path separators) for the included manifest.
        xml_content: Full XML content for the included manifest file.

    Returns:
        Absolute path to the written included manifest file.
    """
    included_file = repodir / "manifests" / filename
    included_file.write_text(xml_content, encoding="utf-8")
    return included_file


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
# Fixture XML content for <include> round-trip tests
# ---------------------------------------------------------------------------

_INCLUDED_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/build" path="build" groups="pdk" />\n'
    '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
    "</manifest>\n"
)

_PRIMARY_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <include name="sub.xml" groups="extra,release" />\n'
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Real parse + model verification
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_include_manifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest containing an <include> element parses into a valid XmlManifest.

    Writes the fixture XML to a real .repo directory structure and loads it.
    No exception must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading include manifest"


@pytest.mark.integration
def test_include_projects_visible_in_parsed_manifest(tmp_path: pathlib.Path) -> None:
    """After parsing, projects from the included manifest are visible in manifest.projects.

    The fixture includes a manifest with platform/build and platform/tools.
    Both must appear in the parent manifest's project list after loading.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/build" in project_names, (
        f"Expected 'platform/build' from included manifest to be visible but got: {project_names!r}"
    )
    assert "platform/tools" in project_names, (
        f"Expected 'platform/tools' from included manifest to be visible but got: {project_names!r}"
    )


@pytest.mark.integration
def test_include_groups_applied_to_all_included_projects(tmp_path: pathlib.Path) -> None:
    """After parsing, groups from <include groups="extra,release"> are on all included projects.

    The fixture uses <include name="sub.xml" groups="extra,release">. After
    parsing, both platform/build and platform/tools must have 'extra' and
    'release' in their groups lists.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    for proj_name in ("platform/build", "platform/tools"):
        proj = projects[proj_name]
        assert "extra" in proj.groups, (
            f"Expected group 'extra' on '{proj_name}' from <include groups='extra,release'> but got: {proj.groups!r}"
        )
        assert "release" in proj.groups, (
            f"Expected group 'release' on '{proj_name}' from <include groups='extra,release'> but got: {proj.groups!r}"
        )


@pytest.mark.integration
def test_include_original_groups_preserved_on_included_projects(tmp_path: pathlib.Path) -> None:
    """Original groups from included projects are preserved alongside <include> groups.

    platform/build declares groups="pdk". After <include groups="extra,release">,
    the 'pdk' group must still be present.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    build = projects["platform/build"]
    assert "pdk" in build.groups, (
        f"Expected original group 'pdk' to be preserved on platform/build alongside "
        f"<include> groups but got: {build.groups!r}"
    )


@pytest.mark.integration
def test_include_project_own_revision_preserved(tmp_path: pathlib.Path) -> None:
    """A project with its own revision retains it after include without revision override.

    platform/tools declares revision="refs/tags/v1.0.0" in the included
    manifest. The primary manifest does not specify <include revision="...">.
    After loading, platform/tools must have revisionExpr="refs/tags/v1.0.0".

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    tools = projects["platform/tools"]
    assert tools.revisionExpr == "refs/tags/v1.0.0", (
        f"Expected platform/tools to keep its own revisionExpr='refs/tags/v1.0.0' "
        f"after include but got: {tools.revisionExpr!r}"
    )


@pytest.mark.integration
def test_include_revision_override_applies_to_project_without_own_revision(tmp_path: pathlib.Path) -> None:
    """<include revision="..."> is applied to projects in included manifest that have no revision.

    Writes a custom included manifest with a project that has no explicit
    revision, then includes it with revision="refs/tags/v4.0.0". The project
    must receive that revision.

    AC-FUNC-001, AC-FINAL-010
    """
    included_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default remote="origin" />\n'
        '  <project name="platform/norev" path="norev" />\n'
        "</manifest>\n"
    )
    primary_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="sub.xml" revision="refs/tags/v4.0.0" />\n'
        "</manifest>\n"
    )

    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", included_xml)
    manifest_file = _write_manifest(repodir, primary_xml)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    norev = projects["platform/norev"]
    assert norev.revisionExpr == "refs/tags/v4.0.0", (
        f"Expected revisionExpr='refs/tags/v4.0.0' from <include revision='...'> applied to "
        f"project with no own revision but got: {norev.revisionExpr!r}"
    )


# ---------------------------------------------------------------------------
# Round-trip: parse + ToXml preserves structural elements
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_include_project_count_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the project count is preserved after parse + serialize.

    <include> pulls projects from the included manifest into the parent. After
    serialization, the resulting XML must contain the same number of <project>
    elements as were loaded via the include.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    original_project_count = len(manifest.projects)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) == original_project_count, (
        f"Expected {original_project_count} <project> elements in round-trip XML but found: {len(project_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_include_project_names_in_serialized_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the project names from the included manifest appear in serialized XML.

    Parses the fixture, calls ToXml(), and verifies the expected project names
    appear in the resulting XML document.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", _INCLUDED_FIXTURE_XML)
    manifest_file = _write_manifest(repodir, _PRIMARY_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    for project_name in ("platform/build", "platform/tools"):
        assert project_name in xml_text, f"Expected project name '{project_name}' in round-trip XML but it was absent"


@pytest.mark.integration
def test_inline_include_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """Inline scenario: manifest with <include> is parsed and model matches expectations.

    Writes manifests directly to tmp_path, parses, and verifies the parsed
    model reflects all applied include groups and project visibility.

    AC-FUNC-001, AC-FINAL-010
    """
    included_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://inline.example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        '  <project name="vendor/lib" path="lib" revision="refs/tags/v0.9.0" />\n'
        "</manifest>\n"
    )
    primary_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="sub.xml" groups="sdk,dev" />\n'
        "</manifest>\n"
    )

    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, "sub.xml", included_xml)
    manifest_file = _write_manifest(repodir, primary_xml)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}

    core = projects["platform/core"]
    assert "sdk" in core.groups, (
        f"Expected 'sdk' in platform/core.groups after <include groups='sdk,dev'> but got: {core.groups!r}"
    )
    assert "dev" in core.groups, (
        f"Expected 'dev' in platform/core.groups after <include groups='sdk,dev'> but got: {core.groups!r}"
    )

    lib = projects["vendor/lib"]
    assert lib.revisionExpr == "refs/tags/v0.9.0", (
        f"Expected vendor/lib revisionExpr='refs/tags/v0.9.0' (project's own) after include but got: {lib.revisionExpr!r}"
    )
    assert "sdk" in lib.groups, (
        f"Expected 'sdk' in vendor/lib.groups after <include groups='sdk,dev'> but got: {lib.groups!r}"
    )
