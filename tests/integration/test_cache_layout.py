"""Integration tests for kanon_cli.completions.cache -- AC-TEST-002, AC-CYCLE-001.

These tests operate on a real filesystem temp directory and verify
on-disk file/dir modes via os.stat, fulfilling the integration-test
requirement for the cache layout implementation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from kanon_cli.completions.cache import (
    cache_dir,
    catalog_entry_dir,
    log_completion_error,
    project_entry_dir,
    read_entries,
    write_entries,
    write_epoch,
    read_epoch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KANON_CACHE_DIR at a real tmp dir and return it."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("KANON_COMPLETION_LOG", raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# AC-CYCLE-001: end-to-end cycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCacheCycleEndToEnd:
    def test_write_entries_file_and_dir_modes(self, real_cache: Path) -> None:
        """AC-CYCLE-001: write_entries creates 0700 dir and 0600 file."""
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, ["foo", "bar"])

        # File content
        content = target.read_text()
        assert content == "foo\nbar\n"

        # File mode 0600
        assert os.stat(target).st_mode & 0o777 == 0o600

        # Parent dir mode 0700
        assert os.stat(target.parent).st_mode & 0o777 == 0o700

    def test_log_completion_error_format_and_mode(self, real_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-CYCLE-001: log_completion_error appends a well-formed line."""
        log_path = real_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("__complete_test", ValueError("x"))

        assert log_path.exists()
        lines = [ln for ln in log_path.read_text().splitlines() if ln]
        assert len(lines) == 1
        line = lines[0]

        pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z "
            r"__complete_test ValueError: x$"
        )
        assert pattern.match(line), f"Bad line format: {line!r}"

        # File mode 0600
        assert os.stat(log_path).st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# On-disk mode checks via os.stat
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOnDiskModes:
    def test_catalog_entry_dir_mode_0700(self, real_cache: Path) -> None:
        d = catalog_entry_dir("https://modes-test.git", "v1")
        write_entries(d / "index.txt", ["entry"])
        assert os.stat(d).st_mode & 0o777 == 0o700

    def test_project_entry_dir_mode_0700(self, real_cache: Path) -> None:
        d = project_entry_dir("https://modes-project.git")
        write_entries(d / "tags.txt", ["1.0.0"])
        assert os.stat(d).st_mode & 0o777 == 0o700

    def test_index_txt_mode_0600(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://modes-file.git", "main") / "index.txt"
        write_entries(target, ["a", "b"])
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_tags_txt_mode_0600(self, real_cache: Path) -> None:
        target = project_entry_dir("https://modes-tags.git") / "tags.txt"
        write_entries(target, ["1.0.0", "2.0.0"])
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_fetched_at_mode_0600(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://epoch.git", "main") / "fetched_at.txt"
        write_epoch(target, 1234567890)
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_origin_txt_mode_0600(self, real_cache: Path) -> None:
        d = catalog_entry_dir("https://origin.git", "main")
        write_entries(d / "origin.txt", ["https://origin.git@main"])
        assert os.stat(d / "origin.txt").st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# Read-write round-trips on real filesystem
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRealFsRoundTrips:
    def test_entries_roundtrip(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://rt.git", "main") / "index.txt"
        write_entries(target, ["alpha", "beta", "gamma"])
        assert read_entries(target) == ["alpha", "beta", "gamma"]

    def test_epoch_roundtrip(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://rt.git", "main") / "fetched_at.txt"
        write_epoch(target, 1700000000)
        assert read_epoch(target) == 1700000000

    def test_missing_file_returns_empty_list(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://rt.git", "main") / "no_such_file.txt"
        assert read_entries(target) == []

    def test_missing_epoch_returns_none(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://rt.git", "main") / "no_fetched_at.txt"
        assert read_epoch(target) is None

    def test_cache_dir_resolves_to_env(self, real_cache: Path) -> None:
        assert cache_dir() == real_cache

    def test_write_entries_overwrites_existing(self, real_cache: Path) -> None:
        target = catalog_entry_dir("https://ov.git", "main") / "index.txt"
        write_entries(target, ["old"])
        write_entries(target, ["new1", "new2"])
        assert read_entries(target) == ["new1", "new2"]
