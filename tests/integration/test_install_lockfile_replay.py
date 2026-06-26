"""Integration test: lockfile replay isolates install from newer remote tags.

AC-TEST-002: builds a real fixture git repo with a tagged release, runs
kanon install() end-to-end (with repo_init/sync/envsubst mocked so no real
repo tool is needed), writes a baseline lockfile, modifies the remote (adds a
newer tag), runs kanon install() again, asserts the second run uses the
ORIGINAL SHA from the lockfile (lockfile replay ignores the newer tag) and
the lockfile is unchanged on disk.

Hash-mismatch cycle (opt-in reconcile contract): ``kanon install --reconcile``
reconciles a changed revision spec to the new pin; the default and
``--strict-lock`` paths error cleanly (LockfileConsistencyError) and never
mutate the lockfile.

The tests in this module use a real fixture git repo (no remote network) to
exercise the state-machine branches end-to-end through install().  The fixture
is a real git repo on the local filesystem so git ls-remote works without
network access.  The repo tool calls (repo_init, repo_envsubst, repo_sync) are
mocked because the embedded repo tool requires a proper XML manifest file.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    install,
)
from kanon_cli.core.lockfile import LockfileConsistencyError, read_lockfile


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: let the test's own patch handle _resolve_ref_to_sha."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: let the test's own subprocess.run patches handle reachability."""
    yield


def _git(*args: str, cwd: pathlib.Path) -> str:
    """Run a git command and return stdout. Raises on non-zero exit."""
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
    """Return the SHA that ref resolves to in the given repo."""
    return _git("rev-parse", ref, cwd=repo_path)


def _build_fixture_repo(base_dir: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Create a fixture git repo with one commit tagged 1.0.0.

    Returns:
        (repo_path, sha_v1_0_0) -- the path to the repo and the commit SHA
        that was tagged 1.0.0.
    """
    repo = base_dir / "fixture-repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("checkout", "-b", "main", cwd=repo)
    readme = repo / "README.md"
    readme.write_text("fixture repo v1.0.0\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)
    _git("tag", "1.0.0", cwd=repo)
    sha = _sha_for_ref(repo, "refs/tags/1.0.0")
    return repo, sha


def _add_tag(repo_path: pathlib.Path, tag: str) -> str:
    """Add a new commit and tag it. Returns the new commit SHA."""
    (repo_path / "VERSION").write_text(f"{tag}\n")
    _git("add", "VERSION", cwd=repo_path)
    _git("commit", "-m", f"release {tag}", cwd=repo_path)
    _git("tag", tag, cwd=repo_path)
    return _sha_for_ref(repo_path, f"refs/tags/{tag}")


def _write_kanon(
    project_dir: pathlib.Path,
    source_url: str,
    revision: str = "==1.0.0",
) -> pathlib.Path:
    """Write a minimal .kanon file pointing at source_url.

    Bare filesystem paths are coerced to ``file://`` URLs so the URL parser
    introduced by E1-F2-S1-T1 accepts them; the autouse
    ``_default_allow_insecure_remotes`` fixture in conftest then permits the
    non-HTTPS/SSH scheme through ``_enforce_remote_url_policy``.
    """
    if source_url.startswith("/"):
        source_url = f"file://{source_url}"
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"GITBASE=https://unused.example.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mktplc\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={source_url}\n"
        f"KANON_SOURCE_alpha_REF={revision}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        f"KANON_SOURCE_alpha_NAME=alpha\n"
        f"KANON_SOURCE_alpha_GITBASE=https://example.com\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _run_install_mocked(
    kanon_path: pathlib.Path,
    *,
    strict_lock: bool = False,
    reconcile: bool = False,
) -> None:
    """Call install() with repo tool calls mocked out.

    repo_init, repo_envsubst, and repo_sync are mocked because the embedded
    repo tool requires a fully configured XML manifest repo; the state-machine
    logic under test does not depend on their side-effects.

    ``kanon install`` is hermetic (spec Section 5.2 / FR-7): it resolves no
    catalog source, so ``_resolve_ref_to_sha`` runs against the real local
    source repos so that lockfile replay tests can verify pinned SHAs.

    ``strict_lock`` and ``reconcile`` are forwarded to ``install()``: the
    default and ``--strict-lock`` paths error cleanly on drift without mutating
    the lock, while ``reconcile`` opts in to the lenient npm-install reconcile.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
    ):
        install(
            kanon_path,
            lock_file_path=kanon_path.parent / ".kanon.lock",
            strict_lock=strict_lock,
            reconcile=reconcile,
        )


@pytest.mark.integration
class TestLockfileReplay:
    """AC-TEST-002: end-to-end lockfile replay through install()."""

    def test_first_install_writes_lockfile(self, tmp_path: pathlib.Path) -> None:
        """First install() with no lockfile writes .kanon.lock (LOCKFILE_ABSENT)."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        lock_path = project_dir / ".kanon.lock"
        assert not lock_path.exists()

        _run_install_mocked(kanon_path)

        assert lock_path.exists(), "install() must write .kanon.lock in LOCKFILE_ABSENT state"

    def test_second_install_lockfile_unchanged(self, tmp_path: pathlib.Path) -> None:
        """Second install() with a consistent lockfile leaves the lockfile on disk unchanged."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lockfile_after_first = lock_path.read_text()

        _add_tag(repo_path, "2.0.0")

        _run_install_mocked(kanon_path)

        lockfile_after_second = lock_path.read_text()
        assert lockfile_after_second == lockfile_after_first, (
            "Second install() must not modify .kanon.lock when state is LOCKFILE_CONSISTENT"
        )

    def test_second_install_uses_pinned_sha_not_newer_tag(self, tmp_path: pathlib.Path) -> None:
        """Second install() uses the SHA pinned in the lockfile, not the newer remote tag."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        _run_install_mocked(kanon_path)

        sha_v2 = _add_tag(repo_path, "2.0.0")
        assert sha_v1 != sha_v2

        lock_path = project_dir / ".kanon.lock"
        lf = read_lockfile(lock_path)
        pinned_sha = lf.sources[0].resolved_sha

        assert pinned_sha == sha_v1
        assert pinned_sha != sha_v2

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
            install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock")

        assert resolve_calls == [], (
            f"install() must not call resolve_version() in LOCKFILE_CONSISTENT state; got calls for: {resolve_calls!r}"
        )

    def test_install_parser_rejects_catalog_source_flag(self) -> None:
        """The install subparser does not register --catalog-source.

        Schema v4 (spec Section 5.2 / FR-7) removed the lockfile [catalog] block, so
        ``kanon install`` is hermetic and never resolves or records a catalog source.
        Passing ``--catalog-source`` to ``kanon install`` is therefore an unrecognized
        argument: argparse exits non-zero (SystemExit) rather than silently accepting it.
        """
        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["install", "--catalog-source", "https://catalog.example.com/repo.git@main"])

        assert exc_info.value.code != 0

    def test_install_ignores_catalog_sources_env_var(self, tmp_path: pathlib.Path) -> None:
        """A populated KANON_CATALOG_SOURCES env var has no effect on install.

        Schema v4 (spec Section 5.2 / FR-7) makes ``kanon install`` hermetic: it is
        driven solely by the committed ``.kanon`` (+ ``.kanon.lock``).  A populated
        ``KANON_CATALOG_SOURCES`` environment variable is ignored (not read, not an
        error): install succeeds, writes the lockfile from ``.kanon``, and the bogus
        env URL never appears in the resulting lock.
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        bogus_env_url = "https://catalog.example.com/repo.git@main"
        lock_path = project_dir / ".kanon.lock"

        with patch.dict(os.environ, {"KANON_CATALOG_SOURCES": bogus_env_url}):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanon_path, lock_file_path=lock_path)

        assert lock_path.exists(), "install() must write .kanon.lock despite KANON_CATALOG_SOURCES being set"

        lf = read_lockfile(lock_path)

        assert [e.name for e in lf.sources] == ["alpha"]
        assert lf.sources[0].resolved_sha == sha_v1

        lock_text = lock_path.read_text()
        assert "catalog.example.com" not in lock_text


@pytest.mark.integration
class TestHashMismatchCycle:
    """End-to-end hash-mismatch through install() under the opt-in reconcile contract.

    Fixture repo with tags 1.0.0 and 2.0.0; first install writes the lockfile at
    1.0.0; modify .kanon REVISION to ==2.0.0 (changes kanon_hash).  ``--reconcile``
    re-resolves alpha to 2.0.0; the default and ``--strict-lock`` paths raise
    LockfileConsistencyError (the ref-specs differ check fires before resolving)
    and leave the lock byte-for-byte unchanged.
    """

    def test_second_install_reconciles_on_hash_mismatch(self, tmp_path: pathlib.Path) -> None:
        """After modifying .kanon, install --reconcile reconciles (re-resolves), no error."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)
        sha_v2 = _add_tag(repo_path, "2.0.0")
        assert sha_v1 != sha_v2

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()
        assert read_lockfile(lock_path).sources[0].resolved_sha == sha_v1

        _write_kanon(project_dir, str(repo_path), revision="==2.0.0")

        _run_install_mocked(kanon_path, reconcile=True)

        lf_after = read_lockfile(lock_path)
        assert lf_after.sources[0].resolved_sha == sha_v2, (
            "install --reconcile must reconcile a changed revision spec to the new pin"
        )

    def test_strict_lock_raises_consistency_error_on_changed_spec(self, tmp_path: pathlib.Path) -> None:
        """`--strict-lock` raises LockfileConsistencyError naming the drifted ref-specs; lock unchanged.

        The default install runs the ``.kanon`` <-> ``.kanon.lock`` ref-spec parity
        check before resolving, so a changed revision spec fails fast (exit 1) with a
        LockfileConsistencyError that names both the ``.kanon`` revision and the
        locked ``ref_spec`` and points at ``--reconcile`` / ``--refresh-lock``.  No
        ``BUG:`` string is emitted and the lockfile is left byte-for-byte unchanged.
        """
        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)
        _add_tag(repo_path, "2.0.0")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lf = read_lockfile(lock_path)
        lockfile_hash = lf.kanon_hash
        lock_before = lock_path.read_bytes()

        _write_kanon(project_dir, str(repo_path), revision="==2.0.0")
        fresh_hash = compute_hash(kanon_path)
        assert fresh_hash != lockfile_hash

        with pytest.raises(LockfileConsistencyError) as exc_info:
            _run_install_mocked(kanon_path, strict_lock=True)

        msg = str(exc_info.value)
        assert "ref-specs differ" in msg
        assert "==2.0.0" in msg, "Expected the .kanon revision in the error message"
        assert "==1.0.0" in msg, "Expected the locked ref_spec in the error message"
        assert "--refresh-lock" in msg
        assert "BUG:" not in msg
        assert lock_path.read_bytes() == lock_before, "--strict-lock must not mutate the lockfile"
