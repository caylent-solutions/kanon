"""Content-pin replay matches the same name/path identity used during capture."""

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from kanon_cli.core.install import apply_content_pins_to_manifests
from kanon_cli.core.lockfile import ContentPinEntry
from kanon_cli.repo.manifest_xml import XmlManifest


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("default_path", ["", ' path=""', ' path="package"'])
def test_replay_uses_name_and_effective_checkout_path(tmp_path: Path, default_path: str) -> None:
    manifest = tmp_path / "manifest.xml"
    manifest.write_text(
        '<manifest><project name="package" path="older" revision="old-tag"/>'
        f'<project name="package"{default_path} revision="main"/>'
        '<project name="package" path="unlocked" revision="untouched"/></manifest>'
    )
    pins = [
        ContentPinEntry(name="package", path="older", resolved_sha="a" * 40),
        ContentPinEntry(name="package", path="package", resolved_sha="b" * 40),
    ]
    apply_content_pins_to_manifests([manifest], pins)
    projects = ET.parse(manifest).getroot().findall("project")
    revisions = {project.get("path") or project.get("name"): project.get("revision") for project in projects}
    assert revisions == {"older": pins[0].resolved_sha, "package": pins[1].resolved_sha, "unlocked": "untouched"}
    before = manifest.read_bytes()
    apply_content_pins_to_manifests([manifest], pins)
    assert manifest.read_bytes() == before


def test_empty_pins_do_not_rewrite_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.xml"
    manifest.write_text('<manifest><project name="package" revision="main"/></manifest>')
    before = manifest.read_bytes()
    apply_content_pins_to_manifests([manifest], [])
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("parent_path", ["", ' path="checkout/"', ' path="."'])
@pytest.mark.parametrize("child_path", ["", ' path=""', ' path="inside/"'])
def test_nested_replay_matches_vendored_project_identity(tmp_path: Path, parent_path: str, child_path: str) -> None:
    repo_dir = tmp_path / ".repo"
    (repo_dir / "manifests").mkdir(parents=True)
    git_dir = repo_dir / "manifests.git"
    git_dir.mkdir()
    (git_dir / "config").write_text('[remote "origin"]\nurl = https://example.com/catalog\n')
    manifest = repo_dir / "manifest.xml"
    manifest.write_text(
        '<manifest><remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        f'<project name="parent"{parent_path} revision="parent-ref">'
        f'<project name="child"{child_path} revision="child-ref">'
        '<project name="leaf" path="deep/" revision="leaf-ref"/></project>'
        '<project name="child" path="second/" revision="other-ref"/>'
        '<project name="unlocked" revision="untouched"/></project>'
        '<project name="child" path="standalone/" revision="standalone-ref"/></manifest>'
    )
    parsed = XmlManifest(str(repo_dir), str(manifest))
    expected = {(project.name, project.relpath): project.revisionExpr for project in parsed.projects}
    pins = [
        ContentPinEntry(name=name, path=path, resolved_sha=f"{index:040x}")
        for index, (name, path) in enumerate(expected, start=1)
        if name != "parent/unlocked"
    ]
    expected.update({(pin.name, pin.path): pin.resolved_sha for pin in pins})

    apply_content_pins_to_manifests([manifest], pins)

    replayed = XmlManifest(str(repo_dir), str(manifest))
    assert {(project.name, project.relpath): project.revisionExpr for project in replayed.projects} == expected
    before = manifest.read_bytes()
    apply_content_pins_to_manifests([manifest], pins)
    assert manifest.read_bytes() == before
