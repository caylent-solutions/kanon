"""Unit tests for kanon_cli.utils.spawn.spawn_detached.

TDD-paired test file covering:
- spawn_detached success: child runs the target callable and parent returns
  immediately (no blocking wait).
- spawn_detached failure: a spawn error fails fast by raising RuntimeError
  with an actionable message (no silent fallback).
- POSIX directory hardening: the log directory is created with mode 0700.

No os.fork is used in the test itself -- tests exercise the public interface
via mocking so the suite runs without spawning a real child process.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.utils.spawn import spawn_detached


def _noop_refresh() -> None:
    """No-op module-level refresh callable used where the body is irrelevant."""


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
    called: list[str] = []

    def refresh_fn() -> None:
        called.append("child_called")

    with patch("os.fork", return_value=42) as mock_fork:
        spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")
        mock_fork.assert_called_once()

    assert called == [], "refresh_fn must not run in the parent after fork"


@pytest.mark.unit
def test_spawn_detached_child_executes_refresh_fn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path (fork returns 0) executes refresh_fn then calls os._exit(0)."""
    called: list[str] = []

    def refresh_fn() -> None:
        called.append("ran")

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", return_value=5),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
    ):
        spawn_detached(refresh_fn, log_path=tmp_path / "errors.log")

        mock_exit.assert_called_once_with(0)

    assert called == ["ran"], "refresh_fn must run in the child process"


@pytest.mark.unit
def test_spawn_detached_child_exits_1_on_refresh_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: if refresh_fn raises, child calls os._exit(1) (fail-fast)."""

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
    with patch("os.fork", side_effect=OSError("fork failed: out of memory")):
        with pytest.raises(RuntimeError, match="spawn_detached: failed to fork"):
            spawn_detached(_noop_refresh, log_path=tmp_path / "errors.log")


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
