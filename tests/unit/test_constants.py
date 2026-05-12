import pytest

from kanon_cli.constants import (
    KANON_LIST_LIMIT,
    KANON_TREE_NO_FILTER_THRESHOLD,
    LIST_EMPTY_CATALOG_NOTE,
    MISSING_CATALOG_ERROR_TEMPLATE,
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


@pytest.mark.unit
class TestKanonTreeNoFilterThreshold:
    """Tests for KANON_TREE_NO_FILTER_THRESHOLD (E2-F2-S1-T3 AC-FUNC-002)."""

    def test_is_int(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD is an int."""
        assert isinstance(KANON_TREE_NO_FILTER_THRESHOLD, int)

    def test_default_value_is_20(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD default value is 20."""
        import importlib
        import os

        import kanon_cli.constants as constants

        # Ensure no override env var is set before checking the default.
        saved = os.environ.pop("KANON_TREE_NO_FILTER_THRESHOLD", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_TREE_NO_FILTER_THRESHOLD == 20
        finally:
            if saved is not None:
                os.environ["KANON_TREE_NO_FILTER_THRESHOLD"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD is a positive integer."""
        assert KANON_TREE_NO_FILTER_THRESHOLD > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_TREE_NO_FILTER_THRESHOLD", "42")
        importlib.reload(constants)
        try:
            assert constants.KANON_TREE_NO_FILTER_THRESHOLD == 42
        finally:
            monkeypatch.delenv("KANON_TREE_NO_FILTER_THRESHOLD", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD set to a non-integer env var raises ValueError."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_TREE_NO_FILTER_THRESHOLD", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_TREE_NO_FILTER_THRESHOLD", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonListLimit:
    """Tests for KANON_LIST_LIMIT (E2-F2-S1-T4 AC-FUNC-002)."""

    def test_is_int(self) -> None:
        """KANON_LIST_LIMIT is an int."""
        assert isinstance(KANON_LIST_LIMIT, int)

    def test_default_value_is_50(self) -> None:
        """KANON_LIST_LIMIT default value is 50."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_LIST_LIMIT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_LIST_LIMIT == 50
        finally:
            if saved is not None:
                os.environ["KANON_LIST_LIMIT"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_LIST_LIMIT is a positive integer."""
        assert KANON_LIST_LIMIT > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_LIST_LIMIT env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_LIST_LIMIT", "77")
        importlib.reload(constants)
        try:
            assert constants.KANON_LIST_LIMIT == 77
        finally:
            monkeypatch.delenv("KANON_LIST_LIMIT", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_LIST_LIMIT set to a non-integer env var raises ValueError."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_LIST_LIMIT", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_LIST_LIMIT", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonAddConstants:
    """Tests for kanon add constants (E2-F4-S1-T1 AC-FUNC-013, AC-TEST-001)."""

    def test_kanon_kanon_file_env_exists(self) -> None:
        """KANON_KANON_FILE_ENV constant exists and is the string 'KANON_KANON_FILE'."""
        from kanon_cli.constants import KANON_KANON_FILE_ENV

        assert isinstance(KANON_KANON_FILE_ENV, str)
        assert KANON_KANON_FILE_ENV == "KANON_KANON_FILE"

    def test_kanon_kanon_file_default_exists(self) -> None:
        """KANON_KANON_FILE_DEFAULT constant exists and is './.kanon'."""
        from kanon_cli.constants import KANON_KANON_FILE_DEFAULT

        assert isinstance(KANON_KANON_FILE_DEFAULT, str)
        assert KANON_KANON_FILE_DEFAULT == "./.kanon"

    def test_kanon_header_gitbase_exists(self) -> None:
        """KANON_HEADER_GITBASE constant exists and contains the template placeholder."""
        from kanon_cli.constants import KANON_HEADER_GITBASE

        assert isinstance(KANON_HEADER_GITBASE, str)
        assert "<YOUR_GIT_ORG_BASE_URL>" in KANON_HEADER_GITBASE

    def test_kanon_header_claude_marketplaces_dir_exists(self) -> None:
        """KANON_HEADER_CLAUDE_MARKETPLACES_DIR constant exists and contains the template value."""
        from kanon_cli.constants import KANON_HEADER_CLAUDE_MARKETPLACES_DIR

        assert isinstance(KANON_HEADER_CLAUDE_MARKETPLACES_DIR, str)
        assert "${HOME}/.claude-marketplaces" in KANON_HEADER_CLAUDE_MARKETPLACES_DIR

    def test_kanon_header_marketplace_install_exists(self) -> None:
        """KANON_HEADER_MARKETPLACE_INSTALL constant exists and contains the template placeholder."""
        from kanon_cli.constants import KANON_HEADER_MARKETPLACE_INSTALL

        assert isinstance(KANON_HEADER_MARKETPLACE_INSTALL, str)
        assert "<true|false>" in KANON_HEADER_MARKETPLACE_INSTALL

    def test_header_constants_are_non_empty(self) -> None:
        """All three standard-header constants are non-empty strings."""
        from kanon_cli.constants import (
            KANON_HEADER_CLAUDE_MARKETPLACES_DIR,
            KANON_HEADER_GITBASE,
            KANON_HEADER_MARKETPLACE_INSTALL,
        )

        assert len(KANON_HEADER_GITBASE) > 0
        assert len(KANON_HEADER_CLAUDE_MARKETPLACES_DIR) > 0
        assert len(KANON_HEADER_MARKETPLACE_INSTALL) > 0

    def test_gitbase_line_starts_with_gitbase(self) -> None:
        """KANON_HEADER_GITBASE starts with 'GITBASE=' per the .kanon template."""
        from kanon_cli.constants import KANON_HEADER_GITBASE

        assert KANON_HEADER_GITBASE.startswith("GITBASE=")

    def test_claude_marketplaces_dir_line_starts_with_key(self) -> None:
        """KANON_HEADER_CLAUDE_MARKETPLACES_DIR starts with 'CLAUDE_MARKETPLACES_DIR='."""
        from kanon_cli.constants import KANON_HEADER_CLAUDE_MARKETPLACES_DIR

        assert KANON_HEADER_CLAUDE_MARKETPLACES_DIR.startswith("CLAUDE_MARKETPLACES_DIR=")

    def test_marketplace_install_line_starts_with_key(self) -> None:
        """KANON_HEADER_MARKETPLACE_INSTALL starts with 'KANON_MARKETPLACE_INSTALL='."""
        from kanon_cli.constants import KANON_HEADER_MARKETPLACE_INSTALL

        assert KANON_HEADER_MARKETPLACE_INSTALL.startswith("KANON_MARKETPLACE_INSTALL=")


@pytest.mark.unit
class TestKanonLockFileConstant:
    """Tests for KANON_LOCK_FILE constant (E3-F1-S1-T1 AC-FUNC-008)."""

    def test_kanon_lock_file_exists(self) -> None:
        """KANON_LOCK_FILE constant exists in kanon_cli.constants and is importable."""
        from kanon_cli.constants import KANON_LOCK_FILE

        assert KANON_LOCK_FILE == "KANON_LOCK_FILE"

    def test_kanon_lock_file_value(self) -> None:
        """KANON_LOCK_FILE constant equals the string 'KANON_LOCK_FILE'."""
        from kanon_cli.constants import KANON_LOCK_FILE

        assert KANON_LOCK_FILE == "KANON_LOCK_FILE"

    def test_kanon_lock_file_is_string(self) -> None:
        """KANON_LOCK_FILE constant is a str."""
        from kanon_cli.constants import KANON_LOCK_FILE

        assert isinstance(KANON_LOCK_FILE, str)

    def test_kanon_lock_file_adjacent_to_kanon_file_env(self) -> None:
        """KANON_LOCK_FILE and KANON_KANON_FILE_ENV are both importable from constants."""
        from kanon_cli.constants import KANON_KANON_FILE_ENV, KANON_LOCK_FILE

        assert KANON_LOCK_FILE == "KANON_LOCK_FILE"
        assert KANON_KANON_FILE_ENV == "KANON_KANON_FILE"
