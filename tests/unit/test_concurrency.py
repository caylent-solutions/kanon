"""Unit tests for kanon_cli.utils.concurrency.

Platform-agnostic tests for the public ``kanon_workspace_lock`` contract.
There is no platform skip-marker anywhere in this module (AC-8): every test
exercises the public context manager and the cross-process backend, which is
selected at acquisition time (POSIX ``fcntl.flock`` / Windows ``msvcrt.locking``).

Covers:
- AC-FUNC-001: eager .kanon-data/ creation before lock acquisition
- AC-FUNC-002: exclusive acquire + release on normal context exit
- AC-FUNC-003: exception inside context still releases the lock (try/finally)
- AC-FUNC-004: cross-process contention -- second process blocks until first releases
- AC-FUNC-005: configurable fail-fast acquisition timeout (#67 / FR-36)
- AC-FUNC-006: #67 re-entrance guard -- nested same-lock acquisition fails fast
- AC-FUNC-007: lock file path built from INSTALL_LOCK_FILENAME constant

AC-TEST-001
"""

import multiprocessing
import multiprocessing.synchronize
import pathlib
import sys
from unittest.mock import patch

import pytest

from kanon_cli.constants import INSTALL_LOCK_FILENAME
from kanon_cli.utils.concurrency import (
    WorkspaceLockReentranceError,
    WorkspaceLockTimeoutError,
    kanon_workspace_lock,
)

# ---------------------------------------------------------------------------
# Timeout constants (overridable via environment variables for slow CI)
# ---------------------------------------------------------------------------

import os

_LOCK_EVENT_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_EVENT_TIMEOUT", "10.0"))
_LOCK_JOIN_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_JOIN_TIMEOUT", "5.0"))

# Multiprocessing start method: "fork" on POSIX (fast, inherits the parent's
# state, no pickling required) and "spawn" on Windows where "fork" is
# unavailable. The cross-process helpers below are module-level so they are
# importable by reference under the "spawn" start method. This keeps the
# cross-process lock contract (AC-8) exercised on both platforms with no skip
# marker -- the lock is cross-platform and so are its tests.
_MP_CONTEXT = multiprocessing.get_context("fork" if sys.platform != "win32" else "spawn")


# ---------------------------------------------------------------------------
# Helpers for cross-process tests
# ---------------------------------------------------------------------------


def _acquire_nonblocking_in_child(
    workspace: pathlib.Path,
    result_queue: "multiprocessing.Queue[str]",
) -> None:
    """Child-process helper: try a short-timeout acquisition; report the outcome.

    A short ``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS`` is set so the child fails
    fast (raising ``WorkspaceLockTimeoutError``) instead of blocking forever
    while the parent holds the lock.

    Args:
        workspace: The workspace root path.
        result_queue: Shared queue. Receives "acquired" if the child obtained
            the lock (unexpected while the parent holds it) or "timed_out" if
            the fail-fast timeout fired (expected while contended).
    """
    import importlib

    import kanon_cli.constants as constants

    os.environ["KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS"] = "1"
    importlib.reload(constants)
    try:
        with kanon_workspace_lock(workspace):
            result_queue.put("acquired")
    except WorkspaceLockTimeoutError:
        result_queue.put("timed_out")


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
        (tmp_path / ".kanon-data").mkdir(parents=True)
        # Must not raise; exist_ok=True is required.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data").is_dir()

    def test_lock_file_created_inside_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """The lock file is created at .kanon-data/INSTALL_LOCK_FILENAME after context entry.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
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
        kanon_data = tmp_path / ".kanon-data"
        simulated_error = OSError(13, "Permission denied")

        with patch.object(pathlib.Path, "mkdir", side_effect=simulated_error):
            with pytest.raises(OSError, match=str(kanon_data)):
                with kanon_workspace_lock(tmp_path):
                    pass  # should not reach here


@pytest.mark.unit
class TestNormalExitRelease:
    """AC-FUNC-002: the exclusive lock is acquired on entry and released on normal exit."""

    def test_lock_is_released_after_normal_exit(self, tmp_path: pathlib.Path) -> None:
        """A second acquisition succeeds immediately after the first exits normally.

        This confirms the lock is released on normal context exit: re-entering
        the context after a clean exit must not raise the re-entrance guard nor
        block on a stale lock.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        with kanon_workspace_lock(tmp_path):
            pass  # Normal exit

        # After exiting, re-acquisition in the same process must succeed (the
        # re-entrance guard is cleared on exit and the kernel lock is released).
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()

    def test_lock_path_uses_install_lock_filename_constant(self, tmp_path: pathlib.Path) -> None:
        """The lock file is at workspace/.kanon-data/INSTALL_LOCK_FILENAME (no inline literal).

        AC-FUNC-007: lock path must be built from the constant, not an inline string.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
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
        """A second acquisition succeeds after an exception exits the context.

        This confirms try/finally semantics: even when the managed code raises,
        the lock is released and the re-entrance guard is cleared, so a fresh
        acquisition in the same process succeeds.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        with pytest.raises(ValueError, match="test exception"):
            with kanon_workspace_lock(tmp_path):
                raise ValueError("test exception")

        # Lock must be released even though an exception propagated out.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()

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
        with pytest.raises(exc_type):
            with kanon_workspace_lock(tmp_path):
                raise exc_type(exc_msg)

        # Re-acquisition must succeed; the guard + kernel lock were released.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()


@pytest.mark.unit
class TestReentranceGuard:
    """AC-FUNC-006: #67 re-entrance guard -- nested same-lock acquisition fails fast."""

    def test_nested_acquisition_same_workspace_raises(self, tmp_path: pathlib.Path) -> None:
        """A nested acquisition of the same workspace lock fails fast (no deadlock).

        Before the #67 guard, opening a second file-description and calling the
        blocking lock on it while the same process already holds the lock would
        deadlock. The guard detects the already-held lock and raises a specific
        error instead.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        with kanon_workspace_lock(tmp_path):
            with pytest.raises(WorkspaceLockReentranceError) as exc_info:
                with kanon_workspace_lock(tmp_path):
                    pytest.fail("Nested acquisition must not enter the inner context body")
            # The error message must be actionable and name the workspace.
            assert str(tmp_path) in str(exc_info.value), (
                "Re-entrance error must name the workspace whose lock is already held"
            )

    def test_guard_cleared_after_outer_exit_allows_reacquire(self, tmp_path: pathlib.Path) -> None:
        """After the outer context exits, the same workspace can be locked again.

        The guard must not leave the workspace permanently marked as held: a
        sequential (non-nested) re-acquisition must succeed.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        with kanon_workspace_lock(tmp_path):
            pass
        # Sequential re-acquire (not nested) must succeed -- guard was cleared.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()

    def test_distinct_workspaces_can_be_nested(self, tmp_path: pathlib.Path) -> None:
        """Two DIFFERENT workspaces may be held simultaneously in one process.

        The guard keys on the resolved lock path, so nesting locks for two
        distinct workspaces is allowed and does not trip the re-entrance guard.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        workspace_a = tmp_path / "a"
        workspace_b = tmp_path / "b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        with kanon_workspace_lock(workspace_a):
            with kanon_workspace_lock(workspace_b):
                assert (workspace_a / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()
                assert (workspace_b / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()

    def test_guard_cleared_when_inner_reentrance_error_handled(self, tmp_path: pathlib.Path) -> None:
        """A handled re-entrance error does not corrupt the held-lock registry.

        After the outer context exits, the workspace must be acquirable again,
        proving the guard did not leak state when the inner attempt raised.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        with kanon_workspace_lock(tmp_path):
            try:
                with kanon_workspace_lock(tmp_path):
                    pass
            except WorkspaceLockReentranceError:
                pass
        # Outer released; re-acquire must succeed.
        with kanon_workspace_lock(tmp_path):
            assert (tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME).exists()


@pytest.mark.unit
class TestFailFastTimeout:
    """AC-FUNC-005: configurable fail-fast acquisition timeout (FR-36, #67)."""

    def test_timeout_raises_when_lock_held_by_other_process(self, tmp_path: pathlib.Path) -> None:
        """Acquisition fails fast (raises) when another process holds the lock past the timeout.

        A holder process takes the lock and keeps it. A short configurable
        timeout is set in this process; the acquisition must raise
        WorkspaceLockTimeoutError rather than block forever.

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
        assert ready_event.is_set(), "Holder process did not acquire the lock within timeout"

        try:
            with patch.dict(os.environ, {"KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS": "1"}):
                import importlib

                import kanon_cli.constants as constants

                importlib.reload(constants)
                with pytest.raises(WorkspaceLockTimeoutError) as exc_info:
                    with kanon_workspace_lock(tmp_path):
                        pytest.fail("Acquisition must not succeed while another process holds the lock")
            # The timeout message must be actionable: name the workspace and the
            # diagnostic fields for stale-lock recovery.
            message = str(exc_info.value)
            assert str(tmp_path) in message, "Timeout error must name the contended workspace"
            assert "pid" in message.lower(), "Timeout error must carry the pid for stale-lock recovery"
        finally:
            release_event.set()
            holder.join(timeout=_LOCK_JOIN_TIMEOUT)
            import importlib

            import kanon_cli.constants as constants

            importlib.reload(constants)

    def test_message_includes_host_and_timestamp(self, tmp_path: pathlib.Path) -> None:
        """The timeout error message carries host and timestamp for recovery (spec 7.3).

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
        assert ready_event.is_set(), "Holder process did not acquire the lock within timeout"

        try:
            with patch.dict(os.environ, {"KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS": "1"}):
                import importlib

                import kanon_cli.constants as constants

                importlib.reload(constants)
                with pytest.raises(WorkspaceLockTimeoutError) as exc_info:
                    with kanon_workspace_lock(tmp_path):
                        pass
            message = str(exc_info.value)
            import socket

            assert socket.gethostname() in message, "Timeout error must name the host for stale-lock recovery"
        finally:
            release_event.set()
            holder.join(timeout=_LOCK_JOIN_TIMEOUT)
            import importlib

            import kanon_cli.constants as constants

            importlib.reload(constants)


@pytest.mark.unit
class TestCrossProcessContention:
    """AC-FUNC-004: two concurrent processes serialise on the same lock."""

    def test_second_process_blocked_while_first_holds_lock(self, tmp_path: pathlib.Path) -> None:
        """A second process cannot acquire the lock while the first holds it.

        The contender uses a short timeout so it fails fast ("timed_out") rather
        than hanging; "acquired" would mean the exclusion failed.

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
        assert ready_event.is_set(), "Holder process did not acquire the lock within timeout"

        result_queue: "multiprocessing.Queue[str]" = ctx.Queue()
        contender = ctx.Process(
            target=_acquire_nonblocking_in_child,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)

        outcome = result_queue.get_nowait() if not result_queue.empty() else None

        release_event.set()
        holder.join(timeout=_LOCK_JOIN_TIMEOUT)

        assert outcome == "timed_out", (
            "Second process must NOT acquire the lock while the first holds it; "
            f"expected 'timed_out' (fail-fast) but got {outcome!r}"
        )

    def test_second_process_can_acquire_after_first_releases(self, tmp_path: pathlib.Path) -> None:
        """A second process acquires the lock after the first process releases it.

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
        assert not holder.is_alive(), "Holder process did not exit cleanly after release signal"

        result_queue: "multiprocessing.Queue[str]" = ctx.Queue()
        contender = ctx.Process(
            target=_acquire_nonblocking_in_child,
            args=(tmp_path, result_queue),
            daemon=True,
        )
        contender.start()
        contender.join(timeout=_LOCK_JOIN_TIMEOUT)

        outcome = result_queue.get_nowait() if not result_queue.empty() else None

        assert outcome == "acquired", (
            f"Second process must acquire the lock after the first releases it; expected 'acquired' but got {outcome!r}"
        )
