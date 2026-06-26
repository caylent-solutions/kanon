"""Scenario tests: npm-style content-SHA locking (spec Section 5.2 / FR-22).

A ``<project revision>`` in a synced manifest may be an exact deep-path tag, a
branch ref (``refs/heads/<name>``), or a 40-hex commit SHA.  On the first
install kanon resolves each ``<project>`` to a content commit SHA and records it
as a per-source v5 content pin (``[[sources.content_pins]]``).  A subsequent
plain install REPLAYS the locked content SHA byte-for-byte -- a branch tip that
advances upstream is NOT silently adopted; only an explicit ``--refresh-lock``
re-resolves the tip.  This mirrors npm's ``#main`` + ``package-lock``.

These scenarios stand up real local git repos (a content repo and a manifest
repo that references it) and drive the real ``kanon install`` subprocess against
``file://`` fixtures, exactly as a human would.  ``KANON_ALLOW_INSECURE_REMOTES=1``
is set per-test so the ``file://`` URLs pass the HTTPS enforcement gate.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import init_git_work_dir, run_git


def _git_out(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command and return its stripped stdout; raise on failure."""
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}: {result.stderr!r}")
    return result.stdout.strip()


def _make_content_repo(parent: pathlib.Path, name: str) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Create a content repo with one commit on ``main`` and a tag ``1.0.0``.

    Args:
        parent: Parent directory for the repos.
        name: Logical repo name.

    Returns:
        A ``(work_dir, bare_dir, tag_commit_sha)`` triple where ``work_dir`` is the
        non-bare working clone (used to advance the branch tip later) and
        ``bare_dir`` is the fetchable bare repo.
    """
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    (work / "file.txt").write_text("v1")
    run_git(["add", "file.txt"], work)
    run_git(["commit", "-m", "c1"], work)
    run_git(["tag", "1.0.0"], work)
    run_git(["clone", "--bare", str(work), str(bare)], parent)
    tag_sha = _git_out(["rev-parse", "1.0.0"], work)
    return work, bare.resolve(), tag_sha


def _make_manifest_repo(parent: pathlib.Path, fetch_url: str, project_name: str, revision: str) -> pathlib.Path:
    """Create a manifest bare repo referencing ``project_name`` at ``revision``.

    Args:
        parent: Parent directory for the repos.
        fetch_url: The ``file://`` fetch base for the content remote.
        project_name: The ``<project name>`` (the content bare repo basename).
        revision: The ``<project revision>`` (a tag, a ``refs/heads/<name>`` ref,
            or a 40-hex SHA).

    Returns:
        The absolute path to the manifest bare repo.
    """
    work = parent / "manifest.work"
    bare = parent / "manifest.git"
    init_git_work_dir(work)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default remote="origin" revision="refs/heads/main" />\n'
        f'  <project name="{project_name}" path="content" revision="{revision}" />\n'
        "</manifest>\n"
    )
    specs = work / "repo-specs"
    specs.mkdir()
    (specs / "meta.xml").write_text(manifest_xml)
    run_git(["add", "repo-specs/meta.xml"], work)
    run_git(["commit", "-m", "manifest"], work)
    run_git(["clone", "--bare", str(work), str(bare)], parent)
    return bare.resolve()


def _write_kanon(project_dir: pathlib.Path, alias: str, manifest_url: str, revision: str) -> pathlib.Path:
    """Write a single-source ``.kanon`` file referencing the manifest repo."""
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"KANON_SOURCE_{alias}_URL={manifest_url}\n"
        f"KANON_SOURCE_{alias}_REF={revision}\n"
        f"KANON_SOURCE_{alias}_PATH=repo-specs/meta.xml\n"
        f"KANON_SOURCE_{alias}_NAME={alias}\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _install(project_dir: pathlib.Path, kanon_home: pathlib.Path, *flags: str) -> subprocess.CompletedProcess:
    """Run ``kanon install [flags]`` as a subprocess against ``file://`` fixtures."""
    env = {**os.environ, "KANON_ALLOW_INSECURE_REMOTES": "1", "KANON_HOME": str(kanon_home)}
    env.pop("KANON_CATALOG_SOURCE", None)
    env.pop("KANON_CATALOG_SOURCES", None)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "install", *flags],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _content_pin(lock_path: pathlib.Path, alias: str, project_name: str) -> str:
    """Return the locked content-pin ``resolved_sha`` for a project in a source."""
    lockfile = read_lockfile(lock_path)
    for source in lockfile.sources:
        if source.alias != alias:
            continue
        for pin in source.content_pins:
            if pin.name == project_name:
                return pin.resolved_sha
    raise KeyError(f"no content pin for {alias}/{project_name} in {lock_path}")


def _advance_main(content_work: pathlib.Path, content_bare: pathlib.Path) -> str:
    """Add a commit to the content repo's ``main`` and push it; return the new tip SHA."""
    (content_work / "file.txt").write_text("v2")
    run_git(["add", "file.txt"], content_work)
    run_git(["commit", "-m", "c2"], content_work)
    run_git(["push", str(content_bare), "main"], content_work)
    return _git_out(["rev-parse", "HEAD"], content_work)


@pytest.mark.scenario
def test_exact_tag_revision_pins_tag_content_sha(tmp_path: pathlib.Path) -> None:
    """A ``<project revision>`` exact tag locks the tag's content SHA and replays it."""
    content_work, content_bare, tag_sha = _make_content_repo(tmp_path, "content")
    manifest_bare = _make_manifest_repo(tmp_path, content_bare.parent.as_uri() + "/", "content.git", "refs/tags/1.0.0")
    ws = tmp_path / "ws"
    ws.mkdir()
    kanon_home = tmp_path / "kh"
    _write_kanon(ws, "dep", manifest_bare.as_uri(), "refs/heads/main")

    result = _install(ws, kanon_home)
    assert result.returncode == 0, result.stderr

    locked = _content_pin(ws / ".kanon.lock", "dep", "content.git")
    assert locked == tag_sha

    replay = _install(ws, kanon_home)
    assert replay.returncode == 0, replay.stderr
    assert _content_pin(ws / ".kanon.lock", "dep", "content.git") == tag_sha


@pytest.mark.scenario
def test_branch_revision_pins_tip_and_replays_after_advance(tmp_path: pathlib.Path) -> None:
    """A branch ``<project revision>`` locks the tip SHA; a reinstall replays it after the branch advances."""
    content_work, content_bare, _tag_sha = _make_content_repo(tmp_path, "content")
    manifest_bare = _make_manifest_repo(tmp_path, content_bare.parent.as_uri() + "/", "content.git", "refs/heads/main")
    ws = tmp_path / "ws"
    ws.mkdir()
    kanon_home = tmp_path / "kh"
    _write_kanon(ws, "dep", manifest_bare.as_uri(), "refs/heads/main")

    result = _install(ws, kanon_home)
    assert result.returncode == 0, result.stderr
    locked = _content_pin(ws / ".kanon.lock", "dep", "content.git")

    new_tip = _advance_main(content_work, content_bare)
    assert new_tip != locked

    replay = _install(ws, kanon_home)
    assert replay.returncode == 0, replay.stderr
    assert _content_pin(ws / ".kanon.lock", "dep", "content.git") == locked

    checkout_head = _git_out(
        ["rev-parse", "HEAD"], kanon_home / "store" / ".kanon-data" / "sources" / "dep" / "content"
    )
    assert checkout_head == locked


@pytest.mark.scenario
def test_refresh_lock_advances_branch_content_pin(tmp_path: pathlib.Path) -> None:
    """``--refresh-lock`` re-resolves the branch tip and updates the content pin."""
    content_work, content_bare, _tag_sha = _make_content_repo(tmp_path, "content")
    manifest_bare = _make_manifest_repo(tmp_path, content_bare.parent.as_uri() + "/", "content.git", "refs/heads/main")
    ws = tmp_path / "ws"
    ws.mkdir()
    kanon_home = tmp_path / "kh"
    _write_kanon(ws, "dep", manifest_bare.as_uri(), "refs/heads/main")

    result = _install(ws, kanon_home)
    assert result.returncode == 0, result.stderr
    locked = _content_pin(ws / ".kanon.lock", "dep", "content.git")

    new_tip = _advance_main(content_work, content_bare)
    assert new_tip != locked

    refreshed = _install(ws, kanon_home, "--refresh-lock")
    assert refreshed.returncode == 0, refreshed.stderr
    assert _content_pin(ws / ".kanon.lock", "dep", "content.git") == new_tip
