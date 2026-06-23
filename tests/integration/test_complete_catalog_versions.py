"""Integration tests for kanon __complete_catalog_versions -- AC-TEST-003, AC-CYCLE-001.

Builds a real fixture manifest git repo on local filesystem with all seven
refs (tags: 1.0.0, 2.0.0, 1.0.0a1, not-a-version, release/v3; branches:
main, develop), points KANON_CATALOG_SOURCES at it, and invokes the completer
via subprocess end-to-end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_manifest_repo(tmp_path: Path) -> Path:
    """Create a local git repo with the seven refs from the spec."""
    repo = tmp_path / "manifest-repo"
    repo.mkdir()

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
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

    # Create initial commit on default branch
    (repo / "README.md").write_text("manifest repo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    # Rename default branch to main
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        check=True,
        capture_output=True,
    )

    # Create tags: 1.0.0, 2.0.0, 1.0.0a1, not-a-version, release/v3
    for tag in ["1.0.0", "2.0.0", "1.0.0a1", "not-a-version"]:
        subprocess.run(
            ["git", "-C", str(repo), "tag", tag],
            check=True,
            capture_output=True,
        )
    # Create a namespaced tag: release/v3 (last component is "v3", non-PEP-440)
    subprocess.run(
        ["git", "-C", str(repo), "tag", "release/v3"],
        check=True,
        capture_output=True,
    )

    # Create branch: develop
    subprocess.run(
        ["git", "-C", str(repo), "branch", "develop"],
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
    """Invoke `kanon __complete_catalog_versions <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_CATALOG_SOURCES"] = f"file://{repo_path}@main"
    env["KANON_CACHE_DIR"] = str(cache_dir)
    env["KANON_COMPLETION_REFRESH_BG"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "__complete_catalog_versions", current_token],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteCatalogVersionsSubprocess:
    """End-to-end subprocess tests for kanon __complete_catalog_versions (AC-TEST-003, AC-CYCLE-001)."""

    def test_empty_prefix_returns_expected_sorted_output(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Empty prefix returns PEP 440-valid tags + branches, sorted (AC-FUNC-001, AC-CYCLE-001).

        Fixture has tags: 1.0.0, 2.0.0, 1.0.0a1, not-a-version, release/v3 (last comp "v3").
        Branches: main, develop.
        Expected output: PEP 440-valid tags in Version order, then branches alphabetically.
        "not-a-version" is excluded (fails PEP 440 parse).
        "v3" (last component of release/v3) passes PEP 440 (packaging normalizes to "3").
        """
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        # "not-a-version" excluded; "v3" included (PEP 440-valid); branches included
        assert "not-a-version" not in names, f"not-a-version should be excluded: {names}"
        assert "release/v3" not in names, f"full slash-path should not appear: {names}"
        assert "not-a-version" not in names
        # PEP 440-valid tags and branches must be present
        for expected in ["1.0.0", "1.0.0a1", "2.0.0", "v3", "develop", "main"]:
            assert expected in names, f"expected {expected!r} in output: {names}"

    def test_non_pep440_tags_excluded(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """not-a-version is NOT in the output; release/v3 full path is NOT present (AC-FUNC-001).

        "v3" (the extracted last component) IS present because packaging.version.Version("v3")
        normalizes to "3" and is a valid PEP 440 version.
        """
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = result.stdout.splitlines()
        assert "not-a-version" not in names, f"not-a-version should be excluded: {names}"
        assert "release/v3" not in names, f"full slash-path should not appear: {names}"

    def test_prefix_1_returns_pep440_tags_starting_with_1(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Prefix '1' returns only 1.0.0 and 1.0.0a1 (AC-FUNC-002)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir, current_token="1")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        # PEP 440 ordering: 1.0.0a1 < 1.0.0
        assert names == ["1.0.0a1", "1.0.0"], f"expected [1.0.0a1, 1.0.0], got {names}"

    def test_prefix_m_returns_main_only(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Prefix 'm' returns only 'main' (AC-FUNC-002)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir, current_token="m")

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["main"], f"expected ['main'], got {names}"

    def test_completion_disabled_returns_empty(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 returns empty stdout, exits 0 (AC-FUNC-007)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(
            fixture_manifest_repo,
            cache_dir,
            extra_env={"KANON_COMPLETION_ENABLED": "0"},
        )

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"

    def test_nonexistent_catalog_source_returns_empty_and_logs(self, tmp_path: Path) -> None:
        """Non-existent KANON_CATALOG_SOURCES: empty stdout, exit 0, error logged (AC-CYCLE-001)."""
        cache_dir = tmp_path / "cache"
        env = {k: v for k, v in os.environ.items()}
        env["KANON_CATALOG_SOURCES"] = "file:///nonexistent/path@main"
        env["KANON_CACHE_DIR"] = str(cache_dir)
        env["KANON_COMPLETION_REFRESH_BG"] = "0"

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "__complete_catalog_versions", ""],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, f"expected exit 0, got {result.returncode}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"
        log_path = cache_dir / "completion-errors.log"
        assert log_path.exists(), "completion-errors.log should be written on failure"
        log_content = log_path.read_text()
        assert "__complete_catalog_versions" in log_content

    def test_hidden_subcommand_not_in_help(self, tmp_path: Path) -> None:
        """kanon --help does not list __complete_catalog_versions (AC-FUNC-007)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "__complete_catalog_versions" not in result.stdout, (
            "__complete_catalog_versions should be hidden from --help output"
        )

    def test_cache_hit_no_git_calls(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Second invocation uses cache; same output (AC-FUNC-006)."""
        cache_dir = tmp_path / "cache"

        result1 = _run_complete(fixture_manifest_repo, cache_dir)
        assert result1.returncode == 0

        result2 = _run_complete(fixture_manifest_repo, cache_dir)
        assert result2.returncode == 0

        names1 = result1.stdout.splitlines()
        names2 = result2.stdout.splitlines()
        assert names1 == names2
        # Both calls return same output (PEP 440-valid tags + branches, not-a-version excluded)
        assert "not-a-version" not in names1
        assert "release/v3" not in names1
        for expected in ["1.0.0", "1.0.0a1", "2.0.0", "develop", "main"]:
            assert expected in names1, f"expected {expected!r} in output: {names1}"

    def test_output_one_entry_per_line_with_trailing_newline(self, fixture_manifest_repo: Path, tmp_path: Path) -> None:
        """Each version is on its own line; output ends with trailing newline."""
        cache_dir = tmp_path / "cache"
        result = _run_complete(fixture_manifest_repo, cache_dir)

        assert result.returncode == 0
        if result.stdout:
            assert result.stdout.endswith("\n"), f"stdout does not end with newline: {result.stdout!r}"
        lines = [line for line in result.stdout.splitlines() if line]
        # fixture has: 1.0.0, 1.0.0a1, 2.0.0, v3 (from release/v3), develop, main
        # not-a-version excluded (6 entries: 4 tags + 2 branches)
        assert len(lines) == 6, f"expected 6 lines, got {lines}"
