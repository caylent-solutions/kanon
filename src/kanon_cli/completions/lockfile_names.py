"""Dynamic completer for names recorded in the .kanon.lock lockfile.

Implements the `kanon __complete_names_in_lockfile <current-token>` hidden
subcommand (spec Section 11.3 row 3).

Public API::

    complete(current_token: str) -> list[str]

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return [] immediately (no file read).
2. Resolve the lockfile path from the three-tier precedence chain:
   a. ${KANON_LOCK_FILE} environment variable.
   b. ${KANON_KANON_FILE} + ".lock" (derived from the kanon file path).
   c. ./.kanon.lock (default derived from KANON_KANON_FILE_DEFAULT).
3. Read and parse the TOML lockfile via core.lockfile.read_lockfile().
4. Enumerate all names:
   - Every top-level SourceEntry.name.
   - Every transitive IncludeEntry.path_in_repo (recursive through nested
     includes, depth-bounded by the lockfile reader's recursion limit).
   - Every ProjectEntry.url.
5. Deduplicate, sort, and filter by prefix-match against current_token.

Failure contract (spec Section 11.3):
- stdout is empty on any error.
- Every error path appends a structured line to completion-errors.log.
- KANON_COMPLETION_ENABLED=0 does NOT touch the cache or log.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from kanon_cli.completions.cache import log_completion_error
from kanon_cli.constants import (
    KANON_COMPLETION_ENABLED,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
)
from kanon_cli.core.lockfile import (
    IncludeEntry,
    Lockfile,
    LockfileSchemaError,
    LockfileValidationError,
    read_lockfile,
)
from kanon_cli.utils.lock_file_path import derive_lock_file_path

_COMPLETER_NAME = "__complete_names_in_lockfile"


def _collect_include_paths(includes: list[IncludeEntry]) -> list[str]:
    """Recursively collect path_in_repo values from all nested includes.

    Traverses the full include tree depth-first. The recursion depth is
    bounded by the lockfile reader's own recursion limit enforced during
    parsing: deeply nested structures that exceed the reader's limit are
    rejected at parse time, so this function never encounters unbounded depth.

    Args:
        includes: List of IncludeEntry objects to traverse.

    Returns:
        Flat list of path_in_repo strings from all nested include entries.
    """
    paths: list[str] = []
    for entry in includes:
        paths.append(entry.path_in_repo)
        paths.extend(_collect_include_paths(entry.includes))
    return paths


def _extract_names(lockfile: Lockfile) -> list[str]:
    """Extract all completion candidates from a parsed Lockfile.

    Collects:
    - Every top-level SourceEntry.name.
    - Every transitive IncludeEntry.path_in_repo (recursive).
    - Every ProjectEntry.url.

    Results are deduplicated and sorted before return.

    Args:
        lockfile: A fully parsed Lockfile instance.

    Returns:
        Sorted, deduplicated list of completion candidate strings.
    """
    candidates: set[str] = set()

    for source in lockfile.sources:
        candidates.add(source.name)
        for path in _collect_include_paths(source.includes):
            candidates.add(path)
        for project in source.projects:
            candidates.add(project.url)

    return sorted(candidates)


def complete(current_token: str) -> list[str]:
    """Return lockfile names that start with current_token.

    Resolution contract:
    1. KANON_COMPLETION_ENABLED=0 -> return [].
    2. Resolve the lockfile path from the three-tier chain.
    3. Parse the lockfile; extract source names, include paths, project URLs.
    4. Filter by prefix (case-sensitive).
    5. On any error: log to completion-errors.log and return [].

    Args:
        current_token: Completion prefix to filter by.

    Returns:
        Sorted list of matching lockfile names, or [] on any error.
    """
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return []

    lock_path = derive_lock_file_path(
        kanon_file_path=Path(os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT)),
        cli_lock_file=None,
        env_lock_file=os.environ.get(KANON_LOCK_FILE),
    )

    try:
        lockfile = read_lockfile(lock_path)
    except (
        FileNotFoundError,
        LockfileSchemaError,
        LockfileValidationError,
        ValueError,
        KeyError,
        OSError,
    ) as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        return []

    names = _extract_names(lockfile)
    return [n for n in names if n.startswith(current_token)]


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__complete_names_in_lockfile`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        _COMPLETER_NAME,
        help=argparse.SUPPRESS,
        description="Internal hidden subcommand for shell completion of lockfile names.",
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
    """Argparse entry point for ``__complete_names_in_lockfile``.

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
