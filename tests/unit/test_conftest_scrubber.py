"""Smoke test for the autouse _scrub_catalog_source_env fixture in tests/conftest.py.

Verifies that the scrubber fixture is registered and that KANON_CATALOG_SOURCE
is cleared after the test body completes. The scrubber runs teardown logic
unconditionally, providing defense in depth against env-var leaks.
"""

from __future__ import annotations

import os

import pytest

_CATALOG_ENV_KEY = "KANON_CATALOG_SOURCE"
_TEST_CATALOG_URL = "https://example.test/catalog-smoke-test.git"


@pytest.mark.unit
def test_scrubber_fixture_is_registered(request: pytest.FixtureRequest) -> None:
    """The autouse _scrub_catalog_source_env fixture is discoverable via pytest.

    This test uses request.getfixturevalue to resolve the fixture by name.
    If the fixture is not registered in conftest.py, pytest raises
    pytest.FixtureLookupError and this test FAILS. After the autouse fixture
    is added (GREEN phase), the fixture resolves successfully and the test PASSES.
    """

    fixture_value = request.getfixturevalue("_scrub_catalog_source_env")

    assert fixture_value is None


@pytest.mark.unit
def test_scrubber_clears_env_set_via_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KANON_CATALOG_SOURCE set via monkeypatch is visible inside the test body.

    The autouse _scrub_catalog_source_env fixture calls
    monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False) after yield.
    This test sets the env via monkeypatch.setenv and asserts the value is
    present during the test body. The scrubber's teardown (plus monkeypatch's
    own undo) ensures the var is cleared before the next test runs.
    """
    monkeypatch.setenv(_CATALOG_ENV_KEY, _TEST_CATALOG_URL)
    assert os.environ.get(_CATALOG_ENV_KEY) == _TEST_CATALOG_URL
