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

import os
from pathlib import Path

import pytest

from kanon_cli.completions.cache import (
    Freshness,
    classify,
    read_entries_with_freshness,
    read_search_versions_with_freshness,
    search_entry_dir,
    write_search_versions,
)


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


# ---------------------------------------------------------------------------
# Search-path TTL cache extension (E3-F1-S4-T1, spec Section 4.1 / FR-25 / AC-17)
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://example.com/org/catalog.git"
_SEARCH_REF = "main"


@pytest.fixture()
def _isolated_search_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KANON_HOME at tmp_path and return the resolved cache root.

    The cache lives at <KANON_HOME>/cache, so the returned path is the value
    ``cache_dir()`` resolves to (``tmp_path / "cache"``); the chmod walk
    terminates safely at that root.
    """
    from kanon_cli.completions.cache import cache_dir

    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    return cache_dir()


@pytest.mark.unit
def test_search_versions_cache_miss_returns_empty_missing(_isolated_search_cache: Path) -> None:
    """A never-written search source returns ([], MISSING) (cache miss)."""
    versions, freshness = read_search_versions_with_freshness(_SEARCH_URL, _SEARCH_REF, ttl_seconds=300, now=1_000_000)
    assert freshness is Freshness.MISSING
    assert versions == []


@pytest.mark.unit
def test_search_versions_fresh_reuse_within_ttl(_isolated_search_cache: Path) -> None:
    """A written enumeration is reused FRESH within the TTL (no re-enumeration)."""
    written = ["alpha@1.2.0", "alpha@1.1.0", "alpha@latest"]
    write_search_versions(_SEARCH_URL, _SEARCH_REF, written, now=1_000_000)

    # now within the TTL window of the stamped fetched_at.
    versions, freshness = read_search_versions_with_freshness(_SEARCH_URL, _SEARCH_REF, ttl_seconds=300, now=1_000_100)
    assert freshness is Freshness.FRESH
    assert versions == written


@pytest.mark.unit
def test_search_versions_stale_past_ttl_still_returns_entries(_isolated_search_cache: Path) -> None:
    """Past the TTL the entry is STALE but its versions are still returned.

    STALE (not MISSING) is the trigger for re-enumeration in the search path while
    the stale data remains usable; the caller re-enumerates on STALE.
    """
    written = ["beta@2.0.0", "beta@latest"]
    write_search_versions(_SEARCH_URL, _SEARCH_REF, written, now=1_000_000)

    # now is well past the TTL window.
    versions, freshness = read_search_versions_with_freshness(
        _SEARCH_URL, _SEARCH_REF, ttl_seconds=300, now=1_000_000 + 301
    )
    assert freshness is Freshness.STALE
    assert versions == written


@pytest.mark.unit
def test_search_versions_per_source_isolation(_isolated_search_cache: Path) -> None:
    """Distinct source@ref keys map to distinct cache entries (no cross-talk)."""
    write_search_versions(_SEARCH_URL, "main", ["alpha@1.0.0"], now=1_000_000)
    write_search_versions(_SEARCH_URL, "dev", ["alpha@9.9.9"], now=1_000_000)

    main_versions, _ = read_search_versions_with_freshness(_SEARCH_URL, "main", ttl_seconds=300, now=1_000_010)
    dev_versions, _ = read_search_versions_with_freshness(_SEARCH_URL, "dev", ttl_seconds=300, now=1_000_010)
    assert main_versions == ["alpha@1.0.0"]
    assert dev_versions == ["alpha@9.9.9"]
    # The two entries live in different per-key directories.
    assert search_entry_dir(_SEARCH_URL, "main") != search_entry_dir(_SEARCH_URL, "dev")


@pytest.mark.unit
def test_search_versions_dir_under_search_namespace(_isolated_search_cache: Path) -> None:
    """The search cache is namespaced under cache_dir()/search/<sha>."""
    entry_dir = search_entry_dir(_SEARCH_URL, _SEARCH_REF)
    assert entry_dir.parent == _isolated_search_cache / "search"
    # The directory name is a 64-char SHA-256 hex digest.
    assert len(entry_dir.name) == 64
    assert all(c in "0123456789abcdef" for c in entry_dir.name)


@pytest.mark.unit
def test_search_versions_write_stamps_fetched_at(_isolated_search_cache: Path) -> None:
    """write_search_versions stamps fetched_at.txt with the supplied epoch."""
    write_search_versions(_SEARCH_URL, _SEARCH_REF, ["alpha@1.0.0"], now=1_234_567)
    fetched_at = search_entry_dir(_SEARCH_URL, _SEARCH_REF) / "fetched_at.txt"
    assert fetched_at.exists()
    assert int(fetched_at.read_text(encoding="utf-8").strip()) == 1_234_567


@pytest.mark.unit
def test_search_versions_files_are_owner_private(_isolated_search_cache: Path) -> None:
    """The search cache files are written 0600 (user-private, spec Section 3.6)."""
    write_search_versions(_SEARCH_URL, _SEARCH_REF, ["alpha@1.0.0"], now=1_000_000)
    entry_dir = search_entry_dir(_SEARCH_URL, _SEARCH_REF)
    versions_file = entry_dir / "versions.txt"
    mode = os.stat(versions_file).st_mode & 0o777
    assert mode == 0o600
