"""Integration tests for <remove-project> round-trip parsing.

Tests parse a real manifest XML file from disk containing <remove-project>
elements, verify the parsed model reflects the removals applied, and confirm
round-trip serialization via ToXml preserves the expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <remove-project> parses without error and the
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


# ---------------------------------------------------------------------------
# Fixture XML content for remove-project round-trip tests
# ---------------------------------------------------------------------------

_REMOVE_PROJECT_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/build" path="build" groups="pdk" />\n'
    '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
    '  <project name="vendor/lib" path="lib" />\n'
    '  <remove-project name="platform/tools" />\n'
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Real parse + model verification
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_remove_project_manifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest containing <remove-project> elements parses into a valid XmlManifest.

    Writes the fixture XML to a real .repo directory structure and loads it.
    No exception must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading remove-project manifest"


@pytest.mark.integration
def test_remove_project_removed_project_absent_from_model(tmp_path: pathlib.Path) -> None:
    """After parsing, the removed project is absent from manifest.projects.

    The fixture removes platform/tools. After parsing, platform/tools must not
    appear in the project list.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/tools" not in project_names, (
        f"Expected 'platform/tools' to be absent after remove-project but got: {project_names!r}"
    )


@pytest.mark.integration
def test_remove_project_non_removed_projects_present_in_model(tmp_path: pathlib.Path) -> None:
    """After parsing, projects not targeted by <remove-project> remain in the model.

    The fixture only removes platform/tools. platform/build and vendor/lib must
    still appear in manifest.projects.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/build" in project_names, (
        f"Expected 'platform/build' to be present after remove-project (not targeted) but got: {project_names!r}"
    )
    assert "vendor/lib" in project_names, (
        f"Expected 'vendor/lib' to be present after remove-project (not targeted) but got: {project_names!r}"
    )


@pytest.mark.integration
def test_remove_project_project_count_reduced(tmp_path: pathlib.Path) -> None:
    """After parsing, the project count is reduced by the number of removed projects.

    The fixture has 3 projects and removes 1. The resulting manifest must have 2.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert len(manifest.projects) == 2, f"Expected 2 projects after removing 1 from 3 but got: {len(manifest.projects)}"


@pytest.mark.integration
def test_remove_project_non_removed_project_attributes_preserved(tmp_path: pathlib.Path) -> None:
    """Remaining projects have their original attributes after a sibling is removed.

    platform/build originally had group 'pdk'. After remove-project removes
    platform/tools, platform/build must still carry the 'pdk' group.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    build = projects["platform/build"]
    assert "pdk" in build.groups, (
        f"Expected 'pdk' group preserved on platform/build after removing sibling but got: {build.groups!r}"
    )


# ---------------------------------------------------------------------------
# Round-trip: parse + ToXml preserves structural elements of remaining projects
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_remove_project_project_count_in_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the serialized XML contains the correct number of <project> elements.

    <remove-project> removes a project from the model. The serialized output
    must contain only the projects that were not removed.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    expected_count = len(manifest.projects)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) == expected_count, (
        f"Expected {expected_count} <project> elements in round-trip XML but found: {len(project_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_remove_project_remote_count_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the remote count is preserved after parse + serialize.

    Removing projects does not affect remote declarations.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    original_remote_count = len(manifest.remotes)

    doc = manifest.ToXml()
    root = doc.documentElement
    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    assert len(remote_elements) == original_remote_count, (
        f"Expected {original_remote_count} <remote> elements in round-trip XML but found: {len(remote_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_remove_project_remaining_project_names_in_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: remaining project names appear in the serialized XML.

    Parses the fixture, calls ToXml(), and verifies that the expected surviving
    project names appear in the resulting XML document.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    for project_name in ("platform/build", "vendor/lib"):
        assert project_name in xml_text, (
            f"Expected surviving project name '{project_name}' in round-trip XML but it was absent"
        )


@pytest.mark.integration
def test_roundtrip_remove_project_removed_name_absent_from_xml(tmp_path: pathlib.Path) -> None:
    """Round-trip: the removed project name does not appear in the serialized XML.

    After parse + serialize, platform/tools (which was removed) must not appear
    in the XML output as a project element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _REMOVE_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_names_in_xml = [n.getAttribute("name") for n in root.childNodes if n.nodeName == "project"]
    assert "platform/tools" not in project_names_in_xml, (
        f"Expected 'platform/tools' to be absent from round-trip XML project elements but found: {project_names_in_xml!r}"
    )


@pytest.mark.integration
def test_inline_remove_project_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """Inline manifest with <remove-project>: parsed model matches expectations.

    Writes an inline manifest directly to tmp_path, parses it, and verifies
    the parsed model reflects all applied removals.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    fetch_url = "https://inline.example.com"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        '  <project name="vendor/lib" path="lib" />\n'
        '  <project name="platform/extras" path="extras" />\n'
        '  <remove-project name="platform/extras" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/extras" not in project_names, (
        f"Expected 'platform/extras' to be removed but got: {project_names!r}"
    )
    assert "platform/core" in project_names, (
        f"Expected 'platform/core' to remain after remove-project but got: {project_names!r}"
    )
    assert "vendor/lib" in project_names, (
        f"Expected 'vendor/lib' to remain after remove-project but got: {project_names!r}"
    )


@pytest.mark.integration
def test_remove_project_optional_true_parse_succeeds_on_absent_project(tmp_path: pathlib.Path) -> None:
    """A manifest with optional <remove-project> targeting an absent project parses cleanly.

    When optional="true" is set, a missing project is silently accepted. The
    remaining projects must be intact.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        '  <remove-project name="platform/absent" optional="true" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/core" in project_names, (
        f"Expected 'platform/core' to remain when optional remove-project silently skips absent project but got: {project_names!r}"
    )
