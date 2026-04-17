"""Tests for Makefile test, test-unit, test-functional, and validate targets.

Validates that the git-repo Makefile test targets invoke pytest with the
correct options: coverage for test, -m unit for test-unit, -m functional
for test-functional, and validate composes check + test.

Spec Reference: Plan: Per-Repo Tooling — make test, make test-unit,
make test-functional, make validate targets.
"""

import os
import re
import subprocess

import pytest


@pytest.mark.unit
def test_make_test_runs_pytest(repo_root):
    """Validate that make test invokes pytest with coverage.

    Given: The Makefile has a test target
    When: make test is dry-run
    Then: The command includes 'pytest' and coverage options
    Spec: Plan: Test targets
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "test"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n test failed: {result.stderr}"
    assert "pytest" in result.stdout, f"test target must invoke pytest, got: {result.stdout}"
    assert "cov" in result.stdout, f"test target must include coverage option, got: {result.stdout}"


@pytest.mark.unit
def test_make_test_unit_uses_marker(repo_root):
    """Validate that make test-unit filters by unit marker.

    Given: The Makefile has a test-unit target
    When: make test-unit is dry-run
    Then: The command includes '-m unit'
    Spec: Plan: Test targets
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "test-unit"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n test-unit failed: {result.stderr}"
    assert "pytest" in result.stdout, f"test-unit target must invoke pytest, got: {result.stdout}"
    assert "-m" in result.stdout and "unit" in result.stdout, (
        f"test-unit target must use '-m unit' marker filter, got: {result.stdout}"
    )


@pytest.mark.unit
def test_make_test_functional_uses_marker(repo_root):
    """Validate that make test-functional filters by functional marker.

    Given: The Makefile has a test-functional target
    When: make test-functional is dry-run
    Then: The command includes '-m functional'
    Spec: Plan: Test targets
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "test-functional"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n test-functional failed: {result.stderr}"
    assert "pytest" in result.stdout, f"test-functional target must invoke pytest, got: {result.stdout}"
    assert "-m" in result.stdout and "functional" in result.stdout, (
        f"test-functional target must use '-m functional' marker filter, got: {result.stdout}"
    )


@pytest.mark.unit
def test_make_validate_runs_check_and_test(repo_root):
    """Validate that make validate composes check and test.

    Given: The Makefile has a validate target
    When: make validate is dry-run
    Then: The output includes both check and test invocations
    Spec: Plan: Validate target
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "validate"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n validate failed: {result.stderr}"
    # validate should run check (which includes lint + format-check) and test
    assert "ruff check" in result.stdout, f"validate must include lint (ruff check), got: {result.stdout}"
    assert "pytest" in result.stdout, f"validate must include test (pytest), got: {result.stdout}"


@pytest.mark.unit
def test_pytest_markers_registered(repo_root):
    """Validate that pyproject.toml registers unit and functional markers.

    Given: pyproject.toml exists
    When: We read the pytest markers configuration
    Then: Both 'unit' and 'functional' markers are registered
    Spec: Plan: Pytest config
    """
    pyproject_path = os.path.join(repo_root, "pyproject.toml")
    with open(pyproject_path) as f:
        content = f.read()

    # Check for marker registrations in [tool.pytest.ini_options]
    assert "unit" in content, "pyproject.toml must register 'unit' marker"
    assert "functional" in content, "pyproject.toml must register 'functional' marker"


@pytest.mark.unit
def test_pyproject_has_testpaths(repo_root):
    """Validate that pyproject.toml configures testpaths.

    Given: pyproject.toml exists with pytest config
    When: We read the pytest configuration
    Then: testpaths is configured
    Spec: AC-6
    """
    pyproject_path = os.path.join(repo_root, "pyproject.toml")
    with open(pyproject_path) as f:
        content = f.read()

    assert "testpaths" in content, "pyproject.toml must configure testpaths for pytest"


@pytest.mark.unit
def test_pyproject_has_marker_comments(repo_root):
    """Validate that pyproject.toml includes comments explaining marker usage.

    Given: pyproject.toml exists with pytest markers
    When: We read the marker definitions
    Then: Each marker has a description explaining its purpose
    Spec: AC-DOC-1
    """
    pyproject_path = os.path.join(repo_root, "pyproject.toml")
    with open(pyproject_path) as f:
        content = f.read()

    # Markers should have descriptions (format: "name: description")
    assert re.search(r'"unit:\s+\S', content), "unit marker must have a description in pyproject.toml"
    assert re.search(r'"functional:\s+\S', content), "functional marker must have a description in pyproject.toml"
