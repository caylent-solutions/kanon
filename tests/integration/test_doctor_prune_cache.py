"""Integration tests for 'kanon doctor --prune-cache'.

Drives the full CLI via subprocess under a controlled tmp_path workspace
with KANON_HOME set (the cache resolves under <KANON_HOME>/cache). Creates
mixed-age cache files (old atime set via
os.utime), runs 'kanon doctor --prune-cache', and asserts:
- Exit code 0.
- stdout or stderr names the pruned count.
- Only files older than KANON_CACHE_PRUNE_AGE_DAYS are removed.

AC-TEST-002, AC-CYCLE-001: end-to-end cycle with five completion-cache
files (three older than 30 days, two newer), assert pruned=3 / kept=2.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.constants import KANON_HOME_CACHE_DIR_MODE


def _set_atime(path: pathlib.Path, dt: datetime.datetime) -> None:
    """Set the atime of path to dt, leaving mtime unchanged.

    Args:
        path: File whose atime is to be updated.
        dt: Desired access time.
    """
    mtime = path.stat().st_mtime
    atime_ts = dt.timestamp()
    os.utime(str(path), (atime_ts, mtime))


def _run_kanon(args: list[str], env: dict[str, str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run 'kanon <args>' as a subprocess and return the result.

    Args:
        args: Arguments to pass after 'kanon'.
        env: Environment for the subprocess.
        cwd: Working directory for the subprocess.

    Returns:
        CompletedProcess instance with returncode, stdout, stderr.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


def _base_env(cache_dir: pathlib.Path, kanon_file: pathlib.Path) -> dict[str, str]:
    """Build the environment dict for a CLI subprocess.

    The cache resolves under <KANON_HOME>/cache, so KANON_HOME is set to the
    parent of *cache_dir* (which is ``tmp_path / "cache"``) so that the
    subprocess-resolved cache equals *cache_dir*.

    Args:
        cache_dir: The cache directory the subprocess must resolve to; its
            parent is set as KANON_HOME.
        kanon_file: Path to set as KANON_KANON_FILE.

    Returns:
        Environment dict with PATH, KANON_HOME, KANON_KANON_FILE set.
    """
    env = {k: v for k, v in os.environ.items()}
    env["KANON_HOME"] = str(cache_dir.parent)
    env["KANON_KANON_FILE"] = str(kanon_file)
    return env


_NOW = datetime.datetime.now(tz=datetime.timezone.utc)
_OLD_DAYS = 31
_NEW_DAYS = 10


@pytest.mark.integration
class TestDoctorPruneCacheIntegration:
    """End-to-end tests for 'kanon doctor --prune-cache'."""

    def _create_workspace(
        self,
        tmp_path: pathlib.Path,
        n_old: int,
        n_new: int,
        file_size: int = 100,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Create a workspace with a .kanon file and cache files of mixed age.

        Args:
            tmp_path: Pytest-provided temporary directory.
            n_old: Number of old (expired) cache files to create.
            n_new: Number of new (unexpired) cache files to create.
            file_size: Byte size of each cache file.

        Returns:
            Tuple of (cache_dir, kanon_file) paths.
        """
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        old_dt = _NOW - datetime.timedelta(days=_OLD_DAYS)
        new_dt = _NOW - datetime.timedelta(days=_NEW_DAYS)

        for i in range(n_old):
            f = cache_dir / f"old-{i}.bin"
            f.write_bytes(b"o" * file_size)
            _set_atime(f, old_dt)

        for i in range(n_new):
            f = cache_dir / f"new-{i}.bin"
            f.write_bytes(b"n" * file_size)
            _set_atime(f, new_dt)

        return cache_dir, kanon_file

    def test_prune_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon doctor --prune-cache' exits 0.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        cache_dir, kanon_file = self._create_workspace(tmp_path, n_old=2, n_new=1)
        env = _base_env(cache_dir, kanon_file)

        result = _run_kanon(["doctor", "--prune-cache"], env, tmp_path)

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_prune_removes_old_files_keeps_new(self, tmp_path: pathlib.Path) -> None:
        """Only files with atime older than threshold are deleted.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        cache_dir, kanon_file = self._create_workspace(tmp_path, n_old=3, n_new=2)
        env = _base_env(cache_dir, kanon_file)

        _run_kanon(["doctor", "--prune-cache"], env, tmp_path)

        remaining = list(cache_dir.iterdir())
        remaining_names = [f.name for f in remaining]

        old_files = [n for n in remaining_names if n.startswith("old-")]
        new_files = [n for n in remaining_names if n.startswith("new-")]

        assert old_files == [], f"Old files must be pruned; remaining: {old_files}"
        assert len(new_files) == 2, f"Both new files must remain; found: {new_files}"

    def test_prune_reports_count_in_output(self, tmp_path: pathlib.Path) -> None:
        """Output contains the pruned file count.

        AC-CYCLE-001: create 5 files (3 old, 2 new), assert stdout/stderr
        names pruned=3.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        cache_dir, kanon_file = self._create_workspace(tmp_path, n_old=3, n_new=2)
        env = _base_env(cache_dir, kanon_file)

        result = _run_kanon(["doctor", "--prune-cache"], env, tmp_path)

        combined_output = result.stdout + result.stderr
        assert "Cache pruned: 3" in combined_output, (
            f"Expected 'Cache pruned: 3' in output.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_prune_no_files_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon doctor --prune-cache' exits 0 when no files are pruned.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        cache_dir, kanon_file = self._create_workspace(tmp_path, n_old=0, n_new=3)
        env = _base_env(cache_dir, kanon_file)

        result = _run_kanon(["doctor", "--prune-cache"], env, tmp_path)

        assert result.returncode == 0

    @pytest.mark.parametrize(
        "n_old,n_new",
        [
            (1, 4),
            (5, 0),
            (2, 3),
        ],
        ids=["one_old", "all_old", "two_old"],
    )
    def test_prune_parametrized_counts(self, tmp_path: pathlib.Path, n_old: int, n_new: int) -> None:
        """Parametrized: correct number of files remain after prune.

        Args:
            tmp_path: Pytest-provided temporary directory.
            n_old: Number of old files to create.
            n_new: Number of new files to keep.
        """
        cache_dir, kanon_file = self._create_workspace(tmp_path, n_old=n_old, n_new=n_new)
        env = _base_env(cache_dir, kanon_file)

        result = _run_kanon(["doctor", "--prune-cache"], env, tmp_path)

        assert result.returncode == 0

        remaining = list(cache_dir.iterdir())
        assert len(remaining) == n_new, (
            f"Expected {n_new} files after prune; got {len(remaining)}: {[f.name for f in remaining]}"
        )

    def test_refresh_and_prune_combined(self, tmp_path: pathlib.Path) -> None:
        """--refresh-completion-cache and --prune-cache can be combined.

        Completion-cache subdir is emptied by refresh; remaining old files are
        pruned; new files survive.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        old_dt = _NOW - datetime.timedelta(days=_OLD_DAYS)
        new_dt = _NOW - datetime.timedelta(days=_NEW_DAYS)

        comp_file = completion_cache / "comp.json"
        comp_file.write_bytes(b"c" * 50)
        _set_atime(comp_file, old_dt)

        old_top = cache_dir / "old.json"
        old_top.write_bytes(b"o" * 100)
        _set_atime(old_top, old_dt)

        new_top = cache_dir / "new.json"
        new_top.write_bytes(b"n" * 100)
        _set_atime(new_top, new_dt)

        env = _base_env(cache_dir, kanon_file)
        result = _run_kanon(["doctor", "--refresh-completion-cache", "--prune-cache"], env, tmp_path)

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert list(completion_cache.iterdir()) == [], "Completion cache must be emptied by refresh"
        assert not old_top.exists(), "Old top-level file must be pruned"
        assert new_top.exists(), "New top-level file must survive"
