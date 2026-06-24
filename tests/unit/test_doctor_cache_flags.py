"""Unit tests for doctor.py cache-management flags (subchecks 8 and 10).

Covers:
- _refresh_completion_cache: removes all files under the completion-cache subdir,
  recreates the directory empty with mode 0700, returns count of files removed.
- _prune_cache: removes only files whose atime is older than the configured
  age threshold; leaves newer files; returns (count_pruned, total_bytes).
- _scan_stale_install_locks: finds .kanon-data/.kanon-install.lock files
  whose mtime exceeds KANON_DOCTOR_STALE_LOCK_AGE_HOURS.
- doctor_command wiring: --refresh-completion-cache alone, --prune-cache alone,
  both combined (refresh runs first then prune).

AC-TEST-001: parametrized unit tests for refresh-only, prune-only,
both-combined, and stale-install-lock advisory paths; each case sets
atime/mtime via os.utime to avoid time-based delays.
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import stat

import pytest

from kanon_cli.constants import KANON_DOCTOR_STALE_LOCK_AGE_HOURS, KANON_HOME_CACHE_DIR_MODE


def _make_namespace(**kwargs: object) -> argparse.Namespace:
    """Build a minimal Namespace for doctor_command tests.

    Args:
        **kwargs: Attributes to set on the namespace; defaults provide
            everything doctor_command reads.

    Returns:
        Namespace instance with all required attributes.
    """
    defaults: dict[str, object] = {
        "kanon_file": None,
        "lock_file": None,
        "strict_drift": False,
        "refresh_completion_cache": False,
        "prune_cache": False,
        "catalog_source": object(),
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _fixed_now(dt: datetime.datetime) -> object:
    """Return a callable that always returns the given datetime.

    Args:
        dt: The fixed datetime to return.

    Returns:
        A zero-argument callable returning dt.
    """

    def _now() -> datetime.datetime:
        return dt

    return _now


def _set_atime(path: pathlib.Path, dt: datetime.datetime) -> None:
    """Set the atime of path to dt, leaving mtime unchanged.

    Args:
        path: File whose atime is to be updated.
        dt: Desired access time.
    """
    mtime = path.stat().st_mtime
    atime_ts = dt.timestamp()
    os.utime(str(path), (atime_ts, mtime))


def _set_mtime(path: pathlib.Path, dt: datetime.datetime) -> None:
    """Set the mtime of path to dt, leaving atime unchanged.

    Args:
        path: File whose mtime is to be updated.
        dt: Desired modification time.
    """
    atime = path.stat().st_atime
    mtime_ts = dt.timestamp()
    os.utime(str(path), (atime, mtime_ts))


@pytest.mark.unit
class TestRefreshCompletionCacheHelper:
    """Tests for the _refresh_completion_cache(cache_dir) helper."""

    def test_refresh_removes_files_and_returns_count_zero(self, tmp_path: pathlib.Path) -> None:
        """Returns 0 when the completion-cache subdir is already empty.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"
        cache_dir.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        count = _refresh_completion_cache(cache_dir)

        assert count == 0
        assert cache_dir.is_dir()

    @pytest.mark.parametrize(
        "n_files",
        [1, 3, 5],
        ids=["one_file", "three_files", "five_files"],
    )
    def test_refresh_removes_n_files_returns_count(self, tmp_path: pathlib.Path, n_files: int) -> None:
        """Returns N when N files are present under the completion-cache subdir.

        Args:
            tmp_path: Pytest-provided temporary directory.
            n_files: Number of cache files to create before calling refresh.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"
        cache_dir.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        for i in range(n_files):
            (cache_dir / f"cache-{i}.json").write_text(f"data-{i}", encoding="utf-8")

        count = _refresh_completion_cache(cache_dir)

        assert count == n_files

        assert cache_dir.is_dir()
        remaining = list(cache_dir.iterdir())
        assert remaining == [], f"Expected empty dir after refresh; found {remaining}"

    def test_refresh_recreates_dir_with_mode_0700(self, tmp_path: pathlib.Path) -> None:
        """After refresh, the completion-cache subdir has mode 0700.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"
        cache_dir.mkdir(mode=0o755)

        _refresh_completion_cache(cache_dir)

        mode = stat.S_IMODE(cache_dir.stat().st_mode)
        assert mode == KANON_HOME_CACHE_DIR_MODE, f"Expected mode {oct(KANON_HOME_CACHE_DIR_MODE)}, got {oct(mode)}"

    def test_refresh_creates_dir_when_absent(self, tmp_path: pathlib.Path) -> None:
        """Creates the completion-cache dir when it does not exist, returning 0.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"
        assert not cache_dir.exists()

        count = _refresh_completion_cache(cache_dir)

        assert count == 0
        assert cache_dir.is_dir()
        mode = stat.S_IMODE(cache_dir.stat().st_mode)
        assert mode == KANON_HOME_CACHE_DIR_MODE

    def test_refresh_handles_subdirectory_with_files(self, tmp_path: pathlib.Path) -> None:
        """Handles a completion-cache dir that contains a subdirectory with files.

        Previously, the implementation used a non-recursive loop + rmdir which
        raised ``OSError: Directory not empty`` when a subdirectory existed.
        The fix uses shutil.rmtree so nested content is removed without error.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"
        cache_dir.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        subdir = cache_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested1.json").write_text("data1", encoding="utf-8")
        (subdir / "nested2.json").write_text("data2", encoding="utf-8")

        (cache_dir / "top.json").write_text("top", encoding="utf-8")

        count = _refresh_completion_cache(cache_dir)

        assert count == 3, f"Expected 3 files removed; got {count}"
        assert cache_dir.is_dir(), "cache_dir must be recreated after refresh"
        remaining = list(cache_dir.iterdir())
        assert remaining == [], f"Expected empty dir after refresh; found {remaining}"
        mode = stat.S_IMODE(cache_dir.stat().st_mode)
        assert mode == KANON_HOME_CACHE_DIR_MODE, (
            f"Expected mode {oct(KANON_HOME_CACHE_DIR_MODE)} after refresh; got {oct(mode)}"
        )


_NOW = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_THRESHOLD_DAYS = 30
_OLD_ATIME = _NOW - datetime.timedelta(days=_THRESHOLD_DAYS + 1)
_NEW_ATIME = _NOW - datetime.timedelta(days=_THRESHOLD_DAYS - 1)


@pytest.mark.unit
class TestPruneCacheHelper:
    """Tests for the _prune_cache(cache_dir, age_days, now) helper."""

    def test_prune_removes_only_old_files(self, tmp_path: pathlib.Path) -> None:
        """Only files with atime older than age_days are pruned.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        old_file = cache_dir / "old.json"
        new_file = cache_dir / "new.json"
        old_file.write_text("x" * 100, encoding="utf-8")
        new_file.write_text("y" * 50, encoding="utf-8")

        _set_atime(old_file, _OLD_ATIME)
        _set_atime(new_file, _NEW_ATIME)

        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == 1
        assert total_bytes == 100
        assert not old_file.exists()
        assert new_file.exists()

    def test_prune_returns_zero_when_no_old_files(self, tmp_path: pathlib.Path) -> None:
        """Returns (0, 0) when no files have expired atimes.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        new_file = cache_dir / "fresh.json"
        new_file.write_text("hello", encoding="utf-8")
        _set_atime(new_file, _NEW_ATIME)

        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == 0
        assert total_bytes == 0
        assert new_file.exists()

    def test_prune_returns_zero_when_cache_dir_absent(self, tmp_path: pathlib.Path) -> None:
        """Returns (0, 0) when the cache_dir does not exist.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "nonexistent"
        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == 0
        assert total_bytes == 0

    @pytest.mark.parametrize(
        "n_old,n_new,old_size,new_size",
        [
            (3, 2, 100, 50),
            (1, 4, 999, 1),
            (5, 0, 200, 0),
        ],
        ids=["three_old_two_new", "one_old_four_new", "all_old"],
    )
    def test_prune_counts_and_bytes_parametrized(
        self,
        tmp_path: pathlib.Path,
        n_old: int,
        n_new: int,
        old_size: int,
        new_size: int,
    ) -> None:
        """Parametrized: pruned count and byte sum match expected old-files-only set.

        Args:
            tmp_path: Pytest-provided temporary directory.
            n_old: Number of old files to create.
            n_new: Number of new files to create.
            old_size: Byte size of each old file.
            new_size: Byte size of each new file.
        """
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        for i in range(n_old):
            f = cache_dir / f"old-{i}.json"
            f.write_bytes(b"x" * old_size)
            _set_atime(f, _OLD_ATIME)

        for i in range(n_new):
            f = cache_dir / f"new-{i}.json"
            f.write_bytes(b"y" * new_size)
            _set_atime(f, _NEW_ATIME)

        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == n_old
        assert total_bytes == n_old * old_size
        assert len(list(cache_dir.iterdir())) == n_new


@pytest.mark.unit
class TestScanStaleInstallLocks:
    """Tests for the _scan_stale_install_locks helper."""

    def test_finds_stale_lock_beyond_age_threshold(self, tmp_path: pathlib.Path) -> None:
        """Yields the lock path when its mtime is older than age_hours.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        lock_dir = tmp_path / ".kanon-data"
        lock_dir.mkdir()
        lock_file = lock_dir / ".kanon-install.lock"
        lock_file.write_text("", encoding="utf-8")

        age_hours = 1
        stale_mtime = _NOW - datetime.timedelta(hours=age_hours + 1)
        _set_mtime(lock_file, stale_mtime)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=4, age_hours=age_hours, now=_fixed_now(_NOW)))

        assert len(stale) == 1
        assert stale[0] == lock_file

    def test_ignores_fresh_lock(self, tmp_path: pathlib.Path) -> None:
        """Does not yield the lock path when its mtime is within age_hours.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        lock_dir = tmp_path / ".kanon-data"
        lock_dir.mkdir()
        lock_file = lock_dir / ".kanon-install.lock"
        lock_file.write_text("", encoding="utf-8")

        age_hours = 1
        fresh_mtime = _NOW - datetime.timedelta(minutes=30)
        _set_mtime(lock_file, fresh_mtime)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=4, age_hours=age_hours, now=_fixed_now(_NOW)))

        assert stale == []

    def test_respects_max_depth(self, tmp_path: pathlib.Path) -> None:
        """Does not recurse beyond max_depth levels.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        deep_dir = tmp_path / "a" / "b" / "c" / ".kanon-data"
        deep_dir.mkdir(parents=True)
        lock_file = deep_dir / ".kanon-install.lock"
        lock_file.write_text("", encoding="utf-8")

        stale_mtime = _NOW - datetime.timedelta(hours=2)
        _set_mtime(lock_file, stale_mtime)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=2, age_hours=1, now=_fixed_now(_NOW)))

        assert stale == [], f"Expected no results at max_depth=2; got {stale}"

    def test_multiple_stale_locks_at_different_depths(self, tmp_path: pathlib.Path) -> None:
        """Finds multiple stale locks within the depth limit.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        stale_mtime = _NOW - datetime.timedelta(hours=2)

        lock1_dir = tmp_path / "project1" / ".kanon-data"
        lock1_dir.mkdir(parents=True)
        lock1 = lock1_dir / ".kanon-install.lock"
        lock1.write_text("", encoding="utf-8")
        _set_mtime(lock1, stale_mtime)

        lock2_dir = tmp_path / "project2" / ".kanon-data"
        lock2_dir.mkdir(parents=True)
        lock2 = lock2_dir / ".kanon-install.lock"
        lock2.write_text("", encoding="utf-8")
        _set_mtime(lock2, stale_mtime)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=4, age_hours=1, now=_fixed_now(_NOW)))

        assert len(stale) == 2
        assert lock1 in stale
        assert lock2 in stale


@pytest.mark.unit
class TestDoctorCommandCacheFlagWiring:
    """Tests that doctor_command honours --refresh-completion-cache and --prune-cache."""

    def _make_cache_dir(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a <KANON_HOME>/cache structure with a completion-cache subdir.

        Returns tmp_path/"cache", which equals cache_dir() when KANON_HOME is set
        to tmp_path (the caller sets KANON_HOME accordingly).

        Args:
            tmp_path: Pytest-provided temporary directory.

        Returns:
            The top-level cache directory path.
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)
        return cache_dir

    def _make_kanon_file(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a minimal .kanon file in tmp_path.

        Args:
            tmp_path: Pytest-provided temporary directory.

        Returns:
            Path to the created .kanon file.
        """
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")
        return kanon_file

    def test_refresh_flag_alone_clears_completion_cache(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--refresh-completion-cache alone: empties the completion subdir.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        cache_dir = self._make_cache_dir(tmp_path)
        completion_cache = cache_dir / "completion-cache"

        (completion_cache / "a.json").write_text("aa", encoding="utf-8")
        (completion_cache / "b.json").write_text("bb", encoding="utf-8")

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        doctor_command(args)

        assert list(completion_cache.iterdir()) == [], "Completion cache must be empty after --refresh-completion-cache"

    def test_refresh_flag_emits_info_finding(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--refresh-completion-cache emits one info finding naming count removed.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        cache_dir = self._make_cache_dir(tmp_path)
        completion_cache = cache_dir / "completion-cache"

        (completion_cache / "c.json").write_text("data", encoding="utf-8")

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        doctor_command(args)

        captured = capsys.readouterr()
        assert "INFO:" in captured.err, f"Expected INFO finding in stderr; got {captured.err!r}"
        assert "Completion cache refreshed: 1" in captured.err, (
            f"Expected 'Completion cache refreshed: 1' in stderr; got {captured.err!r}"
        )

    def test_no_flags_does_not_mutate_cache_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """doctor_command without either flag does NOT mutate the cache directory.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        cache_dir = self._make_cache_dir(tmp_path)
        completion_cache = cache_dir / "completion-cache"

        sentinel = completion_cache / "sentinel.json"
        sentinel.write_text("keep-me", encoding="utf-8")

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            refresh_completion_cache=False,
            prune_cache=False,
        )
        doctor_command(args)

        assert sentinel.exists(), "sentinel.json must not be deleted when no cache flags are set"

    def test_prune_flag_alone_removes_old_files(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--prune-cache alone: removes old cache files, keeps new ones.

        Uses a fixed 'now' injected via monkeypatching so atime comparisons
        are reproducible regardless of the wall clock.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        cache_dir = self._make_cache_dir(tmp_path)

        old_file = cache_dir / "old.json"
        new_file = cache_dir / "new.json"
        old_file.write_bytes(b"x" * 200)
        new_file.write_bytes(b"y" * 100)

        _set_atime(old_file, _OLD_ATIME)
        _set_atime(new_file, _NEW_ATIME)

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            prune_cache=True,
        )
        doctor_command(args, now=_fixed_now(_NOW))

        assert not old_file.exists(), "Old cache file must be pruned"
        assert new_file.exists(), "New cache file must be kept"

        captured = capsys.readouterr()
        assert "Cache pruned: 1" in captured.err, f"Expected 'Cache pruned: 1' in stderr; got {captured.err!r}"

    def test_both_flags_refresh_runs_before_prune(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both flags: refresh empties the completion subdir, then prune removes old files.

        When --refresh-completion-cache runs before --prune-cache, files that were
        in the completion-cache subdir before the refresh are removed by the refresh
        step (not the prune step). The prune step then operates on remaining files.

        Uses a fixed 'now' so atime comparisons are reproducible.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        cache_dir = self._make_cache_dir(tmp_path)
        completion_cache = cache_dir / "completion-cache"

        completion_old = completion_cache / "comp_old.json"
        completion_old.write_bytes(b"z" * 50)
        _set_atime(completion_old, _OLD_ATIME)

        top_old = cache_dir / "top_old.json"
        top_old.write_bytes(b"w" * 30)
        _set_atime(top_old, _OLD_ATIME)

        top_new = cache_dir / "top_new.json"
        top_new.write_bytes(b"v" * 20)
        _set_atime(top_new, _NEW_ATIME)

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
            prune_cache=True,
        )
        doctor_command(args, now=_fixed_now(_NOW))

        assert list(completion_cache.iterdir()) == []

        assert not top_old.exists()

        assert top_new.exists()

    def test_prune_flag_emits_stale_lock_advisory(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--prune-cache emits an advisory finding for stale .kanon-install.lock files.

        The advisory does NOT delete the lock file.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = self._make_kanon_file(tmp_path)
        self._make_cache_dir(tmp_path)

        lock_dir = tmp_path / "sub" / ".kanon-data"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / ".kanon-install.lock"
        lock_file.write_text("", encoding="utf-8")
        stale_mtime = _NOW - datetime.timedelta(hours=KANON_DOCTOR_STALE_LOCK_AGE_HOURS + 1)
        _set_mtime(lock_file, stale_mtime)

        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        args = _make_namespace(
            kanon_file=str(kanon_file),
            prune_cache=True,
        )

        doctor_command(args, now=_fixed_now(_NOW))

        assert lock_file.exists(), "doctor must NOT delete the stale lock file (advisory only)"

        captured = capsys.readouterr()
        assert "Advisory: stale install lock found" in captured.err, (
            f"Expected stale-lock advisory in stderr; got {captured.err!r}"
        )


@pytest.mark.unit
class TestPruneCacheOSErrorHandling:
    """_prune_cache emits a WARN and skips files whose stat() raises OSError."""

    def test_prune_skips_unreadable_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A file that raises OSError from stat() is skipped with a WARN to stderr.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        bad_file = cache_dir / "unreadable.json"
        bad_file.write_text("x", encoding="utf-8")
        good_file = cache_dir / "good.json"
        good_file.write_bytes(b"y" * 50)
        _set_atime(good_file, _OLD_ATIME)

        original_stat = pathlib.Path.stat

        def _bad_stat(self: pathlib.Path, **kwargs: object) -> object:
            if "unreadable" in self.name:
                raise OSError(13, "Permission denied")
            return original_stat(self, **kwargs)

        monkeypatch.setattr(pathlib.Path, "stat", _bad_stat)

        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == 1
        assert total_bytes == 50

        captured = capsys.readouterr()
        assert "WARN:" in captured.err, f"Expected WARN in stderr for unreadable file; got {captured.err!r}"
        assert "unreadable" in captured.err, f"Expected file name in WARN; got {captured.err!r}"

    def test_prune_skips_undeletable_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A file that raises OSError from unlink() is skipped with a WARN."""
        from kanon_cli.commands.doctor import _prune_cache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        bad_file = cache_dir / "locked.json"
        bad_file.write_bytes(b"z" * 30)
        _set_atime(bad_file, _OLD_ATIME)

        good_file = cache_dir / "good.json"
        good_file.write_bytes(b"y" * 50)
        _set_atime(good_file, _OLD_ATIME)

        original_unlink = pathlib.Path.unlink

        def _bad_unlink(self: pathlib.Path, **kwargs: object) -> None:
            if "locked" in self.name:
                raise OSError(13, "Permission denied")
            original_unlink(self, **kwargs)

        monkeypatch.setattr(pathlib.Path, "unlink", _bad_unlink)

        count, total_bytes = _prune_cache(cache_dir, _THRESHOLD_DAYS, _fixed_now(_NOW))

        assert count == 1
        assert total_bytes == 50

        captured = capsys.readouterr()
        assert "WARN:" in captured.err
        assert "locked" in captured.err


@pytest.mark.unit
class TestScanStaleInstallLocksOSErrorHandling:
    """_scan_stale_install_locks emits WARN and skips on OSError from stat or iterdir."""

    def test_skips_lock_when_stat_raises(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A lock whose stat() raises OSError is skipped with a WARN to stderr.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        lock_dir = tmp_path / ".kanon-data"
        lock_dir.mkdir()
        lock_file = lock_dir / ".kanon-install.lock"
        lock_file.write_text("", encoding="utf-8")

        original_stat = pathlib.Path.stat

        def _bad_stat(self: pathlib.Path, **kwargs: object) -> object:
            if ".kanon-install.lock" in str(self):
                raise OSError(13, "Permission denied")
            return original_stat(self, **kwargs)

        monkeypatch.setattr(pathlib.Path, "stat", _bad_stat)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=4, age_hours=1, now=_fixed_now(_NOW)))

        assert stale == [], "Lock with unreadable stat must not be yielded"
        captured = capsys.readouterr()
        assert "WARN:" in captured.err, f"Expected WARN in stderr for unreadable lock stat; got {captured.err!r}"

    def test_skips_dir_when_iterdir_raises(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A directory that raises OSError from iterdir() is skipped with a WARN to stderr.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import _scan_stale_install_locks

        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()

        original_iterdir = pathlib.Path.iterdir

        def _bad_iterdir(self: pathlib.Path) -> object:
            if "sub" in str(self) and self != tmp_path:
                raise OSError(13, "Permission denied")
            return original_iterdir(self)

        monkeypatch.setattr(pathlib.Path, "iterdir", _bad_iterdir)

        stale = list(_scan_stale_install_locks(tmp_path, max_depth=4, age_hours=1, now=_fixed_now(_NOW)))

        assert stale == []
        captured = capsys.readouterr()
        assert "WARN:" in captured.err, f"Expected WARN in stderr for unreadable iterdir; got {captured.err!r}"


@pytest.mark.unit
class TestDoctorCommandDefaultNow:
    """doctor_command uses datetime.datetime.now() when now is not supplied."""

    def test_now_none_uses_wall_clock(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Calling doctor_command without now= covers the default-now branch.

        The function must not raise when now=None (the default); it falls back
        to datetime.datetime.now(tz=datetime.timezone.utc) internally.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest capture fixture for stderr assertions.
        """
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_namespace(
            kanon_file=str(kanon_file),
            prune_cache=True,
            refresh_completion_cache=False,
        )

        result = doctor_command(args)

        assert result == 0, f"doctor_command must return 0 (no errors); got {result!r}"
        captured = capsys.readouterr()
        assert "ERROR:" not in captured.err, f"Unexpected ERROR in stderr; got {captured.err!r}"


@pytest.mark.unit
class TestDoctorRegisterCacheFlags:
    """register() adds --prune-cache to the 'doctor' subparser."""

    def test_prune_cache_flag_exists(self) -> None:
        """The 'doctor' subcommand accepts --prune-cache."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor", "--prune-cache"])
        assert args.prune_cache is True

    def test_prune_cache_default_false(self) -> None:
        """--prune-cache defaults to False when not supplied."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor"])
        assert args.prune_cache is False

    def test_both_cache_flags_accepted_together(self) -> None:
        """Both --refresh-completion-cache and --prune-cache are accepted together."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor", "--refresh-completion-cache", "--prune-cache"])
        assert args.refresh_completion_cache is True
        assert args.prune_cache is True


@pytest.mark.unit
class TestDoctorCommandRefreshOSError:
    """doctor_command returns 1 and prints ERROR: to stderr when _refresh_completion_cache raises OSError."""

    def test_refresh_oserror_returns_1_and_prints_error(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """doctor_command returns 1 and prints ERROR: to stderr when _refresh_completion_cache raises OSError.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        import kanon_cli.commands.doctor as doctor_mod
        from kanon_cli.commands.doctor import doctor_command

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_HOME_CACHE_DIR_MODE)

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def _raise_oserror(path: pathlib.Path) -> int:
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(doctor_mod, "_refresh_completion_cache", _raise_oserror)

        args = _make_namespace(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        result = doctor_command(args)

        assert result == 1, f"Expected return code 1 when OSError is raised; got {result!r}"
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err, f"Expected 'ERROR:' in stderr; got {captured.err!r}"
