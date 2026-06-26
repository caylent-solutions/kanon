"""Regression guard for the autouse home-isolation fixtures in tests/conftest.py.

Every test must run with an isolated ``CLAUDE_CONFIG_DIR`` and ``KANON_HOME`` so
it can never mutate the developer's real ``~/.claude`` or ``~/.kanon``. This
matters most for the marketplace lifecycle: a ``claude-marketplace`` install
shells out to the real ``claude`` binary (``core/marketplace.py``), which inherits
``os.environ`` and reads its config from ``CLAUDE_CONFIG_DIR``. Without the
isolation fixture a marketplace test would register marketplaces and plugins into
the real ``~/.claude`` pointing at the test's temporary marketplace directory;
once that temp directory is reaped the registrations dangle and surface as
``failed to load: cache-miss`` errors in Claude Code. These tests fail loudly if
either autouse isolation fixture is removed or stops pointing at a temp dir.
"""

from __future__ import annotations

import os
import pathlib

import pytest


@pytest.mark.unit
def test_claude_config_dir_is_isolated() -> None:
    """CLAUDE_CONFIG_DIR is set to a temp dir, never the real ~/.claude."""
    value = os.environ.get("CLAUDE_CONFIG_DIR")
    assert value, "CLAUDE_CONFIG_DIR must be set by the autouse _isolate_claude_config fixture"
    resolved = pathlib.Path(value).resolve()
    real = (pathlib.Path.home() / ".claude").resolve()
    assert resolved != real, f"CLAUDE_CONFIG_DIR must not be the real config dir {real}"


@pytest.mark.unit
def test_kanon_home_is_isolated() -> None:
    """KANON_HOME is set to a temp dir, never the real ~/.kanon."""
    value = os.environ.get("KANON_HOME")
    assert value, "KANON_HOME must be set by the autouse _isolate_kanon_home fixture"
    resolved = pathlib.Path(value).resolve()
    real = (pathlib.Path.home() / ".kanon").resolve()
    assert resolved != real, f"KANON_HOME must not be the real store dir {real}"
