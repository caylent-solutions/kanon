"""Unit tests for kanon_cli.completions.midtoken -- resolve_entry_to_repo_url.

Covers:
- Known catalog entry -> returns the catalog source URL (AC-FUNC-006 happy path).
- Unknown entry -> raises EntryNotFoundError (AC-FUNC-006 failure path).
- Malformed cache (index.txt unreadable / catalog source parse error) -> raises
  MidtokenCacheError (AC-FUNC-006 failure path; subcommand converts to empty
  stdout + log).
- KANON_COMPLETION_ENABLED=0 -> returns empty string immediately without
  touching the cache or the catalog source env var (AC-FUNC-007).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kanon_cli.completions.midtoken import (
    EntryNotFoundError,
    MidtokenCacheError,
    resolve_entry_to_repo_url,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_catalog_cache(
    tmp_path: Path,
    catalog_url: str,
    catalog_ref: str,
    entry_names: list[str],
) -> None:
    """Write a minimal catalog cache entry under tmp_path.

    Creates:
        catalogs/<sha>/index.txt   -- one name per line
        catalogs/<sha>/origin.txt  -- <url>@<ref>

    The SHA is derived the same way as cache.catalog_entry_dir() so that
    resolve_entry_to_repo_url can locate it.

    Args:
        tmp_path: The root cache directory to use (set as KANON_CACHE_DIR).
        catalog_url: The catalog source git URL.
        catalog_ref: The catalog source git ref.
        entry_names: List of catalog entry names to write to index.txt.
    """
    import hashlib

    key = f"{catalog_url}@{catalog_ref}"
    sha = hashlib.sha256(key.encode()).hexdigest()
    sha_dir = tmp_path / "catalogs" / sha
    sha_dir.mkdir(parents=True)
    (sha_dir / "index.txt").write_text("\n".join(entry_names) + "\n")
    (sha_dir / "origin.txt").write_text(f"{catalog_url}@{catalog_ref}\n")


# ---------------------------------------------------------------------------
# KANON_COMPLETION_ENABLED=0
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name",
    [
        "foo",
        "bar",
        "unknown-entry",
        "",
    ],
)
def test_resolve_disabled_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entry_name: str,
) -> None:
    """KANON_COMPLETION_ENABLED=0 -> resolve returns empty string immediately.

    The function must NOT inspect the cache or KANON_CATALOG_SOURCE when
    completion is disabled (AC-FUNC-007).
    """
    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "0")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    # Do NOT set KANON_CATALOG_SOURCE -- if the code reads it, it would fail.
    monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

    result = resolve_entry_to_repo_url(entry_name)
    assert result == ""


# ---------------------------------------------------------------------------
# Known entry -> returns catalog URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_known_entry_returns_catalog_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """resolve_entry_to_repo_url('foo') returns the catalog URL when 'foo' is cached."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo", "bar", "baz"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    result = resolve_entry_to_repo_url("foo")
    assert result == catalog_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name",
    ["foo", "bar", "baz"],
)
def test_resolve_each_known_entry_returns_same_catalog_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entry_name: str,
) -> None:
    """Every known entry in the same catalog maps to the same catalog URL."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo", "bar", "baz"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    result = resolve_entry_to_repo_url(entry_name)
    assert result == catalog_url


# ---------------------------------------------------------------------------
# Unknown entry -> EntryNotFoundError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_unknown_entry_raises_entry_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """resolve_entry_to_repo_url('unknown') raises EntryNotFoundError."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo", "bar"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    with pytest.raises(EntryNotFoundError) as exc_info:
        resolve_entry_to_repo_url("unknown")
    assert "unknown" in str(exc_info.value)


@pytest.mark.unit
def test_resolve_empty_name_raises_entry_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """resolve_entry_to_repo_url('') raises EntryNotFoundError (empty name -- AC-FUNC-005)."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    with pytest.raises(EntryNotFoundError):
        resolve_entry_to_repo_url("")


# ---------------------------------------------------------------------------
# Malformed cache -> MidtokenCacheError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_missing_catalog_source_raises_midtoken_cache_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Absent KANON_CATALOG_SOURCE raises MidtokenCacheError."""
    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

    with pytest.raises(MidtokenCacheError):
        resolve_entry_to_repo_url("foo")


@pytest.mark.unit
def test_resolve_malformed_catalog_source_raises_midtoken_cache_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Malformed KANON_CATALOG_SOURCE (no '@') raises MidtokenCacheError."""
    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", "not-a-valid-catalog-source")

    with pytest.raises(MidtokenCacheError):
        resolve_entry_to_repo_url("foo")


@pytest.mark.unit
def test_resolve_empty_cache_index_raises_entry_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Empty index.txt (cache miss / empty catalog) raises EntryNotFoundError for any entry."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, [])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    with pytest.raises(EntryNotFoundError):
        resolve_entry_to_repo_url("foo")


@pytest.mark.unit
def test_resolve_no_cache_dir_raises_midtoken_cache_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When catalogs/ dir does not exist, MidtokenCacheError is raised (no catalog cached)."""
    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    # Do NOT create any cache -- cache directory is empty.
    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    with pytest.raises(MidtokenCacheError):
        resolve_entry_to_repo_url("foo")


# ---------------------------------------------------------------------------
# _handle: CLI entry point tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handle_success_prints_url_to_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """_handle prints the resolved URL to stdout and returns 0 on success."""
    import argparse

    from kanon_cli.completions.midtoken import _handle

    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    args = argparse.Namespace(entry_name="foo")
    result = _handle(args)
    assert result == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == catalog_url


@pytest.mark.unit
def test_handle_entry_not_found_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """_handle returns 1 and prints nothing to stdout when entry is not found."""
    import argparse

    from kanon_cli.completions.midtoken import _handle

    catalog_url = "https://example.com/catalog.git"
    catalog_ref = "main"
    _make_catalog_cache(tmp_path, catalog_url, catalog_ref, ["foo"])

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "1")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_CATALOG_SOURCE", f"{catalog_url}@{catalog_ref}")

    args = argparse.Namespace(entry_name="unknown")
    result = _handle(args)
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""


@pytest.mark.unit
def test_handle_disabled_returns_0_empty_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """_handle returns 0 with empty stdout when KANON_COMPLETION_ENABLED=0."""
    import argparse

    from kanon_cli.completions.midtoken import _handle

    monkeypatch.setenv("KANON_COMPLETION_ENABLED", "0")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

    args = argparse.Namespace(entry_name="foo")
    result = _handle(args)
    assert result == 0
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# _write_stderr_diagnostic: tty path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_stderr_diagnostic_writes_to_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_write_stderr_diagnostic writes to stderr when stderr is a tty."""
    import io
    import sys as _sys

    from kanon_cli.completions.midtoken import _write_stderr_diagnostic

    # Replace stderr with a StringIO subclass that reports isatty() == True.
    class _TtyStringIO(io.StringIO):
        def isatty(self) -> bool:
            return True

    tty_stderr = _TtyStringIO()
    monkeypatch.setattr(_sys, "stderr", tty_stderr)

    exc = EntryNotFoundError("my-entry", "https://example.com/catalog.git@main")
    _write_stderr_diagnostic(exc)

    written = tty_stderr.getvalue()
    assert "__resolve_entry_to_repo_url" in written
    assert "EntryNotFoundError" in written
    assert "my-entry" in written
