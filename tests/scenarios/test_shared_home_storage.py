"""Real install, replay, and cleanup need only the project source workspaces."""

import pathlib

import pytest

from kanon_cli.core.install import compute_project_address
from tests.scenarios.conftest import make_bare_repo_with_tags, make_plain_repo, run_kanon


@pytest.mark.scenario
def test_shared_home_install_replay_and_cleanup_without_snapshots(tmp_path: pathlib.Path) -> None:
    """Two consumers retain isolated content; explicit purge still removes old snapshots."""
    make_bare_repo_with_tags(tmp_path, "content", ["1.0.0"])
    manifest = (
        "<manifest><catalog-metadata><name>content</name><display-name>Content</display-name>"
        "<description>Shared home fixture</description><version>1.0.0</version>"
        "<type>library</type></catalog-metadata>"
        f'<remote name="local" fetch="{tmp_path.as_uri()}/"/>'
        '<default remote="local" revision="main"/>'
        '<project name="content.git" path=".packages/content"/></manifest>'
    )
    catalog = make_plain_repo(tmp_path, "catalog", {"repo-specs/content.xml": manifest})
    home = tmp_path / "home"
    store = home / "store"
    env = {"KANON_HOME": str(home), "KANON_ALLOW_INSECURE_REMOTES": "1"}
    projects = [tmp_path / "consumer-a", tmp_path / "consumer-b"]
    for project in projects:
        project.mkdir()
        for args in (("add", "content@main", "--catalog-source", catalog.as_uri() + "@main"), ("install",)):
            result = run_kanon(*args, cwd=project, extra_env=env)
            assert result.returncode == 0, result.stderr
        assert (project / ".packages" / "content" / "version.txt").read_text() == "1.0.0"
    assert not (store / "entries").exists()
    assert not (store / ".tmp").exists()
    workspaces = [store / ".kanon-data" / "sources" / compute_project_address(p / ".kanon") for p in projects]
    assert all(workspace.is_dir() for workspace in workspaces)
    assert (projects[0] / ".packages").resolve() != (projects[1] / ".packages").resolve()

    first, second = projects
    locked_bytes = (second / ".kanon.lock").read_bytes()
    replay = run_kanon("install", cwd=second, extra_env=env)
    assert replay.returncode == 0, replay.stderr
    assert (second / ".kanon.lock").read_bytes() == locked_bytes
    assert not (store / "entries").exists()
    assert not (store / ".tmp").exists()

    legacy = store / "entries" / "unused" / "payload"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old snapshot", encoding="utf-8")
    old_temp = store / ".tmp" / "interrupted"
    old_temp.mkdir(parents=True)
    unrelated = home / "keep.txt"
    unrelated.write_text("user data", encoding="utf-8")
    cleaned = run_kanon("clean", cwd=first, extra_env=env)
    assert cleaned.returncode == 0, cleaned.stderr
    assert not workspaces[0].exists()
    assert workspaces[1].is_dir()
    assert not (first / ".packages").is_symlink()
    assert (second / ".packages" / "content" / "version.txt").read_text() == "1.0.0"
    assert legacy.read_text() == "old snapshot"
    assert old_temp.is_dir()

    replay = run_kanon("install", cwd=second, extra_env=env)
    assert replay.returncode == 0, replay.stderr
    assert (second / ".kanon.lock").read_bytes() == locked_bytes
    assert legacy.read_text() == "old snapshot"
    purged = run_kanon("clean", "--purge-all", cwd=second, extra_env=env)
    assert purged.returncode == 0, purged.stderr
    assert not store.exists()
    assert not (second / ".kanon").exists()
    assert not (second / ".kanon.lock").exists()
    assert unrelated.read_text() == "user data"
