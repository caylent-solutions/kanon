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
``sleep``** (CLAUDE.md "no time-based synchronization"). The POSIX ``import fcntl`` and the Windows ``import ctypes``/``import msvcrt``
live **inside** their respective backend functions, so importing this module
never fails on a platform that lacks either module (there is no column-0
module-top ``import fcntl`` or ``import msvcrt``).

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

    The lock is an exclusive kernel-level lock acquired through the POSIX
    backend (``fcntl.flock``). The calling process blocks here until any other
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

    with open(lock_path, "wb") as lock_fd:
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
    import ctypes.wintypes
    import msvcrt

    kernel32: ctypes.WinDLL = ctypes.windll.kernel32  # type: ignore[attr-defined]

    LOCKFILE_EXCLUSIVE_LOCK: int = 0x00000002
    WAIT_TIMEOUT: int = 0x00000102
    ERROR_IO_PENDING: int = 997

    class _OffsetStruct(ctypes.Structure):
        _fields_ = [("Offset", ctypes.wintypes.DWORD), ("OffsetHigh", ctypes.wintypes.DWORD)]

    class _OffsetUnion(ctypes.Union):
        _fields_ = [("s", _OffsetStruct), ("Pointer", ctypes.c_void_p)]

    class OVERLAPPED(ctypes.Structure):
        _anonymous_ = ("_u",)
        _fields_ = [
            ("Internal", ctypes.c_ulong),
            ("InternalHigh", ctypes.c_ulong),
            ("_u", _OffsetUnion),
            ("hEvent", ctypes.wintypes.HANDLE),
        ]

    handle = msvcrt.get_osfhandle(lock_fd.fileno())

    # Manual-reset event, starts unsignaled.  The kernel signals it when
    # LockFileEx grants the lock.
    event: ctypes.wintypes.HANDLE = kernel32.CreateEventW(None, True, False, None)
    if not event:
        raise OSError(
            f"CreateEventW failed during workspace lock acquisition"
            f" (GetLastError={ctypes.get_last_error()})"
        )

    overlapped = OVERLAPPED()
    overlapped.hEvent = event

    try:
        success: int = kernel32.LockFileEx(
            handle,
            ctypes.wintypes.DWORD(LOCKFILE_EXCLUSIVE_LOCK),
            ctypes.wintypes.DWORD(0),  # reserved
            ctypes.wintypes.DWORD(1),  # lock one byte
            ctypes.wintypes.DWORD(0),
            ctypes.byref(overlapped),
        )

        last_err = ctypes.get_last_error()
        if not success and last_err != ERROR_IO_PENDING:
            raise OSError(
                f"LockFileEx failed (GetLastError={last_err})"
                f" while acquiring workspace lock for {workspace_root}"
            )

        if not success:
            # ERROR_IO_PENDING: lock contested; wait for the kernel to grant it.
            timeout_ms: int = int(timeout_seconds * 1000)
            wait_result: int = kernel32.WaitForSingleObject(
                event, ctypes.wintypes.DWORD(timeout_ms)
            )

            if wait_result == WAIT_TIMEOUT:
                kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
                raise WorkspaceLockTimeoutError(
                    f"ERROR: timed out acquiring the workspace lock for {workspace_root} "
                    f"after {timeout_seconds}s.\n"
                    f"Lock file: {lock_path}\n"
                    f"Another process is holding the lock ({_stale_lock_diagnostics()}).\n"
                    "If you believe the lock is stale (the owning process has exited), inspect it "
                    "with 'kanon doctor --prune-cache' and remove the lock file once you have "
                    "confirmed no kanon process is running against this workspace."
                )
    finally:
        kernel32.CloseHandle(event)

    unlock_overlapped = OVERLAPPED()
    try:
        yield
    finally:
        kernel32.UnlockFileEx(
            handle,
            ctypes.wintypes.DWORD(0),  # reserved
            ctypes.wintypes.DWORD(1),  # same byte range as the lock
            ctypes.wintypes.DWORD(0),
            ctypes.byref(unlock_overlapped),
        )
