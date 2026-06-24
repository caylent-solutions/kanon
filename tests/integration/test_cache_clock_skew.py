"""Integration test for cache clock-skew handling -- AC-TEST-002.

Verifies that when fetched_at.txt contains a future timestamp (clock skew),
the completer subprocess treats the cache as FRESH and does NOT re-fetch
from the remote repository.

The test writes a real fetched_at.txt with a far-future timestamp into the
per-catalog cache directory, points KANON_CATALOG_SOURCES at a fixture repo,
and invokes `kanon __complete_catalog_entries` via subprocess.  Because the
cache is declared FRESH (future timestamp), the subprocess must return the
pre-seeded index.txt contents without contacting the (unreachable) upstream
URL.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _run_complete(
    catalog_source: str,
    cache_dir: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_catalog_entries <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_CATALOG_SOURCES"] = catalog_source

    env["KANON_HOME"] = str(cache_dir.parent)

    env["KANON_COMPLETION_REFRESH_BG"] = "0"

    env["KANON_COMPLETION_TIMEOUT"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "__complete_catalog_entries", current_token],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.integration
class TestCacheClockSkew:
    """Verify that future timestamps in fetched_at.txt are treated as FRESH."""

    def test_future_fetched_at_returns_cached_entries_without_refetch(self, tmp_path: Path) -> None:
        """A future fetched_at timestamp is treated as FRESH (clock skew rule).

        Setup:
        - index.txt contains 'alpha' and 'beta'.
        - fetched_at.txt contains a timestamp far in the future.
        - KANON_CATALOG_SOURCES points to an unreachable URL.

        Expected:
        - Subprocess returns 'alpha' and 'beta' (from cache).
        - Subprocess exits 0.
        - No git clone is attempted (if it were, it would fail and return empty).
        """

        catalog_url = "file:///nonexistent-repo-path-that-does-not-exist"
        catalog_ref = "main"
        catalog_source = f"{catalog_url}@{catalog_ref}"

        cache_root = tmp_path / "cache"
        key = f"{catalog_url}@{catalog_ref}"
        sha = _sha256(key)
        entry_dir = cache_root / "catalogs" / sha
        entry_dir.mkdir(parents=True)

        (entry_dir / "index.txt").write_text("alpha\nbeta\n")

        future_epoch = 9_999_999_999
        (entry_dir / "fetched_at.txt").write_text(str(future_epoch))

        result = _run_complete(catalog_source, cache_root)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert sorted(names) == names
        assert names == ["alpha", "beta"], (
            f"Expected cached entries ['alpha', 'beta'], got {names!r}. stderr={result.stderr!r}"
        )

    def test_future_fetched_at_with_prefix_filters_correctly(self, tmp_path: Path) -> None:
        """Future-timestamp cache hit still respects prefix filtering."""
        catalog_url = "file:///nonexistent-for-clock-skew-prefix-test"
        catalog_ref = "main"
        catalog_source = f"{catalog_url}@{catalog_ref}"

        cache_root = tmp_path / "cache"
        key = f"{catalog_url}@{catalog_ref}"
        sha = _sha256(key)
        entry_dir = cache_root / "catalogs" / sha
        entry_dir.mkdir(parents=True)

        (entry_dir / "index.txt").write_text("alpha\nbeta\ngamma\n")
        future_epoch = 9_999_999_999
        (entry_dir / "fetched_at.txt").write_text(str(future_epoch))

        result = _run_complete(catalog_source, cache_root, current_token="a")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["alpha"], f"Expected ['alpha'], got {names!r}. stderr={result.stderr!r}"
