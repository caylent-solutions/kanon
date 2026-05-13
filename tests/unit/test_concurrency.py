"""Unit tests for kanon_cli.utils.concurrency.

Covers:
- AC-FUNC-001: eager .kanon-data/ creation before lock acquisition
- AC-FUNC-002: LOCK_EX acquire + release on normal context exit
- AC-FUNC-003: exception inside context still releases the lock (try/finally)
- AC-FUNC-004: cross-process contention -- second process blocks until first releases
- AC-FUNC-006: lock file path built from INSTALL_LOCK_FILENAME constant (no inline literals)

AC-TEST-001
"""

import fcntl
import multiprocessing
import multiprocessing.synchronize
import os
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.constants import INSTALL_LOCK_FILENAME


# ---------------------------------------------------------------------------
# Timeout constants (overridable via environment variables for slow CI)
# ---------------------------------------------------------------------------

_LOCK_EVENT_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_EVENT_TIMEOUT", "10.0"))
_LOCK_JOIN_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_JOIN_TIMEOUT", "5.0"))


# ---------------------------------------------------------------------------
# Helpers for cross-process tests
# ---------------------------------------------------------------------------


def _acquire_nb_succeeds(workspace: pathlib.Path, result_queue: "multiprocessing.Queue[bool]") -> None:
    """Child-process helper: try LOCK_NB on the workspace lock; report success/failure.

    Args:
        workspace: The workspace root path.
        result_queue: Shared queue; True = acquired (unexpected), False = blocked (expected).
    """
    lock_path = workspace / ".kanon-data" / INSTALL_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "w", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Acquired -- unexpected while parent holds it.
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            result_queue.put(True)
    except BlockingIOError:
        result_queue.put(False)


def _hold_lock_then_signal(
    workspace: pathlib.Path,
    ready_event: multiprocessing.synchronize.Event,
    release_event: multiprocessing.synchronize.Event,
) -> None:
    """Child-process helper: acquire the lock, signal ready, wait for release signal.

    Args:
        workspace: The workspace root path.
        ready_event: Set after the lock is acquired (signals parent).
        release_event: Process waits on this; set by parent to release lock.
    """
    from kanon_cli.utils.concurrency import kanon_workspace_lock

    with kanon_workspace_lock(workspace):
        ready_event.set()
        release_event.wait(timeout=_LOCK_EVENT_TIMEOUT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEagerCreate:
    """AC-FUNC-001: .kanon-data/ is created before the lock is acquired."""

    @pytest.mark.parametrize("sub_path", [None, "nested/project"])
    def test_creates_kanon_data_when_absent(self, tmp_path: pathlib.Path, sub_path: str | None) -> None:
        """kanon_workspace_lock creates .kanon-data/ if it does not exist.

        Args:
            tmp_path: Pytest-provided temporary directory.
            sub_path: Optional sub-path to nest the workspace under, exercising
                the parents=True branch.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        workspace = tmp_path if sub_path is None else tmp_path / sub_path
        workspace.mkdir(parents=True, exist_ok=True)
        kanon_data = workspace / ".kanon-data"
        assert not kanon_data.exists(), "Pre-condition: .kanon-data/ must not exist before the test"

        with kanon_workspace_lock(workspace):
            assert kanon_data.is_dir(), (
                ".kanon-data/ must exist inside the context manager body after kanon_workspace_lock acquires the lock"
            )

    def test_does_not_raise_when_kanon_data_already_exists(self, tmp_path: pathlib.Path) -> None:
        """kanon_workspace_lock does not fail when .kanon-data/ already exists (exist_ok=True).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        (tmp_path / ".kanon-data").mkdir(parents=True)
        # Must not raise; exist_ok=True is required.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data").is_dir()

    def test_lock_file_created_inside_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """The lock file is created at .kanon-data/INSTALL_LOCK_FILENAME after context entry.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        expected_lock = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME
        with kanon_workspace_lock(tmp_path):
            assert expected_lock.exists(), f"Lock file must exist at {expected_lock} while context is held"

    def test_raises_os_error_when_mkdir_fails(self, tmp_path: pathlib.Path) -> None:
        """kanon_workspace_lock raises OSError with context when .kanon-data/ mkdir fails.

        If the directory cannot be created (e.g., permission denied), the context
        manager must raise OSError immediately with a clear message that includes
        the directory path -- fail-fast, no silent fallback.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        kanon_data = tmp_path / ".kanon-data"
        simulated_error = OSError(13, "Permission denied")

        with patch.object(pathlib.Path, "mkdir", side_effect=simulated_error):
            with pytest.raises(OSError, match=str(kanon_data)):
                with kanon_workspace_lock(tmp_path):
                    pass  # should not reach here


@pytest.mark.unit
class TestNormalExitRelease:
    """AC-FUNC-002: LOCK_EX is acquired on entry and released on normal context exit."""

    def test_lock_is_released_after_normal_exit(self, tmp_path: pathlib.Path) -> None:
        """LOCK_NB acquisition succeeds immediately after context manager exits normally.

        This confirms the file descriptor is closed and fcntl lock released
        on normal context exit.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME

        with kanon_workspace_lock(tmp_path):
            pass  # Normal exit

        # After exiting the context, we should be able to acquire LOCK_NB immediately.
        with open(lock_path, "w", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pytest.fail(
                    "kanon_workspace_lock must release the exclusive lock on normal context exit; "
                    "LOCK_NB acquisition failed, indicating the FD is still held"
                )
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def test_lock_path_uses_install_lock_filename_constant(self, tmp_path: pathlib.Path) -> None:
        """The lock file is at workspace/.kanon-data/INSTALL_LOCK_FILENAME (no inline literal).

        AC-FUNC-006: lock path must be built from the constant, not an inline string.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        # Build the expected path from the constant -- same derivation as the impl.
        expected = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME
        with kanon_workspace_lock(tmp_path):
            assert expected.exists(), (
                f"Lock file must be at {{workspace}}/.kanon-data/{{INSTALL_LOCK_FILENAME}} "
                f"({expected}); found no file there"
            )


@pytest.mark.unit
class TestExceptionExitRelease:
    """AC-FUNC-003: exception inside context still releases the lock (try/finally)."""

    def test_lock_released_after_exception_in_context(self, tmp_path: pathlib.Path) -> None:
        """LOCK_NB acquisition succeeds after an exception exits the context.

        This confirms try/finally semantics: even when the managed code raises,
        the lock FD is closed and the kernel releases the lock.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME

        with pytest.raises(ValueError, match="test exception"):
            with kanon_workspace_lock(tmp_path):
                raise ValueError("test exception")

        # Lock must be released even though an exception propagated out.
        with open(lock_path, "w", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pytest.fail(
                    "kanon_workspace_lock must release the exclusive lock when an exception "
                    "propagates out of the context body (try/finally semantics required)"
                )
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    @pytest.mark.parametrize(
        "exc_type,exc_msg",
        [
            (RuntimeError, "runtime error"),
            (OSError, "os error"),
            (KeyboardInterrupt, "keyboard interrupt"),
        ],
        ids=["RuntimeError", "OSError", "KeyboardInterrupt"],
    )
    def test_lock_released_for_various_exception_types(
        self,
        tmp_path: pathlib.Path,
        exc_type: type[BaseException],
        exc_msg: str,
    ) -> None:
        """Lock is released for all exception types that propagate out of the context.

        Args:
            tmp_path: Pytest-provided temporary directory.
            exc_type: Exception class to raise inside the context.
            exc_msg: Exception message.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME

        with pytest.raises(exc_type):
            with kanon_workspace_lock(tmp_path):
                raise exc_type(exc_msg)

        with open(lock_path, "w", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pytest.fail(
                    f"Lock must be released when {exc_type.__name__} propagates out of kanon_workspace_lock context"
                )
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@pytest.mark.unit
class TestCrossProcessContention:
    """AC-FUNC-004: two concurrent processes serialise on the same lock."""

    def test_second_process_blocked_while_first_holds_lock(self, tmp_path: pathlib.Path) -> None:
        """Second process cannot acquire LOCK_NB while first process holds LOCK_EX.

        Uses multiprocessing.Event as a barrier so the parent holds the lock
        while the child attempts LOCK_NB; the child must report failure (False).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        ctx = multiprocessing.get_context("fork")
        ready_event = ctx.Event()
        release_event = ctx.Event()

        # First process: hold the lock until told to release.
        holder = ctx.Process(
            target=_hold_lock_then_signal,
            args=(tmp_path, ready_event, release_event),
            daemon=True,
        )
        holder.start()

        # Wait for holder to acquire the lock.
        ready_event.wait(timeout=_LOCK_EVENT_TIMEOUT)
        assert ready_event.is_set(), "Holder process did not acquire the lock within timeout"

        # Second process: attempt LOCK_NB while first holds LOCK_EX.
        result_queue: "multiprocessing.Queue[bool]" = ctx.Queue()
        contender = ctx.Process(
            target=_acquire_nb_succeeds,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)

        acquired = result_queue.get_nowait() if not result_queue.empty() else None

        # Release the holder after the contender finishes.
        release_event.set()
        holder.join(timeout=_LOCK_JOIN_TIMEOUT)

        assert acquired is False, (
            "Second process must NOT be able to acquire LOCK_NB while the first process "
            "holds LOCK_EX via kanon_workspace_lock. "
            f"Result was: {acquired!r} (True = unexpected lock acquisition succeeded)"
        )

    def test_second_process_can_acquire_after_first_releases(self, tmp_path: pathlib.Path) -> None:
        """Second process can acquire LOCK_NB after the first process releases the lock.

        Verifies that release is real: once the holder exits its context,
        the contender can acquire the non-blocking lock.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        ctx = multiprocessing.get_context("fork")
        ready_event = ctx.Event()
        release_event = ctx.Event()

        holder = ctx.Process(
            target=_hold_lock_then_signal,
            args=(tmp_path, ready_event, release_event),
            daemon=True,
        )
        holder.start()

        # Wait for holder, then tell it to release immediately.
        ready_event.wait(timeout=_LOCK_EVENT_TIMEOUT)
        release_event.set()
        holder.join(timeout=_LOCK_JOIN_TIMEOUT)
        assert not holder.is_alive(), "Holder process did not exit cleanly after release signal"

        # Now the second process should succeed with LOCK_NB.
        result_queue: "multiprocessing.Queue[bool]" = ctx.Queue()
        contender = ctx.Process(
            target=_acquire_nb_succeeds,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)

        acquired = result_queue.get_nowait() if not result_queue.empty() else None

        assert acquired is True, (
            "Second process must be able to acquire LOCK_NB after the first process "
            "releases via kanon_workspace_lock. "
            f"Result was: {acquired!r}"
        )
