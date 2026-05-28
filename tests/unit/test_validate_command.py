"""Tests for the validate command handler."""

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.validate import _resolve_repo_root, _run_marketplace, _run_xml, validate_metadata_command


@pytest.mark.unit
class TestResolveRepoRoot:
    def test_explicit_path(self, tmp_path) -> None:
        """An existing absolute --repo-root directory is returned resolved."""
        result = _resolve_repo_root(tmp_path)
        assert result == tmp_path.resolve()
        assert result.is_absolute()

    def test_explicit_relative_path_is_resolved_to_abspath(self, tmp_path, monkeypatch) -> None:
        """A relative --repo-root is resolved to an absolute path at the CLI boundary.

        Downstream validators use ``xml_file.relative_to(repo_root)`` and
        ``repo_root / name`` for include resolution; both require consistent
        rooting. Resolving at the entry point guarantees that consistency
        regardless of whether the user passed ``--repo-root .`` or a full
        absolute path.
        """
        monkeypatch.chdir(tmp_path)
        result = _resolve_repo_root(Path("."))
        assert result.is_absolute(), f"--repo-root must be resolved to an absolute path, got {result!r}"
        assert result == tmp_path.resolve()

    def test_explicit_path_that_does_not_exist_fails_fast(self, tmp_path, capsys) -> None:
        """A non-existent --repo-root directory exits 1 with a clear message."""
        missing = tmp_path / "does-not-exist"
        with pytest.raises(SystemExit) as exc_info:
            _resolve_repo_root(missing)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--repo-root directory not found" in captured.err, (
            f"stderr must name the missing directory, got {captured.err!r}"
        )

    def test_auto_detect(self) -> None:
        with patch("kanon_cli.commands.validate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="/detected/root\n", stderr="")
            result = _resolve_repo_root(None)
            assert result == Path("/detected/root")

    def test_auto_detect_fails(self) -> None:
        with patch("kanon_cli.commands.validate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="not a git repo")
            with pytest.raises(SystemExit):
                _resolve_repo_root(None)


@pytest.mark.unit
class TestRunXml:
    def test_dispatches_to_validate_xml(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path)
        with patch("kanon_cli.commands.validate.validate_xml", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                _run_xml(args)
            assert exc_info.value.code == 0


@pytest.mark.unit
class TestRunMarketplace:
    def test_dispatches_to_validate_marketplace(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path)
        with patch("kanon_cli.commands.validate.validate_marketplace", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                _run_marketplace(args)
            assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Tests for validate_metadata_command JSON output via _build_findings_payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateMetadataCommandJsonOutput:
    """validate_metadata_command JSON output uses _build_findings_payload."""

    def test_json_format_calls_emit_json_payload(self, tmp_path: Path, capsys) -> None:
        """validate_metadata_command --format json routes output through _emit_json_payload."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "alpha-marketplace.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>T</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>k</keywords>"
            "</catalog-metadata></manifest>"
        )
        args = types.SimpleNamespace(repo_root=tmp_path, format="json")

        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "findings" in parsed
        assert isinstance(parsed["findings"], list)
