"""Tests for test fixture files in tests/fixtures/.

Validates that golden fixture files are syntactically valid
and loadable by conftest.py fixtures.

Spec Reference: Plan: Per-Repo Tooling — tests/fixtures/ with initial test data.
"""

import json
import os
import xml.etree.ElementTree as ET

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.mark.unit
def test_fixture_files_exist():
    """Verify all planned fixture files exist.

    Given: tests/fixtures/ directory exists
    When: We check for required fixture files
    Then: sample-manifest.xml, sample-project-config.json, and README.md all exist
    Spec: Plan: Test fixtures
    """
    expected_files = [
        "sample-manifest.xml",
        "sample-project-config.json",
        "README.md",
    ]
    for filename in expected_files:
        filepath = os.path.join(FIXTURES_DIR, filename)
        assert os.path.isfile(filepath), f"Required fixture file missing: {filepath}"


@pytest.mark.unit
def test_sample_manifest_valid_xml():
    """Verify sample-manifest.xml is well-formed XML.

    Given: tests/fixtures/sample-manifest.xml exists
    When: Parsed as XML
    Then: Parsing succeeds and root element is <manifest>
    Spec: Plan: Test fixtures
    """
    manifest_path = os.path.join(FIXTURES_DIR, "sample-manifest.xml")
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    assert root.tag == "manifest", f"Root element must be <manifest>, got <{root.tag}>"
    remotes = root.findall("remote")
    assert len(remotes) > 0, "Manifest must contain at least one <remote> element"
    projects = root.findall("project")
    assert len(projects) > 0, "Manifest must contain at least one <project> element"


@pytest.mark.unit
def test_sample_project_config_valid_json():
    """Verify sample-project-config.json is valid JSON.

    Given: tests/fixtures/sample-project-config.json exists
    When: Parsed as JSON
    Then: Parsing succeeds and contains expected keys
    Spec: Plan: Test fixtures
    """
    config_path = os.path.join(FIXTURES_DIR, "sample-project-config.json")
    with open(config_path) as f:
        config = json.load(f)
    assert isinstance(config, dict), f"Config must be a JSON object, got {type(config)}"
    assert "name" in config, "Config must contain 'name' key"
    assert "path" in config, "Config must contain 'path' key"
    assert "remote" in config, "Config must contain 'remote' key"
    assert "revision" in config, "Config must contain 'revision' key"
