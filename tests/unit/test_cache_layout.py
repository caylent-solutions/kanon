"""Unit tests for kanon_cli.completions.cache -- AC-TEST-001."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from kanon_cli.completions.cache import (
    cache_dir,
    catalog_entry_dir,
    log_completion_error,
    project_entry_dir,
    read_entries,
    read_epoch,
    write_entries,
    write_epoch,
)
from kanon_cli.constants import (
    KANON_COMPLETION_LOG_ENV,
    KANON_HOME_CACHE_SUBDIR,
    KANON_HOME_DIR_NAME,
    KANON_HOME_ENV_VAR,
)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove cache-related env vars so tests see a clean environment."""
    monkeypatch.delenv("KANON_HOME", raising=False)
    monkeypatch.delenv("KANON_COMPLETION_LOG", raising=False)


@pytest.fixture()
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KANON_HOME at a fresh tmp dir and return the resolved cache dir.

    The cache lives at <KANON_HOME>/cache, so the returned path is
    ``tmp_path / "cache"`` -- the exact value ``cache_dir()`` resolves to under
    the configured KANON_HOME.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    return cache_dir()


@pytest.mark.unit
class TestCacheDirPrecedence:
    """cache_dir() resolves under the shared KANON_HOME root (<KANON_HOME>/cache).

    The old per-user KANON_CACHE_DIR override and its XDG_CACHE_HOME fallback are
    removed; the cache now always lives under KANON_HOME (env > default ~/.kanon-home).
    """

    def test_cache_dir_is_kanon_home_cache_subdir_when_env_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With KANON_HOME set, the cache is <KANON_HOME>/cache."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        assert cache_dir() == tmp_path / KANON_HOME_CACHE_SUBDIR

    def test_cache_dir_ignores_xdg_cache_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """XDG_CACHE_HOME no longer influences the cache location."""
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg_should_be_ignored"))
        assert cache_dir() == tmp_path / KANON_HOME_CACHE_SUBDIR

    def test_cache_dir_default_is_under_home_kanon_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With KANON_HOME unset, the cache defaults to $HOME/.kanon-home/cache (env-derived)."""
        monkeypatch.delenv("KANON_HOME", raising=False)
        expected = Path.home() / KANON_HOME_DIR_NAME / KANON_HOME_CACHE_SUBDIR
        assert cache_dir() == expected

    def test_cache_dir_empty_home_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty KANON_HOME value resolves to the default $HOME/.kanon-home/cache."""
        monkeypatch.setenv("KANON_HOME", "")
        expected = Path.home() / KANON_HOME_DIR_NAME / KANON_HOME_CACHE_SUBDIR
        assert cache_dir() == expected


@pytest.mark.unit
class TestCatalogEntryDir:
    def test_returns_path_under_catalogs(self, tmp_cache: Path) -> None:
        d = catalog_entry_dir("https://example.git", "main")
        assert d.parts[-2] == "catalogs"
        assert d.parent.parent == tmp_cache

    def test_sha_is_of_url_at_ref(self, tmp_cache: Path) -> None:
        url = "https://example.git"
        ref = "main"
        expected_sha = _sha256(f"{url}@{ref}")
        d = catalog_entry_dir(url, ref)
        assert d.name == expected_sha

    def test_deterministic_across_calls(self, tmp_cache: Path) -> None:
        d1 = catalog_entry_dir("https://x.git", "v1")
        d2 = catalog_entry_dir("https://x.git", "v1")
        assert d1 == d2

    def test_different_refs_produce_different_dirs(self, tmp_cache: Path) -> None:
        d1 = catalog_entry_dir("https://x.git", "main")
        d2 = catalog_entry_dir("https://x.git", "develop")
        assert d1 != d2

    def test_different_urls_produce_different_dirs(self, tmp_cache: Path) -> None:
        d1 = catalog_entry_dir("https://a.git", "main")
        d2 = catalog_entry_dir("https://b.git", "main")
        assert d1 != d2


@pytest.mark.unit
class TestProjectEntryDir:
    def test_returns_path_under_projects(self, tmp_cache: Path) -> None:
        d = project_entry_dir("https://example.git")
        assert d.parts[-2] == "projects"
        assert d.parent.parent == tmp_cache

    def test_sha_is_of_repo_url(self, tmp_cache: Path) -> None:
        url = "https://example.git"
        expected_sha = _sha256(url)
        d = project_entry_dir(url)
        assert d.name == expected_sha

    def test_deterministic_across_calls(self, tmp_cache: Path) -> None:
        d1 = project_entry_dir("https://x.git")
        d2 = project_entry_dir("https://x.git")
        assert d1 == d2

    def test_different_urls_produce_different_dirs(self, tmp_cache: Path) -> None:
        d1 = project_entry_dir("https://a.git")
        d2 = project_entry_dir("https://b.git")
        assert d1 != d2


@pytest.mark.unit
class TestFileModes:
    def test_write_entries_creates_dir_mode_0700(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, ["a"])
        stat = os.stat(target.parent)
        assert stat.st_mode & 0o777 == 0o700

    def test_write_entries_creates_file_mode_0600(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, ["a"])
        stat = os.stat(target)
        assert stat.st_mode & 0o777 == 0o600

    def test_write_epoch_creates_file_mode_0600(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "fetched_at.txt"
        write_epoch(target, 1000)
        stat = os.stat(target)
        assert stat.st_mode & 0o777 == 0o600

    @pytest.mark.parametrize("entries", [["foo", "bar", "baz"], ["single"], []])
    def test_mode_0700_for_various_payloads(self, tmp_cache: Path, entries: list[str]) -> None:
        target = catalog_entry_dir("https://parametrize.git", "v1") / "index.txt"
        write_entries(target, entries)
        stat = os.stat(target.parent)
        assert stat.st_mode & 0o777 == 0o700

    def test_write_entries_deep_tree_all_dirs_mode_0700(self, tmp_cache: Path) -> None:
        """All directories created by write_entries have mode 0700."""
        target = catalog_entry_dir("https://deep.git", "main") / "index.txt"
        write_entries(target, ["x"])

        path = target.parent
        while path != tmp_cache.parent:
            if path == tmp_cache:
                break
            stat = os.stat(path)
            assert stat.st_mode & 0o777 == 0o700, f"{path} has mode {oct(stat.st_mode & 0o777)}"
            path = path.parent


@pytest.mark.unit
class TestReadWriteEntries:
    def test_roundtrip(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, ["foo", "bar"])
        assert read_entries(target) == ["foo", "bar"]

    def test_missing_file_returns_empty_list(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "nonexistent.txt"
        assert read_entries(target) == []

    def test_strips_trailing_newlines(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, ["alpha", "beta"])
        raw = target.read_text()
        assert raw.endswith("\n")
        result = read_entries(target)
        assert result == ["alpha", "beta"]

    def test_skips_blank_lines(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("a\n\nb\n\n")
        os.chmod(target, 0o600)
        result = read_entries(target)
        assert result == ["a", "b"]

    def test_empty_entries_produces_empty_file(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "index.txt"
        write_entries(target, [])
        assert read_entries(target) == []

    def test_creates_parent_dirs(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://new.git", "main") / "tags.txt"
        assert not target.parent.exists()
        write_entries(target, ["1.0.0"])
        assert target.parent.exists()


@pytest.mark.unit
class TestReadWriteEpoch:
    def test_roundtrip(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "fetched_at.txt"
        write_epoch(target, 12345)
        assert read_epoch(target) == 12345

    def test_missing_returns_none(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "fetched_at.txt"
        assert read_epoch(target) is None

    def test_file_mode_0600(self, tmp_cache: Path) -> None:
        target = catalog_entry_dir("https://x.git", "main") / "fetched_at.txt"
        write_epoch(target, 999)
        assert os.stat(target).st_mode & 0o777 == 0o600

    @pytest.mark.parametrize("epoch", [0, 1, 9999999999])
    def test_various_epoch_values(self, tmp_cache: Path, epoch: int) -> None:
        target = catalog_entry_dir("https://e.git", "main") / "accessed_at.txt"
        write_epoch(target, epoch)
        assert read_epoch(target) == epoch


@pytest.mark.unit
class TestLogCompletionError:
    def test_writes_one_line(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_path = tmp_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("__complete_test", ValueError("oops"))
        lines = [ln for ln in log_path.read_text().splitlines() if ln]
        assert len(lines) == 1

    def test_line_format(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_path = tmp_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("__complete_catalog_entries", RuntimeError("boom"))
        line = log_path.read_text().strip()

        pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z "
            r"__complete_catalog_entries RuntimeError: boom$"
        )
        assert pattern.match(line), f"Line did not match pattern: {line!r}"

    def test_appends_multiple_calls(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_path = tmp_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("c1", ValueError("a"))
        log_completion_error("c2", TypeError("b"))
        lines = [ln for ln in log_path.read_text().splitlines() if ln]
        assert len(lines) == 2

    def test_log_file_mode_0600(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_path = tmp_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("__complete_test", Exception("x"))
        assert os.stat(log_path).st_mode & 0o777 == 0o600

    def test_default_log_path_under_cache_dir(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When KANON_COMPLETION_LOG is unset, log goes to <KANON_HOME>/cache/completion-errors.log."""
        monkeypatch.delenv("KANON_COMPLETION_LOG", raising=False)
        log_completion_error("__complete_test", ValueError("x"))
        default_log = tmp_cache / "completion-errors.log"
        assert default_log.exists()

    def test_includes_error_class_and_message(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_path = tmp_cache / "completion-errors.log"
        monkeypatch.setenv("KANON_COMPLETION_LOG", str(log_path))
        log_completion_error("__complete_versions", KeyError("missing_key"))
        line = log_path.read_text().strip()
        assert "KeyError" in line
        assert "missing_key" in line


@pytest.mark.unit
class TestCacheConstants:
    def test_kanon_home_env_var_value(self) -> None:
        assert KANON_HOME_ENV_VAR == "KANON_HOME"

    def test_kanon_home_dir_name_default(self) -> None:
        assert KANON_HOME_DIR_NAME == ".kanon-home"

    def test_kanon_home_cache_subdir_value(self) -> None:
        assert KANON_HOME_CACHE_SUBDIR == "cache"

    def test_kanon_completion_log_env_value(self) -> None:
        assert KANON_COMPLETION_LOG_ENV == "KANON_COMPLETION_LOG"

    def test_completion_cache_ttl(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_CACHE_TTL

        assert KANON_COMPLETION_CACHE_TTL == 300

    def test_completion_timeout(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_TIMEOUT

        assert KANON_COMPLETION_TIMEOUT == 2

    def test_completion_refresh_bg(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_REFRESH_BG

        assert KANON_COMPLETION_REFRESH_BG == 1

    def test_completion_enabled(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_ENABLED

        assert KANON_COMPLETION_ENABLED == 1

    def test_accessed_at_coalesce_sec(self) -> None:
        from kanon_cli.constants import KANON_ACCESSED_AT_COALESCE_SEC

        assert KANON_ACCESSED_AT_COALESCE_SEC == 60


@pytest.mark.unit
class TestOriginTxt:
    def test_can_write_origin_txt_alongside_index(self, tmp_cache: Path) -> None:
        d = catalog_entry_dir("https://x.git", "main")
        write_entries(d / "index.txt", ["entry1"])
        write_entries(d / "origin.txt", ["https://x.git@main"])
        assert (d / "index.txt").exists()
        assert (d / "origin.txt").exists()
        assert read_entries(d / "origin.txt") == ["https://x.git@main"]

    def test_can_write_origin_txt_alongside_tags(self, tmp_cache: Path) -> None:
        d = project_entry_dir("https://proj.git")
        write_entries(d / "tags.txt", ["1.0.0"])
        write_entries(d / "origin.txt", ["https://proj.git"])
        assert read_entries(d / "origin.txt") == ["https://proj.git"]
