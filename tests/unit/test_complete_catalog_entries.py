"""Unit tests for kanon_cli.completions.catalog_entries -- AC-TEST-001.

Covers: happy path, empty source, malformed source, timeout simulation,
cache-hit, cache-miss, cache-stale, network-error, sanitization,
KANON_COMPLETION_ENABLED=0.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.completions.catalog_entries as ce
from kanon_cli.completions.catalog_entries import (
    _build_index,
    _clone_manifest_repo,
    _fetch_and_cache,
    _handle,
    _inline_fetch,
    _is_safe_entry,
    complete,
)


def _make_xml(name: str) -> str:
    """Return a minimal valid *-marketplace.xml content for catalog name *name*."""
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


@pytest.mark.unit
class TestIsSafeEntry:
    """_is_safe_entry() rejects entries with shell-special chars or controls."""

    @pytest.mark.parametrize(
        "entry",
        [
            "foo",
            "foo-bar",
            "foo_bar",
            "foo.bar",
            "foo123",
            "F",
            "a" * 128,
        ],
        ids=[
            "simple",
            "hyphen",
            "underscore",
            "dot",
            "alphanumeric",
            "single-char",
            "128-chars",
        ],
    )
    def test_safe_entries_pass(self, entry: str) -> None:
        assert _is_safe_entry(entry) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "",
            "foo bar",
            "foo\tbar",
            "foo\nbar",
            "foo\rbar",
            "foo;bar",
            "foo|bar",
            "foo&bar",
            "foo$bar",
            "foo`bar",
            "a" * 129,
        ],
        ids=[
            "empty",
            "space",
            "tab",
            "newline",
            "carriage-return",
            "semicolon",
            "pipe",
            "ampersand",
            "dollar",
            "backtick",
            "too-long",
        ],
    )
    def test_unsafe_entries_rejected(self, entry: str) -> None:
        assert _is_safe_entry(entry) is False


@pytest.mark.unit
class TestBuildIndex:
    """_build_index() parses *-marketplace.xml files and returns sorted names."""

    def test_empty_repo_returns_empty(self, tmp_path: Path) -> None:
        """No *-marketplace.xml files produces an empty list."""
        result = _build_index(tmp_path)
        assert result == []

    def test_single_file_returns_name(self, tmp_path: Path) -> None:
        """One XML file produces one entry."""
        specs = tmp_path / "repo-specs" / "sub"
        specs.mkdir(parents=True)
        (specs / "foo-marketplace.xml").write_text(_make_xml("foo"))
        result = _build_index(tmp_path)
        assert result == ["foo"]

    def test_multiple_files_sorted(self, tmp_path: Path) -> None:
        """Multiple XML files are returned in sorted order."""
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        (specs / "baz-marketplace.xml").write_text(_make_xml("baz"))
        (specs / "bar-marketplace.xml").write_text(_make_xml("bar"))
        (specs / "foo-marketplace.xml").write_text(_make_xml("foo"))
        result = _build_index(tmp_path)
        assert result == ["bar", "baz", "foo"]

    def test_malformed_xml_skipped(self, tmp_path: Path) -> None:
        """A malformed XML file is silently skipped (logs an error but still returns others)."""
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        (specs / "good-marketplace.xml").write_text(_make_xml("good"))
        (specs / "bad-marketplace.xml").write_text("this is not xml <<>>")
        result = _build_index(tmp_path)
        assert result == ["good"]

    def test_unsafe_names_filtered(self, tmp_path: Path) -> None:
        """Names that fail _is_safe_entry are excluded from output."""
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        (specs / "ok-marketplace.xml").write_text(_make_xml("ok"))
        (specs / "bad-marketplace.xml").write_text(_make_xml("bad name"))
        result = _build_index(tmp_path)
        assert result == ["ok"]


@pytest.mark.unit
class TestFetchAndCache:
    """_fetch_and_cache() clones manifest repo, builds index, writes cache."""

    def test_writes_cache_and_returns_names(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On success, cache index.txt is written and the name list returned."""

        cache_entry_dir = tmp_path / "cache_entry"
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def _fake_clone(url: str, ref: str, dest: Path) -> Path:
            specs = dest / "repo-specs"
            specs.mkdir(parents=True)
            (specs / "alpha-marketplace.xml").write_text(_make_xml("alpha"))
            (specs / "beta-marketplace.xml").write_text(_make_xml("beta"))
            return dest

        with patch.object(ce, "_clone_manifest_repo", side_effect=_fake_clone):
            result = _fetch_and_cache("https://example.com/repo.git", "main", cache_entry_dir)

        assert result == ["alpha", "beta"]
        index_path = cache_entry_dir / "index.txt"
        assert index_path.exists()
        assert index_path.read_text().splitlines() == ["alpha", "beta"]

    def test_no_repo_specs_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When repo-specs/ directory is absent, empty list is returned and index.txt is empty."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        cache_entry_dir = tmp_path / "cache_entry"
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "_clone_manifest_repo", return_value=repo_dir):
            result = _fetch_and_cache("https://example.com/repo.git", "main", cache_entry_dir)

        assert result == []
        index_path = cache_entry_dir / "index.txt"
        assert index_path.exists()

    def test_clone_failure_propagates(self, tmp_path: Path) -> None:
        """When _clone_manifest_repo raises, the exception propagates."""
        cache_entry_dir = tmp_path / "cache_entry"

        with patch.object(ce, "_clone_manifest_repo", side_effect=RuntimeError("clone failed")):
            with pytest.raises(RuntimeError, match="clone failed"):
                _fetch_and_cache("https://example.com/repo.git", "main", cache_entry_dir)


@pytest.mark.unit
class TestCloneManifestRepo:
    """_clone_manifest_repo() shells out to git clone and returns the cloned path."""

    def test_success_returns_temp_dir(self, tmp_path: Path) -> None:
        """On git clone success (returncode 0), the temp dir path is returned."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = _clone_manifest_repo("https://example.com/repo.git", "main", tmp_path)

        assert result == tmp_path
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert "clone" in cmd

    def test_failure_raises_runtime_error(self, tmp_path: Path) -> None:
        """When git clone returns non-zero, RuntimeError is raised with stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: repository not found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="git clone failed"):
                _clone_manifest_repo("https://example.com/repo.git", "main", tmp_path)

    def test_timeout_raises_timeout_error(self, tmp_path: Path) -> None:
        """When subprocess.run raises TimeoutExpired, TimeoutError is re-raised."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=2),
        ):
            with pytest.raises(TimeoutError):
                _clone_manifest_repo("https://example.com/repo.git", "main", tmp_path)


@pytest.mark.unit
class TestInlineFetch:
    """_inline_fetch() runs _fetch_and_cache with a timeout, returning empty list on failure."""

    def test_success_returns_names(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On successful fetch, the name list is returned."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        cache_entry_dir = tmp_path / "entry"
        expected = ["alpha", "beta"]

        with patch.object(ce, "_fetch_and_cache", return_value=expected):
            result = _inline_fetch("https://example.com/repo.git", "main", cache_entry_dir, timeout=5)

        assert result == expected

    def test_timeout_returns_empty_and_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On TimeoutError, returns empty list and logs the error."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        cache_entry_dir = tmp_path / "entry"

        with patch.object(ce, "_fetch_and_cache", side_effect=TimeoutError("timed out")):
            with patch.object(ce, "log_completion_error") as mock_log:
                result = _inline_fetch("https://example.com/repo.git", "main", cache_entry_dir, timeout=2)

        assert result == []
        mock_log.assert_called_once()

    def test_exception_returns_empty_and_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On any exception from _fetch_and_cache, returns empty list and logs."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        cache_entry_dir = tmp_path / "entry"

        with patch.object(ce, "_fetch_and_cache", side_effect=RuntimeError("network error")):
            with patch.object(ce, "log_completion_error") as mock_log:
                result = _inline_fetch("https://example.com/repo.git", "main", cache_entry_dir, timeout=2)

        assert result == []
        mock_log.assert_called_once()


@pytest.mark.unit
class TestComplete:
    """complete() is the public API -- tests cache-hit, cache-miss, stale, disabled, errors."""

    def _env_setup(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Configure env vars for a clean test environment."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_COMPLETION_ENABLED", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_CACHE_TTL", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_TIMEOUT", raising=False)
        monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    def test_disabled_returns_empty_no_cache_touch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ENABLED=0 returns empty list without touching the cache (AC-FUNC-006)."""
        self._env_setup(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_ENABLED", "0")

        with patch.object(ce, "_inline_fetch") as mock_fetch:
            with patch("kanon_cli.completions.cache.log_completion_error") as mock_log:
                result = complete("")

        assert result == []
        mock_fetch.assert_not_called()
        mock_log.assert_not_called()

    def test_cache_hit_returns_filtered_entries_no_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache hit: returns entries filtered by prefix; no git calls made (AC-FUNC-001, AC-FUNC-002, AC-FUNC-003)."""
        self._env_setup(monkeypatch, tmp_path)

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        index = entry_dir / "index.txt"
        index.write_text("foo\nbar\nbaz\n")
        fetched = entry_dir / "fetched_at.txt"

        fetched.write_text(str(int(time.time())))

        with patch.object(ce, "_inline_fetch") as mock_fetch:
            result = complete("")

        mock_fetch.assert_not_called()
        assert sorted(result) == ["bar", "baz", "foo"]

    def test_cache_hit_prefix_filter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache hit with prefix 'f' returns only entries starting with 'f' (AC-FUNC-002)."""
        self._env_setup(monkeypatch, tmp_path)

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        index = entry_dir / "index.txt"
        index.write_text("foo\nbar\nbaz\nfizz\n")
        fetched = entry_dir / "fetched_at.txt"
        fetched.write_text(str(int(time.time())))

        with patch.object(ce, "_inline_fetch") as mock_fetch:
            result = complete("f")

        mock_fetch.assert_not_called()
        assert sorted(result) == ["fizz", "foo"]

    def test_cache_miss_calls_inline_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache miss: _inline_fetch is called and result returned (AC-FUNC-005)."""
        self._env_setup(monkeypatch, tmp_path)

        expected = ["alpha", "beta"]
        with patch.object(ce, "_inline_fetch", return_value=expected) as mock_fetch:
            result = complete("")

        mock_fetch.assert_called_once()
        assert result == expected

    def test_cache_stale_returns_stale_and_forks_bg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache stale: stale contents returned; background refresh process spawned (AC-FUNC-004)."""
        self._env_setup(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        index = entry_dir / "index.txt"
        index.write_text("stale-entry\n")
        fetched = entry_dir / "fetched_at.txt"

        fetched.write_text(str(int(time.time()) - 5000))

        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with patch.object(ce, "_inline_fetch") as mock_fetch:
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                result = complete("")

        assert result == ["stale-entry"]

        mock_fetch.assert_not_called()

        mock_popen.assert_called_once()

    def test_cache_stale_bg_disabled_calls_inline_fetch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache stale with KANON_COMPLETION_REFRESH_BG=0: inline fetch used (AC-FUNC-005)."""
        self._env_setup(monkeypatch, tmp_path)
        monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        index = entry_dir / "index.txt"
        index.write_text("stale-entry\n")
        fetched = entry_dir / "fetched_at.txt"
        fetched.write_text(str(int(time.time()) - 5000))

        with patch.object(ce, "_inline_fetch", return_value=["fresh"]) as mock_fetch:
            result = complete("")

        mock_fetch.assert_called_once()
        assert result == ["fresh"]

    def test_network_error_empty_stdout_logs_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Network error: empty result returned when inline fetch returns empty (AC-FUNC-008)."""
        self._env_setup(monkeypatch, tmp_path)

        with patch.object(ce, "_inline_fetch", return_value=[]):
            result = complete("")

        assert result == []

    def test_missing_catalog_source_returns_empty_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing KANON_CATALOG_SOURCES: empty result and error logged (AC-FUNC-008)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "log_completion_error") as mock_log:
            result = complete("")

        assert result == []
        mock_log.assert_called_once()

    @pytest.mark.parametrize("prefix", ["", "f", "bar", "zzz"])
    def test_prefix_filter_case_sensitive(self, prefix: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Prefix matching is case-sensitive (AC-FUNC-002)."""
        self._env_setup(monkeypatch, tmp_path)

        from kanon_cli.completions import cache

        entry_dir = cache.catalog_entry_dir("https://example.com/repo.git", "main")
        entry_dir.mkdir(parents=True)
        index = entry_dir / "index.txt"
        index.write_text("foo\nFoo\nbar\nBAR\n")
        fetched = entry_dir / "fetched_at.txt"
        fetched.write_text(str(int(time.time())))

        result = complete(prefix)
        for name in result:
            assert name.startswith(prefix), f"{name!r} does not start with {prefix!r}"


@pytest.mark.unit
class TestHandle:
    """_handle() is the argparse entry point; tests dispatch and exit-code contract."""

    def test_handle_prints_results_and_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """_handle() prints one name per line and exits 0 on success."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "complete", return_value=["foo", "bar"]):
            args = MagicMock()
            args.current_token = ""
            args.refresh_only = False
            result = _handle(args)

        captured = capsys.readouterr()
        assert "foo\n" in captured.out
        assert "bar\n" in captured.out
        assert result == 0

    def test_handle_empty_result_exits_0_empty_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """_handle() with empty complete() result exits 0 with empty stdout."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "complete", return_value=[]):
            args = MagicMock()
            args.current_token = ""
            args.refresh_only = False
            result = _handle(args)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert result == 0


@pytest.mark.unit
class TestParseCatalogSource:
    """_parse_catalog_source() splits '<url>@<ref>' at the last '@'.

    The implementation lives in kanon_cli.core.catalog and is imported by
    catalog_entries -- tests import from the canonical location.
    """

    def test_valid_source_parsed(self) -> None:
        """Valid source returns (url, ref) tuple."""
        from kanon_cli.core.catalog import _parse_catalog_source

        url, ref = _parse_catalog_source("https://example.com/repo.git@main")
        assert url == "https://example.com/repo.git"
        assert ref == "main"

    def test_no_at_sign_raises_value_error(self) -> None:
        """Source without '@' raises ValueError."""
        from kanon_cli.core.catalog import _parse_catalog_source

        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("https://example.com/repo.git")

    def test_empty_ref_raises_value_error(self) -> None:
        """Source ending with '@' (empty ref) raises ValueError."""
        from kanon_cli.core.catalog import _parse_catalog_source

        with pytest.raises(ValueError, match="[Ee]mpty ref"):
            _parse_catalog_source("https://example.com/repo.git@")

    def test_empty_url_raises_value_error(self) -> None:
        """Source starting with '@' (empty url) raises ValueError."""
        from kanon_cli.core.catalog import _parse_catalog_source

        with pytest.raises(ValueError, match="[Ee]mpty URL"):
            _parse_catalog_source("@main")

    def test_invalid_source_in_complete_returns_empty_and_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """complete() with invalid KANON_CATALOG_SOURCES logs error and returns [] (lines 266-268)."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "no-at-sign-here")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "log_completion_error") as mock_log:
            result = complete("")

        assert result == []
        mock_log.assert_called_once()


@pytest.mark.unit
class TestBuildIndexExceptionHandling:
    """_build_index() only silently skips CatalogMetadataParseError; other exceptions are logged."""

    def test_unexpected_exception_logged_and_skipped(self, tmp_path: Path) -> None:
        """Non-parse exceptions (e.g. PermissionError) are logged via log_completion_error and skipped."""
        specs = tmp_path / "repo-specs"
        specs.mkdir()

        (specs / "perm-marketplace.xml").write_text(_make_xml("perm"))

        with patch.object(ce, "_parse_catalog_metadata", side_effect=PermissionError("denied")):
            with patch.object(ce, "log_completion_error") as mock_log:
                result = _build_index(tmp_path)

        mock_log.assert_called_once()

        assert result == []


@pytest.mark.unit
class TestHandleRefreshOnly:
    """--refresh-only flag causes _handle() to skip stdout printing."""

    def test_refresh_only_skips_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When args.refresh_only is True, _handle() refreshes cache but prints nothing."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "complete", return_value=["foo", "bar"]):
            args = MagicMock()
            args.current_token = ""
            args.refresh_only = True
            result = _handle(args)

        captured = capsys.readouterr()

        assert captured.out == ""
        assert result == 0

    def test_refresh_only_false_prints_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When args.refresh_only is False, _handle() prints results normally."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://example.com/repo.git@main")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with patch.object(ce, "complete", return_value=["foo", "bar"]):
            args = MagicMock()
            args.current_token = ""
            args.refresh_only = False
            result = _handle(args)

        captured = capsys.readouterr()
        assert "foo\n" in captured.out
        assert "bar\n" in captured.out
        assert result == 0


@pytest.mark.unit
class TestInlineFetchTimeoutPassthrough:
    """_inline_fetch() passes the timeout argument to _fetch_and_cache."""

    def test_timeout_passed_to_fetch_and_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_inline_fetch must pass the timeout value via environment to the underlying clone."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        cache_entry_dir = tmp_path / "entry"

        captured_env: dict[str, str] = {}

        def _fake_fetch_and_cache(url: str, ref: str, entry_dir: Path) -> list[str]:
            captured_env["KANON_COMPLETION_TIMEOUT"] = os.environ.get("KANON_COMPLETION_TIMEOUT", "")
            return ["ok"]

        with patch.object(ce, "_fetch_and_cache", side_effect=_fake_fetch_and_cache):
            result = _inline_fetch("https://example.com/repo.git", "main", cache_entry_dir, timeout=42)

        assert result == ["ok"]

        assert captured_env.get("KANON_COMPLETION_TIMEOUT") == "42"

    def test_timeout_restores_pre_existing_env_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When KANON_COMPLETION_TIMEOUT was already set, _inline_fetch restores the original value after fetch."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        monkeypatch.setenv("KANON_COMPLETION_TIMEOUT", "99")
        cache_entry_dir = tmp_path / "entry"

        captured_env: dict[str, str] = {}

        def _fake_fetch_and_cache(url: str, ref: str, entry_dir: Path) -> list[str]:
            captured_env["during"] = os.environ.get("KANON_COMPLETION_TIMEOUT", "")
            return ["ok"]

        with patch.object(ce, "_fetch_and_cache", side_effect=_fake_fetch_and_cache):
            result = _inline_fetch("https://example.com/repo.git", "main", cache_entry_dir, timeout=42)

        assert result == ["ok"]

        assert captured_env["during"] == "42"

        assert os.environ.get("KANON_COMPLETION_TIMEOUT") == "99"


@pytest.mark.unit
class TestStderrTtyDiagnostic:
    """Error paths write a diagnostic line to stderr when stderr is a tty."""

    def test_log_completion_error_writes_to_stderr_when_tty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When sys.stderr.isatty() is True, a diagnostic line is written to stderr."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

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

        assert any("__complete_catalog_entries" in line or "KANON_CATALOG_SOURCES" in line for line in err_lines), (
            f"Expected diagnostic stderr output, got: {err_lines!r}"
        )

    def test_log_completion_error_no_stderr_when_not_tty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sys.stderr.isatty() is False, NO line is written to stderr."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

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
