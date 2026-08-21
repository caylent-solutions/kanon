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
import shutil

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

_PACKAGE_NAME_BY_TAG = {"v1": "pkg-from-v1", "v2": "pkg-from-v2"}
"""Distinct package names per project, deliberately.

This scenario exercises *source workspace* isolation. Two projects publishing the
same package name is a different concern -- the aggregated ``.packages/`` farm is
shared and keyed only by name -- and is covered on its own in
``tests/integration/test_multi_source_aggregation.py``. Reusing one name here
would make MP-01 fail for that second reason and stop testing the first."""

_CONTENT_BY_TAG = {"v1": "payload from v1\n", "v2": "payload from v2\n"}

_INSECURE_LOCAL_REMOTES = {"KANON_ALLOW_INSECURE_REMOTES": "1"}
"""The fixture repositories are local `file://` paths, which the remote-URL check
rejects by default. The scenarios that build their own git fixtures all opt out the
same way."""


def _make_content_repos(parent: pathlib.Path) -> None:
    """Create one bare content repo per package, each carrying its own tag.

    Args:
        parent: Directory the repositories are created under; this is the
            directory the manifest's ``fetch`` points at, so each repo's name is
            the project name the manifest resolves beneath it.
    """
    for tag, package_name in _PACKAGE_NAME_BY_TAG.items():
        work = parent / f"{package_name}.work"
        init_git_work_dir(work)
        (work / "payload.txt").write_text(_CONTENT_BY_TAG[tag], encoding="utf-8")
        run_git(["add", "payload.txt"], work)
        run_git(["commit", "-m", f"payload {tag}"], work)
        run_git(["tag", tag], work)
        clone_as_bare(work, parent / f"{package_name}.git")


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
        package_name = _PACKAGE_NAME_BY_TAG[tag]
        (specs / "shared.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_url}" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{package_name}" path=".packages/{package_name}" '
            f'remote="local" revision="refs/tags/{tag}" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        run_git(["add", "repo-specs/shared.xml"], work)
        run_git(["commit", "-m", f"manifest {tag}"], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, parent / "manifest.git")


def _delivered_payload(store: pathlib.Path, project_dir: pathlib.Path, package_name: str) -> str:
    """Return the payload delivered into *project_dir*'s own source workspace.

    Args:
        store: The `<KANON_HOME>/store` directory.
        project_dir: The consuming project's directory.
        package_name: The package this project pinned.

    Returns:
        The contents of the delivered payload file.
    """
    address = project_address_for(project_dir)
    payload = store / ".kanon-data" / "sources" / address / _SHARED_ALIAS / ".packages" / package_name / "payload.txt"
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
        _make_content_repos(content_repos)
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

        after_b = _delivered_payload(store, project_a, _PACKAGE_NAME_BY_TAG["v1"])
        assert after_b == _CONTENT_BY_TAG["v1"], (
            f"Project B's install overwrote project A's content. Expected A to still hold "
            f"{_CONTENT_BY_TAG['v1']!r}, found {after_b!r}."
        )

        second_a = kanon_install(project_a, extra_env=_INSECURE_LOCAL_REMOTES)
        assert second_a.returncode == 0, f"project A re-install failed: {second_a.stderr!r}"

        assert _delivered_payload(store, project_a, _PACKAGE_NAME_BY_TAG["v1"]) == _CONTENT_BY_TAG["v1"], (
            "Re-installing project A did not restore its own pinned content."
        )
        assert _delivered_payload(store, project_b, _PACKAGE_NAME_BY_TAG["v2"]) == _CONTENT_BY_TAG["v2"], (
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


@pytest.mark.scenario
class TestMPRecovery:
    """MP-02 / MP-03: the workspace survives interruption and an older layout.

    Both are states an operator reaches without doing anything unusual -- killing
    an install, or upgrading kanon -- and neither had coverage.
    """

    def test_install_over_a_pre_keying_workspace_succeeds(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        """An alias-named workspace from before keying must not break the install.

        Workspaces used to live at `sources/<alias>/`. After keying, that directory
        is never read again. Install must ignore it rather than trip over it, and
        it must be left in place rather than silently deleted -- `kanon doctor`
        reports it so the operator decides.
        """
        content_repos = tmp_path / "content-repos"
        manifest_repos = tmp_path / "manifest-repos"
        content_repos.mkdir(parents=True)
        manifest_repos.mkdir(parents=True)
        _make_content_repos(content_repos)
        manifest_bare = _make_manifest_repo(manifest_repos, f"{content_repos.as_uri()}/")

        project = scenario_workspace / "upgraded"
        project.mkdir(parents=True)
        write_kanonenv(project, [(_SHARED_ALIAS, f"file://{manifest_bare}", "v1", "repo-specs/shared.xml")])

        store = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        stale = store / ".kanon-data" / "sources" / _SHARED_ALIAS
        stale.mkdir(parents=True)
        (stale / "leftover.txt").write_text("pre-keying workspace\n", encoding="utf-8")

        result = kanon_install(project, extra_env=_INSECURE_LOCAL_REMOTES)
        assert result.returncode == 0, f"install over a pre-keying workspace failed: {result.stderr!r}"

        assert _delivered_payload(store, project, _PACKAGE_NAME_BY_TAG["v1"]) == _CONTENT_BY_TAG["v1"]
        assert (stale / "leftover.txt").is_file(), (
            "the pre-keying workspace must be left for the operator to reclaim, not silently deleted by an install"
        )

    def test_reinstall_after_an_interrupted_install_recovers(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        """A half-built workspace must not wedge the next install.

        The manifests reset now runs before every `repo init`, so a re-run after a
        kill is the first thing to touch a partially-initialised tree. Simulated by
        truncating the synced workspace rather than by raising in-process, which
        leaves no on-disk damage.
        """
        content_repos = tmp_path / "content-repos"
        manifest_repos = tmp_path / "manifest-repos"
        content_repos.mkdir(parents=True)
        manifest_repos.mkdir(parents=True)
        _make_content_repos(content_repos)
        manifest_bare = _make_manifest_repo(manifest_repos, f"{content_repos.as_uri()}/")

        project = scenario_workspace / "interrupted"
        project.mkdir(parents=True)
        write_kanonenv(project, [(_SHARED_ALIAS, f"file://{manifest_bare}", "v1", "repo-specs/shared.xml")])

        first = kanon_install(project, extra_env=_INSECURE_LOCAL_REMOTES)
        assert first.returncode == 0, f"initial install failed: {first.stderr!r}"

        store = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        workspace = store / ".kanon-data" / "sources" / project_address_for(project) / _SHARED_ALIAS
        delivered = workspace / ".packages" / _PACKAGE_NAME_BY_TAG["v1"]
        shutil.rmtree(delivered)

        second = kanon_install(project, extra_env=_INSECURE_LOCAL_REMOTES)
        assert second.returncode == 0, f"re-install after interruption failed: {second.stderr!r}"
        assert _delivered_payload(store, project, _PACKAGE_NAME_BY_TAG["v1"]) == _CONTENT_BY_TAG["v1"], (
            "the re-install did not restore the content the interruption removed"
        )
