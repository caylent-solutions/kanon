"""Dynamic completer for catalog version tags and branches.

Implements the ``kanon __complete_catalog_versions <current-token>`` hidden
subcommand (spec Section 11.3 row 4).

Public API::

    complete(current_token: str) -> list[str]

Resolution chain:
1. If KANON_COMPLETION_ENABLED=0, return [] immediately.
2. Resolve KANON_CATALOG_SOURCE env var to get the manifest repo URL and ref.
3. Check the catalog versions cache (catalogs/<sha>/tags.txt):
   - Cache hit (fetched_at within TTL): return cached entries filtered by prefix.
   - Cache stale (fetched_at past TTL) + KANON_COMPLETION_REFRESH_BG=1:
     return stale entries and spawn a background refresh.
   - Cache stale/miss: perform inline fetch via git ls-remote bounded by
     KANON_COMPLETION_TIMEOUT.
4. Apply PEP 440 filter: tags whose last path component is not parseable as
   a PEP 440 version are EXCLUDED. Branches pass through unfiltered.
5. Deduplicate, sort (tags by Version ordering, then branches alphabetically),
   filter by prefix-match against current_token.
6. Emit one ref name per line to stdout.

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
import time
from pathlib import Path

from packaging.version import Version

from kanon_cli.completions.cache import (
    catalog_entry_dir,
    log_completion_error,
    read_entries,
    read_epoch,
    write_entries,
    write_epoch,
)
from kanon_cli.completions.pep440_filter import filter_pep440_tags
from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    KANON_COMPLETION_CACHE_TTL,
    KANON_COMPLETION_ENABLED,
    KANON_COMPLETION_REFRESH_BG,
    KANON_COMPLETION_TIMEOUT,
)
from kanon_cli.core.catalog import _parse_catalog_source

_COMPLETER_NAME = "__complete_catalog_versions"
_TAGS_FILENAME = "tags.txt"


class CompletionDisabledError(RuntimeError):
    """Raised internally when KANON_COMPLETION_ENABLED=0 is detected."""


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
# Internal helpers
# ---------------------------------------------------------------------------


def _run_ls_remote(url: str, timeout: int) -> str:
    """Run ``git ls-remote --tags --heads <url>`` and return stdout as a string.

    Args:
        url: Git repository URL to query.
        timeout: Maximum seconds to wait for the subprocess.

    Returns:
        Raw stdout string from git ls-remote.

    Raises:
        RuntimeError: When git ls-remote exits non-zero.
        TimeoutError: When the subprocess exceeds *timeout* seconds.
    """
    cmd = ["git", "ls-remote", "--tags", "--heads", url]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"git ls-remote timed out after {timeout}s: {url}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed for {url} (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _parse_ls_remote_output(output: str) -> tuple[list[str], list[str]]:
    """Parse ``git ls-remote`` output into (tags_last_components, branch_names).

    Processes each line of the form ``<sha>TAB<ref>``.  Lines matching
    ``refs/tags/<name>`` have their last path component (after the final
    ``/``) added to the tags list; deref lines ending in ``^{}`` are
    ignored.  Lines matching ``refs/heads/<name>`` have the branch name
    (everything after ``refs/heads/``) added to the branches list.

    Args:
        output: Raw stdout from ``git ls-remote --tags --heads``.

    Returns:
        A tuple of (tag_last_components, branch_names).  Tag last components
        are NOT yet PEP 440-filtered; that is the caller's responsibility.
    """
    tags: list[str] = []
    branches: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        _sha, ref = line.split("\t", 1)
        ref = ref.strip()
        # Skip annotated-tag deref lines
        if ref.endswith("^{}"):
            continue
        if ref.startswith("refs/tags/"):
            suffix = ref[len("refs/tags/") :]
            # Last path component only (handles refs/tags/release/v3 -> "v3")
            last_component = suffix.rsplit("/", 1)[-1]
            tags.append(last_component)
        elif ref.startswith("refs/heads/"):
            branch_name = ref[len("refs/heads/") :]
            branches.append(branch_name)
    return tags, branches


def _sort_versions_and_branches(
    valid_tags: list[str],
    branches: list[str],
) -> list[str]:
    """Return a merged sorted list: tags by PEP 440 ordering, then branches alphabetically.

    Deduplication is applied before sorting: if a tag name and a branch name
    share the same string, only one entry is emitted (under the tags bucket
    since it passed PEP 440 filter).

    Args:
        valid_tags: PEP 440-valid tag names (already filtered).
        branches: Branch names (not PEP 440-filtered).

    Returns:
        Deduplicated, sorted list with tags first (Version order) then
        branches (alphabetical).
    """
    seen: set[str] = set()

    # Sort tags by PEP 440 Version ordering.
    # valid_tags are guaranteed PEP 440-parseable (filter_pep440_tags was applied).
    sorted_tags: list[str] = []
    for tag in sorted(valid_tags, key=Version):
        if tag not in seen:
            sorted_tags.append(tag)
            seen.add(tag)

    sorted_branches: list[str] = []
    for branch in sorted(branches):
        if branch not in seen:
            sorted_branches.append(branch)
            seen.add(branch)

    return sorted_tags + sorted_branches


def _fetch_and_cache_versions(url: str, entry_dir: Path) -> list[str]:
    """Run git ls-remote, apply PEP 440 filter, write tags.txt, return sorted list.

    Args:
        url: Git repository URL.
        entry_dir: Cache entry directory (catalogs/<sha>/).

    Returns:
        Sorted, deduplicated list of version strings.

    Raises:
        RuntimeError: When git ls-remote fails.
        TimeoutError: When the ls-remote times out.
    """
    timeout = int(os.environ.get("KANON_COMPLETION_TIMEOUT", KANON_COMPLETION_TIMEOUT))
    raw_output = _run_ls_remote(url, timeout)
    raw_tags, branches = _parse_ls_remote_output(raw_output)
    valid_tags = filter_pep440_tags(raw_tags)
    result = _sort_versions_and_branches(valid_tags, branches)

    write_entries(entry_dir / _TAGS_FILENAME, result, completer_name=_COMPLETER_NAME)
    write_epoch(entry_dir / "fetched_at.txt", int(time.time()))
    return result


def _inline_fetch(url: str, entry_dir: Path, timeout: int) -> list[str]:
    """Perform an inline (blocking) fetch bounded by *timeout* seconds.

    Sets ``KANON_COMPLETION_TIMEOUT`` in the environment before calling
    ``_fetch_and_cache_versions`` so the subprocess picks up the caller-
    supplied value via ``os.environ``.

    On any failure, returns [] and appends a structured entry to
    completion-errors.log.

    Args:
        url: Git repository URL.
        entry_dir: Cache entry directory.
        timeout: Maximum seconds to wait for the git ls-remote subprocess.

    Returns:
        Sorted list of version strings, or [] on failure.
    """
    try:
        old_val = os.environ.get("KANON_COMPLETION_TIMEOUT")
        os.environ["KANON_COMPLETION_TIMEOUT"] = str(timeout)
        try:
            return _fetch_and_cache_versions(url, entry_dir)
        finally:
            if old_val is None:
                os.environ.pop("KANON_COMPLETION_TIMEOUT", None)
            else:
                os.environ["KANON_COMPLETION_TIMEOUT"] = old_val
    except (RuntimeError, TimeoutError, OSError) as exc:
        log_completion_error(_COMPLETER_NAME, exc)
        _write_stderr_diagnostic(exc)
        return []


def _spawn_background_refresh(url: str, catalog_source: str) -> None:
    """Spawn a detached subprocess to refresh the completion cache.

    The child process is fully detached (start_new_session=True) so it
    outlives the parent shell completion callback.

    Args:
        url: Git repository URL (unused; passed to identify the target for logging).
        catalog_source: Full ``<url>@<ref>`` value for KANON_CATALOG_SOURCE.
    """
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            _COMPLETER_NAME,
            "--refresh-only",
        ],
        env={
            **os.environ,
            CATALOG_ENV_VAR: catalog_source,
            "KANON_COMPLETION_REFRESH_BG": "0",
        },
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete(current_token: str) -> list[str]:
    """Return catalog versions that start with *current_token*.

    Resolution contract:
    1. KANON_COMPLETION_ENABLED=0 -> return [].
    2. Read KANON_CATALOG_SOURCE from environment.
    3. Cache-hit within TTL -> return cached entries filtered by prefix.
    4. Cache-stale + KANON_COMPLETION_REFRESH_BG=1 -> return stale + fork bg.
    5. Cache-miss or stale + KANON_COMPLETION_REFRESH_BG=0 -> inline fetch.
    6. Filter final list by prefix (case-sensitive).

    Args:
        current_token: Completion prefix to filter by.

    Returns:
        Sorted list of matching version strings, or [] on any error.
    """
    # Step 1: completion disabled guard
    enabled = int(os.environ.get("KANON_COMPLETION_ENABLED", KANON_COMPLETION_ENABLED))
    if enabled == 0:
        return []

    # Step 2: resolve catalog source
    source = os.environ.get(CATALOG_ENV_VAR)
    if not source:
        missing_exc = ValueError(f"{CATALOG_ENV_VAR} is not set")
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
    tags_path = entry_dir / _TAGS_FILENAME
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
            versions = read_entries(tags_path)
        else:
            # Cache stale
            versions = read_entries(tags_path)
            if refresh_bg == 1:
                _spawn_background_refresh(url, source)
            else:
                versions = _inline_fetch(url, entry_dir, timeout)
    else:
        # Cache miss -- inline fetch
        versions = _inline_fetch(url, entry_dir, timeout)

    # Filter by prefix (case-sensitive)
    return [v for v in versions if v.startswith(current_token)]


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the hidden ``__complete_catalog_versions`` subcommand.

    The subcommand is hidden from ``kanon --help`` via ``help=argparse.SUPPRESS``.

    Args:
        subparsers: The top-level argparse subparsers action.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        _COMPLETER_NAME,
        help=argparse.SUPPRESS,
        description=("Internal hidden subcommand for shell completion of catalog version tags and branches."),
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
    """Argparse entry point for ``__complete_catalog_versions``.

    Calls ``complete()`` and, unless ``--refresh-only`` was given, prints
    one version per line to stdout.  When ``--refresh-only`` is set (set by
    the background-refresh subprocess spawned via ``_spawn_background_refresh``),
    the cache is refreshed but nothing is printed -- the spawner has already
    returned stale output to the shell.

    Always exits 0 -- the completer is failure-quiet on stdout.

    Args:
        args: Parsed argparse namespace.  ``args.current_token`` is the
            completion prefix; ``args.refresh_only`` suppresses stdout output.

    Returns:
        Always 0.
    """
    versions = complete(args.current_token)
    if not args.refresh_only:
        for version in versions:
            sys.stdout.write(f"{version}\n")
    return 0
