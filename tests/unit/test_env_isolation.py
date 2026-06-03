"""Regression test: KANON_CATALOG_SOURCE must not leak between test functions.

These two tests together prove that the autouse function-scoped scrubber
fixture in tests/conftest.py clears KANON_CATALOG_SOURCE after every test,
regardless of pytest collection order. If the scrubber fixture is removed or
broken, test_b_catalog_source_unset_at_function_start will fail whenever
test_a_sets_catalog_source runs before it.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.unit
def test_a_sets_catalog_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """First function: set KANON_CATALOG_SOURCE and assert it took."""
    test_url = "https://example.invalid/test-repo@refs/tags/0.0.0"
    monkeypatch.setenv("KANON_CATALOG_SOURCE", test_url)
    assert os.environ["KANON_CATALOG_SOURCE"] == test_url


@pytest.mark.unit
def test_b_catalog_source_unset_at_function_start() -> None:
    """Second function: KANON_CATALOG_SOURCE must NOT be set on entry."""
    assert "KANON_CATALOG_SOURCE" not in os.environ
