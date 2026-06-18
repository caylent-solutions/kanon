import pytest

from kanon_cli.constants import (
    EXIT_CODE_DEPRECATED,
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


@pytest.mark.unit
class TestKanonCompletionCacheDir:
    """Tests for KANON_COMPLETION_CACHE_DIR constant (E3-F3-S1-T9 AC-FUNC-001)."""

    def test_constant_value_equals_completion_cache(self) -> None:
        """KANON_COMPLETION_CACHE_DIR equals the string 'completion-cache'."""
        from kanon_cli.constants import KANON_COMPLETION_CACHE_DIR

        assert KANON_COMPLETION_CACHE_DIR == "completion-cache"

    def test_constant_is_string(self) -> None:
        """KANON_COMPLETION_CACHE_DIR is a str."""
        from kanon_cli.constants import KANON_COMPLETION_CACHE_DIR

        assert isinstance(KANON_COMPLETION_CACHE_DIR, str)

    def test_constant_is_non_empty(self) -> None:
        """KANON_COMPLETION_CACHE_DIR is a non-empty string."""
        from kanon_cli.constants import KANON_COMPLETION_CACHE_DIR

        assert len(KANON_COMPLETION_CACHE_DIR) > 0


@pytest.mark.unit
class TestKanonAllowInsecureRemotesConstant:
    """Tests for KANON_ALLOW_INSECURE_REMOTES constant (E3-F3-S1-T8 AC-FUNC-001)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_ALLOW_INSECURE_REMOTES constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES

        assert KANON_ALLOW_INSECURE_REMOTES is not None

    def test_constant_value(self) -> None:
        """KANON_ALLOW_INSECURE_REMOTES equals the string 'KANON_ALLOW_INSECURE_REMOTES'."""
        from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES

        assert KANON_ALLOW_INSECURE_REMOTES == "KANON_ALLOW_INSECURE_REMOTES"

    def test_constant_is_string(self) -> None:
        """KANON_ALLOW_INSECURE_REMOTES is a str."""
        from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES

        assert isinstance(KANON_ALLOW_INSECURE_REMOTES, str)

    def test_constant_non_empty(self) -> None:
        """KANON_ALLOW_INSECURE_REMOTES is a non-empty string."""
        from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES

        assert len(KANON_ALLOW_INSECURE_REMOTES) > 0

    def test_constant_importable_alongside_kanon_lock_file(self) -> None:
        """KANON_ALLOW_INSECURE_REMOTES and KANON_LOCK_FILE are both importable from constants."""
        from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES, KANON_LOCK_FILE

        assert KANON_ALLOW_INSECURE_REMOTES == "KANON_ALLOW_INSECURE_REMOTES"
        assert KANON_LOCK_FILE == "KANON_LOCK_FILE"


@pytest.mark.unit
class TestKanonOutdatedFormatConstant:
    """Tests for KANON_OUTDATED_FORMAT and KANON_OUTDATED_FORMAT_DEFAULT constants.

    AC-FUNC-007: The default output format for 'kanon outdated' is 'table',
    controlled by the KANON_OUTDATED_FORMAT env var (constant name stored in
    KANON_OUTDATED_FORMAT). The default value is stored in KANON_OUTDATED_FORMAT_DEFAULT.
    """

    def test_kanon_outdated_format_value(self) -> None:
        """KANON_OUTDATED_FORMAT equals the string 'KANON_OUTDATED_FORMAT'."""
        from kanon_cli.constants import KANON_OUTDATED_FORMAT

        assert KANON_OUTDATED_FORMAT == "KANON_OUTDATED_FORMAT"

    def test_kanon_outdated_format_is_string(self) -> None:
        """KANON_OUTDATED_FORMAT is a str."""
        from kanon_cli.constants import KANON_OUTDATED_FORMAT

        assert isinstance(KANON_OUTDATED_FORMAT, str)

    def test_kanon_outdated_format_default_value(self) -> None:
        """KANON_OUTDATED_FORMAT_DEFAULT equals 'table'."""
        from kanon_cli.constants import KANON_OUTDATED_FORMAT_DEFAULT

        assert KANON_OUTDATED_FORMAT_DEFAULT == "table"

    def test_kanon_outdated_format_default_is_string(self) -> None:
        """KANON_OUTDATED_FORMAT_DEFAULT is a str."""
        from kanon_cli.constants import KANON_OUTDATED_FORMAT_DEFAULT

        assert isinstance(KANON_OUTDATED_FORMAT_DEFAULT, str)

    def test_kanon_outdated_format_default_is_non_empty(self) -> None:
        """KANON_OUTDATED_FORMAT_DEFAULT is a non-empty string."""
        from kanon_cli.constants import KANON_OUTDATED_FORMAT_DEFAULT

        assert len(KANON_OUTDATED_FORMAT_DEFAULT) > 0


@pytest.mark.unit
class TestBranchShaTruncationConstants:
    """Tests for BRANCH_SHA_TRUNCATION_LENGTH, SHA1_HEX_LENGTH, SHA256_HEX_LENGTH.

    Added alongside the branch-pinned outdated logic (spec Section 4.4).
    """

    def test_branch_sha_truncation_length_exists(self) -> None:
        """BRANCH_SHA_TRUNCATION_LENGTH constant exists in kanon_cli.constants."""
        from kanon_cli.constants import BRANCH_SHA_TRUNCATION_LENGTH

        assert BRANCH_SHA_TRUNCATION_LENGTH is not None

    def test_branch_sha_truncation_length_value(self) -> None:
        """BRANCH_SHA_TRUNCATION_LENGTH equals 12 (matching git short-SHA convention)."""
        from kanon_cli.constants import BRANCH_SHA_TRUNCATION_LENGTH

        assert BRANCH_SHA_TRUNCATION_LENGTH == 12

    def test_branch_sha_truncation_length_is_positive_int(self) -> None:
        """BRANCH_SHA_TRUNCATION_LENGTH is a positive integer."""
        from kanon_cli.constants import BRANCH_SHA_TRUNCATION_LENGTH

        assert isinstance(BRANCH_SHA_TRUNCATION_LENGTH, int)
        assert BRANCH_SHA_TRUNCATION_LENGTH > 0

    def test_sha1_hex_length_exists(self) -> None:
        """SHA1_HEX_LENGTH constant exists in kanon_cli.constants."""
        from kanon_cli.constants import SHA1_HEX_LENGTH

        assert SHA1_HEX_LENGTH is not None

    def test_sha1_hex_length_value(self) -> None:
        """SHA1_HEX_LENGTH equals 40 (SHA-1 produces a 40-character hex digest)."""
        from kanon_cli.constants import SHA1_HEX_LENGTH

        assert SHA1_HEX_LENGTH == 40

    def test_sha1_hex_length_is_positive_int(self) -> None:
        """SHA1_HEX_LENGTH is a positive integer."""
        from kanon_cli.constants import SHA1_HEX_LENGTH

        assert isinstance(SHA1_HEX_LENGTH, int)
        assert SHA1_HEX_LENGTH > 0

    def test_sha256_hex_length_exists(self) -> None:
        """SHA256_HEX_LENGTH constant exists in kanon_cli.constants."""
        from kanon_cli.constants import SHA256_HEX_LENGTH

        assert SHA256_HEX_LENGTH is not None

    def test_sha256_hex_length_value(self) -> None:
        """SHA256_HEX_LENGTH equals 64 (SHA-256 produces a 64-character hex digest)."""
        from kanon_cli.constants import SHA256_HEX_LENGTH

        assert SHA256_HEX_LENGTH == 64

    def test_sha256_hex_length_is_positive_int(self) -> None:
        """SHA256_HEX_LENGTH is a positive integer."""
        from kanon_cli.constants import SHA256_HEX_LENGTH

        assert isinstance(SHA256_HEX_LENGTH, int)
        assert SHA256_HEX_LENGTH > 0

    def test_sha256_longer_than_sha1(self) -> None:
        """SHA256_HEX_LENGTH is longer than SHA1_HEX_LENGTH."""
        from kanon_cli.constants import SHA1_HEX_LENGTH, SHA256_HEX_LENGTH

        assert SHA256_HEX_LENGTH > SHA1_HEX_LENGTH

    def test_truncation_length_less_than_sha1_length(self) -> None:
        """BRANCH_SHA_TRUNCATION_LENGTH is shorter than SHA1_HEX_LENGTH (the shorter full SHA)."""
        from kanon_cli.constants import BRANCH_SHA_TRUNCATION_LENGTH, SHA1_HEX_LENGTH

        assert BRANCH_SHA_TRUNCATION_LENGTH < SHA1_HEX_LENGTH


@pytest.mark.unit
class TestKanonOutdatedJsonIndent:
    """Tests for KANON_OUTDATED_JSON_INDENT constant (E4-F1-S1-T4 AC-FUNC-001).

    This constant controls the indentation level used by json.dumps when
    'kanon outdated --format json' is selected. It is overridable via the
    KANON_OUTDATED_JSON_INDENT environment variable.
    """

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_OUTDATED_JSON_INDENT constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_OUTDATED_JSON_INDENT

        assert isinstance(KANON_OUTDATED_JSON_INDENT, int)

    def test_default_value_is_2(self) -> None:
        """KANON_OUTDATED_JSON_INDENT default value is 2."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_OUTDATED_JSON_INDENT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_OUTDATED_JSON_INDENT == 2
        finally:
            if saved is not None:
                os.environ["KANON_OUTDATED_JSON_INDENT"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_OUTDATED_JSON_INDENT is a positive integer."""
        from kanon_cli.constants import KANON_OUTDATED_JSON_INDENT

        assert KANON_OUTDATED_JSON_INDENT > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_OUTDATED_JSON_INDENT env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_OUTDATED_JSON_INDENT", "4")
        importlib.reload(constants)
        try:
            assert constants.KANON_OUTDATED_JSON_INDENT == 4
        finally:
            monkeypatch.delenv("KANON_OUTDATED_JSON_INDENT", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_OUTDATED_JSON_INDENT set to a non-integer env var raises ValueError."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_OUTDATED_JSON_INDENT", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_OUTDATED_JSON_INDENT", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonWhyFormatConstants:
    """Tests for KANON_WHY_FORMAT and KANON_WHY_FORMAT_DEFAULT constants (AC-FUNC-006)."""

    def test_kanon_why_format_env_var_name(self) -> None:
        """KANON_WHY_FORMAT is the correct env var name string."""
        from kanon_cli.constants import KANON_WHY_FORMAT

        assert KANON_WHY_FORMAT == "KANON_WHY_FORMAT"

    def test_kanon_why_format_default_is_text(self) -> None:
        """KANON_WHY_FORMAT_DEFAULT is 'text'."""
        from kanon_cli.constants import KANON_WHY_FORMAT_DEFAULT

        assert KANON_WHY_FORMAT_DEFAULT == "text"

    def test_kanon_why_format_default_is_string(self) -> None:
        """KANON_WHY_FORMAT_DEFAULT is a str instance."""
        from kanon_cli.constants import KANON_WHY_FORMAT_DEFAULT

        assert isinstance(KANON_WHY_FORMAT_DEFAULT, str)

    def test_kanon_why_format_json_is_json_string(self) -> None:
        """KANON_WHY_FORMAT_JSON is the string literal 'json'."""
        from kanon_cli.constants import KANON_WHY_FORMAT_JSON

        assert KANON_WHY_FORMAT_JSON == "json"

    def test_kanon_why_format_json_is_string(self) -> None:
        """KANON_WHY_FORMAT_JSON is a str instance."""
        from kanon_cli.constants import KANON_WHY_FORMAT_JSON

        assert isinstance(KANON_WHY_FORMAT_JSON, str)


@pytest.mark.unit
class TestKanonWhySuggestConstants:
    """Tests for KANON_WHY_SUGGEST_MAX_DISTANCE and KANON_WHY_SUGGEST_TOP_N (AC-FUNC-005)."""

    def test_max_distance_env_var_name_exists(self) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE constant exists and is an int."""
        from kanon_cli.constants import KANON_WHY_SUGGEST_MAX_DISTANCE

        assert isinstance(KANON_WHY_SUGGEST_MAX_DISTANCE, int)

    def test_max_distance_default_value_is_3(self) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE defaults to 3."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_WHY_SUGGEST_MAX_DISTANCE", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_SUGGEST_MAX_DISTANCE == 3
        finally:
            if saved is not None:
                os.environ["KANON_WHY_SUGGEST_MAX_DISTANCE"] = saved
            importlib.reload(constants)

    def test_max_distance_is_non_negative(self) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE is a non-negative integer (0 disables suggestions)."""
        from kanon_cli.constants import KANON_WHY_SUGGEST_MAX_DISTANCE

        assert KANON_WHY_SUGGEST_MAX_DISTANCE >= 0

    def test_max_distance_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_MAX_DISTANCE", "5")
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_SUGGEST_MAX_DISTANCE == 5
        finally:
            monkeypatch.delenv("KANON_WHY_SUGGEST_MAX_DISTANCE", raising=False)
            importlib.reload(constants)

    def test_max_distance_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE set to a non-integer env var raises ValueError."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_MAX_DISTANCE", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_MAX_DISTANCE", raising=False)
        importlib.reload(constants)

    def test_top_n_env_var_name_exists(self) -> None:
        """KANON_WHY_SUGGEST_TOP_N constant exists and is an int."""
        from kanon_cli.constants import KANON_WHY_SUGGEST_TOP_N

        assert isinstance(KANON_WHY_SUGGEST_TOP_N, int)

    def test_top_n_default_value_is_3(self) -> None:
        """KANON_WHY_SUGGEST_TOP_N defaults to 3."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_WHY_SUGGEST_TOP_N", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_SUGGEST_TOP_N == 3
        finally:
            if saved is not None:
                os.environ["KANON_WHY_SUGGEST_TOP_N"] = saved
            importlib.reload(constants)

    def test_top_n_is_non_negative(self) -> None:
        """KANON_WHY_SUGGEST_TOP_N is a non-negative integer (0 disables suggestions)."""
        from kanon_cli.constants import KANON_WHY_SUGGEST_TOP_N

        assert KANON_WHY_SUGGEST_TOP_N >= 0

    def test_top_n_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_TOP_N env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_TOP_N", "5")
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_SUGGEST_TOP_N == 5
        finally:
            monkeypatch.delenv("KANON_WHY_SUGGEST_TOP_N", raising=False)
            importlib.reload(constants)

    def test_top_n_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_TOP_N set to a non-integer env var raises ValueError."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_TOP_N", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_TOP_N", raising=False)
        importlib.reload(constants)

    def test_max_distance_negative_value_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE set to a negative integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_MAX_DISTANCE", "-1")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_MAX_DISTANCE", raising=False)
        importlib.reload(constants)

    def test_max_distance_non_int_raises_system_exit_with_error_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """KANON_WHY_SUGGEST_MAX_DISTANCE set to a non-integer raises SystemExit with ERROR: message."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_MAX_DISTANCE", "abc")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_MAX_DISTANCE", raising=False)
        importlib.reload(constants)

    def test_top_n_negative_value_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_SUGGEST_TOP_N set to a negative integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_TOP_N", "-1")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_TOP_N", raising=False)
        importlib.reload(constants)

    def test_top_n_non_int_raises_system_exit_with_error_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """KANON_WHY_SUGGEST_TOP_N set to a non-integer raises SystemExit with ERROR: message."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_SUGGEST_TOP_N", "xyz")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_WHY_SUGGEST_TOP_N", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonWhyJsonIndent:
    """Tests for KANON_WHY_JSON_INDENT constant (E4-F2-S1-T4 AC-DOC-002).

    This constant controls the indentation level used by json.dumps when
    'kanon why --format json' is selected. It is overridable via the
    KANON_WHY_JSON_INDENT environment variable.
    """

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_WHY_JSON_INDENT constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_WHY_JSON_INDENT

        assert isinstance(KANON_WHY_JSON_INDENT, int)

    def test_default_value_is_2(self) -> None:
        """KANON_WHY_JSON_INDENT default value is 2."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_WHY_JSON_INDENT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_JSON_INDENT == 2
        finally:
            if saved is not None:
                os.environ["KANON_WHY_JSON_INDENT"] = saved
            importlib.reload(constants)

    def test_is_non_negative(self) -> None:
        """KANON_WHY_JSON_INDENT is a non-negative integer (0 is valid for compact output)."""
        from kanon_cli.constants import KANON_WHY_JSON_INDENT

        assert KANON_WHY_JSON_INDENT >= 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_JSON_INDENT env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_JSON_INDENT", "4")
        importlib.reload(constants)
        try:
            assert constants.KANON_WHY_JSON_INDENT == 4
        finally:
            monkeypatch.delenv("KANON_WHY_JSON_INDENT", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_JSON_INDENT set to a non-integer env var raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_JSON_INDENT", "not-a-number")
        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(constants)
        assert "KANON_WHY_JSON_INDENT" in str(exc_info.value)
        monkeypatch.delenv("KANON_WHY_JSON_INDENT", raising=False)
        importlib.reload(constants)

    def test_env_override_negative_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_JSON_INDENT set to a negative integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_WHY_JSON_INDENT", "-1")
        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(constants)
        assert "KANON_WHY_JSON_INDENT" in str(exc_info.value)
        monkeypatch.delenv("KANON_WHY_JSON_INDENT", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonResolveTimeoutConstants:
    """Tests for _KANON_RESOLVE_TIMEOUT_ENV and _KANON_RESOLVE_TIMEOUT_DEFAULT (E5-F1-S1-T1)."""

    def test_resolve_timeout_env_name_exists(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_ENV constant exists and is importable."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_ENV

        assert _KANON_RESOLVE_TIMEOUT_ENV is not None

    def test_resolve_timeout_env_name_value(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_ENV equals 'KANON_RESOLVE_TIMEOUT'."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_ENV

        assert _KANON_RESOLVE_TIMEOUT_ENV == "KANON_RESOLVE_TIMEOUT"

    def test_resolve_timeout_env_name_is_string(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_ENV is a str."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_ENV

        assert isinstance(_KANON_RESOLVE_TIMEOUT_ENV, str)

    def test_resolve_timeout_default_exists(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_DEFAULT constant exists and is importable."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_DEFAULT

        assert _KANON_RESOLVE_TIMEOUT_DEFAULT is not None

    def test_resolve_timeout_default_value(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_DEFAULT equals 30."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_DEFAULT

        assert _KANON_RESOLVE_TIMEOUT_DEFAULT == 30

    def test_resolve_timeout_default_is_positive_int(self) -> None:
        """_KANON_RESOLVE_TIMEOUT_DEFAULT is a positive integer."""
        from kanon_cli.constants import _KANON_RESOLVE_TIMEOUT_DEFAULT

        assert isinstance(_KANON_RESOLVE_TIMEOUT_DEFAULT, int)
        assert _KANON_RESOLVE_TIMEOUT_DEFAULT > 0


@pytest.mark.unit
class TestKanonCompletionErrorsReportLimitConstant:
    """Tests for KANON_COMPLETION_ERRORS_REPORT_LIMIT constant (E5-F1-S1-T3 AC-FUNC-008)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_COMPLETION_ERRORS_REPORT_LIMIT

        assert isinstance(KANON_COMPLETION_ERRORS_REPORT_LIMIT, int)

    def test_default_value_is_5(self) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT default value is 5."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_COMPLETION_ERRORS_REPORT_LIMIT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_COMPLETION_ERRORS_REPORT_LIMIT == 5
        finally:
            if saved is not None:
                os.environ["KANON_COMPLETION_ERRORS_REPORT_LIMIT"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT is a positive integer."""
        from kanon_cli.constants import KANON_COMPLETION_ERRORS_REPORT_LIMIT

        assert KANON_COMPLETION_ERRORS_REPORT_LIMIT > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", "10")
        importlib.reload(constants)
        try:
            assert constants.KANON_COMPLETION_ERRORS_REPORT_LIMIT == 10
        finally:
            monkeypatch.delenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT set to a non-integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", "not-a-number")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", raising=False)
        importlib.reload(constants)

    def test_env_override_zero_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT set to 0 raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", "0")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", raising=False)
        importlib.reload(constants)

    def test_env_override_negative_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_COMPLETION_ERRORS_REPORT_LIMIT set to a negative integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", "-1")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_COMPLETION_ERRORS_REPORT_LIMIT", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonCacheDirEnvConstant:
    """Tests for KANON_CACHE_DIR_ENV constant (E5-F1-S1-T3 AC-FUNC-008)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_CACHE_DIR_ENV constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_CACHE_DIR_ENV

        assert isinstance(KANON_CACHE_DIR_ENV, str)

    def test_constant_value_is_kanon_cache_dir(self) -> None:
        """KANON_CACHE_DIR_ENV equals the string 'KANON_CACHE_DIR'."""
        from kanon_cli.constants import KANON_CACHE_DIR_ENV

        assert KANON_CACHE_DIR_ENV == "KANON_CACHE_DIR"

    def test_constant_is_non_empty(self) -> None:
        """KANON_CACHE_DIR_ENV is a non-empty string."""
        from kanon_cli.constants import KANON_CACHE_DIR_ENV

        assert len(KANON_CACHE_DIR_ENV) > 0


@pytest.mark.unit
class TestKanonCompletionErrorsLogFilenameConstant:
    """Tests for KANON_COMPLETION_ERRORS_LOG_FILENAME constant (E5-F1-S1-T3 AC-FUNC-008)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_COMPLETION_ERRORS_LOG_FILENAME constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_COMPLETION_ERRORS_LOG_FILENAME

        assert isinstance(KANON_COMPLETION_ERRORS_LOG_FILENAME, str)

    def test_constant_value_is_completion_errors_log(self) -> None:
        """KANON_COMPLETION_ERRORS_LOG_FILENAME equals 'completion-errors.log'."""
        from kanon_cli.constants import KANON_COMPLETION_ERRORS_LOG_FILENAME

        assert KANON_COMPLETION_ERRORS_LOG_FILENAME == "completion-errors.log"

    def test_constant_is_non_empty(self) -> None:
        """KANON_COMPLETION_ERRORS_LOG_FILENAME is a non-empty string."""
        from kanon_cli.constants import KANON_COMPLETION_ERRORS_LOG_FILENAME

        assert len(KANON_COMPLETION_ERRORS_LOG_FILENAME) > 0


@pytest.mark.unit
class TestKanonStaticCompletionSearchPathsConstant:
    """Tests for KANON_STATIC_COMPLETION_SEARCH_PATHS constant (E5-F1-S1-T3 AC-FUNC-008)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_STATIC_COMPLETION_SEARCH_PATHS constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        assert KANON_STATIC_COMPLETION_SEARCH_PATHS is not None

    def test_constant_is_tuple(self) -> None:
        """KANON_STATIC_COMPLETION_SEARCH_PATHS is a tuple."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        assert isinstance(KANON_STATIC_COMPLETION_SEARCH_PATHS, tuple)

    def test_each_entry_is_two_tuple_of_strings(self) -> None:
        """Each entry in KANON_STATIC_COMPLETION_SEARCH_PATHS is a (str, str) pair."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        for entry in KANON_STATIC_COMPLETION_SEARCH_PATHS:
            assert isinstance(entry, tuple), f"Expected tuple entry, got {type(entry)}"
            assert len(entry) == 2, f"Expected 2-tuple, got length {len(entry)}"
            shell, path = entry
            assert isinstance(shell, str), f"Expected shell to be str, got {type(shell)}"
            assert isinstance(path, str), f"Expected path to be str, got {type(path)}"

    def test_constant_includes_bash_entry(self) -> None:
        """KANON_STATIC_COMPLETION_SEARCH_PATHS includes at least one bash entry."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        shells = [shell for shell, _ in KANON_STATIC_COMPLETION_SEARCH_PATHS]
        assert "bash" in shells, "Expected at least one 'bash' entry in search paths"

    def test_constant_includes_zsh_entry(self) -> None:
        """KANON_STATIC_COMPLETION_SEARCH_PATHS includes at least one zsh entry."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        shells = [shell for shell, _ in KANON_STATIC_COMPLETION_SEARCH_PATHS]
        assert "zsh" in shells, "Expected at least one 'zsh' entry in search paths"

    def test_paths_are_non_empty_strings(self) -> None:
        """All path strings in KANON_STATIC_COMPLETION_SEARCH_PATHS are non-empty."""
        from kanon_cli.constants import KANON_STATIC_COMPLETION_SEARCH_PATHS

        for shell, path in KANON_STATIC_COMPLETION_SEARCH_PATHS:
            assert len(path) > 0, f"Expected non-empty path for shell {shell!r}"


@pytest.mark.unit
class TestKanonStaleCompletionScriptWarningConstant:
    """Tests for KANON_STALE_COMPLETION_SCRIPT_WARNING constant (E5-F1-S1-T3 AC-FUNC-008)."""

    def test_constant_exists_and_is_importable(self) -> None:
        """KANON_STALE_COMPLETION_SCRIPT_WARNING constant exists in kanon_cli.constants."""
        from kanon_cli.constants import KANON_STALE_COMPLETION_SCRIPT_WARNING

        assert isinstance(KANON_STALE_COMPLETION_SCRIPT_WARNING, str)

    def test_constant_is_non_empty(self) -> None:
        """KANON_STALE_COMPLETION_SCRIPT_WARNING is a non-empty string."""
        from kanon_cli.constants import KANON_STALE_COMPLETION_SCRIPT_WARNING

        assert len(KANON_STALE_COMPLETION_SCRIPT_WARNING) > 0

    def test_template_contains_shell_name_placeholder(self) -> None:
        """KANON_STALE_COMPLETION_SCRIPT_WARNING contains a {shell_name} placeholder."""
        from kanon_cli.constants import KANON_STALE_COMPLETION_SCRIPT_WARNING

        assert "{shell_name}" in KANON_STALE_COMPLETION_SCRIPT_WARNING

    def test_template_contains_path_placeholder(self) -> None:
        """KANON_STALE_COMPLETION_SCRIPT_WARNING contains a {path} placeholder."""
        from kanon_cli.constants import KANON_STALE_COMPLETION_SCRIPT_WARNING

        assert "{path}" in KANON_STALE_COMPLETION_SCRIPT_WARNING

    def test_template_is_format_compatible(self) -> None:
        """KANON_STALE_COMPLETION_SCRIPT_WARNING formats correctly with shell_name and path."""
        from kanon_cli.constants import KANON_STALE_COMPLETION_SCRIPT_WARNING

        rendered = KANON_STALE_COMPLETION_SCRIPT_WARNING.format(
            shell_name="bash",
            path="/usr/local/share/bash-completion/completions/kanon",
        )
        assert "bash" in rendered
        assert "/usr/local/share/bash-completion/completions/kanon" in rendered


# ---------------------------------------------------------------------------
# Doctor cache-management constants (subchecks 8 + 10, E5-F1-S1-T4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanonCachePruneAgeDays:
    """KANON_CACHE_PRUNE_AGE_DAYS is a positive integer defaulting to 30."""

    def test_is_positive_integer(self) -> None:
        """KANON_CACHE_PRUNE_AGE_DAYS must be a positive integer."""
        from kanon_cli.constants import KANON_CACHE_PRUNE_AGE_DAYS

        assert isinstance(KANON_CACHE_PRUNE_AGE_DAYS, int)
        assert KANON_CACHE_PRUNE_AGE_DAYS > 0

    def test_default_is_30(self) -> None:
        """Default value of KANON_CACHE_PRUNE_AGE_DAYS is 30."""
        import importlib
        import os
        import sys

        # Remove any existing instance to force reload without the env var.
        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]

        env_backup = os.environ.pop("KANON_CACHE_PRUNE_AGE_DAYS", None)
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_CACHE_PRUNE_AGE_DAYS == 30
        finally:
            if env_backup is not None:
                os.environ["KANON_CACHE_PRUNE_AGE_DAYS"] = env_backup
            # Reload to restore normal module state.
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CACHE_PRUNE_AGE_DAYS can be overridden via environment variable."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_CACHE_PRUNE_AGE_DAYS", "60")
        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_CACHE_PRUNE_AGE_DAYS == 60
        finally:
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_invalid_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-integer KANON_CACHE_PRUNE_AGE_DAYS raises SystemExit at import."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_CACHE_PRUNE_AGE_DAYS", "notanint")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_CACHE_PRUNE_AGE_DAYS", raising=False)
                importlib.import_module(mod_name)

    def test_zero_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CACHE_PRUNE_AGE_DAYS=0 raises SystemExit at import."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_CACHE_PRUNE_AGE_DAYS", "0")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_CACHE_PRUNE_AGE_DAYS", raising=False)
                importlib.import_module(mod_name)


@pytest.mark.unit
class TestKanonDoctorStaleLockScanMaxDepth:
    """KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH is a positive integer defaulting to 4."""

    def test_is_positive_integer(self) -> None:
        """KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH must be a positive integer."""
        from kanon_cli.constants import KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH

        assert isinstance(KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH, int)
        assert KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH > 0

    def test_default_is_4(self) -> None:
        """Default value of KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH is 4."""
        import importlib
        import os
        import sys

        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]

        env_backup = os.environ.pop("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", None)
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH == 4
        finally:
            if env_backup is not None:
                os.environ["KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH"] = env_backup
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH can be overridden via environment."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", "8")
        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH == 8
        finally:
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_invalid_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-integer KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH raises SystemExit."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", "bad")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", raising=False)
                importlib.import_module(mod_name)

    def test_zero_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH=0 raises SystemExit at import."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", "0")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", raising=False)
                importlib.import_module(mod_name)


@pytest.mark.unit
class TestKanonDoctorStaleLockAgeHours:
    """KANON_DOCTOR_STALE_LOCK_AGE_HOURS is a positive integer defaulting to 1."""

    def test_is_positive_integer(self) -> None:
        """KANON_DOCTOR_STALE_LOCK_AGE_HOURS must be a positive integer."""
        from kanon_cli.constants import KANON_DOCTOR_STALE_LOCK_AGE_HOURS

        assert isinstance(KANON_DOCTOR_STALE_LOCK_AGE_HOURS, int)
        assert KANON_DOCTOR_STALE_LOCK_AGE_HOURS > 0

    def test_default_is_1(self) -> None:
        """Default value of KANON_DOCTOR_STALE_LOCK_AGE_HOURS is 1."""
        import importlib
        import os
        import sys

        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]

        env_backup = os.environ.pop("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", None)
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_DOCTOR_STALE_LOCK_AGE_HOURS == 1
        finally:
            if env_backup is not None:
                os.environ["KANON_DOCTOR_STALE_LOCK_AGE_HOURS"] = env_backup
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_STALE_LOCK_AGE_HOURS can be overridden via environment."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", "24")
        for mod_name in list(sys.modules.keys()):
            if "kanon_cli.constants" in mod_name:
                del sys.modules[mod_name]
        try:
            import kanon_cli.constants as _c

            assert _c.KANON_DOCTOR_STALE_LOCK_AGE_HOURS == 24
        finally:
            for mod_name in list(sys.modules.keys()):
                if "kanon_cli.constants" in mod_name:
                    del sys.modules[mod_name]
            importlib.import_module("kanon_cli.constants")

    def test_invalid_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-integer KANON_DOCTOR_STALE_LOCK_AGE_HOURS raises SystemExit."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", "notanumber")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", raising=False)
                importlib.import_module(mod_name)

    def test_zero_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_STALE_LOCK_AGE_HOURS=0 raises SystemExit at import."""
        import importlib
        import sys

        monkeypatch.setenv("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", "0")
        mod_name = "kanon_cli.constants"
        original = sys.modules.pop(mod_name, None)
        try:
            with pytest.raises(SystemExit):
                importlib.import_module(mod_name)
        finally:
            sys.modules.pop(mod_name, None)
            if original is not None:
                sys.modules[mod_name] = original
            else:
                monkeypatch.delenv("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", raising=False)
                importlib.import_module(mod_name)


@pytest.mark.unit
class TestKanonDoctorRemoteStderrPreviewChars:
    """Tests for KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS (E5-F1-S1-T5 AC-FUNC-007)."""

    def test_is_int(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS is an int."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS

        assert isinstance(KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS, int)

    def test_default_value_is_160(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS defaults to 160."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS == 160
        finally:
            if saved is not None:
                os.environ["KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS is a positive integer."""
        from kanon_cli.constants import KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS

        assert KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS env var overrides the default."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", "80")
        importlib.reload(constants)
        try:
            assert constants.KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS == 80
        finally:
            monkeypatch.delenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", raising=False)
            importlib.reload(constants)

    def test_non_int_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS set to non-integer raises SystemExit at import."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", "not-a-number")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", raising=False)
        importlib.reload(constants)

    def test_zero_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS=0 raises SystemExit at import."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", "0")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", raising=False)
        importlib.reload(constants)


# ---------------------------------------------------------------------------
# Tests for the new catalog-audit constants (E5-F2-S1-T1 changes to constants.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanonCatalogAuditValidChecks:
    """KANON_CATALOG_AUDIT_VALID_CHECKS contains the five expected check names."""

    def test_is_frozenset(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert isinstance(KANON_CATALOG_AUDIT_VALID_CHECKS, frozenset)

    def test_contains_metadata(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert "metadata" in KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_contains_source_name_derivation(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert "source-name-derivation" in KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_contains_entry_name_uniqueness(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert "entry-name-uniqueness" in KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_contains_remote_url(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert "remote-url" in KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_contains_tag_format(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert "tag-format" in KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_exactly_five_checks(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        assert len(KANON_CATALOG_AUDIT_VALID_CHECKS) == 5

    def test_all_values_are_strings(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        for name in KANON_CATALOG_AUDIT_VALID_CHECKS:
            assert isinstance(name, str)

    def test_no_underscores_in_check_names(self) -> None:
        """Check names use hyphens, not underscores, per spec Section 4.8."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS

        for name in KANON_CATALOG_AUDIT_VALID_CHECKS:
            assert "_" not in name, f"Check name '{name}' should use hyphens, not underscores"


@pytest.mark.unit
class TestKanonCatalogAuditCacheTTL:
    """KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS has the expected default and env-override."""

    def test_default_is_3600(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS

        assert KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS == 3600

    def test_is_positive_int(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS

        assert isinstance(KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS, int)
        assert KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS > 0

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS env var overrides the default."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", "120")
        importlib.reload(constants)
        try:
            assert constants.KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS == 120
        finally:
            monkeypatch.delenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", raising=False)
            importlib.reload(constants)

    def test_non_int_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS set to non-integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", "not-a-number")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", raising=False)
        importlib.reload(constants)

    def test_zero_env_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS=0 raises SystemExit at import."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", "0")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonCatalogAuditCacheSubdir:
    """KANON_CATALOG_AUDIT_CACHE_SUBDIR is the expected string."""

    def test_value_is_catalog_audit(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_SUBDIR

        assert KANON_CATALOG_AUDIT_CACHE_SUBDIR == "catalog-audit"

    def test_is_string(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_SUBDIR

        assert isinstance(KANON_CATALOG_AUDIT_CACHE_SUBDIR, str)


@pytest.mark.unit
class TestKanonCatalogAuditFormatEnv:
    """KANON_CATALOG_AUDIT_FORMAT_ENV holds the correct env var name."""

    def test_env_var_name(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        assert KANON_CATALOG_AUDIT_FORMAT_ENV == "KANON_CATALOG_AUDIT_FORMAT"

    def test_is_string(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        assert isinstance(KANON_CATALOG_AUDIT_FORMAT_ENV, str)


@pytest.mark.unit
class TestKanonCatalogAuditFormatConstants:
    """KANON_CATALOG_AUDIT_FORMAT_DEFAULT and KANON_CATALOG_AUDIT_FORMAT_JSON hold correct values."""

    def test_format_default_value(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_DEFAULT

        assert KANON_CATALOG_AUDIT_FORMAT_DEFAULT == "text"

    def test_format_default_is_string(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_DEFAULT

        assert isinstance(KANON_CATALOG_AUDIT_FORMAT_DEFAULT, str)

    def test_format_json_value(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_JSON

        assert KANON_CATALOG_AUDIT_FORMAT_JSON == "json"

    def test_format_json_is_string(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_JSON

        assert isinstance(KANON_CATALOG_AUDIT_FORMAT_JSON, str)

    def test_format_default_and_json_are_distinct(self) -> None:
        from kanon_cli.constants import (
            KANON_CATALOG_AUDIT_FORMAT_DEFAULT,
            KANON_CATALOG_AUDIT_FORMAT_JSON,
        )

        assert KANON_CATALOG_AUDIT_FORMAT_DEFAULT != KANON_CATALOG_AUDIT_FORMAT_JSON


@pytest.mark.unit
class TestKanonCatalogMetadataFieldLists:
    """Tests for KANON_CATALOG_METADATA_REQUIRED_FIELDS and
    KANON_CATALOG_METADATA_RECOMMENDED_FIELDS (AC-FUNC-008 / source-test-atomicity)."""

    def test_required_fields_is_tuple(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert isinstance(KANON_CATALOG_METADATA_REQUIRED_FIELDS, tuple)

    def test_required_fields_contains_name(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert "name" in KANON_CATALOG_METADATA_REQUIRED_FIELDS

    def test_required_fields_contains_display_name(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert "display-name" in KANON_CATALOG_METADATA_REQUIRED_FIELDS

    def test_required_fields_contains_description(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert "description" in KANON_CATALOG_METADATA_REQUIRED_FIELDS

    def test_required_fields_contains_version(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert "version" in KANON_CATALOG_METADATA_REQUIRED_FIELDS

    def test_required_fields_length_is_four(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert len(KANON_CATALOG_METADATA_REQUIRED_FIELDS) == 4

    def test_required_fields_all_strings(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_REQUIRED_FIELDS

        assert all(isinstance(f, str) for f in KANON_CATALOG_METADATA_REQUIRED_FIELDS)

    def test_recommended_fields_is_tuple(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert isinstance(KANON_CATALOG_METADATA_RECOMMENDED_FIELDS, tuple)

    def test_recommended_fields_contains_type(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert "type" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

    def test_recommended_fields_contains_owner_name(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert "owner-name" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

    def test_recommended_fields_contains_owner_email(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert "owner-email" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

    def test_recommended_fields_contains_keywords(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert "keywords" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

    def test_recommended_fields_length_is_four(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert len(KANON_CATALOG_METADATA_RECOMMENDED_FIELDS) == 4

    def test_recommended_fields_all_strings(self) -> None:
        from kanon_cli.constants import KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

        assert all(isinstance(f, str) for f in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS)

    def test_required_and_recommended_are_disjoint(self) -> None:
        from kanon_cli.constants import (
            KANON_CATALOG_METADATA_RECOMMENDED_FIELDS,
            KANON_CATALOG_METADATA_REQUIRED_FIELDS,
        )

        required = set(KANON_CATALOG_METADATA_REQUIRED_FIELDS)
        recommended = set(KANON_CATALOG_METADATA_RECOMMENDED_FIELDS)
        assert required.isdisjoint(recommended)


# ---------------------------------------------------------------------------
# KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE (E5-F2-S1-T3 AC-FUNC-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanonCatalogEntryNameAllowedCharsRe:
    """KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE is a compiled regex in constants.py.

    AC-FUNC-006: The constant lives in constants.py (not inline in catalog.py)
    and correctly classifies entry names as within-charset or out-of-charset.
    """

    def test_constant_exists_in_constants_module(self) -> None:
        """KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE is importable from constants."""
        from kanon_cli.constants import KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE

        assert KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE is not None

    def test_constant_is_compiled_regex(self) -> None:
        """KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE is a compiled re.Pattern."""
        import re

        from kanon_cli.constants import KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE

        assert isinstance(KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE, re.Pattern)

    @pytest.mark.parametrize(
        "entry_name",
        [
            "foo_bar",
            "my-tool",
            "FOO",
            "foo123",
            "a",
            "ABC-def_123",
            "",
        ],
    )
    def test_allowed_chars_matches_valid_names(self, entry_name: str) -> None:
        """Entry names using only [a-zA-Z0-9_-] must fullmatch the pattern."""
        from kanon_cli.constants import KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE

        assert KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE.fullmatch(entry_name) is not None, (
            f"Expected {entry_name!r} to match KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE"
        )

    @pytest.mark.parametrize(
        "entry_name",
        [
            "foo.bar",
            "foo bar",
            "foo\tbar",
            "foo@bar",
            "foo/bar",
            "f\u00f3\u00f3",
            "foo!",
            "foo#bar",
        ],
    )
    def test_disallowed_chars_do_not_match(self, entry_name: str) -> None:
        """Entry names with out-of-charset chars must NOT fullmatch the pattern."""
        from kanon_cli.constants import KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE

        assert KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE.fullmatch(entry_name) is None, (
            f"Expected {entry_name!r} NOT to match KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE"
        )


@pytest.mark.unit
class TestKanonCatalogAuditTagReportLimit:
    """Tests for KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT (E5-F2-S1-T6 AC-FUNC-009)."""

    def test_is_int(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT is an int."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT

        assert isinstance(KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT, int)

    def test_default_value_is_50(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT default value is 50."""
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT == 50
        finally:
            if saved is not None:
                os.environ["KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT"] = saved
            importlib.reload(constants)

    def test_is_positive(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT is a positive integer."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT

        assert KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT > 0

    def test_env_override_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT env var overrides the default value."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", "25")
        importlib.reload(constants)
        try:
            assert constants.KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT == 25
        finally:
            monkeypatch.delenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", raising=False)
            importlib.reload(constants)

    def test_env_override_non_int_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT set to a non-integer raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", "not-an-int")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", raising=False)
        importlib.reload(constants)

    def test_env_override_zero_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT set to zero raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", "0")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", raising=False)
        importlib.reload(constants)

    def test_env_override_negative_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT set to a negative value raises SystemExit."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", "-5")
        with pytest.raises(SystemExit):
            importlib.reload(constants)
        monkeypatch.delenv("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", raising=False)
        importlib.reload(constants)


@pytest.mark.unit
class TestKanonCatalogAuditTagFormatSummaryTemplate:
    """Tests for KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE (E5-F2-S1-T6 AC-FUNC-009)."""

    def test_is_str(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE is a str."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

        assert isinstance(KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE, str)

    def test_is_non_empty(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE is non-empty."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

        assert len(KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE) > 0

    def test_contains_remaining_placeholder(self) -> None:
        """Template contains the {remaining} placeholder."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

        assert "{remaining}" in KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

    def test_formatted_contains_remaining_count(self) -> None:
        """Formatted template with remaining=10 contains '10' in the output."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE.format(remaining=10)
        assert "10" in rendered

    def test_formatted_mentions_tag_format_audit(self) -> None:
        """Formatted template mentions kanon catalog audit --check tag-format."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE.format(remaining=5)
        assert "tag-format" in rendered


class TestKanonCatalogAuditLegacyDirWarningTemplate:
    """Tests for KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE (E5-F2-S1-T7 AC-FUNC-006)."""

    def test_is_str(self) -> None:
        """KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE is a str."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        assert isinstance(KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE, str)

    def test_is_non_empty(self) -> None:
        """KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE is non-empty."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        assert len(KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE) > 0

    def test_contains_version_placeholder(self) -> None:
        """Template contains the {version} placeholder."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        assert "{version}" in KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

    def test_formatted_contains_version_string(self) -> None:
        """Formatted template with version='1.2.3' contains '1.2.3' in the output."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version="1.2.3")
        assert "1.2.3" in rendered

    def test_formatted_spec_verbatim_output(self) -> None:
        """Formatted template matches spec Section 4.8 wording exactly."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version="0.99.0")
        expected = (
            "Legacy catalog/ directory detected; this directory is unused by "
            "kanon >= 0.99.0 and should be deleted; "
            "see docs/migration-bootstrap-to-add.md"
        )
        assert rendered == expected

    def test_mentions_migration_doc(self) -> None:
        """Rendered template references the migration documentation path."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version="2.0.0")
        assert "docs/migration-bootstrap-to-add.md" in rendered


@pytest.mark.unit
class TestKanonCatalogAuditStrictSummaryTemplate:
    """Tests for KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE (E5-F2-S1-T8 AC-FUNC-007)."""

    def test_strict_summary_template_is_str(self) -> None:
        """KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE is a non-empty string."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        assert isinstance(KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE, str)
        assert len(KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE) > 0

    def test_strict_summary_template_contains_count_placeholder(self) -> None:
        """Template contains the {count} placeholder."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        assert "{count}" in KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

    def test_strict_summary_template_format_with_count(self) -> None:
        """Template formats correctly when {count} is substituted."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=3)
        assert "3" in rendered

    def test_strict_summary_template_rendered_contains_strict_mode(self) -> None:
        """Rendered template contains 'strict mode' so operators understand the context."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=1)
        assert "strict mode" in rendered

    def test_strict_summary_template_rendered_contains_warning(self) -> None:
        """Rendered template contains 'warning' to name the promoted finding severity."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=2)
        assert "warning" in rendered

    def test_strict_summary_template_count_zero(self) -> None:
        """Template formats without error when count is 0 (edge case)."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=0)
        assert "0" in rendered

    def test_strict_summary_template_count_large(self) -> None:
        """Template formats without error when count is large."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE

        rendered = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=999)
        assert "999" in rendered


@pytest.mark.unit
class TestExitCodeDeprecated:
    """Verify EXIT_CODE_DEPRECATED is defined with the correct value (AC-FUNC-006)."""

    def test_exit_code_deprecated_is_3(self) -> None:
        assert EXIT_CODE_DEPRECATED == 3

    def test_exit_code_deprecated_is_int(self) -> None:
        assert isinstance(EXIT_CODE_DEPRECATED, int)

    def test_exit_code_deprecated_is_module_level_constant(self) -> None:
        import kanon_cli.constants as constants

        assert hasattr(constants, "EXIT_CODE_DEPRECATED"), (
            "EXIT_CODE_DEPRECATED must be a module-level constant in kanon_cli.constants"
        )

    def test_exit_code_deprecated_distinct_from_success(self) -> None:
        assert EXIT_CODE_DEPRECATED != 0

    def test_exit_code_deprecated_distinct_from_runtime_error(self) -> None:
        assert EXIT_CODE_DEPRECATED != 1

    def test_exit_code_deprecated_distinct_from_argparse_error(self) -> None:
        assert EXIT_CODE_DEPRECATED != 2


# ---------------------------------------------------------------------------
# E7-F3-S1-T1: completion cache constants (AC-FUNC-008)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompletionCacheConstants:
    """TDD-paired test for the cache constants added to constants.py by E7-F3-S1-T1."""

    def test_kanon_cache_dir_env_is_string(self) -> None:
        from kanon_cli.constants import KANON_CACHE_DIR_ENV

        assert isinstance(KANON_CACHE_DIR_ENV, str)
        assert KANON_CACHE_DIR_ENV == "KANON_CACHE_DIR"

    def test_kanon_cache_dir_default_is_string(self) -> None:
        from kanon_cli.constants import KANON_CACHE_DIR_DEFAULT

        assert isinstance(KANON_CACHE_DIR_DEFAULT, str)
        assert KANON_CACHE_DIR_DEFAULT == "~/.cache/kanon"

    def test_kanon_completion_cache_ttl_is_int(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_CACHE_TTL

        assert isinstance(KANON_COMPLETION_CACHE_TTL, int)
        assert KANON_COMPLETION_CACHE_TTL == 300

    def test_kanon_completion_timeout_is_int(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_TIMEOUT

        assert isinstance(KANON_COMPLETION_TIMEOUT, int)
        assert KANON_COMPLETION_TIMEOUT == 2

    def test_kanon_completion_refresh_bg_is_int(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_REFRESH_BG

        assert isinstance(KANON_COMPLETION_REFRESH_BG, int)
        assert KANON_COMPLETION_REFRESH_BG == 1

    def test_kanon_completion_refresh_bg_env_is_string(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_REFRESH_BG_ENV

        assert isinstance(KANON_COMPLETION_REFRESH_BG_ENV, str)
        assert KANON_COMPLETION_REFRESH_BG_ENV == "KANON_COMPLETION_REFRESH_BG"

    def test_kanon_completion_enabled_is_int(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_ENABLED

        assert isinstance(KANON_COMPLETION_ENABLED, int)
        assert KANON_COMPLETION_ENABLED == 1

    def test_kanon_accessed_at_coalesce_sec_is_int(self) -> None:
        from kanon_cli.constants import KANON_ACCESSED_AT_COALESCE_SEC

        assert isinstance(KANON_ACCESSED_AT_COALESCE_SEC, int)
        assert KANON_ACCESSED_AT_COALESCE_SEC == 60

    def test_kanon_completion_log_env_is_string(self) -> None:
        from kanon_cli.constants import KANON_COMPLETION_LOG_ENV

        assert isinstance(KANON_COMPLETION_LOG_ENV, str)
        assert KANON_COMPLETION_LOG_ENV == "KANON_COMPLETION_LOG"


@pytest.mark.unit
class TestShellMetachars:
    """Tests for SHELL_METACHARS constant (AC-FUNC-008, E7-F3-S1-T4)."""

    def test_shell_metachars_is_frozenset(self) -> None:
        """SHELL_METACHARS must be a frozenset (immutable, hashable)."""
        from kanon_cli.constants import SHELL_METACHARS

        assert isinstance(SHELL_METACHARS, frozenset)

    def test_shell_metachars_is_nonempty(self) -> None:
        """SHELL_METACHARS must contain at least the spec-mandated characters."""
        from kanon_cli.constants import SHELL_METACHARS

        assert len(SHELL_METACHARS) > 0

    @pytest.mark.parametrize(
        "char",
        ["|", "&", ";", "<", ">", "(", ")", "{", "}", "$", "`", "\\", '"', "'"],
    )
    def test_shell_metachars_contains_required_char(self, char: str) -> None:
        """Each spec-mandated metacharacter must be present in SHELL_METACHARS."""
        from kanon_cli.constants import SHELL_METACHARS

        assert char in SHELL_METACHARS, f"Missing required metachar: {char!r}"

    def test_shell_metachars_contains_only_single_chars(self) -> None:
        """Every element of SHELL_METACHARS is a single character."""
        from kanon_cli.constants import SHELL_METACHARS

        for char in SHELL_METACHARS:
            assert len(char) == 1, f"Non-single-char element in SHELL_METACHARS: {char!r}"


@pytest.mark.unit
class TestCompletionSanitizationConstants:
    """Tests for COMPLETION_MAX_ENTRY_LEN and COMPLETION_UNSAFE_CHARS (spec Section 11.3)."""

    def test_completion_max_entry_len_is_int(self) -> None:
        """COMPLETION_MAX_ENTRY_LEN must be a positive integer."""
        from kanon_cli.constants import COMPLETION_MAX_ENTRY_LEN

        assert isinstance(COMPLETION_MAX_ENTRY_LEN, int)
        assert COMPLETION_MAX_ENTRY_LEN > 0

    def test_completion_max_entry_len_value(self) -> None:
        """COMPLETION_MAX_ENTRY_LEN must be exactly 128 per spec Section 11.3."""
        from kanon_cli.constants import COMPLETION_MAX_ENTRY_LEN

        assert COMPLETION_MAX_ENTRY_LEN == 128

    def test_completion_unsafe_chars_is_frozenset(self) -> None:
        """COMPLETION_UNSAFE_CHARS must be a frozenset (immutable, hashable)."""
        from kanon_cli.constants import COMPLETION_UNSAFE_CHARS

        assert isinstance(COMPLETION_UNSAFE_CHARS, frozenset)

    def test_completion_unsafe_chars_is_nonempty(self) -> None:
        """COMPLETION_UNSAFE_CHARS must contain at least one character."""
        from kanon_cli.constants import COMPLETION_UNSAFE_CHARS

        assert len(COMPLETION_UNSAFE_CHARS) > 0

    @pytest.mark.parametrize(
        "char",
        [" ", "\t", "\n", "\r", ";", "|", "&", "$", "`"],
    )
    def test_completion_unsafe_chars_contains_required_char(self, char: str) -> None:
        """Each shell-special and whitespace character must be in COMPLETION_UNSAFE_CHARS."""
        from kanon_cli.constants import COMPLETION_UNSAFE_CHARS

        assert char in COMPLETION_UNSAFE_CHARS, f"Missing required unsafe char: {char!r}"

    def test_completion_unsafe_chars_contains_only_single_chars(self) -> None:
        """Every element of COMPLETION_UNSAFE_CHARS is a single character."""
        from kanon_cli.constants import COMPLETION_UNSAFE_CHARS

        for char in COMPLETION_UNSAFE_CHARS:
            assert len(char) == 1, f"Non-single-char element in COMPLETION_UNSAFE_CHARS: {char!r}"


@pytest.mark.unit
class TestWorkspaceDirEnvVar:
    """Tests for WORKSPACE_DIR_ENV_VAR constant (E58-F4-S1-T1 AC-1..AC-4)."""

    def test_workspace_dir_env_var_exists(self) -> None:
        """WORKSPACE_DIR_ENV_VAR constant exists in kanon_cli.constants."""
        from kanon_cli.constants import WORKSPACE_DIR_ENV_VAR

        assert isinstance(WORKSPACE_DIR_ENV_VAR, str)

    def test_workspace_dir_env_var_value(self) -> None:
        """WORKSPACE_DIR_ENV_VAR must be exactly 'KANON_WORKSPACE_DIR'."""
        from kanon_cli.constants import WORKSPACE_DIR_ENV_VAR

        assert WORKSPACE_DIR_ENV_VAR == "KANON_WORKSPACE_DIR"

    def test_workspace_dir_env_var_is_non_empty(self) -> None:
        """WORKSPACE_DIR_ENV_VAR must not be empty."""
        from kanon_cli.constants import WORKSPACE_DIR_ENV_VAR

        assert len(WORKSPACE_DIR_ENV_VAR) > 0


# ---------------------------------------------------------------------------
# KANON_GIT_LS_REMOTE_TIMEOUT (E1-F1-S2-T1: per-attempt git ls-remote timeout)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanonGitLsRemoteTimeoutConstant:
    """KANON_GIT_LS_REMOTE_TIMEOUT constant is defined in constants.py via _env_int."""

    def test_constant_is_importable(self) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT is importable from kanon_cli.constants."""
        from kanon_cli.constants import KANON_GIT_LS_REMOTE_TIMEOUT

        assert KANON_GIT_LS_REMOTE_TIMEOUT is not None

    def test_constant_is_positive_integer(self) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT is a positive integer."""
        from kanon_cli.constants import KANON_GIT_LS_REMOTE_TIMEOUT

        assert isinstance(KANON_GIT_LS_REMOTE_TIMEOUT, int)
        assert KANON_GIT_LS_REMOTE_TIMEOUT > 0

    def test_constant_default_is_30(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT defaults to 30 when env var is unset."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.delenv("KANON_GIT_LS_REMOTE_TIMEOUT", raising=False)
        importlib.reload(constants)

        assert constants.KANON_GIT_LS_REMOTE_TIMEOUT == 30

    def test_constant_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT reflects the KANON_GIT_LS_REMOTE_TIMEOUT env var."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_GIT_LS_REMOTE_TIMEOUT", "45")
        importlib.reload(constants)

        assert constants.KANON_GIT_LS_REMOTE_TIMEOUT == 45
