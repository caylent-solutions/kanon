"""Unit tests for the kanon catalog audit --check metadata implementation.

Tests _check_metadata function for every error class defined in spec Section 3.5
soft-spot rule 1:
  - Missing REQUIRED fields (name, display-name, description, version)
  - Missing RECOMMENDED fields (type, owner-name, owner-email, keywords)
  - Duplicate child elements within a single <catalog-metadata> block
  - Multiple <catalog-metadata> blocks in one XML file
  - Empty / whitespace-only values for REQUIRED fields

Also tests registration in the AUDIT_CHECK_REGISTRY, constant presence in
constants.py, and that a fully-valid XML produces zero findings.

AC-TEST-001: Parametrized unit tests covering every metadata error class.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.commands.catalog import AUDIT_CHECK_REGISTRY, AuditFinding
from kanon_cli.constants import (
    KANON_CATALOG_METADATA_RECOMMENDED_FIELDS,
    KANON_CATALOG_METADATA_REQUIRED_FIELDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_XML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <package>
      <catalog-metadata>
        <name>my-tool</name>
        <display-name>My Tool</display-name>
        <description>A useful tool.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Alice</owner-name>
        <owner-email>alice@example.com</owner-email>
        <keywords>infra,deploy</keywords>
      </catalog-metadata>
    </package>
""")


def _write_xml(tmp_path: pathlib.Path, filename: str, content: str) -> pathlib.Path:
    """Write *content* to ``tmp_path/repo-specs/<filename>``."""
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    xml_file = repo_specs / filename
    xml_file.write_text(content, encoding="utf-8")
    return xml_file


def _run_check(tmp_path: pathlib.Path) -> list[AuditFinding]:
    """Invoke the registered 'metadata' check against *tmp_path*."""
    check_fn = AUDIT_CHECK_REGISTRY["metadata"]
    return check_fn(tmp_path)


# ---------------------------------------------------------------------------
# Constants presence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadataConstants:
    """KANON_CATALOG_METADATA_REQUIRED_FIELDS and *_RECOMMENDED_FIELDS exist in constants."""

    def test_required_fields_is_tuple_or_sequence(self) -> None:
        assert KANON_CATALOG_METADATA_REQUIRED_FIELDS
        assert all(isinstance(f, str) for f in KANON_CATALOG_METADATA_REQUIRED_FIELDS)

    def test_required_fields_contains_expected_names(self) -> None:
        assert "name" in KANON_CATALOG_METADATA_REQUIRED_FIELDS
        assert "display-name" in KANON_CATALOG_METADATA_REQUIRED_FIELDS
        assert "description" in KANON_CATALOG_METADATA_REQUIRED_FIELDS
        assert "version" in KANON_CATALOG_METADATA_REQUIRED_FIELDS

    def test_required_fields_count_is_four(self) -> None:
        assert len(KANON_CATALOG_METADATA_REQUIRED_FIELDS) == 4

    def test_recommended_fields_is_tuple_or_sequence(self) -> None:
        assert KANON_CATALOG_METADATA_RECOMMENDED_FIELDS
        assert all(isinstance(f, str) for f in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS)

    def test_recommended_fields_contains_expected_names(self) -> None:
        assert "type" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS
        assert "owner-name" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS
        assert "owner-email" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS
        assert "keywords" in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS

    def test_recommended_fields_count_is_four(self) -> None:
        assert len(KANON_CATALOG_METADATA_RECOMMENDED_FIELDS) == 4

    def test_required_and_recommended_are_disjoint(self) -> None:
        required = set(KANON_CATALOG_METADATA_REQUIRED_FIELDS)
        recommended = set(KANON_CATALOG_METADATA_RECOMMENDED_FIELDS)
        assert required.isdisjoint(recommended)


# ---------------------------------------------------------------------------
# Registry registration (AC-FUNC-007)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadataCheckRegistered:
    """'metadata' is registered in AUDIT_CHECK_REGISTRY."""

    def test_metadata_key_present(self) -> None:
        assert "metadata" in AUDIT_CHECK_REGISTRY

    def test_metadata_value_is_callable(self) -> None:
        assert callable(AUDIT_CHECK_REGISTRY["metadata"])


# ---------------------------------------------------------------------------
# Valid XML produces zero findings (AC-FUNC-009)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidXmlProducesNoFindings:
    def test_fully_valid_xml_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        _write_xml(tmp_path, "tool-marketplace.xml", _VALID_XML)
        findings = _run_check(tmp_path)
        assert findings == []

    def test_no_xml_files_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """No XML files => no findings (nothing to audit)."""
        (tmp_path / "repo-specs").mkdir(parents=True, exist_ok=True)
        findings = _run_check(tmp_path)
        assert findings == []

    def test_non_marketplace_xml_ignored(self, tmp_path: pathlib.Path) -> None:
        """Files not matching *-marketplace.xml are not processed."""
        _write_xml(tmp_path, "tool-other.xml", _VALID_XML)
        findings = _run_check(tmp_path)
        assert findings == []


# ---------------------------------------------------------------------------
# Missing REQUIRED fields => ERROR (AC-FUNC-001, AC-FUNC-002)
# ---------------------------------------------------------------------------


def _xml_missing_required(field: str) -> str:
    """Return valid XML with exactly *field* removed from <catalog-metadata>."""
    mapping = {
        "name": "<name>my-tool</name>",
        "display-name": "<display-name>My Tool</display-name>",
        "description": "<description>A useful tool.</description>",
        "version": "<version>1.0.0</version>",
    }
    content = textwrap.dedent("""\
        <?xml version="1.0"?>
        <package>
          <catalog-metadata>
            <name>my-tool</name>
            <display-name>My Tool</display-name>
            <description>A useful tool.</description>
            <version>1.0.0</version>
            <type>plugin</type>
            <owner-name>Alice</owner-name>
            <owner-email>alice@example.com</owner-email>
            <keywords>infra</keywords>
          </catalog-metadata>
        </package>
    """)
    return content.replace(mapping[field] + "\n", "")


@pytest.mark.unit
class TestMissingRequiredField:
    """Missing each REQUIRED field produces one ERROR finding naming the field."""

    @pytest.mark.parametrize("field", ["name", "display-name", "description", "version"])
    def test_missing_required_field_produces_error(self, tmp_path: pathlib.Path, field: str) -> None:
        """AC-FUNC-001/002: missing a required field => exactly one ERROR naming the field."""
        _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_required(field))
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) >= 1, f"Expected at least one ERROR for missing {field!r}"

        field_findings = [f for f in error_findings if field in f.message]
        assert len(field_findings) == 1, (
            f"Expected exactly one ERROR naming {field!r}, got: {[f.message for f in error_findings]}"
        )

    @pytest.mark.parametrize("field", ["name", "display-name", "description", "version"])
    def test_missing_required_field_names_xml_path(self, tmp_path: pathlib.Path, field: str) -> None:
        """The ERROR finding names the XML file path."""
        xml_file = _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_required(field))
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error" and field in f.message]
        assert error_findings, f"No error finding for field {field!r}"
        assert str(xml_file) in error_findings[0].message or xml_file.name in error_findings[0].message

    def test_all_four_required_fields_missing_produces_four_errors(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: All four REQUIRED fields missing => four ERROR findings."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <type>plugin</type>
              </catalog-metadata>
            </package>
        """)
        _write_xml(tmp_path, "tool-marketplace.xml", xml)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 4, (
            f"Expected 4 ERRORs for 4 missing required fields, got {len(error_findings)}: "
            f"{[f.message for f in error_findings]}"
        )


# ---------------------------------------------------------------------------
# Missing RECOMMENDED fields => WARN (AC-FUNC-003)
# ---------------------------------------------------------------------------


def _xml_missing_recommended(field: str) -> str:
    """Return valid XML with exactly *field* removed from <catalog-metadata>."""
    mapping = {
        "type": "    <type>plugin</type>\n",
        "owner-name": "    <owner-name>Alice</owner-name>\n",
        "owner-email": "    <owner-email>alice@example.com</owner-email>\n",
        "keywords": "    <keywords>infra,deploy</keywords>\n",
    }
    return _VALID_XML.replace(mapping[field], "")


@pytest.mark.unit
class TestMissingRecommendedField:
    """Missing each RECOMMENDED field produces one WARN finding naming the field."""

    @pytest.mark.parametrize("field", ["type", "owner-name", "owner-email", "keywords"])
    def test_missing_recommended_field_produces_warn(self, tmp_path: pathlib.Path, field: str) -> None:
        """AC-FUNC-003: missing a recommended field => exactly one WARN naming the field."""
        _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_recommended(field))
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        field_warnings = [f for f in warn_findings if field in f.message]
        assert len(field_warnings) == 1, (
            f"Expected exactly one WARN naming {field!r}, got: {[f.message for f in warn_findings]}"
        )

    @pytest.mark.parametrize("field", ["type", "owner-name", "owner-email", "keywords"])
    def test_missing_recommended_field_names_xml_path(self, tmp_path: pathlib.Path, field: str) -> None:
        """The WARN finding names the XML file path."""
        xml_file = _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_recommended(field))
        findings = _run_check(tmp_path)
        warn_findings = [f for f in findings if f.kind == "warn" and field in f.message]
        assert warn_findings, f"No warn finding for field {field!r}"
        assert str(xml_file) in warn_findings[0].message or xml_file.name in warn_findings[0].message

    def test_all_four_recommended_fields_missing_produces_four_warns(self, tmp_path: pathlib.Path) -> None:
        """All four RECOMMENDED fields missing => four WARN findings."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _write_xml(tmp_path, "tool-marketplace.xml", xml)
        findings = _run_check(tmp_path)
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 4, (
            f"Expected 4 WARNs for 4 missing recommended fields, got {len(warn_findings)}: "
            f"{[f.message for f in warn_findings]}"
        )

    def test_missing_recommended_no_error_findings(self, tmp_path: pathlib.Path) -> None:
        """Missing only recommended fields must NOT produce any ERROR findings."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _write_xml(tmp_path, "tool-marketplace.xml", xml)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings == []


# ---------------------------------------------------------------------------
# Duplicate child elements => ERROR (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDuplicateChildElement:
    """Duplicate <name> or <description> within one <catalog-metadata> block => ERROR."""

    @pytest.mark.parametrize(
        "tag,extra_line",
        [
            ("name", "        <name>duplicate</name>"),
            ("description", "        <description>duplicate desc</description>"),
        ],
    )
    def test_duplicate_child_produces_error(self, tmp_path: pathlib.Path, tag: str, extra_line: str) -> None:
        """AC-FUNC-004: duplicate child tag => ERROR naming the XML path and tag."""
        xml = textwrap.dedent(f"""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
                {extra_line}
              </catalog-metadata>
            </package>
        """)
        xml_file = _write_xml(tmp_path, "dup-marketplace.xml", xml)
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        tag_errors = [f for f in error_findings if tag in f.message]
        assert tag_errors, f"Expected ERROR naming duplicate tag {tag!r}, got: {[f.message for f in error_findings]}"
        assert str(xml_file) in tag_errors[0].message or xml_file.name in tag_errors[0].message

    def test_duplicate_child_exactly_one_error(self, tmp_path: pathlib.Path) -> None:
        """Exactly one ERROR for a single duplicate child tag."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <name>duplicate-name</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _write_xml(tmp_path, "dup-marketplace.xml", xml)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error" and "name" in f.message]
        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR for duplicate <name>, got {len(error_findings)}: "
            f"{[f.message for f in error_findings]}"
        )


# ---------------------------------------------------------------------------
# Multiple <catalog-metadata> blocks => ERROR (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultipleCatalogMetadataBlocks:
    """Multiple <catalog-metadata> blocks in one file => ERROR naming path and count."""

    def test_two_blocks_produces_error(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-005: two <catalog-metadata> blocks => ERROR naming count."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
              </catalog-metadata>
              <catalog-metadata>
                <name>other-tool</name>
                <display-name>Other Tool</display-name>
                <description>Another tool.</description>
                <version>2.0.0</version>
              </catalog-metadata>
            </package>
        """)
        xml_file = _write_xml(tmp_path, "multi-marketplace.xml", xml)
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings, "Expected at least one ERROR for multiple <catalog-metadata> blocks"
        # Must name the count (2)
        count_errors = [f for f in error_findings if "2" in f.message]
        assert count_errors, f"Expected ERROR naming count '2', got: {[f.message for f in error_findings]}"
        assert str(xml_file) in count_errors[0].message or xml_file.name in count_errors[0].message

    def test_three_blocks_names_count_three(self, tmp_path: pathlib.Path) -> None:
        """Three <catalog-metadata> blocks => ERROR naming count 3."""
        block = textwrap.dedent("""\
              <catalog-metadata>
                <name>t</name>
                <display-name>T</display-name>
                <description>T desc.</description>
                <version>1.0.0</version>
              </catalog-metadata>
        """)
        xml = f'<?xml version="1.0"?>\n<package>\n{block}{block}{block}</package>\n'
        _write_xml(tmp_path, "three-marketplace.xml", xml)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        count_errors = [f for f in error_findings if "3" in f.message]
        assert count_errors, f"Expected ERROR naming count '3', got: {[f.message for f in error_findings]}"


# ---------------------------------------------------------------------------
# Malformed XML => ERROR with M003 (AC-TEST-001 full error-class coverage)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMalformedXml:
    """Malformed XML (parse failure) produces an ERROR finding with code M003."""

    @pytest.mark.parametrize(
        "bad_xml",
        [
            "<?xml version='1.0'?><package><unclosed>",
            "not xml at all",
            "<?xml version='1.0'?><a><b></a></b>",
        ],
    )
    def test_malformed_xml_produces_m003_error(self, tmp_path: pathlib.Path, bad_xml: str) -> None:
        """AC-TEST-001: malformed XML => exactly one ERROR with code M003."""
        _write_xml(tmp_path, "broken-marketplace.xml", bad_xml)
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings, "Expected at least one ERROR for malformed XML"
        m003_findings = [f for f in error_findings if f.code == "M003"]
        assert len(m003_findings) == 1, (
            f"Expected exactly one ERROR with code M003 for malformed XML, "
            f"got: {[(f.code, f.message) for f in error_findings]}"
        )

    def test_malformed_xml_message_names_file(self, tmp_path: pathlib.Path) -> None:
        """M003 finding message must name the XML file path."""
        xml_file = _write_xml(tmp_path, "broken-marketplace.xml", "<unclosed")
        findings = _run_check(tmp_path)
        m003_findings = [f for f in findings if f.code == "M003"]
        assert m003_findings, "Expected M003 finding for malformed XML"
        assert str(xml_file) in m003_findings[0].message or xml_file.name in m003_findings[0].message


# ---------------------------------------------------------------------------
# Zero <catalog-metadata> blocks => ERROR with M004 (AC-TEST-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestZeroCatalogMetadataBlocks:
    """XML with no <catalog-metadata> block produces an ERROR with code M004."""

    @pytest.mark.parametrize(
        "xml",
        [
            "<?xml version='1.0'?><package></package>",
            "<?xml version='1.0'?><package><other-block><name>x</name></other-block></package>",
            "<?xml version='1.0'?><root/>",
        ],
    )
    def test_no_catalog_metadata_block_produces_m004(self, tmp_path: pathlib.Path, xml: str) -> None:
        """AC-TEST-001: zero <catalog-metadata> blocks => exactly one ERROR with code M004."""
        _write_xml(tmp_path, "empty-blocks-marketplace.xml", xml)
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings, "Expected at least one ERROR for missing <catalog-metadata> block"
        m004_findings = [f for f in error_findings if f.code == "M004"]
        assert len(m004_findings) == 1, (
            f"Expected exactly one ERROR with code M004 for zero blocks, "
            f"got: {[(f.code, f.message) for f in error_findings]}"
        )

    def test_no_catalog_metadata_message_names_file(self, tmp_path: pathlib.Path) -> None:
        """M004 finding message must name the XML file path."""
        xml_file = _write_xml(tmp_path, "empty-blocks-marketplace.xml", "<?xml version='1.0'?><package/>")
        findings = _run_check(tmp_path)
        m004_findings = [f for f in findings if f.code == "M004"]
        assert m004_findings, "Expected M004 finding for zero <catalog-metadata> blocks"
        assert str(xml_file) in m004_findings[0].message or xml_file.name in m004_findings[0].message


# ---------------------------------------------------------------------------
# Empty / whitespace-only REQUIRED fields => ERROR (AC-FUNC-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyRequiredField:
    """Empty or whitespace-only REQUIRED fields => ERROR (treated as missing)."""

    @pytest.mark.parametrize(
        "field,empty_element",
        [
            ("name", "<name></name>"),
            ("name", "<name>   </name>"),
            ("description", "<description>  </description>"),
            ("version", "<version></version>"),
            ("display-name", "<display-name>\t</display-name>"),
        ],
    )
    def test_empty_or_whitespace_required_produces_error(
        self, tmp_path: pathlib.Path, field: str, empty_element: str
    ) -> None:
        """AC-FUNC-006: empty/whitespace required field => ERROR for that field."""
        # Build XML replacing the normal field value with the empty/whitespace element.
        replacement_map = {
            "name": "    <name>my-tool</name>",
            "display-name": "    <display-name>My Tool</display-name>",
            "description": "    <description>A useful tool.</description>",
            "version": "    <version>1.0.0</version>",
        }
        xml = _VALID_XML.replace(
            replacement_map[field],
            "    " + empty_element,
        )
        _write_xml(tmp_path, "empty-marketplace.xml", xml)
        findings = _run_check(tmp_path)

        error_findings = [f for f in findings if f.kind == "error"]
        field_errors = [f for f in error_findings if field in f.message]
        assert field_errors, (
            f"Expected ERROR naming field {field!r} for empty/whitespace element, "
            f"got: {[f.message for f in error_findings]}"
        )


# ---------------------------------------------------------------------------
# Exit code: ERROR => non-zero, only WARN => zero (AC-FUNC-010)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckMetadataExitCodeSignal:
    """Check that error vs warn finding kind drives the exit code signal.

    AC-FUNC-010: kanon catalog audit --check metadata exits non-zero when any
    ERROR finding is present; exits 0 when only WARN findings are present.
    audit_command uses the has_error flag from findings.
    This test verifies _check_metadata returns findings with the correct kind,
    so audit_command can drive exit code correctly.
    """

    def test_missing_required_returns_error_kind(self, tmp_path: pathlib.Path) -> None:
        """A missing required field produces kind='error' (not warn)."""
        _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_required("name"))
        findings = _run_check(tmp_path)
        assert any(f.kind == "error" for f in findings)

    def test_missing_recommended_returns_warn_kind(self, tmp_path: pathlib.Path) -> None:
        """A missing recommended field produces kind='warn' (not error)."""
        _write_xml(tmp_path, "tool-marketplace.xml", _xml_missing_recommended("type"))
        findings = _run_check(tmp_path)
        assert any(f.kind == "warn" for f in findings)
        assert not any(f.kind == "error" for f in findings)


# ---------------------------------------------------------------------------
# Multiple XML files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultipleXmlFiles:
    """_check_metadata walks all *-marketplace.xml files under repo-specs/."""

    def test_two_files_both_checked(self, tmp_path: pathlib.Path) -> None:
        """Findings from two separate XML files are both collected."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", _xml_missing_required("name"))
        _write_xml(tmp_path, "tool-b-marketplace.xml", _xml_missing_required("version"))
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        # At least one for each file
        assert len(error_findings) >= 2

    def test_mixed_valid_and_invalid(self, tmp_path: pathlib.Path) -> None:
        """Valid files produce no findings; only invalid files contribute findings."""
        _write_xml(tmp_path, "good-marketplace.xml", _VALID_XML)
        _write_xml(tmp_path, "bad-marketplace.xml", _xml_missing_required("description"))
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) >= 1
        assert all("bad-marketplace.xml" in f.message or "bad-marketplace" in f.message for f in error_findings)
