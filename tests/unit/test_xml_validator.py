"""Tests for XML validation."""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.xml_validator import find_xml_files, validate_manifest, validate_xml


@pytest.mark.unit
class TestFindXmlFiles:
    def test_finds_xml_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.xml").write_text("<manifest/>")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.xml").write_text("<manifest/>")
        result = find_xml_files(str(tmp_path))
        assert len(result) == 2

    def test_empty_dir(self, tmp_path: Path) -> None:
        result = find_xml_files(str(tmp_path))
        assert result == []


@pytest.mark.unit
class TestValidateManifest:
    def test_valid_manifest(self, tmp_path: Path) -> None:
        xml = tmp_path / "valid.xml"
        xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" path=".packages/proj" remote="origin" revision="main" />
            </manifest>
        """)
        )
        errors = validate_manifest(xml, tmp_path)
        assert errors == []

    def test_malformed_xml(self, tmp_path: Path) -> None:
        xml = tmp_path / "bad.xml"
        xml.write_text("<manifest><unclosed")
        errors = validate_manifest(xml, tmp_path)
        assert len(errors) == 1
        assert "parse error" in errors[0].lower()

    def test_wrong_root_element(self, tmp_path: Path) -> None:
        xml = tmp_path / "wrong.xml"
        xml.write_text("<notmanifest/>")
        errors = validate_manifest(xml, tmp_path)
        assert any("Root element" in e for e in errors)

    def test_missing_project_attr(self, tmp_path: Path) -> None:
        xml = tmp_path / "missing.xml"
        xml.write_text('<manifest><project name="proj" /></manifest>')
        errors = validate_manifest(xml, tmp_path)
        assert len(errors) > 0

    def test_broken_include(self, tmp_path: Path) -> None:
        xml = tmp_path / "inc.xml"
        xml.write_text('<manifest><include name="nonexistent.xml" /></manifest>')
        errors = validate_manifest(xml, tmp_path)
        assert any("non-existent" in e for e in errors)

    def test_missing_remote_attr(self, tmp_path: Path) -> None:
        xml = tmp_path / "remote.xml"
        xml.write_text('<manifest><remote name="origin" /></manifest>')
        errors = validate_manifest(xml, tmp_path)
        assert any("fetch" in e for e in errors)

    def test_include_missing_name(self, tmp_path: Path) -> None:
        xml = tmp_path / "inc.xml"
        xml.write_text("<manifest><include /></manifest>")
        errors = validate_manifest(xml, tmp_path)
        assert any("name" in e for e in errors)


@pytest.mark.unit
class TestValidateXml:
    def test_valid_repo_returns_zero(self, tmp_path: Path) -> None:
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "valid.xml").write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" path=".packages/proj" remote="origin" revision="main" />
            </manifest>
        """)
        )
        assert validate_xml(tmp_path) == 0

    def test_no_xml_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()
        assert validate_xml(tmp_path) == 1

    def test_errors_return_one(self, tmp_path: Path) -> None:
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "bad.xml").write_text("<manifest><unclosed")
        assert validate_xml(tmp_path) == 1

    def test_missing_repo_specs_returns_one(self, tmp_path: Path) -> None:
        assert validate_xml(tmp_path) == 1
