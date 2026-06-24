"""Workspace concurrency lock helper.

Provides the ``kanon_workspace_lock`` context manager that serialises
concurrent mutations to a kanon workspace. Any command that mutates
workspace state (kanon install, kanon add, kanon remove,
kanon doctor --refresh-completion-cache) must wrap its mutation
inside this context manager.

Cross-platform backend (spec Section 4 / FR-32, FR-33, FR-36, issue #67)
------------------------------------------------------------------------
The context manager acquires an exclusive kernel-level lock on
``.kanon-data/INSTALL_LOCK_FILENAME`` before yielding control to the caller.
The backend is selected at acquisition time:

* POSIX (Linux, macOS): ``fcntl.flock(fd, LOCK_EX)``.
* Windows: ``msvcrt.locking(fd.fileno(), LK_LOCK, ...)``.

Both give **true kernel-level blocking with NO internal poll loop and NO
``sleep``** (CLAUDE.md "no time-based synchronization"). The POSIX
``import fcntl`` lives **inside** the POSIX branch, and ``import msvcrt`` lives
inside the Windows branch, so importing this module never fails on a platform
that lacks one of them (there is no column-0 module-top ``import fcntl``).

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
(pid / host / timestamp, spec Section 7.3). The timeout is enforced per-OS
without any poll loop or ``sleep``:

* POSIX: a kernel timer (``signal.setitimer`` / ``SIGALRM``) interrupts the
  blocking ``flock`` syscall on expiry (PEP 475 does not retry when the handler
  raises).
* Windows: the blocking ``msvcrt.locking`` runs on a worker thread and the
  calling thread waits on its completion with ``Thread.join(timeout_seconds)``;
  if the join returns while the worker is still blocked, the timeout has
  expired and the acquisition fails fast.

Eager creation
--------------
Before opening the lock file, the context manager creates ``.kanon-data/`` with
``parents=True, exist_ok=True`` so a fresh workspace does not hit a
``FileNotFoundError`` when the lock file path is opened.

Spec reference: ``specs/kanon-refinements.md`` Section 4 (cross-platform lock
interface), Section 7 (``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS``), Section 13.2
P4 (Option B fcntl/msvcrt); issue #67.
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

# Lock paths currently held by THIS process, keyed on the resolved absolute
# lock-file path. Used by the #67 re-entrance guard to fail fast on a nested
# acquisition of an already-held workspace lock instead of deadlocking.
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

    The lock is an exclusive kernel-level lock acquired through the per-OS
    backend selected at acquisition time (POSIX ``fcntl.flock``, Windows
    ``msvcrt.locking``). The calling process blocks here until any other process
    that holds the lock releases it, OR until the configured acquisition timeout
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

    # #67 re-entrance guard: fail fast on a nested acquisition of an already-held
    # workspace lock instead of opening a second file-description and deadlocking.
    if lock_key in _held_lock_paths:
        raise WorkspaceLockReentranceError(
            f"ERROR: workspace lock for {workspace_root} is already held by this process.\n"
            f"Lock file: {lock_path}\n"
            "kanon_workspace_lock must not be nested for the same workspace; a nested "
            "acquisition would deadlock. Refactor the caller so the mutation runs inside "
            "a single lock scope."
        )

    timeout_seconds = _acquire_timeout_seconds()
    # The lock file is opened in binary mode (not text) because the Windows
    # backend (``msvcrt.locking``) locks a byte region of the raw file
    # descriptor: a buffered TextIOWrapper offers no guarantee about the raw
    # fd's position, and locking a region of a 0-byte text file is unreliable.
    # Binary mode lets the Windows backend seek/write a single sentinel byte so
    # the locked region is always within the file on every platform. The POSIX
    # backend (``fcntl.flock``) is a whole-file lock and is mode-agnostic.
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
    """Acquire the per-OS exclusive kernel lock with a fail-fast timeout.

    Dispatches to the POSIX or Windows backend by platform. Both backends give
    kernel-level blocking with no poll loop and no ``sleep``; the timeout is a
    kernel timer that interrupts the blocking syscall on expiry.

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


def _seek_to_lock_region(lock_fd: IO[bytes]) -> None:
    """Ensure the lock file holds a sentinel byte and seek to its start.

    ``msvcrt.locking`` locks the byte region ``[pos, pos + nbytes)`` relative to
    the file descriptor's current position. On a freshly opened (0-byte) lock
    file that region would lie beyond end-of-file, which is unreliable on
    Windows. Writing a single sentinel byte and seeking back to offset 0
    guarantees the one-byte region ``[0, 1)`` is always within the file, so the
    same fixed region is locked by every process that contends for this
    workspace.

    Args:
        lock_fd: The open binary lock-file object.
    """
    lock_fd.seek(0)
    lock_fd.write(b"\0")
    lock_fd.flush()
    lock_fd.seek(0)


@contextlib.contextmanager
def _exclusive_kernel_lock_windows(
    lock_fd: IO[bytes],
    workspace_root: pathlib.Path,
    lock_path: pathlib.Path,
    timeout_seconds: int,
) -> Iterator[None]:
    """Windows backend: ``msvcrt.locking(LK_LOCK)`` with a fail-fast join timeout.

    ``msvcrt.locking(LK_LOCK, 1)`` provides kernel-level blocking on a fixed
    single-byte region (the OS, not this code, waits for the lock). The blocking
    acquisition runs on a worker thread; the calling thread waits on the
    thread's completion event with ``Thread.join(timeout_seconds)``. If the join
    returns while the worker is still blocked, the configured timeout has expired
    and the acquisition fails fast with ``WorkspaceLockTimeoutError``. The wait
    is event-driven (thread completion), not a poll loop, and contains no
    ``sleep``.

    A sentinel byte is written first (``_seek_to_lock_region``) so the locked
    region ``[0, 1)`` is always within the file rather than beyond EOF.
    """
    import threading

    import msvcrt

    _seek_to_lock_region(lock_fd)
    fileno = lock_fd.fileno()

    acquired = threading.Event()
    acquire_error: list[BaseException] = []

    def _blocking_acquire() -> None:
        try:
            # LK_LOCK blocks at the OS level until the single-byte region is
            # locked. The worker thread holds no Python-level loop while blocked.
            msvcrt.locking(fileno, msvcrt.LK_LOCK, 1)
        except BaseException as exc:  # surface to the caller; never swallow
            acquire_error.append(exc)
            return
        acquired.set()

    worker = threading.Thread(target=_blocking_acquire, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive() and not acquired.is_set():
        # The worker is still blocked in the kernel after the configured
        # timeout: fail fast. The OS releases the orphaned blocking attempt when
        # the descriptor is closed on context teardown.
        raise WorkspaceLockTimeoutError(
            f"ERROR: timed out acquiring the workspace lock for {workspace_root} "
            f"after {timeout_seconds}s.\n"
            f"Lock file: {lock_path}\n"
            f"Another process is holding the lock ({_stale_lock_diagnostics()}).\n"
            "If you believe the lock is stale (the owning process has exited), inspect it "
            "with 'kanon doctor --prune-cache' and remove the lock file once you have "
            "confirmed no kanon process is running against this workspace."
        )

    if acquire_error:
        raise acquire_error[0]

    try:
        yield
    finally:
        msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
