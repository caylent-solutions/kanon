"""Fresh-interpreter worker protocol for detached Windows refreshes.

Only importable functions, partials, paths, bytes and JSON values are encoded.
The parent sends the payload through an inherited pipe, never a writable job
file or command-line argument. No pickle or executable source is deserialized.
"""

from __future__ import annotations

import base64
import functools
import importlib
import json
import sys
from pathlib import Path
from types import FunctionType


def encode(value):
    """Describe a refresh callable and its arguments using tagged JSON data."""
    if isinstance(value, functools.partial):
        return ["partial", encode(value.func), encode(list(value.args)), encode(value.keywords)]
    if isinstance(value, FunctionType):
        if value.__module__ == "__main__" or "<locals>" in value.__qualname__:
            raise ValueError("Detached Windows callbacks must be importable module-level functions")
        if getattr(importlib.import_module(value.__module__), value.__name__) is not value:
            raise ValueError("Detached Windows callback does not resolve to the same function")
        return ["function", value.__module__, value.__name__]
    if isinstance(value, Path):
        return ["path", str(value)]
    if isinstance(value, bytes):
        return ["bytes", base64.b64encode(value).decode("ascii")]
    if isinstance(value, (list, tuple)):
        return ["sequence", [encode(item) for item in value]]
    if isinstance(value, dict):
        return ["mapping", {key: encode(item) for key, item in value.items()}]
    if value is None or isinstance(value, (str, int, float, bool)):
        return ["value", value]
    raise TypeError(f"Unsupported detached worker argument: {type(value).__name__}")


def decode(value):
    """Reconstruct the callable using the parent's pipe-delivered description."""
    kind, *items = value
    if kind == "partial":
        return functools.partial(decode(items[0]), *decode(items[1]), **decode(items[2]))
    if kind == "function":
        return getattr(importlib.import_module(items[0]), items[1])
    if kind == "path":
        return Path(items[0])
    if kind == "bytes":
        return base64.b64decode(items[0], validate=True)
    if kind == "sequence":
        return [decode(item) for item in items[0]]
    if kind == "mapping":
        return {key: decode(item) for key, item in items[0].items()}
    if kind == "value":
        return items[0]
    raise ValueError(f"Unknown worker argument type: {kind}")


def main() -> None:
    """Execute a job; uncaught failures reach the log and exit nonzero."""
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdin.close()
    decode(payload)()


if __name__ == "__main__":
    main()
