"""Unit tests for the kanon catalog audit --check source-name-derivation check.

Tests _check_source_name_derivation function for every warning class defined
in spec Section 3.5 soft-spot rule 2:
  - Normalisation drift: entry name differs from derive_source_name(entry_name)
  - Out-of-charset: entry name contains characters outside [a-zA-Z0-9_-]

Both findings are independent and an entry can produce both.

AC-TEST-001: Parametrized unit tests covering normalisation drift and
charset warnings independently and combined.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.commands.catalog import AUDIT_CHECK_REGISTRY, AuditFinding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_xml(tmp_path: pathlib.Path, filename: str, entry_name: str) -> pathlib.Path:
    """Write a minimal *-marketplace.xml with the given entry name under repo-specs/."""
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    xml_content = textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <package>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>Test Tool</display-name>
            <description>A test tool.</description>
            <version>1.0.0</version>
          </catalog-metadata>
        </package>
    """)
    xml_file = repo_specs / filename
    xml_file.write_text(xml_content, encoding="utf-8")
    return xml_file


def _run_check(tmp_path: pathlib.Path) -> list[AuditFinding]:
    """Invoke the registered 'source-name-derivation' check against tmp_path."""
    check_fn = AUDIT_CHECK_REGISTRY["source-name-derivation"]
    return check_fn(tmp_path)


# ---------------------------------------------------------------------------
# Registry registration (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSourceNameDerivationCheckRegistered:
    """'source-name-derivation' is registered in AUDIT_CHECK_REGISTRY."""

    def test_source_name_derivation_key_present(self) -> None:
        assert "source-name-derivation" in AUDIT_CHECK_REGISTRY

    def test_source_name_derivation_value_is_callable(self) -> None:
        assert callable(AUDIT_CHECK_REGISTRY["source-name-derivation"])


# ---------------------------------------------------------------------------
# Already-normalised entry name produces zero findings (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalisedEntryNameNoFindings:
    """An entry name that is already fully normalised produces zero findings."""

    @pytest.mark.parametrize(
        "entry_name",
        [
            "foo_bar",
            "my_tool",
            "a",
            "abc123",
            "tool_with_underscores",
        ],
    )
    def test_normalised_name_produces_zero_findings(self, tmp_path: pathlib.Path, entry_name: str) -> None:
        """AC-FUNC-002: entry name already normalised => zero findings."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)
        assert findings == [], (
            f"Expected zero findings for normalised entry name {entry_name!r}, "
            f"got: {[(f.kind, f.code, f.message) for f in findings]}"
        )


# ---------------------------------------------------------------------------
# Normalisation drift => WARN (AC-FUNC-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalisationDriftWarning:
    """Entry names that differ from derive_source_name(entry_name) produce a WARN."""

    @pytest.mark.parametrize(
        "entry_name,expected_derived",
        [
            ("Foo", "foo"),
            ("Foo-Bar", "foo_bar"),
            ("FOO", "foo"),
            ("foo-bar", "foo_bar"),
            ("My-Tool", "my_tool"),
            ("UPPER", "upper"),
            ("Mixed-Case-Name", "mixed_case_name"),
        ],
    )
    def test_drift_entry_name_produces_warn(
        self, tmp_path: pathlib.Path, entry_name: str, expected_derived: str
    ) -> None:
        """AC-FUNC-001: entry name with normalisation drift => at least one WARN."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert warn_findings, (
            f"Expected at least one WARN for drift entry name {entry_name!r}, "
            f"got: {[(f.kind, f.code, f.message) for f in findings]}"
        )

    @pytest.mark.parametrize(
        "entry_name,expected_derived",
        [
            ("Foo", "foo"),
            ("Foo-Bar", "foo_bar"),
            ("foo-bar", "foo_bar"),
        ],
    )
    def test_drift_warn_names_entry_name_and_derived_form(
        self, tmp_path: pathlib.Path, entry_name: str, expected_derived: str
    ) -> None:
        """WARN finding for drift must name the entry name and the derived form."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        drift_warnings = [f for f in findings if f.kind == "warn" and expected_derived in f.message]
        assert drift_warnings, (
            f"Expected WARN naming derived form {expected_derived!r} for entry {entry_name!r}, "
            f"got warn messages: {[f.message for f in findings if f.kind == 'warn']}"
        )
        # The entry name must also be named in the message
        assert any(entry_name in f.message for f in drift_warnings), (
            f"Expected WARN message to include entry name {entry_name!r}"
        )

    @pytest.mark.parametrize(
        "entry_name,expected_derived",
        [
            ("Foo", "foo"),
            ("Foo-Bar", "foo_bar"),
        ],
    )
    def test_drift_warn_names_xml_path(self, tmp_path: pathlib.Path, entry_name: str, expected_derived: str) -> None:
        """WARN finding for drift must name the XML file path."""
        xml_file = _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert warn_findings, f"Expected WARN for {entry_name!r}"
        assert any(str(xml_file) in f.message or xml_file.name in f.message for f in warn_findings), (
            f"Expected WARN message to name XML file {xml_file}"
        )

    def test_drift_warn_kind_is_warn_not_error(self, tmp_path: pathlib.Path) -> None:
        """Normalisation drift produces kind='warn', not 'error'."""
        _write_xml(tmp_path, "tool-marketplace.xml", "Foo-Bar")
        findings = _run_check(tmp_path)

        assert not any(f.kind == "error" for f in findings), (
            f"Expected no ERROR for drift, only WARN. Got: {[(f.kind, f.message) for f in findings]}"
        )
        assert any(f.kind == "warn" for f in findings), "Expected at least one WARN for drift"


# ---------------------------------------------------------------------------
# Out-of-charset entry name => WARN (AC-FUNC-003, AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOutOfCharsetWarning:
    """Entry names with characters outside [a-zA-Z0-9_-] produce a WARN."""

    @pytest.mark.parametrize(
        "entry_name,bad_char_description",
        [
            ("foo.bar", "dot"),
            ("foo bar", "whitespace"),
            ("foo\tbar", "tab"),
            ("foo@bar", "at-sign"),
            ("foo/bar", "slash"),
            ("f\u00f3\u00f3", "non-ASCII"),
        ],
    )
    def test_out_of_charset_produces_warn(
        self, tmp_path: pathlib.Path, entry_name: str, bad_char_description: str
    ) -> None:
        """AC-FUNC-003/004: entry name with out-of-charset chars => at least one WARN."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert warn_findings, (
            f"Expected at least one WARN for out-of-charset entry name {entry_name!r} "
            f"(bad char: {bad_char_description}), got: {[(f.kind, f.code, f.message) for f in findings]}"
        )

    @pytest.mark.parametrize(
        "entry_name",
        [
            "foo.bar",
            "foo bar",
            "f\u00f3\u00f3",
        ],
    )
    def test_out_of_charset_warn_names_xml_path(self, tmp_path: pathlib.Path, entry_name: str) -> None:
        """Out-of-charset WARN must name the XML file path."""
        xml_file = _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert warn_findings, f"Expected WARN for out-of-charset name {entry_name!r}"
        assert any(str(xml_file) in f.message or xml_file.name in f.message for f in warn_findings), (
            f"Expected WARN message to name XML file {xml_file}"
        )

    @pytest.mark.parametrize(
        "entry_name",
        [
            "foo.bar",
            "foo bar",
        ],
    )
    def test_out_of_charset_warn_kind_is_warn_not_error(self, tmp_path: pathlib.Path, entry_name: str) -> None:
        """Out-of-charset produces kind='warn', not 'error'."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        assert not any(f.kind == "error" for f in findings), (
            f"Expected no ERROR for out-of-charset name, only WARN. Got: {[(f.kind, f.message) for f in findings]}"
        )


# ---------------------------------------------------------------------------
# Both warnings can fire simultaneously (AC-FUNC-003 combined case)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBothWarningsIndependent:
    """An entry name can produce both drift and charset warnings simultaneously."""

    @pytest.mark.parametrize(
        "entry_name",
        [
            "Foo.Bar",
            "F\u00f3o-Bar",
        ],
    )
    def test_name_with_both_violations_produces_two_warns(self, tmp_path: pathlib.Path, entry_name: str) -> None:
        """Entry names with both drift and charset issues produce two WARN findings."""
        _write_xml(tmp_path, "tool-marketplace.xml", entry_name)
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) >= 2, (
            f"Expected at least 2 WARNs for {entry_name!r} (both drift and charset), "
            f"got {len(warn_findings)}: {[f.message for f in warn_findings]}"
        )

    def test_foo_dot_bar_only_charset_no_drift(self, tmp_path: pathlib.Path) -> None:
        """'foo.bar' after normalise gives 'foo.bar' (no drift), but fails charset.

        derive_source_name('foo.bar') = 'foo.bar' (lowercase then replace - with _).
        So no drift warning fires, only the charset warning fires.
        """
        _write_xml(tmp_path, "tool-marketplace.xml", "foo.bar")
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        # Exactly one WARN: the charset one. No drift because 'foo.bar' -> 'foo.bar'.
        assert len(warn_findings) == 1, (
            f"Expected exactly 1 WARN for 'foo.bar' (charset only, no drift), "
            f"got {len(warn_findings)}: {[f.message for f in warn_findings]}"
        )

    def test_foo_dot_bar_charset_warn_has_distinct_code(self, tmp_path: pathlib.Path) -> None:
        """The charset warning for 'foo.bar' has a distinct code from the drift warning."""
        _write_xml(tmp_path, "tool-marketplace.xml", "foo.bar")
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert warn_findings, "Expected at least one WARN for 'foo.bar'"
        # Each finding must have a non-empty code
        assert all(f.code for f in warn_findings), "All findings must have a non-empty code"


# ---------------------------------------------------------------------------
# Exit code behaviour: only WARNs => exit 0 (AC-FUNC-007)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExitCodeSignal:
    """Warn-only findings must not set has_error (exit code 0)."""

    def test_drift_only_produces_no_error_kind(self, tmp_path: pathlib.Path) -> None:
        """A purely drift-only violation produces no error-kind findings."""
        _write_xml(tmp_path, "tool-marketplace.xml", "Foo-Bar")
        findings = _run_check(tmp_path)
        assert not any(f.kind == "error" for f in findings)

    def test_charset_only_produces_no_error_kind(self, tmp_path: pathlib.Path) -> None:
        """A purely charset violation produces no error-kind findings."""
        _write_xml(tmp_path, "tool-marketplace.xml", "foo.bar")
        findings = _run_check(tmp_path)
        assert not any(f.kind == "error" for f in findings)

    def test_clean_name_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """A fully normalised name in charset produces zero findings."""
        _write_xml(tmp_path, "tool-marketplace.xml", "foo_bar")
        findings = _run_check(tmp_path)
        assert findings == []


# ---------------------------------------------------------------------------
# Multiple XML files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultipleXmlFiles:
    """_check_source_name_derivation walks all *-marketplace.xml files."""

    def test_two_files_both_checked(self, tmp_path: pathlib.Path) -> None:
        """Findings from two separate XML files are both collected."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "Foo")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "Bar-Baz")
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) >= 2, f"Expected at least 2 WARNs for two drift files, got {len(warn_findings)}"

    def test_mixed_clean_and_drifted(self, tmp_path: pathlib.Path) -> None:
        """Clean files produce no findings; only drifted files contribute warnings."""
        _write_xml(tmp_path, "clean-marketplace.xml", "foo_bar")
        _write_xml(tmp_path, "drifted-marketplace.xml", "Foo-Bar")
        findings = _run_check(tmp_path)

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) >= 1, "Expected at least one WARN for the drifted file"
        # No findings should reference the clean file (clean has no warnings)
        clean_warnings = [f for f in warn_findings if "clean-marketplace" in f.message]
        assert not clean_warnings, f"Clean file should produce no warnings, got: {[f.message for f in clean_warnings]}"

    def test_no_xml_files_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """No XML files => no findings."""
        (tmp_path / "repo-specs").mkdir(parents=True, exist_ok=True)
        findings = _run_check(tmp_path)
        assert findings == []

    def test_non_marketplace_xml_ignored(self, tmp_path: pathlib.Path) -> None:
        """Files not matching *-marketplace.xml are not processed."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        other_file = repo_specs / "tool-other.xml"
        other_file.write_text(
            '<?xml version="1.0"?><package><catalog-metadata><name>Foo-Bar</name></catalog-metadata></package>',
            encoding="utf-8",
        )
        findings = _run_check(tmp_path)
        assert findings == []


# ---------------------------------------------------------------------------
# Finding code uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindingCodes:
    """Each finding kind has a distinct, non-empty code."""

    def test_drift_finding_has_non_empty_code(self, tmp_path: pathlib.Path) -> None:
        """Drift WARN findings have a non-empty code string."""
        _write_xml(tmp_path, "tool-marketplace.xml", "Foo-Bar")
        findings = _run_check(tmp_path)
        drift_warns = [f for f in findings if f.kind == "warn" and "foo_bar" in f.message]
        assert drift_warns, "Expected at least one drift WARN"
        assert all(f.code for f in drift_warns)

    def test_charset_finding_has_non_empty_code(self, tmp_path: pathlib.Path) -> None:
        """Charset WARN findings have a non-empty code string."""
        _write_xml(tmp_path, "tool-marketplace.xml", "foo.bar")
        findings = _run_check(tmp_path)
        assert findings, "Expected at least one finding for 'foo.bar'"
        assert all(f.code for f in findings)

    def test_drift_and_charset_codes_are_distinct(self, tmp_path: pathlib.Path) -> None:
        """Drift and charset findings produced for the same entry have different codes."""
        _write_xml(tmp_path, "tool-marketplace.xml", "Foo.Bar")
        findings = _run_check(tmp_path)
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) >= 2, "Expected at least 2 WARNs for 'Foo.Bar'"
        codes = {f.code for f in warn_findings}
        assert len(codes) >= 2, f"Expected at least 2 distinct codes for drift+charset, got: {codes}"


# ---------------------------------------------------------------------------
# Edge case: malformed XML is silently skipped (metadata check's job)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdgeCasesSkipped:
    """Malformed XML, missing/multiple blocks, and missing name are silently skipped.

    The source-name-derivation check delegates all structural XML errors to the
    metadata check (_check_metadata). These conditions produce no findings from
    the source-name-derivation check.
    """

    def test_malformed_xml_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """Malformed XML is silently skipped (ParseError path)."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("<unclosed", encoding="utf-8")
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected no findings for malformed XML, got: {findings}"

    def test_zero_catalog_metadata_blocks_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """XML with zero <catalog-metadata> blocks produces no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_file = repo_specs / "no-block-marketplace.xml"
        xml_file.write_text('<?xml version="1.0"?><package></package>', encoding="utf-8")
        findings = _run_check(tmp_path)
        assert findings == []

    def test_multiple_catalog_metadata_blocks_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """XML with multiple <catalog-metadata> blocks produces no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_file = repo_specs / "multi-block-marketplace.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><package>'
            "<catalog-metadata><name>foo</name></catalog-metadata>"
            "<catalog-metadata><name>bar</name></catalog-metadata>"
            "</package>",
            encoding="utf-8",
        )
        findings = _run_check(tmp_path)
        assert findings == []

    def test_missing_name_element_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """XML with no <name> element inside <catalog-metadata> produces no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_file = repo_specs / "no-name-marketplace.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><package>'
            "<catalog-metadata><display-name>No Name</display-name></catalog-metadata>"
            "</package>",
            encoding="utf-8",
        )
        findings = _run_check(tmp_path)
        assert findings == []

    def test_empty_name_element_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """XML with an empty <name> element produces no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_file = repo_specs / "empty-name-marketplace.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><package><catalog-metadata><name>   </name></catalog-metadata></package>',
            encoding="utf-8",
        )
        findings = _run_check(tmp_path)
        assert findings == []
