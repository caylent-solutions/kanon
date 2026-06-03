"""Parametrized unit tests for output sanitization (spec Section 11.3).

Covers:
- Clean entries pass through unchanged (AC-FUNC-001).
- Entries with newline are dropped with reason containing "newline" (AC-FUNC-002).
- Entries with NUL are dropped with reason containing "NUL" (AC-FUNC-003).
- Entries with shell metacharacters are dropped with specific reason (AC-FUNC-004).
- Entries with control characters below 0x20 (other than newline) are dropped (AC-FUNC-005).
- Mixed list preserves order and collects dropped entries (AC-FUNC-006).
- Empty input returns empty output (AC-TEST-001 coverage).
- SanitizationError carries reason and entry (AC-TEST-001 coverage).
"""

from __future__ import annotations

import pytest

from kanon_cli.completions.sanitize import SanitizationError, sanitize_entries
from kanon_cli.constants import SHELL_METACHARS


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- clean entries pass through unchanged
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_entries_pass_through() -> None:
    """Clean entries are all kept; dropped is empty."""
    entries = ["foo", "bar-baz", "1.0.0+local.build"]
    result = sanitize_entries(entries, completer_name="__complete_test")
    assert result.kept == ["foo", "bar-baz", "1.0.0+local.build"]
    assert result.dropped == []


# ---------------------------------------------------------------------------
# AC-FUNC-002 -- newline triggers drop with "newline" in reason
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_newline_entry_is_dropped() -> None:
    """Entry containing \\n is dropped; reason includes 'newline'."""
    result = sanitize_entries(["bad\nentry"], completer_name="__complete_test")
    assert result.kept == []
    assert len(result.dropped) == 1
    entry, reason = result.dropped[0]
    assert entry == "bad\nentry"
    assert "newline" in reason


@pytest.mark.unit
def test_carriage_return_entry_is_dropped() -> None:
    """Entry containing \\r is dropped; reason includes 'newline'."""
    result = sanitize_entries(["bad\rentry"], completer_name="__complete_test")
    assert result.kept == []
    assert len(result.dropped) == 1
    _entry, reason = result.dropped[0]
    assert "newline" in reason


# ---------------------------------------------------------------------------
# AC-FUNC-003 -- NUL triggers drop with "NUL" in reason
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nul_entry_is_dropped() -> None:
    """Entry containing \\x00 is dropped; reason includes 'NUL'."""
    result = sanitize_entries(["bad\x00entry"], completer_name="__complete_test")
    assert result.kept == []
    assert len(result.dropped) == 1
    _entry, reason = result.dropped[0]
    assert "NUL" in reason


# ---------------------------------------------------------------------------
# AC-FUNC-004 -- shell metacharacters each trigger drop naming the character
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("metachar", list(SHELL_METACHARS))
def test_shell_metachar_entry_is_dropped(metachar: str) -> None:
    """Entry containing a shell metacharacter is dropped; reason names the char."""
    entry = f"pre{metachar}post"
    result = sanitize_entries([entry], completer_name="__complete_test")
    assert result.kept == []
    assert len(result.dropped) == 1
    dropped_entry, reason = result.dropped[0]
    assert dropped_entry == entry
    assert metachar in reason


# ---------------------------------------------------------------------------
# AC-FUNC-005 -- control character below 0x20 (other than newline) drops entry
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "ctrl_char",
    [
        "\x07",  # bell
        "\x01",  # SOH
        "\x08",  # backspace
        "\x1f",  # unit separator (highest control char below 0x20)
    ],
)
def test_control_char_entry_is_dropped(ctrl_char: str) -> None:
    """Entry containing a control char below 0x20 is dropped; reason names the byte value."""
    entry = f"pre{ctrl_char}post"
    result = sanitize_entries([entry], completer_name="__complete_test")
    assert result.kept == []
    assert len(result.dropped) == 1
    dropped_entry, reason = result.dropped[0]
    assert dropped_entry == entry
    # Reason must name the byte value (e.g. "0x07").
    expected_hex = f"0x{ord(ctrl_char):02x}"
    assert expected_hex in reason


# ---------------------------------------------------------------------------
# AC-FUNC-006 -- mixed list preserves order; dirty entries are collected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mixed_list_preserves_order() -> None:
    """Mixed list: kept entries are in original order; dropped entries collected."""
    entries = ["clean1", "bad\nentry", "clean2", "also\x00bad", "clean3"]
    result = sanitize_entries(entries, completer_name="__complete_test")
    assert result.kept == ["clean1", "clean2", "clean3"]
    assert len(result.dropped) == 2
    dropped_entries = [e for e, _r in result.dropped]
    assert "bad\nentry" in dropped_entries
    assert "also\x00bad" in dropped_entries


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_input_returns_empty_output() -> None:
    """Empty input produces empty kept and dropped lists."""
    result = sanitize_entries([], completer_name="__complete_test")
    assert result.kept == []
    assert result.dropped == []


# ---------------------------------------------------------------------------
# SanitizationError -- carries reason and original entry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sanitization_error_carries_reason() -> None:
    """SanitizationError stores the reason string and is a valid Exception."""
    reason = "contains newline"
    err = SanitizationError(reason)
    assert str(err) == reason
    assert isinstance(err, Exception)


@pytest.mark.unit
def test_sanitization_error_is_exception_subclass() -> None:
    """SanitizationError is an Exception subclass (fail-fast contract)."""
    assert issubclass(SanitizationError, Exception)


# ---------------------------------------------------------------------------
# SHELL_METACHARS is defined in constants (AC-FUNC-008)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_shell_metachars_defined_in_constants() -> None:
    """SHELL_METACHARS must be importable from kanon_cli.constants."""
    from kanon_cli.constants import SHELL_METACHARS as SM

    assert isinstance(SM, (frozenset, str, set))
    assert len(SM) > 0


@pytest.mark.unit
def test_shell_metachars_contains_expected_chars() -> None:
    """SHELL_METACHARS includes the spec-mandated set of shell-special characters."""
    required = set("|&;<>(){}$`\\\"\\'")
    for char in required:
        assert char in SHELL_METACHARS, f"Missing metachar: {char!r}"
