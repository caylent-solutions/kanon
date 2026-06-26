"""Unit tests for kanon_cli.completions.cache.fork_background_refresh.

After E2-F1-S2-T1, fork_background_refresh no longer drives os.fork / setsid /
dup2 directly: it delegates the detached-spawn mechanics to
kanon_cli.utils.spawn.spawn_detached. These tests therefore patch
spawn_detached (the seam fork_background_refresh now depends on) rather than
os.fork. The child-execution behaviour (setsid, /dev/null redirection,
os._exit on success/failure) is exercised against spawn_detached itself in
tests/unit/test_spawn.py and is intentionally NOT duplicated here.

Cases covered:
- KANON_COMPLETION_REFRESH_BG=0 (integer zero): spawn_detached NOT called, no
  warning emitted.
- KANON_COMPLETION_REFRESH_BG=<non-integer>: spawn_detached NOT called AND a
  warning naming the invalid value is written to stderr (fail-loud, no spawn).
- KANON_COMPLETION_REFRESH_BG=1: spawn_detached called exactly once.
- KANON_COMPLETION_REFRESH_BG unset: defaults to enabled (spawn_detached called).
- Parent does not block: fork_background_refresh returns after spawn_detached
  without invoking refresh_fn in-process.
- Spawn-failure propagation: when spawn_detached raises RuntimeError,
  fork_background_refresh propagates it (fail-fast, no silent fallback).
- The callable handed to spawn_detached is a picklable functools.partial
  wrapping the module-level _run_refresh_with_logging (required for the Windows
  spawn path).
- KANON_COMPLETION_LOG selects the log path forwarded to spawn_detached.

All cases set KANON_HOME to tmp_path so the real cache is never touched.
"""

from __future__ import annotations

import functools
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.completions.cache import _run_refresh_with_logging, fork_background_refresh


def _noop() -> None:
    """Refresh function that does nothing (used for parent-path tests)."""


@pytest.mark.unit
def test_refresh_bg_disabled_integer_zero_does_not_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=0 (integer zero): spawn_detached not called, no warning."""
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")

    fake_stderr = StringIO()
    with (
        patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn,
        patch.object(sys, "stderr", fake_stderr),
    ):
        fork_background_refresh(_noop)
        mock_spawn.assert_not_called()

    assert fake_stderr.getvalue() == "", "KANON_COMPLETION_REFRESH_BG=0 must not emit any warning"


@pytest.mark.unit
@pytest.mark.parametrize("env_value", ["false", "no", "off", ""])
def test_refresh_bg_non_integer_does_not_spawn_and_warns(
    env_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=<non-integer>: spawn_detached not called AND a
    warning identifying the invalid value and expected format is written to stderr."""
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", env_value)

    fake_stderr = StringIO()
    with (
        patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn,
        patch.object(sys, "stderr", fake_stderr),
    ):
        fork_background_refresh(_noop)
        mock_spawn.assert_not_called()

    warning = fake_stderr.getvalue()
    assert warning, f"KANON_COMPLETION_REFRESH_BG={env_value!r}: expected a warning on stderr but got none"
    assert "KANON_COMPLETION_REFRESH_BG" in warning, f"Warning must name the env var; got: {warning!r}"
    assert repr(env_value) in warning or env_value in warning, (
        f"Warning must include the invalid value {env_value!r}; got: {warning!r}"
    )


@pytest.mark.unit
def test_refresh_bg_enabled_calls_spawn_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=1: spawn_detached called exactly once."""
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    with patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn:
        fork_background_refresh(_noop)
        assert mock_spawn.call_count == 1


@pytest.mark.unit
def test_refresh_bg_unset_defaults_to_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG unset: spawn_detached IS called (default 1)."""
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    with patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn:
        fork_background_refresh(_noop)
        mock_spawn.assert_called_once()


@pytest.mark.unit
def test_parent_returns_without_running_refresh_fn_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fork_background_refresh delegates to spawn_detached and returns without
    invoking refresh_fn in the calling (parent) process.

    spawn_detached is responsible for running refresh_fn in the detached child;
    the parent must never execute it itself.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("refresh")

    with patch("kanon_cli.completions.cache.spawn_detached") as mock_spawn:
        fork_background_refresh(refresh_fn)
        mock_spawn.assert_called_once()

    assert called == [], "refresh_fn must not run in the parent process"


@pytest.mark.unit
def test_spawn_detached_receives_picklable_partial_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callable fork_background_refresh passes to spawn_detached is a
    functools.partial of the module-level _run_refresh_with_logging, NOT a
    nested closure.

    A functools.partial of a module-level function is picklable, which the
    Windows spawn path requires. A nested closure would be unpicklable.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    captured: list[object] = []

    def capturing_spawn(fn: object, *, log_path: object) -> None:
        captured.append(fn)

    with patch("kanon_cli.completions.cache.spawn_detached", side_effect=capturing_spawn):
        fork_background_refresh(_noop)

    assert len(captured) == 1
    passed = captured[0]
    assert isinstance(passed, functools.partial), "wrapper must be a functools.partial (picklable)"
    assert passed.func is _run_refresh_with_logging, "wrapper must bind the module-level logging helper"
    assert passed.args[0] is _noop, "wrapper must bind the caller's refresh_fn"


@pytest.mark.unit
def test_spawn_failure_propagates_runtimeerror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When spawn_detached raises RuntimeError, fork_background_refresh
    propagates it unchanged (fail-fast, no silent fallback).
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    with patch(
        "kanon_cli.completions.cache.spawn_detached",
        side_effect=RuntimeError("spawn_detached: failed to fork background refresh child"),
    ):
        with pytest.raises(RuntimeError, match="failed to fork background refresh child"):
            fork_background_refresh(_noop)


@pytest.mark.unit
def test_kanon_completion_log_env_selects_spawn_log_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_LOG, when set, is forwarded to spawn_detached as log_path."""
    custom_log = tmp_path / "custom-errors.log"
    monkeypatch.setenv("KANON_HOME", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")
    monkeypatch.setenv("KANON_COMPLETION_LOG", str(custom_log))

    captured_log_paths: list[object] = []

    def capturing_spawn(fn: object, *, log_path: object) -> None:
        captured_log_paths.append(log_path)

    with patch("kanon_cli.completions.cache.spawn_detached", side_effect=capturing_spawn):
        fork_background_refresh(_noop)

    assert captured_log_paths == [Path(str(custom_log))], (
        f"Expected log_path {custom_log!r} forwarded to spawn_detached; got {captured_log_paths!r}"
    )
