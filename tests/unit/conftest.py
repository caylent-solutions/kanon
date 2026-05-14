"""Unit-test-scoped fixtures for kanon-cli unit tests.

This conftest is loaded automatically by pytest for every test under
tests/unit/.  It provides fixtures that prevent network I/O in unit
tests that call doctor_command with a lockfile.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest


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
