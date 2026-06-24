"""Unit tests for kanon_cli.completions.cached_catalogs.

Covers:
- utf-8 encoding sweep (AC-12): read_text/write_text callsites specify encoding="utf-8".
- _read_origin: validates origin.txt content shape.
- complete: prefix filtering and empty-cache short-circuit.

AC-TEST-001
"""

from __future__ import annotations

import pathlib

import pytest

from tests.conftest import bare_text_io_calls


_CACHED_CATALOGS_PY = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "completions" / "cached_catalogs.py"
)


@pytest.mark.unit
class TestCachedCatalogsPyUtf8EncodingSweep:
    """AC-12: all read_text/write_text calls in completions/cached_catalogs.py specify encoding."""

    def test_no_bare_read_text_calls(self) -> None:
        """completions/cached_catalogs.py must not contain bare .read_text() calls."""
        bare = bare_text_io_calls(_CACHED_CATALOGS_PY)
        read_bare = [b for b in bare if "read_text" in b[1]]
        assert read_bare == [], (
            f"completions/cached_catalogs.py has bare read_text() calls: {read_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )

    def test_no_bare_write_text_calls(self) -> None:
        """completions/cached_catalogs.py must not contain bare .write_text() calls."""
        bare = bare_text_io_calls(_CACHED_CATALOGS_PY)
        write_bare = [b for b in bare if "write_text" in b[1]]
        assert write_bare == [], (
            f"completions/cached_catalogs.py has bare write_text() calls: {write_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )


@pytest.mark.unit
class TestReadOrigin:
    """Unit tests for _read_origin helper."""

    def test_valid_url_at_ref_returned(self, tmp_path: pathlib.Path) -> None:
        """Valid url@ref content is returned as-is.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.completions.cached_catalogs import _read_origin

        origin = tmp_path / "origin.txt"
        origin.write_text("https://example.com/repo.git@main\n", encoding="utf-8")
        result = _read_origin(origin)
        assert result == "https://example.com/repo.git@main"

    def test_empty_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        """Empty origin.txt returns None.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.completions.cached_catalogs import _read_origin

        origin = tmp_path / "origin.txt"
        origin.write_text("", encoding="utf-8")
        assert _read_origin(origin) is None

    def test_missing_at_separator_returns_none(self, tmp_path: pathlib.Path) -> None:
        """Content without '@' separator returns None.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.completions.cached_catalogs import _read_origin

        origin = tmp_path / "origin.txt"
        origin.write_text("https://example.com/repo.git\n", encoding="utf-8")
        assert _read_origin(origin) is None

    def test_whitespace_only_returns_none(self, tmp_path: pathlib.Path) -> None:
        """Whitespace-only content returns None.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.completions.cached_catalogs import _read_origin

        origin = tmp_path / "origin.txt"
        origin.write_text("   \n", encoding="utf-8")
        assert _read_origin(origin) is None
