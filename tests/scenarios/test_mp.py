"""MP (Multi-Project isolation) scenarios from `docs/integration-testing.md` §6a.

Two unrelated projects sharing one `KANON_HOME` and declaring a source under the
same alias must not share a mutable workspace. Before per-project keying they did:
the second project's install either delivered nothing while reporting success, or
raised an unhandled `GitCommandError` that wedged the workspace for both. Each
project now installs into a workspace keyed by a stable address derived from its
own `.kanon` path.

This is the end-to-end proof of that fix. The unit-tier tests for project keying
mock `repo_init`, `repo_envsubst` and `repo_sync`, so nothing is ever written and
the only thing they can assert is that two `mkdir` calls used different paths --
they cannot fail for the reason the fix exists. These tests drive real git repos
through real `kanon install` subprocesses and read the delivered bytes.

Scenarios automated:
- MP-01: two projects, one alias, different revisions, each receives its own content
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_install,
    project_address_for,
    run_git,
    write_kanonenv,
)


_PROJECT_ADDRESS_LENGTH = 64

_SHARED_ALIAS = "shared"

_PACKAGE_NAME = "shared-pkg"

_CONTENT_BY_TAG = {"v1": "payload from v1\n", "v2": "payload from v2\n"}

_INSECURE_LOCAL_REMOTES = {"KANON_ALLOW_INSECURE_REMOTES": "1"}
"""The fixture repositories are local `file://` paths, which the remote-URL check
rejects by default. The scenarios that build their own git fixtures all opt out the
same way."""


def _make_content_repo(parent: pathlib.Path) -> pathlib.Path:
    """Create a bare repo whose `v1` and `v2` tags carry different file content.

    Args:
        parent: Directory to create the repository under.

    Returns:
        Path to the bare repository.
    """
    work = parent / f"{_PACKAGE_NAME}.work"
    init_git_work_dir(work)
    for tag, content in _CONTENT_BY_TAG.items():
        (work / "payload.txt").write_text(content, encoding="utf-8")
        run_git(["add", "payload.txt"], work)
        run_git(["commit", "-m", f"payload {tag}"], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, parent / f"{_PACKAGE_NAME}.git")


def _make_manifest_repo(parent: pathlib.Path, content_url: str) -> pathlib.Path:
    """Create a bare manifest repo whose `v1` and `v2` tags pin different revisions.

    Both tags carry the same manifest path, so the two consuming projects differ
    only in the ref they pin -- which is what makes a shared workspace visible.

    Args:
        parent: Directory to create the repository under.
        content_url: Fetch URL for the content repository.

    Returns:
        Path to the bare manifest repository.
    """
    work = parent / "manifest.work"
    init_git_work_dir(work)
    specs = work / "repo-specs"
    specs.mkdir(parents=True, exist_ok=True)
    for tag in _CONTENT_BY_TAG:
        (specs / "shared.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_url}" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{_PACKAGE_NAME}" path=".packages/{_PACKAGE_NAME}" '
            f'remote="local" revision="refs/tags/{tag}" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        run_git(["add", "repo-specs/shared.xml"], work)
        run_git(["commit", "-m", f"manifest {tag}"], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, parent / "manifest.git")


def _delivered_payload(store: pathlib.Path, project_dir: pathlib.Path) -> str:
    """Return the payload delivered into *project_dir*'s own source workspace.

    Args:
        store: The `<KANON_HOME>/store` directory.
        project_dir: The consuming project's directory.

    Returns:
        The contents of the delivered payload file.
    """
    address = project_address_for(project_dir)
    payload = store / ".kanon-data" / "sources" / address / _SHARED_ALIAS / ".packages" / _PACKAGE_NAME / "payload.txt"
    assert payload.is_file(), f"Expected delivered payload at {payload}, but it does not exist."
    return payload.read_text(encoding="utf-8")


@pytest.mark.scenario
class TestMP:
    """MP-01: two projects sharing an alias each receive their own content."""

    def test_two_projects_sharing_one_alias_each_receive_own_content(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        """Each project's workspace holds the revision that project pinned.

        Installing B must not change what A has, and re-installing A afterwards
        must not change what B has. The re-install is the step that would have
        caught the original defect: a shared workspace only reveals itself once
        the second project has moved it.
        """
        content_repos = tmp_path / "content-repos"
        manifest_repos = tmp_path / "manifest-repos"
        content_repos.mkdir(parents=True)
        manifest_repos.mkdir(parents=True)
        _make_content_repo(content_repos)
        manifest_bare = _make_manifest_repo(manifest_repos, f"{content_repos.as_uri()}/")

        project_a = scenario_workspace / "project-a"
        project_b = scenario_workspace / "project-b"
        for project, tag in ((project_a, "v1"), (project_b, "v2")):
            project.mkdir(parents=True)
            write_kanonenv(
                project,
                [(_SHARED_ALIAS, f"file://{manifest_bare}", tag, "repo-specs/shared.xml")],
            )

        first_a = kanon_install(project_a, extra_env=_INSECURE_LOCAL_REMOTES)
        assert first_a.returncode == 0, f"project A install failed: {first_a.stderr!r}"

        install_b = kanon_install(project_b, extra_env=_INSECURE_LOCAL_REMOTES)
        assert install_b.returncode == 0, f"project B install failed: {install_b.stderr!r}"

        store = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        after_b = _delivered_payload(store, project_a)
        assert after_b == _CONTENT_BY_TAG["v1"], (
            f"Project B's install overwrote project A's content. Expected A to still hold "
            f"{_CONTENT_BY_TAG['v1']!r}, found {after_b!r}."
        )

        second_a = kanon_install(project_a, extra_env=_INSECURE_LOCAL_REMOTES)
        assert second_a.returncode == 0, f"project A re-install failed: {second_a.stderr!r}"

        assert _delivered_payload(store, project_a) == _CONTENT_BY_TAG["v1"], (
            "Re-installing project A did not restore its own pinned content."
        )
        assert _delivered_payload(store, project_b) == _CONTENT_BY_TAG["v2"], (
            f"Re-installing project A disturbed project B's workspace. Expected B to hold {_CONTENT_BY_TAG['v2']!r}."
        )

        address_a = project_address_for(project_a)
        address_b = project_address_for(project_b)
        assert address_a != address_b, (
            "Two projects at different paths must have different project addresses, "
            f"but both resolved to {address_a!r}."
        )
        sources = store / ".kanon-data" / "sources"
        assert (sources / address_a / _SHARED_ALIAS).is_dir(), "project A has no keyed workspace"
        assert (sources / address_b / _SHARED_ALIAS).is_dir(), "project B has no keyed workspace"

    def test_project_addresses_are_distinct_hex_directories(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        """`sources/` is keyed by project address, one directory per consumer.

        Before the fix `sources/` held one directory per alias, shared by every
        project on the machine.
        """
        project_a = scenario_workspace / "addr-a"
        project_b = scenario_workspace / "addr-b"
        for project in (project_a, project_b):
            project.mkdir(parents=True)

        address_a = project_address_for(project_a)
        address_b = project_address_for(project_b)

        assert address_a != address_b
        assert all(len(a) == _PROJECT_ADDRESS_LENGTH for a in (address_a, address_b))
        assert all(all(c in "0123456789abcdef" for c in a) for a in (address_a, address_b))
