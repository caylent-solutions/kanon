"""POSIX detached-process spawn helper.

Provides a single ``spawn_detached`` function that starts a child process
running an arbitrary callable, fully detached from the parent's controlling
terminal and with stdin/stdout/stderr redirected away from the terminal.

Platform behaviour
------------------
POSIX (Linux, macOS):
    Uses ``os.fork()`` once.  The parent returns immediately.  The child calls
    ``os.setsid()`` to start a new session (detaches from the controlling
    terminal), redirects stdin and stdout to ``/dev/null``, redirects stderr to
    the caller-supplied *log_path* (append mode), calls *refresh_fn()*, and
    exits via ``os._exit`` (0 on success, 1 on exception).

Windows is unsupported: kanon targets POSIX hosts (WSL/WSL2 is the recommended
path on Windows in the meantime), so this helper has no Windows backend.

Fail-fast contract
------------------
Any spawn failure raises ``RuntimeError`` with a message that names the
exception class and the underlying OS error.  The caller is responsible for
deciding whether to propagate the error; library code never calls
``sys.exit()``.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from pathlib import Path


def _record_posix_child_error(log_path: Path) -> None:
    """Append the active exception traceback to *log_path* from the child.

    The superseded ``fork_background_refresh`` child logged its failure via
    ``log_completion_error`` before exiting non-zero. This helper preserves
    that behavior for the extracted spawn path: a detached child has no other
    channel to surface a setup or refresh failure, so the error MUST be
    recorded rather than silently swallowed (fail-fast, no silent failures).

    Recording is best-effort: the directory is created with mode 0700 (the
    umask is not trusted) and the traceback is appended. If the log write
    itself raises ``OSError`` (e.g. the filesystem is full), the caller still
    exits non-zero via ``os._exit(1)`` -- the failure is never masked, only the
    redundant logging-of-the-logging-failure is skipped.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(log_path.parent, 0o700)
        with open(log_path, "a", encoding="utf-8") as log_fh:
            log_fh.write(traceback.format_exc())
    except OSError:
        # Detached child about to os._exit(1); no further recovery channel
        # exists and the non-zero exit preserves the fail-fast contract.
        return


def spawn_detached(refresh_fn: Callable[[], None], *, log_path: Path) -> None:
    """Spawn *refresh_fn* in a detached child process and return immediately.

    The child is fully detached from the parent's controlling terminal.
    stdin and stdout are redirected to ``/dev/null``; stderr is redirected to
    *log_path* (opened in append mode, created if absent).

    The child is created via ``os.fork()``; the parent returns as soon as the
    fork succeeds.  kanon is POSIX-only, so there is no Windows backend.

    Args:
        refresh_fn: Zero-argument callable executed only in the child process.
        log_path: Path to the file where the child's stderr is appended.
            The log directory is created with mode 0700 (explicit chmod so the
            umask cannot weaken permissions).  The parent does not create this
            file; the child opens it in append mode so that any error output is
            captured without touching the operator's terminal.

    Raises:
        RuntimeError: If the underlying spawn mechanism fails (``os.fork``
            raises ``OSError``).
    """
    _spawn_detached_posix(refresh_fn, log_path=log_path)


# ---------------------------------------------------------------------------
# POSIX implementation
# ---------------------------------------------------------------------------

_POSIX_FILE_MODE = 0o600


def _spawn_detached_posix(
    refresh_fn: Callable[[], None],
    *,
    log_path: Path,
) -> None:
    """POSIX fork detach: parent returns immediately, child runs refresh_fn."""
    try:
        pid = os.fork()
    except OSError as exc:
        raise RuntimeError(
            f"spawn_detached: failed to fork background refresh child"
            f" ({type(exc).__name__}: {exc})."
            f" Check system resource limits (ulimit -u) and try again."
        ) from exc

    if pid != 0:
        # Parent path: return immediately; do NOT call os.waitpid.
        return

    # Child path: detach, redirect I/O, run refresh_fn, exit.
    # os._exit is always called (success or failure) so the child never
    # falls through to the parent's code path.
    try:
        os.setsid()

        # Redirect stdin and stdout to /dev/null.
        devnull_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull_fd, 0)  # stdin
        os.dup2(devnull_fd, 1)  # stdout

        # Redirect stderr to log_path (append mode).
        # Explicitly chmod to 0700 after mkdir: the umask cannot be trusted
        # to enforce owner-only permissions in a regulated-financial codebase.
        log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(log_path.parent, 0o700)
        log_fd = os.open(
            str(log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            _POSIX_FILE_MODE,
        )
        os.dup2(log_fd, 2)  # stderr

        # Close the extra descriptors now that they are dup'd onto 0, 1, 2.
        os.close(devnull_fd)
        os.close(log_fd)

        refresh_fn()
        os._exit(0)
    except Exception:
        _record_posix_child_error(log_path)
        os._exit(1)
