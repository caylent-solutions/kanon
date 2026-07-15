"""End-to-end journey for ``kanon list`` over the real install lifecycle.

Mimics the full command life cycle a human (or agent) would walk through, using a
real ``file://`` manifest + content fixture and a real ``kanon install`` (no
mocks -- the scenario tier):

  1. declare a source, then ``kanon list`` before install  -> not-installed
  2. ``kanon install`` (writes a real .kanon.lock), then list -> installed
  3. ``kanon list --tree``                                    -> transitive package shown
  4. declare a second source without installing              -> installed + not-installed
  5. undeclare the first source (edit .kanon, no re-install)  -> orphan surfaces
  6. every state is also asserted through ``--format json``

The lock is produced by the real resolver, so this proves ``list`` reads what
``install`` actually writes -- including the transitive package captured under
``--tree``.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from tests.scenarios.conftest import make_plain_repo, run_kanon, write_kanonenv


_CONTENT_PACKAGE = "pkg-alpha"
_PRIMARY_ALIAS = "primary"
_SECOND_ALIAS = "second"


def _build_manifest_url(base: pathlib.Path) -> str:
    """Build a file:// manifest repo that pulls one content package; return its URL."""
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, _CONTENT_PACKAGE, {"README.md": f"# {_CONTENT_PACKAGE}\n"})
    content_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    primary_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        f'  <project name="{_CONTENT_PACKAGE}" path=".packages/{_CONTENT_PACKAGE}"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {"repo-specs/remote.xml": remote_xml, "repo-specs/primary.xml": primary_xml},
    )
    return bare.as_uri()


@pytest.fixture()
def journey_env(tmp_path: pathlib.Path) -> dict[str, str]:
    """A subprocess env isolated from ambient telemetry with an insecure-remote opt-in."""
    env = dict(os.environ)
    for key in ("KANON_TELEMETRY_DISABLED", "KANON_TELEMETRY_ENDPOINT", "KANON_TELEMETRY_FORCE"):
        env.pop(key, None)
    env["KANON_HOME"] = str(tmp_path / "home")
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    env["KANON_SKIP_UPDATE_CHECK"] = "1"
    env["KANON_TELEMETRY_DISABLED"] = "1"
    env["NO_COLOR"] = "1"
    return env


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    """A project directory declaring one source pointing at the manifest fixture."""
    manifest_url = _build_manifest_url(tmp_path / "fixtures")
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_kanonenv(project_root, sources=[(_PRIMARY_ALIAS, manifest_url, "main", "repo-specs/primary.xml")])
    return project_root, manifest_url


def _statuses(project_root: pathlib.Path, env: dict[str, str], *flags: str) -> dict[str, str]:
    """Return an ``{alias: status}`` map from ``kanon list --format json``."""
    result = run_kanon("list", "--format", "json", *flags, cwd=project_root, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return {source["alias"]: source["status"] for source in payload["sources"]}


@pytest.mark.scenario
def test_full_list_lifecycle(project: tuple[pathlib.Path, str], journey_env: dict[str, str]) -> None:
    """Walk declare -> install -> add -> undeclare and assert list at each step."""
    project_root, manifest_url = project

    before = run_kanon("list", cwd=project_root, env=journey_env)
    assert before.returncode == 0
    assert "not-installed" in before.stdout
    assert _statuses(project_root, journey_env) == {_PRIMARY_ALIAS: "not-installed"}

    installed = run_kanon("install", cwd=project_root, env=journey_env)
    assert installed.returncode == 0, installed.stderr
    assert (project_root / ".kanon.lock").is_file()

    after = run_kanon("list", cwd=project_root, env=journey_env)
    assert after.returncode == 0
    assert _statuses(project_root, journey_env) == {_PRIMARY_ALIAS: "installed"}

    tree = run_kanon("list", "--tree", cwd=project_root, env=journey_env)
    assert tree.returncode == 0
    assert _CONTENT_PACKAGE in tree.stdout

    kanon_file = project_root / ".kanon"
    original = kanon_file.read_text()
    second_block = (
        f"KANON_SOURCE_{_SECOND_ALIAS}_URL={manifest_url}\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_REF=main\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_PATH=repo-specs/primary.xml\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_NAME={_SECOND_ALIAS}\n"
    )
    kanon_file.write_text(original + second_block)
    assert _statuses(project_root, journey_env) == {
        _PRIMARY_ALIAS: "installed",
        _SECOND_ALIAS: "not-installed",
    }

    declared_only = _statuses(project_root, journey_env, "--declared")
    assert set(declared_only) == {_PRIMARY_ALIAS, _SECOND_ALIAS}

    only_second = (
        f"KANON_SOURCE_{_SECOND_ALIAS}_URL={manifest_url}\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_REF=main\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_PATH=repo-specs/primary.xml\n"
        f"KANON_SOURCE_{_SECOND_ALIAS}_NAME={_SECOND_ALIAS}\n"
    )
    kanon_file.write_text("GITBASE=https://example.com\n" + only_second)
    statuses = _statuses(project_root, journey_env)
    assert statuses[_PRIMARY_ALIAS] == "orphan"
    assert statuses[_SECOND_ALIAS] == "not-installed"

    orphan_only = _statuses(project_root, journey_env, "--status", "orphan")
    assert orphan_only == {_PRIMARY_ALIAS: "orphan"}
