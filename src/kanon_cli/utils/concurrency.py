"""Workspace concurrency lock helper.

Provides the ``kanon_workspace_lock`` context manager that serialises
concurrent mutations to a kanon workspace. Any command that mutates
workspace state (kanon install, kanon add, kanon remove,
kanon doctor --refresh-completion-cache) must wrap its mutation
inside this context manager.

Lock backends (spec Section 4 / FR-32, FR-33, FR-36, issue #67, issue #75)
---------------------------------------------------------------------------
The context manager acquires an exclusive kernel-level lock on
``.kanon-data/INSTALL_LOCK_FILENAME`` before yielding control to the caller.
Two platform-specific backends are available:

* POSIX (Linux, macOS): ``fcntl.flock(fd, LOCK_EX)`` with a ``SIGALRM``
  fail-fast timeout.
* Windows: Win32 ``LockFileEx`` via ``ctypes`` with a ``WaitForSingleObject``
  timeout.

This gives **true kernel-level blocking with NO internal poll loop and NO
``sleep``** (CLAUDE.md "no time-based synchronization"). The POSIX ``import fcntl`` and the Windows ``import ctypes``
live **inside** their respective backend functions, so importing this module
never fails on a platform that lacks either module (there is no column-0
module-top platform-specific import).

The lock is released (and the file descriptor closed) on exit regardless of
whether the body raised an exception (try/finally semantics). The kernel
releases the lock automatically when the file descriptor is closed (normal
exit, exception exit, or process termination), so a crashed process never
leaves the workspace permanently locked.

Re-entrance guard (issue #67)
-----------------------------
Opening a new file-description on every entry and then blocking on the lock
while the same process already holds it would deadlock. To prevent that, this
module tracks the set of lock paths currently held by **this** process. A
nested acquisition of a workspace whose lock is already held raises
``WorkspaceLockReentranceError`` immediately with an actionable message --
it never silently no-ops and never deadlocks. Locks for two *distinct*
workspaces may be held simultaneously.

Configurable fail-fast timeout (FR-36)
--------------------------------------
The acquisition timeout is read from
``constants.KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS`` (env-driven via ``_env_int``,
default 30; no inline literal here). On expiry the acquisition fails fast with
``WorkspaceLockTimeoutError`` carrying an actionable stale-lock-recovery message
(pid / host / timestamp, spec Section 7.3). The timeout is enforced without any
poll loop or ``sleep``:

* POSIX: a kernel timer (``signal.setitimer`` / ``SIGALRM``) interrupts the
  blocking ``flock`` syscall on expiry (PEP 475 does not retry when the handler
  raises).

Eager creation
--------------
Before opening the lock file, the context manager creates ``.kanon-data/`` with
``parents=True, exist_ok=True`` so a fresh workspace does not hit a
``FileNotFoundError`` when the lock file path is opened.

Spec reference: ``specs/kanon-refinements.md`` Section 4 (cross-platform lock
interface), Section 7 (``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS``), Section 13.2
P4 (Option B fcntl); issue #67.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import pathlib
import socket
import sys
from collections.abc import Generator, Iterator
from typing import IO

from kanon_cli import constants
from kanon_cli.constants import INSTALL_LOCK_FILENAME


_held_lock_paths: set[str] = set()


class WorkspaceLockReentranceError(RuntimeError):
    """Raised when the same process re-enters a workspace lock it already holds.

    This is the #67 guard: opening a new file-description and blocking on the
    lock while the same process holds it via another file-description would
    deadlock. The guard detects the already-held lock and fails fast instead.
    """


class WorkspaceLockTimeoutError(TimeoutError):
    """Raised when the workspace lock cannot be acquired within the timeout.

    Carries an actionable stale-lock-recovery message (workspace path, the
    configured timeout, and pid / host / timestamp diagnostics).
    """


def _stale_lock_diagnostics() -> str:
    """Return a pid/host/timestamp diagnostic suffix for stale-lock recovery.

    The fields let an operator identify which process and host are competing
    for the lock when an acquisition times out (spec Section 7.3). The
    timestamp is timezone-aware UTC so logs from different hosts compare
    cleanly.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return f"pid={os.getpid()} host={socket.gethostname()} timestamp={now}"


def _acquire_timeout_seconds() -> int:
    """Return the configured workspace-lock acquisition timeout in seconds.

    Read from ``constants.KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS`` (env-driven via
    ``_env_int``) so there is no hard-coded literal in this module. The constant
    is validated as a positive integer at import in ``constants.py``.
    """
    return constants.KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS


@contextlib.contextmanager
def kanon_workspace_lock(workspace_root: pathlib.Path) -> Generator[None, None, None]:
    """Acquire an exclusive workspace lock and yield; release on exit.

    Creates ``.kanon-data/`` (with ``parents=True, exist_ok=True``) before
    opening the lock file so a fresh workspace does not fail with
    ``FileNotFoundError``.

    The lock is an exclusive kernel-level lock acquired through the host
    backend (POSIX ``flock`` or Windows ``LockFileEx``). The calling process blocks here until any other
    process that holds the lock releases it, OR until the configured acquisition
    timeout
    (``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS``) expires, in which case a
    ``WorkspaceLockTimeoutError`` is raised with a stale-lock-recovery message.
    Blocking is kernel-level (a kernel timer interrupts the syscall on expiry);
    there is no poll loop and no ``sleep``.

    A nested acquisition of a workspace whose lock is already held by this
    process raises ``WorkspaceLockReentranceError`` immediately (issue #67 guard)
    rather than deadlocking. Locks for two distinct workspaces may be held at
    the same time.

    Args:
        workspace_root: The project root directory. The lock file is created
            at ``workspace_root / ".kanon-data" / INSTALL_LOCK_FILENAME``.

    Yields:
        Nothing. The caller holds the exclusive lock during the body.

    Raises:
        WorkspaceLockReentranceError: If this process already holds the lock for
            ``workspace_root`` (nested acquisition).
        WorkspaceLockTimeoutError: If the lock cannot be acquired within
            ``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS``.
        OSError: If ``.kanon-data/`` cannot be created (e.g. permission denied)
            or if the lock file cannot be opened.
    """
    kanon_data_dir = workspace_root / ".kanon-data"
    try:
        kanon_data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Cannot create source directory {kanon_data_dir}: {exc.strerror}") from exc

    lock_path = kanon_data_dir / INSTALL_LOCK_FILENAME
    lock_key = str(lock_path.resolve())

    if lock_key in _held_lock_paths:
        raise WorkspaceLockReentranceError(
            f"ERROR: workspace lock for {workspace_root} is already held by this process.\n"
            f"Lock file: {lock_path}\n"
            "kanon_workspace_lock must not be nested for the same workspace; a nested "
            "acquisition would deadlock. Refactor the caller so the mutation runs inside "
            "a single lock scope."
        )

    timeout_seconds = _acquire_timeout_seconds()

    with open(lock_path, "ab") as lock_fd:
        with _exclusive_kernel_lock(lock_fd, workspace_root, lock_path, timeout_seconds):
            _held_lock_paths.add(lock_key)
            try:
                yield
            finally:
                _held_lock_paths.discard(lock_key)


@contextlib.contextmanager
def _exclusive_kernel_lock(
    lock_fd: IO[bytes],
    workspace_root: pathlib.Path,
    lock_path: pathlib.Path,
    timeout_seconds: int,
) -> Iterator[None]:
    """Acquire an exclusive kernel lock with a fail-fast timeout.

    Dispatches to the platform-specific backend:

    * POSIX (Linux, macOS): ``_exclusive_kernel_lock_posix`` — uses
      ``fcntl.flock(LOCK_EX)`` interrupted by a ``SIGALRM`` kernel timer on
      expiry.  True kernel-level blocking with no poll loop and no ``sleep``.

    * Windows: ``_exclusive_kernel_lock_windows`` — uses Win32 ``LockFileEx``
      with an OVERLAPPED event and ``WaitForSingleObject`` timeout.  True
      kernel-level blocking with no poll loop and no ``sleep``.

    Args:
        lock_fd: An open writable file object for the lock file.
        workspace_root: The workspace whose lock is being acquired (for messages).
        lock_path: The lock-file path (for messages).
        timeout_seconds: The fail-fast acquisition timeout in seconds.

    Raises:
        WorkspaceLockTimeoutError: If the lock is not granted within the timeout.
    """
    if sys.platform == "win32":
        with _exclusive_kernel_lock_windows(lock_fd, workspace_root, lock_path, timeout_seconds):
            yield
    else:
        with _exclusive_kernel_lock_posix(lock_fd, workspace_root, lock_path, timeout_seconds):
            yield


@contextlib.contextmanager
def _exclusive_kernel_lock_posix(
    lock_fd: IO[bytes],
    workspace_root: pathlib.Path,
    lock_path: pathlib.Path,
    timeout_seconds: int,
) -> Iterator[None]:
    """POSIX backend: ``fcntl.flock(LOCK_EX)`` with a ``SIGALRM`` fail-fast timeout.

    The blocking ``flock`` syscall is interrupted by a ``SIGALRM`` raised by a
    kernel interval timer (``signal.setitimer``). The handler raises
    ``WorkspaceLockTimeoutError``, which propagates out of the syscall (PEP 475
    does not retry when the handler raises). This is kernel-level blocking with
    no poll loop and no ``sleep``.
    """
    import fcntl
    import signal

    fileno = lock_fd.fileno()

    def _on_alarm(signum: int, frame: object) -> None:
        raise WorkspaceLockTimeoutError(
            f"ERROR: timed out acquiring the workspace lock for {workspace_root} "
            f"after {timeout_seconds}s.\n"
            f"Lock file: {lock_path}\n"
            f"Another process is holding the lock ({_stale_lock_diagnostics()}).\n"
            "If you believe the lock is stale (the owning process has exited), inspect it "
            "with 'kanon doctor --prune-cache' and remove the lock file once you have "
            "confirmed no kanon process is running against this workspace."
        )

    previous_handler = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        fcntl.flock(fileno, fcntl.LOCK_EX)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    try:
        yield
    finally:
        fcntl.flock(fileno, fcntl.LOCK_UN)


@contextlib.contextmanager
def _exclusive_kernel_lock_windows(
    lock_fd: IO[bytes],
    workspace_root: pathlib.Path,
    lock_path: pathlib.Path,
    timeout_seconds: int,
) -> Iterator[None]:
    """Windows backend: ``LockFileEx`` with ``WaitForSingleObject`` timeout.

    Uses the Win32 ``LockFileEx`` API with an OVERLAPPED event handle so that
    the kernel signals the event when the lock is granted, then waits on that
    event via ``WaitForSingleObject``.  This gives true kernel-level blocking
    with no poll loop and no ``sleep`` — the equivalent of the POSIX
    ``fcntl.flock`` + ``SIGALRM`` approach on Windows.

    ``UnlockFileEx`` is called in the finally block so the lock is always
    released, even if the caller's body raises.

    Args:
        lock_fd: An open writable file object for the lock file.
        workspace_root: The workspace whose lock is being acquired (for messages).
        lock_path: The lock-file path (for messages).
        timeout_seconds: The fail-fast acquisition timeout in seconds.

    Raises:
        WorkspaceLockTimeoutError: If the lock is not granted within the timeout.
        OSError: If a Win32 API call fails unexpectedly.
    """
    import ctypes
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", w.DWORD),
            ("OffsetHigh", w.DWORD),
            ("hEvent", w.HANDLE),
        ]

    signatures = {
        "CreateFileW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        "CreateEventW": ([w.LPVOID, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
        "LockFileEx": ([w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(OVERLAPPED)], w.BOOL),
        "UnlockFileEx": ([w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(OVERLAPPED)], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "CancelIoEx": ([w.HANDLE, ctypes.POINTER(OVERLAPPED)], w.BOOL),
        "GetOverlappedResult": ([w.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(w.DWORD), w.BOOL], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = args
        function.restype = result

    handle = kernel.CreateFileW(str(lock_path), 0xC0000000, 3, None, 4, 0x40000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    event = None
    acquired = False
    pending = False
    overlapped = OVERLAPPED()
    transferred = w.DWORD()
    try:
        event = kernel.CreateEventW(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        overlapped.hEvent = event
        acquired = bool(kernel.LockFileEx(handle, 2, 0, 1, 0, ctypes.byref(overlapped)))
        if not acquired:
            error = ctypes.get_last_error()
            if error != 997:
                raise ctypes.WinError(error)
            pending = True
            status = kernel.WaitForSingleObject(event, min(timeout_seconds * 1000, 0xFFFFFFFE))
            if status == 258:
                raise WorkspaceLockTimeoutError(
                    f"ERROR: timed out acquiring the workspace lock for {workspace_root} "
                    f"after {timeout_seconds}s. Lock file: {lock_path}. "
                    f"Another process is holding the lock ({_stale_lock_diagnostics()}). "
                    "Wait for that process to finish; do not delete an active lock file."
                )
            if status != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                raise ctypes.WinError(ctypes.get_last_error())
            pending = False
            acquired = True
        yield
    finally:
        try:
            if pending:
                kernel.CancelIoEx(handle, ctypes.byref(overlapped))
                acquired = bool(
                    kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(transferred), True)
                )
                if not acquired and ctypes.get_last_error() != 995:
                    raise ctypes.WinError(ctypes.get_last_error())
            if acquired:
                if not kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(handle)
            if event:
                kernel.CloseHandle(event)
