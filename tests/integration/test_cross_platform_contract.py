"""Cross-platform contract integration tests (J11, AC-56).

Asserts the cross-platform contract of:
- kanon_workspace_lock: cross-process exclusion, release on exit/exception,
  fail-fast on configurable timeout.
- spawn_detached: detached-process spawn contract (POSIX and Windows paths).
- create_dirsymlink: junction/symlink dir-link helper.

The Windows-specific branches (junctions, DETACHED_PROCESS) are exercised
by mocking sys.platform so the contract is verified on any CI host.

On POSIX the workspace-lock tests use real fcntl-based exclusion via child
processes.  On Windows, fcntl is not available and the workspace-lock tests
assert the expected RuntimeError (fail-fast contract for unsupported platform).

No platform-conditional guards are used -- the full contract test file
collects and runs on every platform in the matrix.

FR-32: windows-latest CI matrix leg runs this file natively on Windows.
FR-34, FR-35, FR-36: spawn_detached and create_dirsymlink cross-platform
    contract.
AC-56: real assertions for every contract property; no platform guards.
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.synchronize
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Timeout constants (configurable for slow CI via environment variables)
# ---------------------------------------------------------------------------

_LOCK_EVENT_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_EVENT_TIMEOUT", "10.0"))
_LOCK_JOIN_TIMEOUT = float(os.environ.get("KANON_TEST_LOCK_JOIN_TIMEOUT", "5.0"))


# ---------------------------------------------------------------------------
# Module-level helpers for multiprocessing child processes (spawn-safe)
# ---------------------------------------------------------------------------


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
    """Child-process helper: try LOCK_NB and report True (acquired) or False (blocked).

    Args:
        workspace: Workspace root path.
        result_queue: Queue for reporting the outcome.
    """
    import fcntl

    from kanon_cli.constants import INSTALL_LOCK_FILENAME

    lock_path = workspace / ".kanon-data" / INSTALL_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "w", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            result_queue.put(True)
    except BlockingIOError:
        result_queue.put(False)


# ---------------------------------------------------------------------------
# Module-level callable for spawn_detached picklability tests
# ---------------------------------------------------------------------------


def _noop_refresh() -> None:
    """No-op module-level callable (picklable by reference)."""


# ---------------------------------------------------------------------------
# Multiprocessing context: use "fork" on POSIX (fast, no pickling required),
# "spawn" on Windows (fork is unavailable).
# ---------------------------------------------------------------------------

_MP_CONTEXT = multiprocessing.get_context("fork" if sys.platform != "win32" else "spawn")


# ---------------------------------------------------------------------------
# kanon_workspace_lock contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkspaceLockCrossProcessExclusion:
    """Cross-process exclusion contract for kanon_workspace_lock.

    On Windows, kanon_workspace_lock raises RuntimeError because fcntl is
    unavailable.  These tests assert the POSIX flock exclusion on POSIX and
    the fail-fast RuntimeError on Windows.
    """

    def test_second_process_blocked_while_first_holds_lock(self, tmp_path: pathlib.Path) -> None:
        """A second process cannot acquire LOCK_NB while the first holds LOCK_EX (POSIX).

        On Windows, kanon_workspace_lock raises RuntimeError immediately
        (fcntl unavailable), which is the correct fail-fast contract.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        if sys.platform == "win32":
            from kanon_cli.utils.concurrency import kanon_workspace_lock

            with pytest.raises(RuntimeError, match="not supported on Windows"):
                with kanon_workspace_lock(tmp_path):
                    pass
            return

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
        """A second process can acquire the lock after the first releases it (POSIX).

        On Windows, kanon_workspace_lock raises RuntimeError immediately
        (fcntl unavailable), which is the correct fail-fast contract.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        if sys.platform == "win32":
            from kanon_cli.utils.concurrency import kanon_workspace_lock

            with pytest.raises(RuntimeError, match="not supported on Windows"):
                with kanon_workspace_lock(tmp_path):
                    pass
            return

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
    """Lock is released on both normal exit and exception exit (POSIX only)."""

    def test_lock_released_after_normal_context_exit(self, tmp_path: pathlib.Path) -> None:
        """LOCK_NB succeeds immediately after a normal context exit (POSIX).

        On Windows, kanon_workspace_lock raises RuntimeError immediately
        because fcntl is unavailable; the fail-fast RuntimeError IS the
        contract on that platform.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        if sys.platform == "win32":
            with pytest.raises(RuntimeError, match="not supported on Windows"):
                with kanon_workspace_lock(tmp_path):
                    pass
            return

        import fcntl

        from kanon_cli.constants import INSTALL_LOCK_FILENAME

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME

        with kanon_workspace_lock(tmp_path):
            pass

        with open(lock_path, "w", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                pytest.fail("Lock was not released after normal context exit")

    def test_lock_released_after_exception_exit(self, tmp_path: pathlib.Path) -> None:
        """LOCK_NB succeeds immediately after an exception propagates out of context.

        Demonstrates try/finally semantics: even when managed code raises, the
        file descriptor is closed and the OS releases the lock.

        On Windows, kanon_workspace_lock raises RuntimeError immediately
        (fcntl unavailable); the fail-fast RuntimeError IS the contract.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        if sys.platform == "win32":
            with pytest.raises(RuntimeError, match="not supported on Windows"):
                with kanon_workspace_lock(tmp_path):
                    pass
            return

        import fcntl

        from kanon_cli.constants import INSTALL_LOCK_FILENAME

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME

        with pytest.raises(ValueError, match="forced exception"):
            with kanon_workspace_lock(tmp_path):
                raise ValueError("forced exception")

        with open(lock_path, "w", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                pytest.fail("Lock was not released after exception propagated from context")


@pytest.mark.integration
class TestWorkspaceLockFailFastOnMkdirFailure:
    """Lock fails fast with OSError when .kanon-data/ cannot be created."""

    def test_raises_oserror_when_kanon_data_dir_cannot_be_created(self, tmp_path: pathlib.Path) -> None:
        """kanon_workspace_lock raises OSError immediately when mkdir fails.

        On Windows, the RuntimeError for fcntl-unavailable is raised before
        mkdir is attempted; the test asserts RuntimeError on that platform.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.utils.concurrency import kanon_workspace_lock

        if sys.platform == "win32":
            with pytest.raises(RuntimeError, match="not supported on Windows"):
                with kanon_workspace_lock(tmp_path):
                    pass
            return

        with patch.object(pathlib.Path, "mkdir", side_effect=OSError(13, "Permission denied")):
            with pytest.raises(OSError):
                with kanon_workspace_lock(tmp_path):
                    pass


# ---------------------------------------------------------------------------
# spawn_detached contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSpawnDetachedContract:
    """Cross-platform spawn_detached contract."""

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

    def test_windows_path_uses_detached_process_flag(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows path launches subprocess with DETACHED_PROCESS flag (0x8).

        The contract is verified by mocking sys.platform so the Windows branch
        executes on any CI host.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        if sys.platform != "win32":
            monkeypatch.setattr(sys, "platform", "win32")

        from kanon_cli.utils.spawn import spawn_detached

        mock_proc = MagicMock()
        mock_proc.pid = 1234

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawn_detached(_noop_refresh, log_path=tmp_path / "errors.log")
            mock_popen.assert_called_once()
            kwargs = mock_popen.call_args[1]
            assert kwargs.get("creationflags", 0) & 0x00000008, "Windows spawn must set DETACHED_PROCESS flag (0x8)"

    def test_windows_popen_failure_raises_runtime_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows path raises RuntimeError on Popen failure (fail-fast contract).

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        if sys.platform != "win32":
            monkeypatch.setattr(sys, "platform", "win32")

        from kanon_cli.utils.spawn import spawn_detached

        with patch("subprocess.Popen", side_effect=OSError("access denied")):
            with pytest.raises(RuntimeError, match="spawn_detached: failed to spawn"):
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


# ---------------------------------------------------------------------------
# create_dirsymlink contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateDirsymlinkContract:
    """Junction/symlink dir-link helper cross-platform contract."""

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

    def test_windows_path_runs_mklink_j(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On Windows, create_dirsymlink runs mklink /J (NTFS junction).

        The Windows branch is exercised by mocking sys.platform so the
        contract is verified on any CI host.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        if sys.platform != "win32":
            monkeypatch.setattr(sys, "platform", "win32")

        from kanon_cli.core.marketplace import create_dirsymlink

        target = tmp_path / "target_dir"
        target.mkdir()
        link_path = tmp_path / "link"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            create_dirsymlink(link_path, target)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "/J" in cmd, "Windows junction must use mklink /J flag"
            assert str(link_path) in cmd
            assert str(target) in cmd

    def test_windows_path_raises_oserror_on_mklink_failure(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows, a non-zero mklink exit raises OSError (fail-fast contract).

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        if sys.platform != "win32":
            monkeypatch.setattr(sys, "platform", "win32")

        from kanon_cli.core.marketplace import create_dirsymlink

        target = tmp_path / "target_dir"
        link_path = tmp_path / "link"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Access is denied."

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(OSError, match="junction"):
                create_dirsymlink(link_path, target)

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
        link_path.mkdir()  # pre-existing directory, not a symlink

        with pytest.raises(OSError):
            create_dirsymlink(link_path, target)
