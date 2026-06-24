"""Cache layout helpers for kanon shell-completion infrastructure.

Implements the directory structure and file I/O described in spec
Section 11.4.  Every directory created here has mode 0700; every file
written has mode 0600 -- enforced via os.chmod after the write so the
umask cannot weaken the permission.

Layout (all paths relative to cache_dir())::

    catalogs/
        <sha256-of-catalog-url@ref>/
            index.txt       -- one catalog entry name per line
            tags.txt        -- one PEP 440-valid tag + one branch per line
            fetched_at.txt  -- epoch seconds
            accessed_at.txt -- epoch seconds (updated on read, coalesced)
            origin.txt      -- <url>@<ref> sidecar for __complete_cached_catalogs
    projects/
        <sha256-of-canonical-project-repo-url>/
            tags.txt
            fetched_at.txt
            accessed_at.txt
            origin.txt      -- canonical <repo-url>
    completion-errors.log

Public API::

    cache_dir() -> Path
    catalog_entry_dir(catalog_url, ref) -> Path
    project_entry_dir(repo_url) -> Path
    search_entry_dir(catalog_url, ref) -> Path
    read_entries(file_path) -> list[str]
    write_entries(file_path, entries) -> None
    read_epoch(file_path) -> int | None
    write_epoch(file_path, epoch) -> None
    maybe_update_accessed_at(accessed_at_path, now, coalesce_window_seconds) -> bool
    log_completion_error(completer_name, exc) -> None
    Freshness -- enum: FRESH | STALE | MISSING
    classify(fetched_at_path, ttl_seconds, now) -> Freshness
    read_entries_with_freshness(cache_entry_dir, ttl_seconds, now, entries_filename) -> tuple[list[str], Freshness]
    read_search_versions_with_freshness(catalog_url, ref, ttl_seconds, now) -> tuple[list[str], Freshness]
    write_search_versions(catalog_url, ref, versions, now) -> None
    fork_background_refresh(refresh_fn) -> None

Security: spec Section 3.6 -- cache files are user-private.
"""

from __future__ import annotations

import enum
import functools
import hashlib
import os
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from kanon_cli.completions.sanitize import SanitizationError, sanitize_entries
from kanon_cli.constants import (
    KANON_COMPLETION_ERRORS_LOG_FILENAME,
    KANON_COMPLETION_LOG_ENV,
    KANON_COMPLETION_REFRESH_BG,
    KANON_COMPLETION_REFRESH_BG_ENV,
    KANON_HOME_CACHE_SUBDIR,
    resolve_kanon_home,
)
from kanon_cli.utils.spawn import spawn_detached

# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Default entries filename for a cache entry directory. The catalog/project
# completers store their name index in ``index.txt``; the ``search``
# version-enumeration path stores its enumerated version list under the same
# layout in ``versions.txt`` (see SEARCH_VERSIONS_FILENAME).
_DEFAULT_ENTRIES_FILENAME = "index.txt"

# Entries filename used by the ``search`` version-enumeration cache extension.
# One enumerated version string (a PEP 440 tag suffix or a branch-tip "latest"
# marker) per line, written under ``cache_dir()/search/<sha>/`` (spec
# Section 4.1 / FR-25 -- reuse the completions/cache.py TTL pattern).
SEARCH_VERSIONS_FILENAME = "versions.txt"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _chmod_secure(path: Path, mode: int) -> None:
    """Set *path* to *mode* via os.chmod after creation.

    The umask cannot be trusted to enforce owner-only permissions, so we
    always apply chmod explicitly after every mkdir / file write.
    """
    os.chmod(path, mode)


def _mkdir_secure(path: Path) -> None:
    """Create *path* (including parents) with mode 0700 on every new dir."""
    path.mkdir(parents=True, exist_ok=True)
    # Chmod the full chain from *path* up to (and including) cache_dir() so
    # that intermediate directories (e.g. catalogs/, projects/) also carry
    # 0700 even when created by a recursive mkdir.
    root = cache_dir()
    segment = path
    while segment != root.parent:
        _chmod_secure(segment, _DIR_MODE)
        if segment == root:
            break
        segment = segment.parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    """Return the resolved completion / catalog-audit cache directory path.

    The cache lives under the shared ``KANON_HOME`` root as
    ``<KANON_HOME>/cache`` (spec Section 4.1 / Section 7.3), where ``KANON_HOME``
    resolves with precedence ``KANON_HOME`` env > default ``~/.kanon`` (the
    default is derived from the real user home directory, never a hard-coded
    absolute path). This replaces the removed per-user cache-dir override and its
    XDG fallback; the cache now shares the single ``KANON_HOME`` store root with
    every other piece of fetched data so it is deduped and located deterministically.
    """
    return Path(resolve_kanon_home()) / KANON_HOME_CACHE_SUBDIR


def catalog_entry_dir(catalog_url: str, ref: str) -> Path:
    """Return the per-catalog cache directory path.

    The directory name is the SHA-256 hex digest of ``<url>@<ref>``.
    The path is under ``cache_dir()/catalogs/``.

    The caller is responsible for ensuring ``catalog_url`` and ``ref`` are
    canonicalized before calling this function.
    """
    key = f"{catalog_url}@{ref}"
    sha = hashlib.sha256(key.encode()).hexdigest()
    return cache_dir() / "catalogs" / sha


def project_entry_dir(repo_url: str) -> Path:
    """Return the per-project cache directory path.

    The directory name is the SHA-256 hex digest of ``repo_url``.
    The path is under ``cache_dir()/projects/``.

    The caller is expected to canonicalize ``repo_url`` BEFORE calling
    this function (spec Section 11.4).
    """
    sha = hashlib.sha256(repo_url.encode()).hexdigest()
    return cache_dir() / "projects" / sha


def search_entry_dir(catalog_url: str, ref: str) -> Path:
    """Return the per-source ``search`` version-enumeration cache directory.

    The directory name is the SHA-256 hex digest of ``<url>@<ref>``; the path is
    under ``cache_dir()/search/`` so the ``search`` enumeration cache is namespaced
    separately from the ``catalogs/`` (entry-name completion) and ``projects/``
    caches that share ``cache_dir()``. This is the search-path extension of the
    existing TTL cache machinery (spec Section 4.1 / FR-25): a per-source@ref entry
    holds the concurrently-enumerated version list (``versions.txt``) and its
    ``fetched_at.txt`` freshness sidecar.

    The caller is responsible for ensuring ``catalog_url`` and ``ref`` are
    canonicalized before calling this function (mirrors :func:`catalog_entry_dir`).

    Args:
        catalog_url: The catalog manifest repo URL.
        ref: The catalog source ref (branch, tag, or ``latest``).

    Returns:
        Path to the per-source search cache entry directory.
    """
    key = f"{catalog_url}@{ref}"
    sha = hashlib.sha256(key.encode()).hexdigest()
    return cache_dir() / "search" / sha


def read_entries(file_path: Path) -> list[str]:
    """Read a newline-delimited entries file and return a list of strings.

    Lines are stripped of trailing whitespace; blank lines are skipped.
    A missing file is not an error -- it is treated as a cache miss and
    returns an empty list.  The caller is responsible for refetching.
    """
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return [line.rstrip() for line in lines if line.strip()]


def write_entries(
    file_path: Path,
    entries: Iterable[str],
    completer_name: str = "",
) -> None:
    """Write *entries* to *file_path*, one per line, with 0600 file mode.

    Creates parent directories (mode 0700) as needed.  Each entry is
    passed through ``sanitize_entries()`` before writing; entries that
    contain newlines, NULs, shell metacharacters, or other control
    characters are silently dropped from the file and each dropped entry
    is logged once via ``log_completion_error``.
    The file is written atomically by writing the full content at once.

    Args:
        file_path: Destination path for the entries file.
        entries: Iterable of candidate strings to persist.
        completer_name: Name of the calling completer (forwarded to
            ``log_completion_error`` for each dropped entry).
    """
    _mkdir_secure(file_path.parent)
    result = sanitize_entries(entries, completer_name=completer_name)
    for _entry, reason in result.dropped:
        log_completion_error(completer_name, SanitizationError(reason))
    content = "".join(f"{e}\n" for e in result.kept)
    file_path.write_text(content, encoding="utf-8")
    _chmod_secure(file_path, _FILE_MODE)


def read_epoch(file_path: Path) -> int | None:
    """Read an epoch-seconds integer from *file_path*.

    Returns ``None`` when the file does not exist (cache miss).
    """
    if not file_path.exists():
        return None
    return int(file_path.read_text(encoding="utf-8").strip())


def write_epoch(file_path: Path, epoch: int) -> None:
    """Write *epoch* (seconds since Unix epoch) to *file_path* with mode 0600.

    Creates parent directories (mode 0700) as needed.
    """
    _mkdir_secure(file_path.parent)
    file_path.write_text(f"{epoch}\n", encoding="utf-8")
    _chmod_secure(file_path, _FILE_MODE)


class Freshness(enum.Enum):
    """Cache staleness classification (spec Section 11.4 cache lifecycle).

    FRESH   -- fetched_at is within TTL; use cached data immediately.
    STALE   -- fetched_at is outside TTL but file exists; stale data usable
               while a background refresh runs.
    MISSING -- fetched_at absent, unreadable, non-integer, or negative;
               caller must perform an inline fetch.
    """

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


def classify(fetched_at_path: Path, ttl_seconds: int, now: int) -> Freshness:
    """Classify a cache entry as FRESH, STALE, or MISSING.

    This function is pure: it reads *fetched_at_path* but never writes
    any file.  Calling it twice with the same arguments returns the same
    result and leaves the file system unchanged.

    Rules (spec Section 11.4 cache lifecycle + clock-skew bullet):

    - ``fetched_at_path`` absent on disk -> MISSING.
    - Content not parseable as an integer -> MISSING.
    - Parsed value < 0 -> MISSING (negative epoch is invalid).
    - Parsed value > now (clock skew: future timestamp) -> FRESH.
      The spec is explicit: "fetched_at in the future -- treat as fresh."
    - now - fetched_at <= ttl_seconds -> FRESH.
    - now - fetched_at > ttl_seconds -> STALE.

    Args:
        fetched_at_path: Path to the ``fetched_at.txt`` file.
        ttl_seconds: Cache TTL in seconds (from KANON_COMPLETION_CACHE_TTL).
        now: Current epoch seconds (injected for testability; callers pass
            ``int(time.time())`` in production).

    Returns:
        A ``Freshness`` member indicating the cache entry's status.
    """
    if not fetched_at_path.exists():
        return Freshness.MISSING

    raw = fetched_at_path.read_text(encoding="utf-8").strip()
    try:
        fetched_at = int(raw)
    except ValueError:
        return Freshness.MISSING

    if fetched_at < 0:
        return Freshness.MISSING

    # Clock-skew rule: future timestamp is treated as fresh.
    if fetched_at > now:
        return Freshness.FRESH

    if now - fetched_at <= ttl_seconds:
        return Freshness.FRESH

    return Freshness.STALE


def read_entries_with_freshness(
    cache_entry_dir: Path,
    ttl_seconds: int,
    now: int,
    entries_filename: str = _DEFAULT_ENTRIES_FILENAME,
) -> tuple[list[str], Freshness]:
    """Return (entries, freshness) for a cache entry directory.

    Uses ``classify`` to determine freshness of the ``fetched_at.txt``
    sibling file.  The entries are read from ``entries_filename`` in the same
    directory (``index.txt`` by default for the catalog/project name caches;
    ``versions.txt`` for the ``search`` version-enumeration extension).

    Contract (AC-FUNC-008):
    - MISSING -> returns ([], Freshness.MISSING).
    - FRESH or STALE -> returns (entries_from_<entries_filename>, freshness).

    Args:
        cache_entry_dir: Path to the cache entry directory
            (e.g. ``cache_dir()/catalogs/<sha>`` or ``cache_dir()/search/<sha>``).
        ttl_seconds: Cache TTL in seconds.
        now: Current epoch seconds.
        entries_filename: Name of the entries file in ``cache_entry_dir`` to read
            on a FRESH/STALE hit. Defaults to ``index.txt``.

    Returns:
        A tuple of (list[str], Freshness) where the list contains the
        entries from ``entries_filename`` (or is empty on MISSING).
    """
    fetched_at_path = cache_entry_dir / "fetched_at.txt"
    freshness = classify(fetched_at_path, ttl_seconds=ttl_seconds, now=now)

    if freshness is Freshness.MISSING:
        return [], Freshness.MISSING

    entries = read_entries(cache_entry_dir / entries_filename)
    return entries, freshness


def read_search_versions_with_freshness(
    catalog_url: str,
    ref: str,
    ttl_seconds: int,
    now: int,
) -> tuple[list[str], Freshness]:
    """Return (versions, freshness) for a ``search`` per-source enumeration cache.

    Search-path extension of the TTL cache (spec Section 4.1 / FR-25): resolves the
    per-source@ref entry directory via :func:`search_entry_dir` and delegates to
    :func:`read_entries_with_freshness` reading the ``versions.txt`` entries file.
    The cache primitives are reused verbatim rather than re-implemented (DRY).

    Args:
        catalog_url: The catalog manifest repo URL.
        ref: The catalog source ref.
        ttl_seconds: Cache TTL in seconds (env-driven; never hard-coded here).
        now: Current epoch seconds (injected for testability).

    Returns:
        A tuple of (list[str], Freshness): the enumerated version list on a
        FRESH/STALE hit, or ([], MISSING) on a cache miss.
    """
    entry_dir = search_entry_dir(catalog_url, ref)
    return read_entries_with_freshness(
        entry_dir,
        ttl_seconds=ttl_seconds,
        now=now,
        entries_filename=SEARCH_VERSIONS_FILENAME,
    )


def write_search_versions(
    catalog_url: str,
    ref: str,
    versions: Iterable[str],
    now: int,
) -> None:
    """Persist a ``search`` per-source enumeration to the TTL cache.

    Search-path extension of the TTL cache (spec Section 4.1 / FR-25): writes the
    enumerated ``versions`` to ``versions.txt`` and stamps ``fetched_at.txt`` with
    ``now`` inside the per-source@ref entry directory, reusing the existing
    :func:`write_entries` (sanitised, 0600) and :func:`write_epoch` primitives so a
    later :func:`read_search_versions_with_freshness` within ``ttl_seconds`` reuses
    the cached enumeration (DRY, no duplicated cache logic).

    Args:
        catalog_url: The catalog manifest repo URL.
        ref: The catalog source ref.
        versions: The enumerated version strings to persist (one per line).
        now: Current epoch seconds to stamp as ``fetched_at``.
    """
    entry_dir = search_entry_dir(catalog_url, ref)
    write_entries(entry_dir / SEARCH_VERSIONS_FILENAME, versions, completer_name="search")
    write_epoch(entry_dir / "fetched_at.txt", now)


def maybe_update_accessed_at(
    accessed_at_path: Path,
    now: int,
    coalesce_window_seconds: int,
) -> bool:
    """Update ``accessed_at_path`` with the current epoch, subject to coalescing.

    Implements the coalescing rule from spec Section 11.4: the file is only
    rewritten when ``now - prior_value >= coalesce_window_seconds``.  This
    bounds I/O under rapid Tab-pressing (every completer invocation would
    otherwise rewrite the file on every keystroke).

    Rules:

    - File missing or unreadable (non-integer content) -> write ``now``,
      return True (first-touch).
    - ``now - prior_value < coalesce_window_seconds`` -> do NOT write,
      return False.
    - ``now - prior_value >= coalesce_window_seconds`` -> write ``now``,
      return True.
    - ``prior_value > now`` (clock skew) -> rewrite to ``now`` (force-
      forward to current time), return True.

    Args:
        accessed_at_path: Path to the ``accessed_at.txt`` file.
        now: Current epoch seconds (injected for testability; callers
            pass ``int(time.time())`` in production).
        coalesce_window_seconds: Minimum number of seconds between writes
            (sourced from ``KANON_ACCESSED_AT_COALESCE_SEC`` by callers).

    Returns:
        True when the file was written; False when the write was suppressed
        by the coalescing rule.
    """
    try:
        prior_value = read_epoch(accessed_at_path)
    except ValueError:
        # Non-integer / corrupt content: treat as missing (spec Section 11.4).
        write_epoch(accessed_at_path, now)
        return True

    if prior_value is None:
        # File is absent -- first-touch write.
        write_epoch(accessed_at_path, now)
        return True

    # Clock-skew: prior timestamp is in the future -- force-forward to now.
    if prior_value > now:
        write_epoch(accessed_at_path, now)
        return True

    # Within coalesce window: suppress the write.
    if now - prior_value < coalesce_window_seconds:
        return False

    # At or past the window boundary: write and report.
    write_epoch(accessed_at_path, now)
    return True


_FORK_COMPLETER_NAME = "fork_background_refresh"


def _run_refresh_with_logging(refresh_fn: Callable[[], None], completer_name: str) -> None:
    """Call *refresh_fn* and log any exception via *log_completion_error*.

    This is a module-level function (not a nested closure) so that
    ``functools.partial(_run_refresh_with_logging, refresh_fn, completer_name)``
    is picklable.  Picklability is required for the Windows spawn path, which
    serialises the callable via ``pickle`` to pass it to a child interpreter.

    Args:
        refresh_fn: Zero-argument callable that performs the cache refresh.
        completer_name: Name used in the error log entry on exception.
    """
    try:
        refresh_fn()
    except Exception as exc:
        log_completion_error(completer_name, exc)
        raise


def fork_background_refresh(refresh_fn: Callable[[], None]) -> None:
    """Spawn a detached child process to run *refresh_fn* in the background.

    Implements spec Section 11.4 cache lifecycle bullet 2: when a cache entry
    is STALE, the caller returns the stale data immediately and calls this
    function to schedule an asynchronous refresh.

    Behavior:

    - If ``${KANON_COMPLETION_REFRESH_BG}`` is ``0``, this function returns
      immediately without spawning.
    - If ``${KANON_COMPLETION_REFRESH_BG}`` is set to a value that cannot be
      parsed as an integer, a diagnostic message is written to stderr naming
      the invalid value and the expected format, and the function returns
      immediately without spawning.
    - Otherwise, ``spawn_detached`` is called.  The parent returns immediately
      (no blocking wait; the child is fully detached).
    - In the child process:
      1. The controlling terminal is detached (POSIX: ``os.setsid()``; Windows:
         ``DETACHED_PROCESS`` flag).
      2. stdin (fd 0) and stdout (fd 1) are redirected to ``/dev/null`` so
         the refresh process cannot write to the operator's terminal.
      3. stderr (fd 2) is redirected to append to ``completion-errors.log``
         so refresh-time errors are captured without touching the terminal.
      4. ``refresh_fn()`` is called.
      5. On success the child exits 0 via ``os._exit``.
      6. On any exception the child exits 1 via ``os._exit``.

    The child process MUST NOT write to the parent's stdout (the completer
    is writing completion candidates there).

    Args:
        refresh_fn: Zero-argument callable that performs the cache refresh.
            Called only in the child process.

    Raises:
        RuntimeError: If the underlying spawn mechanism fails (propagated from
            ``spawn_detached``); the refresh is lost but the parent process
            continues normally.
    """
    raw_env = os.environ.get(KANON_COMPLETION_REFRESH_BG_ENV)
    if raw_env is not None:
        try:
            enabled = int(raw_env)
        except ValueError:
            print(
                f"kanon: warning: {KANON_COMPLETION_REFRESH_BG_ENV}={raw_env!r} is not a valid"
                " integer (expected 0 or 1); background refresh disabled."
                " Set to 0 to suppress this warning.",
                file=sys.stderr,
            )
            return
    else:
        enabled = KANON_COMPLETION_REFRESH_BG

    if enabled == 0:
        return

    log_env = os.environ.get(KANON_COMPLETION_LOG_ENV)
    if log_env:
        log_path = Path(log_env)
    else:
        log_path = cache_dir() / KANON_COMPLETION_ERRORS_LOG_FILENAME

    # Build a picklable callable by binding refresh_fn to the module-level
    # _run_refresh_with_logging helper via functools.partial.  A nested closure
    # would not be picklable, which would break the Windows spawn path that
    # serialises the callable via pickle to pass it to the child interpreter.
    refresh_with_logging = functools.partial(_run_refresh_with_logging, refresh_fn, _FORK_COMPLETER_NAME)

    spawn_detached(refresh_with_logging, log_path=log_path)


def log_completion_error(completer_name: str, exc: Exception) -> None:
    """Append one error line to the completion-errors log.

    Line format::

        <ISO-8601-UTC> <completer-name> <error-class-name>: <message>

    The log path is resolved from ``${KANON_COMPLETION_LOG}`` when set,
    otherwise ``cache_dir()/completion-errors.log``.  The file is opened
    in append mode; it is never rotated (operators run
    ``kanon doctor --prune-cache``).
    """
    log_env = os.environ.get(KANON_COMPLETION_LOG_ENV)
    if log_env:
        log_path = Path(log_env)
    else:
        log_path = cache_dir() / "completion-errors.log"

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    error_class = type(exc).__name__
    line = f"{ts} {completer_name} {error_class}: {exc}\n"

    # Ensure the parent directory exists and has mode 0700.
    _mkdir_secure(log_path.parent)
    with log_path.open("a") as fh:
        fh.write(line)
    _chmod_secure(log_path, _FILE_MODE)
