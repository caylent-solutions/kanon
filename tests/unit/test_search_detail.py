"""Unit tests for the --detail per-entry record formatter in kanon search.

Covers:
- Format of the per-entry record for a fully-populated CatalogMetadata.
- Missing recommended fields render as ``<missing>`` placeholder.
- Column-alignment: all field labels are right-padded to a fixed width.
- Output ordering mirrors lexicographic sort used by default mode.
- The formatter is decoupled from the walker (accepts CatalogMetadata instances).
- run_search() with detail=True emits the formatted records.
- register() exposes --detail on the list subparser with appropriate help text.

AC-TEST-001 (unit), AC-FUNC-001 through AC-FUNC-007.
"""

import argparse
import io
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.search import (
    _format_detail_record,
    register,
    run_search,
)
from kanon_cli.core.metadata import CatalogMetadata


def _full_metadata(name: str = "package-a") -> CatalogMetadata:
    """Return a fully-populated CatalogMetadata for testing."""
    return CatalogMetadata(
        name=name,
        display_name=f"{name} Display",
        description=f"Description of {name}.",
        version="1.4.2",
        type="library",
        owner_name="Test Owner",
        owner_email="owner@example.com",
        keywords=["test", "unit"],
    )


def _missing_type_metadata(name: str = "package-b") -> CatalogMetadata:
    """Return a CatalogMetadata with type=None (missing recommended field)."""
    return CatalogMetadata(
        name=name,
        display_name=f"{name} Display",
        description=f"Description of {name}.",
        version="2.0.0",
        type=None,
        owner_name=None,
        owner_email=None,
        keywords=[],
    )


@pytest.mark.unit
class TestFormatDetailRecord:
    """_format_detail_record() formats a single CatalogMetadata as a multi-line record."""

    def test_first_line_is_entry_name(self) -> None:
        """First line of the record is the entry name with no indent."""
        meta = _full_metadata("my-entry")
        record = _format_detail_record(meta)
        lines = record.splitlines()
        assert lines[0] == "my-entry"

    def test_contains_display_name(self) -> None:
        """Record contains the display-name field value."""
        meta = _full_metadata("my-entry")
        record = _format_detail_record(meta)
        assert "my-entry Display" in record

    def test_contains_description(self) -> None:
        """Record contains the description field value."""
        meta = _full_metadata("my-entry")
        record = _format_detail_record(meta)
        assert "Description of my-entry." in record

    def test_contains_version(self) -> None:
        """Record contains the version field value."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "1.4.2" in record

    def test_contains_type(self) -> None:
        """Record contains the type field value."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "library" in record

    def test_all_field_lines_have_two_space_indent(self) -> None:
        """Every field line (not the name line) starts with two spaces."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        lines = record.splitlines()

        for line in lines[1:]:
            assert line.startswith("  "), f"Line missing two-space indent: {line!r}"

    def test_field_labels_are_column_aligned(self) -> None:
        """All field label + ' : ' separators are at the same column position."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        lines = record.splitlines()

        colon_positions = []
        for line in lines[1:]:
            pos = line.find(" : ")
            assert pos != -1, f"No ' : ' separator found in line: {line!r}"
            colon_positions.append(pos)

        assert len(set(colon_positions)) == 1, (
            f"Field labels are not column-aligned; colon positions: {colon_positions}"
        )

    def test_display_name_label_present(self) -> None:
        """Record contains 'display-name' as a field label."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "display-name" in record

    def test_description_label_present(self) -> None:
        """Record contains 'description' as a field label."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "description" in record

    def test_version_label_present(self) -> None:
        """Record contains 'version' as a field label."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "version" in record

    def test_type_label_present(self) -> None:
        """Record contains 'type' as a field label."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        assert "type" in record

    def test_missing_type_renders_placeholder(self) -> None:
        """type=None renders as '<missing>' in the record."""
        meta = _missing_type_metadata()
        record = _format_detail_record(meta)
        assert "<missing>" in record

    def test_missing_type_does_not_crash(self) -> None:
        """_format_detail_record does not raise when type is None; result has name header."""
        meta = _missing_type_metadata("package-b")
        result = _format_detail_record(meta)
        lines = result.splitlines()

        assert lines[0] == "package-b", f"Expected name header 'package-b'; got {lines[0]!r}"

        assert len(lines) == 5, f"Expected 5 lines; got {len(lines)}: {lines}"

    def test_record_field_order_matches_spec(self) -> None:
        """Fields appear in spec order: display-name, description, version, type."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        lines = record.splitlines()
        field_lines = lines[1:]
        labels = []
        for line in field_lines:
            label = line.strip().split(" : ")[0].strip()
            labels.append(label)
        expected_order = ["display-name", "description", "version", "type"]
        assert labels == expected_order, f"Field order mismatch. Expected {expected_order}, got {labels}"

    def test_full_record_shape_matches_spec_example(self) -> None:
        """Record for a fully-populated entry matches the worked-example shape.

        From spec Section 2.1 step 2:
            package-a
              display-name : Package A
              description  : Example dependency
              version      : 1.4.2
              type         : library
        """
        meta = CatalogMetadata(
            name="package-a",
            display_name="Package A",
            description="Example dependency",
            version="1.4.2",
            type="library",
            owner_name="Owner",
            owner_email="owner@example.com",
            keywords=[],
        )
        record = _format_detail_record(meta)
        lines = record.splitlines()

        assert lines[0] == "package-a"

        field_lines = lines[1:]
        assert any("display-name" in ln and "Package A" in ln for ln in field_lines)
        assert any("description" in ln and "Example dependency" in ln for ln in field_lines)
        assert any("version" in ln and "1.4.2" in ln for ln in field_lines)
        assert any("type" in ln and "library" in ln for ln in field_lines)


@pytest.mark.unit
class TestFormatDetailRecordMissingFields:
    """_format_detail_record handles all combinations of missing recommended fields."""

    @pytest.mark.parametrize(
        "pkg_type",
        [None, "plugin", "library"],
    )
    def test_type_variants(self, pkg_type: str | None) -> None:
        """type field renders correctly for None, 'plugin', and 'library'."""
        meta = CatalogMetadata(
            name="test-entry",
            display_name="Test Entry",
            description="A test.",
            version="0.1.0",
            type=pkg_type,
        )
        record = _format_detail_record(meta)
        if pkg_type is None:
            assert "<missing>" in record
        else:
            assert pkg_type in record

    def test_record_five_lines_total(self) -> None:
        """Record has exactly 5 lines: name + 4 fields (display-name, description, version, type)."""
        meta = _full_metadata()
        record = _format_detail_record(meta)
        lines = record.splitlines()
        assert len(lines) == 5, f"Expected 5 lines; got {len(lines)}: {lines}"


@pytest.mark.unit
class TestRunListDetail:
    """run_search() with detail=True emits per-entry records in lexicographic order."""

    def _write_full_xml(self, directory: Path, name: str) -> None:
        """Write a minimal marketplace XML with all recommended fields."""
        directory.mkdir(parents=True, exist_ok=True)
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>{name}</name>
                <display-name>{name} Display</display-name>
                <description>Description of {name}.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Test Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
            </manifest>
        """)
        (directory / f"{name}-marketplace.xml").write_text(xml)

    def _write_partial_xml(self, directory: Path, name: str) -> None:
        """Write a minimal marketplace XML with type missing (triggers warning)."""
        directory.mkdir(parents=True, exist_ok=True)
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>{name}</name>
                <display-name>{name} Display</display-name>
                <description>Description of {name}.</description>
                <version>2.0.0</version>
              </catalog-metadata>
            </manifest>
        """)
        (directory / f"{name}-marketplace.xml").write_text(xml)

    def test_detail_flag_emits_multi_line_records(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search with detail=True emits more than one line per entry."""
        self._write_full_xml(tmp_path / "repo-specs", "alpha")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)
        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert result == 0
        assert len(lines) > 1, "detail mode should emit multiple lines"

    def test_detail_flag_emits_entry_name_as_header(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail emits entry name as the first line of each record."""
        self._write_full_xml(tmp_path / "repo-specs", "alpha")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines[0] == "alpha"

    def test_detail_flag_lexicographic_order(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail output is sorted lexicographically by entry name."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["zebra", "alpha", "mango"]:
            self._write_full_xml(repo_specs, name)
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()

        header_lines = [ln for ln in captured.out.splitlines() if ln and not ln.startswith(" ")]
        assert header_lines == ["alpha", "mango", "zebra"]

    def test_detail_flag_three_entries_three_records(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail emits one record per entry for a three-entry catalog."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["alpha", "beta", "gamma"]:
            self._write_full_xml(repo_specs, name)
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        header_lines = [ln for ln in captured.out.splitlines() if ln and not ln.startswith(" ")]
        assert sorted(header_lines) == ["alpha", "beta", "gamma"]

    def test_detail_missing_type_shows_placeholder(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail renders <missing> for entries with type=None."""
        self._write_partial_xml(tmp_path / "repo-specs", "partial-entry")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        assert "<missing>" in captured.out

    def test_detail_missing_type_warning_on_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail preserves stderr warning emitted by _parse_catalog_metadata."""
        self._write_partial_xml(tmp_path / "repo-specs", "partial-entry")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()

        assert "WARNING:" in captured.err

    def test_detail_missing_type_warning_not_duplicated(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail does not duplicate the recommended-field warning."""
        self._write_partial_xml(tmp_path / "repo-specs", "partial-entry")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        warning_count = captured.err.count("WARNING:")
        assert warning_count == 1, (
            f"Expected exactly one WARNING: on stderr; got {warning_count}. stderr: {captured.err!r}"
        )

    def test_detail_without_flag_uses_default_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search without detail=True uses the default one-name-per-line mode."""
        self._write_full_xml(tmp_path / "repo-specs", "my-entry")
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=False, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        lines = captured.out.splitlines()

        assert lines == ["my-entry"]

    def test_detail_empty_catalog_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --detail exits 0 for empty catalog (no records emitted)."""
        (tmp_path / "repo-specs").mkdir()
        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", detail=True, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)
        assert result == 0

    def test_detail_missing_catalog_source_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_search --detail exits non-zero when no catalog source is configured."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        args = argparse.Namespace(catalog_source=None, detail=True, no_color=False)
        result = run_search(args)
        assert result != 0


@pytest.mark.unit
class TestRegisterDetailFlag:
    """register() correctly exposes --detail on the list subparser."""

    def _build_list_parser(self) -> argparse.ArgumentParser:
        """Return the list subparser via register()."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        return subparsers.choices["search"]

    def test_detail_flag_registered(self) -> None:
        """'list --detail' parses without error and sets detail=True."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["search", "--detail"])
        assert args.detail is True

    def test_detail_defaults_to_false(self) -> None:
        """'list' without --detail sets detail=False."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["search"])
        assert args.detail is False

    def test_detail_help_mentions_human_readable(self) -> None:
        """--detail help text mentions 'human-readable'."""
        list_parser = self._build_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "human-readable" in help_text.lower()

    def test_detail_help_mentions_not_pipeable(self) -> None:
        """--detail help text notes it is not pipeable into kanon add."""
        list_parser = self._build_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "pipeable" in help_text.lower() or "pipe" in help_text.lower()

    def test_detail_help_mentions_format_json(self) -> None:
        """--detail help text mentions --format json for machine consumers."""
        list_parser = self._build_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--format json" in help_text or "format json" in help_text.lower()
