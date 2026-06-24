"""Unit tests for CatalogMetadata dataclass, _parse_catalog_metadata(), and derive_source_name().

Tests cover every acceptance criterion: happy path, required fields,
recommended fields, duplicate children, zero/multiple blocks, malformed XML,
whitespace-only fields, keywords parsing, and the derive_source_name helper.
"""

import textwrap
from pathlib import Path

import pytest

from kanon_cli.core.metadata import (
    CatalogMetadata,
    CatalogMetadataParseError,
    _parse_catalog_metadata,
    derive_source_name,
    find_catalog_entry_files,
)


def _write_xml(path: Path, content: str) -> Path:
    """Write XML content to path, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


FULL_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>my-package</name>
        <display-name>My Package</display-name>
        <description>A helpful package.</description>
        <version>1.2.3</version>
        <type>plugin</type>
        <owner-name>Alice</owner-name>
        <owner-email>alice@example.com</owner-email>
        <keywords>tools, utilities, helpers</keywords>
      </catalog-metadata>
    </manifest>
""")

REQUIRED_ONLY_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>bare-package</name>
        <display-name>Bare Package</display-name>
        <description>Minimal.</description>
        <version>0.1.0</version>
      </catalog-metadata>
    </manifest>
""")


OLD_FLAT_ATTRIBUTE_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata display-name="My Package"
                        description="A helpful package."
                        version="1.2.3"
                        type="plugin"
                        owner-name="Alice"
                        owner-email="alice@example.com"
                        keywords="tools, utilities" />
    </manifest>
""")


@pytest.mark.unit
class TestParseCatalogMetadataRejectsOldScheme:
    """New-scheme-only: the old flat-attribute ``<catalog-metadata .../>`` form is
    rejected with a clear, migration-pointing error (not the generic missing-name error)."""

    def test_old_flat_attribute_scheme_raises_explicit_error(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path / "old-marketplace.xml", OLD_FLAT_ATTRIBUTE_XML)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "flat-attribute" in msg
        assert "unsupported" in msg or "no longer supported" in msg
        assert "nested" in msg
        assert "old-marketplace.xml" in msg


@pytest.mark.unit
class TestCatalogMetadataDataclass:
    """AC-FUNC-001: CatalogMetadata dataclass has the correct field set."""

    def test_required_fields_present(self) -> None:
        md = CatalogMetadata(
            name="x",
            display_name="X",
            description="desc",
            version="1.0.0",
        )
        assert md.name == "x"
        assert md.display_name == "X"
        assert md.description == "desc"
        assert md.version == "1.0.0"

    def test_optional_fields_default_to_none_or_empty(self) -> None:
        md = CatalogMetadata(
            name="x",
            display_name="X",
            description="desc",
            version="1.0.0",
        )
        assert md.type is None
        assert md.owner_name is None
        assert md.owner_email is None
        assert md.keywords == []

    def test_all_fields_populated(self) -> None:
        md = CatalogMetadata(
            name="pkg",
            display_name="Pkg",
            description="A package.",
            version="2.0.0",
            type="plugin",
            owner_name="Bob",
            owner_email="bob@example.com",
            keywords=["a", "b"],
        )
        assert md.type == "plugin"
        assert md.owner_name == "Bob"
        assert md.owner_email == "bob@example.com"
        assert md.keywords == ["a", "b"]


@pytest.mark.unit
class TestParseCatalogMetadataHappyPath:
    """AC-FUNC-002: Full happy-path parsing returns a correct CatalogMetadata."""

    def test_all_fields_full_xml(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", FULL_XML)
        result = _parse_catalog_metadata(xml_file)
        assert isinstance(result, CatalogMetadata)
        assert result.name == "my-package"
        assert result.display_name == "My Package"
        assert result.description == "A helpful package."
        assert result.version == "1.2.3"
        assert result.type == "plugin"
        assert result.owner_name == "Alice"
        assert result.owner_email == "alice@example.com"
        assert result.keywords == ["tools", "utilities", "helpers"]

    def test_required_only_xml(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", REQUIRED_ONLY_XML)
        result = _parse_catalog_metadata(xml_file)
        assert result.name == "bare-package"
        assert result.display_name == "Bare Package"
        assert result.description == "Minimal."
        assert result.version == "0.1.0"
        assert result.type is None
        assert result.owner_name is None
        assert result.owner_email is None
        assert result.keywords == []


@pytest.mark.unit
class TestMissingRequiredFields:
    """AC-FUNC-003: Missing any required field raises CatalogMetadataParseError."""

    @pytest.mark.parametrize(
        "missing_field,xml_tag",
        [
            ("name", "name"),
            ("display-name", "display-name"),
            ("description", "description"),
            ("version", "version"),
        ],
    )
    def test_missing_required_field(self, tmp_path: Path, missing_field: str, xml_tag: str) -> None:
        all_fields = [
            ("name", "pkg"),
            ("display-name", "Pkg"),
            ("description", "desc"),
            ("version", "1.0.0"),
        ]
        inner = "".join(f"<{tag}>{val}</{tag}>" for tag, val in all_fields if tag != missing_field)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest><catalog-metadata>" + inner + "</catalog-metadata></manifest>"
        )
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert missing_field in msg
        assert str(xml_file) in msg


@pytest.mark.unit
class TestWhitespaceOnlyRequiredField:
    """AC-FUNC-004: Whitespace-only text for required field is treated as missing."""

    @pytest.mark.parametrize(
        "field_tag,whitespace_value",
        [
            ("name", "   "),
            ("display-name", "\t"),
            ("description", "   "),
            ("version", " "),
        ],
    )
    def test_whitespace_only_is_missing(self, tmp_path: Path, field_tag: str, whitespace_value: str) -> None:
        default_values: dict[str, str] = {
            "name": "pkg",
            "display-name": "Pkg",
            "description": "desc",
            "version": "1.0.0",
        }
        inner = ""
        for tag in ("name", "display-name", "description", "version"):
            if tag == field_tag:
                inner += f"<{tag}>{whitespace_value}</{tag}>"
            else:
                inner += f"<{tag}>{default_values[tag]}</{tag}>"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest><catalog-metadata>" + inner + "</catalog-metadata></manifest>"
        )
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert field_tag in msg
        assert str(xml_file) in msg


@pytest.mark.unit
class TestMissingRecommendedFields:
    """AC-FUNC-005: Missing recommended fields emit a consolidated warning to stderr."""

    def test_missing_all_recommended_emits_warning(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", REQUIRED_ONLY_XML)
        result = _parse_catalog_metadata(xml_file)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "type" in captured.err
        assert "owner-name" in captured.err
        assert "owner-email" in captured.err
        assert "keywords" in captured.err
        assert result.type is None
        assert result.owner_name is None
        assert result.owner_email is None
        assert result.keywords == []

    def test_warning_is_single_consolidated_line(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", REQUIRED_ONLY_XML)
        _parse_catalog_metadata(xml_file)
        captured = capsys.readouterr()
        warning_lines = [ln for ln in captured.err.splitlines() if "WARNING" in ln]
        assert len(warning_lines) == 1

    def test_no_warning_when_all_recommended_present(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", FULL_XML)
        _parse_catalog_metadata(xml_file)
        captured = capsys.readouterr()
        assert "WARNING" not in captured.err

    def test_whitespace_only_optional_field_yields_none(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:

        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest><catalog-metadata>"
            "<name>pkg</name>"
            "<display-name>Pkg</display-name>"
            "<description>desc</description>"
            "<version>1.0.0</version>"
            "<type>   </type>"
            "<owner-name>Alice</owner-name>"
            "<owner-email>alice@example.com</owner-email>"
            "<keywords>tools</keywords>"
            "</catalog-metadata></manifest>"
        )
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        result = _parse_catalog_metadata(xml_file)
        assert result.type is None


@pytest.mark.unit
class TestDuplicateChildElements:
    """AC-FUNC-006: Duplicate child elements raise a hard error."""

    def test_duplicate_name_raises(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <name>other-pkg</name>
                <display-name>Pkg</display-name>
                <description>desc</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "name" in msg
        assert str(xml_file) in msg

    def test_duplicate_optional_field_raises(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <display-name>Pkg</display-name>
                <description>desc</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <type>library</type>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "type" in msg
        assert str(xml_file) in msg


@pytest.mark.unit
class TestZeroAndMultipleBlocks:
    """AC-FUNC-007 and AC-FUNC-008: Wrong number of catalog-metadata blocks."""

    def test_zero_blocks_raises(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <project name="x" />
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "catalog-metadata" in msg
        assert str(xml_file) in msg

    def test_multiple_blocks_raises(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg-a</name>
                <display-name>Pkg A</display-name>
                <description>First.</description>
                <version>1.0.0</version>
              </catalog-metadata>
              <catalog-metadata>
                <name>pkg-b</name>
                <display-name>Pkg B</display-name>
                <description>Second.</description>
                <version>2.0.0</version>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "catalog-metadata" in msg
        assert str(xml_file) in msg
        assert "2" in msg


@pytest.mark.unit
class TestMalformedXml:
    """AC-FUNC-009: Malformed XML raises a hard error citing the file path."""

    def test_malformed_xml_raises(self, tmp_path: Path) -> None:
        xml_file = _write_xml(
            tmp_path / "pkg-marketplace.xml",
            "this is not valid XML <<<<<",
        )
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert str(xml_file) in msg

    def test_unclosed_tag_raises(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        assert str(xml_file) in str(exc_info.value)


@pytest.mark.unit
class TestKeywordsParsing:
    """AC-FUNC-010: keywords are parsed from comma-separated <keywords> element."""

    def test_keywords_trimmed(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <display-name>Pkg</display-name>
                <description>desc</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Alice</owner-name>
                <owner-email>alice@example.com</owner-email>
                <keywords>  foo ,  bar ,baz  </keywords>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        result = _parse_catalog_metadata(xml_file)
        assert result.keywords == ["foo", "bar", "baz"]

    def test_empty_keywords_element_yields_empty_list(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <display-name>Pkg</display-name>
                <description>desc</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Alice</owner-name>
                <owner-email>alice@example.com</owner-email>
                <keywords></keywords>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "pkg-marketplace.xml", xml_content)
        result = _parse_catalog_metadata(xml_file)
        assert result.keywords == []
        assert result.keywords is not None


@pytest.mark.unit
class TestEndToEndCycle:
    """AC-CYCLE-001: End-to-end verification of happy-path, missing-required, duplicate-child."""

    def test_happy_path_returns_populated_dataclass(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path / "happy-marketplace.xml", FULL_XML)
        result = _parse_catalog_metadata(xml_file)
        assert result.name == "my-package"
        assert result.version == "1.2.3"
        assert result.keywords == ["tools", "utilities", "helpers"]

    def test_missing_required_field_raises_with_path(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <display-name>Pkg</display-name>
                <version>1.0.0</version>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "missing-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "description" in msg
        assert str(xml_file) in msg

    def test_duplicate_child_raises_with_path(self, tmp_path: Path) -> None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <name>duplicate-pkg</name>
                <display-name>Pkg</display-name>
                <description>desc</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = _write_xml(tmp_path / "dup-marketplace.xml", xml_content)
        with pytest.raises(CatalogMetadataParseError) as exc_info:
            _parse_catalog_metadata(xml_file)
        msg = str(exc_info.value)
        assert "name" in msg
        assert str(xml_file) in msg


@pytest.mark.unit
class TestDeriveSourceName:
    """Tests for derive_source_name() in metadata.py (source-test-atomicity companion).

    This class provides the TDD-paired coverage required by
    docs/source-test-atomicity.md for the production change in
    src/kanon_cli/core/metadata.py. Detailed parametrised coverage lives in
    tests/unit/test_derive_source_name.py; this class confirms the function is
    importable from the module and applies the two-step transformation rule.
    """

    def test_derive_source_name_normalises_mixed_case_with_hyphen(self) -> None:
        """derive_source_name applies both transformations: lowercase and hyphen-to-underscore."""
        assert derive_source_name("Foo-Bar") == "foo_bar"

    def test_lowercase_passthrough(self) -> None:
        """Lowercase-only input is returned unchanged."""
        assert derive_source_name("foo") == "foo"

    def test_hyphen_replaced(self) -> None:
        """Each hyphen is replaced by an underscore."""
        assert derive_source_name("foo-bar-baz") == "foo_bar_baz"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert derive_source_name("") == ""

    def test_warning_on_special_chars(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Characters outside [a-zA-Z0-9_-] trigger a stderr WARNING."""
        derive_source_name("foo.bar")
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    @pytest.mark.parametrize(
        "input_name",
        [
            "https://github.com/org/repo",
            "/path/to/manifest.xml",
            "repo-specs/myentry-marketplace.xml",
        ],
    )
    def test_warn_false_emits_no_warning(self, input_name: str, capsys: pytest.CaptureFixture[str]) -> None:
        """derive_source_name(x, warn=False) emits no stderr warning for out-of-set input."""
        derive_source_name(input_name, warn=False)
        captured = capsys.readouterr()
        assert "outside the recommended set" not in captured.err
        assert "WARNING" not in captured.err

    @pytest.mark.parametrize(
        "input_name",
        [
            "https://github.com/org/repo",
            "/path/to/manifest.xml",
        ],
    )
    def test_warn_true_emits_warning_for_out_of_set(self, input_name: str, capsys: pytest.CaptureFixture[str]) -> None:
        """derive_source_name(x) (default warn=True) emits a WARNING for out-of-set chars."""
        derive_source_name(input_name, warn=True)
        captured = capsys.readouterr()
        assert "outside the recommended set" in captured.err

    @pytest.mark.parametrize(
        "input_name",
        [
            "https://github.com/org/repo",
            "/path/to/manifest.xml",
            "My.Special-Name",
        ],
    )
    def test_normalized_return_value_identical_regardless_of_warn(self, input_name: str) -> None:
        """Suppressing the warning does not change the normalized return value."""
        result_warn_true = derive_source_name(input_name, warn=True)
        result_warn_false = derive_source_name(input_name, warn=False)
        assert result_warn_true == result_warn_false


_ENTRY_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name}</display-name>
        <description>desc</description>
        <version>1.0.0</version>
      </catalog-metadata>
    </manifest>
""")

_INCLUDE_XML = '<manifest><remote name="caylent" fetch="https://example.com" /></manifest>'


@pytest.mark.unit
class TestFindCatalogEntryFiles:
    """A catalog entry is any repo-specs/**/*.xml containing a <catalog-metadata> block."""

    def test_discovers_marketplace_named_entries(self, tmp_path: Path) -> None:
        """Legacy *-marketplace.xml names still match (they carry the block)."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "alpha-marketplace.xml", _ENTRY_XML.format(name="alpha"))
        _write_xml(repo_specs / "beta-marketplace.xml", _ENTRY_XML.format(name="beta"))
        names = {p.name for p in find_catalog_entry_files(tmp_path)}
        assert names == {"alpha-marketplace.xml", "beta-marketplace.xml"}

    def test_discovers_entry_regardless_of_filename(self, tmp_path: Path) -> None:
        """The -marketplace suffix is no longer required: any dash-or-no-dash name works."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "widget.xml", _ENTRY_XML.format(name="widget"))
        _write_xml(repo_specs / "my-tool.xml", _ENTRY_XML.format(name="my-tool"))
        _write_xml(repo_specs / "a-b-c.xml", _ENTRY_XML.format(name="abc"))
        names = {p.name for p in find_catalog_entry_files(tmp_path)}
        assert names == {"widget.xml", "my-tool.xml", "a-b-c.xml"}

    def test_excludes_metadata_less_includes(self, tmp_path: Path) -> None:
        """A manifest without <catalog-metadata> (a shared include) is NOT an entry."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "real.xml", _ENTRY_XML.format(name="real"))
        _write_xml(repo_specs / "remote.xml", _INCLUDE_XML)
        names = {p.name for p in find_catalog_entry_files(tmp_path)}
        assert names == {"real.xml"}
        assert "remote.xml" not in names

    def test_recurses_subdirectories(self, tmp_path: Path) -> None:
        nested = tmp_path / "repo-specs" / "team-a" / "group"
        _write_xml(nested / "svc.xml", _ENTRY_XML.format(name="svc"))
        names = [p.name for p in find_catalog_entry_files(tmp_path)]
        assert names == ["svc.xml"]

    def test_only_under_repo_specs(self, tmp_path: Path) -> None:
        """Entries outside repo-specs/ (e.g. a legacy catalog/ dir) are not discovered."""
        _write_xml(tmp_path / "catalog" / "x.xml", _ENTRY_XML.format(name="x"))
        _write_xml(tmp_path / "repo-specs" / "kept.xml", _ENTRY_XML.format(name="kept"))
        names = [p.name for p in find_catalog_entry_files(tmp_path)]
        assert names == ["kept.xml"]

    def test_excludes_non_xml(self, tmp_path: Path) -> None:
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "kept.xml", _ENTRY_XML.format(name="kept"))
        (repo_specs / "README.txt").write_text("not xml")
        names = [p.name for p in find_catalog_entry_files(tmp_path)]
        assert names == ["kept.xml"]

    def test_malformed_but_marked_file_is_returned(self, tmp_path: Path) -> None:
        """A malformed file that still contains the marker is returned so callers report the error."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "broken.xml", "<manifest><catalog-metadata><name>x")
        names = [p.name for p in find_catalog_entry_files(tmp_path)]
        assert names == ["broken.xml"]

    def test_sorted_output(self, tmp_path: Path) -> None:
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs / "zeta.xml", _ENTRY_XML.format(name="zeta"))
        _write_xml(repo_specs / "alpha.xml", _ENTRY_XML.format(name="alpha"))
        results = find_catalog_entry_files(tmp_path)
        assert results == sorted(results)

    def test_empty_when_repo_specs_missing(self, tmp_path: Path) -> None:
        assert find_catalog_entry_files(tmp_path) == []

    def test_empty_when_only_includes(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "repo-specs" / "remote.xml", _INCLUDE_XML)
        assert find_catalog_entry_files(tmp_path) == []

    def test_marker_only_in_comment_is_not_an_entry(self, tmp_path: Path) -> None:
        """A file whose only <catalog-metadata mention is inside an XML comment is not an entry."""
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            "<!-- this shared include has no <catalog-metadata> block -->\n"
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )
        assert find_catalog_entry_files(tmp_path) == []
