"""Integration tests for 'kanon doctor' consistency subchecks 1-5.

Drives the full CLI via subprocess against real fixture git repos.
Covers:
- Absent .kanon: exit non-zero with ERROR shape message
- Absent .kanon.lock: exit 0 with info-level notice
- Hash mismatch: exit non-zero with ERROR: kanon_hash mismatch
- Orphan lock entry: exit non-zero with ERROR: orphan lock entry
- Branch drift (without --strict-drift): exit 0 with info-level notice
- Branch drift (with --strict-drift): exit non-zero with error
- Dangling SHA: exit non-zero with ERROR: dangling SHA

AC-TEST-002, AC-CYCLE-001
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import pytest

from tests.conftest import (
    write_kanon_doctor_integration as _write_kanon,
    write_lockfile_doctor_integration as _write_lockfile,
    write_lockfile_doctor_integration_multi_source as _write_lockfile_two_sources,
)


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _git_output(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command in cwd and return stdout, raising RuntimeError on failure."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")
    return result.stdout.strip()


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_repo_with_two_commits(
    base: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, str, str]:
    """Create a bare repo with two commits on main.

    Returns (bare_path, sha_a, sha_b) where sha_a is the older commit
    and sha_b is HEAD.

    Args:
        base: Parent directory for work and bare repos.
        name: Used for directory naming.

    Returns:
        Tuple of (bare_path, sha_a, sha_b).
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text(f"# {name} initial\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    sha_a = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    (work_dir / "README.md").write_text(f"# {name} second\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Second commit"], cwd=work_dir)
    sha_b = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{name}-bare.git")
    return bare_dir.resolve(), sha_a, sha_b


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the same Python interpreter."""
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


@pytest.mark.integration
class TestDoctorAbsentKanonFile:
    """kanon doctor exits non-zero with ERROR message when .kanon is absent (AC-FUNC-001)."""

    def test_no_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits non-zero when .kanon file is absent."""
        result = _run_kanon(["doctor", "--kanon-file", str(tmp_path / ".kanon")], cwd=tmp_path)

        assert result.returncode != 0

    def test_no_kanon_file_stderr_contains_error_shape(self, tmp_path: pathlib.Path) -> None:
        """doctor prints ERROR-shape message to stderr when .kanon is absent."""
        result = _run_kanon(["doctor", "--kanon-file", str(tmp_path / ".kanon")], cwd=tmp_path)

        assert "ERROR:" in result.stderr

    def test_no_kanon_file_stderr_mentions_not_found(self, tmp_path: pathlib.Path) -> None:
        """doctor stderr mentions '.kanon' not found when .kanon is absent."""
        result = _run_kanon(["doctor", "--kanon-file", str(tmp_path / ".kanon")], cwd=tmp_path)

        assert "not found" in result.stderr or "no kanon workspace" in result.stderr


@pytest.mark.integration
class TestDoctorAbsentLockfile:
    """kanon doctor exits 0 with info notice when .kanon exists but .kanon.lock is absent (AC-FUNC-002)."""

    def test_no_lockfile_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits 0 when .kanon.lock is absent."""
        kanon_file = _write_kanon(tmp_path, "src", "https://example.com/org/repo.git")

        result = _run_kanon(["doctor", "--kanon-file", str(kanon_file)], cwd=tmp_path)

        assert result.returncode == 0

    def test_no_lockfile_stderr_contains_info_notice(self, tmp_path: pathlib.Path) -> None:
        """doctor prints info-level notice to stderr when lockfile absent."""
        kanon_file = _write_kanon(tmp_path, "src", "https://example.com/org/repo.git")

        result = _run_kanon(["doctor", "--kanon-file", str(kanon_file)], cwd=tmp_path)

        assert "No lockfile present" in result.stderr


@pytest.mark.integration
class TestDoctorHashMismatch:
    """kanon doctor exits non-zero with ERROR: kanon_hash mismatch when hash is wrong (AC-FUNC-003)."""

    def test_hash_mismatch_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits non-zero when kanon_hash in lockfile is wrong."""
        url = "https://example.com/org/repo.git"
        kanon_file = _write_kanon(tmp_path, "src", url)

        _write_lockfile(
            tmp_path,
            kanon_hash_val="sha256:" + "b" * 64,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha="a" * 40,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert result.returncode != 0

    def test_hash_mismatch_stderr_contains_error_message(self, tmp_path: pathlib.Path) -> None:
        """doctor stderr contains ERROR: kanon_hash mismatch when hash is wrong."""
        url = "https://example.com/org/repo.git"
        kanon_file = _write_kanon(tmp_path, "src", url)
        _write_lockfile(
            tmp_path,
            kanon_hash_val="sha256:" + "b" * 64,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha="a" * 40,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert "kanon_hash mismatch" in result.stderr

    def test_hash_mismatch_stderr_mentions_refresh_lock(self, tmp_path: pathlib.Path) -> None:
        """doctor stderr mentions kanon install --refresh-lock as remediation."""
        url = "https://example.com/org/repo.git"
        kanon_file = _write_kanon(tmp_path, "src", url)
        _write_lockfile(
            tmp_path,
            kanon_hash_val="sha256:" + "b" * 64,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha="a" * 40,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert "--refresh-lock" in result.stderr


@pytest.mark.integration
class TestDoctorOrphanLock:
    """kanon doctor exits non-zero with ERROR: orphan lock entry when source is orphaned (AC-FUNC-004)."""

    def test_orphan_lock_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits non-zero when lockfile has a source not in .kanon."""
        url = "https://example.com/org/repo.git"
        kanon_file = _write_kanon(tmp_path, "src", url)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)

        _write_lockfile_two_sources(
            tmp_path,
            kanon_hash_val=real_hash,
            sources=[
                {"name": "src", "url": url, "revision_spec": "main", "resolved_sha": "a" * 40},
                {
                    "name": "ghost",
                    "url": "https://example.com/other.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert result.returncode != 0

    def test_orphan_lock_stderr_contains_error_message(self, tmp_path: pathlib.Path) -> None:
        """doctor stderr contains ERROR: orphan lock entry."""
        url = "https://example.com/org/repo.git"
        kanon_file = _write_kanon(tmp_path, "src", url)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile_two_sources(
            tmp_path,
            kanon_hash_val=real_hash,
            sources=[
                {"name": "src", "url": url, "revision_spec": "main", "resolved_sha": "a" * 40},
                {
                    "name": "ghost",
                    "url": "https://example.com/other.git",
                    "revision_spec": "main",
                    "resolved_sha": "b" * 40,
                },
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert "orphan lock entry" in result.stderr
        assert "ghost" in result.stderr


@pytest.mark.integration
class TestDoctorBranchDrift:
    """kanon doctor handles branch drift correctly (AC-FUNC-005)."""

    def test_drift_without_strict_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits 0 (info-level) when branch has drifted but --strict-drift is not set."""
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"

        kanon_file = _write_kanon(tmp_path, "src", url, revision="main")
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)

        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha=sha_a,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert result.returncode == 0

    def test_drift_without_strict_stderr_contains_drift_notice(self, tmp_path: pathlib.Path) -> None:
        """doctor prints drift notice to stderr when branch has drifted (no --strict-drift)."""
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"

        kanon_file = _write_kanon(tmp_path, "src", url, revision="main")
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha=sha_a,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert "drift" in result.stderr.lower() or "BRANCH_DRIFT" in result.stderr

    def test_drift_with_strict_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits non-zero when branch has drifted and --strict-drift is set."""
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"

        kanon_file = _write_kanon(tmp_path, "src", url, revision="main")
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec="main",
            resolved_sha=sha_a,
        )

        result = _run_kanon(
            [
                "doctor",
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(tmp_path / ".kanon.lock"),
                "--strict-drift",
            ],
            cwd=tmp_path,
        )

        assert result.returncode != 0


@pytest.mark.integration
class TestDoctorDanglingSha:
    """kanon doctor exits non-zero with ERROR: dangling SHA when SHA is unreachable (AC-FUNC-006)."""

    def test_reachable_sha_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits 0 when a SHA-pinned source's locked SHA is still reachable.

        Uses a SHA-pinned source (revision_spec is the commit SHA) so that the
        dangling SHA check runs (branch-pinned sources skip it). The SHA is
        sha_b, the current HEAD -- it is still reachable via ls-remote.
        """
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"

        kanon_file = _write_kanon(tmp_path, "src", url, revision=sha_b)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec=sha_b,
            resolved_sha=sha_b,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert result.returncode == 0

    def test_dangling_sha_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """doctor exits non-zero when a SHA-pinned source's SHA is not reachable.

        Uses a SHA-pinned source (revision_spec is a 40-char hex SHA) because
        the dangling SHA check skips branch-pinned sources (those are covered
        by the branch drift check instead).
        """
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"

        fake_sha = "d" * 40

        kanon_file = _write_kanon(tmp_path, "src", url, revision=fake_sha)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec=fake_sha,
            resolved_sha=fake_sha,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert result.returncode != 0

    def test_dangling_sha_stderr_contains_error_message(self, tmp_path: pathlib.Path) -> None:
        """doctor stderr contains ERROR: dangling SHA when SHA-pinned source's SHA is unreachable."""
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "proj")
        url = f"file://{bare_path}"
        fake_sha = "d" * 40

        kanon_file = _write_kanon(tmp_path, "src", url, revision=fake_sha)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec=fake_sha,
            resolved_sha=fake_sha,
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(tmp_path / ".kanon.lock")],
            cwd=tmp_path,
        )

        assert "dangling SHA" in result.stderr or "dangling" in result.stderr.lower()
        assert fake_sha in result.stderr


@pytest.mark.integration
class TestDoctorCycle:
    """AC-CYCLE-001: End-to-end tamper cycle."""

    def test_tampered_hash_detected_and_remediated(self, tmp_path: pathlib.Path) -> None:
        """Tamper with lockfile kanon_hash; doctor detects it; rebuild fixes it.

        Steps:
        1. Create a real local bare repo with two commits (so SHA-pinned sources
           are reachable and the dangling-SHA subcheck does not fire after
           remediation).
        2. Write .kanon pointing to the bare repo with a SHA-pinned source
           (revision and resolved_sha both set to sha_b, the current HEAD).
        3. Write a valid lockfile (correct kanon_hash, reachable SHA).
        4. Tamper the lockfile by overwriting kanon_hash with a bad value.
        5. Run doctor -- assert exit code 1 and 'kanon_hash mismatch' in stderr.
        6. Restore the lockfile with the correct kanon_hash and the real SHA.
        7. Re-run doctor -- assert exit code 0 (all subchecks pass).
        """
        bare_path, sha_a, sha_b = _create_bare_repo_with_two_commits(tmp_path, "cycle")
        url = f"file://{bare_path}"

        kanon_file = _write_kanon(tmp_path, "src", url, revision=sha_b)
        from kanon_cli.core.kanon_hash import kanon_hash

        real_hash = kanon_hash(kanon_file)
        lock_path = tmp_path / ".kanon.lock"

        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec=sha_b,
            resolved_sha=sha_b,
        )

        content = lock_path.read_text(encoding="utf-8")
        tampered = content.replace(f'kanon_hash = "{real_hash}"', 'kanon_hash = "sha256:' + "c" * 64 + '"')
        lock_path.write_text(tampered, encoding="utf-8")

        result1 = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(lock_path)],
            cwd=tmp_path,
        )
        assert result1.returncode != 0, f"Expected non-zero exit. stderr: {result1.stderr!r}"
        assert "kanon_hash mismatch" in result1.stderr

        _write_lockfile(
            tmp_path,
            kanon_hash_val=real_hash,
            source_name="src",
            url=url,
            revision_spec=sha_b,
            resolved_sha=sha_b,
        )

        result2 = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_file), "--lock-file", str(lock_path)],
            cwd=tmp_path,
        )
        assert result2.returncode == 0, (
            "After restoring the lockfile with the correct hash and a reachable SHA, "
            f"kanon doctor must exit 0. stderr: {result2.stderr!r}"
        )
