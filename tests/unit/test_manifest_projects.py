"""Shared graph metadata follows the installed manifest's includes and defaults."""

from pathlib import Path
import shutil

import pytest

from kanon_cli.commands.why import _build_project_nodes_from_xml
from kanon_cli.core.include_walker import IncludeCycleError
from kanon_cli.core.install import build_project_entries
from kanon_cli.core.lockfile import ContentPinEntry
from kanon_cli.core.manifest import collect_manifest_projects
from kanon_cli.repo.manifest_xml import XmlManifest


pytestmark = pytest.mark.unit


def _write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.write_text(f"<manifest>{content}</manifest>")
    return path


@pytest.mark.parametrize("default_location", ["root", "included"])
def test_included_projects_share_defaults_in_install_and_live_why(tmp_path: Path, default_location: str) -> None:
    defaults = '<remote name="origin" fetch="https://example.com/team"/><default remote="origin" revision="main"/>'
    root = _write(
        tmp_path,
        "root.xml",
        (defaults if default_location == "root" else '<include name="defaults.xml"/>') + '<include name="child.xml"/>',
    )
    defaults_path = _write(tmp_path, "defaults.xml", defaults if default_location == "included" else "")
    child = _write(tmp_path, "child.xml", '<project name="package" path="checkout"/>')
    sha = "b" * 40
    entries = build_project_entries(
        root,
        tmp_path,
        [root, child, defaults_path],
        [ContentPinEntry(name="package", path="checkout", resolved_sha=sha)],
    )
    assert [(entry.url, entry.resolved_ref, entry.resolved_sha) for entry in entries] == [
        ("https://example.com/team/package", "main", sha)
    ]
    nodes = _build_project_nodes_from_xml(root, tmp_path, "a" * 40, "source")
    assert [(node.name, node.url) for node in nodes] == [(entries[0].name, entries[0].url)]


def test_revision_precedence_and_checkout_identity(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team" revision="remote"/>'
        '<default remote="origin" revision="default"/>'
        '<include name="child.xml" revision="include"/>'
        '<project name="package" path="root-checkout"/>',
    )
    child = _write(
        tmp_path,
        "child.xml",
        '<project name="package" path="included-checkout"/><project name="explicit" revision="project"/>',
    )
    projects = collect_manifest_projects(root, tmp_path)
    assert {(p.name, p.path): p.revision for p in projects} == {
        ("package", "root-checkout"): "remote",
        ("package", "included-checkout"): "include",
        ("explicit", "explicit"): "project",
    }
    pins = [
        ContentPinEntry(name="package", path=path, resolved_sha=sha * 40)
        for path, sha in [("root-checkout", "a"), ("included-checkout", "b")]
    ]
    entries = build_project_entries(root, tmp_path, [root, child], pins)
    assert {(entry.resolved_ref, entry.resolved_sha) for entry in entries} == {
        ("remote", "a" * 40),
        ("include", "b" * 40),
    }


def test_diamond_projects_are_emitted_once_and_cycles_fail(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<include name="left.xml"/><include name="right.xml"/>',
    )
    for name in ("left.xml", "right.xml"):
        _write(tmp_path, name, '<include name="shared.xml"/>')
    _write(tmp_path, "shared.xml", '<project name="package"/>')
    assert len(collect_manifest_projects(root, tmp_path)) == 1
    _write(tmp_path, "shared.xml", '<include name="root.xml"/>')
    with pytest.raises(IncludeCycleError):
        collect_manifest_projects(root, tmp_path)


@pytest.mark.parametrize("conflict", ["remote", "default"])
def test_conflicting_definitions_fail(tmp_path: Path, conflict: str) -> None:
    definitions = '<remote name="origin" fetch="https://example.com/team"/><default remote="origin" revision="main"/>'
    root = _write(tmp_path, "root.xml", definitions + '<include name="child.xml"/>')
    changed = (
        definitions.replace("example.com", "other.example.com")
        if conflict == "remote"
        else definitions.replace('revision="main"', 'revision="other"')
    )
    _write(tmp_path, "child.xml", changed)
    with pytest.raises(ValueError, match=f"Conflicting manifest {conflict}"):
        collect_manifest_projects(root, tmp_path)


def _assert_vendored_parity(root: Path, manifest_repo: Path) -> None:
    """Compare explanatory identities, URLs and revisions with the sync parser."""
    repo_dir = manifest_repo / ".repo"
    manifest_dir = repo_dir / "manifests"
    manifest_dir.mkdir(parents=True)
    for xml in manifest_repo.glob("*.xml"):
        shutil.copyfile(xml, manifest_dir / xml.name)
    manifest_file = repo_dir / "manifest.xml"
    shutil.copyfile(root, manifest_file)
    git_dir = repo_dir / "manifests.git"
    git_dir.mkdir()
    (git_dir / "config").write_text('[remote "origin"]\nurl = https://example.com/catalog\n')
    manifest = XmlManifest(str(repo_dir), str(manifest_file))
    expected = {(p.name, p.relpath): (p.remote.url, p.revisionExpr) for p in manifest.projects}
    actual = collect_manifest_projects(root, manifest_repo)
    assert {(p.name, p.path): (f"{p.fetch}/{p.name}", p.revision) for p in actual} == expected

    nodes = _build_project_nodes_from_xml(root, manifest_repo, "a" * 40, "source")
    assert {(node.name, node.url) for node in nodes} == {(name, url) for (name, _path), (url, _ref) in expected.items()}
    entries = build_project_entries(
        root,
        manifest_repo,
        list(manifest_repo.glob("*.xml")),
        [ContentPinEntry(name=name, path=path, resolved_sha="b" * 40) for name, path in expected],
    )
    assert {(entry.name, entry.url, entry.resolved_ref) for entry in entries} == {
        (name, url, ref) for (name, _path), (url, ref) in expected.items()
    }


@pytest.mark.parametrize("parent_path", ["checkout", "."])
@pytest.mark.parametrize("child_path", ["inside", ""])
def test_nested_project_identity_and_include_revision_match_repo(
    tmp_path: Path, parent_path: str, child_path: str
) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team" revision="remote"/>'
        '<default remote="origin" revision="default"/>'
        '<include name="child.xml" revision="include"/>',
    )
    _write(
        tmp_path,
        "child.xml",
        f'<project name="parent" path="{parent_path}">'
        f'<project name="child" path="{child_path}"/>'
        '<project name="explicit" path="explicit" revision="child-ref"/></project>'
        '<project name="empty-revision" revision=""/>',
    )
    _assert_vendored_parity(root, tmp_path)


def test_remove_replace_and_extend_follow_expanded_declaration_order(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team"/>'
        '<remote name="replacement" fetch="https://other.example.com/team" revision="remote-ref"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="before"/>'
        '<include name="child.xml"/>'
        '<remove-project name="gone"/>'
        '<remove-project path="old" base-rev="main"/>'
        '<project name="replace" path="old" remote="replacement"/>'
        '<extend-project name="changed" path="left" remote="replacement" revision="extended" '
        'dest-path="moved" base-rev="main"/>',
    )
    _write(
        tmp_path,
        "child.xml",
        '<remove-project name="before"/>'
        '<project name="gone"/><project name="replace" path="old"/>'
        '<project name="changed" path="left"/><project name="changed" path="right"/>',
    )
    _assert_vendored_parity(root, tmp_path)


def test_extend_remote_preserves_revision_and_group_only_ignores_base_rev(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team"/>'
        '<remote name="replacement" fetch="https://other.example.com/team" revision="other-ref"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="package"/>'
        '<extend-project name="package" remote="replacement"/>'
        '<extend-project name="package" groups="extra" base-rev="ignored-without-revision"/>',
    )
    _assert_vendored_parity(root, tmp_path)


@pytest.mark.parametrize(
    "following_mutation",
    [
        "",
        '<extend-project name="second" path="right" dest-path="final" revision="moved"/>',
        '<remove-project name="second" path="right"/>',
    ],
)
def test_destination_overwrite_retains_only_runtime_checkout_projects(tmp_path: Path, following_mutation: str) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="first" path="left"/><project name="second" path="right"/>'
        '<extend-project name="first" dest-path="right"/>' + following_mutation,
    )
    _assert_vendored_parity(root, tmp_path)


@pytest.mark.parametrize("operation", ["remove-project", "extend-project"])
def test_mutation_rejects_mismatched_base_revision(tmp_path: Path, operation: str) -> None:
    root = _write(
        tmp_path,
        "root.xml",
        '<remote name="origin" fetch="https://example.com/team"/>'
        '<default remote="origin" revision="main"/>'
        '<project name="package"/>'
        f'<{operation} name="package" revision="new" base-rev="wrong"/>',
    )
    with pytest.raises(ValueError, match="base-rev"):
        collect_manifest_projects(root, tmp_path)
