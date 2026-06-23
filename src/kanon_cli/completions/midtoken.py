"""Mid-token resolver for the ``kanon add <name>[@<spec>]`` completion helper.

Implements the ``kanon __resolve_entry_to_repo_url <entry-name>`` hidden
subcommand (spec Section 11.5 mid-token splitter).

Public API::

    resolve_entry_to_repo_url(entry_name: str) -> str

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return "" immediately.
2. Resolve the single KANON_CATALOG_SOURCES entry to get the manifest repo URL and ref.
3. Derive the cache directory for this catalog source.
4. Read index.txt from the cache directory.
5. If index.txt is absent (no cache for this catalog source), raise
   MidtokenCacheError: the shell-side splitter cannot produce a repo URL.
6. Search index.txt for entry_name (exact match).
7. If not found, raise EntryNotFoundError.
8. Return the catalog source URL (the manifest repo URL that IS the project URL
   for every entry it contains).

Failure contract (spec Section 11.5, aligned with Section 11.3):
- stdout is empty on any error.
- Every error path appends a structured line to completion-errors.log.
- KANON_COMPLETION_ENABLED=0 does NOT touch the cache or log.
- The shell-side splitter catches a non-zero exit code and emits no candidates.

Spec references:
- spec Section 11.5 -- mid-token splitting.
- spec Section 4.0  -- LAST-@ split rule.
- spec Section 11.3 -- failure-quiet-on-stdout / failure-loud-on-stderr.
"""

from __future__ import annotations

import argparse
import os
import sys

from kanon_cli.completions.cache import (
    catalog_entry_dir,
    log_completion_error,
    read_entries,
)
from kanon_cli.constants import (
    CATALOG_SOURCES_ENV_VAR,
    KANON_COMPLETION_ENABLED,
)
from kanon_cli.core.catalog import _parse_catalog_source, resolve_env_catalog_source

_COMPLETER_NAME = "__resolve_entry_to_repo_url"


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class EntryNotFoundError(LookupError):
    """Raised when entry_name is not found in the cached catalog index.

    The subcommand handler catches this exception, emits empty stdout, and
    logs a structured entry to completion-errors.log.

    Attributes:
        entry_name: The requested catalog entry name that was not found.
    """

    def __init__(self, entry_name: str, catalog_source: str) -> None:
        """Initialise with context for the structured log entry.

        Args:
            entry_name: The requested catalog entry name.
            catalog_source: The KANON_CATALOG_SOURCES value that was searched.
        """
        super().__init__(
            f"catalog entry {entry_name!r} not found in cached index for"
            f" catalog source {catalog_source!r};"
            f" run 'kanon __complete_catalog_entries' to warm the cache"
        )
        self.entry_name = entry_name


class MidtokenCacheError(RuntimeError):
    """Raised when the cache is missing or KANON_CATALOG_SOURCES is absent/malformed.

    The subcommand handler catches this exception, emits empty stdout, and
    logs a structured entry to completion-errors.log.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_stderr_diagnostic(exc: BaseException) -> None:
    """Write a one-line diagnostic to stderr when stderr is a tty.

    Per the documented contract in docs/shell-completion.md: when an error
    occurs, a brief diagnostic line is written to stderr so interactive users
    see it without inspecting completion-errors.log.

    Args:
        exc: The exception that caused the error.
    """
    if sys.stderr.isatty():
        sys.stderr.write(f"{_COMPLETER_NAME}: {type(exc).__name__}: {exc}\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_entry_to_repo_url(entry_name: str) -> str:
    """Return the catalog source URL for entry_name.

    The catalog source URL is the git URL of the manifest repository that
    contains the entry. Because every entry in a catalog is hosted in the same
    manifest repo, the URL is derived from the single KANON_CATALOG_SOURCES entry.

    Resolution contract (spec Section 11.5):
    1. KANON_COMPLETION_ENABLED=0 -> return "".
    2. KANON_CATALOG_SOURCES absent or malformed -> raise MidtokenCacheError.
    3. Cache directory for this catalog source absent -> raise MidtokenCacheError.
    4. entry_name found in cached index -> return catalog URL.
    5. entry_name NOT found -> raise EntryNotFoundError.

    Args:
        entry_name: The catalog entry name to look up (the portion before the
            last ``@`` in the user's completion token).

    Returns:
        The manifest repo git URL (suitable for passing to
        ``_kanon_complete_project_versions``), or ``""`` when completion is
        disabled.

    Raises:
        MidtokenCacheError: When KANON_CATALOG_SOURCES is absent/malformed or
            the catalog cache entry does not exist.
        EntryNotFoundError: When entry_name is not found in the cached index.
    """
    # Step 1: completion disabled guard.
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return ""

    # Step 2: resolve catalog source from the single KANON_CATALOG_SOURCES entry.
    try:
        source = resolve_env_catalog_source()
    except ValueError as exc:
        raise MidtokenCacheError(f"malformed {CATALOG_SOURCES_ENV_VAR}: {exc}") from exc
    if not source:
        raise MidtokenCacheError(f"{CATALOG_SOURCES_ENV_VAR} is not set; cannot resolve entry repo URL")

    try:
        url, ref = _parse_catalog_source(source)
    except ValueError as exc:
        raise MidtokenCacheError(f"malformed {CATALOG_SOURCES_ENV_VAR}={source!r}: {exc}") from exc

    # Step 3: locate the catalog cache directory.
    entry_dir = catalog_entry_dir(url, ref)
    index_path = entry_dir / "index.txt"

    if not index_path.exists():
        raise MidtokenCacheError(
            f"catalog cache not found for {source!r} (expected {index_path});"
            f" run 'kanon __complete_catalog_entries' to populate the cache"
        )

    # Step 4+5: search the cached index for entry_name.
    names = read_entries(index_path)
    if entry_name in names:
        return url

    raise EntryNotFoundError(entry_name, source)


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__resolve_entry_to_repo_url`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        _COMPLETER_NAME,
        help=argparse.SUPPRESS,
        description=(
            "Internal hidden subcommand for the mid-token splitter."
            " Given a catalog entry name, returns the catalog source URL"
            " to stdout so the shell helper can route to"
            " _kanon_complete_project_versions."
        ),
    )
    parser.add_argument(
        "entry_name",
        metavar="<entry-name>",
        help="Catalog entry name to resolve to a repo URL.",
    )
    parser.set_defaults(func=_handle)


def _handle(args: argparse.Namespace) -> int:
    """Argparse entry point for ``__resolve_entry_to_repo_url``.

    Calls ``resolve_entry_to_repo_url()`` and prints the URL to stdout.
    On any exception, logs the error to completion-errors.log, writes a
    stderr diagnostic when stderr is a tty, and returns 1 (non-zero so
    the shell-side splitter can detect failure and emit no candidates).

    Args:
        args: Parsed argparse namespace.  ``args.entry_name`` is the
            catalog entry name to resolve.

    Returns:
        0 on success (URL printed to stdout).
        1 on any error (nothing printed to stdout; error logged).
    """
    try:
        url = resolve_entry_to_repo_url(args.entry_name)
    except (EntryNotFoundError, MidtokenCacheError) as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        _write_stderr_diagnostic(exc)
        return 1

    if url:
        sys.stdout.write(f"{url}\n")
    return 0
