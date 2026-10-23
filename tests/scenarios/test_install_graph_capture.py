"""Scenario: a real ``kanon install`` populates the lockfile project layer (A2b).

Proves the install-graph capture fix end to end against a ``file://`` manifest +
content fixture:

- ``kanon install`` now writes a populated ``[[sources.projects]]`` layer (name +
  source URL + canonical URL + resolved content SHA) for every synced transitive
  repo package, joined from the already-synced manifests and the captured content
  pins -- the previously-empty projects layer that this fix populates;
- the resolved project SHA in ``projects`` matches the captured ``content_pins``
  SHA for the same package;
- ``kanon why <project-url>`` on that install-written lockfile now shows the
  project in a resolved chain (it previously showed no project layer).
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import make_plain_repo, run_kanon, write_kanonenv


_MANIFEST_ALIAS = "primary"
_CONTENT_PACKAGE = "pkg-alpha"


def _build_fixture(base: pathlib.Path, default_location: str = "explicit") -> str:
    """Build a file:// manifest repo pulling one content package; return its URL."""
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
    files = {
        "repo-specs/remote.xml": remote_xml,
        "repo-specs/primary.xml": primary_xml,
    }
    if default_location != "explicit":
        files["repo-specs/packages.xml"] = (
            f'<manifest><project name="{_CONTENT_PACKAGE}" path=".packages/{_CONTENT_PACKAGE}"/></manifest>'
        )
        default = '<default remote="local" revision="main"/>' if default_location == "root" else ""
        if default_location == "root":
            files["repo-specs/remote.xml"] = remote_xml.replace('  <default remote="local" revision="main" />\n', "")
        files["repo-specs/primary.xml"] = (
            f'<manifest>{default}<include name="repo-specs/remote.xml"/>'
            '<include name="repo-specs/packages.xml"/></manifest>'
        )
    bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        files,
    )
    return bare.as_uri()


@pytest.mark.scenario
@pytest.mark.parametrize("default_location", ["explicit", "root", "included"])
def test_install_populates_projects_and_why_shows_them(tmp_path: pathlib.Path, default_location: str) -> None:
    """A real install writes the project layer and 'kanon why' resolves the project."""
    manifest_url = _build_fixture(tmp_path / "fixtures", default_location)
    project_root = tmp_path / "project"
    project_root.mkdir()
    home = tmp_path / "kanon-home"
    write_kanonenv(
        project_root,
        sources=[(_MANIFEST_ALIAS, manifest_url, "main", "repo-specs/primary.xml")],
    )

    extra_env = {
        "KANON_HOME": str(home),
        "KANON_ALLOW_INSECURE_REMOTES": "1",
        "KANON_SKIP_UPDATE_CHECK": "1",
        "KANON_TELEMETRY_DISABLED": "1",
    }

    project_url = (tmp_path / "fixtures" / "content-repos" / _CONTENT_PACKAGE).as_uri()
    live_why = run_kanon(
        "why", project_url, "--catalog-source", f"{manifest_url}@main", cwd=project_root, extra_env=extra_env
    )
    assert live_why.returncode == 0, live_why.stderr
    assert _CONTENT_PACKAGE in live_why.stdout

    install = run_kanon("install", cwd=project_root, extra_env=extra_env)
    assert install.returncode == 0, install.stderr

    lockfile = read_lockfile(project_root / ".kanon.lock")
    source = lockfile.sources[0]
    projects = {p.name: p for p in source.projects}
    assert _CONTENT_PACKAGE in projects, "install did not populate the project layer"

    project = projects[_CONTENT_PACKAGE]
    assert project.url
    assert project.canonical_url
    pin_sha = {pin.name: pin.resolved_sha for pin in source.content_pins}[_CONTENT_PACKAGE]
    assert project.resolved_sha == pin_sha

    why = run_kanon("why", project.url, cwd=project_root, extra_env=extra_env)
    assert why.returncode == 0, why.stderr
    assert _CONTENT_PACKAGE in why.stdout
