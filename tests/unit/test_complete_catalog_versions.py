"""Unit tests for kanon_cli.completions.catalog_versions -- AC-TEST-001.

Covers: tag+branch mix, PEP 440 filter, cache-hit, cache-miss, cache-stale,
network-error, KANON_COMPLETION_ENABLED=0, prefix filter, dedup, sorting.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import subprocess

import kanon_cli.completions.catalog_versions as cv
from kanon_cli.completions.catalog_versions import (
    _fetch_and_cache_versions,
    _handle,
    _parse_ls_remote_output,
    _run_ls_remote,
    complete,
)


# ---------------------------------------------------------------------------
# _parse_ls_remote_output
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseLsRemoteOutput:
    """_parse_ls_remote_output() splits git ls-remote output into (tags, branches)."""

    def test_empty_output_returns_empty_lists(self) -> None:
        tags, branches = _parse_ls_remote_output("")
        assert tags == []
        assert branches == []

    def test_tags_extracted_correctly(self) -> None:
        output = "abc123\trefs/tags/1.0.0\ndef456\trefs/tags/2.0.0\n"
        tags, branches = _parse_ls_remote_output(output)
        assert sorted(tags) == ["1.0.0", "2.0.0"]
        assert branches == []

    def test_branches_extracted_correctly(self) -> None:
        output = "abc123\trefs/heads/main\ndef456\trefs/heads/develop\n"
        tags, branches = _parse_ls_remote_output(output)
        assert tags == []
        assert sorted(branches) == ["develop", "main"]

    def test_mixed_tags_and_branches(self) -> None:
        output = (
            "abc123\trefs/tags/1.0.0\ndef456\trefs/heads/main\nghi789\trefs/tags/2.0.0\njkl012\trefs/heads/develop\n"
        )
        tags, branches = _parse_ls_remote_output(output)
        assert sorted(tags) == ["1.0.0", "2.0.0"]
        assert sorted(branches) == ["develop", "main"]

    def test_slashed_tag_uses_last_component(self) -> None:
        """refs/tags/release/v3 -- last component is 'v3'."""
        output = "abc123\trefs/tags/release/v3\n"
        tags, branches = _parse_ls_remote_output(output)
        # Last component "v3" is kept in tags list; filtering happens separately
        assert tags == ["v3"]
        assert branches == []

    def test_annotated_tag_derefs_excluded(self) -> None:
        """refs/tags/1.0.0^{} (deref lines) are ignored."""
        output = "abc123\trefs/tags/1.0.0\ndef456\trefs/tags/1.0.0^{}\n"
        tags, branches = _parse_ls_remote_output(output)
        assert tags == ["1.0.0"]

    def test_unknown_refs_ignored(self) -> None:
        """Lines that are not refs/tags or refs/heads are ignored."""
        output = "abc123\trefs/keep/something\ndef456\trefs/tags/1.0.0\n"
        tags, branches = _parse_ls_remote_output(output)
        assert tags == ["1.0.0"]
        assert branches == []

    def test_lines_without_tab_ignored(self) -> None:
        """Lines without a tab character are skipped (malformed ls-remote output)."""
        output = "some-line-without-tab\nabc123\trefs/tags/1.0.0\n"
        tags, branches = _parse_ls_remote_output(output)
        assert tags == ["1.0.0"]
        assert branches == []


# ---------------------------------------------------------------------------
# _run_ls_remote
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLsRemote:
    """_run_ls_remote() shells out to git ls-remote and returns stdout."""

    def test_success_returns_stdout(self) -> None:
        """On exit 0, raw stdout is returned."""
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\trefs/tags/1.0.0\n"

        with patch("subprocess.run", return_value=mock_result):
            result = _run_ls_remote("https://example.com/repo.git", timeout=5)

        assert result == "abc123\trefs/tags/1.0.0\n"

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        """When git ls-remote exits non-zero, RuntimeError is raised."""
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: repository not found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="git ls-remote failed"):
                _run_ls_remote("https://example.com/repo.git", timeout=5)

    def test_timeout_raises_timeout_error(self) -> None:
        """When subprocess.run raises TimeoutExpired, TimeoutError is re-raised."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "ls-remote"], timeout=2),
        ):
            with pytest.raises(TimeoutError, match="timed out"):
                _run_ls_remote("https://example.com/repo.git", timeout=2)


# ---------------------------------------------------------------------------
# complete() -- main function
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComplete:
    """complete() integrates PEP 440 filter, cache, dedup, sort, prefix filter."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    def test_disabled_returns_empty_no_cache_touch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ENABLED=0 returns [] without touching cache or log."""
        self._setup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_ENABLED", "0")

        with patch.object(cv, "_fetch_and_cache_versions") as mock_fetch:
            with patch.object(cv, "log_completion_error") as mock_log:
                result = complete("")

        assert result == []
        mock_fetch.assert_not_called()
        mock_log.assert_not_called()

    def test_cache_hit_returns_filtered_entries_no_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache hit: returns entries filtered by prefix; no git calls (AC-FUNC-006)."""
        self._setup_env(monkeypatch, tmp_path)

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        (entry_dir / "tags.txt").write_text("1.0.0\n1.0.0a1\n2.0.0\ndevelop\nmain\n")
        (entry_dir / "fetched_at.txt").write_text(str(int(time.time())))

        with patch.object(cv, "_fetch_and_cache_versions") as mock_fetch:
            result = complete("")

        mock_fetch.assert_not_called()
        assert result == ["1.0.0", "1.0.0a1", "2.0.0", "develop", "main"]

    def test_mixed_tags_branches_pep440_filter_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full pipeline: tags PEP 440-filtered, branches pass through, deduped, sorted (AC-FUNC-001).

        Note: packaging.version.Version("v3") normalizes to "3" -- v3 IS a valid PEP 440
        version per the packaging library. The tag "not-a-version" is excluded (non-PEP-440).
        """
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = (
            "sha1\trefs/tags/1.0.0\n"
            "sha2\trefs/tags/2.0.0\n"
            "sha3\trefs/tags/1.0.0a1\n"
            "sha4\trefs/tags/not-a-version\n"
            "sha6\trefs/heads/main\n"
            "sha7\trefs/heads/develop\n"
        )

        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        # Tags: 1.0.0a1, 1.0.0, 2.0.0 pass; not-a-version excluded
        # Branches: main, develop pass unfiltered
        # Sorted: tags by PEP 440 version ordering first, then branches alphabetically
        assert result == ["1.0.0a1", "1.0.0", "2.0.0", "develop", "main"]

    def test_not_a_version_tag_excluded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tag 'not-a-version' is excluded by PEP 440 filter (AC-FUNC-001)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha1\trefs/tags/not-a-version\nsha2\trefs/tags/1.0.0\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        assert "not-a-version" not in result
        assert "1.0.0" in result

    def test_slashed_tag_last_component_extracted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """refs/tags/release/v3 is filtered on last component 'v3' (AC-FUNC-005).

        packaging.version.Version("v3") normalizes to "3" and is PEP 440-valid,
        so "v3" (the extracted last component) passes the filter and appears in output.
        The full slash-path "release/v3" does NOT appear -- only the last component.
        """
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha5\trefs/tags/release/v3\nsha1\trefs/tags/1.0.0\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        # "release/v3" should NOT appear -- only extracted last component "v3" may appear
        assert "release/v3" not in result
        # "v3" is valid PEP 440 (normalizes to 3), so it passes filter
        assert "v3" in result
        assert "1.0.0" in result

    def test_branches_not_pep440_filtered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Branch named 'not-a-version' passes through unfiltered (AC-FUNC-003)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha1\trefs/heads/not-a-version\nsha2\trefs/heads/main\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        # Branches pass through without PEP 440 filter
        assert "not-a-version" in result
        assert "main" in result

    def test_dedup_same_name_tag_and_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A tag and branch with the same name collapse to one entry (AC-FUNC-008)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/1.0.0\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        assert result.count("1.0.0") == 1

    @pytest.mark.parametrize(
        ("prefix", "expected"),
        [
            ("1", ["1.0.0a1", "1.0.0"]),
            ("m", ["main"]),
            ("2", ["2.0.0"]),
            ("d", ["develop"]),
            ("zzz", []),
        ],
        ids=["prefix-1", "prefix-m", "prefix-2", "prefix-d", "no-match"],
    )
    def test_prefix_filter(
        self, prefix: str, expected: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prefix filter narrows results (AC-FUNC-002)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = (
            "sha1\trefs/tags/1.0.0\n"
            "sha2\trefs/tags/2.0.0\n"
            "sha3\trefs/tags/1.0.0a1\n"
            "sha4\trefs/heads/main\n"
            "sha5\trefs/heads/develop\n"
        )
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete(prefix)

        assert result == expected

    def test_cache_miss_calls_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache miss triggers inline fetch."""
        self._setup_env(monkeypatch, tmp_path)
        # No cache directory -- miss

        with patch.object(cv, "_run_ls_remote", return_value="sha1\trefs/tags/1.0.0\n"):
            result = complete("")

        assert "1.0.0" in result

    def test_cache_stale_forks_bg_returns_stale(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache stale + KANON_COMPLETION_REFRESH_BG=1: stale data returned, bg refresh spawned."""
        self._setup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        (entry_dir / "tags.txt").write_text("1.0.0\n")
        (entry_dir / "fetched_at.txt").write_text(str(int(time.time()) - 5000))

        with patch.object(cv, "_fetch_and_cache_versions") as mock_fetch:
            with patch.object(cv, "_spawn_background_refresh") as mock_spawn:
                result = complete("")

        assert "1.0.0" in result
        mock_fetch.assert_not_called()
        mock_spawn.assert_called_once()

    def test_network_error_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Network error: empty result returned, error logged (AC-FUNC-007)."""
        self._setup_env(monkeypatch, tmp_path)

        with patch.object(cv, "_run_ls_remote", side_effect=RuntimeError("network failure")):
            with patch.object(cv, "log_completion_error") as mock_log:
                result = complete("")

        assert result == []
        mock_log.assert_called()

    def test_missing_catalog_source_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing KANON_CATALOG_SOURCE: empty result, error logged."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))

        with patch.object(cv, "log_completion_error") as mock_log:
            result = complete("")

        assert result == []
        mock_log.assert_called()

    def test_tags_sorted_by_pep440_version_order(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tags are sorted by packaging.version.Version ordering (lowest first)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha1\trefs/tags/2.0.0\nsha2\trefs/tags/1.0.0a1\nsha3\trefs/tags/1.0.0\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        # PEP 440 ordering: 1.0.0a1 < 1.0.0 < 2.0.0
        tags_only = [r for r in result if r not in ("main", "develop")]
        assert tags_only == ["1.0.0a1", "1.0.0", "2.0.0"]

    def test_branches_sorted_alphabetically_after_tags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Branches appear after tags, sorted alphabetically."""
        self._setup_env(monkeypatch, tmp_path)

        ls_remote_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/zebra\nsha3\trefs/heads/alpha\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_remote_output):
            result = complete("")

        assert result == ["1.0.0", "alpha", "zebra"]


# ---------------------------------------------------------------------------
# _fetch_and_cache_versions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchAndCacheVersions:
    """_fetch_and_cache_versions() runs git ls-remote, writes tags.txt + fetched_at.txt."""

    def test_writes_cache_on_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On success, tags.txt is written with filtered+sorted entries."""
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        entry_dir = tmp_path / "entry"

        ls_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/main\n"
        with patch.object(cv, "_run_ls_remote", return_value=ls_output):
            result = _fetch_and_cache_versions("https://example.com/repo.git", entry_dir)

        assert "1.0.0" in result
        assert "main" in result
        tags_path = entry_dir / "tags.txt"
        assert tags_path.exists()

    def test_ls_remote_failure_propagates(self, tmp_path: Path) -> None:
        """When _run_ls_remote raises, the exception propagates."""
        entry_dir = tmp_path / "entry"

        with patch.object(cv, "_run_ls_remote", side_effect=RuntimeError("ls-remote failed")):
            with pytest.raises(RuntimeError, match="ls-remote failed"):
                _fetch_and_cache_versions("https://example.com/repo.git", entry_dir)


# ---------------------------------------------------------------------------
# _handle()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandle:
    """_handle() is the argparse entry point; always exits 0."""

    def test_handle_prints_results_and_exits_0(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_handle() prints one name per line and exits 0."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))

        import argparse

        with patch.object(cv, "complete", return_value=["1.0.0", "main"]):
            args = argparse.Namespace(current_token="", refresh_only=False)
            result = _handle(args)

        captured = capsys.readouterr()
        assert "1.0.0\n" in captured.out
        assert "main\n" in captured.out
        assert result == 0

    def test_handle_empty_result_exits_0_empty_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_handle() with empty complete() result exits 0 with empty stdout."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))

        import argparse

        with patch.object(cv, "complete", return_value=[]):
            args = argparse.Namespace(current_token="", refresh_only=False)
            result = _handle(args)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert result == 0

    def test_handle_refresh_only_skips_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When refresh_only=True, _handle() does not print to stdout."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))

        import argparse

        with patch.object(cv, "complete", return_value=["1.0.0"]):
            args = argparse.Namespace(current_token="", refresh_only=True)
            result = _handle(args)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert result == 0


# ---------------------------------------------------------------------------
# _write_stderr_diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteStderrDiagnostic:
    """_write_stderr_diagnostic() writes to stderr when stderr is a tty."""

    def test_writes_to_stderr_when_tty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sys.stderr.isatty() is True, diagnostic line is written."""
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

        err_lines: list[str] = []

        class FakeTTYStderr:
            def isatty(self) -> bool:
                return True

            def write(self, s: str) -> int:
                err_lines.append(s)
                return len(s)

            def flush(self) -> None:
                pass

        with patch("sys.stderr", FakeTTYStderr()):
            result = complete("")

        assert result == []
        assert any("__complete_catalog_versions" in line for line in err_lines), (
            f"Expected diagnostic stderr output, got: {err_lines!r}"
        )

    def test_no_stderr_when_not_tty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sys.stderr.isatty() is False, NO line is written to stderr."""
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

        err_lines: list[str] = []

        class FakeNonTTYStderr:
            def isatty(self) -> bool:
                return False

            def write(self, s: str) -> int:
                err_lines.append(s)
                return len(s)

            def flush(self) -> None:
                pass

        with patch("sys.stderr", FakeNonTTYStderr()):
            result = complete("")

        assert result == []
        assert err_lines == [], f"Expected no stderr output, got: {err_lines!r}"


# ---------------------------------------------------------------------------
# _inline_fetch env restoration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInlineFetchEnvRestore:
    """_inline_fetch() restores KANON_COMPLETION_TIMEOUT after fetch."""

    def test_restores_pre_existing_env_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When KANON_COMPLETION_TIMEOUT was already set, _inline_fetch restores it."""
        from kanon_cli.completions.catalog_versions import _inline_fetch

        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("KANON_COMPLETION_TIMEOUT", "99")
        entry_dir = tmp_path / "entry"

        captured_env: dict[str, str] = {}

        def _fake_fetch(url: str, entry_dir_: Path) -> list[str]:
            captured_env["during"] = os.environ.get("KANON_COMPLETION_TIMEOUT", "")
            return ["1.0.0"]

        with patch.object(cv, "_fetch_and_cache_versions", side_effect=_fake_fetch):
            result = _inline_fetch("https://example.com/repo.git", entry_dir, timeout=42)

        assert result == ["1.0.0"]
        assert captured_env["during"] == "42"
        assert os.environ.get("KANON_COMPLETION_TIMEOUT") == "99"


# ---------------------------------------------------------------------------
# complete() -- malformed catalog source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteMalformedSource:
    """complete() returns [] on malformed KANON_CATALOG_SOURCE (no @)."""

    def test_invalid_source_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """complete() with invalid KANON_CATALOG_SOURCE logs error and returns []."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "no-at-sign-here")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))

        with patch.object(cv, "log_completion_error") as mock_log:
            result = complete("")

        assert result == []
        mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegister:
    """register() creates a hidden subparser with the correct arguments."""

    def test_register_creates_subparser(self) -> None:
        """register() adds __complete_catalog_versions to subparsers."""
        import argparse
        from kanon_cli.completions.catalog_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["__complete_catalog_versions", "1.0"])
        assert args.current_token == "1.0"

    def test_register_default_token_empty(self) -> None:
        """Without a token argument, current_token defaults to empty string."""
        import argparse
        from kanon_cli.completions.catalog_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["__complete_catalog_versions"])
        assert args.current_token == ""

    def test_register_refresh_only_flag(self) -> None:
        """register() adds --refresh-only flag defaulting to False."""
        import argparse
        from kanon_cli.completions.catalog_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args_with = parser.parse_args(["__complete_catalog_versions", "--refresh-only"])
        assert args_with.refresh_only is True

        args_without = parser.parse_args(["__complete_catalog_versions"])
        assert args_without.refresh_only is False


# ---------------------------------------------------------------------------
# _spawn_background_refresh
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpawnBackgroundRefresh:
    """_spawn_background_refresh() spawns a detached subprocess for cache refresh."""

    def test_spawn_calls_popen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_spawn_background_refresh() calls subprocess.Popen with start_new_session=True."""
        from unittest.mock import MagicMock
        from kanon_cli.completions.catalog_versions import _spawn_background_refresh

        mock_proc = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            _spawn_background_refresh("https://example.com/repo.git", "https://example.com/repo.git@main")

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["start_new_session"] is True
        assert call_kwargs["stdout"] == subprocess.DEVNULL
        assert call_kwargs["stderr"] == subprocess.DEVNULL


# ---------------------------------------------------------------------------
# complete() -- stale cache + bg disabled
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteStaleNoBg:
    """complete() -- stale cache with KANON_COMPLETION_REFRESH_BG=0 does inline fetch."""

    def test_stale_no_bg_calls_inline_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stale cache + KANON_COMPLETION_REFRESH_BG=0: inline fetch replaces stale data."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        (entry_dir / "tags.txt").write_text("stale-version\n")
        (entry_dir / "fetched_at.txt").write_text(str(int(time.time()) - 5000))

        with patch.object(cv, "_fetch_and_cache_versions", return_value=["2.0.0"]) as mock_fetch:
            result = complete("")

        mock_fetch.assert_called_once()
        assert "2.0.0" in result
        assert "stale-version" not in result
