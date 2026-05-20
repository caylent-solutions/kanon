"""Integration tests for kanon __complete_names_in_lockfile -- AC-TEST-002, AC-CYCLE-001.

Writes a real .kanon.lock fixture with nested includes and project URLs,
points ${KANON_LOCK_FILE} at it, invokes
`kanon __complete_names_in_lockfile` via subprocess, and asserts stdout
contains every name (top-level sources + transitive include paths + project
URLs), one per line, deduped, sorted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kanon_cli.core.lockfile import (
    CatalogBlock,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_SHA = "a" * 40
_MINIMAL_CATALOG = CatalogBlock(
    source="",
    url="",
    revision_spec="",
    resolved_ref="",
    resolved_sha="",
)


def _make_lockfile_with_nested_includes(lock_path: Path) -> None:
    """Write a .kanon.lock fixture with nested includes and projects.

    Structure:
      sources:
        - name: "alpha"
          includes:
            - path_in_repo: "repo-specs/beta.xml"
              includes:
                - path_in_repo: "repo-specs/gamma.xml"
                  includes:
                    - path_in_repo: "repo-specs/delta.xml"
          projects:
            - url: "https://example.com/proj-alpha.git"
        - name: "zulu"
          projects:
            - url: "https://example.com/proj-zulu.git"

    Expected complete("") output (sorted, deduped):
      alpha
      https://example.com/proj-alpha.git
      https://example.com/proj-zulu.git
      repo-specs/beta.xml
      repo-specs/delta.xml
      repo-specs/gamma.xml
      zulu
    """

    def _make_project(name: str, url: str) -> ProjectEntry:
        return ProjectEntry(
            name=name,
            url=url,
            canonical_url=canonicalize_repo_url(url),
            revision_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha=_DUMMY_SHA,
        )

    include_l3 = IncludeEntry(
        name="delta_name",
        path_in_repo="repo-specs/delta.xml",
        url="https://github.com/org/repo",
        resolved_sha=_DUMMY_SHA,
        includes=[],
    )
    include_l2 = IncludeEntry(
        name="gamma_name",
        path_in_repo="repo-specs/gamma.xml",
        url="https://github.com/org/repo",
        resolved_sha=_DUMMY_SHA,
        includes=[include_l3],
    )
    include_l1 = IncludeEntry(
        name="beta_name",
        path_in_repo="repo-specs/beta.xml",
        url="https://github.com/org/repo",
        resolved_sha=_DUMMY_SHA,
        includes=[include_l2],
    )
    source_alpha = SourceEntry(
        name="alpha",
        url="https://github.com/org/repo-alpha",
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_DUMMY_SHA,
        path="vendor/alpha",
        includes=[include_l1],
        projects=[_make_project("p_alpha", "https://example.com/proj-alpha.git")],
    )
    source_zulu = SourceEntry(
        name="zulu",
        url="https://github.com/org/repo-zulu",
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_DUMMY_SHA,
        path="vendor/zulu",
        includes=[],
        projects=[_make_project("p_zulu", "https://example.com/proj-zulu.git")],
    )
    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=_MINIMAL_CATALOG,
        sources=[source_alpha, source_zulu],
    )
    write_lockfile(lockfile, lock_path)


def _run_complete(
    lock_path: Path,
    cache_dir: Path,
    current_token: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `kanon __complete_names_in_lockfile <current_token>` as subprocess."""
    env = {k: v for k, v in os.environ.items()}
    env["KANON_LOCK_FILE"] = str(lock_path)
    env["KANON_CACHE_DIR"] = str(cache_dir)
    env["KANON_COMPLETION_ENABLED"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "__complete_names_in_lockfile",
            current_token,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 / AC-CYCLE-001
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteLockfileNamesSubprocess:
    """End-to-end subprocess tests for __complete_names_in_lockfile."""

    def test_all_names_sorted_deduped(self, tmp_path: Path) -> None:
        """AC-CYCLE-001: all seven values returned, sorted, deduped, one per line."""
        lock_path = tmp_path / ".kanon.lock"
        _make_lockfile_with_nested_includes(lock_path)
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            lock_path,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result.returncode == 0
        expected = (
            "alpha\n"
            "https://example.com/proj-alpha.git\n"
            "https://example.com/proj-zulu.git\n"
            "repo-specs/beta.xml\n"
            "repo-specs/delta.xml\n"
            "repo-specs/gamma.xml\n"
            "zulu\n"
        )
        assert result.stdout == expected
        # Completion-errors.log must be empty (no errors)
        assert not log_path.exists()

    def test_prefix_filter_source_names(self, tmp_path: Path) -> None:
        """AC-FUNC-002: prefix 'a' returns only values starting with 'a'."""
        lock_path = tmp_path / ".kanon.lock"
        _make_lockfile_with_nested_includes(lock_path)
        result = _run_complete(lock_path, tmp_path, current_token="a")
        assert result.returncode == 0
        assert result.stdout == "alpha\n"

    def test_prefix_filter_project_urls(self, tmp_path: Path) -> None:
        """AC-FUNC-002: prefix 'https' returns only project URLs."""
        lock_path = tmp_path / ".kanon.lock"
        _make_lockfile_with_nested_includes(lock_path)
        result = _run_complete(lock_path, tmp_path, current_token="https")
        assert result.returncode == 0
        lines = result.stdout.splitlines()
        assert all(line.startswith("https://") for line in lines)
        assert len(lines) == 2

    def test_empty_stdout_on_missing_lockfile(self, tmp_path: Path) -> None:
        """AC-FUNC-004: missing lockfile -> empty stdout, exit 0, log entry written."""
        lock_path = tmp_path / "nonexistent.lock"
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            lock_path,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert log_path.exists()
        log_content = log_path.read_text()
        assert "FileNotFoundError" in log_content
        assert str(lock_path) in log_content

    def test_empty_stdout_on_malformed_lockfile(self, tmp_path: Path) -> None:
        """AC-FUNC-005: malformed lockfile -> empty stdout, exit 0, log entry written."""
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text("not valid toml {{{{")
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            lock_path,
            tmp_path,
            extra_env={"KANON_COMPLETION_LOG": str(log_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert log_path.exists()
        log_content = log_path.read_text()
        assert "__complete_names_in_lockfile" in log_content

    def test_empty_stdout_when_disabled(self, tmp_path: Path) -> None:
        """AC-FUNC-006: KANON_COMPLETION_ENABLED=0 -> empty stdout, exit 0, no log."""
        lock_path = tmp_path / ".kanon.lock"
        _make_lockfile_with_nested_includes(lock_path)
        log_path = tmp_path / "completion-errors.log"
        result = _run_complete(
            lock_path,
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
        """AC-FUNC-007: __complete_names_in_lockfile absent from kanon --help."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert "__complete_names_in_lockfile" not in result.stdout

    def test_nested_includes_all_paths_present(self, tmp_path: Path) -> None:
        """AC-FUNC-008: depth-3 include chain - all three paths appear in output."""
        lock_path = tmp_path / ".kanon.lock"
        _make_lockfile_with_nested_includes(lock_path)
        result = _run_complete(lock_path, tmp_path)
        assert result.returncode == 0
        lines = result.stdout.splitlines()
        assert "repo-specs/beta.xml" in lines
        assert "repo-specs/gamma.xml" in lines
        assert "repo-specs/delta.xml" in lines
