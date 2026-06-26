"""Unit tests for kanon_cli.commands.doctor consistency subchecks 1-5.

Covers:
- check 1: kanon_hash / lockfile presence (_check_kanon_hash)
- check 2: Hand-edit detection (HASH_MISMATCH code path inside _check_kanon_hash)
- check 3: Orphaned lock entries (_check_orphan_locks)
- check 4: Branch drift (_check_branch_drift)
- check 5: Dangling SHA (_check_dangling_shas)

AC-TEST-001: Each parametrized case asserts on DoctorFinding.kind AND
DoctorFinding.code.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from tests.conftest import (
    write_kanon_doctor_unit as _write_kanon,
    write_lockfile_doctor_unit as _write_lockfile,
)


def _compute_hash(kanon_file: pathlib.Path) -> str:
    """Return the kanon_hash for the given .kanon file."""
    from kanon_cli.core.kanon_hash import kanon_hash

    return kanon_hash(kanon_file)


@pytest.mark.unit
class TestDoctorFinding:
    """DoctorFinding dataclass has kind, code, message, remediation."""

    def test_finding_has_kind(self) -> None:
        from kanon_cli.commands.doctor import DoctorFinding

        f = DoctorFinding(kind="error", code="HASH_MISMATCH", message="msg", remediation="fix")
        assert f.kind == "error"

    def test_finding_has_code(self) -> None:
        from kanon_cli.commands.doctor import DoctorFinding

        f = DoctorFinding(kind="info", code="NO_LOCKFILE", message="msg", remediation="")
        assert f.code == "NO_LOCKFILE"

    def test_finding_has_message(self) -> None:
        from kanon_cli.commands.doctor import DoctorFinding

        f = DoctorFinding(kind="error", code="ORPHAN_LOCK", message="orphan source X", remediation="run kanon install")
        assert f.message == "orphan source X"

    def test_finding_has_remediation(self) -> None:
        from kanon_cli.commands.doctor import DoctorFinding

        f = DoctorFinding(kind="warn", code="BRANCH_DRIFT", message="drift", remediation="kanon install --refresh-lock")
        assert f.remediation == "kanon install --refresh-lock"

    @pytest.mark.parametrize("kind", ["info", "warn", "error"])
    def test_finding_valid_kinds(self, kind: str) -> None:
        from kanon_cli.commands.doctor import DoctorFinding

        f = DoctorFinding(kind=kind, code="X", message="m", remediation="r")
        assert f.kind == kind


@pytest.mark.unit
class TestCheckKanonHashConsistency:
    """_check_kanon_hash returns the right DoctorFinding for each scenario."""

    def test_no_kanon_file_returns_error_finding(self, tmp_path: pathlib.Path) -> None:
        """Missing .kanon returns finding with kind=error and code=NO_KANON."""
        from kanon_cli.commands.doctor import _check_kanon_hash

        kanon_file = tmp_path / ".kanon"
        lock_file = tmp_path / ".kanon.lock"
        finding = _check_kanon_hash(kanon_file, lock_file)

        assert finding.kind == "error"
        assert finding.code == "NO_KANON"
        assert str(tmp_path) in finding.message

    def test_no_lockfile_returns_info_finding(self, tmp_path: pathlib.Path) -> None:
        """Present .kanon but absent .kanon.lock returns finding with kind=info and code=NO_LOCKFILE."""
        from kanon_cli.commands.doctor import _check_kanon_hash

        kanon_file = _write_kanon(tmp_path)
        lock_file = tmp_path / ".kanon.lock"

        finding = _check_kanon_hash(kanon_file, lock_file)

        assert finding.kind == "info"
        assert finding.code == "NO_LOCKFILE"

    def test_matching_hash_returns_none(self, tmp_path: pathlib.Path) -> None:
        """When hash matches, check returns None (no finding)."""
        from kanon_cli.commands.doctor import _check_kanon_hash

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(tmp_path, kanon_hash_val=real_hash)
        lock_file = tmp_path / ".kanon.lock"

        result = _check_kanon_hash(kanon_file, lock_file)

        assert result is None

    def test_mismatched_hash_returns_error_finding(self, tmp_path: pathlib.Path) -> None:
        """When stored hash differs from computed hash, returns finding with kind=error and code=HASH_MISMATCH."""
        from kanon_cli.commands.doctor import _check_kanon_hash

        kanon_file = _write_kanon(tmp_path)

        _write_lockfile(tmp_path, kanon_hash_val="sha256:" + "b" * 64)
        lock_file = tmp_path / ".kanon.lock"

        finding = _check_kanon_hash(kanon_file, lock_file)

        assert finding is not None
        assert finding.kind == "error"
        assert finding.code == "HASH_MISMATCH"
        assert "kanon_hash mismatch" in finding.message
        assert "--refresh-lock" in finding.remediation

    def test_zero_source_kanon_returns_no_sources_finding(self, tmp_path: pathlib.Path) -> None:
        """A .kanon with zero source triples returns a clean NO_SOURCES error finding.

        The recompute of kanon_hash parses the .kanon file; a zero-source file
        raises ValueError from _discover_source_names. _check_kanon_hash must
        convert that into a structured DoctorFinding (kind=error, code=NO_SOURCES)
        rather than letting the exception escape and crash the CLI.
        """
        from kanon_cli.commands.doctor import _check_kanon_hash

        kanon_file = _write_kanon(tmp_path, content="KANON_MARKETPLACE_INSTALL=false\n")

        _write_lockfile(tmp_path, kanon_hash_val="sha256:" + "a" * 64)
        lock_file = tmp_path / ".kanon.lock"

        finding = _check_kanon_hash(kanon_file, lock_file)

        assert finding is not None
        assert finding.kind == "error"
        assert finding.code == "NO_SOURCES"
        assert "no sources" in finding.message.lower()
        assert "kanon add" in finding.remediation


@pytest.mark.unit
class TestCheckOrphanLocks:
    """_check_orphan_locks returns the right DoctorFinding for each scenario."""

    def test_no_orphan_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        """When lockfile sources all exist in .kanon, returns empty list."""
        from kanon_cli.commands.doctor import _check_orphan_locks
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(tmp_path, kanon_hash_val=real_hash, source_names=["src"])
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        findings = _check_orphan_locks(kanon_file, lockfile)

        assert findings == []

    def test_orphan_source_returns_error_finding(self, tmp_path: pathlib.Path) -> None:
        """When lockfile has a source absent from .kanon, returns error finding."""
        from kanon_cli.commands.doctor import _check_orphan_locks
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)

        _write_lockfile(tmp_path, kanon_hash_val=real_hash, source_names=["src", "ghost"])
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        findings = _check_orphan_locks(kanon_file, lockfile)

        assert len(findings) == 1
        assert findings[0].kind == "error"
        assert findings[0].code == "ORPHAN_LOCK"
        assert "ghost" in findings[0].message

    def test_multiple_orphans_returns_one_finding_per_orphan(self, tmp_path: pathlib.Path) -> None:
        """Each missing source produces exactly one error finding."""
        from kanon_cli.commands.doctor import _check_orphan_locks
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_names=["src", "ghost1", "ghost2"],
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        findings = _check_orphan_locks(kanon_file, lockfile)

        orphan_names = {f.message for f in findings}
        codes = {f.code for f in findings}
        kinds = {f.kind for f in findings}
        assert len(findings) == 2
        assert codes == {"ORPHAN_LOCK"}
        assert kinds == {"error"}

        assert any("ghost1" in m for m in orphan_names)
        assert any("ghost2" in m for m in orphan_names)


@pytest.mark.unit
class TestCheckBranchDrift:
    """_check_branch_drift returns the right DoctorFinding for each scenario."""

    def test_no_drift_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        """When branch tip matches locked SHA, returns empty list."""
        from kanon_cli.commands.doctor import _check_branch_drift
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        sha = "a" * 40
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_names=["src"],
            revision_specs={"src": "main"},
            resolved_shas={"src": sha},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        ls_remote_output = f"{sha}\trefs/heads/main\n"
        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(0, ls_remote_output, "")):
            findings = _check_branch_drift(lockfile, strict_drift=False)

        assert findings == []

    @pytest.mark.parametrize("strict_drift,expected_kind", [(False, "info"), (True, "error")])
    def test_drift_strict_mode_controls_finding_kind(self, strict_drift, expected_kind, tmp_path: pathlib.Path) -> None:
        """When branch tip differs from locked SHA, kind is 'info' without --strict-drift and 'error' with it."""
        from kanon_cli.commands.doctor import _check_branch_drift
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        locked_sha = "a" * 40
        new_sha = "b" * 40
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_names=["src"],
            revision_specs={"src": "main"},
            resolved_shas={"src": locked_sha},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        ls_remote_output = f"{new_sha}\trefs/heads/main\n"
        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(0, ls_remote_output, "")):
            findings = _check_branch_drift(lockfile, strict_drift=strict_drift)

        assert len(findings) == 1
        assert findings[0].kind == expected_kind
        assert findings[0].code == "BRANCH_DRIFT"

    def test_sha_pinned_source_skipped(self, tmp_path: pathlib.Path) -> None:
        """SHA-pinned sources (40-char hex revision) are skipped by branch drift check."""
        from kanon_cli.commands.doctor import _check_branch_drift
        from kanon_cli.core.lockfile import read_lockfile

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        sha_revision = "c" * 40
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_names=["src"],
            revision_specs={"src": sha_revision},
            resolved_shas={"src": sha_revision},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        with patch("kanon_cli.commands.doctor._run_ls_remote") as mock_ls:
            findings = _check_branch_drift(lockfile, strict_drift=False)
            mock_ls.assert_not_called()

        assert findings == []


@pytest.mark.unit
class TestCheckDanglingShas:
    """_check_dangling_shas returns the right DoctorFinding for each scenario."""

    def test_reachable_sha_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        """When SHA is reachable (in first column of ls-remote output), returns empty list.

        Uses a SHA-pinned source (revision_spec is a 40-char SHA) so the
        dangling SHA check runs (branch-pinned sources are skipped).
        """
        from kanon_cli.commands.doctor import _check_dangling_shas
        from kanon_cli.core.lockfile import read_lockfile

        sha = "a" * 40
        kanon_content = (
            f"KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            f"KANON_SOURCE_src_REF={sha}\n"
            f"KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            f"KANON_SOURCE_src_NAME=src\n"
            f"KANON_SOURCE_src_GITBASE=https://example.com\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
        )
        kanon_file = _write_kanon(tmp_path, content=kanon_content)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            resolved_shas={"src": sha},
            revision_specs={"src": sha},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(0, f"{sha}\trefs/heads/main\n", "")):
            findings = _check_dangling_shas(lockfile)

        assert findings == []

    def test_unreachable_sha_returns_error_finding(self, tmp_path: pathlib.Path) -> None:
        """When SHA is not found in ls-remote output, returns error finding.

        Uses a SHA-pinned source (revision_spec is a 40-char SHA) so the
        dangling SHA check is not skipped (branch-pinned sources are skipped).
        """
        from kanon_cli.commands.doctor import _check_dangling_shas
        from kanon_cli.core.lockfile import read_lockfile

        sha = "a" * 40
        kanon_content = (
            f"KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            f"KANON_SOURCE_src_REF={sha}\n"
            f"KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            f"KANON_SOURCE_src_NAME=src\n"
            f"KANON_SOURCE_src_GITBASE=https://example.com\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
        )
        kanon_file = _write_kanon(tmp_path, content=kanon_content)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            resolved_shas={"src": sha},
            revision_specs={"src": sha},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        other_sha = "b" * 40
        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(0, f"{other_sha}\trefs/heads/main\n", "")):
            findings = _check_dangling_shas(lockfile)

        assert len(findings) == 1
        assert findings[0].kind == "error"
        assert findings[0].code == "DANGLING_SHA"
        assert sha in findings[0].message

    def test_ls_remote_failure_returns_error_finding(self, tmp_path: pathlib.Path) -> None:
        """When ls-remote exits non-zero, returns error finding.

        Uses a SHA-pinned source (revision_spec is a 40-char SHA) so the
        dangling SHA check is not skipped.
        """
        from kanon_cli.commands.doctor import _check_dangling_shas
        from kanon_cli.core.lockfile import read_lockfile

        sha = "a" * 40
        kanon_content = (
            f"KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            f"KANON_SOURCE_src_REF={sha}\n"
            f"KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            f"KANON_SOURCE_src_NAME=src\n"
            f"KANON_SOURCE_src_GITBASE=https://example.com\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
        )
        kanon_file = _write_kanon(tmp_path, content=kanon_content)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            resolved_shas={"src": sha},
            revision_specs={"src": sha},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(128, "", "not a git repo")):
            findings = _check_dangling_shas(lockfile)

        assert len(findings) == 1
        assert findings[0].kind == "error"
        assert findings[0].code == "DANGLING_SHA"
        assert sha in findings[0].message

    def test_multiple_sources_one_dangling(self, tmp_path: pathlib.Path) -> None:
        """Only the source with a dangling SHA produces an error finding.

        Uses SHA-pinned sources for both so neither is skipped by the
        branch-pinned source exclusion logic.
        """
        from kanon_cli.commands.doctor import _check_dangling_shas
        from kanon_cli.core.lockfile import read_lockfile

        sha1 = "a" * 40
        sha2 = "b" * 40
        kanon_content = (
            f"KANON_SOURCE_src1_URL=https://example.com/org/repo1.git\n"
            f"KANON_SOURCE_src1_REF={sha1}\n"
            f"KANON_SOURCE_src1_PATH=repo-specs/meta.xml\n"
            f"KANON_SOURCE_src1_NAME=src1\n"
            f"KANON_SOURCE_src1_GITBASE=https://example.com\n"
            f"KANON_SOURCE_src2_URL=https://example.com/org/repo2.git\n"
            f"KANON_SOURCE_src2_REF={sha2}\n"
            f"KANON_SOURCE_src2_PATH=repo-specs/meta2.xml\n"
            f"KANON_SOURCE_src2_NAME=src2\n"
            f"KANON_SOURCE_src2_GITBASE=https://example.com\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
        )
        kanon_file = _write_kanon(tmp_path, content=kanon_content)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_names=["src1", "src2"],
            resolved_shas={"src1": sha1, "src2": sha2},
            revision_specs={"src1": sha1, "src2": sha2},
            urls={"src1": "https://example.com/org/repo1.git", "src2": "https://example.com/org/repo2.git"},
        )
        lock_file = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lock_file)

        def _fake_ls_remote(
            url: str, ref: str, timeout: int, retry_count: int, retry_delay: float
        ) -> tuple[int, str, str]:
            if url == "https://example.com/org/repo1.git":
                return (0, f"{sha1}\trefs/heads/main\n", "")

            return (0, f"{'c' * 40}\trefs/heads/main\n", "")

        with patch("kanon_cli.commands.doctor._run_ls_remote", side_effect=_fake_ls_remote):
            findings = _check_dangling_shas(lockfile)

        assert len(findings) == 1
        assert findings[0].code == "DANGLING_SHA"
        assert sha2 in findings[0].message


@pytest.mark.unit
class TestDoctorCommand:
    """doctor_command returns the correct exit code and prints findings."""

    def _make_args(
        self,
        kanon_file: str | None = None,
        lock_file: str | None = None,
        strict_drift: bool = False,
        no_color: bool = False,
        refresh_completion_cache: bool = False,
    ) -> object:
        import argparse

        return argparse.Namespace(
            kanon_file=kanon_file,
            lock_file=lock_file,
            strict_drift=strict_drift,
            no_color=no_color,
            refresh_completion_cache=refresh_completion_cache,
        )

    def test_no_kanon_file_returns_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor_command returns non-zero when .kanon is absent."""
        from kanon_cli.commands.doctor import doctor_command

        missing = str(tmp_path / ".kanon")
        args = self._make_args(kanon_file=missing)
        result = doctor_command(args)

        assert result != 0

    def test_no_lockfile_returns_zero(self, tmp_path: pathlib.Path) -> None:
        """doctor_command returns 0 when .kanon is present but .kanon.lock is absent."""
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = _write_kanon(tmp_path)
        args = self._make_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        assert result == 0

    def test_no_lockfile_prints_info_notice(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """doctor_command prints info-level notice to stderr when no lockfile is present."""
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = _write_kanon(tmp_path)
        args = self._make_args(kanon_file=str(kanon_file))
        doctor_command(args)

        captured = capsys.readouterr()
        assert "No lockfile present" in captured.err

    def test_matching_hash_returns_zero(self, tmp_path: pathlib.Path) -> None:
        """doctor_command returns 0 when lockfile matches .kanon."""
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = _write_kanon(tmp_path)
        real_hash = _compute_hash(kanon_file)
        _write_lockfile(tmp_path, kanon_hash_val=real_hash)
        sha = "a" * 40
        lock_file = tmp_path / ".kanon.lock"

        args = self._make_args(kanon_file=str(kanon_file), lock_file=str(lock_file))

        with patch("kanon_cli.commands.doctor._run_ls_remote", return_value=(0, f"{sha}\t{sha}\n", "")):
            result = doctor_command(args)

        assert result == 0

    def test_hash_mismatch_returns_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor_command returns non-zero when kanon_hash is mismatched."""
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = _write_kanon(tmp_path)
        _write_lockfile(tmp_path, kanon_hash_val="sha256:" + "b" * 64)
        lock_file = tmp_path / ".kanon.lock"

        args = self._make_args(kanon_file=str(kanon_file), lock_file=str(lock_file))
        result = doctor_command(args)

        assert result != 0

    def test_zero_source_kanon_returns_nonzero_cleanly(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """doctor_command returns non-zero and prints a clean NO_SOURCES error for a zero-source .kanon.

        The command must not raise the underlying ValueError from
        _discover_source_names; it reports the structured finding and exits
        non-zero instead.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = _write_kanon(tmp_path, content="KANON_MARKETPLACE_INSTALL=false\n")
        _write_lockfile(tmp_path, kanon_hash_val="sha256:" + "a" * 64)
        lock_file = tmp_path / ".kanon.lock"

        args = self._make_args(kanon_file=str(kanon_file), lock_file=str(lock_file))
        result = doctor_command(args)

        assert result != 0
        captured = capsys.readouterr()
        assert "no sources" in captured.err.lower(), f"stderr={captured.err!r}"
