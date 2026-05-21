"""Unit tests closing coverage gaps in src/kanon_cli/commands/doctor.py.

Gaps targeted (from coverage_gaps.md produced by E15-F4-S1-T1):
- Line 114: _is_branch_revision returns False when revision_spec starts with "refs/"
- Line 184: _run_ls_remote_impl sleep path on TimeoutExpired when attempt < retry_count - 1
- Lines 219-223: _run_ls_remote function body (always mocked elsewhere, now tested directly)
- Line 454: _check_branch_drift continue on returncode != 0
- Lines 1114-1116: run_doctor / doctor_command orphan-lock findings loop
- Lines 1121-1123: run_doctor / doctor_command branch-drift findings loop
- Lines 1128-1130: run_doctor / doctor_command dangling-SHA findings loop
- Line 1139: run_doctor / doctor_command remote-reachability findings loop

All gaps are category "test-needed". No restructure-needed or pragma exclusions.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess

import pytest

from kanon_cli.commands.doctor import (
    DoctorFinding,
    _check_branch_drift,
    _is_branch_revision,
    _run_ls_remote,
    _run_ls_remote_impl,
    doctor_command,
)
from kanon_cli.core.lockfile import (
    CatalogBlock,
    Lockfile,
    SourceEntry,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _write_minimal_kanon(kanon_file: pathlib.Path) -> None:
    """Write a minimal .kanon file with only a catalog source declaration.

    Args:
        kanon_file: Path to write the .kanon file.
    """
    kanon_file.write_text(
        "KANON_CATALOG_SOURCE=https://example.com/catalog.git@main\n",
        encoding="utf-8",
    )


def _stub_doctor_subchecks(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    """Stub all doctor subcheck functions with no-op defaults.

    Stubs: _check_branch_drift, _check_dangling_shas, _check_remote_reachability,
    _run_completion_subchecks, _check_effective_catalog_source, _check_kanon_hash,
    and optionally _check_orphan_locks.

    Each stub may be overridden via keyword arguments where the key is the
    function name and the value is the replacement callable.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        **overrides: Map of function-name to replacement callable.
    """
    import kanon_cli.commands.doctor as doctor_mod

    defaults: dict[str, object] = {
        "_check_branch_drift": lambda lockfile, strict_drift: [],
        "_check_dangling_shas": lambda lockfile: [],
        "_check_remote_reachability": lambda lockfile, callable, policy: [],
        "_run_completion_subchecks": lambda generator: None,
        "_check_effective_catalog_source": lambda args, env, lockfile: DoctorFinding(
            kind="info", code="CATALOG_SOURCE_OK", message="ok", remediation=""
        ),
        "_check_kanon_hash": lambda kanon_file, lock_file: None,
    }
    defaults.update(overrides)
    for name, stub in defaults.items():
        monkeypatch.setattr(doctor_mod, name, stub)


def _make_lockfile_with_sources(
    tmp_path: pathlib.Path,
    sources: list[dict],
) -> Lockfile:
    """Build and write a Lockfile with the given source list.

    Args:
        tmp_path: Temp directory for the lockfile file.
        sources: List of dicts with keys: name, url, revision_spec, resolved_sha.

    Returns:
        A Lockfile dataclass instance read back from disk.
    """
    from kanon_cli.core.lockfile import read_lockfile

    entries = [
        SourceEntry(
            name=s["name"],
            url=s["url"],
            revision_spec=s["revision_spec"],
            resolved_ref=s["revision_spec"],
            resolved_sha=s["resolved_sha"],
            path="repo-specs/meta.xml",
        )
        for s in sources
    ]
    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=entries,
    )
    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return read_lockfile(lock_path)


def _make_doctor_args(
    kanon_file: str | None = None,
    strict_drift: bool = False,
    refresh_completion_cache: bool = False,
    prune_cache: bool = False,
) -> argparse.Namespace:
    """Construct argparse.Namespace for doctor_command / run_doctor.

    Args:
        kanon_file: Path to .kanon file, or None to use default.
        strict_drift: Promote branch-drift findings to errors.
        refresh_completion_cache: Flag for --refresh-completion-cache.
        prune_cache: Flag for --prune-cache.

    Returns:
        Namespace with all required attributes.
    """
    return argparse.Namespace(
        kanon_file=kanon_file,
        strict_drift=strict_drift,
        refresh_completion_cache=refresh_completion_cache,
        prune_cache=prune_cache,
    )


# ---------------------------------------------------------------------------
# Line 114: _is_branch_revision returns False for refs/-prefixed strings
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision_spec,expected",
    [
        ("refs/heads/main", False),
        ("refs/tags/1.0.0", False),
        ("refs/custom/something", False),
        ("main", True),
        ("a" * 40, False),
        ("b" * 64, False),
    ],
    ids=[
        "refs_heads_returns_false",
        "refs_tags_returns_false",
        "refs_prefix_returns_false",
        "plain_branch_name_returns_true",
        "sha40_returns_false",
        "sha64_returns_false",
    ],
)
def test_is_branch_revision(revision_spec: str, expected: bool) -> None:
    """_is_branch_revision returns expected result for each revision_spec."""
    assert _is_branch_revision(revision_spec) is expected


# ---------------------------------------------------------------------------
# Line 184: _run_ls_remote_impl sleep path on TimeoutExpired retries
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLsRemoteImplTimeoutSleepPath:
    """_run_ls_remote_impl calls time.sleep between TimeoutExpired retries."""

    def test_sleep_called_between_timeout_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """time.sleep is called when TimeoutExpired occurs and attempt < retry_count - 1."""
        sleep_calls: list[float] = []

        def _fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(subprocess, "run", _fake_run)
        monkeypatch.setattr(doctor_mod.time, "sleep", _fake_sleep)

        # retry_count=2 means two attempts; between them one sleep should occur
        retry_delay = 0.5
        _run_ls_remote_impl(
            ["git", "ls-remote", "https://example.com/repo.git", "HEAD"],
            timeout=1,
            retry_count=2,
            retry_delay=retry_delay,
        )

        assert len(sleep_calls) == 1
        assert sleep_calls[0] == retry_delay

    def test_sleep_not_called_on_last_timeout_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """time.sleep is NOT called after the final TimeoutExpired attempt."""
        sleep_calls: list[float] = []

        def _fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(subprocess, "run", _fake_run)
        monkeypatch.setattr(doctor_mod.time, "sleep", _fake_sleep)

        # retry_count=1 means only one attempt; no sleep should occur
        _run_ls_remote_impl(
            ["git", "ls-remote", "https://example.com/repo.git", "HEAD"],
            timeout=1,
            retry_count=1,
            retry_delay=1.0,
        )

        assert len(sleep_calls) == 0

    def test_multiple_timeouts_sleep_between_each(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With retry_count=3 and 3 timeouts, sleep is called exactly twice."""
        sleep_calls: list[float] = []

        def _fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(subprocess, "run", _fake_run)
        monkeypatch.setattr(doctor_mod.time, "sleep", _fake_sleep)

        _run_ls_remote_impl(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=1,
            retry_count=3,
            retry_delay=0.1,
        )

        # Between 3 attempts there should be 2 sleeps
        assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# Lines 219-223: _run_ls_remote function body (direct unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLsRemoteDirectly:
    """Direct unit tests for _run_ls_remote covering both ref-truthy and ref-falsy paths."""

    def test_with_ref_builds_cmd_with_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ref is non-empty, _run_ls_remote passes url and ref to _run_ls_remote_impl."""
        captured_cmds: list[list[str]] = []

        def _fake_impl(cmd, timeout, retry_count, retry_delay):
            captured_cmds.append(list(cmd))
            return (0, "sha\trefs/heads/main\n", "")

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "_run_ls_remote_impl", _fake_impl)

        url = "https://example.com/repo.git"
        ref = "refs/heads/main"
        _run_ls_remote(url, ref, timeout=30, retry_count=1, retry_delay=0.0)

        assert len(captured_cmds) == 1
        assert captured_cmds[0] == ["git", "ls-remote", url, ref]

    def test_with_empty_ref_builds_cmd_without_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ref is empty string, _run_ls_remote omits the ref arg from cmd."""
        captured_cmds: list[list[str]] = []

        def _fake_impl(cmd, timeout, retry_count, retry_delay):
            captured_cmds.append(list(cmd))
            return (0, "", "")

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "_run_ls_remote_impl", _fake_impl)

        url = "https://example.com/repo.git"
        _run_ls_remote(url, "", timeout=30, retry_count=1, retry_delay=0.0)

        assert len(captured_cmds) == 1
        assert captured_cmds[0] == ["git", "ls-remote", url]

    def test_returns_impl_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_run_ls_remote returns the result tuple from _run_ls_remote_impl."""

        def _fake_impl(cmd, timeout, retry_count, retry_delay):
            return (0, "stdout-content", "stderr-content")

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "_run_ls_remote_impl", _fake_impl)

        result = _run_ls_remote("https://x.com/r.git", "HEAD", 30, 1, 0.0)

        assert result == (0, "stdout-content", "stderr-content")

    def test_with_nonzero_return_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-zero exit code from _run_ls_remote_impl is returned unchanged."""

        def _fake_impl(cmd, timeout, retry_count, retry_delay):
            return (128, "", "not found")

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "_run_ls_remote_impl", _fake_impl)

        code, out, err = _run_ls_remote("https://x.com/r.git", "HEAD", 30, 1, 0.0)

        assert code == 128
        assert err == "not found"


# ---------------------------------------------------------------------------
# Line 454: _check_branch_drift continues on returncode != 0
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckBranchDriftNonZeroReturncode:
    """_check_branch_drift skips sources when _run_ls_remote returns non-zero."""

    def test_nonzero_returncode_produces_no_finding(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _run_ls_remote returns non-zero, no drift finding is produced."""
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(
            doctor_mod,
            "_run_ls_remote",
            lambda url, ref, timeout, retry_count, retry_delay: (1, "", "network error"),
        )

        findings = _check_branch_drift(lockfile, strict_drift=False)

        assert findings == []

    def test_nonzero_returncode_continues_to_next_source(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When first source returns non-zero, remaining branch-pinned sources are still checked."""
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "first",
                    "url": "https://example.com/first.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                },
                {
                    "name": "second",
                    "url": "https://example.com/second.git",
                    "revision_spec": "develop",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        import kanon_cli.commands.doctor as doctor_mod

        checked_urls: list[str] = []

        def _recording_stub(url, ref, timeout, retry_count, retry_delay):
            checked_urls.append(url)
            # First call fails; second returns a "no drift" result
            if url == "https://example.com/first.git":
                return (128, "", "error")
            # Return same SHA as locked to avoid a drift finding
            return (0, f"{'b' * 40}\trefs/heads/develop\n", "")

        monkeypatch.setattr(doctor_mod, "_run_ls_remote", _recording_stub)

        _check_branch_drift(lockfile, strict_drift=False)

        # Both URLs must have been queried
        assert "https://example.com/first.git" in checked_urls
        assert "https://example.com/second.git" in checked_urls

    def test_zero_returncode_with_drift_produces_finding(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ls-remote returns 0 and SHA differs, a drift finding is produced."""
        locked_sha = "a" * 40
        remote_sha = "b" * 40
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "src",
                    "url": "https://example.com/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": locked_sha,
                }
            ],
        )

        import kanon_cli.commands.doctor as doctor_mod

        monkeypatch.setattr(
            doctor_mod,
            "_run_ls_remote",
            lambda url, ref, timeout, retry_count, retry_delay: (
                0,
                f"{remote_sha}\trefs/heads/main\n",
                "",
            ),
        )

        findings = _check_branch_drift(lockfile, strict_drift=False)

        assert len(findings) == 1
        assert findings[0].code == "BRANCH_DRIFT"


# ---------------------------------------------------------------------------
# Lines 1114-1116: doctor_command orphan-lock findings loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorCommandOrphanLockFindings:
    """doctor_command prints orphan-lock findings and sets has_errors on error-level findings."""

    def _write_kanon_with_source(self, kanon_file: pathlib.Path, source_name: str) -> None:
        """Write a .kanon file that declares the given source name.

        Args:
            kanon_file: Path to write the .kanon file.
            source_name: Name of the KANON_SOURCE to declare.
        """
        kanon_file.write_text(
            f"KANON_SOURCE_{source_name}_URL=https://example.com/repo.git\n"
            f"KANON_SOURCE_{source_name}_REVISION=main\n"
            f"KANON_SOURCE_{source_name}_PATH=repo-specs/meta.xml\n"
            "KANON_CATALOG_SOURCE=https://example.com/catalog.git@main\n",
            encoding="utf-8",
        )

    def _write_kanon_without_source(self, kanon_file: pathlib.Path) -> None:
        """Write a .kanon file that declares a source NOT matching the lockfile entry.

        The file must declare at least one source so parse_kanonenv does not raise,
        but the source name "real-src" will NOT match the lockfile's "orphan-src"
        entry, triggering an ORPHAN_LOCK finding.

        Args:
            kanon_file: Path to write the .kanon file.
        """
        kanon_file.write_text(
            "KANON_SOURCE_REALSRC_URL=https://example.com/real.git\n"
            "KANON_SOURCE_REALSRC_REVISION=main\n"
            "KANON_SOURCE_REALSRC_PATH=repo-specs/real.xml\n"
            "KANON_CATALOG_SOURCE=https://example.com/catalog.git@main\n",
            encoding="utf-8",
        )

    def test_orphan_lock_error_finding_causes_nonzero_exit(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An orphan-lock error finding causes doctor_command to return 1."""
        kanon_file = tmp_path / ".kanon"
        self._write_kanon_without_source(kanon_file)

        # Build a lockfile with a source that is NOT in .kanon
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "orphan-src",
                    "url": "https://example.com/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )
        write_lockfile(lockfile, lock_path)

        _stub_doctor_subchecks(monkeypatch)

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        assert result == 1

    def test_orphan_lock_error_finding_printed_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An orphan-lock error finding is printed to stderr by doctor_command."""
        kanon_file = tmp_path / ".kanon"
        self._write_kanon_without_source(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "orphan-src",
                    "url": "https://example.com/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )
        write_lockfile(lockfile, lock_path)

        _stub_doctor_subchecks(monkeypatch)

        args = _make_doctor_args(kanon_file=str(kanon_file))
        doctor_command(args)

        captured = capsys.readouterr()
        assert "ORPHAN_LOCK" in captured.err or "orphan" in captured.err.lower()

    def test_orphan_lock_no_findings_no_errors(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When orphan check produces no findings, has_errors remains False."""
        kanon_file = tmp_path / ".kanon"
        self._write_kanon_with_source(kanon_file, "MYSRC")

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(
            tmp_path,
            [
                {
                    "name": "MYSRC",
                    "url": "https://example.com/repo.git",
                    "revision_spec": "main",
                    "resolved_sha": "a" * 40,
                }
            ],
        )
        write_lockfile(lockfile, lock_path)

        _stub_doctor_subchecks(monkeypatch)

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        assert result == 0


# ---------------------------------------------------------------------------
# Lines 1121-1123: doctor_command branch-drift findings loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorCommandBranchDriftFindings:
    """doctor_command prints branch-drift findings and sets has_errors for strict-drift errors."""

    def test_strict_drift_error_finding_causes_nonzero_exit(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A strict-drift error finding causes doctor_command to return 1."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        drift_finding = DoctorFinding(
            kind="error", code="BRANCH_DRIFT", message="drift detected", remediation="run install"
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_branch_drift=lambda lockfile, strict_drift: [drift_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file), strict_drift=True)
        result = doctor_command(args)

        assert result == 1

    def test_info_drift_finding_does_not_cause_error_exit(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An info-level drift finding does not promote has_errors to True."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        info_finding = DoctorFinding(kind="info", code="BRANCH_DRIFT", message="info drift", remediation="run install")
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_branch_drift=lambda lockfile, strict_drift: [info_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        assert result == 0

    def test_branch_drift_finding_printed_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Branch-drift finding is printed to stderr via _print_finding."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        drift_finding = DoctorFinding(
            kind="info",
            code="BRANCH_DRIFT",
            message="branch is drifting",
            remediation="run install",
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_branch_drift=lambda lockfile, strict_drift: [drift_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        doctor_command(args)

        captured = capsys.readouterr()
        assert "BRANCH_DRIFT" in captured.err or "branch" in captured.err.lower()


# ---------------------------------------------------------------------------
# Lines 1128-1130: doctor_command dangling-SHA findings loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorCommandDanglingShaFindings:
    """doctor_command prints dangling-SHA findings and sets has_errors for error findings."""

    def test_dangling_sha_error_finding_causes_nonzero_exit(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A dangling-SHA error finding causes doctor_command to return 1."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        dangling_finding = DoctorFinding(
            kind="error",
            code="DANGLING_SHA",
            message="sha no longer reachable",
            remediation="run install --refresh-lock",
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_dangling_shas=lambda lockfile: [dangling_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        assert result == 1

    def test_dangling_sha_finding_printed_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dangling-SHA finding is printed to stderr by doctor_command."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        dangling_finding = DoctorFinding(
            kind="error",
            code="DANGLING_SHA",
            message="dangling sha detected",
            remediation="run install",
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_dangling_shas=lambda lockfile: [dangling_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        doctor_command(args)

        captured = capsys.readouterr()
        assert "DANGLING_SHA" in captured.err or "dangling" in captured.err.lower()


# ---------------------------------------------------------------------------
# Line 1139: doctor_command remote-reachability findings loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorCommandRemoteReachabilityFindings:
    """doctor_command prints remote-reachability findings (always warnings, never errors)."""

    def test_remote_warning_finding_does_not_cause_error_exit(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Remote-reachability warning findings never set has_errors; exit remains 0."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        remote_finding = DoctorFinding(
            kind="warn",
            code="REMOTE_UNREACHABLE",
            message="remote not reachable",
            remediation="check network",
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_remote_reachability=lambda lockfile, callable, policy: [remote_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        # Remote findings are always warnings -- they must not cause a non-zero exit
        assert result == 0

    def test_remote_finding_printed_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Remote-reachability finding is printed to stderr via _print_finding."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        remote_finding = DoctorFinding(
            kind="warn",
            code="REMOTE_UNREACHABLE",
            message="remote-not-reachable-test",
            remediation="check network",
        )
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_remote_reachability=lambda lockfile, callable, policy: [remote_finding],
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        doctor_command(args)

        captured = capsys.readouterr()
        assert "REMOTE_UNREACHABLE" in captured.err or "remote" in captured.err.lower()

    def test_multiple_remote_findings_all_printed(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Multiple remote-reachability findings are each printed to stderr."""
        kanon_file = tmp_path / ".kanon"
        _write_minimal_kanon(kanon_file)

        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile_with_sources(tmp_path, [])
        write_lockfile(lockfile, lock_path)

        findings = [
            DoctorFinding(
                kind="warn",
                code="REMOTE_UNREACHABLE",
                message="remote-alpha-unreachable",
                remediation="check network",
            ),
            DoctorFinding(
                kind="warn",
                code="REMOTE_UNREACHABLE",
                message="remote-beta-unreachable",
                remediation="check network",
            ),
        ]
        _stub_doctor_subchecks(
            monkeypatch,
            _check_orphan_locks=lambda kanon_file, lockfile: [],
            _check_remote_reachability=lambda lockfile, callable, policy: findings,
        )

        args = _make_doctor_args(kanon_file=str(kanon_file))
        result = doctor_command(args)

        captured = capsys.readouterr()
        assert "remote-alpha-unreachable" in captured.err
        assert "remote-beta-unreachable" in captured.err
        assert result == 0
