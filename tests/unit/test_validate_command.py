"""Tests for the validate command handler."""

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.validate import _resolve_repo_root, _run_marketplace, _run_xml


@pytest.mark.unit
class TestResolveRepoRoot:
    def test_explicit_path(self) -> None:
        result = _resolve_repo_root(Path("/some/path"))
        assert result == Path("/some/path")

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
