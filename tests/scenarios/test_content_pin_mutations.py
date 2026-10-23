"""Real Git installs preserve effective project pins after manifest mutations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import make_plain_repo, project_address_for
from tests.scenarios.test_content_pins import (
    _advance_main,
    _git_out,
    _install,
    _make_content_repo,
    _write_kanon,
)


pytestmark = pytest.mark.scenario


@pytest.mark.parametrize("layout", ["nested", "extend-revision", "extend-destination", "replace"])
def test_effective_projects_capture_replay_and_refresh(tmp_path: Path, layout: str) -> None:
    work, bare, initial_sha = _make_content_repo(tmp_path, "content")
    repositories = [(work, bare)]
    expected = {("content.git", "checkout"): initial_sha}
    project_xml = '<project name="content.git" path="checkout" revision="refs/tags/1.0.0"/>'
    mutations = ""
    if layout == "nested":
        child_work, child_bare, child_sha = _make_content_repo(bare, "child")
        repositories.append((child_work, child_bare))
        project_xml = '<project name="content.git" path="checkout"><project name="child.git" path="child"/></project>'
        expected[(os.path.join("content.git", "child.git"), os.path.join("checkout", "child"))] = child_sha
    elif layout == "extend-revision":
        mutations = '<extend-project name="content.git" revision="refs/heads/main" base-rev="refs/tags/1.0.0"/>'
    elif layout == "extend-destination":
        mutations = (
            '<extend-project name="content.git" path="checkout" dest-path="relocated" '
            'revision="refs/heads/main" base-rev="refs/tags/1.0.0"/>'
        )
        expected = {("content.git", "relocated"): initial_sha}
    else:
        mutations = (
            '<remove-project name="content.git" base-rev="refs/tags/1.0.0"/>'
            '<project name="content.git" path="checkout"/>'
        )
    manifest_xml = (
        f'<manifest><remote name="origin" fetch="{tmp_path.as_uri()}/"/>'
        '<default remote="origin" revision="refs/heads/main"/>'
        f'{project_xml}<include name="repo-specs/mutations.xml"/></manifest>'
    )
    manifest = make_plain_repo(
        tmp_path,
        "manifest",
        {"repo-specs/meta.xml": manifest_xml, "repo-specs/mutations.xml": f"<manifest>{mutations}</manifest>"},
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "kanon-home"
    _write_kanon(workspace, "dep", manifest.as_uri(), "refs/heads/main")
    initial = _install(workspace, home)
    assert initial.returncode == 0, initial.stderr
    lock_path = workspace / ".kanon.lock"
    source = read_lockfile(lock_path).sources[0]
    assert {(pin.name, pin.path): pin.resolved_sha for pin in source.content_pins} == expected
    assert {(project.name, project.resolved_sha) for project in source.projects} == {
        (name, sha) for (name, _path), sha in expected.items()
    }
    original_lock = lock_path.read_bytes()
    new_shas = [_advance_main(content_work, content_bare) for content_work, content_bare in repositories]
    checkout = home / "store" / ".kanon-data" / "sources" / project_address_for(workspace) / "dep"
    for _ in range(2):
        replay = _install(workspace, home)
        assert replay.returncode == 0, replay.stderr
        assert lock_path.read_bytes() == original_lock
        for (_name, path), sha in expected.items():
            assert _git_out(["rev-parse", "HEAD"], checkout / path) == sha
    refresh = _install(workspace, home, "--refresh-lock")
    assert refresh.returncode == 0, refresh.stderr
    refreshed = read_lockfile(lock_path).sources[0]
    assert {pin.resolved_sha for pin in refreshed.content_pins} == set(new_shas)
    for pin in refreshed.content_pins:
        assert _git_out(["rev-parse", "HEAD"], checkout / pin.path) == pin.resolved_sha
