"""Integration tests for marketplace manifest validation (13 tests).

Exercises validate_marketplace(), validate_linkfile_dest(),
validate_include_chain(), validate_name_uniqueness(), and validate_tag_format()
using real temporary directories and XML files.
"""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.marketplace_validator import (
    _is_exact_tag_revision,
    validate_include_chain,
    validate_linkfile_dest,
    validate_marketplace,
    validate_name_uniqueness,
    validate_tag_format,
)


def _ls_remote_hit(_url: str, ref: str) -> tuple[int, str, str]:
    """Stub ls-remote runner reporting *ref* exists (offline, no network)."""
    return (0, f"deadbeef\t{ref}\n", "")


def _write_xml(path: Path, content: str) -> Path:
    """Write XML to path (creating parent dirs) and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


def _valid_marketplace_xml() -> str:
    """Return a valid marketplace manifest XML body (no prolog)."""
    return textwrap.dedent("""\
        <manifest>
          <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
            <linkfile src="proj" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
          </project>
          <catalog-metadata>
            <name>proj</name>
            <display-name>Proj</display-name>
            <description>d</description>
            <version>1.0.0</version>
          </catalog-metadata>
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
    """Verify exact-only revision tag format validation (spec Section 4.5 / FR-22)."""

    @pytest.mark.parametrize(
        "revision,filename_stem",
        [
            ("refs/tags/example/proj/1.0.0", "refs_tags"),
            ("refs/tags/example/proj/2024.6", "calver"),
            ("refs/tags/deep/nested/proj/1.2.0a1", "prerelease"),
        ],
    )
    def test_exact_tag_revision_returns_no_errors(self, tmp_path: Path, revision: str, filename_stem: str) -> None:
        xml = _write_xml(
            tmp_path / f"m_{filename_stem}.xml",
            f'<manifest><project name="p" path=".packages/p" remote="r" revision="{revision}" /></manifest>',
        )
        assert validate_tag_format([xml], tmp_path) == []

    @pytest.mark.parametrize(
        "revision,filename_stem",
        [
            ("~=1.2.0", "compat_release"),
            ("*", "wildcard"),
            ("main", "branch_main"),
            (">=1.0.0", "gte_1_0_0"),
            ("refs/tags/example/proj/*", "prefixed_wildcard"),
            ("refs/heads/main", "refs_heads"),
        ],
    )
    def test_non_exact_revision_returns_error(self, tmp_path: Path, revision: str, filename_stem: str) -> None:
        xml = _write_xml(
            tmp_path / f"m_{filename_stem}.xml",
            f'<manifest><project name="p" path=".packages/p" remote="r" revision="{revision}" /></manifest>',
        )
        errors = validate_tag_format([xml], tmp_path)
        assert len(errors) == 1
        assert "exact" in errors[0].lower()

    def test_range_constraint_returns_error(self, tmp_path: Path) -> None:
        """A compound range constraint (XML-encoded) is rejected exact-only."""
        xml = _write_xml(
            tmp_path / "m_range.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="&gt;=1.0.0,&lt;2.0.0" /></manifest>',
        )
        errors = validate_tag_format([xml], tmp_path)
        assert len(errors) == 1
        assert "exact" in errors[0].lower()

    def test_is_exact_tag_revision_wildcard_rejected(self) -> None:
        assert _is_exact_tag_revision("*") is False

    def test_is_exact_tag_revision_refs_tags_accepted(self) -> None:
        assert _is_exact_tag_revision("refs/tags/org/proj/1.0.0") is True

    def test_is_exact_tag_revision_constraint_rejected(self) -> None:
        assert _is_exact_tag_revision("~=1.0.0") is False

    def test_is_exact_tag_revision_refs_heads_rejected(self) -> None:
        assert _is_exact_tag_revision("refs/heads/main") is False

    def test_is_exact_tag_revision_branch_rejected(self) -> None:
        assert _is_exact_tag_revision("main") is False


@pytest.mark.integration
class TestValidateMarketplaceFunction:
    """Verify validate_marketplace() return codes for various repo structures."""

    def test_valid_marketplace_returns_zero(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "repo-specs" / "test-marketplace.xml", _valid_marketplace_xml())
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 0

    def test_no_marketplace_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 1

    def test_invalid_linkfile_dest_returns_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "bad-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="proj" dest="/absolute/bad" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 1

    def test_new_naming_convention_discovered(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "sub" / "my-feature-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="proj" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 0

    def test_non_marketplace_xml_not_counted(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 1
