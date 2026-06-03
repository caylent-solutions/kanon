"""Unit tests for the Levenshtein edit-distance helper.

Covers:
- Identical strings -> 0
- Single insertion -> 1
- Single deletion -> 1
- Single substitution -> 1
- Empty vs non-empty -> len(other)
- Mixed-case preserved (no normalization)
- Classic example: levenshtein("kitten", "sitting") == 3
- Symmetry: distance(a, b) == distance(b, a)
- Unicode characters counted as single characters

AC-TEST-001
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Identical strings -> 0
        ("", "", 0),
        ("foo", "foo", 0),
        ("hello world", "hello world", 0),
        # Single insertion (add one character) -> 1
        ("cat", "cats", 1),
        ("bat", "abat", 1),
        # Single deletion (remove one character) -> 1
        ("cats", "cat", 1),
        ("abat", "bat", 1),
        # Single substitution (change one character) -> 1
        ("cat", "bat", 1),
        ("foo", "boo", 1),
        # Empty vs non-empty -> len(other)
        ("", "abc", 3),
        ("", "hello", 5),
        ("", "x", 1),
        # Non-empty vs empty -> len(self)
        ("abc", "", 3),
        ("hello", "", 5),
        ("x", "", 1),
        # Mixed-case preserved: no normalization; uppercase differs from lowercase
        ("Foo", "foo", 1),
        ("FOO", "foo", 3),
        # Classic example: "kitten" vs "sitting" -> 3
        # k->s, e->i, insert g (kitten -> sitten -> sittin -> sitting = 3 edits)
        ("kitten", "sitting", 3),
        # Additional multi-edit examples
        ("saturday", "sunday", 3),
        ("abc", "xyz", 3),
        # Unicode: characters counted as single units
        ("\u03b1\u03b2\u03b3", "\u03b1\u03b2\u03b4", 1),  # alpha beta gamma -> alpha beta delta
        ("\u00e9", "\u00e8", 1),  # e-acute vs e-grave
    ],
)
class TestLevenshteinDistance:
    """Parametrized tests for levenshtein_distance(a, b)."""

    def test_distance(self, a: str, b: str, expected: int) -> None:
        """levenshtein_distance(a, b) returns the expected edit distance."""
        from kanon_cli.utils.levenshtein import levenshtein_distance

        result = levenshtein_distance(a, b)
        assert result == expected, f"levenshtein_distance({a!r}, {b!r}) expected {expected}, got {result}"

    def test_symmetry(self, a: str, b: str, expected: int) -> None:
        """levenshtein_distance is symmetric: distance(a, b) == distance(b, a)."""
        from kanon_cli.utils.levenshtein import levenshtein_distance

        assert levenshtein_distance(a, b) == levenshtein_distance(b, a), (
            f"levenshtein_distance({a!r}, {b!r}) != levenshtein_distance({b!r}, {a!r})"
        )


@pytest.mark.unit
class TestLevenshteinReturnType:
    """Type and value invariants for levenshtein_distance."""

    def test_returns_int(self) -> None:
        """Return value is always an int."""
        from kanon_cli.utils.levenshtein import levenshtein_distance

        result = levenshtein_distance("abc", "xyz")
        assert isinstance(result, int)

    def test_returns_non_negative(self) -> None:
        """Return value is always non-negative."""
        from kanon_cli.utils.levenshtein import levenshtein_distance

        for a, b in [("abc", "xyz"), ("", ""), ("foo", "foo"), ("x", "")]:
            assert levenshtein_distance(a, b) >= 0, f"levenshtein_distance({a!r}, {b!r}) returned a negative value"

    def test_empty_string_both_is_zero(self) -> None:
        """Two empty strings have distance 0."""
        from kanon_cli.utils.levenshtein import levenshtein_distance

        assert levenshtein_distance("", "") == 0
