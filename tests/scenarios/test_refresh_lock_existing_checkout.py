"""Scenario tests: --refresh-lock[-source] succeeds on an existing .kanon-data checkout (BUG-1).

Documents and locks the fix from spec S.0 / E51-F1:

  ``kanon install --refresh-lock`` and ``kanon install --refresh-lock-source <name>``
  MUST advance the lockfile pin when the manifest's branch tip moved, even when
  ``.kanon-data`` was already populated by a prior install.

Prior to the fix, kanon's ``repo envsubst`` step dirtied the ``.repo/manifests``
working tree (rewriting XML files and creating ``.bak`` files). On the second
``kanon install --refresh-lock``, the repo re-init attempted to check out the new
manifest commit over the dirty working tree, failed with "local changes would be
overwritten", and a follow-on ``git rev-list ^HEAD <sha>`` raised an unhandled
``GitCommandError`` ("fatal: bad revision '^HEAD'", exit 1), leaving the pin
unadvanced.

After the fix:
  - The ``.repo/manifests`` working tree is restored (dirty files reset, ``.bak``
    removed) before re-init, so the checkout to the moved manifest commit succeeds.
  - Any genuine git failure on the refresh path is re-raised as a kanon ``ERROR:``
    with the offending source name and remediation hint; no raw traceback reaches
    the operator.

These are subprocess (operator-path) tests: each test invokes ``kanon install``
as a real subprocess against on-disk fixture git repos, reads the resulting
``.kanon.lock``, and asserts the SHA advanced.

AC-TEST-001: test_refresh_lock_advances_over_existing_checkout and
             test_refresh_lock_source_advances_over_existing_checkout added here.
AC-TEST-002: RED->GREEN transition recorded in the TDD Cycle Log.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import init_git_work_dir, make_plain_repo, run_git


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _git_capturing(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command and return stripped stdout; raise RuntimeError on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} failed in {cwd!r} (exit {result.returncode}):"
            f"\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    return result.stdout.strip()


def _build_manifest_source_fixture(
    base_dir: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Build a content repo and a manifest repo that references it, both bare.

    The manifest XML uses a plain project reference (no ``${VAR}`` placeholders);
    the envsubst step still rewrites XML files and creates ``.bak`` files, which
    is the root cause of BUG-1.

    Args:
        base_dir: Parent directory for the fixture repos.
        name: Logical name used to label directories and source entries.

    Returns:
        ``(content_bare, manifest_bare, content_fetch_url)`` -- absolute paths to
        both bare repos and the ``file://`` fetch URL used in manifest.xml so the
        caller can construct an updated manifest for the advanced commit.
    """
    content_dir = base_dir / "content"
    manifest_dir = base_dir / "manifest"
    content_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    content_bare = make_plain_repo(content_dir, f"{name}-content", {"README.md": f"# {name}\n"})
    content_fetch_url = content_dir.as_uri() + "/"

    manifest_work = manifest_dir / f"{name}-work"
    manifest_work.mkdir(parents=True)
    init_git_work_dir(manifest_work)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_url}"/>\n'
        '  <default remote="local" revision="main"/>\n'
        f'  <project name="{name}-content" path=".packages/{name}"/>\n'
        "</manifest>\n"
    )
    (manifest_work / "manifest.xml").write_text(manifest_xml)
    run_git(["add", "manifest.xml"], manifest_work)
    run_git(["commit", "-m", "Initial manifest"], manifest_work)
    run_git(["tag", "-a", "1.0.0", "-m", "Release 1.0.0"], manifest_work)

    manifest_bare = manifest_dir / f"{name}.git"
    run_git(["clone", "--bare", str(manifest_work), str(manifest_bare)], manifest_dir)
    return content_bare, manifest_bare.resolve(), content_fetch_url


def _build_catalog_fixture(base_dir: pathlib.Path) -> pathlib.Path:
    """Build a minimal bare catalog repo with a tagged commit on ``main``.

    The catalog repo only needs to exist and be fetchable; it does not need
    actual entry XML files for these tests.

    Args:
        base_dir: Parent directory where the catalog bare repo is created.

    Returns:
        Absolute path to the bare catalog repo.
    """
    work = base_dir / "catalog-work"
    work.mkdir(parents=True, exist_ok=True)
    init_git_work_dir(work)
    (work / "repo-specs" / ".gitkeep").parent.mkdir(parents=True)
    (work / "repo-specs" / ".gitkeep").write_text("")
    run_git(["add", "repo-specs"], work)
    run_git(["commit", "-m", "Initial catalog"], work)
    run_git(["tag", "-a", "1.0.0", "-m", "Release 1.0.0"], work)

    bare = base_dir / "catalog.git"
    run_git(["clone", "--bare", str(work), str(bare)], base_dir)
    return bare.resolve()


def _advance_manifest_branch(
    work_root: pathlib.Path,
    manifest_bare: pathlib.Path,
    content_fetch_url: str,
    name: str,
) -> str:
    """Add a commit to the manifest repo's main branch that also changes manifest.xml.

    Modifying manifest.xml in the new commit is required to reproduce BUG-1: the
    envsubst step rewrites manifest.xml in the working tree (dirtying it), and git
    refuses to checkout the new commit if manifest.xml also changed between commits
    ("Your local changes to the following files would be overwritten by checkout").
    After the refused checkout, HEAD still points to the deleted ``default`` branch,
    causing ``git rev-list ^HEAD <newsha>`` to fail with "fatal: bad revision '^HEAD'".

    Args:
        work_root: Scratch directory for the temporary clone.
        manifest_bare: Absolute path to the manifest bare repo.
        content_fetch_url: The ``file://`` URL used in manifest.xml's ``<remote>`` element.
        name: Logical source name used in the manifest's ``<project>`` element.

    Returns:
        The SHA of the new HEAD commit (the new ``main`` tip in the bare repo).
    """
    clone = work_root / f"advance-clone-{manifest_bare.name}"
    clone.mkdir(parents=True)
    _git_capturing(["clone", str(manifest_bare), str(clone)], work_root)
    _git_capturing(["config", "user.name", "Test"], clone)
    _git_capturing(["config", "user.email", "t@t.com"], clone)

    updated_manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_url}"/>\n'
        '  <default remote="local" revision="main"/>\n'
        f'  <project name="{name}-content" path=".packages/{name}"/>\n'
        "  <!-- advanced: v2 -->\n"
        "</manifest>\n"
    )
    (clone / "manifest.xml").write_text(updated_manifest_xml)
    _git_capturing(["add", "manifest.xml"], clone)
    _git_capturing(["commit", "-m", "advance branch tip with updated manifest.xml"], clone)
    _git_capturing(["push", "origin", "HEAD:main"], clone)
    return _git_capturing(["rev-parse", "HEAD"], clone)


def _write_kanon_file(
    project_dir: pathlib.Path,
    source_name: str,
    manifest_bare: pathlib.Path,
    revision: str,
) -> pathlib.Path:
    """Write a minimal .kanon file for a single source tracked at ``revision``.

    Args:
        project_dir: Directory where ``.kanon`` is written.
        source_name: KANON_SOURCE_<name> key.
        manifest_bare: Bare manifest repo path (``file://`` URL is derived from this).
        revision: Branch, tag, or SHA to track.

    Returns:
        Path to the written ``.kanon`` file.
    """
    url = manifest_bare.as_uri()
    lines = [
        f"KANON_SOURCE_{source_name}_URL={url}",
        f"KANON_SOURCE_{source_name}_REF={revision}",
        f"KANON_SOURCE_{source_name}_PATH=manifest.xml",
        f"KANON_SOURCE_{source_name}_NAME={source_name}",
        f"KANON_SOURCE_{source_name}_GITBASE={url}",
    ]
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text("\n".join(lines) + "\n")
    kanon_path.chmod(0o600)
    return kanon_path


def _run_install(
    project_dir: pathlib.Path,
    catalog_uri: str,
    *,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke ``kanon install [--refresh-lock[--source <name>]]`` as a subprocess.

    ``KANON_ALLOW_INSECURE_REMOTES=1`` is set per-test so ``file://`` fixture URLs
    pass the HTTPS enforcement gate (AC-SEC-001).

    Args:
        project_dir: Working directory for the subprocess.
        catalog_uri: Catalog source URI passed via ``KANON_CATALOG_SOURCE``.
        refresh_lock: When True, passes ``--refresh-lock``.
        refresh_lock_source: When set, passes ``--refresh-lock-source <name>``.

    Returns:
        The completed subprocess result.
    """
    import sys

    cmd = [sys.executable, "-m", "kanon_cli", "install"]
    if refresh_lock:
        cmd.append("--refresh-lock")
    if refresh_lock_source is not None:
        cmd.extend(["--refresh-lock-source", refresh_lock_source])
    env = {
        **os.environ,
        "KANON_ALLOW_INSECURE_REMOTES": "1",
        "KANON_CATALOG_SOURCE": catalog_uri,
    }
    return subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _resolved_sha_from_lock(lock_path: pathlib.Path, source_name: str) -> str:
    """Return the ``resolved_sha`` for ``source_name`` from the lockfile at ``lock_path``.

    Args:
        lock_path: Path to ``.kanon.lock``.
        source_name: Name of the source entry to look up.

    Returns:
        The ``resolved_sha`` string.

    Raises:
        KeyError: If the source is not present in the lockfile.
    """
    lf = read_lockfile(lock_path)
    for entry in lf.sources:
        if entry.name == source_name:
            return entry.resolved_sha
    known = [e.name for e in lf.sources]
    raise KeyError(f"Source {source_name!r} not found in lockfile; known: {known!r}")


@pytest.mark.scenario
class TestRefreshLockExistingCheckout:
    """BUG-1 fix: --refresh-lock[-source] survives an existing .kanon-data checkout.

    Both tests exercise the operator path: subprocess ``kanon install`` against
    local ``file://`` fixtures, with no ``caylent-private-kanon`` runtime dep
    (AC-SEC-001 / Goal G4).
    """

    def test_refresh_lock_advances_over_existing_checkout(self, tmp_path: pathlib.Path) -> None:
        """--refresh-lock exits 0 and advances the pin when main moved, over existing .kanon-data.

        Scenario (BUG-1 regression guard):
        1. Build a manifest bare repo whose main branch has an initial commit.
        2. Build a catalog bare repo (required by kanon install).
        3. Write .kanon tracking the manifest @main.
        4. ``kanon install`` -- populates .kanon-data; envsubst dirties .repo/manifests.
        5. Advance main in the manifest repo (new commit).
        6. ``kanon install --refresh-lock`` -- MUST exit 0 and advance the lockfile pin.

        Today (before the fix) step 6 raises an unhandled GitCommandError
        ("fatal: bad revision '^HEAD'", exit 1). After the fix it exits 0.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        _content_bare, manifest_bare, content_fetch_url = _build_manifest_source_fixture(fixtures / "src", "SRC")
        catalog_bare = _build_catalog_fixture(fixtures / "catalog")
        catalog_uri = f"{catalog_bare.as_uri()}@main"

        _write_kanon_file(project, "SRC", manifest_bare, "main")

        r1 = _run_install(project, catalog_uri)
        assert r1.returncode == 0, (
            f"Initial kanon install failed (exit {r1.returncode}):\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), ".kanon.lock not created after initial install"
        sha_before = _resolved_sha_from_lock(lock_path, "SRC")

        advance_root = tmp_path / "advance"
        advance_root.mkdir()
        sha_new_tip = _advance_manifest_branch(advance_root, manifest_bare, content_fetch_url, "SRC")
        assert sha_new_tip != sha_before, "New tip SHA should differ from the initial SHA -- fixture setup error"

        r2 = _run_install(project, catalog_uri, refresh_lock=True)
        assert r2.returncode == 0, (
            f"kanon install --refresh-lock failed (exit {r2.returncode}) over existing checkout:\n"
            f"stdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        sha_after = _resolved_sha_from_lock(lock_path, "SRC")
        assert sha_after == sha_new_tip, (
            f"Expected lockfile pin to advance to new tip {sha_new_tip!r}, but got {sha_after!r} (was {sha_before!r})"
        )

    def test_refresh_lock_source_advances_over_existing_checkout(self, tmp_path: pathlib.Path) -> None:
        """--refresh-lock-source <name> exits 0 and advances the named pin over existing .kanon-data.

        Same scenario as ``test_refresh_lock_advances_over_existing_checkout`` but
        exercises the ``--refresh-lock-source`` flag instead of ``--refresh-lock``.
        Both flags trigger the same envsubst-dirty -> re-init crash path.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        _content_bare, manifest_bare, content_fetch_url = _build_manifest_source_fixture(fixtures / "src", "SRC")
        catalog_bare = _build_catalog_fixture(fixtures / "catalog")
        catalog_uri = f"{catalog_bare.as_uri()}@main"

        _write_kanon_file(project, "SRC", manifest_bare, "main")

        r1 = _run_install(project, catalog_uri)
        assert r1.returncode == 0, (
            f"Initial kanon install failed (exit {r1.returncode}):\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), ".kanon.lock not created after initial install"
        sha_before = _resolved_sha_from_lock(lock_path, "SRC")

        advance_root = tmp_path / "advance"
        advance_root.mkdir()
        sha_new_tip = _advance_manifest_branch(advance_root, manifest_bare, content_fetch_url, "SRC")
        assert sha_new_tip != sha_before, "New tip SHA should differ from the initial SHA -- fixture setup error"

        r2 = _run_install(project, catalog_uri, refresh_lock_source="SRC")
        assert r2.returncode == 0, (
            f"kanon install --refresh-lock-source SRC failed (exit {r2.returncode}) over existing checkout:\n"
            f"stdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        sha_after = _resolved_sha_from_lock(lock_path, "SRC")
        assert sha_after == sha_new_tip, (
            f"Expected lockfile pin to advance to new tip {sha_new_tip!r}, but got {sha_after!r} (was {sha_before!r})"
        )
