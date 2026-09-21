"""Detached-process spawn helper — cross-platform.

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

Windows:
    Uses a detached subprocess running an importable module-level function or
    partial from the installed environment. Isolated Python startup excludes
    the workspace, PYTHONPATH and user site from imports. JSON arguments travel
    over a private pipe. The interpreter never
    joins this subprocess at shutdown; stdout is discarded and stderr is
    appended to *log_path*. Callback failures exit nonzero.

Fail-fast contract
------------------
Any spawn failure raises ``RuntimeError`` with a message that names the
exception class and the underlying OS error.  The caller is responsible for
deciding whether to propagate the error; library code never calls
``sys.exit()``.
"""

from __future__ import annotations

import os
import sys
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
        return


def spawn_detached(refresh_fn: Callable[[], None], *, log_path: Path) -> None:
    """Spawn *refresh_fn* in a detached child process and return immediately.

    The child is fully detached from the parent's controlling terminal.
    stdin and stdout are redirected to ``/dev/null``; stderr is redirected to
    *log_path* (opened in append mode, created if absent).

    Dispatches to the platform-specific backend:

    * POSIX: ``_spawn_detached_posix`` — ``os.fork()`` + ``os.setsid()``.
    * Windows: ``_spawn_detached_windows`` — detached ``subprocess.Popen``.

    Args:
        refresh_fn: Zero-argument callable executed only in the child process.
            Must be a module-level function or partial installed in the Python
            environment on Windows, with JSON values, paths, bytes, or nested
            partials as arguments. Workspace, PYTHONPATH and user-site imports
            are excluded from the isolated worker.
        log_path: Path to the file where the child's stderr is appended.
            The log directory is created with mode 0700 on POSIX (explicit chmod
            so the umask cannot weaken permissions) and with default permissions
            on Windows. The Windows parent creates the log before launching the
            child so log setup errors are raised synchronously.

    Raises:
        RuntimeError: If the underlying spawn mechanism fails.
    """
    if sys.platform == "win32":
        _spawn_detached_windows(refresh_fn, log_path=log_path)
    else:
        _spawn_detached_posix(refresh_fn, log_path=log_path)


_POSIX_FILE_MODE = 0o600


def _windows_append_fd(path, flags):
    """Open an append-only Win32 handle; child writes cannot overwrite old data.

    CRT append mode alone only seeks before writes made through that CRT file
    descriptor. An inherited stderr handle needs FILE_APPEND_DATA without
    FILE_WRITE_DATA so the kernel appends every write from every process.
    Ownership passes to the CRT descriptor only after open_osfhandle succeeds.
    """
    import ctypes
    from ctypes import wintypes as w
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    handle = kernel.CreateFileW(path, 4, 3, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise


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
        return

    try:
        os.setsid()

        devnull_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull_fd, 0)
        os.dup2(devnull_fd, 1)

        log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(log_path.parent, 0o700)
        log_fd = os.open(
            str(log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            _POSIX_FILE_MODE,
        )
        os.dup2(log_fd, 2)

        os.close(devnull_fd)
        os.close(log_fd)

        refresh_fn()
        os._exit(0)
    except Exception:
        _record_posix_child_error(log_path)
        os._exit(1)


def _spawn_detached_windows(
    refresh_fn: Callable[[], None],
    *,
    log_path: Path,
):
    """Start a detached subprocess, with no multiprocessing shutdown join.

    The parent creates the log before launch so setup errors are synchronous.
    Only a pipe carries the JSON job; stderr and stdout are redirected at the
    OS handle level, including output from subprocesses started by the worker.
    The returned Popen handle lets native contract tests observe the exit code.
    Production callers do not wait for the worker.
    """
    import json
    import subprocess

    from kanon_cli.utils.worker import encode

    try:
        payload = json.dumps(encode(refresh_fn), ensure_ascii=True).encode("utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab", opener=_windows_append_fd) as log:
            child = subprocess.Popen(
                [sys.executable, "-I", "-X", "utf8", "-m", "kanon_cli.utils.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        try:
            child.stdin.write(payload)
            child.stdin.close()
        except BaseException:
            child.terminate()
            child.wait()
            raise
        return child
    except Exception as exc:
        raise RuntimeError(
            f"spawn_detached: failed to spawn background refresh child on Windows"
            f" ({type(exc).__name__}: {exc})."
            " Check the log directory permissions and Python installation."
        ) from exc
