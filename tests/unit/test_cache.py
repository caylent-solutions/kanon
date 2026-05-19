"""Unit tests for maybe_update_accessed_at() in kanon_cli.completions.cache.

TDD-paired test file for the production change introduced by E7-F3-S1-T3
(source-test atomicity per docs/source-test-atomicity.md).

Covers the public API surface of maybe_update_accessed_at: return value
semantics and file-write semantics for all five branches of the
coalescing rule.

All tests set KANON_CACHE_DIR to tmp_path so that _mkdir_secure's chmod
walk terminates at the tmp dir (which the test process owns), preventing
PermissionError on /tmp.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kanon_cli.completions.cache import maybe_update_accessed_at


@pytest.mark.unit
def test_missing_file_writes_and_returns_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-touch: missing accessed_at.txt -> write now, return True."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    result = maybe_update_accessed_at(path, now=5000, coalesce_window_seconds=60)
    assert result is True
    assert path.exists()
    assert int(path.read_text().strip()) == 5000


@pytest.mark.unit
def test_within_window_no_write_returns_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within coalesce window: no write, return False."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    path.write_text("5000\n")
    mtime_before = os.stat(path).st_mtime_ns

    result = maybe_update_accessed_at(path, now=5050, coalesce_window_seconds=60)

    assert result is False
    assert os.stat(path).st_mtime_ns == mtime_before


@pytest.mark.unit
def test_at_boundary_writes_and_returns_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At boundary (now - prior == window): write now, return True."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    path.write_text("5000\n")

    result = maybe_update_accessed_at(path, now=5060, coalesce_window_seconds=60)

    assert result is True
    assert int(path.read_text().strip()) == 5060


@pytest.mark.unit
def test_past_window_writes_and_returns_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past window (now - prior > window): write now, return True."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    path.write_text("5000\n")

    result = maybe_update_accessed_at(path, now=5200, coalesce_window_seconds=60)

    assert result is True
    assert int(path.read_text().strip()) == 5200


@pytest.mark.unit
def test_clock_skew_force_forward_returns_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clock skew (prior > now): rewrite to now, return True."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    path.write_text("9999\n")

    result = maybe_update_accessed_at(path, now=5000, coalesce_window_seconds=60)

    assert result is True
    assert int(path.read_text().strip()) == 5000


@pytest.mark.unit
def test_corrupt_file_treated_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-integer content is treated as missing: write now, return True."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    path.write_text("not-an-integer\n")

    result = maybe_update_accessed_at(path, now=5000, coalesce_window_seconds=60)

    assert result is True
    assert int(path.read_text().strip()) == 5000


@pytest.mark.unit
def test_written_file_has_secure_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written accessed_at.txt must have mode 0600 (owner read/write only)."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = tmp_path / "accessed_at.txt"
    maybe_update_accessed_at(path, now=1000, coalesce_window_seconds=60)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
