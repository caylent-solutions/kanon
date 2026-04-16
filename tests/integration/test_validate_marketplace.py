"""Integration tests for marketplace manifest validation (13 tests).

Exercises validate_marketplace(), validate_linkfile_dest(),
validate_include_chain(), validate_name_uniqueness(), and validate_tag_format()
using real temporary directories and XML files.
"""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.marketplace_validator import (
    _is_valid_revision,
    validate_include_chain,
    validate_linkfile_dest,
    validate_marketplace,
    validate_name_uniqueness,
    validate_tag_format,
)


# ---------------------------------------------------------------------------
# AC-FUNC-004: Validate marketplace integration tests (13 tests)
# ---------------------------------------------------------------------------


def _write_xml(path: Path, content: str) -> Path:
    """Write XML to path (creating parent dirs) and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


def _valid_marketplace_xml() -> str:
    """Return a valid marketplace manifest XML body (no prolog)."""
    return textwrap.dedent("""\
        <manifest>
          <project name="proj" path=".packages/proj" remote="r" revision="main">
            <linkfile src="proj" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
          </project>
        </manifest>
    """)


@pytest.mark.integration
class TestLinkfileDestValidation:
    """Verify linkfile dest attribute validation."""

    def test_valid_dest_returns_no_errors(self, tmp_path: Path) -> None:
        xml = _write_xml(tmp_path / "m.xml", _valid_marketplace_xml())
        assert validate_linkfile_dest(xml) == []

    def test_invalid_absolute_dest_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="proj" dest="/absolute/bad/path" />
                  </project>
                </manifest>
            """),
        )
        errors = validate_linkfile_dest(xml)
        assert len(errors) >= 1
        assert "proj" in errors[0]

    def test_missing_dest_prefix_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="proj" dest="relative/path" />
                  </project>
                </manifest>
            """),
        )
        errors = validate_linkfile_dest(xml)
        assert len(errors) >= 1


@pytest.mark.integration
class TestIncludeChainValidation:
    """Verify include chain integrity validation."""

    def test_valid_chain_returns_no_errors(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "base.xml", '<manifest><remote name="r" fetch="u" /></manifest>')
        xml = _write_xml(tmp_path / "leaf.xml", '<manifest><include name="base.xml" /></manifest>')
        assert validate_include_chain(xml, tmp_path) == []

    def test_broken_chain_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(tmp_path / "leaf.xml", '<manifest><include name="missing.xml" /></manifest>')
        errors = validate_include_chain(xml, tmp_path)
        assert any("missing.xml" in e for e in errors)

    def test_circular_include_does_not_loop(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "a.xml", '<manifest><include name="b.xml" /></manifest>')
        _write_xml(tmp_path / "b.xml", '<manifest><include name="a.xml" /></manifest>')
        errors = validate_include_chain(tmp_path / "a.xml", tmp_path)
        assert errors == []


@pytest.mark.integration
class TestNameUniquenessValidation:
    """Verify project path uniqueness validation across manifests."""

    def test_unique_paths_returns_no_errors(self, tmp_path: Path) -> None:
        f1 = _write_xml(
            tmp_path / "a.xml",
            '<manifest><project name="a" path=".packages/a" remote="r" revision="main" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "b.xml",
            '<manifest><project name="b" path=".packages/b" remote="r" revision="main" /></manifest>',
        )
        assert validate_name_uniqueness([f1, f2]) == []

    def test_duplicate_paths_returns_error(self, tmp_path: Path) -> None:
        f1 = _write_xml(
            tmp_path / "a.xml",
            '<manifest><project name="dup" path=".packages/dup" remote="r" revision="main" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "b.xml",
            '<manifest><project name="dup" path=".packages/dup" remote="r" revision="main" /></manifest>',
        )
        errors = validate_name_uniqueness([f1, f2])
        assert len(errors) >= 1


@pytest.mark.integration
class TestTagFormatValidation:
    """Verify revision tag format validation."""

    @pytest.mark.parametrize(
        "revision,filename_stem",
        [
            ("refs/tags/example/proj/1.0.0", "refs_tags"),
            ("~=1.2.0", "compat_release"),
            ("*", "wildcard"),
            ("main", "branch_main"),
            (">=1.0.0", "gte_1_0_0"),
        ],
    )
    def test_valid_revision_returns_no_errors(self, tmp_path: Path, revision: str, filename_stem: str) -> None:
        xml = _write_xml(
            tmp_path / f"m_{filename_stem}.xml",
            f'<manifest><project name="p" path=".packages/p" remote="r" revision="{revision}" /></manifest>',
        )
        assert validate_tag_format([xml]) == []

    def test_valid_range_revision_returns_no_errors(self, tmp_path: Path) -> None:
        """Range constraints with < require XML entity encoding (&lt;) in the revision attr."""
        xml = _write_xml(
            tmp_path / "m_range.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="&gt;=1.0.0,&lt;2.0.0" /></manifest>',
        )
        assert validate_tag_format([xml]) == []

    def test_invalid_revision_returns_error(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="refs/heads/main" /></manifest>',
        )
        errors = validate_tag_format([xml])
        assert len(errors) >= 1

    def test_is_valid_revision_wildcard(self) -> None:
        assert _is_valid_revision("*") is True

    def test_is_valid_revision_refs_tags(self) -> None:
        assert _is_valid_revision("refs/tags/org/proj/1.0.0") is True

    def test_is_valid_revision_constraint(self) -> None:
        assert _is_valid_revision("~=1.0.0") is True

    def test_is_valid_revision_refs_heads_returns_false(self) -> None:
        assert _is_valid_revision("refs/heads/main") is False


@pytest.mark.integration
class TestValidateMarketplaceFunction:
    """Verify validate_marketplace() return codes for various repo structures."""

    def test_valid_marketplace_returns_zero(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "repo-specs" / "test-marketplace.xml", _valid_marketplace_xml())
        assert validate_marketplace(tmp_path) == 0

    def test_no_marketplace_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()
        assert validate_marketplace(tmp_path) == 1

    def test_invalid_linkfile_dest_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "bad-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="proj" dest="/absolute/bad" />
                  </project>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path) == 1

    def test_new_naming_convention_discovered(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "sub" / "my-feature-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/1.0.0">
                    <linkfile src="proj" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path) == 0

    def test_non_marketplace_xml_not_counted(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )
        assert validate_marketplace(tmp_path) == 1
