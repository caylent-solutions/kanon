import pytest

from kanon_cli.constants import (
    MISSING_CATALOG_ERROR_TEMPLATE,
    LIST_EMPTY_CATALOG_NOTE,
    RECOMMENDED_CHAR_RE,
    TAG_ERROR_DISPLAY_CAP,
)


@pytest.mark.unit
class TestTagErrorDisplayCap:
    def test_tag_error_display_cap_is_positive_int(self):
        assert isinstance(TAG_ERROR_DISPLAY_CAP, int)
        assert TAG_ERROR_DISPLAY_CAP > 0

    def test_tag_error_display_cap_value(self):
        assert TAG_ERROR_DISPLAY_CAP == 10


@pytest.mark.unit
class TestNoColorConstants:
    """Assert NO_COLOR_ENV and _NO_COLOR_ACTIVE exist with correct defaults (AC-TEST-003)."""

    def test_no_color_env_name_is_no_color(self) -> None:
        import kanon_cli.constants as constants

        assert constants.NO_COLOR_ENV == "NO_COLOR"

    def test_no_color_env_is_string(self) -> None:
        import kanon_cli.constants as constants

        assert isinstance(constants.NO_COLOR_ENV, str)

    def test_no_color_active_exists_at_import(self) -> None:
        import kanon_cli.constants as constants

        assert hasattr(constants, "_NO_COLOR_ACTIVE")

    def test_no_color_active_default_is_false(self) -> None:
        """_NO_COLOR_ACTIVE defaults to False at module load time."""
        import importlib

        import kanon_cli.constants as constants

        # Reload the module to get the initial default state
        importlib.reload(constants)
        assert constants._NO_COLOR_ACTIVE is False

    def test_no_color_active_is_bool(self) -> None:
        import kanon_cli.constants as constants

        assert isinstance(constants._NO_COLOR_ACTIVE, bool)


@pytest.mark.unit
class TestRecommendedCharRe:
    """Tests for RECOMMENDED_CHAR_RE (soft-spot rule 2, E2-F3-S1-T1 AC-CONST-001)."""

    @pytest.mark.parametrize(
        "value",
        [
            "foo",
            "FOO",
            "Foo",
            "abc123",
            "foo_bar",
            "foo-bar",
            "A-Z_0",
            "z9",
            "a",
            "",
        ],
    )
    def test_recommended_chars_produce_full_match(self, value: str) -> None:
        """Characters in [a-zA-Z0-9_-] (or empty string) produce a full match."""
        assert RECOMMENDED_CHAR_RE.fullmatch(value) is not None, (
            f"Expected RECOMMENDED_CHAR_RE to fullmatch {value!r} but it did not"
        )

    @pytest.mark.parametrize(
        "value",
        [
            "foo.bar",
            "foo bar",
            "foo@bar",
            "foo/bar",
            "foo!bar",
            "\u03b1pkg",
            "has#hash",
            "foo\n",  # trailing newline: re.match() with $ would silently accept this
        ],
    )
    def test_non_recommended_chars_produce_no_match(self, value: str) -> None:
        """Characters outside [a-zA-Z0-9_-] produce no full match."""
        assert RECOMMENDED_CHAR_RE.fullmatch(value) is None, (
            f"Expected RECOMMENDED_CHAR_RE NOT to fullmatch {value!r} but it did"
        )

    def test_empty_string_matches(self) -> None:
        """Empty string matches because the * quantifier allows zero characters."""
        assert RECOMMENDED_CHAR_RE.fullmatch("") is not None

    def test_pattern_anchored_at_start_and_end(self) -> None:
        """fullmatch() ensures the entire string is checked, so a bad char anywhere rejects the value."""
        # A value that is clean at start but has a bad char later must not match
        assert RECOMMENDED_CHAR_RE.fullmatch("good.bad") is None


@pytest.mark.unit
class TestMissingCatalogErrorTemplate:
    """Tests for MISSING_CATALOG_ERROR_TEMPLATE (AC-CONST-001, AC-TEST-001)."""

    def test_is_str(self) -> None:
        """MISSING_CATALOG_ERROR_TEMPLATE is a str."""
        assert isinstance(MISSING_CATALOG_ERROR_TEMPLATE, str)

    def test_is_non_empty(self) -> None:
        """MISSING_CATALOG_ERROR_TEMPLATE is non-empty."""
        assert len(MISSING_CATALOG_ERROR_TEMPLATE) > 0

    def test_formatted_starts_with_error(self) -> None:
        """Formatted result starts with 'ERROR:' as required by the spec."""
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert rendered.startswith("ERROR:")

    def test_formatted_contains_command_name(self) -> None:
        """The {command} placeholder is substituted into the formatted string."""
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "list" in rendered

    def test_formatted_mentions_catalog_source_flag(self) -> None:
        """The formatted string names the --catalog-source CLI flag."""
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "--catalog-source" in rendered

    def test_formatted_mentions_env_var(self) -> None:
        """The formatted string names the KANON_CATALOG_SOURCE env var."""
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "KANON_CATALOG_SOURCE" in rendered

    def test_template_is_format_compatible(self) -> None:
        """Template accepts str.format() with command kwarg without raising."""
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="add")
        assert "add" in rendered

    def test_no_dead_code_list_limit_env_var(self) -> None:
        """LIST_LIMIT_ENV_VAR must not exist in constants (dead-code check, AC-CONST-003)."""
        import kanon_cli.constants as constants

        assert not hasattr(constants, "LIST_LIMIT_ENV_VAR")

    def test_no_dead_code_list_limit_default(self) -> None:
        """LIST_LIMIT_DEFAULT must not exist in constants (dead-code check, AC-CONST-003)."""
        import kanon_cli.constants as constants

        assert not hasattr(constants, "LIST_LIMIT_DEFAULT")


@pytest.mark.unit
class TestListEmptyCatalogNote:
    """Tests for LIST_EMPTY_CATALOG_NOTE (AC-CONST-002, AC-TEST-001)."""

    def test_is_str(self) -> None:
        """LIST_EMPTY_CATALOG_NOTE is a str."""
        assert isinstance(LIST_EMPTY_CATALOG_NOTE, str)

    def test_is_non_empty(self) -> None:
        """LIST_EMPTY_CATALOG_NOTE is a non-empty string."""
        assert len(LIST_EMPTY_CATALOG_NOTE) > 0

    def test_contains_zero_entries_phrase(self) -> None:
        """Value contains the spec-canonical 'manifest repo contains 0 entries' phrase."""
        assert "manifest repo contains 0 entries" in LIST_EMPTY_CATALOG_NOTE
