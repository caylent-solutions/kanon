"""Integration tests for <annotation> round-trip parsing.

Tests parse a real manifest XML file from disk containing <annotation> elements
inside <project> and <remote> parent elements, verify the parsed model reflects
the annotation attributes, and confirm round-trip serialization via ToXml
preserves the expected structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <annotation> parses without error and the parsed
model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.project import Annotation


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


def _build_manifest_with_project_annotation(
    annotation_name: str,
    annotation_value: str,
    annotation_keep: str = "true",
    project_name: str = "platform/tools",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <project> containing one <annotation> child.

    Args:
        annotation_name: The name attribute of the <annotation>.
        annotation_value: The value attribute of the <annotation>.
        annotation_keep: The keep attribute of the <annotation>.
        project_name: The name attribute of the <project>.
        remote_name: The name attribute of the <remote>.
        fetch_url: The fetch attribute of the <remote>.
        default_revision: The revision on the <default>.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <project name="{project_name}">\n'
        f'    <annotation name="{annotation_name}" value="{annotation_value}" keep="{annotation_keep}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project matching project_name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The project name to look up.

    Returns:
        The matching Project object.

    Raises:
        AssertionError: If no project with that name is found.
    """
    projects = {p.name: p for p in manifest.projects}
    assert project_name in projects, (
        f"Expected project '{project_name}' in manifest but found: {list(projects.keys())!r}"
    )
    return projects[project_name]


def _get_remote(manifest: manifest_xml.XmlManifest, remote_name: str):
    """Return the remote matching remote_name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        remote_name: The remote name to look up.

    Returns:
        The matching _XmlRemote object.

    Raises:
        AssertionError: If no remote with that name is found.
    """
    remotes = manifest.remotes
    assert remote_name in remotes, f"Expected remote '{remote_name}' in manifest but found: {list(remotes.keys())!r}"
    return remotes[remote_name]


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_annotation_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with a project annotated by <annotation> parses without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_project_annotation(
        annotation_name="team",
        annotation_value="platform-eng",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_annotation_name_and_value_preserved_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, annotation.name and annotation.value match the XML attributes.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_project_annotation(
        annotation_name="team",
        annotation_value="platform-eng",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    project = _get_project(manifest, "platform/tools")

    assert len(project.annotations) == 1, f"Expected 1 annotation on project but got: {len(project.annotations)}"
    assert project.annotations[0].name == "team", (
        f"Expected annotation.name='team' but got: {project.annotations[0].name!r}"
    )
    assert project.annotations[0].value == "platform-eng", (
        f"Expected annotation.value='platform-eng' but got: {project.annotations[0].value!r}"
    )


@pytest.mark.integration
def test_annotation_keep_true_preserved_in_roundtrip(tmp_path: pathlib.Path) -> None:
    """An annotation with keep='true' appears in the ToXml round-trip output.

    When keep='true', the annotation element is emitted in the round-trip XML.
    When keep='false', it is not emitted.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_project_annotation(
        annotation_name="tier",
        annotation_value="gold",
        annotation_keep="true",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_nodes = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_nodes) >= 1, (
        f"Expected at least 1 <project> element in round-trip XML but found: {len(project_nodes)}"
    )

    annotation_nodes_found = []
    for project_node in project_nodes:
        for child in project_node.childNodes:
            if child.nodeName == "annotation":
                annotation_nodes_found.append(child)

    assert len(annotation_nodes_found) == 1, (
        f"Expected 1 <annotation> element in round-trip XML for keep='true' but found: {len(annotation_nodes_found)}"
    )
    ann_node = annotation_nodes_found[0]
    assert ann_node.getAttribute("name") == "tier", (
        f"Expected annotation name='tier' in round-trip but got: {ann_node.getAttribute('name')!r}"
    )
    assert ann_node.getAttribute("value") == "gold", (
        f"Expected annotation value='gold' in round-trip but got: {ann_node.getAttribute('value')!r}"
    )


@pytest.mark.integration
def test_annotation_keep_false_excluded_from_roundtrip(tmp_path: pathlib.Path) -> None:
    """An annotation with keep='false' is excluded from the ToXml round-trip output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_project_annotation(
        annotation_name="tier",
        annotation_value="bronze",
        annotation_keep="false",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    project = _get_project(manifest, "platform/tools")

    assert len(project.annotations) == 1, f"Expected 1 annotation in parsed model but got: {len(project.annotations)}"
    assert project.annotations[0].keep == "false", (
        f"Expected keep='false' in parsed model but got: {project.annotations[0].keep!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement

    annotation_nodes_found = []
    for project_node in [n for n in root.childNodes if n.nodeName == "project"]:
        for child in project_node.childNodes:
            if child.nodeName == "annotation":
                annotation_nodes_found.append(child)

    assert len(annotation_nodes_found) == 0, (
        f"Expected 0 <annotation> elements in round-trip XML for keep='false' but found: {len(annotation_nodes_found)}"
    )


@pytest.mark.integration
def test_annotation_on_remote_roundtrip(tmp_path: pathlib.Path) -> None:
    """An <annotation> on a <remote> element parses and round-trips correctly.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com">\n'
        '    <annotation name="geo" value="us-east" keep="true" />\n'
        "  </remote>\n"
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    remote = _get_remote(manifest, "origin")

    assert len(remote.annotations) == 1, f"Expected 1 annotation on remote but got: {len(remote.annotations)}"
    assert remote.annotations[0].name == "geo", (
        f"Expected annotation.name='geo' but got: {remote.annotations[0].name!r}"
    )
    assert remote.annotations[0].value == "us-east", (
        f"Expected annotation.value='us-east' but got: {remote.annotations[0].value!r}"
    )

    doc = manifest.ToXml()
    root = doc.documentElement

    remote_nodes = [n for n in root.childNodes if n.nodeName == "remote"]
    assert len(remote_nodes) >= 1, (
        f"Expected at least 1 <remote> element in round-trip XML but found: {len(remote_nodes)}"
    )

    annotation_nodes_found = []
    for remote_node in remote_nodes:
        for child in remote_node.childNodes:
            if child.nodeName == "annotation":
                annotation_nodes_found.append(child)

    assert len(annotation_nodes_found) == 1, (
        f"Expected 1 <annotation> under <remote> in round-trip XML but found: {len(annotation_nodes_found)}"
    )


@pytest.mark.integration
def test_annotation_no_children_means_empty_list(tmp_path: pathlib.Path) -> None:
    """When no <annotation> child is present, project.annotations is an empty list.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/tools" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    project = _get_project(manifest, "platform/tools")

    assert project.annotations == [], (
        f"Expected project.annotations=[] when no annotation children but got: {project.annotations!r}"
    )


@pytest.mark.integration
def test_annotation_invalid_keep_raises_error(tmp_path: pathlib.Path) -> None:
    """A manifest with an <annotation> having an invalid keep value raises ManifestParseError.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/tools">\n'
        '    <annotation name="label" value="x" keep="invalid" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"


@pytest.mark.integration
def test_annotation_multiple_children_roundtrip(tmp_path: pathlib.Path) -> None:
    """Multiple <annotation> children with keep='true' all appear in round-trip XML.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/tools">\n'
        '    <annotation name="team" value="platform-eng" keep="true" />\n'
        '    <annotation name="env" value="prod" keep="true" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    project = _get_project(manifest, "platform/tools")

    assert len(project.annotations) == 2, f"Expected 2 annotations in parsed model but got: {len(project.annotations)}"

    doc = manifest.ToXml()
    root = doc.documentElement

    annotation_nodes_found = []
    for project_node in [n for n in root.childNodes if n.nodeName == "project"]:
        for child in project_node.childNodes:
            if child.nodeName == "annotation":
                annotation_nodes_found.append(child)

    assert len(annotation_nodes_found) == 2, (
        f"Expected 2 <annotation> elements in round-trip XML but found: {len(annotation_nodes_found)}"
    )


@pytest.mark.integration
def test_annotation_is_annotation_instance_after_parse(tmp_path: pathlib.Path) -> None:
    """Parsed annotations are Annotation instances with correct fields.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_manifest_with_project_annotation(
        annotation_name="tier",
        annotation_value="gold",
        annotation_keep="true",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    project = _get_project(manifest, "platform/tools")

    assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
    ann = project.annotations[0]
    assert isinstance(ann, Annotation), f"Expected Annotation instance but got: {type(ann)!r}"
    assert ann.name == "tier", f"Expected name='tier' but got: {ann.name!r}"
    assert ann.value == "gold", f"Expected value='gold' but got: {ann.value!r}"
    assert ann.keep == "true", f"Expected keep='true' but got: {ann.keep!r}"
