"""Advanced edge-case tests for the .kanon parser.

Covers:
- AC-TEST-001: duplicate keys produce a clear error
- AC-TEST-002: = in values is split only on the first =
- AC-TEST-003: quoted values are handled consistently
- AC-TEST-004: permission-denied on .kanon read raises with file path
"""

import pathlib
import stat

import pytest

from kanon_cli.core.kanonenv import parse_kanonenv


# ---------------------------------------------------------------------------
# Minimal valid .kanon content that satisfies source discovery requirements.
# Reused across multiple tests as a shared constant to avoid duplication.
# ---------------------------------------------------------------------------
_VALID_SOURCE_LINES = (
    "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
)


@pytest.mark.unit
class TestDuplicateKeys:
    """AC-TEST-001: duplicate keys produce a clear error."""

    def test_duplicate_global_key_raises(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file with the same global key defined twice must raise ValueError."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_URL=https://first.example.com\nREPO_URL=https://second.example.com\n" + _VALID_SOURCE_LINES
        )
        with pytest.raises(ValueError, match="Duplicate key 'REPO_URL'"):
            parse_kanonenv(kanonenv)

    def test_duplicate_source_key_raises(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file with the same source variable defined twice must raise ValueError."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://first.example.com\n"
            "KANON_SOURCE_build_URL=https://second.example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        with pytest.raises(ValueError, match="Duplicate key 'KANON_SOURCE_build_URL'"):
            parse_kanonenv(kanonenv)

    @pytest.mark.parametrize(
        "key",
        [
            "SOME_KEY",
            "KANON_SOURCE_alpha_URL",
            "KANON_MARKETPLACE_INSTALL",
        ],
    )
    def test_any_duplicate_key_raises(self, tmp_path: pathlib.Path, key: str) -> None:
        """Any key appearing more than once must raise ValueError."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(f"{key}=first_value\n{key}=second_value\n" + _VALID_SOURCE_LINES)
        with pytest.raises(ValueError, match=f"Duplicate key '{key}'"):
            parse_kanonenv(kanonenv)

    def test_unique_keys_do_not_raise(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file with all unique keys must parse without error."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_URL=https://example.com\nREPO_REV=main\n" + _VALID_SOURCE_LINES)
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["REPO_URL"] == "https://example.com"
        assert result["globals"]["REPO_REV"] == "main"


@pytest.mark.unit
class TestEqualsInValues:
    """AC-TEST-002: = in values is split only on the first =."""

    def test_value_with_multiple_equals_parsed_correctly(self, tmp_path: pathlib.Path) -> None:
        """A value containing multiple = signs must keep everything after the first =."""
        kanonenv = tmp_path / ".kanon"
        url_with_equals = "https://example.com/path?token=abc&sig=xyz==pad"
        kanonenv.write_text(f"COMPLEX_URL={url_with_equals}\n" + _VALID_SOURCE_LINES)
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["COMPLEX_URL"] == url_with_equals

    @pytest.mark.parametrize(
        "raw_line,expected_key,expected_value",
        [
            ("KEY=a=b", "KEY", "a=b"),
            ("KEY=a=b=c", "KEY", "a=b=c"),
            ("KEY=a==b", "KEY", "a==b"),
            ("KEY==leading_equals_in_value", "KEY", "=leading_equals_in_value"),
        ],
    )
    def test_first_equals_is_separator(
        self,
        tmp_path: pathlib.Path,
        raw_line: str,
        expected_key: str,
        expected_value: str,
    ) -> None:
        """The first = in a line is always the key-value separator."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(raw_line + "\n" + _VALID_SOURCE_LINES)
        result = parse_kanonenv(kanonenv)
        assert result["globals"][expected_key] == expected_value


@pytest.mark.unit
class TestQuotedValues:
    """AC-TEST-003: quoted values are handled consistently."""

    @pytest.mark.parametrize(
        "raw_value,expected",
        [
            ('"double quoted"', '"double quoted"'),
            ("'single quoted'", "'single quoted'"),
            ('"with inner = sign"', '"with inner = sign"'),
            ("bare_value", "bare_value"),
        ],
    )
    def test_quotes_preserved_as_is(
        self,
        tmp_path: pathlib.Path,
        raw_value: str,
        expected: str,
    ) -> None:
        """Quoted values are not stripped of their quotes -- stored verbatim."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(f"MY_VAR={raw_value}\n" + _VALID_SOURCE_LINES)
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["MY_VAR"] == expected

    def test_empty_value_is_empty_string(self, tmp_path: pathlib.Path) -> None:
        """A key with no value (KEY=) parses to an empty string."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("EMPTY_VAR=\n" + _VALID_SOURCE_LINES)
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["EMPTY_VAR"] == ""


@pytest.mark.unit
class TestPermissionDenied:
    """AC-TEST-004: permission-denied on .kanon read raises with file path."""

    def test_unreadable_file_raises_with_path(self, tmp_path: pathlib.Path) -> None:
        """When .kanon exists but is not readable, PermissionError includes the path."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_VALID_SOURCE_LINES)
        # Remove all read permissions from the file
        kanonenv.chmod(stat.S_IWRITE)
        try:
            with pytest.raises(PermissionError) as exc_info:
                parse_kanonenv(kanonenv)
            assert str(kanonenv) in str(exc_info.value)
        finally:
            # Restore permissions so tmp_path cleanup can delete the file
            kanonenv.chmod(stat.S_IRUSR | stat.S_IWUSR)
