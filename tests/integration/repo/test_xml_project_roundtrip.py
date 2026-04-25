"""Integration tests for <project> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <project>
element, verify the parsed model reflects the project configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <project> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_remote_roundtrip.py
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


def _build_project_manifest(
    project_name: str = "platform/core",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_project_attrs: str = "",
) -> str:
    """Build a manifest XML string with a single <project> element.

    Args:
        project_name: The name attribute for the <project> element.
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_revision: The revision on the <default> element.
        extra_project_attrs: Additional attributes string for the <project> element.

    Returns:
        Full XML string for the manifest.
    """
    project_attrs = f'name="{project_name}"'
    if extra_project_attrs:
        project_attrs = f"{project_attrs} {extra_project_attrs}"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <project {project_attrs} />\n"
        "</manifest>\n"
    )


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
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_project_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <project> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(project_name="platform/core")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_project_is_registered_in_manifest_projects(tmp_path: pathlib.Path) -> None:
    """After parsing, the named project is registered in manifest.projects.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(project_name="platform/core")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "platform/core" in project_names, (
        f"Expected 'platform/core' in manifest.projects after parsing but not found. Got: {project_names!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_preserves_project_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <project> element with the correct name.

    Parses a manifest with a <project> element, calls ToXml(), and verifies
    the resulting XML document contains at least one <project> element with
    the expected name attribute.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(project_name="platform/core")
    manifest_file = _write_manifest(repodir, xml_content)

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
def test_project_roundtrip_with_explicit_path_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: an explicit path attribute on <project> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name="platform/core",
        extra_project_attrs='path="src/core"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    assert core_elements[0].getAttribute("path") == "src/core", (
        f"Expected path='src/core' in round-trip XML but got: {core_elements[0].getAttribute('path')!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_with_revision_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: a revision attribute on <project> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name="platform/core",
        extra_project_attrs='revision="refs/heads/stable"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    assert core_elements[0].getAttribute("revision") == "refs/heads/stable", (
        f"Expected revision='refs/heads/stable' in round-trip XML but got: "
        f"{core_elements[0].getAttribute('revision')!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_with_groups_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: an explicit groups attribute on <project> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name="platform/core",
        extra_project_attrs='groups="platform,infra"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    groups_str = core_elements[0].getAttribute("groups")
    groups = [g.strip() for g in groups_str.split(",") if g.strip()]
    assert "platform" in groups, f"Expected 'platform' in round-trip groups attribute but got: {groups_str!r}"
    assert "infra" in groups, f"Expected 'infra' in round-trip groups attribute but got: {groups_str!r}"


@pytest.mark.integration
def test_project_roundtrip_name_defaults_to_path_when_path_omitted(tmp_path: pathlib.Path) -> None:
    """Round-trip: when path is omitted on <project>, ToXml omits the path attribute.

    When path equals name, the serializer does not write a redundant path attribute.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(project_name="platform/core")
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    path_attr = core_elements[0].getAttribute("path")
    assert path_attr == "", f"Expected path attribute to be absent when path==name in round-trip but got: {path_attr!r}"


@pytest.mark.integration
def test_project_roundtrip_multiple_projects_all_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: multiple <project> elements are all preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" />\n'
        '  <project name="platform/tools" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    project_names = {e.getAttribute("name") for e in project_elements}
    assert "platform/core" in project_names, (
        f"Expected 'platform/core' in round-trip project names but found: {project_names!r}"
    )
    assert "platform/tools" in project_names, (
        f"Expected 'platform/tools' in round-trip project names but found: {project_names!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model project matches what was written to disk.

    Writes a manifest with a specific project name, path, and revision, parses it,
    and asserts that the parsed model attributes match the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    project_name = "caylent/platform"
    project_path = "src/platform"
    revision = "refs/heads/release"

    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name=project_name,
        extra_project_attrs=f'path="{project_path}" revision="{revision}"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    project = _get_project(manifest, project_name)
    assert project.name == project_name, f"Expected project.name='{project_name}' but got: {project.name!r}"
    assert project.relpath == project_path, f"Expected project.relpath='{project_path}' but got: {project.relpath!r}"
    assert project.revisionExpr == revision, (
        f"Expected project.revisionExpr='{revision}' but got: {project.revisionExpr!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_sync_c_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: sync-c='true' on <project> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name="platform/core",
        extra_project_attrs='sync-c="true"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    assert core_elements[0].getAttribute("sync-c") == "true", (
        f"Expected sync-c='true' in round-trip XML but got: {core_elements[0].getAttribute('sync-c')!r}"
    )


@pytest.mark.integration
def test_project_roundtrip_clone_depth_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: clone-depth='3' on <project> appears in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_project_manifest(
        project_name="platform/core",
        extra_project_attrs='clone-depth="3"',
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    core_elements = [e for e in project_elements if e.getAttribute("name") == "platform/core"]
    assert len(core_elements) == 1, (
        f"Expected exactly 1 <project name='platform/core'> in round-trip XML but found: {len(core_elements)}"
    )
    assert core_elements[0].getAttribute("clone-depth") == "3", (
        f"Expected clone-depth='3' in round-trip XML but got: {core_elements[0].getAttribute('clone-depth')!r}"
    )
