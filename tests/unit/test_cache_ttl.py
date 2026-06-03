"""Unit tests for Freshness enum and classify() -- AC-TEST-001.

Parametrized cases covering every Freshness rule:
- Missing file -> MISSING
- Empty file -> MISSING
- Non-numeric content -> MISSING
- Negative value -> MISSING
- Future timestamp (clock skew) -> FRESH
- Boundary: now - fetched_at == ttl -> FRESH
- Boundary: now - fetched_at == ttl + 1 -> STALE
- Ordinary fresh case -> FRESH
- Ordinary stale case -> STALE

Also covers read_entries_with_freshness() contract (AC-FUNC-008).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kanon_cli.completions.cache import Freshness, classify, read_entries_with_freshness


# ---------------------------------------------------------------------------
# Parametrized tests for classify()
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "file_content, ttl, now, expected",
    [
        # AC-FUNC-001: missing file -> MISSING
        (None, 300, 1_000_000, Freshness.MISSING),
        # AC-FUNC-002: empty file -> MISSING
        ("", 300, 1_000_000, Freshness.MISSING),
        # AC-FUNC-003: non-numeric content -> MISSING
        ("not-a-number", 300, 1_000_000, Freshness.MISSING),
        ("1.5", 300, 1_000_000, Freshness.MISSING),
        ("abc\n", 300, 1_000_000, Freshness.MISSING),
        # AC-FUNC-004: negative value -> MISSING
        ("-1", 300, 1_000_000, Freshness.MISSING),
        ("-1000000", 300, 1_000_000, Freshness.MISSING),
        # AC-FUNC-005: future timestamp (clock skew: fetched_at > now) -> FRESH
        ("2000000", 300, 1_000_000, Freshness.FRESH),
        ("1000001", 300, 1_000_000, Freshness.FRESH),
        # AC-FUNC-006 boundary: now - fetched_at == ttl -> FRESH
        ("999700", 300, 1_000_000, Freshness.FRESH),
        # AC-FUNC-006 boundary: now - fetched_at == ttl + 1 -> STALE
        ("999699", 300, 1_000_000, Freshness.STALE),
        # Ordinary fresh case: well within TTL
        ("999900", 300, 1_000_000, Freshness.FRESH),
        # Ordinary stale case: far past TTL
        ("100000", 300, 1_000_000, Freshness.STALE),
    ],
)
def test_classify_parametrized(
    tmp_path: Path,
    file_content: str | None,
    ttl: int,
    now: int,
    expected: Freshness,
) -> None:
    """classify() returns the correct Freshness for every rule.

    When file_content is None the file is not created (missing-file case).
    """
    fetched_at_path = tmp_path / "fetched_at.txt"
    if file_content is not None:
        fetched_at_path.write_text(file_content)

    result = classify(fetched_at_path, ttl_seconds=ttl, now=now)

    assert result == expected


# ---------------------------------------------------------------------------
# AC-FUNC-007: purity -- same result on repeated calls, no side effects
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_pure_no_side_effects(tmp_path: Path) -> None:
    """classify() is pure: calling it twice yields the same result and does not
    modify the file system.
    """
    fetched_at_path = tmp_path / "fetched_at.txt"
    fetched_at_path.write_text("999900")

    before_mtime = fetched_at_path.stat().st_mtime

    result1 = classify(fetched_at_path, ttl_seconds=300, now=1_000_000)
    result2 = classify(fetched_at_path, ttl_seconds=300, now=1_000_000)

    assert result1 == result2 == Freshness.FRESH
    # The file must not have been modified.
    assert fetched_at_path.stat().st_mtime == before_mtime
    # No extra files created alongside the fetched_at file.
    assert list(tmp_path.iterdir()) == [fetched_at_path]


# ---------------------------------------------------------------------------
# AC-FUNC-008: read_entries_with_freshness() contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_read_entries_with_freshness_missing_returns_empty(tmp_path: Path) -> None:
    """MISSING freshness => entries list is empty."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # No files created -- fetched_at.txt is absent.
    entries, freshness = read_entries_with_freshness(cache_dir, ttl_seconds=300, now=1_000_000)

    assert freshness == Freshness.MISSING
    assert entries == []


@pytest.mark.unit
def test_read_entries_with_freshness_fresh_returns_entries(tmp_path: Path) -> None:
    """FRESH freshness => entries list contains file contents."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    (cache_dir / "index.txt").write_text("foo\nbar\nbaz\n")
    (cache_dir / "fetched_at.txt").write_text("999900")

    entries, freshness = read_entries_with_freshness(cache_dir, ttl_seconds=300, now=1_000_000)

    assert freshness == Freshness.FRESH
    assert entries == ["foo", "bar", "baz"]


@pytest.mark.unit
def test_read_entries_with_freshness_stale_returns_entries(tmp_path: Path) -> None:
    """STALE freshness => entries list contains file contents."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    (cache_dir / "index.txt").write_text("alpha\nbeta\n")
    # fetched_at is 1000 seconds ago, ttl is 300 -- stale
    (cache_dir / "fetched_at.txt").write_text("999000")

    entries, freshness = read_entries_with_freshness(cache_dir, ttl_seconds=300, now=1_000_000)

    assert freshness == Freshness.STALE
    assert entries == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# AC-CYCLE-001: end-to-end cycle test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cycle_far_future_fetched_at_returns_fresh(tmp_path: Path) -> None:
    """Write index.txt and a far-future fetched_at.txt; confirm FRESH result."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    (cache_dir / "index.txt").write_text("foo\nbar\n")
    (cache_dir / "fetched_at.txt").write_text("2000000000")

    entries, freshness = read_entries_with_freshness(cache_dir, ttl_seconds=300, now=1_000_000_000)

    assert freshness == Freshness.FRESH
    assert entries == ["foo", "bar"]


@pytest.mark.unit
def test_cycle_just_expired_returns_stale(tmp_path: Path) -> None:
    """Write index.txt and fetched_at = now - ttl - 1; confirm STALE result."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ttl = 300
    now = 1_000_000_000
    fetched_at = now - ttl - 1

    (cache_dir / "index.txt").write_text("foo\nbar\n")
    (cache_dir / "fetched_at.txt").write_text(str(fetched_at))

    entries, freshness = read_entries_with_freshness(cache_dir, ttl_seconds=ttl, now=now)

    assert freshness == Freshness.STALE
    assert entries == ["foo", "bar"]
