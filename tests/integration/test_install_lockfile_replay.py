"""Integration test: lockfile replay isolates install from newer remote tags.

AC-TEST-002: builds a real fixture git repo with a tagged release, runs
kanon install() end-to-end (with repo_init/sync/envsubst mocked so no real
repo tool is needed), writes a baseline lockfile, modifies the remote (adds a
newer tag), runs kanon install() again, asserts the second run uses the
ORIGINAL SHA from the lockfile (lockfile replay ignores the newer tag) and
the lockfile is unchanged on disk.

AC-CYCLE-001: end-to-end hash-mismatch cycle using a fixture git repo.

The tests in this module use a real fixture git repo (no remote network) to
exercise the state-machine branches end-to-end through install().  The fixture
is a real git repo on the local filesystem so git ls-remote works without
network access.  The repo tool calls (repo_init, repo_envsubst, repo_sync) are
mocked because the embedded repo tool requires a proper XML manifest file.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    KanonHashMismatchError,
    _RefResolution,
    install,
)
from kanon_cli.core.lockfile import read_lockfile


# ---------------------------------------------------------------------------
# Override autouse conftest fixtures
# ---------------------------------------------------------------------------
# This module uses real local git repos and custom _resolve_ref_to_sha
# patching (catalog URL only). The autouse fixtures in
# tests/integration/conftest.py would intercept the real function calls
# that these tests depend on. Override them to be no-ops.


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: let the test's own patch handle _resolve_ref_to_sha."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: let the test's own subprocess.run patches handle reachability."""
    yield


# ---------------------------------------------------------------------------
# Fixture: minimal git repo with tagged releases
# ---------------------------------------------------------------------------


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
    """Write a minimal .kanon file pointing at source_url."""
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"GITBASE=https://unused.example.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mktplc\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={source_url}\n"
        f"KANON_SOURCE_alpha_REVISION={revision}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


# Catalog source used across all tests -- a synthetic value in url@ref form.
_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
# Fake catalog SHA returned when the catalog URL is not a real git repo.
_FAKE_CATALOG_SHA = "c" * 40


def _run_install_mocked(
    kanon_path: pathlib.Path,
    catalog_source: str = _CATALOG_SOURCE,
) -> None:
    """Call install() with repo tool calls mocked out.

    repo_init, repo_envsubst, and repo_sync are mocked because the embedded
    repo tool requires a fully configured XML manifest repo; the state-machine
    logic under test does not depend on their side-effects.

    _resolve_ref_to_sha is patched only for the catalog URL (which is a fake
    HTTPS URL). Calls for real local source repos pass through to the real
    implementation so that lockfile replay tests can verify pinned SHAs.
    """
    import kanon_cli.core.install as _install_mod

    original_resolve_ref = _install_mod._resolve_ref_to_sha

    catalog_url = catalog_source.rsplit("@", 1)[0] if "@" in catalog_source else catalog_source

    def _resolve_ref_to_sha_patched(url: str, ref: str) -> _RefResolution:
        if url == catalog_url:
            return _RefResolution(sha=_FAKE_CATALOG_SHA, resolved_ref=f"refs/heads/{ref}")
        return original_resolve_ref(url, ref)

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_resolve_ref_to_sha_patched),
    ):
        install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock", catalog_source=catalog_source)


# ===========================================================================
# AC-TEST-002: lockfile-consistent replay ignores newer remote tag
# ===========================================================================


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

        # First install -- writes the lockfile.
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lockfile_after_first = lock_path.read_text()

        # Add a newer tag on remote to prove replay ignores it.
        _add_tag(repo_path, "2.0.0")

        # Second install -- must use the lockfile, NOT re-resolve.
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

        # First install writes lockfile with sha_v1 for tag 1.0.0.
        _run_install_mocked(kanon_path)

        # Add newer tag 2.0.0 on remote.
        sha_v2 = _add_tag(repo_path, "2.0.0")
        assert sha_v1 != sha_v2

        lock_path = project_dir / ".kanon.lock"
        lf = read_lockfile(lock_path)
        pinned_sha = lf.sources[0].resolved_sha

        # The pinned SHA must be the 1.0.0 SHA, not 2.0.0.
        assert pinned_sha == sha_v1
        assert pinned_sha != sha_v2

        # Capture the resolve_version calls during second install.
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
            install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock", catalog_source=_CATALOG_SOURCE)

        # In the LOCKFILE_CONSISTENT state, resolve_version must NOT be called.
        assert resolve_calls == [], (
            f"install() must not call resolve_version() in LOCKFILE_CONSISTENT state; got calls for: {resolve_calls!r}"
        )

    def test_lockfile_contains_catalog_source(self, tmp_path: pathlib.Path) -> None:
        """Lockfile written by install() records the catalog source in [catalog].source."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, _sha = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        _run_install_mocked(kanon_path, catalog_source=_CATALOG_SOURCE)

        lock_path = project_dir / ".kanon.lock"
        lf = read_lockfile(lock_path)
        assert lf.catalog.source == _CATALOG_SOURCE


# ===========================================================================
# AC-CYCLE-001: Hash-mismatch end-to-end cycle through install()
# ===========================================================================


@pytest.mark.integration
class TestHashMismatchCycle:
    """AC-CYCLE-001: end-to-end hash-mismatch through install().

    Fixture repo at tag 1.0.0; first install writes lockfile; modify .kanon
    REVISION to 2.0.0; second install() hard-errors with KanonHashMismatchError
    naming both kanon_hash values.
    """

    def test_second_install_raises_on_hash_mismatch(self, tmp_path: pathlib.Path) -> None:
        """After modifying .kanon, install() raises KanonHashMismatchError."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Write .kanon at revision ==1.0.0 and run first install.
        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()

        # Modify .kanon to bump revision to ==2.0.0 -- changes kanon_hash.
        _write_kanon(project_dir, str(repo_path), revision="==2.0.0")

        # Second install must raise KanonHashMismatchError without touching remote.
        with pytest.raises(KanonHashMismatchError) as exc_info:
            _run_install_mocked(kanon_path)

        err = exc_info.value
        msg = str(err)
        assert "--refresh-lock" in msg

    def test_hash_mismatch_error_names_both_hashes(self, tmp_path: pathlib.Path) -> None:
        """KanonHashMismatchError raised by install() names both hash values."""
        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # First install at ==1.0.0.
        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lf = read_lockfile(lock_path)
        lockfile_hash = lf.kanon_hash

        # Modify .kanon to bump revision -- changes kanon_hash.
        _write_kanon(project_dir, str(repo_path), revision="==2.0.0")
        fresh_hash = compute_hash(kanon_path)

        # The two hashes must differ.
        assert fresh_hash != lockfile_hash

        # install() must raise with both hashes in the message.
        with pytest.raises(KanonHashMismatchError) as exc_info:
            _run_install_mocked(kanon_path)

        msg = str(exc_info.value)
        assert lockfile_hash in msg, f"Expected lockfile_hash {lockfile_hash!r} in error message"
        assert fresh_hash in msg, f"Expected fresh_hash {fresh_hash!r} in error message"
