"""Worker serialization and real fresh-interpreter execution contracts."""

import functools
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.completions.cache import _run_refresh_with_logging
from kanon_cli.core.update_check import _refresh_cache
from kanon_cli.utils.spawn import _spawn_detached_windows, _windows_append_fd
from kanon_cli.utils.worker import decode, encode


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, True, 2, 1.5, "café", b"\x00\xff", Path("a b"), [1, "x"], {"a": 3}])
def test_worker_round_trip(value):
    assert decode(json.loads(json.dumps(encode(value)))) == value


@pytest.mark.unit
def test_nested_refresh_partial_round_trip():
    callback = functools.partial(_run_refresh_with_logging, _refresh_cache, "update")
    restored = decode(json.loads(json.dumps(encode(callback))))
    assert restored.func is _run_refresh_with_logging
    assert restored.args == callback.args


@pytest.mark.unit
def test_unimportable_callback_fails_before_start(tmp_path):
    with pytest.raises(RuntimeError, match="module-level"):
        _spawn_detached_windows(lambda: None, log_path=tmp_path / "errors")
    assert not (tmp_path / "errors").exists()


@pytest.mark.unit
def test_log_setup_failure_is_synchronous(tmp_path):
    (tmp_path / "file").write_text("occupied", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed to spawn"):
        _spawn_detached_windows(_refresh_cache, log_path=tmp_path / "file" / "bad")


@pytest.mark.unit
def test_worker_exception_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "kanon_cli.utils.worker"],
        input=json.dumps(["invalid"]).encode(),
        capture_output=True,
        timeout=float(os.environ.get("KANON_TEST_SUBPROCESS_TIMEOUT", "300")),
    )
    assert result.returncode != 0
    assert b"Unknown worker argument type" in result.stderr


@pytest.mark.unit
def test_windows_launch_flags_and_log_directory(tmp_path):
    with (
        patch.object(subprocess, "DETACHED_PROCESS", 8, create=True),
        patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
        patch.object(subprocess, "Popen") as launch,
        patch("kanon_cli.utils.spawn._windows_append_fd", side_effect=os.open),
    ):
        log = tmp_path / "nested" / "errors.log"
        child = _spawn_detached_windows(_refresh_cache, log_path=log)
    assert log.exists()
    assert launch.call_args.kwargs["creationflags"] == 520
    assert launch.call_args.args[0] == [sys.executable, "-I", "-X", "utf8", "-m", "kanon_cli.utils.worker"]
    assert launch.call_args.kwargs["stdout"] == subprocess.DEVNULL
    child.stdin.write.assert_called_once()
    child.stdin.close.assert_called_once()
    child.wait.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("outcome", ["success", "open_error", "descriptor_error"])
def test_append_handle_ownership(monkeypatch, outcome):
    kernel = MagicMock()
    crt = MagicMock()
    kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value if outcome == "open_error" else 100
    crt.open_osfhandle.return_value = 101
    if outcome == "descriptor_error":
        crt.open_osfhandle.side_effect = OSError("descriptor failure")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "open failure"), raising=False)
    monkeypatch.setattr(os, "O_BINARY", 0x8000, raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", crt)
    if outcome == "success":
        assert _windows_append_fd("worker.log", os.O_WRONLY) == 101
        kernel.CloseHandle.assert_not_called()
    else:
        with pytest.raises(OSError):
            _windows_append_fd("worker.log", os.O_WRONLY)
        if outcome == "descriptor_error":
            kernel.CloseHandle.assert_called_once_with(100)
        else:
            kernel.CloseHandle.assert_not_called()
    assert kernel.CreateFileW.call_args.args[1] == 4


@pytest.mark.unit
def test_worker_launch_ignores_untrusted_imports(tmp_path, monkeypatch):
    package = tmp_path / "kanon_cli"
    package.mkdir()
    poison = "raise RuntimeError('untrusted-workspace-module')\n"
    (package / "__init__.py").write_text(poison, encoding="utf-8")
    (tmp_path / "sitecustomize.py").write_text(poison, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with (
        patch.object(subprocess, "DETACHED_PROCESS", 8, create=True),
        patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
        patch.object(subprocess, "Popen") as launch,
        patch("kanon_cli.utils.spawn._windows_append_fd", side_effect=os.open),
    ):
        _spawn_detached_windows(_refresh_cache, log_path=tmp_path / "log")
    result = subprocess.run(
        launch.call_args.args[0],
        input=json.dumps(["invalid"]).encode(),
        capture_output=True,
        timeout=float(os.environ.get("KANON_TEST_SUBPROCESS_TIMEOUT", "300")),
    )
    assert result.returncode != 0
    assert b"Unknown worker argument type" in result.stderr
    assert b"untrusted-workspace-module" not in result.stderr
