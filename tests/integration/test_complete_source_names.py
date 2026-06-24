"""Integration tests for kanon __complete_source_names_in_kanon -- AC-TEST-002, AC-CYCLE-001.

Builds a real .kanon fixture file with three sources, sets ${KANON_KANON_FILE}
to that path, invokes `kanon __complete_source_names_in_kanon` via subprocess,
and asserts stdout is the sorted list of normalized names.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanon(path: Path, content: str) -> None:
    """Write content to path with mode 0600 (owner-read/write only)."""
    path.write_text(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _run_complete(
    kanon_path: Path,
    cache_dir: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_source_names_in_kanon <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_KANON_FILE"] = str(kanon_path)
    # The source-names completer does not touch the catalog cache; KANON_HOME
    # only isolates cache resolution under <KANON_HOME>/cache. Every log path in
    # these tests is set explicitly via KANON_COMPLETION_LOG.
    env["KANON_HOME"] = str(cache_dir)
    env["KANON_COMPLETION_ENABLED"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "__complete_source_names_in_kanon", current_token],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 / AC-CYCLE-001
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteSourceNamesSubprocess:
    """End-to-end subprocess tests for __complete_source_names_in_kanon."""

    def test_three_sources_sorted_output(self, tmp_path: Path) -> None:
        """AC-FUNC-001 / AC-CYCLE-001: three sources return sorted names, one per line."""
        kanon = tmp_path / ".kanon"
        _write_kanon(
            kanon,
            "KANON_SOURCE_foo_URL=https://example.com/foo\n"
            "KANON_SOURCE_bar_URL=https://example.com/bar\n"
            "KANON_SOURCE_baz_URL=https://example.com/baz\n",
        )
        result = _run_complete(kanon, tmp_path)
        assert result.returncode == 0
        assert result.stdout == "bar\nbaz\nfoo\n"

    def test_prefix_filter(self, tmp_path: Path) -> None:
        """AC-FUNC-002: prefix 'b' returns only 'bar' and 'baz'."""
        kanon = tmp_path / ".kanon"
        _write_kanon(
            kanon,
            "KANON_SOURCE_foo_URL=https://example.com/foo\n"
            "KANON_SOURCE_bar_URL=https://example.com/bar\n"
            "KANON_SOURCE_baz_URL=https://example.com/baz\n",
        )
        result = _run_complete(kanon, tmp_path, current_token="b")
        assert result.returncode == 0
        assert result.stdout == "bar\nbaz\n"

    def test_empty_stdout_on_missing_file(self, tmp_path: Path) -> None:
        """AC-FUNC-004: missing .kanon -> empty stdout, exit 0, log entry written."""
        kanon = tmp_path / "nonexistent.kanon"
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            kanon,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert log_path.exists()
        log_content = log_path.read_text()
        assert "FileNotFoundError" in log_content
        assert str(kanon) in log_content

    def test_empty_stdout_when_disabled(self, tmp_path: Path) -> None:
        """AC-FUNC-006: KANON_COMPLETION_ENABLED=0 -> empty stdout, exit 0."""
        kanon = tmp_path / ".kanon"
        _write_kanon(
            kanon,
            "KANON_SOURCE_foo_URL=https://example.com/foo\n",
        )
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            kanon,
            tmp_path,
            extra_env={
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_COMPLETION_LOG": str(log_path),
            },
        )
        assert result.returncode == 0
        assert result.stdout == ""
        # Log must not be written when disabled
        assert not log_path.exists()

    def test_hidden_subcommand_not_in_help(self, tmp_path: Path) -> None:
        """AC-FUNC-007: __complete_source_names_in_kanon absent from kanon --help."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert "__complete_source_names_in_kanon" not in result.stdout

    def test_cycle_truncated_kanon_logs_error(self, tmp_path: Path) -> None:
        """AC-CYCLE-001 second half: truncate .kanon -> empty stdout, log entry appears."""
        kanon = tmp_path / ".kanon"
        _write_kanon(
            kanon,
            "KANON_SOURCE_foo_URL=https://example.com/foo\n"
            "KANON_SOURCE_bar_URL=https://example.com/bar\n"
            "KANON_SOURCE_baz_URL=https://example.com/baz\n",
        )
        log_path = tmp_path / "completion-errors.log"
        # First invocation -- confirm all three sources
        result_full = _run_complete(
            kanon,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result_full.returncode == 0
        assert result_full.stdout == "bar\nbaz\nfoo\n"

        # Truncate the fixture (empty file -- no KANON_SOURCE_*_URL keys)
        _write_kanon(kanon, "")

        # Second invocation -- empty stdout, log entry for ValueError
        result_empty = _run_complete(
            kanon,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result_empty.returncode == 0
        assert result_empty.stdout == ""
        log_content = log_path.read_text()
        assert "ValueError" in log_content
