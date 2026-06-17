"""Unit tests for --strict-lock and --strict-drift flags in kanon install.

Covers spec Section 4.7 state-matrix rows for:
- Orphaned lock entry (source in lockfile but absent from .kanon)
- Branch drift (branch tip on remote differs from locked SHA)

AC-TEST-001: parametrises the five cases:
  (a) orphan + default flag = prune-and-info (AC-FUNC-001)
  (b) orphan + --strict-lock = hard error (AC-FUNC-002)
  (c) drift + default flag = reuse-and-info (AC-FUNC-003)
  (d) drift + --strict-drift = hard error (AC-FUNC-004)
  (e) both flags set with both event types present (AC-FUNC-005)
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    BranchDriftError,
    BranchDriftReport,
    OrphanedLockEntryError,
    _detect_branch_drift,
    _detect_orphaned_lock_entries,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash
from kanon_cli.core.lockfile import CURRENT_SCHEMA_VERSION, Lockfile, SourceEntry


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FAKE_SHA_ALPHA = "a" * 40
_FAKE_SHA_BETA = "b" * 40
_FAKE_SHA_REMOTE = "c" * 40  # simulates the remote's current branch tip


# ---------------------------------------------------------------------------
# Helpers to build test fixtures
# ---------------------------------------------------------------------------


def _write_kanon_single(
    directory: pathlib.Path,
    source_name: str = "alpha",
    url: str = "https://git.example.com/alpha.git",
    revision: str = "main",
) -> pathlib.Path:
    """Write a minimal single-source .kanon file."""
    kanon_path = directory / ".kanon"
    kanon_path.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL={url}\n"
        f"KANON_SOURCE_{source_name}_REVISION={revision}\n"
        f"KANON_SOURCE_{source_name}_PATH=manifest.xml\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _write_lockfile_with_orphan(
    directory: pathlib.Path,
    kanon_hash: str,
    active_source: str = "alpha",
    orphan_source: str = "ghost",
    sha_active: str = _FAKE_SHA_ALPHA,
    sha_orphan: str = _FAKE_SHA_BETA,
) -> pathlib.Path:
    """Write a lockfile containing one active source + one orphaned source."""
    lock_path = directory / ".kanon.lock"
    lock_path.write_text(
        f"schema_version = {CURRENT_SCHEMA_VERSION}\n"
        f'generated_at = "2026-01-15T00:00:00Z"\n'
        f'generator = "kanon-cli/test"\n'
        f'kanon_hash = "{kanon_hash}"\n'
        f"\n"
        f"[[sources]]\n"
        f'alias = "{active_source}"\n'
        f'name = "{active_source}"\n'
        f'url = "https://git.example.com/{active_source}.git"\n'
        f'ref_spec = "main"\n'
        f'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{sha_active}"\n'
        f'path = "manifest.xml"\n'
        f"\n"
        f"[[sources]]\n"
        f'alias = "{orphan_source}"\n'
        f'name = "{orphan_source}"\n'
        f'url = "https://git.example.com/{orphan_source}.git"\n'
        f'ref_spec = "main"\n'
        f'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{sha_orphan}"\n'
        f'path = "manifest.xml"\n'
    )
    return lock_path


def _write_lockfile_branch(
    directory: pathlib.Path,
    kanon_hash: str,
    source_name: str = "alpha",
    sha: str = _FAKE_SHA_ALPHA,
    revision_spec: str = "main",
    resolved_ref: str = "refs/heads/main",
) -> pathlib.Path:
    """Write a minimal lockfile for a branch-shaped source."""
    lock_path = directory / ".kanon.lock"
    lock_path.write_text(
        f"schema_version = {CURRENT_SCHEMA_VERSION}\n"
        f'generated_at = "2026-01-15T00:00:00Z"\n'
        f'generator = "kanon-cli/test"\n'
        f'kanon_hash = "{kanon_hash}"\n'
        f"\n"
        f"[[sources]]\n"
        f'alias = "{source_name}"\n'
        f'name = "{source_name}"\n'
        f'url = "https://git.example.com/{source_name}.git"\n'
        f'ref_spec = "{revision_spec}"\n'
        f'resolved_ref = "{resolved_ref}"\n'
        f'resolved_sha = "{sha}"\n'
        f'path = "manifest.xml"\n'
    )
    return lock_path


def _build_source_entry(
    name: str,
    url: str = "https://git.example.com/alpha.git",
    ref_spec: str = "main",
    resolved_ref: str = "refs/heads/main",
    resolved_sha: str = _FAKE_SHA_ALPHA,
    path: str = "manifest.xml",
) -> SourceEntry:
    return SourceEntry(
        alias=name,
        name=name,
        url=url,
        ref_spec=ref_spec,
        resolved_ref=resolved_ref,
        resolved_sha=resolved_sha,
        path=path,
    )


def _build_lockfile(
    kanon_hash: str,
    sources: list[SourceEntry],
) -> Lockfile:
    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2026-01-15T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash=kanon_hash,
        sources=sources,
    )


# ===========================================================================
# Tests for _detect_orphaned_lock_entries (AC-FUNC-007)
# ===========================================================================


@pytest.mark.unit
class TestDetectOrphanedLockEntries:
    """Unit tests for _detect_orphaned_lock_entries helper."""

    def test_no_orphans_when_all_sources_present(self) -> None:
        """Returns empty list when every lockfile source appears in kanon_sources."""
        sources = [
            _build_source_entry("alpha"),
            _build_source_entry("beta"),
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        result = _detect_orphaned_lock_entries(lockfile, ["alpha", "beta"])
        assert result == []

    def test_detects_single_orphan(self) -> None:
        """Returns the name of a source in the lockfile but absent from kanon."""
        sources = [
            _build_source_entry("alpha"),
            _build_source_entry("ghost"),
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        result = _detect_orphaned_lock_entries(lockfile, ["alpha"])
        assert result == ["ghost"]

    def test_detects_multiple_orphans(self) -> None:
        """All orphaned source names are returned."""
        sources = [
            _build_source_entry("alpha"),
            _build_source_entry("ghost1"),
            _build_source_entry("ghost2"),
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        result = _detect_orphaned_lock_entries(lockfile, ["alpha"])
        assert sorted(result) == ["ghost1", "ghost2"]

    def test_empty_lockfile_sources(self) -> None:
        """Returns empty list when lockfile has no sources."""
        lockfile = _build_lockfile("sha256:" + "a" * 64, [])
        result = _detect_orphaned_lock_entries(lockfile, ["alpha"])
        assert result == []

    def test_empty_kanon_sources_all_orphaned(self) -> None:
        """When kanon_sources is empty, every lockfile source is an orphan."""
        sources = [
            _build_source_entry("alpha"),
            _build_source_entry("beta"),
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        result = _detect_orphaned_lock_entries(lockfile, [])
        assert sorted(result) == ["alpha", "beta"]


# ===========================================================================
# Tests for _detect_branch_drift (AC-FUNC-008)
# ===========================================================================


@pytest.mark.unit
class TestDetectBranchDrift:
    """Unit tests for _detect_branch_drift helper."""

    def _make_ls_remote_result(self, sha: str, ref: str = "refs/heads/main") -> MagicMock:
        """Build a mock subprocess.CompletedProcess with ls-remote output."""
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = f"{sha}\t{ref}\n"
        return mock

    def test_no_drift_when_sha_matches_remote(self) -> None:
        """No reports when locked SHA equals current branch tip."""
        sources = [_build_source_entry("alpha", resolved_sha=_FAKE_SHA_ALPHA)]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        with patch(
            "kanon_cli.core.install.subprocess.run",
            return_value=self._make_ls_remote_result(_FAKE_SHA_ALPHA),
        ):
            reports = _detect_branch_drift(lockfile)
        assert reports == []

    def test_detects_drift_when_sha_differs(self) -> None:
        """Returns one report when locked SHA differs from remote branch tip."""
        sources = [_build_source_entry("alpha", resolved_sha=_FAKE_SHA_ALPHA)]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        with patch(
            "kanon_cli.core.install.subprocess.run",
            return_value=self._make_ls_remote_result(_FAKE_SHA_REMOTE),
        ):
            reports = _detect_branch_drift(lockfile)
        assert len(reports) == 1
        report = reports[0]
        assert isinstance(report, BranchDriftReport)
        assert report.source_name == "alpha"
        assert report.branch == "main"
        assert report.locked_sha == _FAKE_SHA_ALPHA
        assert report.current_sha == _FAKE_SHA_REMOTE

    def test_skips_pep440_tag_shaped_spec(self) -> None:
        """Sources with PEP 440 ref_spec (tags) are skipped."""
        sources = [_build_source_entry("alpha", ref_spec="==1.0.0", resolved_sha=_FAKE_SHA_ALPHA)]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            reports = _detect_branch_drift(lockfile)
        mock_run.assert_not_called()
        assert reports == []

    def test_skips_refs_tags_spec(self) -> None:
        """Sources with refs/tags/ ref_spec are skipped."""
        sources = [
            _build_source_entry(
                "alpha",
                ref_spec="refs/tags/1.0.0",
                resolved_ref="refs/tags/1.0.0",
                resolved_sha=_FAKE_SHA_ALPHA,
            )
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            reports = _detect_branch_drift(lockfile)
        mock_run.assert_not_called()
        assert reports == []

    def test_branch_spec_with_refs_heads_prefix(self) -> None:
        """refs/heads/ specs are treated as branch-shaped and checked for drift."""
        sources = [
            _build_source_entry(
                "alpha",
                ref_spec="refs/heads/main",
                resolved_ref="refs/heads/main",
                resolved_sha=_FAKE_SHA_ALPHA,
            )
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)
        with patch(
            "kanon_cli.core.install.subprocess.run",
            return_value=self._make_ls_remote_result(_FAKE_SHA_REMOTE, "refs/heads/main"),
        ):
            reports = _detect_branch_drift(lockfile)
        assert len(reports) == 1
        assert reports[0].current_sha == _FAKE_SHA_REMOTE

    def test_multiple_sources_partial_drift(self) -> None:
        """Only the drifted branch is reported; stable branches are silent."""
        sources = [
            _build_source_entry("alpha", resolved_sha=_FAKE_SHA_ALPHA),
            _build_source_entry("beta", url="https://git.example.com/beta.git", resolved_sha=_FAKE_SHA_BETA),
        ]
        lockfile = _build_lockfile("sha256:" + "a" * 64, sources)

        def _ls_remote_side_effect(*args, **kwargs):
            # args[0] is the command list: ["git", "ls-remote", url, ref]
            url = args[0][2]
            mock = MagicMock()
            mock.returncode = 0
            if "alpha" in url:
                # alpha has drifted
                mock.stdout = f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n"
            else:
                # beta is stable
                mock.stdout = f"{_FAKE_SHA_BETA}\trefs/heads/main\n"
            return mock

        with patch("kanon_cli.core.install.subprocess.run", side_effect=_ls_remote_side_effect):
            reports = _detect_branch_drift(lockfile)

        assert len(reports) == 1
        assert reports[0].source_name == "alpha"


# ===========================================================================
# Tests for OrphanedLockEntryError (AC-FUNC-002)
# ===========================================================================


@pytest.mark.unit
class TestOrphanedLockEntryError:
    """Unit tests for the OrphanedLockEntryError exception class."""

    def test_str_contains_orphan_names(self) -> None:
        err = OrphanedLockEntryError(orphaned_names=["ghost1", "ghost2"])
        s = str(err)
        assert "ghost1" in s
        assert "ghost2" in s

    def test_str_contains_remediation(self) -> None:
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        s = str(err)
        assert "--strict-lock" in s

    def test_is_install_error_subclass(self) -> None:
        from kanon_cli.core.install import InstallError

        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert isinstance(err, InstallError)


# ===========================================================================
# Tests for BranchDriftError (AC-FUNC-004)
# ===========================================================================


@pytest.mark.unit
class TestBranchDriftError:
    """Unit tests for the BranchDriftError exception class."""

    def test_str_contains_source_name(self) -> None:
        reports = [BranchDriftReport("alpha", "main", _FAKE_SHA_ALPHA, _FAKE_SHA_REMOTE)]
        err = BranchDriftError(reports=reports)
        s = str(err)
        assert "alpha" in s

    def test_str_contains_both_shas(self) -> None:
        reports = [BranchDriftReport("alpha", "main", _FAKE_SHA_ALPHA, _FAKE_SHA_REMOTE)]
        err = BranchDriftError(reports=reports)
        s = str(err)
        assert _FAKE_SHA_ALPHA in s
        assert _FAKE_SHA_REMOTE in s

    def test_str_contains_remediation(self) -> None:
        reports = [BranchDriftReport("alpha", "main", _FAKE_SHA_ALPHA, _FAKE_SHA_REMOTE)]
        err = BranchDriftError(reports=reports)
        s = str(err)
        assert "--refresh-lock-source" in s

    def test_is_install_error_subclass(self) -> None:
        from kanon_cli.core.install import InstallError

        reports = [BranchDriftReport("alpha", "main", _FAKE_SHA_ALPHA, _FAKE_SHA_REMOTE)]
        err = BranchDriftError(reports=reports)
        assert isinstance(err, InstallError)


# ===========================================================================
# Tests for AC-FUNC-001: orphan + no flag -> prune + info-line
# ===========================================================================


@pytest.mark.unit
class TestOrphanPruneNoFlag:
    """AC-FUNC-001: Orphaned entries are pruned and info-line is emitted (default mode)."""

    def test_orphan_pruned_and_info_emitted(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Install with orphaned lock entry (default): prunes entry, emits info-line."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_with_orphan(
            tmp_path,
            real_hash,
            active_source="alpha",
            orphan_source="ghost",
        )

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            # ls-remote call from _detect_branch_drift: alpha's tip equals locked SHA
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_ALPHA}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=False,
                strict_drift=False,
            )

        captured = capsys.readouterr()
        assert "pruned orphaned lock entry: ghost" in captured.out

    def test_orphan_pruned_from_rewritten_lockfile(self, tmp_path: pathlib.Path) -> None:
        """The rewritten lockfile must NOT contain the orphaned source entry."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_with_orphan(
            tmp_path,
            real_hash,
            active_source="alpha",
            orphan_source="ghost",
        )

        from kanon_cli.core.install import _RefResolution
        from kanon_cli.core.lockfile import read_lockfile

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_ALPHA}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=False,
                strict_drift=False,
            )

        lock_path = tmp_path / ".kanon.lock"
        updated_lockfile = read_lockfile(lock_path)
        source_names = [s.name for s in updated_lockfile.sources]
        assert "ghost" not in source_names
        assert "alpha" in source_names


# ===========================================================================
# Tests for AC-FUNC-002: orphan + --strict-lock -> OrphanedLockEntryError
# ===========================================================================


@pytest.mark.unit
class TestOrphanStrictLock:
    """AC-FUNC-002: --strict-lock upgrades orphaned entries to hard errors."""

    def test_strict_lock_raises_orphaned_error(self, tmp_path: pathlib.Path) -> None:
        """install with --strict-lock and an orphan raises OrphanedLockEntryError."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_with_orphan(
            tmp_path,
            real_hash,
            active_source="alpha",
            orphan_source="ghost",
        )

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(OrphanedLockEntryError) as exc_info,
        ):
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=True,
                strict_drift=False,
            )

        assert "ghost" in str(exc_info.value)

    def test_strict_lock_error_lists_all_orphans(self, tmp_path: pathlib.Path) -> None:
        """OrphanedLockEntryError names every orphaned source in the message."""
        # Write a .kanon with only "alpha"
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha")
        real_hash = compute_kanon_hash(kanon_path)
        # Lockfile has alpha (active) + ghost1, ghost2 (orphans)
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text(
            f"schema_version = {CURRENT_SCHEMA_VERSION}\n"
            f'generated_at = "2026-01-15T00:00:00Z"\n'
            f'generator = "kanon-cli/test"\n'
            f'kanon_hash = "{real_hash}"\n'
            f"\n"
            f"[[sources]]\n"
            f'alias = "alpha"\n'
            f'name = "alpha"\n'
            f'url = "https://git.example.com/alpha.git"\n'
            f'ref_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_FAKE_SHA_ALPHA}"\n'
            f'path = "manifest.xml"\n'
            f"\n"
            f"[[sources]]\n"
            f'alias = "ghost1"\n'
            f'name = "ghost1"\n'
            f'url = "https://git.example.com/ghost1.git"\n'
            f'ref_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_FAKE_SHA_BETA}"\n'
            f'path = "manifest.xml"\n'
            f"\n"
            f"[[sources]]\n"
            f'alias = "ghost2"\n'
            f'name = "ghost2"\n'
            f'url = "https://git.example.com/ghost2.git"\n'
            f'ref_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_FAKE_SHA_BETA}"\n'
            f'path = "manifest.xml"\n'
        )

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(OrphanedLockEntryError) as exc_info,
        ):
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=True,
                strict_drift=False,
            )

        error_msg = str(exc_info.value)
        assert "ghost1" in error_msg
        assert "ghost2" in error_msg

    def test_strict_lock_error_remediation_text(self, tmp_path: pathlib.Path) -> None:
        """OrphanedLockEntryError includes remediation text."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_with_orphan(tmp_path, real_hash)

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(OrphanedLockEntryError) as exc_info,
        ):
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=True,
            )

        error_msg = str(exc_info.value)
        # Remediation must mention running without --strict-lock OR restoring source triples
        assert "KANON_SOURCE_" in error_msg or "--strict-lock" in error_msg


# ===========================================================================
# Tests for AC-FUNC-003: drift + no flag -> reuse + info-line
# ===========================================================================


@pytest.mark.unit
class TestDriftReuseNoFlag:
    """AC-FUNC-003: Branch drift (default mode) reuses locked SHA and emits info-line."""

    def test_drift_reuse_emits_info_line(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Branch drift without --strict-drift: emits the drift info-line and exits 0."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_branch(tmp_path, real_hash, source_name="alpha", sha=_FAKE_SHA_ALPHA)

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            # Remote tip differs from locked SHA -- simulates drift
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=False,
                strict_drift=False,
            )

        captured = capsys.readouterr()
        expected_fragment = f"branch drift: alpha: main tip {_FAKE_SHA_REMOTE} differs from locked {_FAKE_SHA_ALPHA}; reusing locked SHA"
        assert expected_fragment in captured.out

    def test_drift_reuse_uses_locked_sha(self, tmp_path: pathlib.Path) -> None:
        """Branch drift without --strict-drift: the locked SHA is passed to repo init."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_branch(tmp_path, real_hash, source_name="alpha", sha=_FAKE_SHA_ALPHA)

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init") as mock_init,
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=False,
                strict_drift=False,
            )

        # repo init should use the locked SHA, NOT the remote tip
        assert mock_init.called
        init_call_args = mock_init.call_args
        # Third positional arg to run_repo_init is the revision passed to repo init
        called_revision = init_call_args.args[2]
        assert called_revision == _FAKE_SHA_ALPHA


# ===========================================================================
# Tests for AC-FUNC-004: drift + --strict-drift -> BranchDriftError
# ===========================================================================


@pytest.mark.unit
class TestDriftStrictFlag:
    """AC-FUNC-004: --strict-drift upgrades branch drift to a hard error."""

    def test_strict_drift_raises_branch_drift_error(self, tmp_path: pathlib.Path) -> None:
        """install with --strict-drift and a drifted branch raises BranchDriftError."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_branch(tmp_path, real_hash, source_name="alpha", sha=_FAKE_SHA_ALPHA)

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(BranchDriftError) as exc_info,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=False,
                strict_drift=True,
            )

        error_msg = str(exc_info.value)
        assert "alpha" in error_msg
        assert _FAKE_SHA_ALPHA in error_msg
        assert _FAKE_SHA_REMOTE in error_msg

    def test_strict_drift_error_remediation_mentions_refresh_lock_source(self, tmp_path: pathlib.Path) -> None:
        """BranchDriftError remediation instructs --refresh-lock-source."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile_branch(tmp_path, real_hash, source_name="alpha", sha=_FAKE_SHA_ALPHA)

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            pytest.raises(BranchDriftError) as exc_info,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_drift=True,
            )

        error_msg = str(exc_info.value)
        assert "--refresh-lock-source" in error_msg


# ===========================================================================
# Tests for AC-FUNC-005: both flags, both events present
# ===========================================================================


@pytest.mark.unit
class TestBothFlagsBothEvents:
    """AC-FUNC-005: --strict-lock + --strict-drift with both event types.

    Orphan error is raised first (deterministic ordering).
    """

    def test_orphan_error_raised_first_when_both_events_present(self, tmp_path: pathlib.Path) -> None:
        """When orphan AND drift both exist with both strict flags, OrphanedLockEntryError fires first."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        real_hash = compute_kanon_hash(kanon_path)
        # Lockfile has alpha (active, drifted) AND ghost (orphan)
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text(
            f"schema_version = {CURRENT_SCHEMA_VERSION}\n"
            f'generated_at = "2026-01-15T00:00:00Z"\n'
            f'generator = "kanon-cli/test"\n'
            f'kanon_hash = "{real_hash}"\n'
            f"\n"
            f"[[sources]]\n"
            f'alias = "alpha"\n'
            f'name = "alpha"\n'
            f'url = "https://git.example.com/alpha.git"\n'
            f'ref_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_FAKE_SHA_ALPHA}"\n'
            f'path = "manifest.xml"\n'
            f"\n"
            f"[[sources]]\n"
            f'alias = "ghost"\n'
            f'name = "ghost"\n'
            f'url = "https://git.example.com/ghost.git"\n'
            f'ref_spec = "main"\n'
            f'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_FAKE_SHA_BETA}"\n'
            f'path = "manifest.xml"\n'
        )

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            # The orphan error must be raised, not the drift error
            pytest.raises(OrphanedLockEntryError),
        ):
            # Both alpha's tip differs from locked SHA (drift) AND ghost is orphaned
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_lock=True,
                strict_drift=True,
            )


# ===========================================================================
# Tests for AC-FUNC-006: drift detector only runs in consistent state
# ===========================================================================


@pytest.mark.unit
class TestDriftDetectorScope:
    """AC-FUNC-006: drift detection only in LOCKFILE_CONSISTENT state."""

    def test_drift_not_emitted_in_lockfile_absent_state(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When lockfile is absent, no branch drift info-line is emitted."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        # No lockfile -- LOCKFILE_ABSENT state

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_drift=True,
            )

        captured = capsys.readouterr()
        assert "branch drift" not in captured.out

    def test_drift_not_raised_in_lockfile_absent_state(self, tmp_path: pathlib.Path) -> None:
        """strict-drift does NOT raise when lockfile is absent (no lockfile to compare)."""
        kanon_path = _write_kanon_single(tmp_path, source_name="alpha", revision="main")
        # No lockfile

        from kanon_cli.core.install import _RefResolution

        fake_ref = _RefResolution(sha=_FAKE_SHA_ALPHA, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_ref),
            patch("kanon_cli.core.install._check_sha_reachable"),
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{_FAKE_SHA_REMOTE}\trefs/heads/main\n")
            # Must NOT raise BranchDriftError -- lockfile is absent, nothing to compare
            install(
                kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                strict_drift=True,
            )
