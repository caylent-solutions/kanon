"""Content-pin replay matches the same name/path identity used during capture."""

from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from kanon_cli.core.install import apply_content_pins_to_manifests, build_project_entries, capture_content_pins
from kanon_cli.core.lockfile import ContentPinEntry
from kanon_cli.core.manifest import collect_manifest_projects
from kanon_cli.repo.manifest_xml import XmlManifest


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("default_path", ["", ' path=""', ' path="package"'])
def test_replay_uses_name_and_effective_checkout_path(tmp_path: Path, default_path: str) -> None:
    manifest = tmp_path / "manifest.xml"
    manifest.write_text(
        '<manifest><remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="package" path="older" revision="old-tag"/>'
        f'<project name="package"{default_path} revision="main"/>'
        '<project name="package" path="unlocked" revision="untouched"/></manifest>'
    )
    pins = [
        ContentPinEntry(name="package", path="older", resolved_sha="a" * 40),
        ContentPinEntry(name="package", path="package", resolved_sha="b" * 40),
    ]
    apply_content_pins_to_manifests(manifest, pins, collect_manifest_projects(manifest, tmp_path))
    projects = collect_manifest_projects(manifest, tmp_path)
    revisions = {project.path: project.revision for project in projects}
    assert revisions == {"older": pins[0].resolved_sha, "package": pins[1].resolved_sha, "unlocked": "untouched"}
    before = manifest.read_bytes()
    apply_content_pins_to_manifests(manifest, pins, projects)
    assert manifest.read_bytes() == before


def test_empty_pins_do_not_rewrite_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.xml"
    manifest.write_text('<manifest><project name="package" revision="main"/></manifest>')
    before = manifest.read_bytes()
    apply_content_pins_to_manifests(manifest, [], [])
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

    apply_content_pins_to_manifests(manifest, pins, collect_manifest_projects(manifest, repo_dir))

    replayed = XmlManifest(str(repo_dir), str(manifest))
    assert {(project.name, project.relpath): project.revisionExpr for project in replayed.projects} == expected
    before = manifest.read_bytes()
    apply_content_pins_to_manifests(manifest, pins, collect_manifest_projects(manifest, repo_dir))
    assert manifest.read_bytes() == before


def test_replay_applies_pins_after_ordered_extensions_and_replacements(tmp_path: Path) -> None:
    repo_dir = tmp_path / ".repo"
    manifest_dir = repo_dir / "manifests"
    manifest_dir.mkdir(parents=True)
    git_dir = repo_dir / "manifests.git"
    git_dir.mkdir()
    (git_dir / "config").write_text('[remote "origin"]\nurl = https://example.com/catalog\n')
    manifest = manifest_dir / "root.xml"
    manifest.write_text(
        '<manifest><remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="package" path="left" revision="main"/>'
        '<project name="package" path="right" revision="main"/>'
        '<project name="replaced" path="replace" revision="old"/>'
        '<include name="mutations.xml"/></manifest>'
    )
    mutations = manifest_dir / "mutations.xml"
    mutations.write_text(
        '<manifest><extend-project name="package" revision="branch" base-rev="main"/>'
        '<extend-project name="package" path="left" dest-path="moved/" revision="other" base-rev="branch"/>'
        '<remove-project name="replaced" base-rev="old"/>'
        '<project name="replaced" path="replace" revision="replacement"/></manifest>'
    )
    pins = [
        ContentPinEntry(name="package", path="moved", resolved_sha="a" * 40),
        ContentPinEntry(name="package", path="right", resolved_sha="b" * 40),
        ContentPinEntry(name="replaced", path="replace", resolved_sha="c" * 40),
        ContentPinEntry(name="removed", path="unused", resolved_sha="d" * 40),
    ]
    original_elements = [ET.tostring(element) for element in ET.parse(manifest).getroot()]
    original_mutations = mutations.read_bytes()

    declared_projects = collect_manifest_projects(manifest, manifest_dir)
    apply_content_pins_to_manifests(manifest, pins, declared_projects)

    replayed = XmlManifest(str(repo_dir), str(manifest))
    assert {(p.name, p.relpath): p.revisionExpr for p in replayed.projects} == {
        (pin.name, pin.path): pin.resolved_sha for pin in pins if pin.name != "removed"
    }
    assert [ET.tostring(element) for element in list(ET.parse(manifest).getroot())[: len(original_elements)]] == (
        original_elements
    )
    assert mutations.read_bytes() == original_mutations
    entries = build_project_entries(manifest, manifest_dir, [manifest, mutations], pins, projects=declared_projects)
    assert {(entry.name, entry.resolved_ref, entry.resolved_sha) for entry in entries} == {
        ("package", "other", "a" * 40),
        ("package", "branch", "b" * 40),
        ("replaced", "replacement", "c" * 40),
    }
    before = manifest.read_bytes()
    apply_content_pins_to_manifests(manifest, pins, collect_manifest_projects(manifest, manifest_dir))
    assert manifest.read_bytes() == before


def test_invalid_base_revision_fails_before_replay_writes(tmp_path: Path) -> None:
    manifest = tmp_path / "root.xml"
    manifest.write_text(
        '<manifest><remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/><project name="package"/>'
        '<extend-project name="package" revision="branch" base-rev="wrong"/></manifest>'
    )
    before = manifest.read_bytes()
    pins = [ContentPinEntry(name="package", path="package", resolved_sha="a" * 40)]
    with pytest.raises(ValueError, match="base-rev"):
        apply_content_pins_to_manifests(manifest, pins, collect_manifest_projects(manifest, tmp_path))
    assert manifest.read_bytes() == before


def test_capture_and_replay_exclude_overwritten_checkout_identity(tmp_path: Path) -> None:
    repo_dir = tmp_path / ".repo"
    manifest_dir = repo_dir / "manifests"
    manifest_dir.mkdir(parents=True)
    git_dir = repo_dir / "manifests.git"
    git_dir.mkdir()
    (git_dir / "config").write_text('[remote "origin"]\nurl = https://example.com/catalog\n')
    manifest = manifest_dir / "root.xml"
    manifest.write_text(
        '<manifest><remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="first" path="left"/><project name="second" path="right"/>'
        '<extend-project name="first" dest-path="right"/></manifest>'
    )
    checkout = tmp_path / "right"
    checkout.mkdir()
    for args in (
        ["init", "-b", "main"],
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "content"],
    ):
        subprocess.run(["git", *args], cwd=checkout, capture_output=True, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=True
    ).stdout.strip()
    expected_identities = {(p.name, p.relpath) for p in XmlManifest(str(repo_dir), str(manifest)).projects}
    projects = collect_manifest_projects(manifest, manifest_dir)

    pins = capture_content_pins(tmp_path, projects)

    assert {(pin.name, pin.path): pin.resolved_sha for pin in pins} == {
        identity: sha for identity in expected_identities
    }
    apply_content_pins_to_manifests(manifest, pins, projects)
    assert {(p.name, p.relpath): p.revisionExpr for p in XmlManifest(str(repo_dir), str(manifest)).projects} == {
        identity: sha for identity in expected_identities
    }
