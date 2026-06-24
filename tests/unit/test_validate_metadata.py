"""Unit tests for the kanon validate metadata sub-subcommand.

Tests validate_metadata_command() and _run_metadata() for every documented
success and error path. Verifies that the imported check functions from
catalog.py are invoked the expected number of times using monkeypatching.

AC-TEST-001: Parametrized unit tests covering every success and error path.
"""

from __future__ import annotations

import json
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.validate import _run_metadata, _run_validate_help, register, validate_metadata_command


def _write_xml(path: Path, content: str) -> Path:
    """Write XML content to path (creating parent dirs) and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0"?>\n' + content)
    return path


def _valid_xml() -> str:
    """Return a fully valid catalog-metadata XML body (no prolog)."""
    return textwrap.dedent("""\
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


def _make_repo(tmp_path: Path, xml_files: dict[str, str]) -> Path:
    """Create a minimal manifest-repo skeleton with repo-specs/ and given XML files.

    Args:
        tmp_path: Base temporary directory.
        xml_files: Mapping of filename -> XML content (body without prolog).

    Returns:
        Path to the manifest repo root (tmp_path itself).
    """
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    for filename, content in xml_files.items():
        _write_xml(repo_specs / filename, content)
    return tmp_path


def _make_args(repo_root: Path, fmt: str = "text") -> types.SimpleNamespace:
    """Build a minimal argparse.Namespace for validate_metadata_command."""
    return types.SimpleNamespace(repo_root=repo_root, format=fmt)


@pytest.mark.unit
class TestValidateMetadataCommandCleanRepo:
    """AC-FUNC-001: Clean manifest repo exits 0 with zero findings."""

    def test_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 0

    def test_empty_repo_specs_exits_zero(self, tmp_path: Path) -> None:
        """No XML files means no findings -- command exits 0."""
        _make_repo(tmp_path, {})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 0


@pytest.mark.unit
class TestValidateMetadataCommandMissingRequiredField:
    """AC-FUNC-002: Missing REQUIRED field exits 1."""

    @pytest.mark.parametrize(
        "field",
        ["name", "display-name", "description", "version"],
    )
    def test_missing_required_field_exits_one(self, tmp_path: Path, field: str) -> None:
        fields = {
            "name": "<name>my-tool</name>",
            "display-name": "<display-name>My Tool</display-name>",
            "description": "<description>A useful tool.</description>",
            "version": "<version>1.0.0</version>",
        }

        remaining = {k: v for k, v in fields.items() if k != field}
        body = textwrap.dedent(f"""\
            <package>
              <catalog-metadata>
                {"".join(remaining.values())}
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"tool-marketplace.xml": body})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 1


@pytest.mark.unit
class TestValidateMetadataCommandMissingRecommendedField:
    """AC-FUNC-003: Missing RECOMMENDED field exits 0 with WARN finding."""

    @pytest.mark.parametrize(
        "field",
        ["type", "owner-name", "owner-email", "keywords"],
    )
    def test_missing_recommended_field_exits_zero(
        self, tmp_path: Path, field: str, capsys: pytest.CaptureFixture[str]
    ) -> None:

        rec_fields = {
            "type": "<type>plugin</type>",
            "owner-name": "<owner-name>Alice</owner-name>",
            "owner-email": "<owner-email>alice@example.com</owner-email>",
            "keywords": "<keywords>infra</keywords>",
        }
        remaining_rec = {k: v for k, v in rec_fields.items() if k != field}
        body = textwrap.dedent(f"""\
            <package>
              <catalog-metadata>
                <name>my-tool</name>
                <display-name>My Tool</display-name>
                <description>A useful tool.</description>
                <version>1.0.0</version>
                {"".join(remaining_rec.values())}
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"tool-marketplace.xml": body})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "WARN" in captured.out or "WARN" in captured.err, (
            f"Expected WARN finding in output, got stdout={captured.out!r} stderr={captured.err!r}"
        )


@pytest.mark.unit
class TestValidateMetadataCommandDuplicateChild:
    """AC-FUNC-004: Duplicate child element exits 1."""

    def test_duplicate_child_element_exits_one(self, tmp_path: Path) -> None:
        body = textwrap.dedent("""\
            <package>
              <catalog-metadata>
                <name>dup-tool</name>
                <name>dup-tool-alias</name>
                <display-name>Dup Tool</display-name>
                <description>A tool with duplicate name.</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"dup-marketplace.xml": body})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 1


@pytest.mark.unit
class TestValidateMetadataCommandMultipleBlocks:
    """AC-FUNC-005: Multiple catalog-metadata blocks exits 1."""

    def test_multiple_catalog_metadata_blocks_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = textwrap.dedent("""\
            <package>
              <catalog-metadata>
                <name>first</name>
                <display-name>First</display-name>
                <description>First block.</description>
                <version>1.0.0</version>
              </catalog-metadata>
              <catalog-metadata>
                <name>second</name>
                <display-name>Second</display-name>
                <description>Second block.</description>
                <version>2.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"multi-marketplace.xml": body})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "multi-marketplace.xml" in captured.out or "multi-marketplace.xml" in captured.err, (
            f"Expected XML path in output. stdout={captured.out!r} stderr={captured.err!r}"
        )


@pytest.mark.unit
class TestValidateMetadataCommandSourceNameDrift:
    """AC-FUNC-006: Source-name drift exits 0 with WARN finding."""

    def test_source_name_drift_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:

        body = textwrap.dedent("""\
            <package>
              <catalog-metadata>
                <name>Foo-Bar</name>
                <display-name>Foo Bar</display-name>
                <description>A tool with uppercase name.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Alice</owner-name>
                <owner-email>alice@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"drift-marketplace.xml": body})
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "WARN" in captured.out or "WARN" in captured.err, (
            f"Expected WARN finding in output. stdout={captured.out!r} stderr={captured.err!r}"
        )


@pytest.mark.unit
class TestValidateMetadataCommandEntryNameCollision:
    """AC-FUNC-007: Entry-name collision exits 1."""

    def test_entry_name_collision_exits_one(self, tmp_path: Path) -> None:
        shared_body = textwrap.dedent("""\
            <package>
              <catalog-metadata>
                <name>shared-tool</name>
                <display-name>Shared Tool</display-name>
                <description>A tool with a colliding name.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Alice</owner-name>
                <owner-email>alice@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
            </package>
        """)
        _make_repo(
            tmp_path,
            {
                "a-marketplace.xml": shared_body,
                "b-marketplace.xml": shared_body,
            },
        )
        args = _make_args(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 1


@pytest.mark.unit
class TestValidateMetadataCommandJsonFormat:
    """AC-FUNC-009: --format json emits parseable JSON matching catalog audit schema."""

    def test_json_format_clean_repo(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path, fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "findings" in parsed
        assert isinstance(parsed["findings"], list)

    def test_json_format_with_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        body = textwrap.dedent("""\
            <package>
              <catalog-metadata>
                <display-name>No Name Tool</display-name>
                <description>Missing name.</description>
                <version>1.0.0</version>
              </catalog-metadata>
            </package>
        """)
        _make_repo(tmp_path, {"noname-marketplace.xml": body})
        args = _make_args(tmp_path, fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "findings" in parsed
        assert len(parsed["findings"]) >= 1
        finding = parsed["findings"][0]
        assert "kind" in finding
        assert "code" in finding
        assert "message" in finding
        assert "remediation" in finding


@pytest.mark.unit
class TestValidateMetadataCommandCheckFunctionsInvoked:
    """AC-FUNC-010 / AC-TEST-001: Verify the imported check functions are invoked."""

    def test_all_three_check_functions_invoked(self, tmp_path: Path) -> None:
        """validate_metadata_command invokes all three catalog check functions."""
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path)

        mock_metadata = MagicMock(return_value=[])
        mock_source_name = MagicMock(return_value=[])
        mock_uniqueness = MagicMock(return_value=[])

        with (
            patch("kanon_cli.commands.validate._check_metadata", mock_metadata),
            patch("kanon_cli.commands.validate._check_source_name_derivation", mock_source_name),
            patch("kanon_cli.commands.validate._check_entry_name_uniqueness", mock_uniqueness),
        ):
            with pytest.raises(SystemExit):
                validate_metadata_command(args)

        mock_metadata.assert_called_once()
        mock_source_name.assert_called_once()
        mock_uniqueness.assert_called_once()

    def test_check_functions_receive_resolved_repo_root(self, tmp_path: Path) -> None:
        """The resolved repo_root Path is passed to each check function."""
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path)
        received_paths: list[Path] = []

        def _capture_path(p: Path) -> list:
            received_paths.append(p)
            return []

        with (
            patch("kanon_cli.commands.validate._check_metadata", side_effect=_capture_path),
            patch("kanon_cli.commands.validate._check_source_name_derivation", side_effect=_capture_path),
            patch("kanon_cli.commands.validate._check_entry_name_uniqueness", side_effect=_capture_path),
        ):
            with pytest.raises(SystemExit):
                validate_metadata_command(args)

        assert len(received_paths) == 3
        for p in received_paths:
            assert p == tmp_path.resolve()

    def test_errors_from_all_checks_are_aggregated(self, tmp_path: Path) -> None:
        """Findings from all three checks are combined before exit-code determination."""
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path)

        from kanon_cli.commands.catalog import AuditFinding

        error_finding = AuditFinding(kind="error", code="X001", message="test error", remediation="")
        warn_finding = AuditFinding(kind="warn", code="X002", message="test warn", remediation="")

        with (
            patch("kanon_cli.commands.validate._check_metadata", return_value=[error_finding]),
            patch("kanon_cli.commands.validate._check_source_name_derivation", return_value=[warn_finding]),
            patch("kanon_cli.commands.validate._check_entry_name_uniqueness", return_value=[]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                validate_metadata_command(args)

        assert exc_info.value.code == 1


@pytest.mark.unit
class TestRunMetadata:
    """Tests for _run_metadata() handler."""

    def test_run_metadata_calls_validate_metadata_command(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path, format="text")
        with patch("kanon_cli.commands.validate.validate_metadata_command") as mock_cmd:
            mock_cmd.side_effect = SystemExit(0)
            with pytest.raises(SystemExit) as exc_info:
                _run_metadata(args)
            assert exc_info.value.code == 0
            mock_cmd.assert_called_once_with(args)

    def test_run_metadata_propagates_exit_code(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path, format="text")
        with patch("kanon_cli.commands.validate.validate_metadata_command") as mock_cmd:
            mock_cmd.side_effect = SystemExit(1)
            with pytest.raises(SystemExit) as exc_info:
                _run_metadata(args)
            assert exc_info.value.code == 1


@pytest.mark.unit
class TestRunValidateHelp:
    """Tests for _run_validate_help() handler."""

    def test_exits_two_when_no_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """_run_validate_help exits 2 with error message when no sub-subcommand is given."""
        args = types.SimpleNamespace(validate_command=None)
        with pytest.raises(SystemExit) as exc_info:
            _run_validate_help(args)
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "metadata" in captured.err, (
            f"Error message must name 'metadata' as a valid target. stderr={captured.err!r}"
        )

    def test_no_exit_when_subcommand_is_set(self) -> None:
        """_run_validate_help does nothing when validate_command is already set."""
        args = types.SimpleNamespace(validate_command="metadata")

        result = _run_validate_help(args)
        assert result is None


@pytest.mark.unit
class TestValidateRegisterMetadataSubcommand:
    """Verify that the metadata subcommand is registered by register()."""

    def test_metadata_registered_in_subparsers(self) -> None:
        """register() adds 'metadata' alongside 'xml' and 'marketplace'."""
        import argparse

        top_parser = argparse.ArgumentParser()
        subparsers = top_parser.add_subparsers(dest="command")
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            top_parser.parse_args(["validate", "metadata", "--help"])
        assert exc_info.value.code == 0

    def test_metadata_subparser_has_format_option(self) -> None:
        """The metadata subparser registers --format with text/json choices."""
        import argparse

        top_parser = argparse.ArgumentParser()
        subparsers = top_parser.add_subparsers(dest="command")
        register(subparsers)

        parsed = top_parser.parse_args(["validate", "metadata", "--format", "json"])
        assert parsed.format == "json"

    def test_metadata_subparser_default_format_is_text(self, tmp_path: Path) -> None:
        """The metadata subparser defaults --format to 'text'."""
        import argparse

        top_parser = argparse.ArgumentParser()
        subparsers = top_parser.add_subparsers(dest="command")
        register(subparsers)

        parsed = top_parser.parse_args(["validate", "metadata", "--repo-root", str(tmp_path)])
        assert parsed.format == "text"

    def test_validate_help_shows_xml_marketplace_metadata(self) -> None:
        """register() adds validate with xml, marketplace, and metadata sub-subcommands."""
        import argparse

        top_parser = argparse.ArgumentParser()
        subparsers = top_parser.add_subparsers(dest="command")
        register(subparsers)

        parsed_xml = top_parser.parse_args(["validate", "xml"])
        assert hasattr(parsed_xml, "func")

        parsed_mp = top_parser.parse_args(["validate", "marketplace"])
        assert hasattr(parsed_mp, "func")

        parsed_meta = top_parser.parse_args(["validate", "metadata"])
        assert hasattr(parsed_meta, "func")


@pytest.mark.unit
class TestValidateMetadataCommandNoGitCalls:
    """AC-FUNC-008: validate metadata must not call git ls-remote."""

    def test_no_git_subprocess_calls(self, tmp_path: Path) -> None:
        """validate_metadata_command never invokes subprocess.run with git."""
        _make_repo(tmp_path, {"valid-marketplace.xml": _valid_xml()})
        args = _make_args(tmp_path)
        captured_calls: list[list[str]] = []

        original_run = __import__("subprocess").run

        def _track_run(cmd: object, **kwargs: object) -> object:
            if isinstance(cmd, list):
                captured_calls.append(list(cmd))
            return original_run(cmd, **kwargs)

        with patch("subprocess.run", side_effect=_track_run):
            with pytest.raises(SystemExit):
                validate_metadata_command(args)

        git_ls_remote_calls = [c for c in captured_calls if "git" in c and "ls-remote" in c]
        assert git_ls_remote_calls == [], (
            f"validate_metadata_command must not call git ls-remote, but got: {git_ls_remote_calls}"
        )
