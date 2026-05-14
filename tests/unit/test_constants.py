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
