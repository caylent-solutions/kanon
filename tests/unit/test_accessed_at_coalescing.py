"""Unit tests for maybe_update_accessed_at() -- AC-TEST-001.

Parametrized cases covering every coalescing rule from spec Section 11.4:

- Missing file -> write now + True (first-touch).
- Prior value within window -> no write + False.
- Prior value at exactly the window boundary -> write + True.
- Prior value past the window -> write + True.
- Clock skew: prior_value > now -> rewrite to now + True.
- Non-numeric / corrupt content -> treated as missing, write now + True.
- Two back-to-back calls with delta == 0 -> first writes, second does not.

Mtime assertions use os.stat().st_mtime_ns (nanosecond granularity) to
verify that the no-write case leaves the file physically untouched.

All tests set KANON_HOME to tmp_path so that _mkdir_secure's chmod
walk terminates at the tmp dir (which the test process owns), preventing
PermissionError on /tmp.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kanon_cli.completions.cache import maybe_update_accessed_at


@pytest.mark.unit
@pytest.mark.parametrize(
    "prior_content, now, window, expected_return, expect_write",
    [
        (None, 1000, 60, True, True),
        ("1000\n", 1030, 60, False, False),
        ("1000\n", 1060, 60, True, True),
        ("1000\n", 1200, 60, True, True),
        ("2000\n", 1000, 60, True, True),
        ("not-a-number\n", 1000, 60, True, True),
        ("", 1000, 60, True, True),
    ],
)
def test_maybe_update_accessed_at_parametrized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_content: str | None,
    now: int,
    window: int,
    expected_return: bool,
    expect_write: bool,
) -> None:
    """maybe_update_accessed_at() follows the coalescing rules for each scenario."""
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    accessed_at_path = tmp_path / "accessed_at.txt"

    if prior_content is not None:
        accessed_at_path.write_text(prior_content)
        mtime_before = os.stat(accessed_at_path).st_mtime_ns
    else:
        mtime_before = None

    result = maybe_update_accessed_at(accessed_at_path, now=now, coalesce_window_seconds=window)

    assert result == expected_return

    if expect_write:
        assert accessed_at_path.exists()
        written_value = int(accessed_at_path.read_text().strip())
        assert written_value == now
    else:
        assert mtime_before is not None, "no-write case requires a pre-existing file"
        mtime_after = os.stat(accessed_at_path).st_mtime_ns
        assert mtime_after == mtime_before, (
            f"File mtime changed: before={mtime_before}, after={mtime_after} -- "
            "the coalescing rule should have suppressed the write"
        )


@pytest.mark.unit
def test_two_back_to_back_calls_same_now(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-FUNC-007: first call writes (first-touch); second call with same now
    is within the coalesce window (delta == 0) and returns False without writing.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    accessed_at_path = tmp_path / "accessed_at.txt"
    now = 1000
    window = 60

    result1 = maybe_update_accessed_at(accessed_at_path, now=now, coalesce_window_seconds=window)
    assert result1 is True
    assert accessed_at_path.exists()
    assert int(accessed_at_path.read_text().strip()) == now

    mtime_after_first = os.stat(accessed_at_path).st_mtime_ns

    result2 = maybe_update_accessed_at(accessed_at_path, now=now, coalesce_window_seconds=window)
    assert result2 is False

    mtime_after_second = os.stat(accessed_at_path).st_mtime_ns
    assert mtime_after_second == mtime_after_first, "Second back-to-back call should not have modified the file"


@pytest.mark.unit
def test_end_to_end_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-CYCLE-001: create an empty cache; call maybe_update_accessed_at with
    now=1000 then now=1030 (window=60); assert first wrote, second did not;
    then call with now=1100 and assert write happened.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    accessed_at_path = tmp_path / "accessed_at.txt"
    window = 60

    r1 = maybe_update_accessed_at(accessed_at_path, now=1000, coalesce_window_seconds=window)
    assert r1 is True
    assert int(accessed_at_path.read_text().strip()) == 1000

    mtime_after_1000 = os.stat(accessed_at_path).st_mtime_ns

    r2 = maybe_update_accessed_at(accessed_at_path, now=1030, coalesce_window_seconds=window)
    assert r2 is False
    assert os.stat(accessed_at_path).st_mtime_ns == mtime_after_1000

    r3 = maybe_update_accessed_at(accessed_at_path, now=1100, coalesce_window_seconds=window)
    assert r3 is True
    assert int(accessed_at_path.read_text().strip()) == 1100
