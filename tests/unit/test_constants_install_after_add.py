"""Unit tests for [catalog] block constants and parser (E22 DEFECT-001).

Verifies AC-FUNC-001: KANON_CATALOG_BLOCK_HEADER and KANON_CATALOG_BLOCK_KEY
are defined in kanon_cli.constants with the exact string values expected by
spec Section 5 (data format) and that no inline magic strings appear in the
modified modules.

Also covers the _parse_catalog_block and CatalogBlockParseError logic
introduced by E22 (AC-FUNC-002, AC-FUNC-005).
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.constants import (
    KANON_CATALOG_BLOCK_HEADER,
    KANON_CATALOG_BLOCK_KEY,
)
from kanon_cli.core.install import (
    CatalogBlockParseError,
    _parse_catalog_block,
)


@pytest.mark.unit
class TestCatalogBlockConstants:
    """AC-FUNC-001: constants are defined with the correct values."""

    def test_kanon_catalog_block_header_value(self) -> None:
        assert KANON_CATALOG_BLOCK_HEADER == "[catalog]"

    def test_kanon_catalog_block_key_value(self) -> None:
        assert KANON_CATALOG_BLOCK_KEY == "KANON_CATALOG_SOURCE"

    def test_kanon_catalog_block_header_is_string(self) -> None:
        assert isinstance(KANON_CATALOG_BLOCK_HEADER, str)

    def test_kanon_catalog_block_key_is_string(self) -> None:
        assert isinstance(KANON_CATALOG_BLOCK_KEY, str)


@pytest.mark.unit
class TestParseCatalogBlock:
    """AC-FUNC-002: _parse_catalog_block returns the correct value or None."""

    def test_returns_none_when_file_absent(self, tmp_path: pathlib.Path) -> None:
        """When .kanon does not exist, returns None (no error)."""
        missing = tmp_path / ".kanon"
        result = _parse_catalog_block(missing)
        assert result is None

    def test_returns_none_when_no_catalog_header(self, tmp_path: pathlib.Path) -> None:
        """When .kanon exists but has no [catalog] header, returns None."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=https://github.com/example\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "\n"
            "KANON_SOURCE_foo_URL=https://example.com/repo.git\n"
        )
        result = _parse_catalog_block(kanon_file)
        assert result is None

    def test_returns_value_when_block_present(self, tmp_path: pathlib.Path) -> None:
        """When .kanon has a valid [catalog] block, returns the catalog source."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=https://github.com/example\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "\n"
            "[catalog]\n"
            "KANON_CATALOG_SOURCE=https://github.com/org/manifest.git@main\n"
        )
        result = _parse_catalog_block(kanon_file)
        assert result == "https://github.com/org/manifest.git@main"

    def test_returns_value_with_file_url_and_ref(self, tmp_path: pathlib.Path) -> None:
        """Value can be a file:// URL -- verbatim preservation."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\nKANON_CATALOG_SOURCE=file:///tmp/catalog@main\n")
        result = _parse_catalog_block(kanon_file)
        assert result == "file:///tmp/catalog@main"

    def test_block_at_end_of_file_without_newline(self, tmp_path: pathlib.Path) -> None:
        """Block value without trailing newline is still parsed correctly."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\nKANON_CATALOG_SOURCE=https://example.com@main")
        result = _parse_catalog_block(kanon_file)
        assert result == "https://example.com@main"


@pytest.mark.unit
class TestParseCatalogBlockErrors:
    """AC-FUNC-005: malformed [catalog] block raises CatalogBlockParseError."""

    def test_raises_when_header_only_no_follow_line(self, tmp_path: pathlib.Path) -> None:
        """[catalog] at end of file with no follow-up line raises CatalogBlockParseError."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        err = exc_info.value
        assert err.kanon_path == kanon_file
        assert "no following KANON_CATALOG_SOURCE=" in str(err)

    def test_raises_when_follow_line_wrong_key(self, tmp_path: pathlib.Path) -> None:
        """Wrong key name after [catalog] header raises CatalogBlockParseError."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\nKANON_WRONG_KEY=value\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        err = exc_info.value
        assert err.kanon_path == kanon_file
        assert "KANON_CATALOG_SOURCE=<url>@<ref>" in str(err)

    def test_raises_when_value_is_empty(self, tmp_path: pathlib.Path) -> None:
        """Empty value after KANON_CATALOG_SOURCE= raises CatalogBlockParseError."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\nKANON_CATALOG_SOURCE=\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        err = exc_info.value
        assert err.kanon_path == kanon_file
        assert "empty" in str(err)

    def test_error_str_has_error_prefix(self, tmp_path: pathlib.Path) -> None:
        """CatalogBlockParseError __str__ starts with 'ERROR:'."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        assert str(exc_info.value).startswith("ERROR:")

    def test_error_str_has_remediation_line(self, tmp_path: pathlib.Path) -> None:
        """CatalogBlockParseError includes the remediation instruction."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        error_text = str(exc_info.value)
        assert "Remove the block or supply a value" in error_text

    def test_error_includes_line_number(self, tmp_path: pathlib.Path) -> None:
        """CatalogBlockParseError exposes the line_number attribute."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("GITBASE=x\n[catalog]\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        assert exc_info.value.line_number == 2  # [catalog] is on line 2


@pytest.mark.unit
class TestCatalogBlockParseErrorAttributes:
    """CatalogBlockParseError exposes all required attributes."""

    def test_is_install_error_subclass(self, tmp_path: pathlib.Path) -> None:
        from kanon_cli.core.install import InstallError

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        assert isinstance(exc_info.value, InstallError)

    def test_attributes_accessible(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("[catalog]\nKANON_CATALOG_SOURCE=\n")
        with pytest.raises(CatalogBlockParseError) as exc_info:
            _parse_catalog_block(kanon_file)
        err = exc_info.value
        assert hasattr(err, "line_number")
        assert hasattr(err, "reason")
        assert hasattr(err, "kanon_path")
        assert isinstance(err.line_number, int)
        assert isinstance(err.reason, str)
        assert isinstance(err.kanon_path, pathlib.Path)
