"""Unit tests for kanon_cli.completions.cache.

TDD-paired test file covering:
- maybe_update_accessed_at (introduced by E7-F3-S1-T3).
- write_entries sanitization integration (introduced by E7-F3-S1-T4):
  write_entries now calls sanitize_entries internally and logs dropped
  entries via log_completion_error.
- fork_background_refresh (E2-F1-S2-T1): routes through spawn_detached
  instead of os.fork/setsid/dup2 directly.
- utf-8 encoding sweep (AC-12): read_text/write_text callsites specify encoding="utf-8"

All tests set KANON_CACHE_DIR to tmp_path so that _mkdir_secure's chmod
walk terminates at the tmp dir (which the test process owns), preventing
PermissionError on /tmp.
"""

from __future__ import annotations

import os
import pathlib
from pathlib import Path

import pytest

from unittest.mock import patch

from kanon_cli.completions.cache import fork_background_refresh, maybe_update_accessed_at, write_entries
from tests.conftest import bare_text_io_calls


# ---------------------------------------------------------------------------
# utf-8 encoding sweep (AC-12)
# ---------------------------------------------------------------------------

_CACHE_PY = pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "completions" / "cache.py"


@pytest.mark.unit
class TestCachePyUtf8EncodingSweep:
    """AC-12: all read_text/write_text calls in completions/cache.py specify encoding."""

    def test_no_bare_read_text_calls(self) -> None:
        """completions/cache.py must not contain bare .read_text() calls."""
        bare = bare_text_io_calls(_CACHE_PY)
        read_bare = [b for b in bare if "read_text" in b[1]]
        assert read_bare == [], (
            f"completions/cache.py has bare read_text() calls: {read_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )

    def test_no_bare_write_text_calls(self) -> None:
        """completions/cache.py must not contain bare .write_text() calls."""
        bare = bare_text_io_calls(_CACHE_PY)
        write_bare = [b for b in bare if "write_text" in b[1]]
        assert write_bare == [], (
            f"completions/cache.py has bare write_text() calls: {write_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )


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


# ---------------------------------------------------------------------------
# write_entries -- sanitization integration (E7-F3-S1-T4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_entries_clean_entries_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean entries are written verbatim to the file, one per line."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    out = tmp_path / "index.txt"
    write_entries(out, ["foo", "bar-baz", "1.0.0"], completer_name="__complete_test")
    assert out.read_text() == "foo\nbar-baz\n1.0.0\n"


@pytest.mark.unit
def test_write_entries_dirty_entries_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entries with forbidden characters are excluded from the written file."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    out = tmp_path / "index.txt"
    write_entries(
        out,
        ["good", "bad\nentry", "also-good"],
        completer_name="__complete_test",
    )
    content = out.read_text()
    assert content == "good\nalso-good\n"
    assert "bad" not in content


@pytest.mark.unit
def test_write_entries_logs_dropped_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each dropped entry produces exactly one log line in completion-errors.log."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("KANON_COMPLETION_LOG", raising=False)

    out = tmp_path / "index.txt"
    write_entries(
        out,
        ["good", "bad\nentry", "also\x00bad"],
        completer_name="__complete_test",
    )

    log_path = tmp_path / "completion-errors.log"
    assert log_path.exists(), "completion-errors.log was not created"
    lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2, f"Expected 2 log lines, got {len(lines)}: {lines}"


@pytest.mark.unit
def test_write_entries_log_line_contains_newline_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log line for a dropped newline entry contains 'newline' in the message."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("KANON_COMPLETION_LOG", raising=False)

    out = tmp_path / "index.txt"
    write_entries(out, ["bad\nentry"], completer_name="__complete_test")

    log_path = tmp_path / "completion-errors.log"
    content = log_path.read_text()
    assert "newline" in content


@pytest.mark.unit
def test_write_entries_file_mode_is_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written entries file has mode 0600."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    out = tmp_path / "index.txt"
    write_entries(out, ["foo"], completer_name="__complete_test")
    mode = os.stat(out).st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


@pytest.mark.unit
def test_write_entries_empty_input_writes_empty_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty entries list writes an empty file."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    out = tmp_path / "index.txt"
    write_entries(out, [], completer_name="__complete_test")
    assert out.read_text() == ""


# ---------------------------------------------------------------------------
# fork_background_refresh -- importability and env-off short-circuit
# (E7-F3-S1-T5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fork_background_refresh_importable() -> None:
    """fork_background_refresh is importable from kanon_cli.completions.cache."""
    # The import at module level already proves importability; this test exists
    # to satisfy source-test atomicity for cache.py and gives an explicit,
    # human-readable assertion.
    from kanon_cli.completions.cache import fork_background_refresh as fbr

    assert callable(fbr)


@pytest.mark.unit
def test_fork_background_refresh_disabled_by_env_does_not_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When KANON_COMPLETION_REFRESH_BG=0, fork_background_refresh returns
    without calling spawn_detached.

    This test covers the fast-return branch of the function defined in cache.py
    and satisfies source-test atomicity for the fork_background_refresh symbol.
    """
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("called")

    with patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn:
        fork_background_refresh(refresh_fn)
        mock_spawn.assert_not_called()

    assert called == [], "refresh_fn must not be invoked when forking is disabled"


@pytest.mark.unit
def test_fork_background_refresh_routes_through_spawn_detached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fork_background_refresh calls spawn_detached (not os.fork directly)
    when the background refresh is enabled.

    This test verifies AC-9: the os.fork/setsid/dup2 sequence has been
    replaced by the spawn_detached helper.
    """
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("called")

    with patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn:
        fork_background_refresh(refresh_fn)
        mock_spawn.assert_called_once()
        # Verify a callable was passed as the first positional argument (the
        # logging wrapper around refresh_fn, not refresh_fn itself).
        assert callable(mock_spawn.call_args[0][0]), "spawn_detached must receive a callable as its first argument"
