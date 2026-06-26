"""Integration tests for fork_background_refresh end-to-end (AC-TEST-002, AC-CYCLE-001).

Pre-seeds a stale cache entry, invokes `kanon __complete_catalog_entries ""`,
asserts the completer returns stale data immediately, then polls fetched_at.txt
until the background refresh updates it.

Readiness detection: bounded polling loop (no time.sleep) with
KANON_TEST_READINESS_TIMEOUT controlling the maximum wait.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


_DEFAULT_READINESS_TIMEOUT = 15


def _make_xml(name: str) -> str:
    """Return minimal valid *-marketplace.xml content for catalog entry *name*."""
    return (
        '<?xml version="1.0"?>\n'
        "<package>\n"
        "  <catalog-metadata>\n"
        f"    <name>{name}</name>\n"
        "    <display-name>Display</display-name>\n"
        "    <description>desc</description>\n"
        "    <version>1.0.0</version>\n"
        "  </catalog-metadata>\n"
        "</package>\n"
    )


@pytest.fixture()
def fixture_manifest_repo(tmp_path: Path) -> Path:
    """Create a local git repo with catalog entries: foo, bar.

    The repo is initialised with an explicit ``main`` initial branch
    (``git init -b main``) so the fixture is deterministic regardless of the
    ambient ``init.defaultBranch`` git config. Under the full suite a
    session-scoped fixture in ``tests/unit/repo/conftest.py`` repoints ``HOME``
    at a config-less temp dir for the rest of the session; without an explicit
    initial branch ``git init`` would then fall back to git's compiled-in
    default (``master``) and the ``git clone --branch main`` performed by the
    background-refresh path would fail with "Remote branch main not found".
    """
    repo = tmp_path / "manifest-repo"
    repo.mkdir()

    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )

    specs = repo / "repo-specs"
    specs.mkdir()
    (specs / "foo-marketplace.xml").write_text(_make_xml("foo"))
    (specs / "bar-marketplace.xml").write_text(_make_xml("bar"))

    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


def _poll_until_fetched_at_updated(
    fetched_at_path: Path,
    stale_value: int,
    timeout_seconds: int,
) -> bool:
    """Poll *fetched_at_path* until its integer value differs from *stale_value*.

    Returns True when the file has been updated (its content no longer equals
    *stale_value*) within *timeout_seconds*; False when the deadline is exceeded.

    Uses busy-wait with os.sched_yield so there is no time.sleep dependency
    (readiness detection, not time-based).
    """
    deadline_ns = time.monotonic_ns() + timeout_seconds * 1_000_000_000
    while time.monotonic_ns() < deadline_ns:
        if fetched_at_path.exists():
            raw = fetched_at_path.read_text().strip()
            try:
                value = int(raw)
            except ValueError:
                pass
            else:
                if value != stale_value:
                    return True

        os.sched_yield()
    return False


@pytest.mark.integration
class TestBackgroundRefreshEndToEnd:
    """End-to-end integration test for the stale-cache background-refresh path."""

    def test_stale_cache_returns_immediately_and_bg_refresh_updates_fetched_at(
        self,
        fixture_manifest_repo: Path,
        tmp_path: Path,
    ) -> None:
        """AC-CYCLE-001: pre-seed stale cache, completer returns stale entries
        immediately, background process updates fetched_at.txt to recent value."""
        cache_dir = tmp_path / "cache"
        catalog_url = f"file://{fixture_manifest_repo}"
        catalog_ref = "main"

        entry_dir_real = _compute_entry_dir(cache_dir, catalog_url, catalog_ref)
        entry_dir_real.mkdir(parents=True, exist_ok=True)
        (entry_dir_real / "index.txt").write_text("foo\nbar\n")
        (entry_dir_real / "fetched_at.txt").write_text("1\n")

        stale_value = 1

        env = {k: v for k, v in os.environ.items()}
        env["KANON_CATALOG_SOURCES"] = f"{catalog_url}@{catalog_ref}"

        env["KANON_HOME"] = str(tmp_path)
        env["KANON_COMPLETION_REFRESH_BG"] = "1"

        env["KANON_COMPLETION_CACHE_TTL"] = "300"

        readiness_timeout = int(os.environ.get("KANON_TEST_READINESS_TIMEOUT", _DEFAULT_READINESS_TIMEOUT))

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "__complete_catalog_entries", ""],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, f"completer exited {result.returncode}; stderr: {result.stderr!r}"
        names = sorted(line for line in result.stdout.splitlines() if line)
        assert names == ["bar", "foo"], f"Expected stale entries ['bar', 'foo'], got {names!r}"

        fetched_at_path = entry_dir_real / "fetched_at.txt"
        refreshed = _poll_until_fetched_at_updated(
            fetched_at_path,
            stale_value=stale_value,
            timeout_seconds=readiness_timeout,
        )
        current_content = fetched_at_path.read_text() if fetched_at_path.exists() else "<missing>"
        assert refreshed, (
            f"fetched_at.txt was not updated within {readiness_timeout}s. Current content: {current_content!r}"
        )

        refreshed_epoch = int(fetched_at_path.read_text().strip())
        assert refreshed_epoch > stale_value, f"refreshed_epoch={refreshed_epoch} must be > stale_value={stale_value}"


def _compute_entry_dir(cache_dir: Path, catalog_url: str, ref: str) -> Path:
    """Compute the cache entry directory path without calling cache_dir()."""
    import hashlib

    key = f"{catalog_url}@{ref}"
    sha = hashlib.sha256(key.encode()).hexdigest()
    return cache_dir / "catalogs" / sha
