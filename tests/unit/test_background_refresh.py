"""Unit tests for kanon_cli.completions.cache.fork_background_refresh.

Parametrized cases:
- KANON_COMPLETION_REFRESH_BG=0: returns without calling os.fork, no warning.
- KANON_COMPLETION_REFRESH_BG=<non-integer>: returns without forking AND emits
  a warning to stderr naming the invalid value.
- KANON_COMPLETION_REFRESH_BG=1 (or unset): os.fork called exactly once.
- Parent path (fork returns non-zero pid): returns immediately; no waitpid.
- Child path (fork returns 0): os.setsid called, refresh_fn invoked, exit 0.
- Child path exception: log_completion_error called, exit non-zero.

All cases set KANON_CACHE_DIR to tmp_path to avoid touching the real cache.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.completions.cache import fork_background_refresh


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _noop() -> None:
    """Refresh function that does nothing (used for parent-path tests)."""


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-TEST-001: env-var "0" (integer zero) -- disables silently
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refresh_bg_disabled_integer_zero_does_not_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=0 (integer zero): fork not called, no warning."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "0")

    fake_stderr = StringIO()
    with patch("os.fork") as mock_fork, patch.object(sys, "stderr", fake_stderr):
        fork_background_refresh(_noop)
        mock_fork.assert_not_called()

    assert fake_stderr.getvalue() == "", "KANON_COMPLETION_REFRESH_BG=0 must not emit any warning"


# ---------------------------------------------------------------------------
# AC-FUNC-001b / AC-TEST-001: non-integer env values -- disables AND warns
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("env_value", ["false", "no", "off", ""])
def test_refresh_bg_non_integer_does_not_fork_and_warns(
    env_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=<non-integer>: fork not called AND a warning
    identifying the invalid value and expected format is written to stderr."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", env_value)

    fake_stderr = StringIO()
    with patch("os.fork") as mock_fork, patch.object(sys, "stderr", fake_stderr):
        fork_background_refresh(_noop)
        mock_fork.assert_not_called()

    warning = fake_stderr.getvalue()
    assert warning, f"KANON_COMPLETION_REFRESH_BG={env_value!r}: expected a warning on stderr but got none"
    assert "KANON_COMPLETION_REFRESH_BG" in warning, f"Warning must name the env var; got: {warning!r}"
    assert repr(env_value) in warning or env_value in warning, (
        f"Warning must include the invalid value {env_value!r}; got: {warning!r}"
    )


@pytest.mark.unit
def test_refresh_bg_unset_defaults_to_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG unset: os.fork IS called (default 1)."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KANON_COMPLETION_REFRESH_BG", raising=False)

    # Simulate the parent path (fork returns non-zero pid) so we do not
    # actually fork. os.waitpid must NOT be called.
    with patch("os.fork", return_value=42) as mock_fork, patch("os.waitpid") as mock_waitpid:
        fork_background_refresh(_noop)
        mock_fork.assert_called_once()
        mock_waitpid.assert_not_called()


# ---------------------------------------------------------------------------
# AC-FUNC-002 / AC-TEST-001: env-var-on, os.fork called exactly once
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refresh_bg_enabled_calls_fork_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_COMPLETION_REFRESH_BG=1: os.fork called exactly once."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    with patch("os.fork", return_value=1234) as mock_fork:
        fork_background_refresh(_noop)
        assert mock_fork.call_count == 1


# ---------------------------------------------------------------------------
# AC-FUNC-003 / AC-TEST-001: parent-return-path (fork returns non-zero pid)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parent_path_returns_immediately_no_waitpid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent path (fork returns non-zero): returns immediately, no waitpid."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    called: list[str] = []

    def refresh_fn() -> None:
        called.append("refresh")

    with patch("os.fork", return_value=9999), patch("os.waitpid") as mock_waitpid:
        fork_background_refresh(refresh_fn)
        mock_waitpid.assert_not_called()
        # The parent must NOT call refresh_fn
        assert called == []


# ---------------------------------------------------------------------------
# AC-FUNC-004 / AC-TEST-001: child-exec-path (fork returns 0)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_child_path_calls_setsid_and_refresh_fn_then_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path (fork returns 0): setsid called, refresh_fn invoked, exits 0."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    call_log: list[str] = []

    def refresh_fn() -> None:
        call_log.append("refresh")

    mock_devnull_fd = 5

    def fake_open(path: str, flags: int, mode: int = 0) -> int:
        return mock_devnull_fd

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid") as mock_setsid,
        patch("os.open", side_effect=fake_open),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
    ):
        fork_background_refresh(refresh_fn)
        mock_setsid.assert_called_once()
        assert "refresh" in call_log
        mock_exit.assert_called_once_with(0)


@pytest.mark.unit
def test_child_path_redirects_stdin_stdout_to_devnull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: stdin (fd 0) and stdout (fd 1) are redirected to /dev/null."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    dup2_calls: list[tuple[int, int]] = []

    def capture_dup2(fd1: int, fd2: int) -> None:
        dup2_calls.append((fd1, fd2))

    devnull_fd = 77

    def fake_open(path: str, flags: int, mode: int = 0) -> int:
        return devnull_fd

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", side_effect=fake_open),
        patch("os.dup2", side_effect=capture_dup2),
        patch("os.close"),
        patch("os._exit"),
    ):
        fork_background_refresh(_noop)

    # stdin=0 and stdout=1 must be redirected to /dev/null (devnull_fd)
    redirected_fds = {dst for _src, dst in dup2_calls if _src == devnull_fd}
    assert 0 in redirected_fds, "stdin (fd 0) must be redirected to /dev/null"
    assert 1 in redirected_fds, "stdout (fd 1) must be redirected to /dev/null"


# ---------------------------------------------------------------------------
# AC-FUNC-005 / AC-TEST-001: child-exception-path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_child_exception_logs_and_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: if refresh_fn raises, log_completion_error is called, exit non-zero."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    class RefreshError(RuntimeError):
        pass

    def bad_refresh() -> None:
        raise RefreshError("simulated refresh failure")

    devnull_fd = 42

    def fake_open(path: str, flags: int, mode: int = 0) -> int:
        return devnull_fd

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", side_effect=fake_open),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit") as mock_exit,
        patch("kanon_cli.completions.cache.log_completion_error") as mock_log,
    ):
        fork_background_refresh(bad_refresh)
        # log_completion_error must be called with the raised exception
        assert mock_log.call_count == 1
        logged_exc = mock_log.call_args[0][1]
        assert isinstance(logged_exc, RefreshError)
        # exit must be called with a non-zero code
        assert mock_exit.call_count == 1
        exit_code = mock_exit.call_args[0][0]
        assert exit_code != 0


# ---------------------------------------------------------------------------
# AC-FUNC-006 / AC-TEST-001: child must NOT write to parent's stdout (fd 1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_child_stdout_redirected_before_refresh_fn_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: stdout (fd 1) is redirected to /dev/null BEFORE refresh_fn is called."""
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")

    event_log: list[str] = []

    def capture_dup2(fd1: int, fd2: int) -> None:
        event_log.append(f"dup2({fd1},{fd2})")

    def refresh_fn() -> None:
        event_log.append("refresh")

    devnull_fd = 55

    def fake_open(path: str, flags: int, mode: int = 0) -> int:
        return devnull_fd

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", side_effect=fake_open),
        patch("os.dup2", side_effect=capture_dup2),
        patch("os.close"),
        patch("os._exit"),
    ):
        fork_background_refresh(refresh_fn)

    # Find the index of stdout redirect and refresh call in event_log
    stdout_redirect_index: int | None = None
    refresh_index: int | None = None
    for idx, ev in enumerate(event_log):
        if ev == f"dup2({devnull_fd},1)":
            stdout_redirect_index = idx
        if ev == "refresh":
            refresh_index = idx

    assert stdout_redirect_index is not None, "stdout (fd 1) was never redirected to /dev/null"
    assert refresh_index is not None, "refresh_fn was never called"
    assert stdout_redirect_index < refresh_index, "stdout must be redirected BEFORE refresh_fn is called"


# ---------------------------------------------------------------------------
# Coverage: KANON_COMPLETION_LOG env var path in child
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_child_uses_kanon_completion_log_env_for_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child path: KANON_COMPLETION_LOG env var is used for stderr redirection."""
    custom_log = str(tmp_path / "custom-errors.log")
    monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KANON_COMPLETION_REFRESH_BG", "1")
    monkeypatch.setenv("KANON_COMPLETION_LOG", custom_log)

    opened_paths: list[str] = []

    def fake_open(path: str, flags: int, mode: int = 0) -> int:
        opened_paths.append(path)
        return 99

    with (
        patch("os.fork", return_value=0),
        patch("os.setsid"),
        patch("os.open", side_effect=fake_open),
        patch("os.dup2"),
        patch("os.close"),
        patch("os._exit"),
    ):
        fork_background_refresh(_noop)

    # The custom log path must appear in the opened paths.
    assert custom_log in opened_paths, (
        f"Expected KANON_COMPLETION_LOG path {custom_log!r} to be opened; got {opened_paths!r}"
    )
