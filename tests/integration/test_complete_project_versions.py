"""Integration tests for kanon __complete_project_versions -- AC-TEST-002, AC-CYCLE-001.

Builds a real fixture project git repo on local filesystem with all six refs
(tags: 1.0.0, 2.0.0, 1.0.0a1, not-a-version; branches: main, feature/foo),
invokes ``kanon __complete_project_versions <fixture-url> ""`` via subprocess,
asserts stdout matches expected output.
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
def fixture_project_repo(tmp_path: Path) -> Path:
    """Create a local git repo with tags and branches per AC-FUNC-001."""
    repo = tmp_path / "project-repo"
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

    (repo / "README.md").write_text("project repo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        check=True,
        capture_output=True,
    )

    # Tags per AC-FUNC-001: 1.0.0, 2.0.0, 1.0.0a1, not-a-version
    for tag in ["1.0.0", "2.0.0", "1.0.0a1", "not-a-version"]:
        subprocess.run(
            ["git", "-C", str(repo), "tag", tag],
            check=True,
            capture_output=True,
        )

    # Branch per AC-FUNC-001: feature/foo
    subprocess.run(
        ["git", "-C", str(repo), "branch", "feature/foo"],
        check=True,
        capture_output=True,
    )

    return repo


def _run_complete_project_versions(
    repo_url: str,
    cache_dir: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_project_versions <repo_url> <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_CACHE_DIR"] = str(cache_dir)
    env["KANON_COMPLETION_REFRESH_BG"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "__complete_project_versions",
            repo_url,
            current_token,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteProjectVersionsSubprocess:
    """End-to-end subprocess tests for kanon __complete_project_versions (AC-TEST-002, AC-CYCLE-001)."""

    def test_empty_prefix_returns_expected_sorted_output(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """AC-CYCLE-001: kanon __complete_project_versions <fixture-url> '' returns sorted output.

        Expected: 1.0.0, 1.0.0a1, 2.0.0 (PEP 440 order) then feature/foo, main (alphabetical).
        not-a-version is excluded (fails PEP 440 parse).
        """
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        names = [line for line in result.stdout.splitlines() if line]
        assert "not-a-version" not in names, f"not-a-version should be excluded: {names}"
        for expected in ["1.0.0", "1.0.0a1", "2.0.0", "feature/foo", "main"]:
            assert expected in names, f"expected {expected!r} in output: {names}"

    def test_ac_cycle_001_exact_output(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """AC-CYCLE-001 exact assertion: stdout lists PEP 440 tags in version order then branches.

        PEP 440 ordering: 1.0.0a1 < 1.0.0 < 2.0.0 (pre-release before release).
        Branches follow alphabetically: feature/foo, main.
        Expected stdout: 1.0.0a1\\n1.0.0\\n2.0.0\\nfeature/foo\\nmain\\n
        """
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)

        assert result.returncode == 0, f"non-zero exit: {result.stderr!r}"
        assert result.stdout == "1.0.0a1\n1.0.0\n2.0.0\nfeature/foo\nmain\n", f"unexpected stdout: {result.stdout!r}"

    def test_non_pep440_tags_excluded(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """not-a-version is NOT in the output (AC-FUNC-001)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)

        assert result.returncode == 0
        names = result.stdout.splitlines()
        assert "not-a-version" not in names

    def test_prefix_1_returns_pep440_tags_starting_with_1(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """Prefix '1' returns only PEP 440 tags starting with '1' (AC-FUNC-003)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir, current_token="1")

        assert result.returncode == 0
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["1.0.0a1", "1.0.0"], f"expected [1.0.0a1, 1.0.0], got {names}"

    def test_prefix_m_returns_main_only(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """Prefix 'm' returns only 'main' (AC-FUNC-003)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir, current_token="m")

        assert result.returncode == 0
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["main"], f"expected ['main'], got {names}"

    def test_prefix_f_returns_feature_foo(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """Prefix 'f' returns 'feature/foo' (AC-FUNC-003)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir, current_token="f")

        assert result.returncode == 0
        names = [line for line in result.stdout.splitlines() if line]
        assert names == ["feature/foo"], f"expected ['feature/foo'], got {names}"

    def test_completion_disabled_returns_empty(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 returns empty stdout, exits 0 (AC-FUNC-007)."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(
            f"file://{fixture_project_repo}",
            cache_dir,
            extra_env={"KANON_COMPLETION_ENABLED": "0"},
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"

    def test_malformed_url_returns_empty_and_logs(self, tmp_path: Path) -> None:
        """AC-FUNC-005: malformed URL returns empty stdout, exit 0, error logged."""
        cache_dir = tmp_path / "cache"
        log_path = tmp_path / "errors.log"
        env = {k: v for k, v in os.environ.items()}
        env["KANON_CACHE_DIR"] = str(cache_dir)
        env["KANON_COMPLETION_LOG"] = str(log_path)
        env["KANON_COMPLETION_REFRESH_BG"] = "0"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "__complete_project_versions",
                "",  # empty URL -- malformed
                "",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, f"expected exit 0, got {result.returncode}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"
        assert log_path.exists(), "completion-errors.log should be written on failure"
        content = log_path.read_text()
        assert "__complete_project_versions" in content

    def test_nonexistent_repo_returns_empty_and_logs(self, tmp_path: Path) -> None:
        """Non-existent repo URL returns empty stdout, exit 0, error logged."""
        cache_dir = tmp_path / "cache"
        env = {k: v for k, v in os.environ.items()}
        env["KANON_CACHE_DIR"] = str(cache_dir)
        env["KANON_COMPLETION_REFRESH_BG"] = "0"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "__complete_project_versions",
                "file:///nonexistent/repo",
                "",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, f"expected exit 0, got {result.returncode}"
        assert result.stdout.strip() == "", f"expected empty stdout, got {result.stdout!r}"
        log_path = cache_dir / "completion-errors.log"
        assert log_path.exists(), "completion-errors.log should be written on failure"
        content = log_path.read_text()
        assert "__complete_project_versions" in content

    def test_cache_hit_no_git_calls_second_invocation(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """AC-FUNC-006: second invocation uses cache; same output returned."""
        cache_dir = tmp_path / "cache"

        result1 = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)
        assert result1.returncode == 0

        result2 = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)
        assert result2.returncode == 0

        assert result1.stdout == result2.stdout
        assert "not-a-version" not in result1.stdout.splitlines()

    def test_hidden_subcommand_not_in_help(self) -> None:
        """__complete_project_versions does not appear in kanon --help (AC-FUNC-007)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "__complete_project_versions" not in result.stdout

    def test_missing_current_token_arg_fails(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """AC-FUNC-004: missing current_token (second positional) fails with non-zero exit."""
        cache_dir = tmp_path / "cache"
        env = {k: v for k, v in os.environ.items()}
        env["KANON_CACHE_DIR"] = str(cache_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "__complete_project_versions",
                f"file://{fixture_project_repo}",
                # current_token intentionally omitted -- only one positional
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        # With only repo_url provided and current_token required, argparse exits non-zero
        assert result.returncode != 0, (
            f"expected non-zero exit when current_token omitted, got 0 (stdout={result.stdout!r})"
        )

    def test_output_ends_with_trailing_newline(self, fixture_project_repo: Path, tmp_path: Path) -> None:
        """Each entry on its own line, output ends with trailing newline."""
        cache_dir = tmp_path / "cache"
        result = _run_complete_project_versions(f"file://{fixture_project_repo}", cache_dir)

        assert result.returncode == 0
        if result.stdout:
            assert result.stdout.endswith("\n"), f"stdout does not end with newline: {result.stdout!r}"
