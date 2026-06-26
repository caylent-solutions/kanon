"""Lock-file path derivation helper.

Implements the three-tier precedence chain from spec Section 4.7:

  1. Explicit ``--lock-file <path>`` CLI flag (cli_lock_file).
  2. ``KANON_LOCK_FILE`` environment variable (env_lock_file).
  3. ``<kanon-file-path>.lock`` derived from the kanon file path.

All four commands that accept ``--lock-file`` (``kanon install``,
``kanon doctor``, ``kanon outdated``, ``kanon why``) call
``derive_lock_file_path`` in their command handlers so the derivation
logic lives in exactly one place.
"""

from __future__ import annotations

from pathlib import Path


def derive_lock_file_path(
    kanon_file_path: Path,
    cli_lock_file: Path | None,
    env_lock_file: str | None,
) -> Path:
    """Return the resolved lock-file path using the three-tier precedence chain.

    Precedence (highest wins):
      1. cli_lock_file -- non-None value supplied by the ``--lock-file`` CLI flag.
      2. env_lock_file -- non-empty string from the ``KANON_LOCK_FILE`` env var.
      3. Derived path -- ``kanon_file_path`` with ``.lock`` appended to the suffix.

    For the default kanon file path ``Path("./.kanon")``, the derivation
    produces ``Path("./.kanon.lock")``.  For ``Path("./alt.kanon")``, the
    derivation produces ``Path("./alt.kanon.lock")``.

    An empty-string ``env_lock_file`` is treated as unset and falls through
    to the derivation.  A whitespace-only ``env_lock_file`` is non-empty and
    is used as-is (the caller is responsible for trimming if desired).

    Args:
        kanon_file_path: Path to the ``.kanon`` configuration file.  Used
            only when both cli_lock_file and env_lock_file are absent.
        cli_lock_file: Path supplied via the ``--lock-file`` CLI flag, or
            ``None`` when the flag was not provided.
        env_lock_file: Raw string value of the ``KANON_LOCK_FILE`` environment
            variable, or ``None`` when the variable is unset.

    Returns:
        The resolved ``Path`` for the lock file.  The returned path is never
        ``None``; the derivation always produces a concrete path.
    """
    if cli_lock_file is not None:
        return cli_lock_file

    if env_lock_file is not None and env_lock_file != "":
        return Path(env_lock_file)

    suffix = kanon_file_path.suffix
    return kanon_file_path.with_suffix(suffix + ".lock")
