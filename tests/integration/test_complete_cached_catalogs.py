"""Integration tests for kanon __complete_cached_catalogs -- AC-TEST-002, AC-CYCLE-001.

Seeds ``<KANON_HOME>/cache/catalogs/<sha>/origin.txt`` files with known url@ref
values, invokes `kanon __complete_cached_catalogs` via subprocess, and asserts
stdout matches the expected sorted output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kanon_cli.completions.cache import cache_dir


def _resolved_cache(home: Path) -> Path:
    """Return the cache directory resolved from KANON_HOME=*home*.

    Mirrors ``cache_dir()`` (= ``<KANON_HOME>/cache``) without depending on the
    parent process environment, so seed paths line up with what the subprocess
    resolves when ``KANON_HOME`` is set to *home*.
    """
    os.environ["KANON_HOME"] = str(home)
    try:
        return cache_dir()
    finally:
        del os.environ["KANON_HOME"]


def _make_catalog(home: Path, sha: str, origin: str) -> None:
    """Create <KANON_HOME>/cache/catalogs/<sha>/origin.txt with the given content."""
    entry = _resolved_cache(home) / "catalogs" / sha
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "origin.txt").write_text(origin)


def _run_complete(
    home: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_cached_catalogs <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_HOME"] = str(home)
    env["KANON_COMPLETION_ENABLED"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "__complete_cached_catalogs", current_token],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.integration
class TestCompleteCachedCatalogsSubprocess:
    """End-to-end subprocess tests for __complete_cached_catalogs."""

    def test_three_catalogs_sorted_output(self, tmp_path: Path) -> None:
        """AC-FUNC-001 / AC-CYCLE-001: three seeded catalogs return sorted url@ref output."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")
        result = _run_complete(tmp_path)
        assert result.returncode == 0
        assert result.stdout == (
            "git@c.example.com:org/m.git@develop\n"
            "https://a.example.com/m.git@main\n"
            "https://b.example.com/m.git@v1.0.0\n"
        )

    def test_empty_catalogs_dir_empty_stdout(self, tmp_path: Path) -> None:
        """AC-FUNC-002: empty catalogs/ directory -> empty stdout, exit 0."""
        catalogs_dir = _resolved_cache(tmp_path) / "catalogs"
        catalogs_dir.mkdir(parents=True)
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(tmp_path, extra_env={"KANON_COMPLETION_LOG": str(log_path)})
        assert result.returncode == 0
        assert result.stdout == ""
        assert not log_path.exists()

    def test_missing_cache_dir_empty_stdout(self, tmp_path: Path) -> None:
        """AC-FUNC-003: missing cache dir under KANON_HOME -> empty stdout, exit 0, no log."""
        missing_home = tmp_path / "no_cache_home"
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            missing_home,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert not log_path.exists()

    def test_prefix_https_filter(self, tmp_path: Path) -> None:
        """AC-FUNC-005: prefix 'https' returns only https URLs, one per line."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")
        result = _run_complete(tmp_path, current_token="https")
        assert result.returncode == 0
        assert result.stdout == ("https://a.example.com/m.git@main\nhttps://b.example.com/m.git@v1.0.0\n")

    def test_prefix_git_at_filter(self, tmp_path: Path) -> None:
        """AC-FUNC-005: prefix 'git@' returns only ssh URL."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")
        result = _run_complete(tmp_path, current_token="git@")
        assert result.returncode == 0
        assert result.stdout == "git@c.example.com:org/m.git@develop\n"

    def test_malformed_origin_skipped_valid_emitted_log_written(self, tmp_path: Path) -> None:
        """AC-FUNC-004 / AC-CYCLE-001: malformed origin.txt skipped, valid ones emitted, log entry written."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")

        _make_catalog(tmp_path, "sha4_bad", "")
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(tmp_path, extra_env={"KANON_COMPLETION_LOG": str(log_path)})
        assert result.returncode == 0

        assert result.stdout == (
            "git@c.example.com:org/m.git@develop\n"
            "https://a.example.com/m.git@main\n"
            "https://b.example.com/m.git@v1.0.0\n"
        )
        assert log_path.exists()
        log_content = log_path.read_text()
        assert "__complete_cached_catalogs" in log_content
        assert "sha4_bad" in log_content

    def test_disabled_empty_stdout_no_log(self, tmp_path: Path) -> None:
        """AC-FUNC-006: KANON_COMPLETION_ENABLED=0 -> empty stdout, exit 0, no log."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            tmp_path,
            extra_env={
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_COMPLETION_LOG": str(log_path),
            },
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert not log_path.exists()

    def test_hidden_subcommand_not_in_help(self, tmp_path: Path) -> None:
        """__complete_cached_catalogs is absent from kanon --help."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert "__complete_cached_catalogs" not in result.stdout

    def test_cycle_add_fourth_malformed_three_valid_emitted(self, tmp_path: Path) -> None:
        """AC-CYCLE-001 full cycle: seed three valid catalogs, then add malformed fourth.

        First invocation: assert sorted three-line output.
        Second invocation (with malformed fourth): assert three valid lines + log entry.
        """
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")
        log_path = tmp_path / "completion-errors.log"

        result1 = _run_complete(tmp_path, extra_env={"KANON_COMPLETION_LOG": str(log_path)})
        assert result1.returncode == 0
        assert result1.stdout == (
            "git@c.example.com:org/m.git@develop\n"
            "https://a.example.com/m.git@main\n"
            "https://b.example.com/m.git@v1.0.0\n"
        )
        assert not log_path.exists()

        _make_catalog(tmp_path, "sha4_bad", "")

        result2 = _run_complete(tmp_path, extra_env={"KANON_COMPLETION_LOG": str(log_path)})
        assert result2.returncode == 0
        assert result2.stdout == (
            "git@c.example.com:org/m.git@develop\n"
            "https://a.example.com/m.git@main\n"
            "https://b.example.com/m.git@v1.0.0\n"
        )
        assert log_path.exists()
        log_content = log_path.read_text()
        assert "__complete_cached_catalogs" in log_content
        assert "sha4_bad" in log_content
