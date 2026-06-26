"""Integration tests for kanon __complete_catalog_entries -- AC-TEST-002, AC-CYCLE-001.

Builds a real fixture manifest repo on local filesystem, points
KANON_CATALOG_SOURCES at it, and invokes `kanon __complete_catalog_entries`
via subprocess end-to-end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _make_xml(name: str) -> str:
    """Return minimal valid *-marketplace.xml content for catalog name *name*."""
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
    """Create a local git repo with three catalog entries: foo, bar, baz.

    The repo is initialised with an explicit ``main`` initial branch
    (``git init -b main``) so the fixture is deterministic regardless of the
    ambient ``init.defaultBranch`` git config. Under the full suite a
    session-scoped fixture in ``tests/unit/repo/conftest.py`` repoints ``HOME``
    at a config-less temp dir for the rest of the session; without an explicit
    initial branch ``git init`` would then fall back to git's compiled-in
    default (``master``) and the ``git clone --branch main`` performed by the
    completion path would fail with "Remote branch main not found".
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

    specs = repo / "repo-specs" / "sub"
    specs.mkdir(parents=True)
    (specs / "foo-marketplace.xml").write_text(_make_xml("foo"))
    (specs / "bar-marketplace.xml").write_text(_make_xml("bar"))
    (specs / "baz-marketplace.xml").write_text(_make_xml("baz"))

    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )

    return repo


def _run_complete(
    repo_path: Path,
    cache_dir: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_catalog_entries <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_CATALOG_SOURCES"] = f"file://{repo_path}@main"

    env["KANON_HOME"] = str(cache_dir.parent)
    env["KANON_COMPLETION_REFRESH_BG"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "__complete_catalog_entries", current_token],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.integration
class TestCompleteCatalogEntriesSubprocess:
    """End-to-end subprocess tests for kanon __complete_catalog_entries (AC-TEST-002, AC-CYCLE-001)."""

    def test_empty_prefix_returns_all_entries_sorted(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """kanon __complete_catalog_entries '' returns bar, baz, foo sorted (AC-FUNC-001, AC-CYCLE-001)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert sorted(names) == names, f"entries not sorted: {names}"
        assert names == ["bar", "baz", "foo"], f"expected bar/baz/foo, got {names}"

    def test_prefix_f_returns_foo_only(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """kanon __complete_catalog_entries 'f' returns only foo (AC-FUNC-002)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir, current_token="f")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["foo"], f"expected ['foo'], got {names}"

    def test_prefix_ba_returns_bar_baz(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """kanon __complete_catalog_entries 'ba' returns bar and baz (AC-FUNC-002)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir, current_token="ba")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert sorted(names) == names
        assert names == ["bar", "baz"], f"expected ['bar', 'baz'], got {names}"

    def test_prefix_no_match_returns_empty(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """kanon __complete_catalog_entries 'zzz' returns empty stdout (AC-FUNC-002)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir, current_token="zzz")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"

    def test_completion_disabled_returns_empty(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 returns empty stdout, exits 0 (AC-FUNC-006)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(
            fixture_manifest_repo,
            cache_dir,
            extra_env={"KANON_COMPLETION_ENABLED": "0"},
        )

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"

    def test_nonexistent_catalog_source_returns_empty_and_logs(self, tmp_path: Path) -> None:
        """Non-existent KANON_CATALOG_SOURCES: empty stdout, exit 0, error logged (AC-CYCLE-001, AC-FUNC-008)."""
        cache_dir = tmp_path / "cache"
        env = {k: v for k, v in os.environ.items()}
        env["KANON_CATALOG_SOURCES"] = "file:///nonexistent/path@main"
        env["KANON_HOME"] = str(cache_dir.parent)
        env["KANON_COMPLETION_REFRESH_BG"] = "0"

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "__complete_catalog_entries", ""],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, f"expected exit 0, got {result.returncode}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"

        log_path = cache_dir / "completion-errors.log"
        assert log_path.exists(), "completion-errors.log should be written on failure"
        log_content = log_path.read_text()
        assert "__complete_catalog_entries" in log_content

    def test_hidden_subcommand_not_in_help(self, tmp_path: Path) -> None:
        """kanon --help does not list __complete_catalog_entries (AC-FUNC-007)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "__complete_catalog_entries" not in result.stdout, (
            "__complete_catalog_entries should be hidden from --help output"
        )

    def test_cache_hit_no_git_calls(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Second invocation uses cache (no new git clone needed) (AC-FUNC-003)."""
        cache_dir = tmp_path / "cache"

        result1 = _run_complete(fixture_manifest_repo, cache_dir)
        assert result1.returncode == 0

        result2 = _run_complete(fixture_manifest_repo, cache_dir)
        assert result2.returncode == 0

        names1 = sorted(result1.stdout.splitlines())
        names2 = sorted(result2.stdout.splitlines())
        assert names1 == names2 == ["bar", "baz", "foo"]

    def test_output_one_entry_per_line_with_trailing_newline(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Each catalog name is on its own line; output ends with trailing newline (spec Section 11.3)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir)

        assert result.returncode == 0

        if result.stdout:
            assert result.stdout.endswith("\n"), f"stdout does not end with newline: {result.stdout!r}"
        lines = result.stdout.splitlines()
        assert len(lines) == 3, f"expected 3 lines, got {lines}"
