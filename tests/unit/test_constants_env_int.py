"""Tests for the _env_int helper in kanon_cli.constants.

Covers:
- parse-success: valid integer string returns the integer
- default: unset variable returns the default
- malformed-value: non-integer string raises SystemExit naming the variable
"""

import importlib
import sys

import pytest


# ---------------------------------------------------------------------------
# Helper: reload constants module with a specific env-var set
# ---------------------------------------------------------------------------


def _reload_constants_with_env(monkeypatch, env_updates: dict) -> object:
    """Reload kanon_cli.constants in a subprocess-equivalent manner.

    Because constants are computed at module import time, we must unload and
    re-import the module after mutating the environment.
    """
    for key, value in env_updates.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    if "kanon_cli.constants" in sys.modules:
        del sys.modules["kanon_cli.constants"]
    return importlib.import_module("kanon_cli.constants")


# ---------------------------------------------------------------------------
# AC-2: _env_int helper exists and is callable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvIntHelperExists:
    def test_env_int_is_callable(self) -> None:
        import kanon_cli.constants as constants

        assert callable(constants._env_int)

    def test_env_int_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KANON_TEST_VAR_MISSING", raising=False)
        import kanon_cli.constants as constants

        result = constants._env_int("KANON_TEST_VAR_MISSING", 42)
        assert result == 42

    def test_env_int_returns_parsed_int_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_TEST_VAR_VALID", "99")
        import kanon_cli.constants as constants

        result = constants._env_int("KANON_TEST_VAR_VALID", 42)
        assert result == 99

    @pytest.mark.parametrize(
        "var_name,bad_value",
        [
            ("KANON_TEST_VAR_BAD", "abc"),
            ("KANON_TEST_VAR_BAD", "1.5"),
            ("KANON_TEST_VAR_BAD", ""),
            ("KANON_TEST_VAR_BAD", "twelve"),
        ],
    )
    def test_env_int_raises_system_exit_on_malformed_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        var_name: str,
        bad_value: str,
    ) -> None:
        monkeypatch.setenv(var_name, bad_value)
        import kanon_cli.constants as constants

        with pytest.raises(SystemExit) as exc_info:
            constants._env_int(var_name, 42)
        assert str(exc_info.value.code) is not None
        assert var_name in str(exc_info.value.code)

    def test_env_int_system_exit_message_names_the_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_MY_SPECIAL_VAR", "not_a_number")
        import kanon_cli.constants as constants

        with pytest.raises(SystemExit) as exc_info:
            constants._env_int("KANON_MY_SPECIAL_VAR", 7)
        assert "KANON_MY_SPECIAL_VAR" in str(exc_info.value.code)


# ---------------------------------------------------------------------------
# AC-2: the 3 previously-unguarded constants route through _env_int
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnguardedConstantsUseEnvInt:
    def test_kanon_tree_no_filter_threshold_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_TREE_NO_FILTER_THRESHOLD": None})
        assert constants.KANON_TREE_NO_FILTER_THRESHOLD == 20

    def test_kanon_tree_no_filter_threshold_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_TREE_NO_FILTER_THRESHOLD": "30"})
        assert constants.KANON_TREE_NO_FILTER_THRESHOLD == 30

    def test_kanon_tree_no_filter_threshold_malformed_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _reload_constants_with_env(monkeypatch, {"KANON_TREE_NO_FILTER_THRESHOLD": "bad"})
        # non-zero exit (SystemExit message, not numeric code)
        assert exc_info.value.code is not None
        assert "KANON_TREE_NO_FILTER_THRESHOLD" in str(exc_info.value.code)

    def test_kanon_list_limit_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_LIST_LIMIT": None})
        assert constants.KANON_LIST_LIMIT == 50

    def test_kanon_list_limit_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_LIST_LIMIT": "25"})
        assert constants.KANON_LIST_LIMIT == 25

    def test_kanon_list_limit_malformed_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _reload_constants_with_env(monkeypatch, {"KANON_LIST_LIMIT": "abc"})
        assert exc_info.value.code is not None
        assert "KANON_LIST_LIMIT" in str(exc_info.value.code)

    def test_kanon_outdated_json_indent_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_OUTDATED_JSON_INDENT": None})
        assert constants.KANON_OUTDATED_JSON_INDENT == 2

    def test_kanon_outdated_json_indent_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constants = _reload_constants_with_env(monkeypatch, {"KANON_OUTDATED_JSON_INDENT": "4"})
        assert constants.KANON_OUTDATED_JSON_INDENT == 4

    def test_kanon_outdated_json_indent_malformed_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _reload_constants_with_env(monkeypatch, {"KANON_OUTDATED_JSON_INDENT": "two"})
        assert exc_info.value.code is not None
        assert "KANON_OUTDATED_JSON_INDENT" in str(exc_info.value.code)
