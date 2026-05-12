import pytest

from kanon_cli.constants import RECOMMENDED_CHAR_RE, TAG_ERROR_DISPLAY_CAP


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
