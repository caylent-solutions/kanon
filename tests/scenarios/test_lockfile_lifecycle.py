"""Scenario tests: .kanon.lock lifecycle -- pin-retention and refresh-regression guard.

Ports the centerpiece lifecycle properties verified manually in
``test-fixtures/lockfile/`` (see ``test-fixtures/lockfile/FINDINGS.md``) into the
automated ``tests/scenarios/`` suite, per spec S4 EPIC E52 (E52-F1), S9, S10.

Two property groups:

1. **Pin-retention (CENTERPIECE)** -- for each constraint type a fresh plain
   ``kanon install`` REPLAYS the LOCKED version and never silently adopts a newer
   in-range latest published upstream. Covered constraint types (parametrised):
   exact ``==``, compatible-release ``~=``, explicit range ``>=,<``, two-major range
   ``>=1.0,<3.0``, and a branch-ref SHA pin. Each case installs against a multi-tag
   local fixture, records the resolved SHA from ``.kanon.lock``, publishes a newer
   in-range tag, runs a fresh plain install, and asserts the lockfile pin is
   byte-identical (the LOCKED version, not the newer latest). These assertions are
   GREEN immediately because pin-retention is already sound (FINDINGS.md).

2. **Refresh-regression guard (guards LF-BUG-1)** -- install a floating-branch
   catalog source over an existing ``.kanon-data`` checkout, advance the branch tip,
   run ``kanon install --refresh-lock`` / ``--refresh-lock-source <name>``, and
   assert exit 0 + the source pin ADVANCED to the new tip. This was RED against
   pre-E51-F1 code (the envsubst-dirtied ``.repo/manifests`` tree made the re-init
   checkout abort and ``git rev-list ^HEAD <sha>`` raised an unhandled
   ``GitCommandError``, leaving the pin unadvanced -- LF-BUG-1). GREENs after
   E51-F1-S1-T1 lands the BUG-1 fix.

``KANON_ALLOW_INSECURE_REMOTES=1`` is set per-test for ``file://`` fixtures (spec
S3.6). No ``caylent-private-kanon`` runtime dependency (Goal G4).

AC-FUNC-001: TestPinRetention + TestRefreshRegression classes added here.
AC-FUNC-002: TestPinRetention parametrised over ==, ~=, >=<, two-major range, branch-ref.
AC-FUNC-003: each pin-retention case asserts fresh install replays the locked pin.
AC-FUNC-004: TestRefreshRegression covers --refresh-lock and --refresh-lock-source.
AC-FUNC-005: @pytest.mark.scenario; KANON_ALLOW_INSECURE_REMOTES=1 per-test.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import (
    init_git_work_dir,
    make_bare_repo_with_tags,
    make_plain_repo,
    run_git,
)


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


def _sha_for_ref(repo: pathlib.Path, ref: str) -> str:
    """Resolve a git ref to its SHA in the given repo.

    Args:
        repo: Path to a git repository (bare or non-bare).
        ref: Any git ref (branch, tag, HEAD, etc.).

    Returns:
        The 40-character SHA string.
    """
    return _git_capturing(["rev-parse", ref], repo)


def _run_install(
    project_dir: pathlib.Path,
    *,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
    strict_lock: bool = False,
) -> subprocess.CompletedProcess:
    """Invoke ``kanon install [--refresh-lock[--source <name>]] [--strict-lock]`` as a subprocess.

    ``kanon install`` is hermetic (schema v4 / FR-7): it installs exactly the
    sources declared in ``.kanon`` and pinned in ``.kanon.lock`` and never resolves
    a remote catalog. The subprocess is therefore run with ``KANON_CATALOG_SOURCE``
    scrubbed and no ``--catalog-source`` flag; supplying either would be rejected
    fail-fast by ``HermeticInstallCatalogSourceError``.

    ``KANON_ALLOW_INSECURE_REMOTES=1`` is set per-test so ``file://`` fixture URLs
    pass the HTTPS enforcement gate (AC-FUNC-005 / AC-SEC-001).

    Args:
        project_dir: Working directory for the subprocess.
        refresh_lock: When True, passes ``--refresh-lock``.
        refresh_lock_source: When set, passes ``--refresh-lock-source <name>``.
        strict_lock: When True, passes ``--strict-lock`` (npm-ci: error on any drift).

    Returns:
        The completed subprocess result.
    """
    import sys

    cmd = [sys.executable, "-m", "kanon_cli", "install"]
    if refresh_lock:
        cmd.append("--refresh-lock")
    if refresh_lock_source is not None:
        cmd.extend(["--refresh-lock-source", refresh_lock_source])
    if strict_lock:
        cmd.append("--strict-lock")
    env = {
        **os.environ,
        "KANON_ALLOW_INSECURE_REMOTES": "1",
    }
    env.pop("KANON_CATALOG_SOURCE", None)
    return subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_kanon_for_source(
    project_dir: pathlib.Path,
    source_name: str,
    manifest_url: str,
    revision_spec: str,
) -> pathlib.Path:
    """Write a minimal ``.kanon`` file for a single source entry.

    ``KANON_MARKETPLACE_INSTALL=false`` and ``GITBASE`` are set to values that
    allow the install to proceed without a real marketplace checkout.

    Args:
        project_dir: Directory where ``.kanon`` is written.
        source_name: The ``KANON_SOURCE_<name>`` key.
        manifest_url: The ``file://`` URL of the manifest bare repo.
        revision_spec: The PEP 440 constraint or branch ref to track.

    Returns:
        Path to the written ``.kanon`` file.
    """
    lines = [
        "GITBASE=https://unused.example.com",
        f"CLAUDE_MARKETPLACES_DIR={project_dir / 'kanon-test-mktplc'}",
        "KANON_MARKETPLACE_INSTALL=false",
        f"KANON_SOURCE_{source_name}_URL={manifest_url}",
        f"KANON_SOURCE_{source_name}_REF={revision_spec}",
        f"KANON_SOURCE_{source_name}_PATH=manifest.xml",
        f"KANON_SOURCE_{source_name}_NAME={source_name}",
        f"KANON_SOURCE_{source_name}_GITBASE={manifest_url}",
    ]
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text("\n".join(lines) + "\n")
    kanon_path.chmod(0o600)
    return kanon_path


def _build_manifest_repo_with_tags(
    base_dir: pathlib.Path,
    name: str,
    tags: list[str],
    content_dir: pathlib.Path,
) -> tuple[pathlib.Path, str]:
    """Build a manifest bare repo that references a content bare repo, tagged at each version.

    Each tag commit updates ``manifest.xml`` so that the tag's content is distinct
    (no-op same-content commits would collapse to the same SHA under some git configs).
    The ``<project revision>`` inside the manifest is pinned to ``main`` on the
    content repo so that the inner project sync is deterministic regardless of which
    manifest commit is checked out.

    Args:
        base_dir: Parent directory for the repos.
        name: Logical name (used as dir prefix and ``<project name>``).
        tags: PEP 440 version strings to tag (e.g. ["1.0.0", "1.5.0", "2.0.0"]).
        content_dir: Directory whose ``file://`` URI is used as the manifest fetch URL.

    Returns:
        ``(manifest_bare_path, content_fetch_url)`` where ``content_fetch_url`` is
        the ``file://`` URI of ``content_dir`` (the directory containing content
        bare repos).
    """
    content_fetch_url = content_dir.as_uri() + "/"
    manifest_work = base_dir / f"{name}-manifest-work"
    manifest_bare = base_dir / f"{name}-manifest.git"
    manifest_work.mkdir(parents=True, exist_ok=True)
    init_git_work_dir(manifest_work)

    for tag in tags:
        manifest_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_fetch_url}"/>\n'
            '  <default remote="local" revision="main"/>\n'
            f'  <project name="{name}-content" path=".packages/{name}"/>\n'
            f"  <!-- version: {tag} -->\n"
            "</manifest>\n"
        )
        (manifest_work / "manifest.xml").write_text(manifest_xml)
        run_git(["add", "manifest.xml"], manifest_work)
        run_git(["commit", "-m", f"version {tag}"], manifest_work)
        run_git(["tag", "-a", tag, "-m", f"Release {tag}"], manifest_work)

    run_git(["clone", "--bare", str(manifest_work), str(manifest_bare)], base_dir)
    return manifest_bare.resolve(), content_fetch_url


def _add_tag_to_manifest_bare(
    work_root: pathlib.Path,
    manifest_bare: pathlib.Path,
    new_tag: str,
    content_fetch_url: str,
    manifest_project_name: str,
) -> str:
    """Clone the manifest bare repo, add a commit + annotated tag, push; return the new tag SHA.

    Args:
        work_root: Scratch dir for the temporary clone.
        manifest_bare: Absolute path to the manifest bare repo.
        new_tag: Tag name to create (e.g. ``"1.9.0"``).
        content_fetch_url: The ``file://`` fetch URL written in manifest.xml.
        manifest_project_name: The ``<project name>`` in manifest.xml.

    Returns:
        The SHA of the new tag commit.
    """
    clone = work_root / f"push-clone-{new_tag}"
    clone.mkdir(parents=True)
    _git_capturing(["clone", str(manifest_bare), str(clone)], work_root)
    _git_capturing(["config", "user.name", "Test"], clone)
    _git_capturing(["config", "user.email", "t@t.com"], clone)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_url}"/>\n'
        '  <default remote="local" revision="main"/>\n'
        f'  <project name="{manifest_project_name}-content" path=".packages/{manifest_project_name}"/>\n'
        f"  <!-- version: {new_tag} -->\n"
        "</manifest>\n"
    )
    (clone / "manifest.xml").write_text(manifest_xml)
    _git_capturing(["add", "manifest.xml"], clone)
    _git_capturing(["commit", "-m", f"release {new_tag}"], clone)
    _git_capturing(["tag", "-a", new_tag, "-m", f"Release {new_tag}"], clone)
    _git_capturing(["push", "origin", "HEAD:main", "--tags"], clone)
    return _git_capturing(["rev-parse", f"refs/tags/{new_tag}"], clone)


def _build_manifest_source_fixture(
    base_dir: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Build a content repo and a manifest repo referencing it; return both bare paths + fetch URL.

    The manifest XML uses a plain project reference so that the envsubst step still
    rewrites ``manifest.xml`` and creates ``.bak`` files, reproducing the BUG-1
    root cause (dirty working tree blocking the re-init checkout).

    Args:
        base_dir: Parent directory for the fixture repos.
        name: Logical name used to label directories and source entries.

    Returns:
        ``(content_bare, manifest_bare, content_fetch_url)``
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


def _advance_manifest_branch(
    work_root: pathlib.Path,
    manifest_bare: pathlib.Path,
    content_fetch_url: str,
    name: str,
) -> str:
    """Add a commit to the manifest repo's main branch; return the new tip SHA.

    Modifying ``manifest.xml`` in the new commit is essential to reproduce BUG-1:
    the envsubst step rewrites ``manifest.xml`` in the working tree (dirtying it),
    and git refuses to check out the new commit if ``manifest.xml`` also changed
    between commits.

    Args:
        work_root: Scratch directory for the temporary clone.
        manifest_bare: Absolute path to the manifest bare repo.
        content_fetch_url: The ``file://`` URL used in manifest.xml.
        name: Logical source name used in ``<project>``.

    Returns:
        The SHA of the new HEAD commit.
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


def _write_kanon_for_refresh(
    project_dir: pathlib.Path,
    source_name: str,
    manifest_bare: pathlib.Path,
    revision: str,
) -> pathlib.Path:
    """Write a minimal .kanon file tracking a floating branch source.

    Args:
        project_dir: Directory where ``.kanon`` is written.
        source_name: The ``KANON_SOURCE_<name>`` key.
        manifest_bare: Bare manifest repo path (``file://`` URL is derived from this).
        revision: Branch name or ref to track (e.g. ``"main"``).

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


_PIN_RETENTION_CASES: list[tuple[str, list[str], str, str]] = [
    ("exact_eq", ["1.0.0", "1.5.0", "1.7.0"], "==1.7.0", "1.8.0"),
    ("compat_release_tilde", ["1.0.0", "1.5.0", "1.7.0"], "~=1.2", "1.8.0"),
    ("explicit_range_ge_lt", ["1.0.0", "1.5.0", "1.7.0"], ">=1.0,<2.0", "1.9.0"),
    ("two_major_range", ["1.0.0", "2.0.0", "2.1.0"], ">=1.0,<3.0", "2.2.0"),
]


@pytest.mark.scenario
class TestPinRetention:
    """CENTERPIECE: fresh plain install REPLAYS the LOCKED version, never the newer latest.

    Parametrised over the constraint types documented in FINDINGS.md:
    exact ``==``, compatible-release ``~=``, explicit range ``>=,<``, two-major
    range ``>=1.0,<3.0``, and branch-ref SHA pin (AC-FUNC-002).

    Scenario for each case (AC-FUNC-003):
    1. Build a multi-tag manifest fixture via the conftest ``init_git_work_dir`` /
       ``run_git`` primitives and ``make_bare_repo_with_tags`` for the content repo.
    2. Write ``.kanon`` with the constraint and run ``kanon install``.
    3. Record the resolved SHA from ``.kanon.lock``.
    4. Publish a newer in-range (or in-spec) tag on the manifest fixture.
    5. Run a FRESH plain ``kanon install`` (no ``--refresh-lock`` flag).
    6. Assert the lockfile ``resolved_sha`` is byte-identical to step 3 (pin
       retained, newer tag NOT adopted).
    """

    @pytest.mark.parametrize(
        "constraint_id,initial_tags,revision_spec,newer_tag",
        _PIN_RETENTION_CASES,
        ids=[c[0] for c in _PIN_RETENTION_CASES],
    )
    def test_fresh_install_replays_locked_pin_not_newer_tag(
        self,
        tmp_path: pathlib.Path,
        constraint_id: str,
        initial_tags: list[str],
        revision_spec: str,
        newer_tag: str,
    ) -> None:
        """Fresh plain install replays the lockfile-pinned SHA, not the newer in-range tag.

        Guards the CENTERPIECE property: once ``.kanon.lock`` records a resolved SHA,
        subsequent plain installs MUST replay that exact SHA. This assertion is GREEN
        immediately (pin-retention is sound -- FINDINGS.md).

        If this test fails, the pin-retention contract is broken. Surface:
        - The constraint type (``revision_spec``).
        - The locked SHA vs the SHA after the second install.
        - The byte diff of ``.kanon.lock`` between the two installs so the reviewer
          can determine whether a resolver regression must be escalated.

        Args:
            tmp_path: pytest-provided temporary directory.
            constraint_id: Short label for the constraint type (used in messages).
            initial_tags: Version tags to publish before the first install.
            revision_spec: PEP 440 constraint or branch ref written to ``.kanon``.
            newer_tag: In-range tag published after the initial install.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        content_bare_dir = fixtures / "content"
        content_bare_dir.mkdir()
        make_bare_repo_with_tags(content_bare_dir, f"{constraint_id}-content", initial_tags)

        manifest_bare, content_fetch_url = _build_manifest_repo_with_tags(
            fixtures,
            constraint_id,
            initial_tags,
            content_bare_dir,
        )

        _write_kanon_for_source(project, constraint_id.upper(), manifest_bare.as_uri(), revision_spec)

        r1 = _run_install(project)
        assert r1.returncode == 0, (
            f"[{constraint_id}] Initial kanon install failed (exit {r1.returncode}):"
            f"\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), f"[{constraint_id}] .kanon.lock not created after initial install"
        locked_sha = _resolved_sha_from_lock(lock_path, constraint_id.upper())
        locked_content = lock_path.read_bytes()

        _add_tag_to_manifest_bare(scratch, manifest_bare, newer_tag, content_fetch_url, constraint_id)

        kanon_data = project / ".kanon-data"
        if kanon_data.exists():
            import shutil

            shutil.rmtree(str(kanon_data))

        r2 = _run_install(project)
        assert r2.returncode == 0, (
            f"[{constraint_id}] Fresh plain install failed (exit {r2.returncode}):"
            f"\nstdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        replayed_sha = _resolved_sha_from_lock(lock_path, constraint_id.upper())
        replayed_content = lock_path.read_bytes()

        assert replayed_sha == locked_sha, (
            f"ERROR: [{constraint_id}] pin-retention contract broken for revision_spec={revision_spec!r}.\n"
            f"  Fresh plain install adopted the newer tag instead of replaying the locked version.\n"
            f"  Locked SHA    : {locked_sha!r}\n"
            f"  Replayed SHA  : {replayed_sha!r}\n"
            f"  Newer in-range tag: {newer_tag!r}\n"
            f"  .kanon.lock diff: before={locked_content!r} after={replayed_content!r}\n"
            f"  Escalate if the resolver has regressed."
        )
        assert replayed_content == locked_content, (
            f"ERROR: [{constraint_id}] .kanon.lock byte content changed after fresh plain install "
            f"(revision_spec={revision_spec!r}). The lockfile was mutated without --refresh-lock.\n"
            f"  Before: {locked_content!r}\n"
            f"  After : {replayed_content!r}"
        )

    def test_branch_ref_fresh_install_replays_locked_sha_not_new_tip(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Branch-ref pin: fresh plain install replays the locked SHA even after branch tip advances.

        Constraint type: branch-ref SHA pin (last entry from FINDINGS.md CENTERPIECE).
        The source tracks ``main`` (a floating branch). After the initial install the
        tip SHA is pinned in ``.kanon.lock``. A new commit is pushed to ``main``. A
        FRESH plain install (no --refresh-lock) must replay the locked SHA, not
        checkout the new tip.

        This is the branch-ref row from FINDINGS.md -- demonstrating that pin
        retention applies to branch-ref sources too (once locked, stays locked).
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        content_bare_dir = fixtures / "content"
        content_bare_dir.mkdir()
        make_bare_repo_with_tags(content_bare_dir, "branchref-content", ["1.0.0"])

        manifest_bare, _ = _build_manifest_repo_with_tags(
            fixtures,
            "branchref",
            ["1.0.0"],
            content_bare_dir,
        )

        _write_kanon_for_source(project, "BRANCHREF", manifest_bare.as_uri(), "main")

        r1 = _run_install(project)
        assert r1.returncode == 0, (
            f"Initial kanon install failed (exit {r1.returncode}):\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), ".kanon.lock not created after initial install"
        locked_sha = _resolved_sha_from_lock(lock_path, "BRANCHREF")
        locked_content = lock_path.read_bytes()

        clone = scratch / "branch-advance-clone"
        clone.mkdir()
        _git_capturing(["clone", str(manifest_bare), str(clone)], scratch)
        _git_capturing(["config", "user.name", "Test"], clone)
        _git_capturing(["config", "user.email", "t@t.com"], clone)
        (clone / "ADVANCE.md").write_text("branch advance\n")
        _git_capturing(["add", "ADVANCE.md"], clone)
        _git_capturing(["commit", "-m", "advance branch tip"], clone)
        _git_capturing(["push", "origin", "HEAD:main"], clone)
        new_tip_sha = _git_capturing(["rev-parse", "HEAD"], clone)
        assert new_tip_sha != locked_sha, "Fixture setup error: new tip SHA must differ from locked SHA"

        kanon_data = project / ".kanon-data"
        if kanon_data.exists():
            import shutil

            shutil.rmtree(str(kanon_data))

        r2 = _run_install(project)
        assert r2.returncode == 0, (
            f"Fresh plain install failed (exit {r2.returncode}):\nstdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        replayed_sha = _resolved_sha_from_lock(lock_path, "BRANCHREF")
        replayed_content = lock_path.read_bytes()

        assert replayed_sha == locked_sha, (
            f"ERROR: branch-ref pin-retention broken.\n"
            f"  Fresh plain install adopted the new branch tip instead of replaying the locked SHA.\n"
            f"  Locked SHA  : {locked_sha!r}\n"
            f"  Replayed SHA: {replayed_sha!r}\n"
            f"  New tip SHA : {new_tip_sha!r}\n"
            f"  .kanon.lock diff: before={locked_content!r} after={replayed_content!r}\n"
            f"  Escalate if the resolver has regressed."
        )
        assert replayed_content == locked_content, (
            f"ERROR: branch-ref .kanon.lock byte content changed after fresh plain install. "
            f"The lockfile was mutated without --refresh-lock.\n"
            f"  Before: {locked_content!r}\n"
            f"  After : {replayed_content!r}"
        )


@pytest.mark.scenario
class TestRefreshRegression:
    """Refresh-regression guard: --refresh-lock[-source] advances over an existing checkout (LF-BUG-1).

    Both tests exercise the operator path: subprocess ``kanon install`` against
    local ``file://`` fixtures, with no ``caylent-private-kanon`` runtime dep
    (AC-FUNC-004, AC-FUNC-005, Goal G4).

    These tests were RED against pre-E51-F1 code (the envsubst-dirtied
    ``.repo/manifests`` tree caused an unhandled ``GitCommandError`` on re-init,
    leaving the pin unadvanced). They GREEN after E51-F1-S1-T1 lands the BUG-1 fix.
    """

    def test_refresh_lock_advances_over_existing_checkout(self, tmp_path: pathlib.Path) -> None:
        """--refresh-lock exits 0 and advances the pin when main moved, over existing .kanon-data.

        Scenario (BUG-1 regression guard):
        1. Build a manifest bare repo whose main branch has an initial commit.
        2. Build a catalog bare repo (required by kanon install).
        3. Write .kanon tracking the manifest @main.
        4. ``kanon install`` -- populates .kanon-data; envsubst dirties .repo/manifests.
        5. Advance main in the manifest repo (new commit that also changes manifest.xml).
        6. ``kanon install --refresh-lock`` -- MUST exit 0 and advance the lockfile pin.

        Before the fix (pre-E51-F1): step 6 raised an unhandled GitCommandError
        (``fatal: bad revision '^HEAD'``, exit 1). After the fix it exits 0 and the
        pin advances.

        If this assertion fails after E51-F1-S1-T1 has landed, the BUG-1 fix has
        regressed. Surface the raw exit code, stdout/stderr, and the unadvanced pin
        so the reviewer can decide whether to amend E51-F1 scope.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        _content_bare, manifest_bare, content_fetch_url = _build_manifest_source_fixture(fixtures / "src", "SRC")

        _write_kanon_for_refresh(project, "SRC", manifest_bare, "main")

        r1 = _run_install(project)
        assert r1.returncode == 0, (
            f"Initial kanon install failed (exit {r1.returncode}):\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), ".kanon.lock not created after initial install"
        sha_before = _resolved_sha_from_lock(lock_path, "SRC")

        advance_root = tmp_path / "advance"
        advance_root.mkdir()
        sha_new_tip = _advance_manifest_branch(advance_root, manifest_bare, content_fetch_url, "SRC")
        assert sha_new_tip != sha_before, "Fixture setup error: new tip SHA must differ from the initial SHA"

        r2 = _run_install(project, refresh_lock=True)
        assert r2.returncode == 0, (
            f"ERROR: kanon install --refresh-lock failed (exit {r2.returncode}) over existing checkout.\n"
            f"  If E51-F1-S1-T1 has landed, this is a real regression of the BUG-1 fix.\n"
            f"  stdout={r2.stdout!r}\n  stderr={r2.stderr!r}"
        )
        sha_after = _resolved_sha_from_lock(lock_path, "SRC")
        assert sha_after == sha_new_tip, (
            f"ERROR: kanon install --refresh-lock over existing checkout left pin unadvanced.\n"
            f"  Expected: {sha_new_tip!r}\n"
            f"  Got     : {sha_after!r}\n"
            f"  Was     : {sha_before!r}\n"
            f"  stdout={r2.stdout!r}\n  stderr={r2.stderr!r}"
        )

    def test_refresh_lock_source_advances_over_existing_checkout(self, tmp_path: pathlib.Path) -> None:
        """--refresh-lock-source <name> exits 0 and advances the named pin over existing .kanon-data.

        Same scenario as ``test_refresh_lock_advances_over_existing_checkout`` but
        exercises the ``--refresh-lock-source`` flag instead of ``--refresh-lock``.
        Both flags trigger the same envsubst-dirty -> re-init crash path (BUG-1).

        If this assertion fails after E51-F1-S1-T1 has landed, the BUG-1 fix has
        regressed on the ``--refresh-lock-source`` code path. Surface the raw exit
        code, stdout/stderr, and the unadvanced pin.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        _content_bare, manifest_bare, content_fetch_url = _build_manifest_source_fixture(fixtures / "src", "SRC")

        _write_kanon_for_refresh(project, "SRC", manifest_bare, "main")

        r1 = _run_install(project)
        assert r1.returncode == 0, (
            f"Initial kanon install failed (exit {r1.returncode}):\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        )
        lock_path = project / ".kanon.lock"
        assert lock_path.exists(), ".kanon.lock not created after initial install"
        sha_before = _resolved_sha_from_lock(lock_path, "SRC")

        advance_root = tmp_path / "advance"
        advance_root.mkdir()
        sha_new_tip = _advance_manifest_branch(advance_root, manifest_bare, content_fetch_url, "SRC")
        assert sha_new_tip != sha_before, "Fixture setup error: new tip SHA must differ from the initial SHA"

        r2 = _run_install(project, refresh_lock_source="SRC")
        assert r2.returncode == 0, (
            f"ERROR: kanon install --refresh-lock-source SRC failed (exit {r2.returncode}) "
            f"over existing checkout.\n"
            f"  If E51-F1-S1-T1 has landed, this is a real regression of the BUG-1 fix.\n"
            f"  stdout={r2.stdout!r}\n  stderr={r2.stderr!r}"
        )
        sha_after = _resolved_sha_from_lock(lock_path, "SRC")
        assert sha_after == sha_new_tip, (
            f"ERROR: kanon install --refresh-lock-source SRC over existing checkout left pin unadvanced.\n"
            f"  Expected: {sha_new_tip!r}\n"
            f"  Got     : {sha_after!r}\n"
            f"  Was     : {sha_before!r}\n"
            f"  stdout={r2.stdout!r}\n  stderr={r2.stderr!r}"
        )
