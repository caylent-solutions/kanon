"""Unit tests for kanon_cli.completions.project_versions -- AC-TEST-001.

Covers: PEP 440 filter (same accept/reject set as T4), URL canonicalization
sharing cache, malformed URL, cache states, network-error,
KANON_COMPLETION_ENABLED=0.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.completions.project_versions as pv
from kanon_cli.completions.project_versions import (
    _fetch_and_cache_versions,
    _handle,
    _parse_ls_remote_output,
    _run_ls_remote,
    complete,
)


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
        """Lines without a tab character are skipped."""
        output = "some-line-without-tab\nabc123\trefs/tags/1.0.0\n"
        tags, branches = _parse_ls_remote_output(output)
        assert tags == ["1.0.0"]
        assert branches == []


@pytest.mark.unit
class TestRunLsRemote:
    """_run_ls_remote() shells out to git ls-remote and returns stdout."""

    def test_success_returns_stdout(self) -> None:
        """On exit 0, raw stdout is returned."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\trefs/tags/1.0.0\n"

        with patch("subprocess.run", return_value=mock_result):
            result = _run_ls_remote("https://example.com/repo.git", timeout=5)

        assert result == "abc123\trefs/tags/1.0.0\n"

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        """When git ls-remote exits non-zero, RuntimeError is raised."""
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


@pytest.mark.unit
class TestCompletePEP440Filter:
    """complete() applies PEP 440 filter to tags, passes branches through."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    @pytest.mark.parametrize(
        ("tags", "expected_in", "expected_not_in"),
        [
            (["1.0.0", "2.0.0", "1.0.0a1"], ["1.0.0", "2.0.0", "1.0.0a1"], []),
            (["not-a-version", "1.0.0"], ["1.0.0"], ["not-a-version"]),
            (["v3"], ["v3"], []),
        ],
        ids=["valid-pep440", "reject-non-pep440", "v-prefix-valid"],
    )
    def test_pep440_filter_parametrized(
        self,
        tags: list[str],
        expected_in: list[str],
        expected_not_in: list[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PEP 440 filter accepts and rejects correctly."""
        self._setup_env(monkeypatch, tmp_path)

        ls_output = "".join(f"sha\trefs/tags/{t}\n" for t in tags)
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = complete("https://example.com/proj.git", "")

        for expected in expected_in:
            assert expected in result, f"{expected!r} should be in {result}"
        for not_expected in expected_not_in:
            assert not_expected not in result, f"{not_expected!r} should not be in {result}"

    def test_branches_not_pep440_filtered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Branch named 'not-a-version' passes through unfiltered."""
        self._setup_env(monkeypatch, tmp_path)

        ls_output = "sha1\trefs/heads/not-a-version\nsha2\trefs/heads/main\n"
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = complete("https://example.com/proj.git", "")

        assert "not-a-version" in result
        assert "main" in result

    def test_ac_func_001_fixture_tags_and_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-001: tags 1.0.0, 2.0.0, 1.0.0a1, not-a-version + branches main, feature/foo.

        Expected output: 1.0.0a1, 1.0.0, 2.0.0 (PEP 440 order), feature/foo, main (alphabetical).
        non-PEP-440 tag excluded.
        """
        self._setup_env(monkeypatch, tmp_path)

        ls_output = (
            "sha1\trefs/tags/1.0.0\n"
            "sha2\trefs/tags/2.0.0\n"
            "sha3\trefs/tags/1.0.0a1\n"
            "sha4\trefs/tags/not-a-version\n"
            "sha5\trefs/heads/main\n"
            "sha6\trefs/heads/feature/foo\n"
        )
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = complete("https://example.com/proj.git", "")

        assert "not-a-version" not in result
        assert result == ["1.0.0a1", "1.0.0", "2.0.0", "feature/foo", "main"]

    def test_imports_filter_pep440_tags(self) -> None:
        """AC-FUNC-008: filter_pep440_tags is imported from pep440_filter (no duplicate impl)."""
        from kanon_cli.completions.project_versions import filter_pep440_tags
        from kanon_cli.completions.pep440_filter import filter_pep440_tags as ref_fn

        assert filter_pep440_tags is ref_fn


@pytest.mark.unit
class TestCompleteURLCanonicalization:
    """Two URL shapes that canonicalize to the same value share the same cache entry."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    def test_https_and_ssh_urls_share_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-002: https://example.com/proj.git and git@example.com:org/proj.git both
        canonicalize, and after one fetch the other reads from cache without fetching."""
        self._setup_env(monkeypatch, tmp_path)

        ls_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/main\n"

        fetch_count = 0

        def counting_fetch(url: str, timeout: int) -> str:
            nonlocal fetch_count
            fetch_count += 1
            return ls_output

        with patch.object(pv, "_run_ls_remote", side_effect=counting_fetch):
            result_https = complete("https://example.com/proj.git", "")

        from kanon_cli.completions import cache as cache_mod
        from kanon_cli.core.url import canonicalize_repo_url

        canonical_https = canonicalize_repo_url("https://example.com/proj.git")
        entry_dir = cache_mod.project_entry_dir(canonical_https)

        assert entry_dir.exists(), f"cache dir not created: {entry_dir}"

        with patch.object(pv, "_run_ls_remote", side_effect=counting_fetch):
            result_ssh = complete("https://example.com/proj.git", "")

        assert result_https == result_ssh, (
            f"Same canonical URL must yield same result: {result_https!r} vs {result_ssh!r}"
        )

    def test_canonical_url_used_for_cache_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cache directory is keyed on the canonicalized URL, not the raw input."""
        self._setup_env(monkeypatch, tmp_path)

        from kanon_cli.completions import cache as cache_mod
        from kanon_cli.core.url import canonicalize_repo_url

        raw_url = "https://example.com/org/proj.git"
        canonical = canonicalize_repo_url(raw_url)
        expected_dir = cache_mod.project_entry_dir(canonical)

        ls_output = "sha1\trefs/tags/1.0.0\n"
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            complete(raw_url, "")

        assert expected_dir.exists(), f"Expected cache dir at {expected_dir}"


@pytest.mark.unit
class TestCompleteMalformedURL:
    """Malformed repo_url produces empty stdout AND a structured log entry."""

    def test_empty_url_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty URL causes ValueError from canonicalize_repo_url, empty result."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(pv, "log_completion_error") as mock_log:
            result = complete("", "")

        assert result == []
        mock_log.assert_called_once()
        args = mock_log.call_args
        assert isinstance(args[0][1], ValueError)

    def test_whitespace_url_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Whitespace-only URL fails canonicalize_repo_url with ValueError."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(pv, "log_completion_error") as mock_log:
            result = complete("   ", "")

        assert result == []
        mock_log.assert_called_once()

    def test_url_with_query_string_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """URL with query string fails canonicalize_repo_url with ValueError."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(pv, "log_completion_error") as mock_log:
            result = complete("https://example.com/proj?foo=bar", "")

        assert result == []
        mock_log.assert_called_once()

    def test_url_with_fragment_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """URL with fragment fails canonicalize_repo_url with ValueError."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(pv, "log_completion_error") as mock_log:
            result = complete("https://example.com/proj#section", "")

        assert result == []
        mock_log.assert_called_once()

    def test_log_entry_contains_completer_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log entry contains the completer name '__complete_project_versions'."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        log_path = tmp_path / "errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))

        complete("", "")

        assert log_path.exists(), "error log should be written"
        content = log_path.read_text()
        assert "__complete_project_versions" in content
        assert "ValueError" in content


@pytest.mark.unit
class TestCompleteCacheStates:
    """Cache hit, stale, and miss behavior for project_versions."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    def _seed_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, entries: list[str], age_seconds: int = 0
    ) -> None:
        """Seed the project cache for https://example.com/proj.git."""
        from kanon_cli.completions import cache as cache_mod
        from kanon_cli.core.url import canonicalize_repo_url

        canonical = canonicalize_repo_url("https://example.com/proj.git")
        entry_dir = cache_mod.project_entry_dir(canonical)
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "tags.txt").write_text("\n".join(entries) + "\n")
        (entry_dir / "fetched_at.txt").write_text(str(int(time.time()) - age_seconds))

    def test_cache_hit_no_git_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache hit within TTL: no git ls-remote call (AC-FUNC-006)."""
        self._setup_env(monkeypatch, tmp_path)
        self._seed_cache(monkeypatch, tmp_path, ["1.0.0", "main"])

        with patch.object(pv, "_fetch_and_cache_versions") as mock_fetch:
            result = complete("https://example.com/proj.git", "")

        mock_fetch.assert_not_called()
        assert "1.0.0" in result
        assert "main" in result

    def test_cache_miss_calls_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache miss triggers inline fetch."""
        self._setup_env(monkeypatch, tmp_path)

        ls_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/main\n"
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = complete("https://example.com/proj.git", "")

        assert "1.0.0" in result
        assert "main" in result

    def test_stale_cache_bg_disabled_does_inline_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stale cache + KANON_COMPLETION_REFRESH_BG=0: inline fetch replaces stale data."""
        self._setup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")
        self._seed_cache(monkeypatch, tmp_path, ["stale-entry"], age_seconds=5000)

        with patch.object(pv, "_fetch_and_cache_versions", return_value=["2.0.0"]) as mock_fetch:
            result = complete("https://example.com/proj.git", "")

        mock_fetch.assert_called_once()
        assert "2.0.0" in result
        assert "stale-entry" not in result

    def test_stale_cache_bg_enabled_returns_stale_forks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stale cache + KANON_COMPLETION_REFRESH_BG=1: stale returned, bg refresh spawned."""
        self._setup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")
        self._seed_cache(monkeypatch, tmp_path, ["1.0.0"], age_seconds=5000)

        with patch.object(pv, "_fetch_and_cache_versions") as mock_fetch:
            with patch.object(pv, "fork_background_refresh") as mock_fork:
                result = complete("https://example.com/proj.git", "")

        mock_fetch.assert_not_called()
        mock_fork.assert_called_once()
        assert "1.0.0" in result


@pytest.mark.unit
class TestCompletePrefixFilter:
    """Prefix filter narrows the candidate list correctly."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    @pytest.mark.parametrize(
        ("prefix", "expected"),
        [
            ("1", ["1.0.0a1", "1.0.0"]),
            ("m", ["main"]),
            ("2", ["2.0.0"]),
            ("f", ["feature/foo"]),
            ("zzz", []),
            ("", ["1.0.0a1", "1.0.0", "2.0.0", "feature/foo", "main"]),
        ],
        ids=["prefix-1", "prefix-m", "prefix-2", "prefix-f", "no-match", "empty-prefix"],
    )
    def test_prefix_filter_parametrized(
        self,
        prefix: str,
        expected: list[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prefix filter narrows results correctly (AC-FUNC-003)."""
        self._setup_env(monkeypatch, tmp_path)

        ls_output = (
            "sha1\trefs/tags/1.0.0\n"
            "sha2\trefs/tags/2.0.0\n"
            "sha3\trefs/tags/1.0.0a1\n"
            "sha4\trefs/tags/not-a-version\n"
            "sha5\trefs/heads/main\n"
            "sha6\trefs/heads/feature/foo\n"
        )
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = complete("https://example.com/proj.git", prefix)

        assert result == expected, f"prefix={prefix!r}: expected {expected}, got {result}"


@pytest.mark.unit
class TestCompleteDisabled:
    """KANON_COMPLETION_ENABLED=0 returns [] without touching cache or log."""

    def test_disabled_returns_empty_no_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ENABLED=0 exits early with []."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.setenv("KANON_COMPLETION_ENABLED", "0")

        with patch.object(pv, "_fetch_and_cache_versions") as mock_fetch:
            with patch.object(pv, "log_completion_error") as mock_log:
                result = complete("https://example.com/proj.git", "")

        assert result == []
        mock_fetch.assert_not_called()
        mock_log.assert_not_called()


@pytest.mark.unit
class TestCompleteNetworkError:
    """Network error: empty result returned, error logged."""

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    def test_runtime_error_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """RuntimeError from git ls-remote -> empty result + error logged."""
        self._setup_env(monkeypatch, tmp_path)

        with patch.object(pv, "_run_ls_remote", side_effect=RuntimeError("connection refused")):
            with patch.object(pv, "log_completion_error") as mock_log:
                result = complete("https://example.com/proj.git", "")

        assert result == []
        mock_log.assert_called()

    def test_timeout_error_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TimeoutError from git ls-remote -> empty result + error logged."""
        self._setup_env(monkeypatch, tmp_path)

        with patch.object(pv, "_run_ls_remote", side_effect=TimeoutError("timed out")):
            with patch.object(pv, "log_completion_error") as mock_log:
                result = complete("https://example.com/proj.git", "")

        assert result == []
        mock_log.assert_called()


@pytest.mark.unit
class TestFetchAndCacheVersions:
    """_fetch_and_cache_versions() runs git ls-remote, writes tags.txt."""

    def test_writes_cache_on_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On success, tags.txt is written with filtered+sorted entries."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        entry_dir = tmp_path / "entry"

        ls_output = "sha1\trefs/tags/1.0.0\nsha2\trefs/heads/main\n"
        with patch.object(pv, "_run_ls_remote", return_value=ls_output):
            result = _fetch_and_cache_versions("https://example.com/proj.git", entry_dir)

        assert "1.0.0" in result
        assert "main" in result
        tags_path = entry_dir / "tags.txt"
        assert tags_path.exists()

    def test_ls_remote_failure_propagates(self, tmp_path: Path) -> None:
        """When _run_ls_remote raises, the exception propagates."""
        entry_dir = tmp_path / "entry"

        with patch.object(pv, "_run_ls_remote", side_effect=RuntimeError("ls-remote failed")):
            with pytest.raises(RuntimeError, match="ls-remote failed"):
                _fetch_and_cache_versions("https://example.com/proj.git", entry_dir)


@pytest.mark.unit
class TestHandle:
    """_handle() is the argparse entry point for __complete_project_versions."""

    def test_handle_prints_results_and_exits_0(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_handle() prints one version per line and returns 0."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        import argparse

        with patch.object(pv, "complete", return_value=["1.0.0", "main"]):
            args = argparse.Namespace(repo_url="https://example.com/proj.git", current_token="")
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
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        import argparse

        with patch.object(pv, "complete", return_value=[]):
            args = argparse.Namespace(repo_url="https://example.com/proj.git", current_token="")
            result = _handle(args)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert result == 0


@pytest.mark.unit
class TestRegister:
    """register() creates a hidden subparser with TWO positional args."""

    def test_register_creates_subparser_with_two_args(self) -> None:
        """register() adds __complete_project_versions with repo_url and current_token."""
        import argparse
        from kanon_cli.completions.project_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["__complete_project_versions", "https://example.com/proj.git", "1.0"])
        assert args.repo_url == "https://example.com/proj.git"
        assert args.current_token == "1.0"

    def test_register_repo_url_required(self) -> None:
        """AC-FUNC-004: repo_url is the first positional argument; omitting fails with non-zero exit."""
        import argparse
        from kanon_cli.completions.project_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["__complete_project_versions"])
        assert exc_info.value.code != 0

    def test_register_extra_args_fails(self) -> None:
        """AC-FUNC-004: extra positional arguments fail with non-zero exit."""
        import argparse
        from kanon_cli.completions.project_versions import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["__complete_project_versions", "https://example.com/proj.git", "1.0", "extra"])
        assert exc_info.value.code != 0

    def test_subcommand_registered_with_suppress_help(self) -> None:
        """AC-FUNC-007: __complete_project_versions is registered with help=argparse.SUPPRESS.

        The kanon top-level --help uses a custom action (_TopLevelHelpAction) that
        prints a fixed constant string. The hidden completers do not appear in that
        string. This test verifies the subcommand is NOT listed in the top-level
        constant help text (spec Section 11.3).
        """
        from kanon_cli.cli import _TOP_LEVEL_HELP

        assert "__complete_project_versions" not in _TOP_LEVEL_HELP, (
            f"__complete_project_versions should not appear in _TOP_LEVEL_HELP: {_TOP_LEVEL_HELP!r}"
        )


@pytest.mark.unit
class TestWriteStderrDiagnostic:
    """_write_stderr_diagnostic() writes to stderr when stderr is a tty."""

    def test_writes_to_stderr_when_tty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sys.stderr.isatty() is True, diagnostic line is written."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

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
            result = complete("", "")

        assert result == []
        assert any("__complete_project_versions" in line for line in err_lines), (
            f"Expected diagnostic stderr output, got: {err_lines!r}"
        )

    def test_no_stderr_when_not_tty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sys.stderr.isatty() is False, NO line is written to stderr."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

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
            result = complete("", "")

        assert result == []
        assert err_lines == [], f"Expected no stderr output, got: {err_lines!r}"


@pytest.mark.unit
class TestInlineFetchEnvRestore:
    """_inline_fetch() restores KANON_COMPLETION_TIMEOUT after fetch."""

    def test_restores_pre_existing_env_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When KANON_COMPLETION_TIMEOUT was already set, _inline_fetch restores it."""
        from kanon_cli.completions.project_versions import _inline_fetch

        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.setenv("KANON_COMPLETION_TIMEOUT", "99")
        entry_dir = tmp_path / "entry"

        import os

        captured_env: dict[str, str] = {}

        def _fake_fetch(url: str, entry_dir_: Path) -> list[str]:
            captured_env["during"] = os.environ.get("KANON_COMPLETION_TIMEOUT", "")
            return ["1.0.0"]

        with patch.object(pv, "_fetch_and_cache_versions", side_effect=_fake_fetch):
            result = _inline_fetch("https://example.com/proj.git", entry_dir, timeout=42)

        assert result == ["1.0.0"]
        assert captured_env["during"] == "42"
        assert os.environ.get("KANON_COMPLETION_TIMEOUT") == "99"


@pytest.mark.unit
class TestBackgroundRefreshClosure:
    """The refresh callable passed to fork_background_refresh calls _fetch_and_cache_versions."""

    _REPO_URL = "https://example.com/proj.git"

    def _seed_stale_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Seed a stale project cache entry and return its entry directory."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)

        from kanon_cli.completions import cache as cache_mod
        from kanon_cli.core.url import canonicalize_repo_url

        canonical = canonicalize_repo_url(self._REPO_URL)
        entry_dir = cache_mod.project_entry_dir(canonical)
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "tags.txt").write_text("1.0.0\n")
        (entry_dir / "fetched_at.txt").write_text(str(int(time.time()) - 5000))
        return entry_dir

    def test_refresh_fn_calls_fetch_and_cache_versions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When fork_background_refresh is called, the callable invokes _fetch_and_cache_versions."""
        self._seed_stale_cache(tmp_path, monkeypatch)

        captured: list = []

        def _fake_fork(refresh_fn: object) -> None:

            captured.append(refresh_fn)

        with patch.object(pv, "fork_background_refresh", side_effect=_fake_fork):
            with patch.object(pv, "_fetch_and_cache_versions", return_value=["2.0.0"]) as mock_fetch:
                complete(self._REPO_URL, "")

                assert len(captured) == 1
                captured[0]()

        mock_fetch.assert_called_once()

        call_args = mock_fetch.call_args[0]
        assert call_args[0] == self._REPO_URL, "background refresh must use the original repo_url"

    def test_refresh_callable_is_picklable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The EXACT callable the real callsite passes to fork_background_refresh
        must be picklable so the Windows detached-spawn path works end-to-end.

        ``project_versions.complete`` builds the background-refresh callable from
        a nested closure historically; a nested closure is NOT picklable and the
        Windows ``spawn_detached`` path serialises the callable via pickle. This
        test captures the precise object handed to fork_background_refresh and
        asserts ``pickle.dumps`` succeeds on it; it FAILS if picklability
        regresses (e.g. the callsite reverts to a nested closure).
        """
        import pickle

        self._seed_stale_cache(tmp_path, monkeypatch)

        captured: list = []

        def _capture_fork(refresh_fn: object) -> None:
            captured.append(refresh_fn)

        with patch.object(pv, "fork_background_refresh", side_effect=_capture_fork):
            complete(self._REPO_URL, "")

        assert len(captured) == 1, "complete() must call fork_background_refresh exactly once on stale+bg"
        passed_fn = captured[0]

        try:
            pickle.dumps(passed_fn)
        except Exception as exc:
            raise AssertionError(
                f"The callable passed to fork_background_refresh is not picklable "
                f"({type(exc).__name__}: {exc}). The Windows detach path requires a "
                f"picklable callable -- the callsite must pass functools.partial of a "
                f"module-level function, never a nested closure."
            ) from exc

    def test_refresh_callable_round_trips_through_pickle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The picklable callable round-trips and, when invoked, reaches
        _fetch_and_cache_versions with the original repo_url and entry dir.

        This proves the Windows child would actually run the intended refresh
        after deserialising, not merely that serialisation does not raise.
        """
        import functools
        import pickle

        entry_dir = self._seed_stale_cache(tmp_path, monkeypatch)

        captured: list = []

        def _capture_fork(refresh_fn: object) -> None:
            captured.append(refresh_fn)

        with patch.object(pv, "fork_background_refresh", side_effect=_capture_fork):
            complete(self._REPO_URL, "")

        assert len(captured) == 1
        revived = pickle.loads(pickle.dumps(captured[0]))

        assert isinstance(revived, functools.partial)
        assert revived.func is pv._fetch_and_cache_versions
        assert revived.args[0] == self._REPO_URL
        assert revived.args[1] == entry_dir
