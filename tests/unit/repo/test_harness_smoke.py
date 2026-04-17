"""Smoke tests for the git-repo test harness.

Exercises all conftest.py fixtures to verify the test harness
is fully operational. Also validates that make targets work correctly.

These tests are excluded from ``make test`` via the ``addopts`` setting
in ``pyproject.toml`` because they invoke make targets as subprocesses.
They run only via ``make test-functional`` which selects them by the
``functional`` marker.

Spec Reference: Plan: Per-Repo Tooling — Test harness verification.
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


@pytest.mark.unit
def test_smoke_all_fixtures_available(mock_manifest_xml, mock_project_config):
    """Verify all conftest.py fixtures are available and return expected types.

    Given: conftest.py defines mock_manifest_xml and mock_project_config
    When: A test requests both fixtures
    Then: mock_manifest_xml returns a valid file path, mock_project_config
          returns a dict
    Spec: Plan: Test harness
    """
    # mock_manifest_xml should return a path to an existing XML file
    assert os.path.isfile(mock_manifest_xml), (
        f"mock_manifest_xml must return an existing file path: {mock_manifest_xml}"
    )
    tree = ET.parse(mock_manifest_xml)
    assert tree.getroot().tag == "manifest", "mock_manifest_xml file must contain a <manifest> root element"

    # mock_project_config should return a dict with standard keys
    assert isinstance(mock_project_config, dict), (
        f"mock_project_config must return a dict, got {type(mock_project_config)}"
    )
    for key in ("name", "path", "remote", "revision"):
        assert key in mock_project_config, f"mock_project_config must contain '{key}' key"


@pytest.mark.functional
def test_make_validate_passes(repo_root, subprocess_timeout):
    """Verify make validate exits 0 (full CI pipeline).

    Given: All tooling (linters, formatters, test harness) is configured
    When: make validate is run
    Then: Exit code is 0
    Spec: Plan: Full pipeline
    """
    result = subprocess.run(
        ["make", "validate"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=subprocess_timeout,
    )
    assert result.returncode == 0, (
        f"make validate failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout[-500:]}\n"
        f"stderr: {result.stderr[-500:]}"
    )


@pytest.mark.functional
def test_make_clean_removes_artifacts(repo_root, subprocess_timeout):
    """Verify make clean removes build/cache artifacts.

    Given: Cache artifacts may exist from test runs
    When: make clean is run
    Then: __pycache__, .pytest_cache, .ruff_cache, .coverage are removed
    Spec: Plan: Clean target
    """
    # Run a few unit tests to create cache artifacts
    setup_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "unit", "-q", "--tb=short"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=subprocess_timeout,
    )
    assert setup_result.returncode == 0, (
        f"Setup step failed: pytest exited {setup_result.returncode}.\nstderr: {setup_result.stderr[-500:]}"
    )

    # Now clean
    result = subprocess.run(
        ["make", "clean"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=subprocess_timeout,
    )
    assert result.returncode == 0, f"make clean failed: {result.stderr}"

    # Verify key artifacts are gone
    artifacts = [".pytest_cache", ".ruff_cache", ".coverage"]
    for artifact in artifacts:
        artifact_path = os.path.join(repo_root, artifact)
        assert not os.path.exists(artifact_path), f"make clean should remove {artifact}, but it still exists"
