"""Worker serialization and real fresh-interpreter execution contracts."""

import functools
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from kanon_cli.completions.cache import _run_refresh_with_logging
from kanon_cli.core.update_check import _refresh_cache
from kanon_cli.utils.spawn import _spawn_detached_windows
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
    ):
        log = tmp_path / "nested" / "errors.log"
        child = _spawn_detached_windows(_refresh_cache, log_path=log)
    assert log.exists()
    assert launch.call_args.kwargs["creationflags"] == 520
    assert launch.call_args.kwargs["stdout"] == subprocess.DEVNULL
    child.stdin.write.assert_called_once()
    child.stdin.close.assert_called_once()
    child.wait.assert_not_called()
