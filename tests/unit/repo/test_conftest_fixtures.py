"""Tests for conftest.py shared fixtures.

Validates that mock_manifest_xml and mock_project_config fixtures
are available, use tmp_path for isolation, and return expected data.

Spec Reference: Plan: Test harness — tests/conftest.py with shared fixtures.
"""

import os

import pytest


@pytest.mark.unit
def test_mock_manifest_xml_fixture(mock_manifest_xml):
    """Verify mock_manifest_xml fixture returns valid XML content.

    Given: conftest.py provides a mock_manifest_xml fixture
    When: A test requests the fixture
    Then: It receives a path to a file containing valid manifest XML
    Spec: Plan: Test harness
    """
    assert os.path.isfile(mock_manifest_xml), (
        f"mock_manifest_xml must return a path to an existing file: {mock_manifest_xml}"
    )
    with open(mock_manifest_xml) as f:
        content = f.read()
    assert "<?xml" in content, "Manifest XML must contain XML declaration"
    assert "<manifest>" in content, "Manifest XML must contain <manifest> element"
    assert "<remote" in content, "Manifest XML must contain <remote> element"
    assert "<project" in content, "Manifest XML must contain <project> element"


@pytest.mark.unit
def test_mock_project_config_fixture(mock_project_config):
    """Verify mock_project_config fixture returns a valid config dict.

    Given: conftest.py provides a mock_project_config fixture
    When: A test requests the fixture
    Then: It receives a dict with expected project config keys
    Spec: Plan: Test harness
    """
    assert isinstance(mock_project_config, dict), (
        f"mock_project_config must return a dict, got {type(mock_project_config)}"
    )
    assert "name" in mock_project_config, "Config must contain 'name' key"
    assert "path" in mock_project_config, "Config must contain 'path' key"
    assert "remote" in mock_project_config, "Config must contain 'remote' key"
    assert "revision" in mock_project_config, "Config must contain 'revision' key"


@pytest.mark.unit
def test_fixtures_use_tmp_path(mock_manifest_xml, tmp_path):
    """Verify that fixtures use tmp_path for test isolation.

    Given: conftest.py fixtures use tmp_path
    When: A test checks the fixture output location
    Then: The file is located under the tmp_path hierarchy
    Spec: Plan: Test harness
    """
    # mock_manifest_xml should be within a temporary directory
    assert os.path.isfile(mock_manifest_xml), f"mock_manifest_xml must be a real file: {mock_manifest_xml}"
    # The file should not be in the repo tree — it should be in a temp dir
    repo_root = os.path.join(os.path.dirname(__file__), os.pardir)
    real_repo = os.path.realpath(repo_root)
    real_file = os.path.realpath(mock_manifest_xml)
    assert not real_file.startswith(real_repo), (
        f"Fixture file should be in a temp directory, not in repo tree: {real_file}"
    )
