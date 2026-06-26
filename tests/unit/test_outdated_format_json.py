"""Unit tests for the JSON output format of 'kanon outdated'.

Covers:
- Single tag-pinned source -> JSON array length 1, correct field values.
- Multi-source mix (tag, branch, SHA) -> array length equals source count.
- JSON well-formedness (parses via json.loads without error).
- KANON_OUTDATED_FORMAT=json env var selects JSON when --format is not passed.
- --format json overrides KANON_OUTDATED_FORMAT=table (CLI flag wins over env var).

AC-TEST-001
"""

import json
import pathlib

import pytest

from kanon_cli.commands.outdated import OutdatedRow, _build_outdated_payload, _format_json, _row_to_dict


@pytest.mark.unit
class TestRowToDict:
    """Tests for the _row_to_dict helper that converts OutdatedRow to a JSON-ready dict."""

    def test_keys_match_spec_column_names(self) -> None:
        """All five spec-canonical hyphenated key names must be present."""
        row = OutdatedRow(
            name="FOO",
            current="1.0.0",
            latest_matching_spec="1.0.1",
            latest_available="1.1.0",
            upgrade_type="patch",
        )
        result = _row_to_dict(row)
        assert set(result.keys()) == {"name", "current", "latest-matching-spec", "latest-available", "upgrade-type"}

    def test_values_match_row_fields(self) -> None:
        """Each dict value matches the corresponding OutdatedRow field."""
        row = OutdatedRow(
            name="BAR",
            current="2.0.0",
            latest_matching_spec="2.1.0",
            latest_available="3.0.0",
            upgrade_type="minor",
        )
        result = _row_to_dict(row)
        assert result["name"] == "BAR"
        assert result["current"] == "2.0.0"
        assert result["latest-matching-spec"] == "2.1.0"
        assert result["latest-available"] == "3.0.0"
        assert result["upgrade-type"] == "minor"

    @pytest.mark.parametrize(
        "upgrade_type",
        ["none", "patch", "minor", "major", "prerelease", "drift"],
    )
    def test_upgrade_type_values_preserved(self, upgrade_type: str) -> None:
        """Every valid upgrade-type string is passed through unchanged."""
        row = OutdatedRow(
            name="SRC",
            current="1.0.0",
            latest_matching_spec="1.0.0",
            latest_available="1.0.0",
            upgrade_type=upgrade_type,
        )
        result = _row_to_dict(row)
        assert result["upgrade-type"] == upgrade_type

    def test_exactly_five_keys(self) -> None:
        """The dict has exactly five keys -- no extras, none missing."""
        row = OutdatedRow(
            name="EXACT",
            current="0.0.1",
            latest_matching_spec="0.0.1",
            latest_available="0.0.1",
            upgrade_type="none",
        )
        result = _row_to_dict(row)
        assert len(result) == 5


@pytest.mark.unit
class TestFormatJson:
    """Tests for the _format_json function."""

    def test_single_source_array_length_one(self) -> None:
        """A single row produces a JSON array with exactly one element."""
        rows = [
            OutdatedRow(
                name="SINGLE",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="1.1.0",
                upgrade_type="patch",
            )
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_single_source_field_values(self) -> None:
        """The single element contains the correct field values."""
        rows = [
            OutdatedRow(
                name="SINGLE",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="1.1.0",
                upgrade_type="patch",
            )
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        obj = parsed[0]
        assert obj["name"] == "SINGLE"
        assert obj["current"] == "1.0.0"
        assert obj["latest-matching-spec"] == "1.0.1"
        assert obj["latest-available"] == "1.1.0"
        assert obj["upgrade-type"] == "patch"

    def test_multi_source_array_length_matches_row_count(self) -> None:
        """Multiple rows produce a JSON array with matching length."""
        rows = [
            OutdatedRow(
                name="TAG_SRC",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="2.0.0",
                upgrade_type="patch",
            ),
            OutdatedRow(
                name="BRANCH_SRC",
                current="abc123456789",
                latest_matching_spec="def456789012",
                latest_available="def456789012",
                upgrade_type="drift",
            ),
            OutdatedRow(
                name="SHA_SRC",
                current="aabbccddeeff",
                latest_matching_spec="aabbccddeeff",
                latest_available="aabbccddeeff",
                upgrade_type="none",
            ),
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 3

    def test_multi_source_field_shapes_match(self) -> None:
        """Each element in the array has exactly five keys with the correct names."""
        rows = [
            OutdatedRow(
                name="A",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="2.0.0",
                upgrade_type="major",
            ),
            OutdatedRow(
                name="B",
                current="abc123456789",
                latest_matching_spec="abc123456789",
                latest_available="abc123456789",
                upgrade_type="none",
            ),
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        expected_keys = {"name", "current", "latest-matching-spec", "latest-available", "upgrade-type"}
        for obj in parsed:
            assert set(obj.keys()) == expected_keys

    def test_json_well_formed_parseable_by_loads(self) -> None:
        """Output parses cleanly via json.loads without raising any exception."""
        rows = [
            OutdatedRow(
                name="WF",
                current="1.0.0",
                latest_matching_spec="1.0.0",
                latest_available="1.0.0",
                upgrade_type="none",
            )
        ]
        output = _format_json(rows)

        result = json.loads(output)
        assert isinstance(result, list)

    def test_output_ends_with_newline(self) -> None:
        """Output ends with a trailing newline for POSIX-tool friendliness."""
        rows = [
            OutdatedRow(
                name="NL",
                current="1.0.0",
                latest_matching_spec="1.0.0",
                latest_available="1.0.0",
                upgrade_type="none",
            )
        ]
        output = _format_json(rows)
        assert output.endswith("\n")

    def test_empty_rows_produces_empty_array(self) -> None:
        """Zero rows produces an empty JSON array."""
        output = _format_json([])
        parsed = json.loads(output)
        assert parsed == []

    def test_branch_pinned_sha_serializes_as_string(self) -> None:
        """Branch-pinned 12-char SHA is serialized as a string, not a number."""
        rows = [
            OutdatedRow(
                name="BR",
                current="abc123456789",
                latest_matching_spec="def012345678",
                latest_available="def012345678",
                upgrade_type="drift",
            )
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        obj = parsed[0]
        assert isinstance(obj["current"], str)
        assert isinstance(obj["latest-matching-spec"], str)
        assert isinstance(obj["latest-available"], str)
        assert obj["current"] == "abc123456789"
        assert obj["latest-matching-spec"] == "def012345678"

    def test_order_of_sources_preserved(self) -> None:
        """Sources appear in the same order as the input rows."""
        names = ["ALPHA", "BETA", "GAMMA"]
        rows = [
            OutdatedRow(
                name=n,
                current="1.0.0",
                latest_matching_spec="1.0.0",
                latest_available="1.0.0",
                upgrade_type="none",
            )
            for n in names
        ]
        output = _format_json(rows)
        parsed = json.loads(output)
        assert [obj["name"] for obj in parsed] == names


@pytest.mark.unit
class TestFormatDispatch:
    """Tests for the --format / KANON_OUTDATED_FORMAT dispatch logic in run()."""

    def test_env_var_json_selects_json_formatter(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_OUTDATED_FORMAT=json selects the JSON formatter when --format is not passed."""
        import argparse
        import importlib

        import kanon_cli.commands.outdated as outdated_mod

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///fake/foo.git\n"
            "KANON_SOURCE_FOO_REVISION=>=1.0.0\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
        )

        monkeypatch.setenv("KANON_OUTDATED_FORMAT", "json")
        importlib.reload(outdated_mod)

        top_parser = argparse.ArgumentParser()
        subs = top_parser.add_subparsers()
        outdated_mod.register(subs)
        parsed = top_parser.parse_args(
            [
                "outdated",
                "--catalog-source",
                "file:///fake@HEAD",
                "--kanon-file",
                str(kanon_file),
            ]
        )
        assert parsed.format == "json"

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)

    def test_cli_flag_overrides_env_var(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--format json overrides KANON_OUTDATED_FORMAT=table (flag wins over env var)."""
        import argparse
        import importlib

        import kanon_cli.commands.outdated as outdated_mod

        monkeypatch.setenv("KANON_OUTDATED_FORMAT", "table")
        importlib.reload(outdated_mod)

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_BAR_URL=file:///fake/bar.git\n"
            "KANON_SOURCE_BAR_REVISION=>=1.0.0\n"
            "KANON_SOURCE_BAR_PATH=./bar\n"
        )

        top_parser = argparse.ArgumentParser()
        subs = top_parser.add_subparsers()
        outdated_mod.register(subs)
        parsed = top_parser.parse_args(
            [
                "outdated",
                "--catalog-source",
                "file:///fake@HEAD",
                "--kanon-file",
                str(kanon_file),
                "--format",
                "json",
            ]
        )

        assert parsed.format == "json"

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)

    def test_invalid_format_value_not_in_choices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--format with an unsupported value raises argparse error (non-zero exit)."""
        import argparse
        import importlib

        import kanon_cli.commands.outdated as outdated_mod

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)

        top_parser = argparse.ArgumentParser()
        subs = top_parser.add_subparsers()
        outdated_mod.register(subs)

        with pytest.raises(SystemExit) as exc_info:
            top_parser.parse_args(
                [
                    "outdated",
                    "--catalog-source",
                    "file:///fake@HEAD",
                    "--format",
                    "xml",
                ]
            )
        assert exc_info.value.code != 0

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)

    def test_format_choices_include_table_and_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The --format argument choices include both 'table' and 'json'."""
        import argparse
        import importlib

        import kanon_cli.commands.outdated as outdated_mod

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)

        top_parser = argparse.ArgumentParser()
        subs = top_parser.add_subparsers()
        outdated_mod.register(subs)

        outdated_parser = subs.choices["outdated"]
        format_action = None
        for action in outdated_parser._actions:
            if hasattr(action, "dest") and action.dest == "format":
                format_action = action
                break

        assert format_action is not None, "No --format action found on the outdated subparser"
        assert format_action.choices is not None
        assert "table" in format_action.choices
        assert "json" in format_action.choices

        monkeypatch.delenv("KANON_OUTDATED_FORMAT", raising=False)
        importlib.reload(outdated_mod)


@pytest.mark.unit
class TestRunJsonDispatch:
    """Tests for the run() function dispatching to _format_json when format='json'.

    These tests patch the network calls so run() can be exercised in-process,
    covering the format-dispatch branch in outdated.py.
    """

    def test_run_outputs_json_with_patched_tags(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() emits valid JSON when args.format='json' and _list_tags is patched."""
        import argparse
        from unittest.mock import patch

        from kanon_cli.commands.outdated import run

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0,<1.1\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=foo-manifest\n"
            "KANON_SOURCE_FOO_GITBASE=file:///some\n"
        )
        kanon_file.chmod(0o644)

        fake_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1", "refs/tags/1.1.0"]

        args = argparse.Namespace(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=None,
            format="json",
            fail_on_upgrade=False,
        )

        with patch("kanon_cli.commands.outdated._list_tags", return_value=fake_tags):
            result = run(args)

        assert result == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert isinstance(parsed, dict)
        assert parsed["aliases"] == ["FOO -> foo-manifest from file:///some/repo@>=1.0.0,<1.1"]
        sources = parsed["sources"]
        assert isinstance(sources, list)
        assert len(sources) == 1
        obj = sources[0]
        assert obj["name"] == "FOO"
        assert set(obj.keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }


@pytest.mark.unit
class TestBuildOutdatedPayload:
    """_build_outdated_payload returns a list of dicts consumed by _emit_json_payload."""

    def test_single_row_has_five_keys(self) -> None:
        """Each element has exactly the five spec-canonical keys."""
        rows = [
            OutdatedRow(
                name="FOO",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="1.1.0",
                upgrade_type="patch",
            )
        ]
        payload = _build_outdated_payload(rows)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert set(payload[0].keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }

    def test_values_match_row_fields(self) -> None:
        """Field values match the OutdatedRow attributes."""
        rows = [
            OutdatedRow(
                name="BAR",
                current="2.0.0",
                latest_matching_spec="2.1.0",
                latest_available="3.0.0",
                upgrade_type="minor",
            )
        ]
        payload = _build_outdated_payload(rows)
        obj = payload[0]
        assert obj["name"] == "BAR"
        assert obj["current"] == "2.0.0"
        assert obj["latest-matching-spec"] == "2.1.0"
        assert obj["latest-available"] == "3.0.0"
        assert obj["upgrade-type"] == "minor"

    def test_empty_rows_produces_empty_list(self) -> None:
        """Empty input produces an empty list."""
        assert _build_outdated_payload([]) == []

    def test_result_is_json_serialisable(self) -> None:
        """The payload round-trips through json.dumps / json.loads without error."""
        rows = [
            OutdatedRow(
                name="ALPHA",
                current="1.0.0",
                latest_matching_spec="1.0.0",
                latest_available="1.0.0",
                upgrade_type="none",
            )
        ]
        payload = _build_outdated_payload(rows)
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        assert parsed[0]["name"] == "ALPHA"
