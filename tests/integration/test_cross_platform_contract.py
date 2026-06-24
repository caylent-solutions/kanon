"""POSIX contract integration tests (J11, AC-56).

Asserts the POSIX contract of:
- kanon_workspace_lock: cross-process exclusion, release on exit/exception,
  fail-fast on configurable timeout.
- spawn_detached: detached-process spawn contract (POSIX fork path).
- create_dirsymlink: symlink dir-link helper.

Kanon is POSIX-only; the Windows backends were removed (the recommended
Windows path is WSL/WSL2), so there are no Windows-specific branches to
exercise here.

The workspace-lock tests use the real ``kanon_workspace_lock`` context manager
via child processes; the POSIX backend (``fcntl.flock``) gives cross-process
exclusion, asserted here through a non-blocking ``fcntl.flock`` probe of the same
lock region the context manager locks.

No platform-conditional guards are used -- the contract test file collects and
runs on the single Linux set.

FR-34, FR-35, FR-36: spawn_detached and create_dirsymlink POSIX contract.
AC-56: real assertions for every contract property; no platform guards.
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.synchronize
import os
import pathlib
from unittest.mock import patch

import pytest


_LOCK_EVENT_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_EVENT_TIMEOUT", "10.0"))
_LOCK_JOIN_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_JOIN_TIMEOUT", "5.0"))


def _hold_lock_then_signal(
    workspace: pathlib.Path,
    ready_event: "multiprocessing.synchronize.Event",
    release_event: "multiprocessing.synchronize.Event",
) -> None:
    """Child-process helper: acquire workspace lock, signal ready, wait to release.

    Args:
        workspace: Workspace root path.
        ready_event: Set after lock is acquired.
        release_event: Child waits on this before exiting (releasing the lock).
    """
    from kanon_cli.utils.concurrency import kanon_workspace_lock

    with kanon_workspace_lock(workspace):
        ready_event.set()
        release_event.wait(timeout=_LOCK_EVENT_TIMEOUT)


def _attempt_nonblocking_lock(
    workspace: pathlib.Path,
    result_queue: "multiprocessing.Queue[bool]",
) -> None:
    """Child-process helper: probe the workspace lock NON-blocking; report the result.

    Probes the exact lock-file region that the production
    ``kanon_workspace_lock`` POSIX backend locks, using the OS-native
    non-blocking primitive so there is no acquisition timeout to race:

    * POSIX: ``fcntl.flock(LOCK_EX | LOCK_NB)`` -- raises ``BlockingIOError`` when
      another process already holds the exclusive lock.

    Reports True when the probe acquired the lock (no other holder) and False
    when it was blocked by an existing holder.

    Args:
        workspace: Workspace root path.
        result_queue: Queue for reporting the outcome.
    """
    import fcntl

    from kanon_cli.constants import INSTALL_LOCK_FILENAME

    lock_path = workspace / ".kanon-data" / INSTALL_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            result_queue.put(True)
        except BlockingIOError:
            result_queue.put(False)


def _noop_refresh() -> None:
    """No-op module-level callable (picklable by reference)."""


_MP_CONTEXT = multiprocessing.get_context("fork")


@pytest.mark.integration
class TestWorkspaceLockCrossProcessExclusion:
    """Cross-process exclusion contract for kanon_workspace_lock.

    kanon_workspace_lock acquires an exclusive kernel-level lock through the
    POSIX backend (``fcntl.flock``). These tests assert cross-process exclusion
    via child processes.
    """

    def test_second_process_blocked_while_first_holds_lock(self, tmp_path: pathlib.Path) -> None:
        """A second process cannot acquire the lock while the first holds it.

        Holds the lock in a child process, then a contender child probes the same
        lock region non-blocking (``fcntl.flock`` LOCK_NB) and must report it was
        blocked (False).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        ctx = _MP_CONTEXT
        ready_event = ctx.Event()
        release_event = ctx.Event()

        holder = ctx.Process(
            target=_hold_lock_then_signal,
            args=(tmp_path, ready_event, release_event),
            daemon=True,
        )
        holder.start()

        ready_event.wait(timeout=_LOCK_EVENT_TIMEOUT)
        assert ready_event.is_set(), "Holder did not acquire the lock within timeout"

        result_queue: multiprocessing.Queue[bool] = ctx.Queue()
        contender = ctx.Process(
            target=_attempt_nonblocking_lock,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)

        acquired = result_queue.get_nowait() if not result_queue.empty() else None

        release_event.set()
        holder.join(timeout=_LOCK_JOIN_TIMEOUT)

        assert acquired is False, (
            f"Second process must not acquire LOCK_NB while first holds LOCK_EX; result was {acquired!r}"
        )

    def test_second_process_acquires_after_first_releases(self, tmp_path: pathlib.Path) -> None:
        """A second process can acquire the lock after the first releases it.

        The holder child acquires then releases the lock; a contender child then
        acquires it successfully (reports True).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        ctx = _MP_CONTEXT
        ready_event = ctx.Event()
        release_event = ctx.Event()

        holder = ctx.Process(
            target=_hold_lock_then_signal,
            args=(tmp_path, ready_event, release_event),
            daemon=True,
        )
        holder.start()

        ready_event.wait(timeout=_LOCK_EVENT_TIMEOUT)
        release_event.set()
        holder.join(timeout=_LOCK_JOIN_TIMEOUT)
        assert not holder.is_alive(), "Holder did not exit cleanly after release"

        result_queue: multiprocessing.Queue[bool] = ctx.Queue()
        contender = ctx.Process(
            target=_attempt_nonblocking_lock,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)
        acquired = result_queue.get_nowait() if not result_queue.empty() else None

        assert acquired is True, f"Second process must acquire LOCK_NB after first releases; result was {acquired!r}"


@pytest.mark.integration
class TestWorkspaceLockReleaseOnExit:
    """Lock is released on both normal exit and exception exit.

    Release is asserted by a contender child process that acquires the lock
    after the holder has exited; the contender probes the POSIX ``fcntl.flock``
    lock region. A successful acquisition (True) proves the holder's lock was
    released.
    """

    def _assert_lock_acquirable_by_child(self, ctx, tmp_path: pathlib.Path) -> None:
        """Spawn a contender child and assert it acquires the (now-free) lock.

        Args:
            ctx: Multiprocessing context (fork on POSIX).
            tmp_path: Workspace root whose lock must currently be free.
        """
        result_queue: multiprocessing.Queue[bool] = ctx.Queue()
        contender = ctx.Process(
            target=_attempt_nonblocking_lock,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)
        acquired = result_queue.get_nowait() if not result_queue.empty() else None
        assert acquired is True, f"Lock must be acquirable after the holder exits; result was {acquired!r}"

    def test_lock_released_after_normal_context_exit(self, tmp_path: pathlib.Path) -> None:
        """The lock is acquirable by another process after a normal context exit.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        with kanon_workspace_lock(tmp_path):
            pass

        self._assert_lock_acquirable_by_child(_MP_CONTEXT, tmp_path)

    def test_lock_released_after_exception_exit(self, tmp_path: pathlib.Path) -> None:
        """The lock is acquirable after an exception propagates out of the context.

        Demonstrates try/finally semantics: even when managed code raises, the
        file descriptor is closed and the OS releases the lock.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        with pytest.raises(ValueError, match="forced exception"):
            with kanon_workspace_lock(tmp_path):
                raise ValueError("forced exception")

        self._assert_lock_acquirable_by_child(_MP_CONTEXT, tmp_path)


@pytest.mark.integration
class TestWorkspaceLockFailFastOnMkdirFailure:
    """Lock fails fast with OSError when .kanon-data/ cannot be created."""

    def test_raises_oserror_when_kanon_data_dir_cannot_be_created(self, tmp_path: pathlib.Path) -> None:
        """kanon_workspace_lock raises OSError immediately when mkdir fails.

        Fail-fast contract: a failed ``.kanon-data/`` creation surfaces as an
        OSError, never a silent skip.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        with patch.object(pathlib.Path, "mkdir", side_effect=OSError(13, "Permission denied")):
            with pytest.raises(OSError):
                with kanon_workspace_lock(tmp_path):
                    pass


@pytest.mark.integration
class TestSpawnDetachedContract:
    """POSIX spawn_detached contract (fork-based detached process)."""

    def test_posix_parent_returns_without_running_refresh_fn(self, tmp_path: pathlib.Path) -> None:
        """On POSIX, parent returns immediately after fork; refresh_fn runs in child.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.spawn import spawn_detached

        called: list[str] = []

        def refresh_fn() -> None:
            called.append("parent_called")

        with patch("os.fork", return_value=42) as mock_fork:
            spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")
            mock_fork.assert_called_once()

        assert called == [], "refresh_fn must not run in the parent process after fork"

    def test_posix_fork_failure_raises_runtime_error(self, tmp_path: pathlib.Path) -> None:
        """On POSIX, an os.fork failure raises RuntimeError (fail-fast contract).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.spawn import spawn_detached

        with patch("os.fork", side_effect=OSError("resource limit reached")):
            with pytest.raises(RuntimeError, match="spawn_detached: failed to fork"):
                spawn_detached(_noop_refresh, log_path=tmp_path / "errors.log")

    def test_child_exception_recorded_to_log_not_swallowed(self, tmp_path: pathlib.Path) -> None:
        """On POSIX, a failing refresh_fn has its traceback written to log_path.

        Demonstrates fail-fast/no-silent-failure contract: the detached child
        must record its failure rather than losing it.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.spawn import spawn_detached

        log_path = tmp_path / "child_errors" / "errors.log"

        def failing_refresh() -> None:
            raise RuntimeError("child refresh failed")

        with (
            patch("os.fork", return_value=0),
            patch("os.setsid"),
            patch("os.open", return_value=5),
            patch("os.dup2"),
            patch("os.close"),
            patch("os._exit") as mock_exit,
        ):
            spawn_detached(failing_refresh, log_path=log_path)
            mock_exit.assert_called_once_with(1)

        assert log_path.exists(), "Child must record its error to log_path (fail-fast)"
        content = log_path.read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert "child refresh failed" in content


@pytest.mark.integration
class TestCreateDirsymlinkContract:
    """POSIX symlink dir-link helper contract (os.symlink)."""

    def test_posix_creates_symlink_pointing_to_target(self, tmp_path: pathlib.Path) -> None:
        """On POSIX, create_dirsymlink creates a symlink that resolves to the target.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.core.marketplace import create_dirsymlink

        target = tmp_path / "target_dir"
        target.mkdir()
        link_path = tmp_path / "link"

        create_dirsymlink(link_path, target)

        assert link_path.is_symlink(), "create_dirsymlink must create a symlink on POSIX"
        assert link_path.resolve() == target.resolve(), "Symlink must resolve to the target directory"

    def test_posix_raises_oserror_when_link_path_already_exists(self, tmp_path: pathlib.Path) -> None:
        """On POSIX, create_dirsymlink raises OSError if link_path already exists.

        Demonstrates fail-fast: the helper never silently skips a conflicting
        path.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.core.marketplace import create_dirsymlink

        target = tmp_path / "target_dir"
        target.mkdir()
        link_path = tmp_path / "link"
        link_path.mkdir()

        with pytest.raises(OSError):
            create_dirsymlink(link_path, target)
