"""Shared pytest fixtures wrapping synthetic-fixture helper modules.

Defines two function-scoped pytest fixtures that are auto-discovered by
pytest for any test under ``tests/integration/fixtures/synthetic/``:

- ``synthetic_drift_repo`` -- wraps ``create_drift_fixture`` from
  ``tests.integration.fixtures.synthetic.drift``.
- ``synthetic_upgrade_versioned_repo`` -- wraps
  ``create_upgrade_versioned_repo_fixture`` from
  ``tests.integration.fixtures.synthetic.upgrade_versioned``.

Both fixtures are function-scoped (the pytest default) so each consuming
test receives a fresh bare repo isolated under its own pytest ``tmp_path``
temporary directory.

These fixtures are the ergonomic entry points consumed by downstream
Epics E42 and E48. Tests that need the helper functions directly can still
import them; these fixtures are the recommended interface for scenario-
automation tests.

Spec reference: spec §4 E36 (amended 2026-05-27), §13 D6 (fixture-scope
decision).
"""

import pathlib

import pytest

from tests.integration.fixtures.synthetic.drift import create_drift_fixture
from tests.integration.fixtures.synthetic.upgrade_versioned import (
    create_upgrade_versioned_repo_fixture,
)


@pytest.fixture
def synthetic_drift_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Pytest fixture wrapping create_drift_fixture.

    Returns the absolute path to a freshly-materialised bare git repo
    whose manifest.xml declares <remote> + <default> before any <project>.
    Each test invocation receives a fresh bare repo isolated under its own
    pytest tmp_path temporary directory.

    Args:
        tmp_path: Pytest-provided per-test temporary directory.

    Returns:
        Absolute path to the bare git repository with a valid manifest.xml.
    """
    return create_drift_fixture(tmp_path)


@pytest.fixture
def synthetic_upgrade_versioned_repo(
    tmp_path: pathlib.Path,
) -> pathlib.Path:
    """Pytest fixture wrapping create_upgrade_versioned_repo_fixture.

    Returns the absolute path to a freshly-materialised bare git repo
    whose manifest.xml declares <remote> + <default> before any <project>
    and whose commit graph carries 3 PEP 440-valid annotated tags
    (0.1.0, 0.2.0, 1.0.0).
    Each test invocation receives a fresh bare repo isolated under its own
    pytest tmp_path temporary directory.

    Args:
        tmp_path: Pytest-provided per-test temporary directory.

    Returns:
        Absolute path to the bare git repository with a valid manifest.xml
        and annotated tags 0.1.0, 0.2.0, and 1.0.0.
    """
    return create_upgrade_versioned_repo_fixture(tmp_path)
