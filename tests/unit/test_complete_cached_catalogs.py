"""Unit tests for kanon_cli.completions.cached_catalogs -- AC-TEST-001.

Covers: happy path (three origin.txt files), empty catalogs/ directory,
missing KANON_CACHE_DIR entirely, malformed origin.txt (skipped + logged),
prefix filter, KANON_COMPLETION_ENABLED=0 short-circuit.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.completions.cached_catalogs import (
    _handle,
    _read_origin,
    _walk_catalogs,
    complete,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog(cache_dir: Path, sha: str, origin: str) -> Path:
    """Create catalogs/<sha>/origin.txt with the given content."""
    entry = cache_dir / "catalogs" / sha
    entry.mkdir(parents=True, exist_ok=True)
    origin_file = entry / "origin.txt"
    origin_file.write_text(origin)
    return origin_file


# ---------------------------------------------------------------------------
# _read_origin
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadOrigin:
    """_read_origin() reads the first line from origin.txt."""

    def test_valid_origin_returned(self, tmp_path: Path) -> None:
        """A well-formed origin.txt returns the stripped content."""
        f = tmp_path / "origin.txt"
        f.write_text("https://example.com/m.git@main\n")
        result = _read_origin(f)
        assert result == "https://example.com/m.git@main"

    def test_origin_with_no_newline(self, tmp_path: Path) -> None:
        """origin.txt without trailing newline is read correctly."""
        f = tmp_path / "origin.txt"
        f.write_text("https://example.com/m.git@main")
        result = _read_origin(f)
        assert result == "https://example.com/m.git@main"

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        """An empty origin.txt returns None (malformed)."""
        f = tmp_path / "origin.txt"
        f.write_text("")
        result = _read_origin(f)
        assert result is None

    def test_missing_at_sign_returns_none(self, tmp_path: Path) -> None:
        """origin.txt content without '@' returns None (invalid shape)."""
        f = tmp_path / "origin.txt"
        f.write_text("https://example.com/m.git\n")
        result = _read_origin(f)
        assert result is None

    def test_whitespace_only_returns_none(self, tmp_path: Path) -> None:
        """origin.txt with only whitespace returns None (malformed)."""
        f = tmp_path / "origin.txt"
        f.write_text("   \n")
        result = _read_origin(f)
        assert result is None

    def test_ssh_url_with_ref(self, tmp_path: Path) -> None:
        """SSH-format URL with @ref is accepted."""
        f = tmp_path / "origin.txt"
        f.write_text("git@c.example.com:org/m.git@develop\n")
        result = _read_origin(f)
        assert result == "git@c.example.com:org/m.git@develop"


# ---------------------------------------------------------------------------
# _walk_catalogs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkCatalogs:
    """_walk_catalogs() walks catalogs/<sha>/origin.txt files."""

    def test_three_valid_origins_sorted(self, tmp_path: Path) -> None:
        """Three valid origin.txt files return three sorted url@ref strings."""
        _make_catalog(tmp_path, "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path, "sha3", "git@c.example.com:org/m.git@develop\n")
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == [
            "git@c.example.com:org/m.git@develop",
            "https://a.example.com/m.git@main",
            "https://b.example.com/m.git@v1.0.0",
        ]
        assert errors == []

    def test_empty_catalogs_dir_returns_empty(self, tmp_path: Path) -> None:
        """Empty catalogs/ directory returns empty list and no errors."""
        catalogs_dir = tmp_path / "catalogs"
        catalogs_dir.mkdir()
        result, errors = _walk_catalogs(catalogs_dir)
        assert result == []
        assert errors == []

    def test_missing_catalogs_dir_returns_empty(self, tmp_path: Path) -> None:
        """Missing catalogs/ directory returns empty list and no errors."""
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == []
        assert errors == []

    def test_malformed_origin_skipped_and_error_logged(self, tmp_path: Path) -> None:
        """Malformed origin.txt is skipped; its sha is included in errors list."""
        _make_catalog(tmp_path, "sha_good", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha_bad", "")  # empty = malformed
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == ["https://a.example.com/m.git@main"]
        assert "sha_bad" in errors

    def test_does_not_walk_into_subdirectories(self, tmp_path: Path) -> None:
        """Subdirectories under catalogs/<sha>/ are not read."""
        entry = tmp_path / "catalogs" / "sha1"
        entry.mkdir(parents=True)
        (entry / "origin.txt").write_text("https://a.example.com/m.git@main\n")
        # Create a nested subdirectory with its own origin.txt -- should be ignored
        nested = entry / "nested"
        nested.mkdir()
        (nested / "origin.txt").write_text("https://nested.example.com/m.git@main\n")
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == ["https://a.example.com/m.git@main"]
        assert errors == []

    def test_no_origin_txt_sha_dir_not_an_error(self, tmp_path: Path) -> None:
        """A sha directory that has no origin.txt is silently skipped."""
        entry = tmp_path / "catalogs" / "sha1"
        entry.mkdir(parents=True)
        # No origin.txt created -- just the directory
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == []
        assert errors == []

    def test_non_directory_entry_in_catalogs_is_skipped(self, tmp_path: Path) -> None:
        """A regular file (not a directory) inside catalogs/ is silently skipped."""
        catalogs_dir = tmp_path / "catalogs"
        catalogs_dir.mkdir(parents=True)
        # Place a file directly in catalogs/ (not a sha directory)
        stale_file = catalogs_dir / "some-file.txt"
        stale_file.write_text("not a sha directory\n")
        # Also add a valid entry
        _make_catalog(tmp_path, "sha_valid", "https://a.example.com/m.git@main\n")
        result, errors = _walk_catalogs(catalogs_dir)
        assert result == ["https://a.example.com/m.git@main"]
        assert errors == []

    def test_os_error_reading_origin_logged_and_skipped(self, tmp_path: Path) -> None:
        """An OSError raised when reading origin.txt is logged and the entry is skipped."""
        import stat

        catalogs_dir = tmp_path / "catalogs"
        _make_catalog(tmp_path, "sha_good", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path, "sha_bad", "https://b.example.com/m.git@main\n")
        # Make origin.txt of sha_bad unreadable to trigger OSError
        bad_origin = catalogs_dir / "sha_bad" / "origin.txt"
        bad_origin.chmod(0)
        try:
            result, errors = _walk_catalogs(catalogs_dir)
            assert result == ["https://a.example.com/m.git@main"]
            assert "sha_bad" in errors
        finally:
            # Restore permissions so tmp_path cleanup works
            bad_origin.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.parametrize(
        "origin,expected",
        [
            ("https://example.com/m.git@main\n", "https://example.com/m.git@main"),
            ("git@example.com:org/m.git@develop\n", "git@example.com:org/m.git@develop"),
        ],
        ids=["https-url", "ssh-url"],
    )
    def test_parametrized_url_formats(self, tmp_path: Path, origin: str, expected: str) -> None:
        """Parametrized check that both https and ssh url formats work."""
        _make_catalog(tmp_path, "sha1", origin)
        result, errors = _walk_catalogs(tmp_path / "catalogs")
        assert result == [expected]
        assert errors == []


# ---------------------------------------------------------------------------
# complete() -- KANON_COMPLETION_ENABLED=0 short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteDisabled:
    """KANON_COMPLETION_ENABLED=0 causes complete() to return [] immediately."""

    def test_disabled_returns_empty(self, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 -> empty list (AC-FUNC-006)."""
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == []

    def test_disabled_does_not_write_log(self, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 does not touch completion-errors.log (AC-FUNC-006)."""
        log_path = tmp_path / "completion-errors.log"
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_HOME": str(tmp_path),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            complete("")
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# complete() -- happy path (AC-FUNC-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteHappyPath:
    """complete() returns sorted, prefix-filtered url@ref strings."""

    def test_three_catalogs_no_prefix(self, tmp_path: Path) -> None:
        """AC-FUNC-001: three origin.txt files, empty prefix -> all three sorted."""
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path / "cache", "sha3", "git@c.example.com:org/m.git@develop\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == [
            "git@c.example.com:org/m.git@develop",
            "https://a.example.com/m.git@main",
            "https://b.example.com/m.git@v1.0.0",
        ]

    def test_prefix_https_narrows(self, tmp_path: Path) -> None:
        """AC-FUNC-005: prefix 'https' returns only the two https URLs."""
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path / "cache", "sha3", "git@c.example.com:org/m.git@develop\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("https")
        assert result == [
            "https://a.example.com/m.git@main",
            "https://b.example.com/m.git@v1.0.0",
        ]

    def test_prefix_git_at_narrows(self, tmp_path: Path) -> None:
        """AC-FUNC-005: prefix 'git@' returns only the ssh URL."""
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path / "cache", "sha3", "git@c.example.com:org/m.git@develop\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("git@")
        assert result == ["git@c.example.com:org/m.git@develop"]

    @pytest.mark.parametrize(
        "prefix,expected",
        [
            (
                "",
                [
                    "git@c.example.com:org/m.git@develop",
                    "https://a.example.com/m.git@main",
                    "https://b.example.com/m.git@v1.0.0",
                ],
            ),
            ("https", ["https://a.example.com/m.git@main", "https://b.example.com/m.git@v1.0.0"]),
            ("https://a", ["https://a.example.com/m.git@main"]),
            ("git@", ["git@c.example.com:org/m.git@develop"]),
            ("nonexistent", []),
        ],
        ids=["empty", "https-prefix", "https-a-prefix", "git-at-prefix", "no-match"],
    )
    def test_prefix_filter_parametrized(self, tmp_path: Path, prefix: str, expected: list[str]) -> None:
        """Parametrized prefix-filter coverage (AC-FUNC-005)."""
        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "https://b.example.com/m.git@v1.0.0\n")
        _make_catalog(tmp_path / "cache", "sha3", "git@c.example.com:org/m.git@develop\n")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete(prefix)
        assert result == expected


# ---------------------------------------------------------------------------
# complete() -- empty catalogs directory (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteEmptyCatalogsDir:
    """complete() with empty catalogs/ -> empty stdout, no log entry."""

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        """AC-FUNC-002: empty catalogs/ dir -> empty stdout."""
        catalogs_dir = tmp_path / "cache" / "catalogs"
        catalogs_dir.mkdir(parents=True)
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            result = complete("")
        assert result == []
        assert not log_path.exists()

    def test_empty_dir_no_log_entry(self, tmp_path: Path) -> None:
        """AC-FUNC-002: empty dir is NOT an error -- no log entry written."""
        catalogs_dir = tmp_path / "cache" / "catalogs"
        catalogs_dir.mkdir(parents=True)
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            complete("")
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# complete() -- missing KANON_CACHE_DIR (AC-FUNC-003)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteMissingCacheDir:
    """complete() with missing KANON_CACHE_DIR -> empty stdout, no log."""

    def test_missing_cache_dir_returns_empty(self, tmp_path: Path) -> None:
        """AC-FUNC-003: missing KANON_CACHE_DIR -> empty stdout (no error)."""
        missing_dir = tmp_path / "no_such_dir"
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(missing_dir),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            result = complete("")
        assert result == []
        assert not log_path.exists()

    def test_missing_cache_dir_no_log(self, tmp_path: Path) -> None:
        """AC-FUNC-003: missing KANON_CACHE_DIR is NOT an error -- no log."""
        missing_dir = tmp_path / "no_such_dir"
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(missing_dir),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            complete("")
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# complete() -- malformed origin.txt (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteMalformedOrigin:
    """complete() with malformed origin.txt skips entry + writes log."""

    def test_malformed_skipped_valid_returned(self, tmp_path: Path) -> None:
        """AC-FUNC-004: malformed origin.txt is skipped; valid entries returned."""
        _make_catalog(tmp_path / "cache", "sha_good", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha_bad", "")  # empty = malformed
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == ["https://a.example.com/m.git@main"]

    def test_malformed_writes_log_entry(self, tmp_path: Path) -> None:
        """AC-FUNC-004: malformed origin.txt writes structured log entry with sha."""
        _make_catalog(tmp_path / "cache", "sha_good", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha_bad", "no-at-sign")  # invalid shape
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            complete("")
        assert log_path.exists()
        content = log_path.read_text()
        assert "__complete_cached_catalogs" in content
        assert "sha_bad" in content

    @pytest.mark.parametrize(
        "bad_content",
        [
            "",
            "   \n",
            "no-at-sign\n",
        ],
        ids=["empty", "whitespace-only", "no-at-sign"],
    )
    def test_parametrized_malformed_shapes(self, tmp_path: Path, bad_content: str) -> None:
        """Parametrized malformed origin.txt shapes all produce log entries."""
        _make_catalog(tmp_path / "cache", "sha_bad", bad_content)
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
                "KANON_COMPLETION_LOG": str(log_path),
            },
        ):
            result = complete("")
        assert result == []
        assert log_path.exists()


# ---------------------------------------------------------------------------
# _handle() -- argparse entry point
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandle:
    """_handle() calls complete() and writes one url@ref per line to stdout."""

    def test_handle_prints_urls(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """_handle() with three-catalog setup prints sorted urls to stdout."""
        import argparse

        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "git@b.example.com:org/m.git@develop\n")
        args = argparse.Namespace(current_token="")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = _handle(args)
        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == "git@b.example.com:org/m.git@develop\nhttps://a.example.com/m.git@main\n"

    def test_handle_returns_zero_on_empty(self, tmp_path: Path) -> None:
        """_handle() always returns 0 even when no urls found."""
        import argparse

        args = argparse.Namespace(current_token="")
        missing_dir = tmp_path / "no_cache"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(missing_dir),
            },
        ):
            result = _handle(args)
        assert result == 0

    def test_handle_prefix_filter(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """_handle() with prefix 'https' outputs only https URLs."""
        import argparse

        _make_catalog(tmp_path / "cache", "sha1", "https://a.example.com/m.git@main\n")
        _make_catalog(tmp_path / "cache", "sha2", "git@b.example.com:org/m.git@develop\n")
        args = argparse.Namespace(current_token="https")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_HOME": str(tmp_path),
            },
        ):
            _handle(args)
        captured = capsys.readouterr()
        assert captured.out == "https://a.example.com/m.git@main\n"
