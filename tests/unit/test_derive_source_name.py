"""Unit tests for the derive_source_name() helper.

Covers every acceptance criterion from E2-F3-S1-T1:
  - AC-FUNC-002: lowercase-only inputs pass through unchanged.
  - AC-FUNC-003: uppercase inputs are lowercased.
  - AC-FUNC-004: hyphens are replaced with underscores.
  - AC-FUNC-005: mixed-case inputs with hyphens normalised correctly.
  - AC-FUNC-006: digits and underscores pass through.
  - AC-FUNC-007: idempotence property.
  - AC-FUNC-008: inputs with characters outside [a-zA-Z0-9_-] emit a stderr warning.
  - AC-FUNC-009: empty string returns empty string, no warning.
  - AC-CYCLE-001: end-to-end enumeration of the seven spec-documented shapes.
"""

import re

import pytest

from kanon_cli.core.metadata import derive_source_name


# ---------------------------------------------------------------------------
# AC-FUNC-002: lowercase-only inputs pass through unchanged
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("foo", "foo"),
        ("bar", "bar"),
        ("helloworld", "helloworld"),
        ("abc123", "abc123"),
        ("foo_bar", "foo_bar"),
    ],
)
def test_lowercase_inputs_pass_through(entry_name: str, expected: str) -> None:
    """AC-FUNC-002: lowercase-only inputs are returned unchanged."""
    assert derive_source_name(entry_name) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-003: uppercase inputs are lowercased
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("Foo", "foo"),
        ("FOO", "foo"),
        ("BAR", "bar"),
        ("MyPackage", "mypackage"),
        ("HELLOWORLD", "helloworld"),
    ],
)
def test_uppercase_inputs_are_lowercased(entry_name: str, expected: str) -> None:
    """AC-FUNC-003: uppercase characters are converted to lowercase."""
    assert derive_source_name(entry_name) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-004: hyphens are replaced with underscores
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("foo-bar", "foo_bar"),
        ("foo-bar-baz", "foo_bar_baz"),
        ("a-b-c-d", "a_b_c_d"),
        ("-leading", "_leading"),
        ("trailing-", "trailing_"),
    ],
)
def test_hyphens_replaced_with_underscores(entry_name: str, expected: str) -> None:
    """AC-FUNC-004: every hyphen in the input is replaced with an underscore."""
    assert derive_source_name(entry_name) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-005: mixed-case inputs with hyphens normalised correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("Foo-Bar", "foo_bar"),
        ("FOO-BAR", "foo_bar"),
        ("My-Package-Name", "my_package_name"),
        ("CamelCase-Hyphen", "camelcase_hyphen"),
    ],
)
def test_mixed_case_with_hyphens_normalised(entry_name: str, expected: str) -> None:
    """AC-FUNC-005: mixed-case inputs with hyphens are fully normalised."""
    assert derive_source_name(entry_name) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-006: digits and underscores pass through
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("foo_1", "foo_1"),
        ("foo-1", "foo_1"),
        ("pkg_2_0", "pkg_2_0"),
        ("123", "123"),
        ("foo_bar_123", "foo_bar_123"),
    ],
)
def test_digits_and_underscores_pass_through(entry_name: str, expected: str) -> None:
    """AC-FUNC-006: digits and underscores are unchanged by the transformation."""
    assert derive_source_name(entry_name) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-007 / AC-TEST-002: idempotence property (at least 8 distinct inputs)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name",
    [
        "foo",
        "foo_bar",
        "foo_bar_baz",
        "helloworld",
        "abc123",
        "my_package_name",
        "foo_1",
        "pkg_2_0",
        "lowercase_with_underscore",
        "123",
    ],
)
def test_idempotence(entry_name: str) -> None:
    """AC-FUNC-007 / AC-TEST-002: derive_source_name(derive_source_name(x)) == derive_source_name(x)."""
    once = derive_source_name(entry_name)
    twice = derive_source_name(once)
    assert once == twice, (
        f"Idempotence violated: derive_source_name({entry_name!r}) = {once!r}, "
        f"but derive_source_name({once!r}) = {twice!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-008: characters outside [a-zA-Z0-9_-] emit a stderr warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected_output",
    [
        ("foo.bar", "foo.bar"),
        ("foo bar", "foo bar"),
        ("foo@bar", "foo@bar"),
        ("foo/bar", "foo/bar"),
        ("foo!bar", "foo!bar"),
    ],
)
def test_special_chars_emit_warning_and_still_transform(
    entry_name: str, expected_output: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-FUNC-008: inputs with chars outside [a-zA-Z0-9_-] emit a stderr warning.

    The function still returns the lowercase + hyphen-to-underscore result.
    """
    result = derive_source_name(entry_name)
    assert result == expected_output.lower().replace("-", "_")
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert entry_name in captured.err or "characters outside" in captured.err


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name",
    [
        "foo.bar",
        "\u03b1-pkg",  # Greek alpha -- Unicode outside ASCII set
        "pkg with spaces",
        "has#hash",
    ],
)
def test_unicode_and_special_chars_emit_warning(entry_name: str, capsys: pytest.CaptureFixture[str]) -> None:
    """AC-FUNC-008: Unicode and special characters outside [a-zA-Z0-9_-] trigger a warning."""
    derive_source_name(entry_name)
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


@pytest.mark.unit
def test_warning_contains_entry_name(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-FUNC-008: the warning message names the entry that triggered it."""
    entry = "foo.bar"
    derive_source_name(entry)
    captured = capsys.readouterr()
    assert entry in captured.err


@pytest.mark.unit
def test_warning_mentions_recommended_set(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-FUNC-008: the warning mentions the recommended character set."""
    derive_source_name("bad@name")
    captured = capsys.readouterr()
    # The warning must note that the entry name contains characters outside the
    # recommended set.
    assert "recommended" in captured.err.lower() or "outside" in captured.err.lower()


# ---------------------------------------------------------------------------
# AC-FUNC-009: empty string returns empty string, no warning emitted
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_string_returns_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-FUNC-009: empty string input returns empty string with no warning."""
    result = derive_source_name("")
    assert result == ""
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err


# ---------------------------------------------------------------------------
# AC-CYCLE-001: end-to-end enumeration of spec-documented input shapes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name,expected",
    [
        ("foo", "foo"),  # lowercase-only passthrough
        ("Foo", "foo"),  # single uppercase
        ("FOO", "foo"),  # all uppercase
        ("foo-bar", "foo_bar"),  # hyphen replacement
        ("Foo-Bar", "foo_bar"),  # mixed case with hyphen
        ("foo_1", "foo_1"),  # digit and underscore
    ],
)
def test_spec_documented_shapes(entry_name: str, expected: str) -> None:
    """AC-CYCLE-001: verify spec-documented input shapes produce expected normalisation."""
    assert derive_source_name(entry_name) == expected


@pytest.mark.unit
def test_spec_foo_bar_emits_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-CYCLE-001: Foo.bar (dot outside [a-zA-Z0-9_-]) emits a character-set warning."""
    result = derive_source_name("Foo.bar")
    assert result == "foo.bar"
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    # Warning must reference the entry name
    assert "Foo.bar" in captured.err


# ---------------------------------------------------------------------------
# Regression: verify hyphen-to-underscore happens AFTER lowercase
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lowercase_before_hyphen_replacement() -> None:
    """Both transformations are applied: uppercase lowered, hyphens replaced."""
    assert derive_source_name("A-B-C") == "a_b_c"


# ---------------------------------------------------------------------------
# Regression: pure underscore inputs remain unchanged
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_already_canonical_form_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """A fully-canonical input (already lower, no hyphens) is returned as-is without warning."""
    result = derive_source_name("foo_bar_baz")
    assert result == "foo_bar_baz"
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err


# ---------------------------------------------------------------------------
# Extra: warning message format -- single line per invocation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_is_single_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Each call emits at most one WARNING line to stderr for a non-conforming input."""
    derive_source_name("bad.name")
    captured = capsys.readouterr()
    warning_lines = [ln for ln in captured.err.splitlines() if "WARNING" in ln]
    assert len(warning_lines) == 1


# ---------------------------------------------------------------------------
# Idempotence for inputs that contain special chars (warning emitted first call)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry_name",
    [
        "foo.bar",
        "foo bar",
        "foo@bar",
    ],
)
def test_idempotence_with_special_chars(entry_name: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Idempotence holds even for inputs with non-recommended characters."""
    once = derive_source_name(entry_name)
    # Check if the result is already canonical (no special chars triggering warning)
    # The second call may or may not warn depending on whether once still has special chars
    twice = derive_source_name(once)
    assert once == twice


# ---------------------------------------------------------------------------
# Pattern: warning regex contains expected set reference
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_contains_character_set_language(capsys: pytest.CaptureFixture[str]) -> None:
    """The warning emitted for non-conforming input references the character set [a-zA-Z0-9_-]."""
    derive_source_name("foo%bar")
    captured = capsys.readouterr()
    # The warning must mention chars outside the recommended set; we look for
    # some combination of the set description in the message.
    assert re.search(r"(outside|recommended|character)", captured.err, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Regression: trailing newline must be treated as outside the recommended set
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trailing_newline_triggers_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """A trailing newline in the entry name is outside [a-zA-Z0-9_-] and must emit a WARNING.

    Python's re.match() with a '$' anchor silently accepts a trailing newline
    before the end of the string. derive_source_name() must use fullmatch() (or
    equivalent) so that 'foo\\n' is correctly identified as non-conforming.
    """
    result = derive_source_name("foo\n")
    assert result == "foo\n"
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
