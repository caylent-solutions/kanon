"""Integration-test conftest: autouse fixtures for install engine mocks.

These fixtures patch ``_resolve_ref_to_sha`` and ``_check_sha_reachable`` so
that integration tests using synthetic (non-network) git URLs do not fail
with ``git ls-remote`` errors.  Individual test modules that need the real
implementations can override these fixtures locally (see
``test_install_lockfile_replay.py`` for an example).

The ``_auto_create_manifest_on_walk`` fixture transparently creates a minimal
manifest XML at the expected path whenever ``_walk_includes`` is called and the
target file does not yet exist.  This is needed because tests that mock
``repo_init`` to a no-op or a call-recording side-effect never invoke the real
``repo init`` command, so the ``.repo/manifests/`` tree is never populated.
Without this fixture those tests would fail with ``FileNotFoundError`` inside
the XML include-walker.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import _walk_includes as _real_walk_includes
from kanon_cli.core.install import _RefResolution

# Deterministic dummy values returned by the autouse mocks.
_MOCK_RESOLVED_SHA = "a" * 40
_MOCK_RESOLVED_REF = "refs/heads/main"

_MINIMAL_MANIFEST_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest></manifest>\n"
)


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


@pytest.fixture(autouse=True)
def _auto_create_manifest_on_walk():
    """Auto-create a minimal manifest XML when the target file is missing.

    Tests that mock ``repo_init`` to a recording no-op never run the real
    ``repo init`` command, so ``.repo/manifests/<path>`` is never populated.
    This fixture wraps ``_walk_includes`` to create a minimal well-formed XML
    manifest at the expected path if it does not yet exist before delegating to
    the real parser.

    Tests that already create the manifest themselves (via ``fake_repo_init``
    or ``write_manifest_for_sync``) are unaffected -- the fixture only writes
    the file when it is absent.
    """

    def _walk_includes_with_auto_create(
        start_xml_path: pathlib.Path,
        manifest_repo: pathlib.Path,
    ) -> object:
        if not start_xml_path.exists():
            start_xml_path.parent.mkdir(parents=True, exist_ok=True)
            start_xml_path.write_text(_MINIMAL_MANIFEST_XML)
        return _real_walk_includes(start_xml_path, manifest_repo)

    with patch(
        "kanon_cli.core.install._walk_includes",
        side_effect=_walk_includes_with_auto_create,
    ):
        yield
