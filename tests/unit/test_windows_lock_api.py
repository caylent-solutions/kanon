"""Win32 error-path contracts, complemented by native cross-process tests."""

import ctypes
from unittest.mock import MagicMock

import pytest

from kanon_cli.utils.concurrency import WorkspaceLockTimeoutError, _exclusive_kernel_lock_windows


@pytest.mark.unit
@pytest.mark.parametrize(
    "outcome",
    [
        "immediate",
        "pending",
        "timeout",
        "lock_error",
        "wait_error",
        "completion_error",
        "event_error",
        "open_error",
        "unlock_error",
    ],
)
def test_windows_lock_lifecycle(monkeypatch, tmp_path, outcome):
    kernel = MagicMock()
    kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value if outcome == "open_error" else 100
    kernel.CreateEventW.return_value = 0 if outcome == "event_error" else 200
    kernel.LockFileEx.return_value = outcome in ("immediate", "unlock_error")
    kernel.WaitForSingleObject.return_value = {"timeout": 258, "wait_error": 0xFFFFFFFF}.get(outcome, 0)
    kernel.GetOverlappedResult.return_value = outcome != "completion_error"
    kernel.UnlockFileEx.return_value = outcome != "unlock_error"
    error = 5 if outcome in ("lock_error", "open_error", "event_error", "unlock_error", "wait_error") else 997
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "win32 error"), raising=False)
    path = tmp_path / "lock"
    expected = WorkspaceLockTimeoutError if outcome == "timeout" else OSError
    if outcome in ("immediate", "pending"):
        with _exclusive_kernel_lock_windows(None, tmp_path, path, 1):
            kernel.CloseHandle.assert_not_called()
        kernel.UnlockFileEx.assert_called_once()
    else:
        with pytest.raises(expected):
            with _exclusive_kernel_lock_windows(None, tmp_path, path, 1):
                pass
    if outcome == "timeout":
        kernel.CancelIoEx.assert_called_once()
        assert kernel.GetOverlappedResult.call_args.args[-1] is True
    if outcome != "open_error":
        assert any(call.args == (100,) for call in kernel.CloseHandle.call_args_list)
