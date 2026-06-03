"""Levenshtein edit-distance helper.

Provides a single public function ``levenshtein_distance(a, b)`` that returns
the standard Levenshtein edit distance (insertions, deletions, substitutions;
no transpositions) between two strings.

The implementation uses the standard two-row dynamic-programming algorithm to
keep memory usage O(min(len(a), len(b))) rather than O(len(a) * len(b)).

No external dependencies.
"""

from __future__ import annotations


def levenshtein_distance(a: str, b: str) -> int:
    """Return the Levenshtein edit distance between strings a and b.

    The distance is the minimum number of single-character edits (insertions,
    deletions, or substitutions) required to change one string into the other.
    Transpositions are NOT counted as a single edit (this is pure Levenshtein,
    not Damerau-Levenshtein).

    Properties:
    - levenshtein_distance(a, a) == 0 for any a.
    - levenshtein_distance("", s) == len(s) for any s.
    - levenshtein_distance(a, b) == levenshtein_distance(b, a) (symmetric).
    - Result is always a non-negative integer.
    - Character comparisons are case-sensitive (no normalization performed).
    - Unicode characters are counted as single units.

    Args:
        a: First input string.
        b: Second input string.

    Returns:
        The Levenshtein edit distance as a non-negative integer.
    """
    # Base cases: one string is empty.
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)

    # Ensure `a` is the shorter string to minimise memory use for the DP row.
    if len(a) > len(b):
        a, b = b, a

    len_a = len(a)
    len_b = len(b)

    # Two-row DP: previous row and current row.
    # previous[j] = edit distance between a[:i] and b[:j].
    previous = list(range(len_b + 1))
    current = [0] * (len_b + 1)

    for i in range(1, len_a + 1):
        current[0] = i
        for j in range(1, len_b + 1):
            if a[i - 1] == b[j - 1]:
                cost = 0
            else:
                cost = 1
            current[j] = min(
                previous[j] + 1,  # deletion from a
                current[j - 1] + 1,  # insertion into a
                previous[j - 1] + cost,  # substitution
            )
        previous, current = current, previous

    return previous[len_b]
