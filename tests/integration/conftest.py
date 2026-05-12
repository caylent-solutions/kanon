"""Integration-test conftest: autouse fixtures for install engine mocks.

These fixtures patch ``_resolve_ref_to_sha`` and ``_check_sha_reachable`` so
that integration tests using synthetic (non-network) git URLs do not fail
with ``git ls-remote`` errors.  Individual test modules that need the real
implementations can override these fixtures locally (see
``test_install_lockfile_replay.py`` for an example).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kanon_cli.core.install import _RefResolution

# Deterministic dummy values returned by the autouse mocks.
_MOCK_RESOLVED_SHA = "a" * 40
_MOCK_RESOLVED_REF = "refs/heads/main"


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Patch ``_resolve_ref_to_sha`` to avoid real ``git ls-remote`` calls."""
    with patch(
        "kanon_cli.core.install._resolve_ref_to_sha",
        return_value=_RefResolution(sha=_MOCK_RESOLVED_SHA, resolved_ref=_MOCK_RESOLVED_REF),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Patch ``_check_sha_reachable`` to avoid real ``git ls-remote`` calls."""
    with patch("kanon_cli.core.install._check_sha_reachable"):
        yield
