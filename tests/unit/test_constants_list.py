"""Unit tests for the kanon list command constants.

Verifies constants.py defines the KANON_LIST_* output-format, status, scope,
column, note, and JSON-indent constants with the correct values, that "status"
is in the telemetry flag-value allowlist, and that no inline string literals for
the status / scope / format tokens appear in commands/list.py (CLAUDE.md
NO HARD-CODED VALUES).
"""

from __future__ import annotations

import pathlib
import re

import pytest

from kanon_cli import constants


@pytest.mark.unit
class TestListConstants:
    """The KANON_LIST_* constants exist with the expected values."""

    def test_output_format_env_and_values(self) -> None:
        """The output-format env name and its table/json values are defined."""
        assert constants.KANON_LIST_OUTPUT_FORMAT == "KANON_LIST_OUTPUT_FORMAT"
        assert constants.KANON_LIST_OUTPUT_FORMAT_TABLE == "table"
        assert constants.KANON_LIST_OUTPUT_FORMAT_JSON == "json"
        assert constants.KANON_LIST_OUTPUT_FORMAT_DEFAULT == constants.KANON_LIST_OUTPUT_FORMAT_TABLE

    def test_output_format_choices(self) -> None:
        """The output-format choices tuple carries exactly table then json."""
        assert constants.KANON_LIST_OUTPUT_FORMAT_CHOICES == ("table", "json")

    def test_distinct_from_search_list_constants(self) -> None:
        """The list command's format env must not collide with search's KANON_LIST_FORMAT / KANON_LIST_LIMIT."""
        assert constants.KANON_LIST_OUTPUT_FORMAT != "KANON_LIST_FORMAT"
        assert hasattr(constants, "KANON_LIST_LIMIT")
        assert constants.KANON_LIST_OUTPUT_FORMAT != constants.KANON_LIST_LIMIT

    def test_status_values(self) -> None:
        """The three status tags are defined with hyphenated values."""
        assert constants.KANON_LIST_STATUS_INSTALLED == "installed"
        assert constants.KANON_LIST_STATUS_NOT_INSTALLED == "not-installed"
        assert constants.KANON_LIST_STATUS_ORPHAN == "orphan"

    def test_status_choices(self) -> None:
        """The status-choices tuple carries the three tags in canonical order."""
        assert constants.KANON_LIST_STATUS_CHOICES == ("installed", "not-installed", "orphan")

    def test_scope_values(self) -> None:
        """The direct/transitive scope tags are defined."""
        assert constants.KANON_LIST_SCOPE_DIRECT == "direct"
        assert constants.KANON_LIST_SCOPE_TRANSITIVE == "transitive"

    def test_column_headers(self) -> None:
        """The table column headers are defined."""
        assert constants.KANON_LIST_COLUMN_SOURCE == "SOURCE"
        assert constants.KANON_LIST_COLUMN_REF == "REF"
        assert constants.KANON_LIST_COLUMN_STATUS == "STATUS"

    def test_json_indent_is_non_negative_int(self) -> None:
        """The JSON indent is a non-negative integer."""
        assert isinstance(constants.KANON_LIST_JSON_INDENT, int)
        assert constants.KANON_LIST_JSON_INDENT >= 0

    def test_notes_defined(self) -> None:
        """The empty and no-lockfile stderr notes are defined."""
        assert isinstance(constants.KANON_LIST_NO_SOURCES_NOTE, str)
        assert isinstance(constants.KANON_LIST_NO_LOCKFILE_NOTE, str)
        assert constants.KANON_LIST_NO_SOURCES_NOTE
        assert constants.KANON_LIST_NO_LOCKFILE_NOTE

    def test_status_in_telemetry_flag_value_allowlist(self) -> None:
        """The --status value must be capturable by the telemetry emitter."""
        assert "status" in constants.KANON_TELEMETRY_FLAG_VALUE_ALLOWLIST
        assert "format" in constants.KANON_TELEMETRY_FLAG_VALUE_ALLOWLIST


@pytest.mark.unit
class TestListConstantsNoInlineLiterals:
    """No bare status / scope / format string literals appear in commands/list.py."""

    @pytest.fixture
    def list_py_source(self) -> str:
        """Read the source of commands/list.py for inspection."""
        src_root = pathlib.Path(__file__).parent.parent.parent / "src" / "kanon_cli"
        list_path = src_root / "commands" / "list.py"
        assert list_path.exists(), f"commands/list.py not found at {list_path}"
        return list_path.read_text(encoding="utf-8")

    @pytest.mark.parametrize("token", ["installed", "not-installed", "orphan", "direct", "transitive", "table", "json"])
    def test_no_inline_token_literal(self, list_py_source: str, token: str) -> None:
        """The token must not appear as a bare quoted string literal in list.py."""
        literal_pattern = re.compile(rf"""(?<!\w)['"]{re.escape(token)}['"]""")
        matches = literal_pattern.findall(list_py_source)
        assert not matches, (
            f"Found bare {token!r} string literal(s) in commands/list.py. "
            "Use the corresponding KANON_LIST_* constant instead. "
            f"Matched {len(matches)} occurrence(s)."
        )

    def test_list_imports_list_constants(self, list_py_source: str) -> None:
        """commands/list.py must reference the KANON_LIST_* status and format constants."""
        assert "KANON_LIST_STATUS_CHOICES" in list_py_source
        assert "KANON_LIST_OUTPUT_FORMAT_CHOICES" in list_py_source
