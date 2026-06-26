"""Idempotent maintenance of the auto-managed ``.kanon`` global header.

A ``claude-marketplace`` dependency requires the global ``.kanon`` header
``CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces`` so that
``kanon install`` knows where to register marketplace plugins (spec Section 4.3).
This module keeps that header in sync with the presence of any
``KANON_SOURCE_<alias>_MARKETPLACE=true`` dependency:

* ``ensure_claude_marketplaces_dir`` inserts the header the first time a
  marketplace dependency is added or enabled (never duplicating it, never
  clobbering a custom value an operator hand-set).
* ``prune_claude_marketplaces_dir_if_unused`` removes the header once the last
  marketplace dependency is removed or disabled, so the CWD ``.kanon`` carries no
  stale auto-managed line.

Both functions are idempotent and preserve the file's dominant newline. Matching
is done on the parsed KEY of each line, never on a substring: the literal
``"_MARKETPLACE"`` is a substring of ``"CLAUDE_MARKETPLACES_DIR"``, so a substring
test would falsely treat the header itself as a marketplace dependency.
"""

from __future__ import annotations

import pathlib

from kanon_cli.constants import (
    KANON_HEADER_CLAUDE_MARKETPLACES_DIR,
    MARKETPLACE_DIR_GLOBAL_KEY,
    MARKETPLACE_FLAG_TRUE,
    SOURCE_MARKETPLACE_SUFFIX,
    SOURCE_PREFIX,
)
from kanon_cli.core.install import resolve_kanon_lock_root
from kanon_cli.utils.concurrency import kanon_workspace_lock


def _key_of(raw_line: str) -> str | None:
    """Return the parsed KEY of a ``.kanon`` line, or ``None`` when it has none.

    Blank lines, comment lines (``#`` after stripping), and lines without an
    ``=`` carry no key and return ``None``. Otherwise the text left of the first
    ``=`` is returned, stripped of surrounding whitespace.

    Args:
        raw_line: A single line from the ``.kanon`` file (newline optional).

    Returns:
        The stripped key string, or ``None`` when the line carries no key.
    """
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _detect_newline(lines: list[str]) -> str:
    """Return the newline string to use when inserting a line into ``.kanon``.

    Mirrors the dominant ending of the file's content so an inserted header line
    matches the existing convention. Defaults to ``\\n`` for an empty file or a
    final line that carries no newline.

    Args:
        lines: All lines of the ``.kanon`` file (newlines retained).

    Returns:
        ``"\\r\\n"`` when the last newline-terminated line is CRLF, else ``"\\n"``.
    """
    for raw_line in reversed(lines):
        if raw_line.endswith("\r\n"):
            return "\r\n"
        if raw_line.endswith("\n"):
            return "\n"
    return "\n"


def _read_lines(kanon_file: pathlib.Path) -> list[str]:
    """Return the ``.kanon`` file's lines, or an empty list when it is absent.

    Args:
        kanon_file: Path to the ``.kanon`` file.

    Returns:
        The file content split into newline-retaining lines, or ``[]`` when the
        file does not yet exist.
    """
    if not kanon_file.exists():
        return []
    return kanon_file.read_text(encoding="utf-8", newline="").splitlines(keepends=True)


def _has_header(lines: list[str]) -> bool:
    """Return whether any line's parsed KEY is the marketplace-dir global key.

    Args:
        lines: All lines of the ``.kanon`` file.

    Returns:
        ``True`` when a ``CLAUDE_MARKETPLACES_DIR`` line is present.
    """
    return any(_key_of(line) == MARKETPLACE_DIR_GLOBAL_KEY for line in lines)


def has_claude_marketplaces_dir_header(kanon_file: pathlib.Path) -> bool:
    """Return whether ``kanon_file`` already carries the marketplace-dir header.

    A read-only predicate (no lock, no write) keyed on parsed-KEY equality, used
    by ``kanon add --dry-run`` to decide whether to preview the auto-added header.

    Args:
        kanon_file: Path to the ``.kanon`` file (treated as empty when absent).

    Returns:
        ``True`` when a ``CLAUDE_MARKETPLACES_DIR`` line is present.
    """
    return _has_header(_read_lines(kanon_file))


def _is_enabled_marketplace_line(line: str) -> bool:
    """Return whether ``line`` is a ``KANON_SOURCE_<alias>_MARKETPLACE`` true flag.

    Match is on the parsed KEY (prefix + suffix) and the parsed value, never a
    substring, so the ``CLAUDE_MARKETPLACES_DIR`` header is never mistaken for a
    marketplace dependency.

    Args:
        line: A single ``.kanon`` line.

    Returns:
        ``True`` when the key is a source marketplace flag whose value is true.
    """
    key = _key_of(line)
    if key is None:
        return False
    if not key.startswith(SOURCE_PREFIX) or not key.endswith(SOURCE_MARKETPLACE_SUFFIX):
        return False
    value = line.strip().split("=", 1)[1].strip()
    return value.lower() == MARKETPLACE_FLAG_TRUE


def _first_content_index(lines: list[str]) -> int:
    """Return the index of the first non-comment, non-blank line.

    Leading comment (``#``) and blank lines are skipped so the header is inserted
    after any file preamble. Returns ``len(lines)`` when the file holds only
    comments and blanks (or is empty).

    Args:
        lines: All lines of the ``.kanon`` file.

    Returns:
        The insertion index for the header line.
    """
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            return index
    return len(lines)


def ensure_claude_marketplaces_dir(kanon_file: pathlib.Path, *, hold_lock: bool = True) -> bool:
    """Insert the ``CLAUDE_MARKETPLACES_DIR`` header when absent; idempotent.

    Reads ``kanon_file`` (treated as empty when absent). If no line's parsed KEY
    equals ``CLAUDE_MARKETPLACES_DIR``, the literal
    ``KANON_HEADER_CLAUDE_MARKETPLACES_DIR`` (unexpanded
    ``CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces``) is inserted as the
    first non-comment, non-blank line, using the file's dominant newline, and the
    file is written back. An existing header (even a custom value) is never
    duplicated and never clobbered.

    Args:
        kanon_file: Path to the ``.kanon`` file.
        hold_lock: When ``True`` (default), the read-modify-write runs under the
            store-side workspace lock for ``kanon_file``. Callers that already
            hold that lock pass ``False`` to avoid a reentrant acquisition.

    Returns:
        ``True`` when the header was inserted; ``False`` when it was already
        present (no write performed).
    """
    if hold_lock:
        with kanon_workspace_lock(resolve_kanon_lock_root(kanon_file)):
            return _ensure_unlocked(kanon_file)
    return _ensure_unlocked(kanon_file)


def _ensure_unlocked(kanon_file: pathlib.Path) -> bool:
    """Perform the ensure read-modify-write without acquiring the workspace lock.

    Args:
        kanon_file: Path to the ``.kanon`` file.

    Returns:
        ``True`` when the header was inserted; ``False`` otherwise.
    """
    lines = _read_lines(kanon_file)
    if _has_header(lines):
        return False

    newline = _detect_newline(lines)
    header_line = KANON_HEADER_CLAUDE_MARKETPLACES_DIR + newline
    insert_at = _first_content_index(lines)
    lines.insert(insert_at, header_line)
    kanon_file.write_text("".join(lines), encoding="utf-8", newline="")
    return True


def prune_claude_marketplaces_dir_if_unused(kanon_file: pathlib.Path, *, hold_lock: bool = True) -> bool:
    """Remove the ``CLAUDE_MARKETPLACES_DIR`` header when no marketplace remains.

    Reads ``kanon_file`` (treated as empty when absent). When the header is
    present AND no remaining line is a ``KANON_SOURCE_<alias>_MARKETPLACE`` flag
    with a true value, every header line is removed and the file is written back.
    Pruning is unconditional of the header's value (a custom value is removed too)
    once no marketplace dependency remains; the header is re-added automatically on
    the next add or enable. A hand-written ``=false`` flag does not count as a
    remaining marketplace.

    Args:
        kanon_file: Path to the ``.kanon`` file.
        hold_lock: When ``True`` (default), the read-modify-write runs under the
            store-side workspace lock for ``kanon_file``. Callers that already
            hold that lock pass ``False`` to avoid a reentrant acquisition.

    Returns:
        ``True`` when the header was removed; ``False`` otherwise (header absent
        or a marketplace dependency still remains).
    """
    if hold_lock:
        with kanon_workspace_lock(resolve_kanon_lock_root(kanon_file)):
            return _prune_unlocked(kanon_file)
    return _prune_unlocked(kanon_file)


def _prune_unlocked(kanon_file: pathlib.Path) -> bool:
    """Perform the prune read-modify-write without acquiring the workspace lock.

    Args:
        kanon_file: Path to the ``.kanon`` file.

    Returns:
        ``True`` when the header was removed; ``False`` otherwise.
    """
    lines = _read_lines(kanon_file)
    if not _has_header(lines):
        return False
    if any(_is_enabled_marketplace_line(line) for line in lines):
        return False

    kept = [line for line in lines if _key_of(line) != MARKETPLACE_DIR_GLOBAL_KEY]
    kanon_file.write_text("".join(kept), encoding="utf-8", newline="")
    return True
