"""Dynamic completer for source names defined in the .kanon file.

Implements the `kanon __complete_source_names_in_kanon <current-token>` hidden
subcommand (spec Section 11.3 row 2).

Public API::

    complete(current_token: str) -> list[str]

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return [] immediately (no cache touch, no file read).
2. Resolve the .kanon file path from ${KANON_KANON_FILE} (default: ./.kanon).
3. Read the file and extract all KANON_SOURCE_<name>_URL keys.
4. Emit each <name> portion sorted alphabetically.
5. Filter by prefix-match against current_token.

Normalization contract (spec Section 11.3 row 2):
The <name> portion of KANON_SOURCE_<name>_URL is the normalized source name.
It is NOT derived at completion time -- it is read directly from the key.
Normalization (derive_source_name) was applied at 'kanon add' time and is
one-way and lossy. The original entry name cannot be recovered.

Failure contract (spec Section 11.3):
- stdout is empty on any error.
- Every error path appends a structured line to completion-errors.log.
- KANON_COMPLETION_ENABLED=0 does NOT touch the cache or log.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from kanon_cli.completions.cache import log_completion_error
from kanon_cli.constants import (
    KANON_COMPLETION_ENABLED,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    SOURCE_PREFIX,
    SOURCE_URL_SUFFIX,
)

_COMPLETER_NAME = "__complete_source_names_in_kanon"

# Pattern that matches KANON_SOURCE_<name>_URL where <name> is non-empty.
_SOURCE_URL_RE = re.compile(
    r"^" + re.escape(SOURCE_PREFIX) + r"(.+)" + re.escape(SOURCE_URL_SUFFIX) + r"\s*=",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_kanon_file() -> Path:
    """Return the Path to the active .kanon file.

    Resolution order (highest wins):
    1. ${KANON_KANON_FILE} environment variable.
    2. ./.kanon (KANON_KANON_FILE_DEFAULT).

    Returns:
        Path to the .kanon file (may or may not exist on disk).
    """
    env_val = os.environ.get(KANON_KANON_FILE_ENV)
    if env_val:
        return Path(env_val)
    return Path(KANON_KANON_FILE_DEFAULT)


def _extract_source_names(content: str) -> list[str]:
    """Parse KANON_SOURCE_<name>_URL keys from raw .kanon file text.

    Scans each line for the pattern KANON_SOURCE_<name>_URL=... and
    returns the sorted list of non-empty <name> portions.

    Args:
        content: Raw text content of the .kanon file.

    Returns:
        Sorted list of source names extracted from KANON_SOURCE_<name>_URL keys.
        Returns an empty list when no such keys are found.
    """
    names: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _SOURCE_URL_RE.match(stripped)
        if m:
            name = m.group(1)
            if name:
                names.append(name)
    return sorted(names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete(current_token: str) -> list[str]:
    """Return source names from the .kanon file that start with current_token.

    Resolution contract:
    1. KANON_COMPLETION_ENABLED=0 -> return [].
    2. Read the .kanon file from ${KANON_KANON_FILE} (default: ./.kanon).
    3. Extract KANON_SOURCE_<name>_URL keys; return sorted <name> list.
    4. Filter by prefix (case-sensitive).
    5. On any error: log to completion-errors.log and return [].

    Args:
        current_token: Completion prefix to filter by.

    Returns:
        Sorted list of matching source names, or [] on any error.
    """
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return []

    kanon_path = _resolve_kanon_file()

    try:
        content = kanon_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        return []

    names = _extract_source_names(content)
    if not names:
        log_completion_error(
            _COMPLETER_NAME,
            ValueError(f"No KANON_SOURCE_*_URL keys found in {kanon_path}"),
        )
        return []

    return [n for n in names if n.startswith(current_token)]


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__complete_source_names_in_kanon`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        _COMPLETER_NAME,
        help=argparse.SUPPRESS,
        description="Internal hidden subcommand for shell completion of .kanon source names.",
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
    """Argparse entry point for ``__complete_source_names_in_kanon``.

    Calls ``complete()`` and prints one name per line to stdout.
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
