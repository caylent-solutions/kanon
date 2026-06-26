"""TDD-paired unit tests for kanon_cli.completions.sanitize (source-test atomicity).

Covers the public API surface of sanitize_entries and SanitizationError.
The broader parametrized test matrix lives in test_completion_sanitization.py;
this file focuses on the structural contract and edge cases specific to the
sanitize module's internal design.
"""

from __future__ import annotations

import pytest

from kanon_cli.completions.sanitize import SanitizationError, SanitizationResult, sanitize_entries


@pytest.mark.unit
def test_sanitization_result_is_named_tuple() -> None:
    """SanitizationResult must be a NamedTuple with .kept and .dropped fields."""
    result = sanitize_entries([], completer_name="test")
    assert isinstance(result, SanitizationResult)
    assert hasattr(result, "kept")
    assert hasattr(result, "dropped")


@pytest.mark.unit
def test_sanitization_result_kept_type() -> None:
    """SanitizationResult.kept is a list of strings."""
    result = sanitize_entries(["foo", "bar"], completer_name="test")
    assert isinstance(result.kept, list)
    assert all(isinstance(s, str) for s in result.kept)


@pytest.mark.unit
def test_sanitization_result_dropped_type() -> None:
    """SanitizationResult.dropped is a list of (str, str) tuples."""
    result = sanitize_entries(["bad\nentry"], completer_name="test")
    assert isinstance(result.dropped, list)
    for item in result.dropped:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)


@pytest.mark.unit
def test_first_forbidden_char_determines_reason() -> None:
    """When entry has multiple forbidden chars, the first one determines the reason."""

    entry = "\x00bad\nentry"
    result = sanitize_entries([entry], completer_name="test")
    assert len(result.dropped) == 1
    _e, reason = result.dropped[0]
    assert "NUL" in reason


@pytest.mark.unit
def test_newline_before_metachar_wins() -> None:
    """When newline appears before a shell metachar, newline reason is reported."""
    entry = "bad\n|entry"
    result = sanitize_entries([entry], completer_name="test")
    assert len(result.dropped) == 1
    _e, reason = result.dropped[0]
    assert "newline" in reason
    assert "|" not in reason


@pytest.mark.unit
def test_iterable_input_accepted() -> None:
    """sanitize_entries accepts any Iterable, not just lists."""

    def gen():
        yield "clean1"
        yield "bad\x00"
        yield "clean2"

    result = sanitize_entries(gen(), completer_name="test")
    assert result.kept == ["clean1", "clean2"]
    assert len(result.dropped) == 1


@pytest.mark.unit
@pytest.mark.parametrize("name", ["__complete_catalog_entries", "", "arbitrary-name"])
def test_completer_name_parameter_accepted(name: str) -> None:
    """sanitize_entries accepts any completer_name string without raising."""
    result = sanitize_entries(["clean"], completer_name=name)
    assert result.kept == ["clean"]
    assert result.dropped == []


@pytest.mark.unit
def test_sanitization_error_message_roundtrip() -> None:
    """SanitizationError(reason) -> str(err) == reason (exact roundtrip)."""
    reason = "contains shell metacharacter '|'"
    err = SanitizationError(reason)
    assert str(err) == reason
