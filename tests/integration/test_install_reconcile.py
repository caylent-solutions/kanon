"""Integration tests: npm-like ``kanon install`` reconcile of ``.kanon`` <-> lock.

Bug guard: ``install-orphan-rescue-crash-and-lock-corruption``.

Plain ``kanon install`` reconciles the lockfile to the current ``.kanon`` the
way ``npm install`` reconciles ``package.json`` to ``package-lock.json``:

- removed sources (orphans) are pruned,
- newly-added AND changed-spec sources are resolved fresh,
- unchanged sources preserve their locked SHA (replay, no re-resolve),
- the lock is rebuilt and written ONCE at the end, on success only.

``kanon install --strict-lock`` is the ``npm ci`` analogue: it errors cleanly on
ANY drift and NEVER mutates the lockfile.

These tests use real local fixture git repos (no network) so ``git ls-remote``
works for fresh resolution, with the repo tool calls
(``repo_init``/``repo_envsubst``/``repo_sync``) mocked because the embedded repo
tool requires a fully-configured XML manifest repo.  ``_resolve_ref_to_sha`` is
patched only for the synthetic catalog URL; real local source repos resolve
through the unpatched implementation so the recorded SHAs are genuine.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    KanonHashMismatchError,
    OrphanedLockEntryError,
    _RefResolution,
    install,
)
from kanon_cli.core.lockfile import read_lockfile


# ---------------------------------------------------------------------------
# Override autouse conftest fixtures: this module uses real local git repos.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: let the test's own patch handle _resolve_ref_to_sha."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: let the test's own subprocess.run patches handle reachability."""
    yield


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: pathlib.Path) -> str:
    """Run a git command and return stdout; raise RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def _sha_for_ref(repo_path: pathlib.Path, ref: str) -> str:
    """Return the SHA that ``ref`` resolves to in ``repo_path``."""
    return _git("rev-parse", ref, cwd=repo_path)


def _build_repo_with_tag(base_dir: pathlib.Path, name: str, tag: str) -> tuple[pathlib.Path, str]:
    """Create a fixture git repo named ``name`` with one commit tagged ``tag``.

    Returns ``(repo_path, sha_for_tag)``.
    """
    repo = base_dir / name
    repo.mkdir(parents=True)
    _git("init", cwd=repo)
    _git("checkout", "-b", "main", cwd=repo)
    (repo / "README.md").write_text(f"{name} {tag}\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", f"initial {tag}", cwd=repo)
    _git("tag", tag, cwd=repo)
    return repo, _sha_for_ref(repo, f"refs/tags/{tag}")


def _add_tag(repo_path: pathlib.Path, tag: str) -> str:
    """Add a new commit and tag it; return the new commit SHA."""
    (repo_path / "VERSION").write_text(f"{tag}\n")
    _git("add", "VERSION", cwd=repo_path)
    _git("commit", "-m", f"release {tag}", cwd=repo_path)
    _git("tag", tag, cwd=repo_path)
    return _sha_for_ref(repo_path, f"refs/tags/{tag}")


def _source_block(name: str, url: str, revision: str) -> str:
    """Render the three KANON_SOURCE_<name>_* lines for a single source."""
    if url.startswith("/"):
        url = f"file://{url}"
    return (
        f"KANON_SOURCE_{name}_URL={url}\n"
        f"KANON_SOURCE_{name}_REF={revision}\n"
        f"KANON_SOURCE_{name}_PATH=manifest.xml\n"
        f"KANON_SOURCE_{name}_NAME={name}\n"
        f"KANON_SOURCE_{name}_GITBASE=https://example.com\n"
    )


def _write_kanon(project_dir: pathlib.Path, *source_blocks: str) -> pathlib.Path:
    """Write a ``.kanon`` file with the given pre-rendered source blocks."""
    kanon_path = project_dir / ".kanon"
    header = (
        "GITBASE=https://unused.example.com\nCLAUDE_MARKETPLACES_DIR=/tmp/mktplc\nKANON_MARKETPLACE_INSTALL=false\n"
    )
    kanon_path.write_text(header + "".join(source_blocks))
    kanon_path.chmod(0o600)
    return kanon_path


_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
_FAKE_CATALOG_SHA = "c" * 40


def _run_install_mocked(
    kanon_path: pathlib.Path,
    catalog_source: str = _CATALOG_SOURCE,
    *,
    strict_lock: bool = False,
) -> None:
    """Call ``install()`` with repo tool calls mocked out.

    ``_resolve_ref_to_sha`` is patched only for the catalog URL; calls for real
    local source repos pass through so the recorded SHAs are genuine.  Raises
    whatever ``install()`` raises (callers use ``pytest.raises`` as needed).
    """
    import kanon_cli.core.install as _install_mod

    original_resolve_ref = _install_mod._resolve_ref_to_sha
    catalog_url = catalog_source.rsplit("@", 1)[0] if "@" in catalog_source else catalog_source

    def _resolve_ref_patched(url: str, ref: str) -> _RefResolution:
        if url == catalog_url:
            return _RefResolution(sha=_FAKE_CATALOG_SHA, resolved_ref=f"refs/heads/{ref}")
        return original_resolve_ref(url, ref)

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_resolve_ref_patched),
    ):
        install(
            kanon_path,
            lock_file_path=kanon_path.parent / ".kanon.lock",
            strict_lock=strict_lock,
        )


def _locked_sha(lock_path: pathlib.Path, name: str) -> str:
    """Return the ``resolved_sha`` for source ``name`` in the lockfile."""
    lf = read_lockfile(lock_path)
    for entry in lf.sources:
        if entry.name == name:
            return entry.resolved_sha
    raise KeyError(f"{name!r} not in lockfile sources: {[e.name for e in lf.sources]!r}")


def _locked_names(lock_path: pathlib.Path) -> list[str]:
    """Return the sorted list of source names recorded in the lockfile."""
    return sorted(e.name for e in read_lockfile(lock_path).sources)


# ===========================================================================
# Default (npm install) reconcile
# ===========================================================================


@pytest.mark.integration
class TestPlainInstallReconcile:
    """Plain ``kanon install`` reconciles ``.kanon`` <-> lock without crashing."""

    def test_remove_a_add_b_reconciles_to_b_only(self, tmp_path: pathlib.Path) -> None:
        """remove A + add B + plain install -> lock ends with B only, succeeds, no BUG.

        This is the exact wedged-workspace scenario from the bug report: the lock
        has A (now an orphan) while .kanon declares only B (a new source). The
        old code wrote a corrupt lock and raised the internal ``BUG:`` assertion.
        Reconcile must prune A, resolve B fresh, and write a valid lock = {B}.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        # First install with A only -> lock = {alpha}.
        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"))
        _run_install_mocked(kanon_path)
        assert _locked_names(lock_path) == ["alpha"]

        # Remove A, add B (now .kanon has only beta; lock still has alpha orphan).
        _write_kanon(project, _source_block("beta", str(repo_b), "==1.0.0"))

        # Plain install must reconcile: prune alpha, resolve beta fresh.
        _run_install_mocked(kanon_path)

        assert _locked_names(lock_path) == ["beta"], (
            "reconcile must drop the orphaned alpha entry and add the new beta entry"
        )
        assert _locked_sha(lock_path, "beta") == sha_b

    def test_second_plain_install_is_idempotent_consistent(self, tmp_path: pathlib.Path) -> None:
        """After a reconcile, a second plain install is CONSISTENT (no re-resolve, lock byte-stable)."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, _sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"))
        _run_install_mocked(kanon_path)

        _write_kanon(project, _source_block("beta", str(repo_b), "==1.0.0"))
        _run_install_mocked(kanon_path)  # reconcile
        lock_after_reconcile = lock_path.read_bytes()

        # Second plain install: CONSISTENT replay, no re-resolve, no lock mutation.
        resolve_calls: list[str] = []
        original_resolve = __import__("kanon_cli.version", fromlist=["resolve_version"]).resolve_version

        def _capturing_resolve(url: str, rev_spec: str) -> str:
            resolve_calls.append(rev_spec)
            return original_resolve(url, rev_spec)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.resolve_version", side_effect=_capturing_resolve),
        ):
            install(kanon_path, lock_file_path=lock_path)

        assert resolve_calls == [], f"second plain install must be CONSISTENT (no re-resolve); got {resolve_calls!r}"
        assert lock_path.read_bytes() == lock_after_reconcile, "CONSISTENT install must not mutate the lockfile"

    def test_add_b_preserves_a_locked_sha(self, tmp_path: pathlib.Path) -> None:
        """add B (lock already has A) + plain install -> lock = A+B; A's locked SHA preserved."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        block_a = _source_block("alpha", str(repo_a), "==1.0.0")
        kanon_path = _write_kanon(project, block_a)
        _run_install_mocked(kanon_path)
        a_sha_before = _locked_sha(lock_path, "alpha")
        assert a_sha_before == sha_a

        # Advance repo-a's tag to prove A is REPLAYED (not re-resolved) after adding B.
        new_a_sha = _add_tag(repo_a, "2.0.0")
        assert new_a_sha != sha_a

        # Add B alongside the unchanged A.
        _write_kanon(project, block_a, _source_block("beta", str(repo_b), "==1.0.0"))
        _run_install_mocked(kanon_path)

        assert _locked_names(lock_path) == ["alpha", "beta"]
        assert _locked_sha(lock_path, "alpha") == a_sha_before, (
            "A's locked SHA must be preserved (replayed), not re-resolved, when only B is added"
        )
        assert _locked_sha(lock_path, "beta") == sha_b

    def test_changed_spec_for_a_reresolves_a_preserves_others(self, tmp_path: pathlib.Path) -> None:
        """changed spec for A + plain install -> A re-resolved to new spec; B preserved."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, sha_a_v1 = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        sha_a_v2 = _add_tag(repo_a, "2.0.0")
        repo_b, sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        block_b = _source_block("beta", str(repo_b), "==1.0.0")
        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"), block_b)
        _run_install_mocked(kanon_path)
        assert _locked_sha(lock_path, "alpha") == sha_a_v1
        b_sha_before = _locked_sha(lock_path, "beta")
        assert b_sha_before == sha_b

        # Bump A's revision spec; B unchanged.
        _write_kanon(project, _source_block("alpha", str(repo_a), "==2.0.0"), block_b)
        _run_install_mocked(kanon_path)

        assert _locked_sha(lock_path, "alpha") == sha_a_v2, (
            "A's changed revision spec must be re-resolved to the new pin"
        )
        assert _locked_sha(lock_path, "beta") == b_sha_before, (
            "B's locked SHA must be preserved (replayed) when only A changed"
        )

    def test_pure_orphan_removal_prunes_and_replays(self, tmp_path: pathlib.Path) -> None:
        """pure orphan removal + plain install -> orphan pruned, remaining sources replayed (regression)."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        block_a = _source_block("alpha", str(repo_a), "==1.0.0")
        kanon_path = _write_kanon(project, block_a, _source_block("beta", str(repo_b), "==1.0.0"))
        _run_install_mocked(kanon_path)
        assert _locked_names(lock_path) == ["alpha", "beta"]
        a_sha_before = _locked_sha(lock_path, "alpha")

        # Advance A's tag to prove A is replayed, not re-resolved, after pruning B.
        assert _add_tag(repo_a, "2.0.0") != sha_a

        # Remove beta only.
        _write_kanon(project, block_a)
        _run_install_mocked(kanon_path)

        assert _locked_names(lock_path) == ["alpha"]
        assert _locked_sha(lock_path, "alpha") == a_sha_before, (
            "remaining source's SHA must be preserved (replayed) after orphan prune"
        )

    def test_unchanged_kanon_plain_install_is_consistent(self, tmp_path: pathlib.Path) -> None:
        """unchanged .kanon + plain install -> CONSISTENT (replay, no re-resolve), lock byte-stable."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"))
        _run_install_mocked(kanon_path)
        lock_before = lock_path.read_bytes()

        resolve_calls: list[str] = []
        original_resolve = __import__("kanon_cli.version", fromlist=["resolve_version"]).resolve_version

        def _capturing_resolve(url: str, rev_spec: str) -> str:
            resolve_calls.append(rev_spec)
            return original_resolve(url, rev_spec)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.resolve_version", side_effect=_capturing_resolve),
        ):
            install(kanon_path, lock_file_path=lock_path)

        assert resolve_calls == [], f"unchanged .kanon must replay (no re-resolve); got {resolve_calls!r}"
        assert lock_path.read_bytes() == lock_before, "CONSISTENT install must not mutate the lockfile"


# ===========================================================================
# --strict-lock (npm ci): clean error, lock never mutated
# ===========================================================================


@pytest.mark.integration
class TestStrictLockOnDrift:
    """``--strict-lock`` errors cleanly on ANY drift and never mutates the lock."""

    def test_orphan_only_drift_errors_and_lock_unchanged(self, tmp_path: pathlib.Path) -> None:
        """orphan-only drift under --strict-lock -> OrphanedLockEntryError; lock byte-for-byte unchanged."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, _sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        block_a = _source_block("alpha", str(repo_a), "==1.0.0")
        kanon_path = _write_kanon(project, block_a, _source_block("beta", str(repo_b), "==1.0.0"))
        _run_install_mocked(kanon_path)
        lock_before = lock_path.read_bytes()

        # Remove beta -> orphan-only drift.
        _write_kanon(project, block_a)

        with pytest.raises(OrphanedLockEntryError) as exc_info:
            _run_install_mocked(kanon_path, strict_lock=True)
        assert "beta" in str(exc_info.value)
        assert lock_path.read_bytes() == lock_before, "--strict-lock must not mutate the lockfile on drift"

    def test_orphan_plus_addition_drift_errors_and_lock_unchanged(self, tmp_path: pathlib.Path) -> None:
        """orphan+addition drift under --strict-lock -> clean error (no BUG); lock unchanged."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        repo_b, _sha_b = _build_repo_with_tag(fixtures, "repo-b", "1.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"))
        _run_install_mocked(kanon_path)
        lock_before = lock_path.read_bytes()

        # Remove A, add B -> orphan (alpha) + addition (beta).
        _write_kanon(project, _source_block("beta", str(repo_b), "==1.0.0"))

        # Strict-lock must raise an InstallError subclass cleanly (never the BUG assertion).
        with pytest.raises((OrphanedLockEntryError, KanonHashMismatchError)):
            _run_install_mocked(kanon_path, strict_lock=True)
        assert lock_path.read_bytes() == lock_before, "--strict-lock must not mutate the lockfile on drift"

    def test_changed_spec_drift_errors_and_lock_unchanged(self, tmp_path: pathlib.Path) -> None:
        """changed-spec drift (no orphan) under --strict-lock -> KanonHashMismatchError; lock unchanged."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        repo_a, _sha_a = _build_repo_with_tag(fixtures, "repo-a", "1.0.0")
        _add_tag(repo_a, "2.0.0")

        project = tmp_path / "project"
        project.mkdir()
        lock_path = project / ".kanon.lock"

        kanon_path = _write_kanon(project, _source_block("alpha", str(repo_a), "==1.0.0"))
        _run_install_mocked(kanon_path)
        lock_before = lock_path.read_bytes()

        # Bump A's spec -> hash mismatch with no orphan.
        _write_kanon(project, _source_block("alpha", str(repo_a), "==2.0.0"))

        with pytest.raises(KanonHashMismatchError) as exc_info:
            _run_install_mocked(kanon_path, strict_lock=True)
        assert "--refresh-lock" in str(exc_info.value)
        assert lock_path.read_bytes() == lock_before, "--strict-lock must not mutate the lockfile on drift"
