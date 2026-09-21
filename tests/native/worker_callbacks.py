"""Importable callbacks used by native child-process contract tests."""

import os
from pathlib import Path
import socket
import sys


def wait_for_release(port, timeout):
    """Prove the worker outlives its parent using a controller-owned socket."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as channel:
        channel.sendall(b"ready")
        assert channel.recv(1) == b"!"
        channel.sendall(b"done")


def output():
    print("hidden-stdout", flush=True)
    os.write(1, b"hidden-fd-stdout\n")
    print("visible-stderr-caf\u00e9", file=sys.stderr, flush=True)


def fail():
    raise ValueError("native-worker-controlled-failure")


def released_output(port, timeout, message):
    """Keep two worker logs open before allowing either process to write."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as channel:
        channel.sendall(b"R")
        assert channel.recv(1) == b"!"
        print(message, file=sys.stderr, flush=True)
        channel.sendall(b"D")


def marker(path):
    Path(path).write_text("completed", encoding="utf-8")


def refresh_update_fixture():
    """Run the actual update writer with only its remote version response stubbed."""
    from unittest.mock import patch
    from kanon_cli.core.update_check import _refresh_cache

    with patch("kanon_cli.core.update_check.fetch_latest_version", return_value="9.8.7"):
        _refresh_cache()
