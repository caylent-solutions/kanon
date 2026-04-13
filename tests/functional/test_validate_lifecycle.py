"""Full validate xml/marketplace lifecycle tests."""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.marketplace_validator import validate_marketplace
from kanon_cli.core.xml_validator import validate_xml


def _write_xml(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


@pytest.mark.functional
class TestValidateXmlLifecycle:
    def test_valid_repo_specs_returns_zero(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "valid.xml",
            textwrap.dedent("""\
                <manifest>
                  <remote name="origin" fetch="https://example.com" />
                  <project name="proj" path=".packages/proj" remote="origin" revision="main" />
                </manifest>
            """),
        )

        result = validate_xml(tmp_path)
        assert result == 0

    def test_malformed_xml_returns_one(self, tmp_path: Path) -> None:
        xml_dir = tmp_path / "repo-specs"
        xml_dir.mkdir(parents=True)
        (xml_dir / "bad.xml").write_text("<manifest><unclosed")

        result = validate_xml(tmp_path)
        assert result == 1

    def test_missing_project_attr_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "missing.xml",
            '<manifest><project name="proj" /></manifest>',
        )

        result = validate_xml(tmp_path)
        assert result == 1

    def test_no_xml_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()

        result = validate_xml(tmp_path)
        assert result == 1


@pytest.mark.functional
class TestValidateMarketplaceLifecycle:
    def test_valid_marketplace_returns_zero(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "test-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 0

    def test_invalid_linkfile_dest_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "test-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="/bad/path" />
                  </project>
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 1

    def test_invalid_revision_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "test-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="invalid-string">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 1

    def test_new_naming_convention_discovered(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "history" / "claude-history-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 0

    def test_no_marketplace_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()

        result = validate_marketplace(tmp_path)
        assert result == 1

    def test_non_marketplace_xml_not_discovered(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            textwrap.dedent("""\
                <manifest>
                  <remote name="origin" fetch="https://example.com" />
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 1

    def test_duplicate_project_paths_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "a" / "a-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="dup" path=".packages/dup" remote="r" revision="refs/tags/ex/dup/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/dup" />
                  </project>
                </manifest>
            """),
        )
        _write_xml(
            tmp_path / "repo-specs" / "b" / "b-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="dup" path=".packages/dup" remote="r" revision="refs/tags/ex/dup/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/dup" />
                  </project>
                </manifest>
            """),
        )

        result = validate_marketplace(tmp_path)
        assert result == 1
