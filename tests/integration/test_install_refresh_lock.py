"""Integration test: --refresh-lock against a real fixture git repo.

AC-TEST-002: builds a fixture git repo with one tag, installs to produce a
baseline lockfile, hand-edits the lockfile to record a wrong SHA, runs
install(refresh_lock=True), asserts the rebuilt lockfile contains the correct
SHA from the fixture.

End-to-end cycle under the npm-like reconcile contract:
  - Fixture repo has tags 1.0.0 and 1.1.0.
  - First install at ==1.0.0 writes lockfile recording the 1.0.0 SHA.
  - Modify .kanon REVISION to ==1.1.0 (kanon_hash changes).
  - Plain kanon install RECONCILES: re-resolves alpha to the 1.1.0 SHA (no error).
  - kanon install --strict-lock errors cleanly (KanonHashMismatchError) and
    leaves the lockfile byte-for-byte unchanged.
  - kanon install --refresh-lock rebuilds the lockfile with the 1.1.0 SHA.
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
# Override autouse conftest fixtures: this module uses real local git repos
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
    """Run a git command and return stdout. Raises RuntimeError on non-zero exit."""
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
        (repo_path, sha_v1_0_0) -- path to the repo and the 1.0.0 commit SHA.
    """
    repo = base_dir / "fixture-repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("checkout", "-b", "main", cwd=repo)
    (repo / "README.md").write_text("fixture repo v1.0.0\n")
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
    """Write a minimal .kanon file pointing at source_url with the given revision.

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


# Catalog source used across all tests -- a synthetic url@ref value.
_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
# Fake catalog SHA returned when the catalog URL is not a real git repo.
_FAKE_CATALOG_SHA = "c" * 40


def _run_install_mocked(
    kanon_path: pathlib.Path,
    catalog_source: str = _CATALOG_SOURCE,
    refresh_lock: bool = False,
    *,
    strict_lock: bool = False,
) -> None:
    """Call install() with repo tool calls mocked out.

    _resolve_ref_to_sha is patched only for the catalog URL; calls for real
    local source repos pass through so SHA values from the fixture git repo
    are recorded in the lockfile.  ``strict_lock`` is forwarded to ``install()``.
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
            refresh_lock=refresh_lock,
            strict_lock=strict_lock,
        )


# ===========================================================================
# AC-TEST-002: refresh_lock rewrites lockfile with stale SHA
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockRebuildsLockfile:
    """AC-TEST-002: --refresh-lock against fixture repo with a stale lockfile."""

    def test_refresh_lock_rewrites_stale_lockfile(self, tmp_path: pathlib.Path) -> None:
        """install(refresh_lock=True) with a hand-edited stale lockfile rewrites
        the lockfile and records the current resolved SHA from the fixture repo."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        # First install -- writes the lockfile with the correct 1.0.0 SHA.
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()
        lf_before = read_lockfile(lock_path)
        assert lf_before.sources[0].resolved_sha == sha_v1

        # Hand-edit the lockfile to record a wrong (stale) SHA.
        stale_sha = "d" * 40
        original_text = lock_path.read_text()
        corrupted = original_text.replace(sha_v1, stale_sha)
        lock_path.write_text(corrupted)

        lf_stale = read_lockfile(lock_path)
        assert lf_stale.sources[0].resolved_sha == stale_sha

        # Run install with refresh_lock=True -- must ignore the stale lockfile
        # and re-resolve the SHA from the fixture repo.
        _run_install_mocked(kanon_path, refresh_lock=True)

        lf_after = read_lockfile(lock_path)
        assert lf_after.sources[0].resolved_sha == sha_v1, (
            f"Expected SHA {sha_v1!r} after --refresh-lock; got {lf_after.sources[0].resolved_sha!r}"
        )

    def test_refresh_lock_info_line_emitted(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """install(refresh_lock=True) emits the 'lockfile rebuilt from .kanon' info-line."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, _sha = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))

        # Write baseline lockfile first.
        _run_install_mocked(kanon_path)
        # Clear captured output from first install.
        capsys.readouterr()

        # Now run with --refresh-lock and check the info-line.
        _run_install_mocked(kanon_path, refresh_lock=True)

        captured = capsys.readouterr()
        assert "lockfile rebuilt from .kanon" in captured.out

    def test_refresh_lock_does_not_modify_kanon_file(self, tmp_path: pathlib.Path) -> None:
        """install(refresh_lock=True) must not modify the .kanon file (AC-FUNC-002)."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, _sha = _build_fixture_repo(fixture_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_kanon(project_dir, str(repo_path))
        original_kanon = kanon_path.read_text()

        _run_install_mocked(kanon_path, refresh_lock=True)

        assert kanon_path.read_text() == original_kanon, "--refresh-lock must not modify the .kanon file"


# ===========================================================================
# AC-CYCLE-001: Full cycle: 1.0.0 -> hash mismatch -> refresh-lock -> 1.1.0
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockCycle:
    """End-to-end hash-mismatch cycle under the npm-like reconcile contract.

    Plain `kanon install` reconciles a changed revision spec (no error);
    `--strict-lock` errors cleanly; `--refresh-lock` is the explicit full
    rebuild. All three paths land on the new 1.1.0 pin (reconcile/refresh) or
    leave the lock untouched (strict-lock).
    """

    def test_hash_mismatch_then_plain_install_reconciles(self, tmp_path: pathlib.Path) -> None:
        """Plain install reconciles a changed spec to the new pin (no error).

        1. Fixture repo has tags 1.0.0 and 1.1.0.
        2. First install at ==1.0.0 writes lockfile with 1.0.0 SHA.
        3. Modify .kanon REVISION to ==1.1.0 -> kanon_hash changes.
        4. Plain kanon install reconciles: re-resolves alpha to the 1.1.0 SHA.
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)
        sha_v2 = _add_tag(repo_path, "1.1.0")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Step 2: install at ==1.0.0 to write lockfile.
        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()
        lf_v1 = read_lockfile(lock_path)
        assert lf_v1.sources[0].resolved_sha == sha_v1

        # Step 3: modify .kanon to bump revision to ==1.1.0.
        _write_kanon(project_dir, str(repo_path), revision="==1.1.0")

        # Step 4: plain kanon install reconciles to the new pin.
        _run_install_mocked(kanon_path)

        lf_v2 = read_lockfile(lock_path)
        assert lf_v2.sources[0].resolved_sha == sha_v2, (
            f"Expected reconcile to record 1.1.0 SHA {sha_v2!r}; got {lf_v2.sources[0].resolved_sha!r}"
        )
        assert lf_v2.sources[0].resolved_sha != sha_v1

    def test_hash_mismatch_strict_lock_errors_then_refresh_lock_succeeds(self, tmp_path: pathlib.Path) -> None:
        """--strict-lock errors cleanly on the changed spec; --refresh-lock then rebuilds.

        1. Fixture repo has tags 1.0.0 and 1.1.0.
        2. First install at ==1.0.0 writes lockfile with 1.0.0 SHA.
        3. Modify .kanon REVISION to ==1.1.0 -> kanon_hash changes.
        4. kanon install --strict-lock fails with KanonHashMismatchError; lock unchanged.
        5. kanon install --refresh-lock succeeds, lockfile records 1.1.0 SHA.
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        repo_path, sha_v1 = _build_fixture_repo(fixture_dir)
        sha_v2 = _add_tag(repo_path, "1.1.0")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        kanon_path = _write_kanon(project_dir, str(repo_path), revision="==1.0.0")
        _run_install_mocked(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()
        assert read_lockfile(lock_path).sources[0].resolved_sha == sha_v1
        lock_before = lock_path.read_bytes()

        # Step 3: bump revision -> hash mismatch (no orphan).
        _write_kanon(project_dir, str(repo_path), revision="==1.1.0")

        # Step 4: --strict-lock must fail and leave the lock byte-for-byte unchanged.
        with pytest.raises(KanonHashMismatchError) as exc_info:
            _run_install_mocked(kanon_path, strict_lock=True)
        assert "--refresh-lock" in str(exc_info.value)
        assert lock_path.read_bytes() == lock_before, "--strict-lock must not mutate the lockfile"

        # Step 5: --refresh-lock must succeed and update the lockfile.
        _run_install_mocked(kanon_path, refresh_lock=True)

        lf_v2 = read_lockfile(lock_path)
        assert lf_v2.sources[0].resolved_sha == sha_v2, (
            f"Expected lockfile to record 1.1.0 SHA {sha_v2!r}; got {lf_v2.sources[0].resolved_sha!r}"
        )
        assert lf_v2.sources[0].resolved_sha != sha_v1
