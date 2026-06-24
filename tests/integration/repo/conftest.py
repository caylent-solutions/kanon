"""Integration-test conftest for the embedded repo-tool suite.

Applies @pytest.mark.linux_only to every test collected under
tests/integration/repo/. The embedded Google "repo" tool
(src/kanon_cli/repo/**) is a POSIX-oriented subsystem: it shells out to git,
relies on fork-based process isolation, POSIX signal handling, and symlink
semantics that have no Windows equivalent in the kanon embedding. kanon shells
out to it; making the vendored internals Windows-clean is out of scope for the
cross-platform CI effort, which targets kanon's own primitives (kanonenv ACL,
workspace lock, spawn). Marking the whole repo-tool suite linux_only deselects
it on the Windows CI leg while it still runs in full on the Linux leg. The
marker is applied here (one place) rather than with 29 per-file decorators
(DRY). The integration marker is already present on every test in this tree.
"""

from __future__ import annotations

import pathlib

import pytest


def pytest_collection_modifyitems(config, items):
    """Apply @pytest.mark.linux_only to every item under tests/integration/repo/."""
    this_dir = pathlib.Path(__file__).resolve().parent
    for item in items:
        try:
            item_path = pathlib.Path(str(item.fspath)).resolve()
        except (AttributeError, OSError):
            continue
        try:
            item_path.relative_to(this_dir)
        except ValueError:
            continue
        item.add_marker(pytest.mark.linux_only)
