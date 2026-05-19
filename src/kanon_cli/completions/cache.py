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
    read_entries(file_path) -> list[str]
    write_entries(file_path, entries) -> None
    read_epoch(file_path) -> int | None
    write_epoch(file_path, epoch) -> None
    maybe_update_accessed_at(accessed_at_path, now, coalesce_window_seconds) -> bool
    log_completion_error(completer_name, exc) -> None
    Freshness -- enum: FRESH | STALE | MISSING
    classify(fetched_at_path, ttl_seconds, now) -> Freshness
    read_entries_with_freshness(cache_entry_dir, ttl_seconds, now) -> tuple[list[str], Freshness]

Security: spec Section 3.6 -- cache files are user-private.
"""

from __future__ import annotations

import enum
import hashlib
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from kanon_cli.constants import (
    KANON_CACHE_DIR_DEFAULT,
    KANON_CACHE_DIR_ENV,
    KANON_COMPLETION_LOG_ENV,
)

# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# ---------------------------------------------------------------------------
# Stub sanitizer -- replaced by E7-F3-S1-T4 with the real implementation.
# ---------------------------------------------------------------------------


def sanitize(s: str) -> str:
    """Stub sanitizer.  E7-F3-S1-T4 replaces this with the real implementation."""
    return s


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
    """Return the resolved cache directory path.

    Resolution order (highest wins):
    1. ``${KANON_CACHE_DIR}`` env var.
    2. ``${XDG_CACHE_HOME}/kanon``.
    3. ``~/.cache/kanon`` (XDG default; Section 11.4).
    """
    env_val = os.environ.get(KANON_CACHE_DIR_ENV)
    if env_val:
        return Path(env_val)

    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "kanon"

    return Path(KANON_CACHE_DIR_DEFAULT).expanduser()


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


def read_entries(file_path: Path) -> list[str]:
    """Read a newline-delimited entries file and return a list of strings.

    Lines are stripped of trailing whitespace; blank lines are skipped.
    A missing file is not an error -- it is treated as a cache miss and
    returns an empty list.  The caller is responsible for refetching.
    """
    if not file_path.exists():
        return []
    lines = file_path.read_text().splitlines()
    return [line.rstrip() for line in lines if line.strip()]


def write_entries(file_path: Path, entries: Iterable[str]) -> None:
    """Write *entries* to *file_path*, one per line, with 0600 file mode.

    Creates parent directories (mode 0700) as needed.  Each entry is
    passed through ``sanitize()`` before writing (stub until E7-F3-S1-T4).
    The file is written atomically by writing the full content at once.
    """
    _mkdir_secure(file_path.parent)
    sanitized = [sanitize(e) for e in entries]
    content = "".join(f"{e}\n" for e in sanitized)
    file_path.write_text(content)
    _chmod_secure(file_path, _FILE_MODE)


def read_epoch(file_path: Path) -> int | None:
    """Read an epoch-seconds integer from *file_path*.

    Returns ``None`` when the file does not exist (cache miss).
    """
    if not file_path.exists():
        return None
    return int(file_path.read_text().strip())


def write_epoch(file_path: Path, epoch: int) -> None:
    """Write *epoch* (seconds since Unix epoch) to *file_path* with mode 0600.

    Creates parent directories (mode 0700) as needed.
    """
    _mkdir_secure(file_path.parent)
    file_path.write_text(f"{epoch}\n")
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

    raw = fetched_at_path.read_text().strip()
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
) -> tuple[list[str], Freshness]:
    """Return (entries, freshness) for a cache entry directory.

    Uses ``classify`` to determine freshness of the ``fetched_at.txt``
    sibling file.  The entries are read from ``index.txt`` in the same
    directory.

    Contract (AC-FUNC-008):
    - MISSING -> returns ([], Freshness.MISSING).
    - FRESH or STALE -> returns (entries_from_index_txt, freshness).

    Args:
        cache_entry_dir: Path to the cache entry directory
            (e.g. ``cache_dir()/catalogs/<sha>``).
        ttl_seconds: Cache TTL in seconds.
        now: Current epoch seconds.

    Returns:
        A tuple of (list[str], Freshness) where the list contains the
        entries from ``index.txt`` (or is empty on MISSING).
    """
    fetched_at_path = cache_entry_dir / "fetched_at.txt"
    freshness = classify(fetched_at_path, ttl_seconds=ttl_seconds, now=now)

    if freshness is Freshness.MISSING:
        return [], Freshness.MISSING

    entries = read_entries(cache_entry_dir / "index.txt")
    return entries, freshness


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
