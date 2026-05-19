"""Output sanitizer for shell-completion candidates (spec Section 11.3).

Implements the sanitization described in spec Section 11.3 "Output
sanitization" and the Section 3.6 trust model ("Completion candidates
are shell-escaped").

Rejected character classes (all checked in a single O(n) pass per entry):
- ASCII NUL (0x00).
- ASCII newline (0x0a) or carriage return (0x0d).
- Any character in SHELL_METACHARS (see kanon_cli.constants).
- Any other character below 0x20 (control characters).

Public API::

    class SanitizationError(Exception): ...

    class SanitizationResult(NamedTuple):
        kept: list[str]
        dropped: list[tuple[str, str]]   # (entry, rejection_reason)

    def sanitize_entries(
        entries: Iterable[str],
        completer_name: str,
    ) -> SanitizationResult: ...
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from kanon_cli.constants import SHELL_METACHARS


class SanitizationError(Exception):
    """Raised (and logged) when a completion candidate is rejected.

    The message describes the specific rejected character so operators can
    diagnose the source of malformed catalog entries.
    """


class SanitizationResult(NamedTuple):
    """Result of a sanitize_entries() call.

    Attributes:
        kept: Entries that passed all checks, in original order.
        dropped: (entry, rejection_reason) pairs for rejected entries,
            in the order they were encountered.
    """

    kept: list[str]
    dropped: list[tuple[str, str]]


def sanitize_entries(
    entries: Iterable[str],
    completer_name: str,
) -> SanitizationResult:
    """Filter completion candidates, rejecting entries with forbidden characters.

    Each entry is scanned character-by-character in a single pass (O(n) per
    entry, where n is the entry length). On the first forbidden character the
    entry is immediately dropped with a descriptive reason; no further scanning
    of that entry occurs.

    Forbidden characters (checked in order within the single pass):
    - NUL (0x00) -- "contains NUL"
    - Newline (0x0a) or carriage return (0x0d) -- "contains newline"
    - Shell metacharacters from SHELL_METACHARS -- "contains shell metacharacter '<c>'"
    - Any character with code < 0x20 (control chars) -- "contains control char 0xNN"

    Args:
        entries: Iterable of candidate strings to check.
        completer_name: The name of the calling completer (used by the
            caller to log dropped entries via log_completion_error).

    Returns:
        A SanitizationResult with .kept (clean entries in original order)
        and .dropped (list of (entry, reason) pairs for rejected entries).
    """
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []

    for entry in entries:
        reject_reason: str | None = None
        for char in entry:
            code = ord(char)
            if code == 0x00:
                reject_reason = "contains NUL"
                break
            if char in ("\n", "\r"):
                reject_reason = "contains newline"
                break
            if char in SHELL_METACHARS:
                reject_reason = f"contains shell metacharacter {char!r}"
                break
            if code < 0x20:
                reject_reason = f"contains control char {code:#04x}"
                break

        if reject_reason is None:
            kept.append(entry)
        else:
            dropped.append((entry, reject_reason))

    return SanitizationResult(kept=kept, dropped=dropped)
