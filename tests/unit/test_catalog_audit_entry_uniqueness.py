"""Unit tests for the kanon catalog audit --check entry-name-uniqueness check.

Tests _check_entry_name_uniqueness function for every collision pattern defined
in spec Section 3.5 soft-spot rule 3:
  - All unique names: zero findings.
  - Two files with the same name: one ERROR finding listing both paths.
  - Three files with the same name: one ERROR finding listing all three paths.
  - Two independent collision groups: two ERROR findings.
  - A file with a missing <name> element contributes nothing to uniqueness.

Comparison is case-sensitive: 'Foo' and 'foo' do NOT collide here.

AC-TEST-001: Parametrized unit tests covering the above scenarios.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.commands.catalog import AUDIT_CHECK_REGISTRY, AuditFinding


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


def _write_xml_no_name(tmp_path: pathlib.Path, filename: str) -> pathlib.Path:
    """Write a minimal *-marketplace.xml with no <name> element under repo-specs/."""
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    xml_content = textwrap.dedent("""\
        <?xml version="1.0"?>
        <package>
          <catalog-metadata>
            <display-name>No Name Tool</display-name>
            <description>A tool with no name element.</description>
            <version>1.0.0</version>
          </catalog-metadata>
        </package>
    """)
    xml_file = repo_specs / filename
    xml_file.write_text(xml_content, encoding="utf-8")
    return xml_file


def _run_check(tmp_path: pathlib.Path) -> list[AuditFinding]:
    """Invoke the registered 'entry-name-uniqueness' check against tmp_path."""
    check_fn = AUDIT_CHECK_REGISTRY["entry-name-uniqueness"]
    return check_fn(tmp_path)


@pytest.mark.unit
class TestEntryNameUniquenessCheckRegistered:
    """'entry-name-uniqueness' is registered in AUDIT_CHECK_REGISTRY."""

    def test_entry_name_uniqueness_key_present(self) -> None:
        assert "entry-name-uniqueness" in AUDIT_CHECK_REGISTRY

    def test_entry_name_uniqueness_value_is_callable(self) -> None:
        assert callable(AUDIT_CHECK_REGISTRY["entry-name-uniqueness"])


@pytest.mark.unit
class TestAllUniqueNamesProduceZeroFindings:
    """An audit target with all-unique entry names produces zero findings."""

    def test_single_file_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """A single XML file always has a unique name -- zero findings."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "tool_a")
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings for single file, got: {findings}"

    @pytest.mark.parametrize(
        "names",
        [
            ["alpha", "beta"],
            ["foo", "bar", "baz"],
            ["tool_x", "tool_y", "tool_z"],
            ["Foo", "foo"],
        ],
    )
    def test_all_distinct_names_produce_zero_findings(self, tmp_path: pathlib.Path, names: list[str]) -> None:
        """AC-FUNC-001 / AC-FUNC-006: all-distinct names (case-sensitive) produce zero findings."""
        for i, name in enumerate(names):
            _write_xml(tmp_path, f"tool-{i}-marketplace.xml", name)
        findings = _run_check(tmp_path)
        assert findings == [], (
            f"Expected zero findings for distinct names {names}, got: {[(f.kind, f.code, f.message) for f in findings]}"
        )

    def test_no_xml_files_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """No XML files => zero findings."""
        (tmp_path / "repo-specs").mkdir(parents=True, exist_ok=True)
        findings = _run_check(tmp_path)
        assert findings == []


@pytest.mark.unit
class TestTwoWayCollisionProducesOneError:
    """Two XML files with the same entry name produce exactly one ERROR finding."""

    def test_two_files_same_name_produce_exactly_one_finding(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: two files with the same name => exactly one ERROR finding."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "shared-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "shared-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR finding for two-way collision, "
            f"got {len(error_findings)}: {[(f.kind, f.code, f.message) for f in findings]}"
        )

    def test_two_files_same_name_finding_names_both_paths(self, tmp_path: pathlib.Path) -> None:
        """The single ERROR finding must name both XML file paths."""
        file_a = _write_xml(tmp_path, "tool-a-marketplace.xml", "shared-name")
        file_b = _write_xml(tmp_path, "tool-b-marketplace.xml", "shared-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        msg = error_findings[0].message
        assert str(file_a) in msg or file_a.name in msg, f"Expected finding to name path {file_a} but got: {msg}"
        assert str(file_b) in msg or file_b.name in msg, f"Expected finding to name path {file_b} but got: {msg}"

    def test_two_files_same_name_finding_names_colliding_name(self, tmp_path: pathlib.Path) -> None:
        """The ERROR finding must name the colliding entry name."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "my-tool")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "my-tool")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        assert "my-tool" in error_findings[0].message, (
            f"Expected finding to name 'my-tool', got: {error_findings[0].message}"
        )

    def test_two_files_same_name_finding_is_error_not_warn(self, tmp_path: pathlib.Path) -> None:
        """Uniqueness collisions produce kind='error', not 'warn'."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "shared-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "shared-name")
        findings = _run_check(tmp_path)
        assert all(f.kind == "error" for f in findings), (
            f"Expected all findings to be 'error', got: {[(f.kind, f.message) for f in findings]}"
        )

    @pytest.mark.parametrize("colliding_name", ["alpha", "my_tool", "Foo", "tool-x"])
    def test_two_files_same_name_parametrized(self, tmp_path: pathlib.Path, colliding_name: str) -> None:
        """AC-FUNC-002 parametrized: various colliding names each produce exactly one ERROR."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", colliding_name)
        _write_xml(tmp_path, "tool-b-marketplace.xml", colliding_name)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR for name {colliding_name!r}, got {len(error_findings)}"
        )
        assert colliding_name in error_findings[0].message, f"Expected finding to name {colliding_name!r}"


@pytest.mark.unit
class TestThreeWayCollisionProducesOneError:
    """Three XML files with the same entry name produce exactly one ERROR finding."""

    def test_three_files_same_name_produce_exactly_one_finding(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-003: three files with the same name => exactly one ERROR finding."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "triple-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "triple-name")
        _write_xml(tmp_path, "tool-c-marketplace.xml", "triple-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR finding for three-way collision, "
            f"got {len(error_findings)}: {[(f.kind, f.message) for f in findings]}"
        )

    def test_three_files_same_name_finding_names_all_three_paths(self, tmp_path: pathlib.Path) -> None:
        """The single ERROR finding must name all three XML file paths."""
        file_a = _write_xml(tmp_path, "tool-a-marketplace.xml", "triple-name")
        file_b = _write_xml(tmp_path, "tool-b-marketplace.xml", "triple-name")
        file_c = _write_xml(tmp_path, "tool-c-marketplace.xml", "triple-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        msg = error_findings[0].message
        assert str(file_a) in msg or file_a.name in msg, f"Expected finding to name {file_a} but got: {msg}"
        assert str(file_b) in msg or file_b.name in msg, f"Expected finding to name {file_b} but got: {msg}"
        assert str(file_c) in msg or file_c.name in msg, f"Expected finding to name {file_c} but got: {msg}"


@pytest.mark.unit
class TestTwoIndependentCollisionGroups:
    """Two independent collision groups produce two ERROR findings."""

    def test_two_groups_produce_exactly_two_error_findings(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-004: two independent collisions => exactly two ERROR findings."""
        _write_xml(tmp_path, "group-a-1-marketplace.xml", "name-a")
        _write_xml(tmp_path, "group-a-2-marketplace.xml", "name-a")
        _write_xml(tmp_path, "group-b-1-marketplace.xml", "name-b")
        _write_xml(tmp_path, "group-b-2-marketplace.xml", "name-b")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 2, (
            f"Expected exactly 2 ERROR findings for two collision groups, "
            f"got {len(error_findings)}: {[(f.kind, f.message) for f in findings]}"
        )

    def test_two_groups_each_finding_names_its_own_colliding_name(self, tmp_path: pathlib.Path) -> None:
        """Each ERROR finding names the entry name that collided."""
        _write_xml(tmp_path, "group-a-1-marketplace.xml", "name-a")
        _write_xml(tmp_path, "group-a-2-marketplace.xml", "name-a")
        _write_xml(tmp_path, "group-b-1-marketplace.xml", "name-b")
        _write_xml(tmp_path, "group-b-2-marketplace.xml", "name-b")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 2
        messages = {f.message for f in error_findings}
        name_a_in_any = any("name-a" in m for m in messages)
        name_b_in_any = any("name-b" in m for m in messages)
        assert name_a_in_any, f"Expected 'name-a' to appear in some ERROR finding: {messages}"
        assert name_b_in_any, f"Expected 'name-b' to appear in some ERROR finding: {messages}"

    def test_two_groups_findings_do_not_cross_reference(self, tmp_path: pathlib.Path) -> None:
        """Each ERROR finding only names the files that collide on that name."""
        file_a1 = _write_xml(tmp_path, "group-a-1-marketplace.xml", "name-a")
        file_a2 = _write_xml(tmp_path, "group-a-2-marketplace.xml", "name-a")
        file_b1 = _write_xml(tmp_path, "group-b-1-marketplace.xml", "name-b")
        file_b2 = _write_xml(tmp_path, "group-b-2-marketplace.xml", "name-b")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 2

        finding_a = next((f for f in error_findings if "name-a" in f.message), None)
        assert finding_a is not None, "Expected a finding for 'name-a'"
        assert str(file_a1) in finding_a.message or file_a1.name in finding_a.message
        assert str(file_a2) in finding_a.message or file_a2.name in finding_a.message
        assert file_b1.name not in finding_a.message, (
            f"'name-a' finding should not name group-b files but got: {finding_a.message}"
        )
        assert file_b2.name not in finding_a.message, (
            f"'name-a' finding should not name group-b files but got: {finding_a.message}"
        )


@pytest.mark.unit
class TestMissingNameIgnored:
    """An XML file with no parseable <name> element contributes nothing to uniqueness."""

    def test_missing_name_file_alone_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-005: a file with no <name> element alone produces zero uniqueness findings."""
        _write_xml_no_name(tmp_path, "no-name-marketplace.xml")
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero uniqueness findings for a file with no <name>, got: {findings}"

    def test_missing_name_file_does_not_collide_with_unique_file(self, tmp_path: pathlib.Path) -> None:
        """A file with no <name> plus a file with a unique name => zero uniqueness findings."""
        _write_xml_no_name(tmp_path, "no-name-marketplace.xml")
        _write_xml(tmp_path, "unique-marketplace.xml", "unique-tool")
        findings = _run_check(tmp_path)
        assert findings == [], (
            f"Expected zero uniqueness findings when missing-name + unique-name present, got: {findings}"
        )

    def test_missing_name_file_with_two_colliding_files_does_not_add_finding(self, tmp_path: pathlib.Path) -> None:
        """Missing-name file does not multiply collision findings."""
        _write_xml_no_name(tmp_path, "no-name-marketplace.xml")
        _write_xml(tmp_path, "tool-a-marketplace.xml", "shared-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "shared-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]

        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR (missing-name file must not add a collision), "
            f"got {len(error_findings)}: {[f.message for f in error_findings]}"
        )

    def test_malformed_xml_file_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """A malformed XML file contributes nothing to uniqueness (skipped silently)."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("<unclosed", encoding="utf-8")
        _write_xml(tmp_path, "good-marketplace.xml", "good-name")
        findings = _run_check(tmp_path)

        assert findings == [], (
            f"Expected zero uniqueness findings when malformed XML present with one good file, got: {findings}"
        )

    def test_zero_catalog_metadata_blocks_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """An XML file with zero <catalog-metadata> blocks contributes nothing to uniqueness."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        no_block_xml = repo_specs / "no-block-marketplace.xml"
        no_block_xml.write_text('<?xml version="1.0"?><package></package>', encoding="utf-8")
        _write_xml(tmp_path, "good-marketplace.xml", "good-name")
        findings = _run_check(tmp_path)
        assert findings == [], (
            f"Expected zero uniqueness findings when zero-block XML present with one good file, got: {findings}"
        )

    def test_multiple_catalog_metadata_blocks_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """An XML file with multiple <catalog-metadata> blocks contributes nothing to uniqueness."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        multi_xml = repo_specs / "multi-block-marketplace.xml"
        multi_xml.write_text(
            '<?xml version="1.0"?><package>'
            "<catalog-metadata><name>foo</name></catalog-metadata>"
            "<catalog-metadata><name>bar</name></catalog-metadata>"
            "</package>",
            encoding="utf-8",
        )
        _write_xml(tmp_path, "good-marketplace.xml", "good-name")
        findings = _run_check(tmp_path)
        assert findings == [], (
            f"Expected zero uniqueness findings when multi-block XML present with one good file, got: {findings}"
        )


@pytest.mark.unit
class TestCaseSensitiveComparison:
    """Uniqueness comparison is case-sensitive; 'Foo' and 'foo' do not collide."""

    @pytest.mark.parametrize(
        "name_a,name_b",
        [
            ("Foo", "foo"),
            ("FOO", "foo"),
            ("FOO", "Foo"),
            ("My-Tool", "my-tool"),
            ("ALPHA", "alpha"),
        ],
    )
    def test_differing_case_names_do_not_collide(self, tmp_path: pathlib.Path, name_a: str, name_b: str) -> None:
        """AC-FUNC-006: case-differing names are treated as distinct -- no collision."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", name_a)
        _write_xml(tmp_path, "tool-b-marketplace.xml", name_b)
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings == [], (
            f"Expected no ERROR findings for case-distinct names {name_a!r}/{name_b!r}, "
            f"got: {[(f.kind, f.code, f.message) for f in error_findings]}"
        )

    def test_exact_same_case_does_collide(self, tmp_path: pathlib.Path) -> None:
        """Two files with the EXACT same name (same case) do collide."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "MyTool")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "MyTool")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected exactly one ERROR for same-case name collision, "
            f"got {len(error_findings)}: {[f.message for f in error_findings]}"
        )


@pytest.mark.unit
class TestFindingAttributes:
    """Each uniqueness ERROR finding has a non-empty code and correct attributes."""

    def test_finding_has_non_empty_code(self, tmp_path: pathlib.Path) -> None:
        """Uniqueness ERROR findings have a non-empty code string."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "dup-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "dup-name")
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings, "Expected at least one ERROR finding"
        assert all(f.code for f in error_findings), "All ERROR findings must have a non-empty code"

    def test_finding_kind_is_error(self, tmp_path: pathlib.Path) -> None:
        """Uniqueness collisions produce kind='error'."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "dup-name")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "dup-name")
        findings = _run_check(tmp_path)
        assert all(f.kind == "error" for f in findings), (
            f"All findings must be 'error' kind, got: {[(f.kind, f.code) for f in findings]}"
        )

    def test_unique_names_produce_no_error_kind(self, tmp_path: pathlib.Path) -> None:
        """Unique names produce zero findings of any kind."""
        _write_xml(tmp_path, "tool-a-marketplace.xml", "alpha")
        _write_xml(tmp_path, "tool-b-marketplace.xml", "beta")
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings for unique names, got: {findings}"
