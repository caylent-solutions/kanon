"""Unit tests for kanon_cli.utils.spawn.spawn_detached.

TDD-paired test file covering:
- spawn_detached success: child runs the target callable and parent returns
  immediately (no blocking wait).
- spawn_detached failure: a spawn error fails fast by raising RuntimeError
  with an actionable message (no silent fallback).
- Windows picklability: the callable passed by the real cache.py callsite
  (fork_background_refresh) is picklable so the Windows path works end-to-end.
- POSIX directory hardening: the log directory is created with mode 0700.

No os.fork is used in the test itself -- tests exercise the public interface
via mocking so the suite runs cross-platform.
"""

from __future__ import annotations

import functools
import os
import pickle
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.utils.spawn import spawn_detached


# ---------------------------------------------------------------------------
# Module-level callables used for picklable Windows tests.
#
# The Windows spawn path serialises the callable via pickle. Nested closures
# are NOT picklable; module-level functions and functools.partial wrappers of
# them ARE. The PRODUCTION callsite
# (kanon_cli.completions.cache.fork_background_refresh) passes a
# functools.partial of a module-level function, so the Windows tests below use
# the SAME shape -- a functools.partial of a module-level function -- rather
# than a bare module-level function, so the test cannot pass while the real
# (partial) path would fail.
# ---------------------------------------------------------------------------


def _noop_refresh() -> None:
    """No-op module-level refresh callable (picklable by reference).

    Used where the callable is passed to fork_background_refresh, which wraps
    it in a module-level functools.partial -- the picklable production shape.
    """


def _refresh_target(*, marker: list[str]) -> None:
    """Module-level refresh target used to build a production-shaped partial.

    Mirrors the real callsite, where fork_background_refresh binds a
    module-level function with functools.partial.
    """
    marker.append("ran")


def _production_shaped_refresh() -> functools.partial[None]:
    """Build a functools.partial of a module-level function.

    This is the EXACT callable shape the production callsite passes to
    spawn_detached (a functools.partial of a module-level function, never a
    nested closure), so the Windows picklability tests exercise the real path.
    """
    return functools.partial(_refresh_target, marker=[])


# ---------------------------------------------------------------------------
# POSIX tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_spawn_detached_success_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On POSIX, spawn_detached forks a child that runs refresh_fn and the
    parent returns immediately without blocking.

    We mock os.fork to return a non-zero PID (parent path) to verify that
    the parent branch exits after fork without executing refresh_fn itself.
    """
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("child_called")

    # Simulate parent path: fork returns non-zero PID.
    with patch("os.fork", return_value=42) as mock_fork:
        spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")
        mock_fork.assert_called_once()

    # refresh_fn must NOT be called in the parent process.
    assert called == [], "refresh_fn must not run in the parent after fork"


@pytest.mark.unit
def test_spawn_detached_child_executes_refresh_fn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path (fork returns 0) executes refresh_fn then calls os._exit(0)."""
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("ran")

    # Simulate child path: fork returns 0.
    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", return_value=5),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
    ):
        spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")
        # child exits 0 on success
        mock_exit.assert_called_once_with(0)

    assert called == ["ran"], "refresh_fn must run in the child process"


@pytest.mark.unit
def test_spawn_detached_child_exits_1_on_refresh_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: if refresh_fn raises, child calls os._exit(1) (fail-fast)."""
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    def refresh_fn() -> None:
        raise RuntimeError("refresh broke")

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", return_value=5),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
    ):
        spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")
        mock_exit.assert_called_once_with(1)


@pytest.mark.unit
def test_spawn_detached_posix_child_records_error_to_log(
    tmp_path: Path,
) -> None:
    """Child path: a failing refresh_fn has its traceback RECORDED to log_path
    before the child exits non-zero.

    Regression guard for the no-silent-failure contract: the superseded
    fork_background_refresh child logged the exception via log_completion_error
    before os._exit(1); the extracted spawn helper must be behaviorally
    substitutable and never swallow a child failure without a record.
    """
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    log_path = tmp_path / "secured" / "errors.log"

    def refresh_fn() -> None:
        raise RuntimeError("refresh broke in detached child")

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", return_value=5),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
    ):
        spawn_detached(refresh_fn, log_path=log_path)
        mock_exit.assert_called_once_with(1)

    assert log_path.exists(), "the child must record its error to log_path, not swallow it"
    recorded = log_path.read_text()
    assert "RuntimeError" in recorded
    assert "refresh broke in detached child" in recorded
    assert (log_path.parent.stat().st_mode & 0o777) == 0o700, "log dir must be hardened to 0700"


@pytest.mark.unit
def test_spawn_detached_fork_failure_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If os.fork raises OSError, spawn_detached raises RuntimeError with an
    actionable message (fail-fast; no silent fallback).
    """
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    with patch("os.fork", side_effect=OSError("fork failed: out of memory")):
        with pytest.raises(RuntimeError, match="spawn_detached: failed to fork"):
            spawn_detached(_noop_refresh, log_path=tmp_path / "errors.log")


# ---------------------------------------------------------------------------
# Windows tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_spawn_detached_windows_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, spawn_detached uses subprocess.Popen with DETACHED_PROCESS
    and the parent returns immediately without calling refresh_fn.

    Uses the production-shaped callable (a functools.partial of a module-level
    function) so the pickle serialisation step exercises the real path.
    """
    if sys.platform != "win32":
        # Test the Windows path on non-Windows by patching sys.platform.
        monkeypatch.setattr(sys, "platform", "win32")

    mock_proc = MagicMock()
    mock_proc.pid = 1234

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        spawn_detached(_production_shaped_refresh(), log_path=tmp_path / "errors.log")
        mock_popen.assert_called_once()
        # Verify DETACHED_PROCESS flag (0x00000008) is set.
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("creationflags", 0) & 0x00000008, (
            "DETACHED_PROCESS flag must be set for Windows detached spawn"
        )


@pytest.mark.unit
def test_spawn_detached_windows_popen_failure_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, if Popen raises OSError, spawn_detached raises RuntimeError
    (fail-fast; no silent fallback).

    Uses the production-shaped callable (functools.partial of a module-level
    function) so the serialisation step succeeds and OSError from Popen is the
    first error encountered.
    """
    if sys.platform != "win32":
        monkeypatch.setattr(sys, "platform", "win32")

    with patch(
        "subprocess.Popen",
        side_effect=OSError("cannot spawn"),
    ):
        with pytest.raises(RuntimeError, match="spawn_detached: failed to spawn"):
            spawn_detached(_production_shaped_refresh(), log_path=tmp_path / "errors.log")


@pytest.mark.unit
def test_spawn_detached_windows_unpicklable_callable_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, an UNPICKLABLE callable (a nested closure) makes spawn_detached
    fail fast with a 'failed to serialise' RuntimeError -- it must NOT spawn.

    This is the negative counterpart to the picklability tests: it proves the
    Windows path genuinely depends on picklability, so a regression to a nested
    closure at the callsite would surface as a hard failure rather than silent
    breakage.
    """
    if sys.platform != "win32":
        monkeypatch.setattr(sys, "platform", "win32")

    captured: list[str] = []

    def _unpicklable_closure() -> None:
        # Defined inside the test function -> a nested closure -> not picklable.
        captured.append("never")

    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(RuntimeError, match="spawn_detached: failed to serialise"):
            spawn_detached(_unpicklable_closure, log_path=tmp_path / "errors.log")
        # Fail-fast before any process is launched.
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# Windows picklability -- real cache.py callsite
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fork_background_refresh_callable_is_picklable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callable that fork_background_refresh actually passes to
    spawn_detached must be picklable so the Windows path works end-to-end.

    A nested closure is NOT picklable; if cache.py wraps refresh_fn in a
    plain nested closure, pickle.dumps will raise and the Windows background
    refresh will always fail.

    This test captures the exact callable that spawn_detached receives from the
    real fork_background_refresh callsite and asserts that pickle.dumps
    succeeds on it.  The test FAILS if the production code passes an
    unpicklable nested closure.
    """
    import kanon_cli.completions.cache as cache_mod

    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    captured: list[object] = []

    def capturing_spawn(fn: object, *, log_path: object) -> None:
        captured.append(fn)

    monkeypatch.setattr(cache_mod, "spawn_detached", capturing_spawn)

    cache_mod.fork_background_refresh(_noop_refresh)

    assert len(captured) == 1, "fork_background_refresh must call spawn_detached once"
    passed_fn = captured[0]
    # This is the critical assertion: pickle.dumps must not raise.
    try:
        pickle.dumps(passed_fn)
    except Exception as exc:
        raise AssertionError(
            f"The callable passed to spawn_detached is not picklable "
            f"({type(exc).__name__}: {exc}). "
            f"The Windows detach path requires a picklable callable -- "
            f"refactor cache.py to pass a picklable entrypoint."
        ) from exc


@pytest.mark.unit
def test_fork_background_refresh_windows_path_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the Windows path, spawn_detached must not raise when called from
    fork_background_refresh.

    This test exercises the REAL callsite: fork_background_refresh calls
    spawn_detached with the actual production callable, then the Windows
    _spawn_detached_windows function calls pickle.dumps on it.  The test
    fails if that callable is an unpicklable closure.
    """
    if sys.platform != "win32":
        monkeypatch.setattr(sys, "platform", "win32")

    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    mock_proc = MagicMock()
    mock_proc.pid = 9999

    from kanon_cli.completions.cache import fork_background_refresh

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        # Must NOT raise -- if the callable is not picklable, spawn_detached
        # raises RuntimeError("spawn_detached: failed to serialise ...").
        fork_background_refresh(_noop_refresh)
        mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# POSIX log-directory hardening (0700)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_spawn_detached_posix_log_dir_mode_0700(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the POSIX path, the log directory must be created with mode 0700.

    A plain mkdir with no chmod leaves the directory world-readable (subject
    to the process umask), which is unacceptable for a directory that captures
    completion error output in a regulated-financial codebase.

    The test simulates the parent path (fork returns non-zero PID) so that the
    log directory creation code in spawn.py runs but the child code does not.
    """
    if sys.platform == "win32":
        pytest.skip("POSIX branch not applicable on Windows")

    log_dir = tmp_path / "spawn_log_dir"
    log_path = log_dir / "errors.log"

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", return_value=5),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit"),
    ):
        spawn_detached(_noop_refresh, log_path=log_path)

    assert log_dir.exists(), "log directory must be created by spawn_detached"
    actual_mode = os.stat(log_dir).st_mode & 0o777
    assert actual_mode == 0o700, (
        f"log directory must have mode 0700 (got {oct(actual_mode)}); "
        f"umask-reliant mkdir is insufficient for regulated-financial codebase"
    )
