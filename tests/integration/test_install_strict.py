"""Integration tests for --strict-lock and --strict-drift flags.

AC-TEST-002: Builds a fixture git repo with a branch-shaped source, runs
a baseline install, advances the branch tip on the fixture remote, then
exercises strict-drift mode against the updated remote.

AC-CYCLE-001: End-to-end cycle documented in TDD Cycle Log:
  - Fixture git repo with branch `main` at SHA `aaaa` (real SHA).
  - Baseline install records lockfile with the baseline SHA.
  - Advance fixture's `main` to a new commit (SHA changes).
  - `kanon install` (no flag) exits 0 with the drift info-line in stdout.
  - `kanon install --strict-drift` exits non-zero with BranchDriftError.
  - `kanon install --refresh-lock-source <source>` rewrites lockfile with
    the new SHA.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

from kanon_cli.core.install import (
    BranchDriftError,
    OrphanedLockEntryError,
    _RefResolution,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as _compute_kanon_hash
from kanon_cli.core.lockfile import read_lockfile
from kanon_cli.core.metadata import derive_source_name
from tests.integration.test_add_core import _create_manifest_repo_with_tags


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


def _build_branch_fixture_repo(base_dir: pathlib.Path, name: str) -> tuple[pathlib.Path, str]:
    """Create a fixture git repo with one commit on branch `main`.

    Returns:
        (repo_path, baseline_sha) -- path to the repo and the initial commit SHA.
    """
    repo = base_dir / name
    repo.mkdir()
    _git("init", cwd=repo)
    _git("checkout", "-b", "main", cwd=repo)
    (repo / "README.md").write_text(f"{name} initial\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)
    sha = _sha_for_ref(repo, "refs/heads/main")
    return repo, sha


def _advance_branch(repo: pathlib.Path) -> str:
    """Add a new commit to advance the branch tip. Returns the new SHA."""
    readme = repo / "README.md"
    readme.write_text(readme.read_text() + "updated\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "advance branch", cwd=repo)
    return _sha_for_ref(repo, "refs/heads/main")


def _write_kanon(directory: pathlib.Path, source_name: str, remote_url: str) -> pathlib.Path:
    """Write a minimal .kanon pointing at a branch-shaped source.

    Bare filesystem paths are coerced to ``file://`` URLs so the URL parser
    introduced by E1-F2-S1-T1 accepts them; the autouse
    ``_default_allow_insecure_remotes`` fixture in conftest then permits the
    non-HTTPS/SSH scheme through ``_enforce_remote_url_policy``.
    """
    if remote_url.startswith("/"):
        remote_url = f"file://{remote_url}"
    kanon_path = directory / ".kanon"
    kanon_path.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL={remote_url}\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=manifest.xml\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _write_kanon_with_orphan(
    directory: pathlib.Path,
    active_source: str,
    active_url: str,
) -> pathlib.Path:
    """Write a .kanon with one active source (for orphan tests)."""
    return _write_kanon(directory, active_source, active_url)


def _run_install_with_fake_catalog(
    kanon_path: pathlib.Path,
    fixture_repo: pathlib.Path,
    baseline_sha: str,
    **kwargs,
) -> None:
    """Run install() with patched catalog resolution and repo operations.

    The catalog resolution is mocked because the test fixture repos are not
    real catalog repos. The _resolve_ref_to_sha for the catalog source is
    intercepted; _resolve_ref_to_sha for SOURCE repos uses the real git binary
    (the fixture repos are local paths on disk).

    The repo init/envsubst/sync operations are patched to no-ops because the
    fixture repos are minimal git repos without real manifest files.

    Args:
        kanon_path: Path to the .kanon file.
        fixture_repo: Path to the fixture source repository.
        baseline_sha: The SHA to use for the catalog mock.
        **kwargs: Additional keyword arguments forwarded to install().
    """
    catalog_source = f"{fixture_repo}@main"
    catalog_fake_ref = _RefResolution(sha=baseline_sha, resolved_ref="refs/heads/main")

    def _resolve_ref_to_sha_side_effect(url: str, ref: str) -> _RefResolution:
        # For source URLs that are local paths, use the real git binary.
        if str(url) in (str(fixture_repo), f"file://{fixture_repo}"):
            result = subprocess.run(
                ["git", "ls-remote", str(fixture_repo), ref],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise ValueError(f"git ls-remote failed: {result.stderr}")
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    matched_sha, matched_ref = parts[0], parts[1]
                    if matched_ref == ref or matched_ref.endswith(f"/{ref}"):
                        return _RefResolution(sha=matched_sha, resolved_ref=matched_ref)
            raise ValueError(f"ref {ref!r} not found in {fixture_repo}")
        # For catalog and other URLs use the fake
        return catalog_fake_ref

    def _check_sha_reachable_side_effect(url: str, sha: str, source_name: str) -> None:
        # Use real git ls-remote for local fixture repos; others are no-ops.
        if str(url) in (str(fixture_repo), f"file://{fixture_repo}"):
            result = subprocess.run(
                ["git", "ls-remote", str(fixture_repo)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                from kanon_cli.core.install import LockfileUnreachableShaError

                raise LockfileUnreachableShaError(source_name=source_name, sha=sha, remote_url=url)
            # Check whether sha appears in any ref's SHA column
            sha_found = any(line.split("\t")[0] == sha for line in result.stdout.strip().splitlines() if "\t" in line)
            if not sha_found:
                from kanon_cli.core.install import LockfileUnreachableShaError

                raise LockfileUnreachableShaError(source_name=source_name, sha=sha, remote_url=url)

    with (
        patch(
            "kanon_cli.core.install._resolve_ref_to_sha",
            side_effect=_resolve_ref_to_sha_side_effect,
        ),
        patch(
            "kanon_cli.core.install._check_sha_reachable",
            side_effect=_check_sha_reachable_side_effect,
        ),
        patch("kanon_cli.core.install.run_repo_init"),
        patch("kanon_cli.core.install.run_repo_envsubst"),
        patch("kanon_cli.core.install.run_repo_sync"),
    ):
        install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock", catalog_source=catalog_source, **kwargs)


# ---------------------------------------------------------------------------
# AC-TEST-002: End-to-end strict-drift against a real fixture repo
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStrictDriftEndToEnd:
    """AC-TEST-002: full strict-drift cycle against a real fixture git repo.

    This test is marked integration because it executes real git commands
    against a local fixture repository created in tmp_path.
    """

    def test_strict_drift_raises_with_correct_shas(self, tmp_path: pathlib.Path) -> None:
        """Baseline install -> advance branch -> strict-drift raises BranchDriftError.

        The error message must contain the EXACT baseline SHA and the new SHA.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fixture_repo, baseline_sha = _build_branch_fixture_repo(repos_dir, "source-alpha")
        kanon_path = _write_kanon(project_dir, "alpha", str(fixture_repo))

        # Step 1: Baseline install -- records lockfile with baseline_sha
        _run_install_with_fake_catalog(
            kanon_path,
            fixture_repo,
            baseline_sha,
            strict_lock=False,
            strict_drift=False,
        )

        lock_path = project_dir / ".kanon.lock"
        baseline_lf = read_lockfile(lock_path)
        locked_sha = baseline_lf.sources[0].resolved_sha
        assert locked_sha == baseline_sha, f"Locked SHA {locked_sha!r} != baseline {baseline_sha!r}"

        # Step 2: Advance the branch tip on the fixture remote
        new_sha = _advance_branch(fixture_repo)
        assert new_sha != locked_sha, "Expected branch to advance to a new SHA"

        # Step 3: kanon install --strict-drift must raise BranchDriftError
        with pytest.raises(BranchDriftError) as exc_info:
            _run_install_with_fake_catalog(
                kanon_path,
                fixture_repo,
                baseline_sha,
                strict_lock=False,
                strict_drift=True,
            )

        error_msg = str(exc_info.value)
        assert locked_sha in error_msg, f"Error message missing locked SHA {locked_sha!r}"
        assert new_sha in error_msg, f"Error message missing new SHA {new_sha!r}"
        assert "alpha" in error_msg

    def test_no_strict_flag_emits_drift_info_line(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Without --strict-drift, branch drift emits info-line and exits 0."""
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fixture_repo, baseline_sha = _build_branch_fixture_repo(repos_dir, "source-beta")
        kanon_path = _write_kanon(project_dir, "beta", str(fixture_repo))

        # Baseline install
        _run_install_with_fake_catalog(
            kanon_path,
            fixture_repo,
            baseline_sha,
            strict_lock=False,
            strict_drift=False,
        )
        # Advance branch
        new_sha = _advance_branch(fixture_repo)
        capsys.readouterr()  # discard baseline output

        # Reinstall without strict flag -- must emit drift info-line, not raise
        _run_install_with_fake_catalog(
            kanon_path,
            fixture_repo,
            baseline_sha,
            strict_lock=False,
            strict_drift=False,
        )

        captured = capsys.readouterr()
        # The drift info-line must appear in stdout
        assert "branch drift: beta:" in captured.out
        assert "reusing locked SHA" in captured.out
        assert new_sha in captured.out or baseline_sha in captured.out

    def test_refresh_lock_source_updates_lockfile_after_drift(self, tmp_path: pathlib.Path) -> None:
        """After drift, --refresh-lock-source rewrites lockfile with the new SHA."""
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fixture_repo, baseline_sha = _build_branch_fixture_repo(repos_dir, "source-gamma")
        kanon_path = _write_kanon(project_dir, "gamma", str(fixture_repo))

        # Baseline install
        _run_install_with_fake_catalog(
            kanon_path,
            fixture_repo,
            baseline_sha,
            strict_lock=False,
            strict_drift=False,
        )

        # Advance branch
        new_sha = _advance_branch(fixture_repo)

        # refresh-lock-source should accept new tip
        _run_install_with_fake_catalog(
            kanon_path,
            fixture_repo,
            baseline_sha,
            refresh_lock_source="gamma",
            strict_lock=False,
            strict_drift=False,
        )

        lock_path = project_dir / ".kanon.lock"
        updated_lf = read_lockfile(lock_path)
        updated_sha = updated_lf.sources[0].resolved_sha
        assert updated_sha == new_sha, f"Expected lockfile to record new SHA {new_sha!r}, got {updated_sha!r}"


# ---------------------------------------------------------------------------
# AC-CYCLE-001: full cycle with strict-lock (orphaned entries)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStrictLockEndToEnd:
    """Strict-lock cycle: orphaned lock entries raise hard errors.

    The orphaned lock entry scenario occurs when the lockfile contains a source
    that is absent from the current .kanon, BUT the kanon_hash still matches.
    In practice this can occur if the lockfile was manually edited to add an
    extra [[sources]] entry without updating the kanon_hash, or when using
    tools that bypass the normal install flow.

    We simulate this by writing a lockfile manually: compute the kanon_hash
    for the current (single-source) .kanon, then write a lockfile that contains
    BOTH the active source AND an orphaned source entry, using the computed
    kanon_hash.  This produces a LOCKFILE_CONSISTENT state with an orphan.
    """

    def _write_lockfile_with_orphan(
        self,
        lock_path: pathlib.Path,
        kanon_hash: str,
        catalog_source: str,
        active_name: str,
        active_url: str,
        active_sha: str,
        orphan_name: str,
        orphan_url: str,
        orphan_sha: str,
    ) -> None:
        """Write a lockfile with one active source and one orphaned source.

        Bare filesystem paths are coerced to ``file://`` URLs so the URL parser
        introduced by E1-F2-S1-T1 accepts the locked URLs when the install
        engine re-validates them.
        """
        if active_url.startswith("/"):
            active_url = f"file://{active_url}"
        if orphan_url.startswith("/"):
            orphan_url = f"file://{orphan_url}"
        lock_path.write_text(
            f"schema_version = 1\n"
            f'generated_at = "2026-01-15T00:00:00Z"\n'
            f'generator = "kanon-cli/test"\n'
            f'kanon_hash = "{kanon_hash}"\n'
            f"\n"
            f"[catalog]\n"
            f'source = "{catalog_source}"\n'
            f'url = "{catalog_source.rsplit("@", 1)[0]}"\n'
            f'revision_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{active_sha}"\n'
            f"\n"
            f"[[sources]]\n"
            f'name = "{active_name}"\n'
            f'url = "{active_url}"\n'
            f'revision_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{active_sha}"\n'
            f'path = "manifest.xml"\n'
            f"\n"
            f"[[sources]]\n"
            f'name = "{orphan_name}"\n'
            f'url = "{orphan_url}"\n'
            f'revision_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{orphan_sha}"\n'
            f'path = "manifest.xml"\n'
        )

    def test_strict_lock_raises_orphaned_error(self, tmp_path: pathlib.Path) -> None:
        """strict-lock raises OrphanedLockEntryError when lockfile has orphaned source.

        This test simulates a LOCKFILE_CONSISTENT state with an orphaned entry by
        manually writing a lockfile that includes an extra source entry not present
        in the current .kanon, but using the correct kanon_hash for the current .kanon.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fixture_alpha, sha_alpha = _build_branch_fixture_repo(repos_dir, "source-alpha2")
        fixture_orphan, sha_orphan = _build_branch_fixture_repo(repos_dir, "source-orphan")

        # Single-source .kanon (only alpha)
        kanon_path = project_dir / ".kanon"
        kanon_path.write_text(
            f"KANON_MARKETPLACE_INSTALL=false\n"
            f"KANON_SOURCE_alpha_URL=file://{fixture_alpha}\n"
            f"KANON_SOURCE_alpha_REVISION=main\n"
            f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        )
        kanon_path.chmod(0o600)

        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        real_hash = compute_hash(kanon_path)
        catalog_source = f"{fixture_alpha}@main"

        # Write a lockfile that is CONSISTENT (correct kanon_hash) but contains
        # an extra orphaned source entry for "ghost"
        lock_path = project_dir / ".kanon.lock"
        self._write_lockfile_with_orphan(
            lock_path,
            kanon_hash=real_hash,
            catalog_source=catalog_source,
            active_name="alpha",
            active_url=str(fixture_alpha),
            active_sha=sha_alpha,
            orphan_name="ghost",
            orphan_url=str(fixture_orphan),
            orphan_sha=sha_orphan,
        )

        fake_ref = _RefResolution(sha=sha_alpha, resolved_ref="refs/heads/main")

        def _check_reachable(url: str, sha: str, source_name: str) -> None:
            # Only alpha is in the .kanon, and its SHA is reachable
            pass  # always pass for this test

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable", side_effect=_check_reachable),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(OrphanedLockEntryError) as exc_info,
        ):
            # No drift: remote tip equals locked SHA
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{sha_alpha}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=catalog_source,
                strict_lock=True,
            )

        error_msg = str(exc_info.value)
        assert "ghost" in error_msg
        # Remediation must mention running without --strict-lock OR restoring triples
        assert "KANON_SOURCE_" in error_msg or "--strict-lock" in error_msg

    def test_strict_lock_default_prunes_orphan(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Without --strict-lock, orphaned entries are pruned with info-line."""
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fixture_alpha, sha_alpha = _build_branch_fixture_repo(repos_dir, "source-alpha3")
        fixture_orphan, sha_orphan = _build_branch_fixture_repo(repos_dir, "source-orphan2")

        kanon_path = project_dir / ".kanon"
        kanon_path.write_text(
            f"KANON_MARKETPLACE_INSTALL=false\n"
            f"KANON_SOURCE_alpha_URL=file://{fixture_alpha}\n"
            f"KANON_SOURCE_alpha_REVISION=main\n"
            f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        )
        kanon_path.chmod(0o600)

        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        real_hash = compute_hash(kanon_path)
        catalog_source = f"{fixture_alpha}@main"

        lock_path = project_dir / ".kanon.lock"
        self._write_lockfile_with_orphan(
            lock_path,
            kanon_hash=real_hash,
            catalog_source=catalog_source,
            active_name="alpha",
            active_url=str(fixture_alpha),
            active_sha=sha_alpha,
            orphan_name="ghost",
            orphan_url=str(fixture_orphan),
            orphan_sha=sha_orphan,
        )

        fake_ref = _RefResolution(sha=sha_alpha, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{sha_alpha}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=catalog_source,
                strict_lock=False,
            )

        captured = capsys.readouterr()
        assert "pruned orphaned lock entry: ghost" in captured.out

        # Verify the lockfile was rewritten without the orphan
        updated_lf = read_lockfile(lock_path)
        source_names = [s.name for s in updated_lf.sources]
        assert "ghost" not in source_names
        assert "alpha" in source_names


# ---------------------------------------------------------------------------
# TestStrictLockOrphanErrorMessage: verify error message content (DEFECT-011)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStrictLockOrphanErrorMessage:
    """Verify that --strict-lock error names each orphan source and includes remediation.

    DEFECT-011: the error message produced by OrphanedLockEntryError must contain
    the normalized orphan source name, the substring '--strict-lock', the substring
    'kanon remove', and a count-prefixed noun phrase that is grammatically correct
    for singular (1 orphaned lockfile entry:) and plural (N orphaned lockfile entries:).

    Each test constructs a LOCKFILE_CONSISTENT state manually: a .kanon with only
    the active source, a lockfile with the correct kanon_hash for that .kanon but
    containing additional orphaned [[sources]] entries. Running
    'kanon install --strict-lock' as a subprocess surfaces the error on stderr.
    """

    def _write_kanon_single_source(
        self,
        directory: pathlib.Path,
        source_name: str,
        source_url: str,
    ) -> pathlib.Path:
        """Write .kanon with a single source triple and return the path.

        Args:
            directory: Directory in which to create the .kanon file.
            source_name: The KANON_SOURCE_<name> key suffix (already normalized).
            source_url: URL for the source; bare paths are coerced to file://.
        """
        if source_url.startswith("/"):
            source_url = f"file://{source_url}"
        kanon_path = directory / ".kanon"
        kanon_path.write_text(
            f"KANON_MARKETPLACE_INSTALL=false\n"
            f"KANON_SOURCE_{source_name}_URL={source_url}\n"
            f"KANON_SOURCE_{source_name}_REVISION=main\n"
            f"KANON_SOURCE_{source_name}_PATH=manifest.xml\n"
        )
        kanon_path.chmod(0o600)
        return kanon_path

    def _write_lockfile_with_orphans(
        self,
        lock_path: pathlib.Path,
        kanon_hash: str,
        catalog_source: str,
        active_name: str,
        active_url: str,
        active_sha: str,
        orphan_entries: list[tuple[str, str, str]],
    ) -> None:
        """Write a lockfile with correct kanon_hash but extra orphaned source entries.

        The lockfile is in the LOCKFILE_CONSISTENT state (hash matches the current
        .kanon) but contains additional [[sources]] entries that are absent from
        the current .kanon, making them orphans detectable by --strict-lock.

        Args:
            lock_path: Path at which to write the lockfile.
            kanon_hash: The kanon_hash that matches the current .kanon content.
            catalog_source: The catalog source URL@ref used in the lockfile header.
            active_name: Source name for the non-orphaned active entry.
            active_url: URL for the active source; bare paths coerced to file://.
            active_sha: Resolved SHA for the active source.
            orphan_entries: List of (name, url, sha) tuples for orphaned entries.
        """
        if active_url.startswith("/"):
            active_url = f"file://{active_url}"

        active_block = (
            f"[[sources]]\n"
            f'name = "{active_name}"\n'
            f'url = "{active_url}"\n'
            f'revision_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{active_sha}"\n'
            f'path = "manifest.xml"\n'
        )

        orphan_blocks = []
        for orphan_name, orphan_url, orphan_sha in orphan_entries:
            if orphan_url.startswith("/"):
                orphan_url = f"file://{orphan_url}"
            orphan_blocks.append(
                f"[[sources]]\n"
                f'name = "{orphan_name}"\n'
                f'url = "{orphan_url}"\n'
                f'revision_spec = "main"\n'
                f'resolved_ref = "refs/heads/main"\n'
                f'resolved_sha = "{orphan_sha}"\n'
                f'path = "manifest.xml"\n'
            )

        catalog_url = catalog_source.rsplit("@", 1)[0]
        body = (
            f"schema_version = 1\n"
            f'generated_at = "2026-01-15T00:00:00Z"\n'
            f'generator = "kanon-cli/test"\n'
            f'kanon_hash = "{kanon_hash}"\n'
            f"\n"
            f"[catalog]\n"
            f'source = "{catalog_source}"\n'
            f'url = "{catalog_url}"\n'
            f'revision_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{active_sha}"\n'
            f"\n"
            + active_block
        )
        for block in orphan_blocks:
            body += "\n" + block

        lock_path.write_text(body)

    def _run_strict_lock_install(
        self,
        project_dir: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        """Run 'kanon install --strict-lock' as a subprocess in project_dir.

        Args:
            project_dir: The working directory containing the .kanon file.

        Returns:
            The completed subprocess result with stdout and stderr captured.
        """
        env = dict(os.environ)
        env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install", "--strict-lock"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(project_dir),
        )

    def test_error_names_each_orphan_source_and_remediation(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """--strict-lock stderr must contain orphan name, '--strict-lock', and 'kanon remove'.

        Spec reference: spec Section 4 E26 Failing test.

        DEFECT-011 root cause: the current OrphanedLockEntryError message does not
        include 'kanon remove' in the remediation hint. The test fails RED because the
        expected substring is absent.

        Setup:
        - Two bare repos: catA (entry 'source-delta') and catB (entry 'source-echo').
        - .kanon with only source-delta active.
        - Lockfile with correct kanon_hash for that .kanon, but also containing
          a source-echo orphaned entry (simulating the state after 'kanon remove'
          was not followed by a lockfile prune).
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Build two bare repos: one for the active source, one for the orphan.
        cat_a_bare = _create_manifest_repo_with_tags(
            repos_dir / "catA",
            entry_names=["source-delta"],
            tags=["1.0.0"],
        )
        cat_b_bare = _create_manifest_repo_with_tags(
            repos_dir / "catB",
            entry_names=["source-echo"],
            tags=["1.0.0"],
        )

        # Derive normalized source names the same way kanon's install engine does.
        active_entry_name = "source-delta"
        orphan_entry_name = "source-echo"
        active_source_key = derive_source_name(active_entry_name)
        expected_orphan_name = derive_source_name(orphan_entry_name)

        # Placeholder SHAs (orphan check runs before SHA resolution).
        placeholder_sha = "a" * 40

        # Write .kanon with only the active source triple.
        kanon_path = self._write_kanon_single_source(
            project_dir,
            source_name=active_source_key,
            source_url=str(cat_a_bare),
        )

        # Compute kanon_hash for the single-source .kanon so the lockfile is CONSISTENT.
        real_hash = _compute_kanon_hash(kanon_path)
        catalog_source = f"file://{cat_a_bare}@main"

        # Write lockfile: consistent hash, active entry, plus orphaned source-echo.
        lock_path = project_dir / ".kanon.lock"
        self._write_lockfile_with_orphans(
            lock_path,
            kanon_hash=real_hash,
            catalog_source=catalog_source,
            active_name=active_source_key,
            active_url=str(cat_a_bare),
            active_sha=placeholder_sha,
            orphan_entries=[(expected_orphan_name, str(cat_b_bare), placeholder_sha)],
        )

        # Run kanon install --strict-lock and capture the result.
        result = self._run_strict_lock_install(project_dir)

        stderr = result.stderr
        assert result.returncode != 0, (
            f"Expected non-zero exit for strict-lock orphan, got 0.\n"
            f"stdout: {result.stdout!r}\nstderr: {stderr!r}"
        )
        assert expected_orphan_name in stderr, (
            f"Expected orphan name {expected_orphan_name!r} in stderr.\n"
            f"stderr: {stderr!r}"
        )
        assert "--strict-lock" in stderr, (
            f"Expected '--strict-lock' in stderr (remediation hint).\n"
            f"stderr: {stderr!r}"
        )
        assert "kanon remove" in stderr, (
            f"Expected 'kanon remove' in stderr (alternative remediation).\n"
            f"stderr: {stderr!r}"
        )

    @pytest.mark.parametrize(
        ("orphan_count", "expected_word"),
        [(1, "entry:"), (2, "entries:")],
    )
    def test_error_grammatically_correct_for_single_vs_multiple_orphans(
        self,
        tmp_path: pathlib.Path,
        orphan_count: int,
        expected_word: str,
    ) -> None:
        """Singular/plural count prefix is grammatically correct in --strict-lock stderr.

        For 1 orphan: stderr contains '1 orphaned lockfile entry:'.
        For 2 orphans: stderr contains '2 orphaned lockfile entries:'.

        Spec reference: spec Section 4 E26 Edge cases.

        DEFECT-011 root cause: the current error message has no count-prefixed phrase;
        both parametrized cases fail RED because neither expected substring is present.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Build one bare repo for the active source.
        cat_active_bare = _create_manifest_repo_with_tags(
            repos_dir / "cat-active",
            entry_names=["source-foxtrot"],
            tags=["1.0.0"],
        )
        active_source_key = derive_source_name("source-foxtrot")

        # Build one bare repo per orphan (named golf-0, golf-1, ...).
        orphan_entries: list[tuple[str, str, str]] = []
        placeholder_sha = "b" * 40
        for idx in range(orphan_count):
            orphan_entry_name = f"source-golf-{idx}"
            orphan_bare = _create_manifest_repo_with_tags(
                repos_dir / f"cat-orphan-{idx}",
                entry_names=[orphan_entry_name],
                tags=["1.0.0"],
            )
            orphan_source_key = derive_source_name(orphan_entry_name)
            orphan_entries.append((orphan_source_key, str(orphan_bare), placeholder_sha))

        # Write .kanon with only the active source.
        placeholder_active_sha = "c" * 40
        kanon_path = self._write_kanon_single_source(
            project_dir,
            source_name=active_source_key,
            source_url=str(cat_active_bare),
        )

        real_hash = _compute_kanon_hash(kanon_path)
        catalog_source = f"file://{cat_active_bare}@main"

        lock_path = project_dir / ".kanon.lock"
        self._write_lockfile_with_orphans(
            lock_path,
            kanon_hash=real_hash,
            catalog_source=catalog_source,
            active_name=active_source_key,
            active_url=str(cat_active_bare),
            active_sha=placeholder_active_sha,
            orphan_entries=orphan_entries,
        )

        result = self._run_strict_lock_install(project_dir)

        stderr = result.stderr
        assert result.returncode != 0, (
            f"Expected non-zero exit for strict-lock with {orphan_count} orphan(s), got 0.\n"
            f"stdout: {result.stdout!r}\nstderr: {stderr!r}"
        )
        expected_phrase = f"{orphan_count} orphaned lockfile {expected_word}"
        assert expected_phrase in stderr, (
            f"Expected {expected_phrase!r} in stderr for {orphan_count} orphan(s).\n"
            f"stderr: {stderr!r}"
        )
