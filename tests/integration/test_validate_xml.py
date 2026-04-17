"""Integration tests for XML manifest validation (15 tests).

Exercises validate_xml() and validate_manifest() using real temporary
directories and XML files.  Tests cover well-formedness, required attributes,
include chains, and the validate_xml() return codes.
"""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.xml_validator import find_xml_files, validate_manifest, validate_xml


# ---------------------------------------------------------------------------
# AC-FUNC-003: Validate XML integration tests (15 tests)
# ---------------------------------------------------------------------------


def _write_xml(path: Path, content: str) -> Path:
    """Write XML content to path (creating parent dirs) and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


def _valid_manifest_xml() -> str:
    """Return a minimal valid manifest XML body (without the prolog)."""
    return textwrap.dedent("""\
        <manifest>
          <remote name="origin" fetch="https://example.com" />
          <project name="proj" path=".packages/proj" remote="origin" revision="main" />
        </manifest>
    """)


@pytest.mark.integration
class TestFindXmlFiles:
    """Verify recursive XML file discovery."""

    def test_finds_files_in_root(self, tmp_path: Path) -> None:
        (tmp_path / "a.xml").write_text("<manifest/>")
        files = find_xml_files(str(tmp_path))
        assert len(files) == 1

    def test_finds_files_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a.xml").write_text("<manifest/>")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.xml").write_text("<manifest/>")
        files = find_xml_files(str(tmp_path))
        assert len(files) == 2

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        files = find_xml_files(str(tmp_path))
        assert files == []


@pytest.mark.integration
class TestValidateManifest:
    """Verify single-file manifest validation."""

    def test_valid_manifest_returns_no_errors(self, tmp_path: Path) -> None:
        xml = _write_xml(tmp_path / "valid.xml", _valid_manifest_xml())
        errors = validate_manifest(xml, tmp_path)
        assert errors == []

    def test_malformed_xml_returns_error(self, tmp_path: Path) -> None:
        xml = tmp_path / "bad.xml"
        xml.write_text("<manifest><unclosed")
        errors = validate_manifest(xml, tmp_path)
        assert len(errors) == 1
        assert "parse error" in errors[0].lower()

    def test_wrong_root_element_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(tmp_path / "wrong.xml", "<notmanifest/>")
        errors = validate_manifest(xml, tmp_path)
        assert any("Root element" in e for e in errors)

    def test_project_missing_name_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project path=".packages/p" remote="o" revision="main" /></manifest>',
        )
        errors = validate_manifest(xml, tmp_path)
        assert any("name" in e for e in errors)

    def test_project_missing_path_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project name="p" remote="o" revision="main" /></manifest>',
        )
        errors = validate_manifest(xml, tmp_path)
        assert any("path" in e for e in errors)

    def test_remote_missing_fetch_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            '<manifest><remote name="origin" /></manifest>',
        )
        errors = validate_manifest(xml, tmp_path)
        assert any("fetch" in e for e in errors)

    def test_broken_include_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            '<manifest><include name="nonexistent.xml" /></manifest>',
        )
        errors = validate_manifest(xml, tmp_path)
        assert any("non-existent" in e for e in errors)

    def test_include_missing_name_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(tmp_path / "m.xml", "<manifest><include /></manifest>")
        errors = validate_manifest(xml, tmp_path)
        assert any("name" in e for e in errors)

    def test_valid_include_chain_returns_no_errors(self, tmp_path: Path) -> None:
        included = _write_xml(tmp_path / "base.xml", '<manifest><remote name="r" fetch="u" /></manifest>')
        xml = _write_xml(
            tmp_path / "main.xml",
            f'<manifest><include name="{included.name}" /></manifest>',
        )
        errors = validate_manifest(xml, tmp_path)
        assert errors == []


@pytest.mark.integration
class TestValidateXml:
    """Verify validate_xml() return codes for various repo structures."""

    def test_valid_repo_returns_zero(self, tmp_path: Path) -> None:
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        _write_xml(specs / "manifest.xml", _valid_manifest_xml())
        assert validate_xml(tmp_path) == 0

    def test_no_xml_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()
        assert validate_xml(tmp_path) == 1

    def test_missing_repo_specs_dir_returns_one(self, tmp_path: Path) -> None:
        assert validate_xml(tmp_path) == 1

    def test_invalid_xml_returns_one(self, tmp_path: Path) -> None:
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        (specs / "bad.xml").write_text("<manifest><unclosed")
        assert validate_xml(tmp_path) == 1

    def test_multiple_valid_manifests_return_zero(self, tmp_path: Path) -> None:
        specs = tmp_path / "repo-specs"
        specs.mkdir()
        for name in ["a.xml", "b.xml", "c.xml"]:
            _write_xml(specs / name, _valid_manifest_xml())
        assert validate_xml(tmp_path) == 0
