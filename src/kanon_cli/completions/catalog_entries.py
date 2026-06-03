"""Dynamic completer for catalog entry names.

Implements the `kanon __complete_catalog_entries <current-token>` hidden
subcommand (spec Section 11.3 row 1).

Public API::

    complete(current_token: str) -> list[str]

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return [] immediately.
2. Resolve KANON_CATALOG_SOURCE env var to get the manifest repo URL and ref.
3. Check the catalog entry cache (catalogs/<sha>/index.txt):
   - Cache hit (fetched_at within TTL): return cached entries filtered by prefix.
   - Cache stale (fetched_at past TTL) and KANON_COMPLETION_REFRESH_BG=1:
     return stale entries and fork a background refresh.
   - Cache stale/miss and KANON_COMPLETION_REFRESH_BG=0 (or not set for miss):
     perform inline fetch bounded by KANON_COMPLETION_TIMEOUT.
4. Filter by case-sensitive prefix match against current_token.
5. Emit one name per line to stdout.

Failure contract (spec Section 11.3):
- stdout is empty on any error.
- Every error path appends a structured line to completion-errors.log.
- KANON_COMPLETION_ENABLED=0 does NOT touch the cache or log.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from kanon_cli.completions.cache import (
    catalog_entry_dir,
    log_completion_error,
    read_entries,
    read_epoch,
    write_entries,
    write_epoch,
)
from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    COMPLETION_MAX_ENTRY_LEN,
    COMPLETION_UNSAFE_CHARS,
    KANON_COMPLETION_CACHE_TTL,
    KANON_COMPLETION_ENABLED,
    KANON_COMPLETION_REFRESH_BG,
    KANON_COMPLETION_TIMEOUT,
)
from kanon_cli.core.catalog import _parse_catalog_source
from kanon_cli.core.metadata import CatalogMetadataParseError, _parse_catalog_metadata

_COMPLETER_NAME = "__complete_catalog_entries"


class CompletionDisabledError(RuntimeError):
    """Raised internally when KANON_COMPLETION_ENABLED=0 is detected."""


def _write_stderr_diagnostic(exc: BaseException) -> None:
    """Write a one-line diagnostic to stderr if and only if stderr is a tty.

    Per the documented contract in docs/shell-completion.md: when an error
    occurs, a brief diagnostic line is written to stderr so that interactive
    users see it immediately without having to inspect completion-errors.log.
    Non-interactive contexts (pipes, scripts) receive no stderr output.

    Args:
        exc: The exception that caused the error.
    """
    if sys.stderr.isatty():
        sys.stderr.write(f"{_COMPLETER_NAME}: {type(exc).__name__}: {exc}\n")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_safe_entry(name: str) -> bool:
    """Return True iff *name* is safe to emit as a shell completion candidate.

    Rejects empty strings, names longer than COMPLETION_MAX_ENTRY_LEN, and
    names that contain any character in COMPLETION_UNSAFE_CHARS.

    Args:
        name: The candidate entry name.

    Returns:
        True if the name is safe; False otherwise.
    """
    if not name:
        return False
    if len(name) > COMPLETION_MAX_ENTRY_LEN:
        return False
    return not any(ch in COMPLETION_UNSAFE_CHARS for ch in name)


def _build_index(repo_dir: Path) -> list[str]:
    """Parse all *-marketplace.xml files under repo_dir/repo-specs/ and return sorted names.

    Each file that fails to parse due to CatalogMetadataParseError is silently
    skipped (malformed entries must not break completion). Unexpected exceptions
    (e.g. PermissionError, IOError) are logged via log_completion_error and then
    skipped; they are not re-raised because completion must be failure-quiet on
    stdout, but they are surfaced to the error log.

    Args:
        repo_dir: Path to the cloned manifest repo root.

    Returns:
        Sorted list of safe catalog entry names found in repo-specs/.
    """
    specs_root = repo_dir / "repo-specs"
    if not specs_root.is_dir():
        return []

    names: list[str] = []
    for xml_path in specs_root.rglob("*-marketplace.xml"):
        try:
            metadata = _parse_catalog_metadata(xml_path)
        except CatalogMetadataParseError:
            continue
        except OSError as exc:
            log_completion_error(_COMPLETER_NAME, exc)
            continue
        name = metadata.name
        if _is_safe_entry(name):
            names.append(name)

    return sorted(names)


def _clone_manifest_repo(url: str, ref: str, dest: Path) -> Path:
    """Clone the manifest repo at url@ref into dest and return dest.

    Uses `git clone --depth 1 --branch <ref>` via subprocess.  On timeout
    or git failure, raises an exception; the caller is responsible for
    logging the error.

    Args:
        url: Git repository URL.
        ref: Branch or tag ref to clone.
        dest: Directory path to clone into.

    Returns:
        dest (the cloned repo root).

    Raises:
        RuntimeError: When git clone exits non-zero.
        TimeoutError: When the clone exceeds the configured timeout.
    """
    timeout = int(os.environ.get("KANON_COMPLETION_TIMEOUT", KANON_COMPLETION_TIMEOUT))
    cmd = ["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"git clone timed out after {timeout}s: {url}@{ref}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"git clone failed for {url}@{ref} (exit {result.returncode}): {result.stderr.strip()}")
    return dest


def _fetch_and_cache(url: str, ref: str, entry_dir: Path) -> list[str]:
    """Clone the manifest repo, build index, write cache, return names.

    Args:
        url: Git repository URL.
        ref: Branch or tag ref.
        entry_dir: Cache entry directory (catalogs/<sha>/).

    Returns:
        Sorted list of safe catalog entry names.

    Raises:
        RuntimeError: When git clone fails.
        TimeoutError: When the clone times out.
    """
    with tempfile.TemporaryDirectory(prefix="kanon-completion-") as tmp:
        clone_dest = Path(tmp) / "repo"
        clone_dest.mkdir()
        _clone_manifest_repo(url, ref, clone_dest)
        names = _build_index(clone_dest)

    write_entries(entry_dir / "index.txt", names)
    write_epoch(entry_dir / "fetched_at.txt", int(time.time()))
    return names


def _inline_fetch(url: str, ref: str, entry_dir: Path, timeout: int) -> list[str]:
    """Perform an inline (blocking) fetch bounded by *timeout* seconds.

    Sets ``KANON_COMPLETION_TIMEOUT`` in the environment before calling
    ``_fetch_and_cache`` so that ``_clone_manifest_repo`` picks up the
    caller-supplied value via ``os.environ``.

    On any failure (network error, timeout, parse error), returns [] and
    appends a structured entry to completion-errors.log.

    Args:
        url: Git repository URL.
        ref: Branch or tag ref.
        entry_dir: Cache entry directory.
        timeout: Maximum seconds to wait for the git clone subprocess.

    Returns:
        List of catalog entry names, or [] on failure.
    """
    try:
        old_val = os.environ.get("KANON_COMPLETION_TIMEOUT")
        os.environ["KANON_COMPLETION_TIMEOUT"] = str(timeout)
        try:
            return _fetch_and_cache(url, ref, entry_dir)
        finally:
            if old_val is None:
                os.environ.pop("KANON_COMPLETION_TIMEOUT", None)
            else:
                os.environ["KANON_COMPLETION_TIMEOUT"] = old_val
    except (RuntimeError, TimeoutError, OSError) as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete(current_token: str) -> list[str]:
    """Return catalog entry names that start with *current_token*.

    Resolution contract:
    1. KANON_COMPLETION_ENABLED=0 -> return [].
    2. Read KANON_CATALOG_SOURCE from environment.
    3. Cache-hit within TTL -> return cached names filtered by prefix.
    4. Cache-stale + KANON_COMPLETION_REFRESH_BG=1 -> return stale + fork bg.
    5. Cache-miss or stale + KANON_COMPLETION_REFRESH_BG=0 -> inline fetch.
    6. Filter final list by prefix (case-sensitive).

    Args:
        current_token: Completion prefix to filter by.

    Returns:
        Sorted list of matching catalog entry names, or [] on any error.
    """
    # Step 1: completion disabled guard
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return []

    # Step 2: resolve catalog source
    source = os.environ.get(CATALOG_ENV_VAR)
    if not source:
        missing_exc = ValueError("KANON_CATALOG_SOURCE is not set")
        log_completion_error(_COMPLETER_NAME, missing_exc)
        _write_stderr_diagnostic(missing_exc)
        return []

    try:
        url, ref = _parse_catalog_source(source)
    except ValueError as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        _write_stderr_diagnostic(exc)
        return []

    # Step 3: check cache
    entry_dir = catalog_entry_dir(url, ref)
    index_path = entry_dir / "index.txt"
    fetched_path = entry_dir / "fetched_at.txt"

    ttl = int(os.environ.get("KANON_COMPLETION_CACHE_TTL", KANON_COMPLETION_CACHE_TTL))
    timeout = int(os.environ.get("KANON_COMPLETION_TIMEOUT", KANON_COMPLETION_TIMEOUT))
    refresh_bg = int(os.environ.get("KANON_COMPLETION_REFRESH_BG", KANON_COMPLETION_REFRESH_BG))

    fetched_at = read_epoch(fetched_path)
    now = int(time.time())

    if fetched_at is not None:
        age = now - fetched_at
        if age <= ttl:
            # Cache hit
            names = read_entries(index_path)
        else:
            # Cache stale
            names = read_entries(index_path)
            if refresh_bg == 1:
                # Fork background refresh; return stale contents
                _spawn_background_refresh(url, ref)
            else:
                # Inline refresh
                names = _inline_fetch(url, ref, entry_dir, timeout)
    else:
        # Cache miss -- inline fetch
        names = _inline_fetch(url, ref, entry_dir, timeout)

    # Filter by prefix (case-sensitive)
    return [n for n in names if n.startswith(current_token)]


def _spawn_background_refresh(url: str, ref: str) -> None:
    """Spawn a detached subprocess to refresh the completion cache.

    The child process is fully detached (start_new_session=True) so it
    outlives the parent shell completion callback.

    Args:
        url: Git repository URL.
        ref: Branch or tag ref.
    """
    source = f"{url}@{ref}"
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "__complete_catalog_entries",
            "--refresh-only",
        ],
        env={**os.environ, CATALOG_ENV_VAR: source, "KANON_COMPLETION_REFRESH_BG": "0"},
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__complete_catalog_entries`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "__complete_catalog_entries",
        help=argparse.SUPPRESS,
        description="Internal hidden subcommand for shell completion of catalog entry names.",
    )
    parser.add_argument(
        "current_token",
        nargs="?",
        default="",
        metavar="<prefix>",
        help="Completion prefix to filter results.",
    )
    parser.add_argument(
        "--refresh-only",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(func=_handle)


def _handle(args: argparse.Namespace) -> int:
    """Argparse entry point for ``__complete_catalog_entries``.

    Calls ``complete()`` and, unless ``--refresh-only`` was given, prints
    one name per line to stdout.  When ``--refresh-only`` is set (set by the
    background-refresh subprocess spawned via ``_spawn_background_refresh``),
    the cache is refreshed but nothing is printed -- the spawner has already
    returned stale output to the shell.

    Always exits 0 -- the completer is failure-quiet on stdout.

    Args:
        args: Parsed argparse namespace.  ``args.current_token`` is the
            completion prefix; ``args.refresh_only`` suppresses stdout output.

    Returns:
        Always 0.
    """
    names = complete(args.current_token)
    if not args.refresh_only:
        for name in names:
            sys.stdout.write(f"{name}\n")
    return 0
