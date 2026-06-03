"""Unit-test-scoped fixtures for kanon-cli unit tests.

This conftest is loaded automatically by pytest for every test under
tests/unit/.  It provides fixtures that prevent network I/O in unit
tests that call doctor_command with a lockfile.

It also exports shared helper functions used by multiple test modules:

- ``_make_ls_remote_stub``: builds a callable stub that simulates
  ``git ls-remote --tags`` output for injecting into
  ``_check_tag_format`` in catalog audit tests.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Generator
from unittest.mock import patch

import pytest


def _make_ls_remote_stub(tags: list[str]) -> Callable[[pathlib.Path], str]:
    """Return a callable stub that produces ``git ls-remote --tags`` output.

    The stub mimics the output format of ``git ls-remote --tags <path>``:
    each line is ``<sha>\\trefs/tags/<tag-name>``.

    Shared by ``test_catalog_audit_tag_format.py`` and
    ``test_catalog_audit_project_tag_format.py`` to avoid duplicate helper
    definitions.

    Args:
        tags: List of tag name strings (without ``refs/tags/`` prefix).

    Returns:
        A callable accepting a ``target_path`` argument and returning the
        raw stdout string of the simulated ``git ls-remote --tags`` command.
    """

    def _stub(target_path: pathlib.Path) -> str:
        sha = "a" * 40  # deterministic placeholder SHA
        lines = [f"{sha}\trefs/tags/{tag}" for tag in tags]
        return "\n".join(lines) + ("\n" if lines else "")

    return _stub


@pytest.fixture(autouse=True)
def _stub_ls_remote_exit_code() -> Generator[None, None, None]:
    """Auto-patch _run_ls_remote_exit_code so unit tests never make real network calls.

    kanon doctor subcheck 11 calls _run_ls_remote_exit_code for every
    distinct canonicalized remote URL in the lockfile.  When a unit test
    builds a workspace with a real .kanon.lock, doctor_command would issue
    git ls-remote calls to whatever URLs are in the lockfile -- typically
    example.com placeholders that incur real DNS/TCP latency and occasional
    flakiness.

    This fixture short-circuits those calls for every unit test by replacing
    _run_ls_remote_exit_code with a stub that returns (0, '', ''), indicating
    that every remote is reachable.  Tests that need to exercise the
    reachability logic directly (tests/unit/test_doctor_remote_reachability.py)
    inject their own callable stub via the ls_remote_callable parameter and
    do not call _run_ls_remote_exit_code at all -- so this patch does not
    interfere with those tests.
    """
    with patch(
        "kanon_cli.commands.doctor._run_ls_remote_exit_code",
        return_value=(0, "", ""),
    ):
        yield
