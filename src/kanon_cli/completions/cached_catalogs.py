"""Dynamic completer for cached catalog identifiers.

Implements the `kanon __complete_cached_catalogs <current-token>` hidden
subcommand (spec Section 11.3 row 6).

Public API::

    complete(current_token: str) -> list[str]

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return [] immediately.
2. Resolve the cache directory (<KANON_HOME>/cache) and check for a catalogs/ subdirectory.
3. If catalogs/ does not exist, return [] (first-run / empty cache -- not an error).
4. Enumerate immediate subdirectories of catalogs/; for each read origin.txt.
5. Malformed origin.txt entries (empty, no '@') are skipped with a structured log entry.
6. Emit sorted list of valid url@ref strings, prefix-filtered by current_token.

Failure contract (spec Section 11.3):
- stdout is empty on any error.
- Every error path appends a structured line to completion-errors.log.
- KANON_COMPLETION_ENABLED=0 does NOT touch the cache or log.
- Missing or empty catalogs/ is NOT an error; no log entry is written.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from kanon_cli.completions.cache import cache_dir, log_completion_error
from kanon_cli.constants import KANON_COMPLETION_ENABLED

_COMPLETER_NAME = "__complete_cached_catalogs"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_origin(origin_path: Path) -> str | None:
    """Read and validate origin.txt for a single catalog cache entry.

    Reads the first line from origin_path, strips whitespace, and validates
    that it contains an '@' separator (url@ref shape). Returns None for any
    content that does not satisfy the shape (empty, whitespace-only, or
    missing '@').

    Args:
        origin_path: Path to the origin.txt file.

    Returns:
        The stripped url@ref string if valid, or None if malformed.
    """
    content = origin_path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    if "@" not in content:
        return None
    return content


def _walk_catalogs(catalogs_dir: Path) -> tuple[list[str], list[str]]:
    """Walk catalogs/ and return (valid_origins, malformed_shas).

    Enumerates immediate subdirectories of catalogs_dir. For each
    subdirectory, attempts to read origin.txt. Subdirectories that have no
    origin.txt or a malformed origin.txt are collected in malformed_shas
    for caller-side error logging. The function never recurses into
    subdirectories of sha-named directories.

    Args:
        catalogs_dir: Path to the catalogs/ directory (may not exist).

    Returns:
        A tuple of (sorted list of valid url@ref strings, list of sha
        directory names whose origin.txt was absent or malformed).
    """
    if not catalogs_dir.is_dir():
        return [], []

    origins: list[str] = []
    malformed: list[str] = []

    for sha_dir in catalogs_dir.iterdir():
        if not sha_dir.is_dir():
            continue
        origin_path = sha_dir / "origin.txt"
        if not origin_path.is_file():
            # No origin.txt -- silently skip (spec: only origin.txt is read)
            continue
        try:
            value = _read_origin(origin_path)
        except OSError as exc:
            log_completion_error(_COMPLETER_NAME, exc)
            malformed.append(sha_dir.name)
            continue

        if value is None:
            malformed.append(sha_dir.name)
        else:
            origins.append(value)

    return sorted(origins), malformed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete(current_token: str) -> list[str]:
    """Return cached catalog url@ref strings that start with current_token.

    Resolution contract:
    1. KANON_COMPLETION_ENABLED=0 -> return [].
    2. Resolve the <KANON_HOME>/cache/catalogs/ directory.
    3. Missing or empty catalogs/ -> return [] (not an error; no log entry).
    4. Walk immediate sha-named subdirs; read origin.txt from each.
    5. Malformed origin.txt -> skip + log.
    6. Return sorted, prefix-filtered list.

    Args:
        current_token: Completion prefix to filter by.

    Returns:
        Sorted list of matching url@ref strings, or [] on any error.
    """
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return []

    catalogs_dir = cache_dir() / "catalogs"
    origins, malformed_shas = _walk_catalogs(catalogs_dir)

    for sha in malformed_shas:
        log_completion_error(
            _COMPLETER_NAME,
            ValueError(f"malformed or missing origin.txt in catalogs/{sha}"),
        )

    return [o for o in origins if o.startswith(current_token)]


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__complete_cached_catalogs`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        _COMPLETER_NAME,
        help=argparse.SUPPRESS,
        description="Internal hidden subcommand for shell completion of cached catalog identifiers.",
    )
    parser.add_argument(
        "current_token",
        nargs="?",
        default="",
        metavar="<prefix>",
        help="Completion prefix to filter results.",
    )
    parser.set_defaults(func=_handle)


def _handle(args: argparse.Namespace) -> int:
    """Argparse entry point for ``__complete_cached_catalogs``.

    Calls ``complete()`` and prints one url@ref per line to stdout.
    Always exits 0 -- the completer is failure-quiet on stdout.

    Args:
        args: Parsed argparse namespace. ``args.current_token`` is the
            completion prefix.

    Returns:
        Always 0.
    """
    names = complete(args.current_token)
    for name in names:
        sys.stdout.write(f"{name}\n")
    return 0
