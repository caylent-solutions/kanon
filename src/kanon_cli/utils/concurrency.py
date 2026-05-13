"""Workspace concurrency lock helper.

Provides the ``kanon_workspace_lock`` context manager that serialises
concurrent mutations to a kanon workspace. Any command that mutates
workspace state (kanon install, kanon add, kanon remove,
kanon doctor --refresh-completion-cache) must wrap its mutation
inside this context manager.

Lock mechanics
--------------
The context manager acquires an exclusive ``fcntl.LOCK_EX`` lock on
``.kanon-data/INSTALL_LOCK_FILENAME`` before yielding control to the
caller. The lock is released (and the file descriptor closed) on exit
regardless of whether the body raised an exception (try/finally semantics).

The lock is process-local in the sense that the kernel grants it per
file-description: two threads in the same process that both call
``fcntl.flock(LOCK_EX)`` on the SAME open file-description DO NOT
deadlock -- they share ownership. If two threads each open the file
separately and call ``flock(LOCK_EX)`` on their own FD, they will
deadlock. The wrapper documents this: ``kanon_workspace_lock`` opens a
new file-description every time it is entered, so nested invocations
within the same process will deadlock. Do NOT nest this context manager
within the same process.

Eager creation
--------------
Before opening the lock file, the context manager creates
``.kanon-data/`` with ``parents=True, exist_ok=True``. This ensures
that a fresh workspace with no prior kanon operations does not hit a
``FileNotFoundError`` when the lock file path is opened.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 7.5 (Concurrency and atomicity).
"""

from __future__ import annotations

import contextlib
import fcntl
import pathlib
from collections.abc import Generator

from kanon_cli.constants import INSTALL_LOCK_FILENAME


@contextlib.contextmanager
def kanon_workspace_lock(workspace_root: pathlib.Path) -> Generator[None, None, None]:
    """Acquire an exclusive workspace lock and yield; release on exit.

    Creates ``.kanon-data/`` (with ``parents=True, exist_ok=True``) before
    opening the lock file so a fresh workspace does not fail with
    ``FileNotFoundError``.

    The lock is ``fcntl.LOCK_EX`` (blocking exclusive). The calling process
    blocks here until any other process that holds ``LOCK_EX`` or ``LOCK_SH``
    on the same file releases it. The kernel releases the lock automatically
    when the file descriptor is closed (on normal exit, exception exit, or
    process termination), so a crashed process never leaves the workspace
    permanently locked.

    .. warning::
        Do NOT nest this context manager within the same process. Opening a
        new file-description (which this function does on every entry) and
        then calling ``flock(LOCK_EX)`` on it while the same process already
        holds ``LOCK_EX`` via a different file-description will deadlock.
        ``fcntl.flock`` on Linux does NOT upgrade an existing lock when called
        on a new FD in the same process -- it queues a new lock request that
        can never be granted while the first FD is open.

    Args:
        workspace_root: The project root directory. The lock file is created
            at ``workspace_root / ".kanon-data" / INSTALL_LOCK_FILENAME``.

    Yields:
        Nothing. The caller holds the exclusive lock during the body.

    Raises:
        OSError: If ``.kanon-data/`` cannot be created (e.g. permission denied)
            or if the lock file cannot be opened.
    """
    kanon_data_dir = workspace_root / ".kanon-data"
    try:
        kanon_data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Cannot create source directory {kanon_data_dir}: {exc.strerror}") from exc

    lock_path = kanon_data_dir / INSTALL_LOCK_FILENAME
    with open(lock_path, "w", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
