"""Unit tests for ``kanon list --format json``.

Covers AC-TEST-001:
- JSON shape for default mode: array of {name, display-name, type, description, version}
- JSON shape for --all-versions mode: array of {name, version, ref, sha}
- --detail mode with --format json emits the same shape as default mode
- KANON_LIST_FORMAT env var sets the format when CLI flag is absent
- CLI flag takes precedence over KANON_LIST_FORMAT env var
- --format json --tree mutual exclusion (hard error at argparse-validation time)
- Empty catalog with --format json emits [] to stdout, stderr note, exit 0
- JSON output is a single document terminated by exactly one newline
"""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.list import (
    _build_all_versions_payload,
    _build_catalog_payload,
    _format_json_all_versions,
    _format_json_catalog,
    register,
    run_list,
)
from kanon_cli.commands.list import VersionRow
from kanon_cli.core.metadata import CatalogMetadata


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for run_list().

    list_format defaults to None (same as argparse default) so that run_list
    resolves the effective format via its env-var precedence logic. Pass
    list_format="names" or list_format="json" to simulate an explicit CLI flag.
    """
    defaults = {
        "catalog_source": None,
        "detail": False,
        "tree": False,
        "max_depth": None,
        "no_filter_required": False,
        "all_versions": False,
        "limit": 50,
        "no_limit": False,
        "since_version": None,
        "list_format": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Tests for _format_json_catalog (default + detail mode JSON renderer)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatJsonCatalog:
    """AC-FUNC-003: JSON array of {name, display-name, type, description, version}."""

    def test_single_entry_shape(self):
        """Each object has exactly the five specified keys."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        obj = parsed[0]
        assert set(obj.keys()) == {"name", "display-name", "type", "description", "version"}

    def test_name_field_value(self):
        """'name' field matches the catalog entry name."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["name"] == "alpha"

    def test_display_name_field_value(self):
        """'display-name' field matches the display_name attribute."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["display-name"] == "alpha Display"

    def test_type_field_value(self):
        """'type' field matches the type attribute."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["type"] == "library"

    def test_description_field_value(self):
        """'description' field matches the description attribute."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["description"] == "Description of alpha."

    def test_version_field_value(self):
        """'version' field matches the version attribute."""
        metadata = _full_metadata("alpha")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["version"] == "1.4.2"

    def test_multiple_entries_produces_array(self):
        """Multiple entries produce a multi-element JSON array."""
        entries = [_full_metadata("alpha"), _full_metadata("beta")]
        result = _format_json_catalog(entries)
        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_entry_ordering_is_preserved(self):
        """The JSON array preserves the order of the input list."""
        entries = [_full_metadata("alpha"), _full_metadata("beta")]
        result = _format_json_catalog(entries)
        parsed = json.loads(result)
        assert parsed[0]["name"] == "alpha"
        assert parsed[1]["name"] == "beta"

    def test_empty_list_produces_empty_json_array(self):
        """Empty input produces an empty JSON array '[]'."""
        result = _format_json_catalog([])
        parsed = json.loads(result)
        assert parsed == []

    def test_output_ends_with_exactly_one_newline(self):
        """AC-FUNC-008: output ends with exactly one newline."""
        result = _format_json_catalog([_full_metadata()])
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_output_is_valid_json(self):
        """json.loads must succeed without raising ValueError."""
        result = _format_json_catalog([_full_metadata()])
        json.loads(result)  # raises on invalid JSON

    @pytest.mark.parametrize(
        "name,expected_name",
        [
            ("alpha", "alpha"),
            ("my-lib", "my-lib"),
            ("tool_x", "tool_x"),
        ],
    )
    def test_parametrized_name_values(self, name: str, expected_name: str):
        """Name values are passed through verbatim."""
        metadata = _full_metadata(name)
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["name"] == expected_name

    def test_null_type_is_serialised_as_null(self):
        """When type is None, the JSON field is null (not the string '<missing>')."""
        metadata = _missing_type_metadata("package-b")
        result = _format_json_catalog([metadata])
        parsed = json.loads(result)
        assert parsed[0]["type"] is None


# ---------------------------------------------------------------------------
# Tests for _format_json_all_versions (--all-versions JSON renderer)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatJsonAllVersions:
    """AC-FUNC-005: JSON array of {name, version, ref, sha}."""

    def test_single_row_shape(self):
        """Each object has exactly the four specified keys."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert set(parsed[0].keys()) == {"name", "version", "ref", "sha"}

    def test_name_field_value(self):
        """'name' maps to VersionRow.name."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert parsed[0]["name"] == "alpha"

    def test_version_field_value(self):
        """'version' maps to VersionRow.version."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert parsed[0]["version"] == "1.0.0"

    def test_ref_field_value(self):
        """'ref' maps to VersionRow.ref."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert parsed[0]["ref"] == "refs/tags/1.0.0"

    def test_sha_field_value(self):
        """'sha' maps to VersionRow.sha."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert parsed[0]["sha"] == "abc123"

    def test_multiple_rows_produce_array(self):
        """Multiple rows produce a multi-element array."""
        rows = [
            VersionRow(name="alpha", version="2.0.0", ref="refs/tags/2.0.0", sha="sha2"),
            VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="sha1"),
        ]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_empty_rows_produces_empty_array(self):
        """Empty input produces '[]'."""
        result = _format_json_all_versions([])
        parsed = json.loads(result)
        assert parsed == []

    def test_output_ends_with_exactly_one_newline(self):
        """AC-FUNC-008: output ends with exactly one newline."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_output_is_valid_json(self):
        """json.loads must succeed without raising ValueError."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc123")]
        result = _format_json_all_versions(rows)
        json.loads(result)

    @pytest.mark.parametrize(
        "sha",
        ["abc123456789", "", "0" * 40],
    )
    def test_sha_field_values_parametrized(self, sha: str):
        """SHA field passes through any string value including empty."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha=sha)]
        result = _format_json_all_versions(rows)
        parsed = json.loads(result)
        assert parsed[0]["sha"] == sha


# ---------------------------------------------------------------------------
# Tests for register() -- --format flag is registered on the subparser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterFormatFlag:
    """AC-FUNC-001: --format flag registered with choices and default."""

    def test_format_flag_default_is_none_sentinel(self):
        """--format default is None when the flag is absent (env-var precedence requires None)."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        args = top.parse_args(["list", "--catalog-source", "x@main"])
        # Default is None so run_list can distinguish "not set" from explicit "names"
        assert args.list_format is None

    def test_format_flag_accepts_names(self):
        """--format names is accepted."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        args = top.parse_args(["list", "--format", "names", "--catalog-source", "x@main"])
        assert args.list_format == "names"

    def test_format_flag_accepts_json(self):
        """--format json is accepted."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        args = top.parse_args(["list", "--format", "json", "--catalog-source", "x@main"])
        assert args.list_format == "json"

    def test_format_flag_rejects_unknown_choice(self):
        """--format <unknown> is rejected by argparse."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        with pytest.raises(SystemExit) as exc_info:
            top.parse_args(["list", "--format", "csv", "--catalog-source", "x@main"])
        assert exc_info.value.code != 0

    def test_help_mentions_format_flag(self, capsys):
        """--help text includes --format."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        with pytest.raises(SystemExit):
            top.parse_args(["list", "--help"])
        captured = capsys.readouterr()
        assert "--format" in captured.out

    def test_help_mentions_kanon_list_format_env_var(self, capsys):
        """--help text mentions KANON_LIST_FORMAT env var."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        with pytest.raises(SystemExit):
            top.parse_args(["list", "--help"])
        captured = capsys.readouterr()
        assert "KANON_LIST_FORMAT" in captured.out

    def test_help_mentions_format_json_tree_mutual_exclusion(self, capsys):
        """--help text mentions --format json --tree mutual exclusion."""
        top = argparse.ArgumentParser()
        subs = top.add_subparsers()
        register(subs)
        with pytest.raises(SystemExit):
            top.parse_args(["list", "--help"])
        captured = capsys.readouterr()
        # The help must mention the incompatibility with --tree
        assert "--tree" in captured.out
        assert "json" in captured.out


# ---------------------------------------------------------------------------
# Tests for env var KANON_LIST_FORMAT
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvVarListFormat:
    """AC-FUNC-002: KANON_LIST_FORMAT env var and CLI flag precedence."""

    def test_env_var_sets_json_format_when_flag_absent(self, tmp_path: Path, capsys):
        """KANON_LIST_FORMAT=json produces JSON output when --format is absent."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_path = repo_specs / "alpha-marketplace.xml"
        xml_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Alpha desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>Tester</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>test</keywords>"
            "</catalog-metadata></manifest>"
        )

        # list_format=None simulates "flag absent from CLI"
        args = _make_args(catalog_source="file:///unused@main", list_format=None)

        with (
            patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path),
            patch.dict("os.environ", {"KANON_LIST_FORMAT": "json"}),
        ):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "alpha"

    def test_cli_flag_takes_precedence_over_env_var(self, tmp_path: Path, capsys):
        """CLI --format names wins over KANON_LIST_FORMAT=json."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_path = repo_specs / "alpha-marketplace.xml"
        xml_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Alpha desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>Tester</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>test</keywords>"
            "</catalog-metadata></manifest>"
        )

        # list_format="names" simulates explicit CLI --format names flag
        args = _make_args(catalog_source="file:///unused@main", list_format="names")

        with (
            patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path),
            patch.dict("os.environ", {"KANON_LIST_FORMAT": "json"}),
        ):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        # names format: one line per entry, ending with newline
        lines = captured.out.strip().splitlines()
        assert lines == ["alpha"]
        # Must NOT be valid JSON array of dicts
        try:
            parsed = json.loads(captured.out)
            assert not (isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict))
        except json.JSONDecodeError:
            pass  # Not JSON -- correct for names format


# ---------------------------------------------------------------------------
# Tests for --format json --tree mutual exclusion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatJsonTreeMutualExclusion:
    """AC-FUNC-006: --format json --tree is a hard error."""

    def test_format_json_with_tree_exits_nonzero(self, capsys):
        """run_list exits with code 1 when --format json and --tree are combined."""
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            tree=True,
        )
        exit_code = run_list(args)
        assert exit_code == 1

    def test_format_json_with_tree_prints_error_to_stderr(self, capsys):
        """The mutual-exclusion error message is printed to stderr."""
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            tree=True,
        )
        run_list(args)
        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "json" in captured.err.lower() or "format" in captured.err.lower()
        assert "--tree" in captured.err or "tree" in captured.err.lower()

    def test_format_json_tree_error_has_no_stdout(self, capsys):
        """The mutual-exclusion error produces no stdout output."""
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            tree=True,
        )
        run_list(args)
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# Tests for empty catalog + --format json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyCatalogJsonFormat:
    """AC-FUNC-007: empty catalog with --format json emits [] and exits 0."""

    def test_empty_catalog_emits_empty_json_array(self, tmp_path: Path, capsys):
        """Empty manifest repo produces '[]' on stdout."""
        # Create an empty repo-specs dir (no XML files)
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_args(catalog_source="file:///unused@main", list_format="json")

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == []

    def test_empty_catalog_emits_stderr_note(self, tmp_path: Path, capsys):
        """Empty manifest repo with JSON format still emits the stderr note."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_args(catalog_source="file:///unused@main", list_format="json")

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args)

        captured = capsys.readouterr()
        assert "0 entries" in captured.err

    def test_empty_catalog_all_versions_json_emits_empty_array(self, tmp_path: Path, capsys):
        """Empty all-versions with JSON format emits [] and stderr note."""
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            all_versions=True,
        )

        with patch("kanon_cli.commands.list._walk_all_versions", return_value=[]):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == []


# ---------------------------------------------------------------------------
# Tests for run_list() with --format json default mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListJsonDefaultMode:
    """AC-FUNC-003: run_list with json format in default mode."""

    def test_json_output_parseable(self, tmp_path: Path, capsys):
        """run_list --format json produces parseable JSON on stdout."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Alpha desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>Tester</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>test</keywords>"
            "</catalog-metadata></manifest>"
        )
        (repo_specs / "alpha-marketplace.xml").write_text(xml_content)

        args = _make_args(catalog_source="file:///unused@main", list_format="json")

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "alpha"

    def test_json_output_has_correct_shape(self, tmp_path: Path, capsys):
        """Each element has {name, display-name, type, description, version}."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha Lib</display-name>"
            "<description>The alpha lib.</description><version>2.3.1</version>"
            "<type>library</type><owner-name>Tester</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>test</keywords>"
            "</catalog-metadata></manifest>"
        )
        (repo_specs / "alpha-marketplace.xml").write_text(xml_content)

        args = _make_args(catalog_source="file:///unused@main", list_format="json")

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        obj = parsed[0]
        assert obj["name"] == "alpha"
        assert obj["display-name"] == "Alpha Lib"
        assert obj["description"] == "The alpha lib."
        assert obj["version"] == "2.3.1"
        assert obj["type"] == "library"


# ---------------------------------------------------------------------------
# Tests for run_list() with --format json --detail (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListJsonDetailMode:
    """AC-FUNC-004: --format json --detail emits the same shape as default mode."""

    def test_detail_json_same_shape_as_default_json(self, tmp_path: Path, capsys):
        """--detail flag does not change the JSON shape when --format json is set."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>Owner</owner-name>"
            "<owner-email>o@e.com</owner-email><keywords>k</keywords>"
            "</catalog-metadata></manifest>"
        )
        (repo_specs / "alpha-marketplace.xml").write_text(xml_content)

        args_default = _make_args(catalog_source="file:///unused@main", list_format="json", detail=False)
        args_detail = _make_args(catalog_source="file:///unused@main", list_format="json", detail=True)

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args_default)
            captured_default = capsys.readouterr()

        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args_detail)
            captured_detail = capsys.readouterr()

        parsed_default = json.loads(captured_default.out)
        parsed_detail = json.loads(captured_detail.out)
        assert parsed_default == parsed_detail


# ---------------------------------------------------------------------------
# Tests for run_list() with --format json --all-versions (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListJsonAllVersionsMode:
    """AC-FUNC-005: --format json --all-versions emits {name, version, ref, sha} array."""

    def test_all_versions_json_shape(self, capsys):
        """--all-versions --format json produces array of {name, version, ref, sha}."""
        rows = [
            VersionRow(name="alpha", version="2.0.0", ref="refs/tags/2.0.0", sha="sha2abc"),
            VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="sha1abc"),
        ]
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            all_versions=True,
        )

        with patch("kanon_cli.commands.list._walk_all_versions", return_value=rows):
            exit_code = run_list(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 2
        assert set(parsed[0].keys()) == {"name", "version", "ref", "sha"}

    def test_all_versions_json_field_values(self, capsys):
        """Field values in the --all-versions JSON output match VersionRow attributes."""
        rows = [
            VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="deadbeef1234"),
        ]
        args = _make_args(
            catalog_source="file:///unused@main",
            list_format="json",
            all_versions=True,
        )

        with patch("kanon_cli.commands.list._walk_all_versions", return_value=rows):
            run_list(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed[0]["name"] == "alpha"
        assert parsed[0]["version"] == "1.0.0"
        assert parsed[0]["ref"] == "refs/tags/1.0.0"
        assert parsed[0]["sha"] == "deadbeef1234"


# ---------------------------------------------------------------------------
# Tests for invalid KANON_LIST_FORMAT env var value (fail-fast, AC-FAIL-FAST-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvalidEnvVarListFormat:
    """AC-FAIL-FAST-001: invalid KANON_LIST_FORMAT value must error, not fall through."""

    def test_invalid_env_var_returns_exit_code_1(self, capsys):
        """run_list returns 1 when KANON_LIST_FORMAT is set to an unrecognized value."""
        args = _make_args(catalog_source="file:///unused@main", list_format=None)
        with patch.dict("os.environ", {"KANON_LIST_FORMAT": "csv"}):
            exit_code = run_list(args)
        assert exit_code == 1

    def test_invalid_env_var_prints_error_to_stderr(self, capsys):
        """run_list prints an ERROR message to stderr for an invalid KANON_LIST_FORMAT value."""
        args = _make_args(catalog_source="file:///unused@main", list_format=None)
        with patch.dict("os.environ", {"KANON_LIST_FORMAT": "csv"}):
            run_list(args)
        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "KANON_LIST_FORMAT" in captured.err

    def test_invalid_env_var_no_stdout(self, capsys):
        """run_list produces no stdout output when KANON_LIST_FORMAT is invalid."""
        args = _make_args(catalog_source="file:///unused@main", list_format=None)
        with patch.dict("os.environ", {"KANON_LIST_FORMAT": "xml"}):
            run_list(args)
        captured = capsys.readouterr()
        assert captured.out == ""

    @pytest.mark.parametrize("bad_value", ["csv", "xml", "table", "pretty", "NAMES", "JSON", ""])
    def test_invalid_env_var_various_bad_values(self, capsys, bad_value):
        """Any value that is not 'names' or 'json' (case-sensitive) triggers exit 1."""
        args = _make_args(catalog_source="file:///unused@main", list_format=None)
        with patch.dict("os.environ", {"KANON_LIST_FORMAT": bad_value}):
            exit_code = run_list(args)
        assert exit_code == 1

    def test_invalid_env_var_error_mentions_valid_choices(self, capsys):
        """The error message names the valid choices ('names', 'json')."""
        args = _make_args(catalog_source="file:///unused@main", list_format=None)
        with patch.dict("os.environ", {"KANON_LIST_FORMAT": "table"}):
            run_list(args)
        captured = capsys.readouterr()
        assert "names" in captured.err
        assert "json" in captured.err


# ---------------------------------------------------------------------------
# Tests for _KANON_LIST_FORMAT_ENV_VAR private inline constant in list.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFormatEnvVarConstant:
    """AC-CONST-001: _KANON_LIST_FORMAT_ENV_VAR private constant is defined inline in list.py."""

    def test_list_format_env_var_exists_inline_in_list_module(self):
        """_KANON_LIST_FORMAT_ENV_VAR is defined as a private module-level constant in list.py."""
        import kanon_cli.commands.list as list_module

        assert hasattr(list_module, "_KANON_LIST_FORMAT_ENV_VAR")

    def test_list_format_env_var_value_is_correct(self):
        """_KANON_LIST_FORMAT_ENV_VAR equals 'KANON_LIST_FORMAT'."""
        import kanon_cli.commands.list as list_module

        assert list_module._KANON_LIST_FORMAT_ENV_VAR == "KANON_LIST_FORMAT"

    def test_list_format_env_var_is_string(self):
        """_KANON_LIST_FORMAT_ENV_VAR is a str."""
        import kanon_cli.commands.list as list_module

        assert isinstance(list_module._KANON_LIST_FORMAT_ENV_VAR, str)


# ---------------------------------------------------------------------------
# Tests verifying _build_catalog_payload and _build_all_versions_payload helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildCatalogPayload:
    """_build_catalog_payload returns a list of dicts consumed by _emit_json_payload."""

    def test_single_entry_has_five_keys(self):
        """Each element has exactly the five spec-canonical keys."""
        metadata = _full_metadata("alpha")
        payload = _build_catalog_payload([metadata])
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert set(payload[0].keys()) == {"name", "display-name", "type", "description", "version"}

    def test_values_match_metadata_fields(self):
        """Field values match the CatalogMetadata attributes."""
        metadata = _full_metadata("alpha")
        payload = _build_catalog_payload([metadata])
        obj = payload[0]
        assert obj["name"] == "alpha"
        assert obj["display-name"] == "alpha Display"
        assert obj["type"] == "library"
        assert obj["description"] == "Description of alpha."
        assert obj["version"] == "1.4.2"

    def test_empty_input_produces_empty_list(self):
        """Empty entry list produces an empty payload list."""
        assert _build_catalog_payload([]) == []

    def test_none_type_serialises_as_none(self):
        """None type is preserved (serialises to JSON null)."""
        metadata = _missing_type_metadata("b")
        payload = _build_catalog_payload([metadata])
        assert payload[0]["type"] is None

    def test_result_is_json_serialisable(self):
        """The payload round-trips through json.dumps / json.loads without error."""
        import json

        metadata = _full_metadata("alpha")
        payload = _build_catalog_payload([metadata])
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        assert parsed[0]["name"] == "alpha"


@pytest.mark.unit
class TestBuildAllVersionsPayload:
    """_build_all_versions_payload returns a list of dicts consumed by _emit_json_payload."""

    def test_single_row_has_four_keys(self):
        """Each element has exactly the four spec-canonical keys."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="abc")]
        payload = _build_all_versions_payload(rows)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert set(payload[0].keys()) == {"name", "version", "ref", "sha"}

    def test_values_match_version_row_fields(self):
        """Field values match the VersionRow attributes."""
        rows = [VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="deadbeef")]
        payload = _build_all_versions_payload(rows)
        assert payload[0]["name"] == "alpha"
        assert payload[0]["version"] == "1.0.0"
        assert payload[0]["ref"] == "refs/tags/1.0.0"
        assert payload[0]["sha"] == "deadbeef"

    def test_empty_input_produces_empty_list(self):
        """Empty rows list produces an empty payload list."""
        assert _build_all_versions_payload([]) == []
