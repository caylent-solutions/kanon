"""Tests for ruff configuration in pyproject.toml.

Validates that the rpm-git-repo ruff configuration is valid and catches
known-bad Python patterns in test fixtures.
"""

import os
import subprocess

import pytest


@pytest.mark.unit
def test_ruff_config_valid_syntax(repo_root):
    """Validate that ruff configuration in pyproject.toml is valid.

    Given: pyproject.toml contains [tool.ruff] configuration
    When: ruff check is invoked
    Then: ruff does not report a config error
    """
    config_path = os.path.join(repo_root, "pyproject.toml")
    assert os.path.isfile(config_path), f"pyproject.toml must exist at repo root: {config_path}"
    result = subprocess.run(
        [
            "ruff",
            "check",
            "--stdin-filename",
            "test.py",
        ],
        input="",
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert "Failed to parse" not in result.stderr, f"ruff config has invalid syntax: {result.stderr}"


@pytest.mark.unit
def test_ruff_catches_known_bad_python(repo_root):
    """Validate that ruff catches lint errors in known-bad fixture.

    Given: A known-bad Python file exists in tests/fixtures/
    When: ruff check is run against it
    Then: ruff reports errors and exits non-zero
    """
    bad_file = os.path.join(repo_root, "tests", "fixtures", "repo", "linter-test-bad.py")
    assert os.path.isfile(bad_file), f"Known-bad fixture must exist: {bad_file}"
    result = subprocess.run(
        ["ruff", "check", bad_file],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode != 0, (
        f"ruff check should report errors on known-bad file, stdout: {result.stdout}, stderr: {result.stderr}"
    )
    assert result.stdout.strip(), f"ruff check should produce output describing the errors, stderr: {result.stderr}"
