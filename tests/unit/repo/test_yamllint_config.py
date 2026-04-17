"""Tests for .yamllint configuration.

Validates that the rpm-git-repo yamllint configuration is valid and
catches known-bad YAML patterns in test fixtures.
"""

import os
import subprocess

import pytest

REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)


@pytest.mark.unit
def test_yamllint_config_valid():
    """Validate that .yamllint is valid configuration.

    Given: .yamllint exists at repo root
    When: yamllint is invoked with a clean YAML input
    Then: It does not report a config error and exits zero
    """
    config_path = os.path.join(REPO_ROOT, ".yamllint")
    assert os.path.isfile(config_path), f".yamllint must exist at repo root: {config_path}"
    result = subprocess.run(
        ["yamllint", "-c", config_path, "-"],
        input="---\nkey: value\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"yamllint should accept valid YAML, stderr: {result.stderr}"


@pytest.mark.unit
def test_yamllint_catches_known_bad_yaml():
    """Validate that yamllint catches errors in known-bad fixture.

    Given: A known-bad YAML file exists in tests/fixtures/
    When: yamllint is run against it
    Then: It reports errors and exits non-zero
    """
    bad_file = os.path.join(REPO_ROOT, "tests", "fixtures", "repo", "linter-test-bad.yml")
    assert os.path.isfile(bad_file), f"Known-bad fixture must exist: {bad_file}"
    config_path = os.path.join(REPO_ROOT, ".yamllint")
    result = subprocess.run(
        ["yamllint", "-c", config_path, bad_file],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"yamllint should report errors on known-bad file, stdout: {result.stdout}, stderr: {result.stderr}"
    )
