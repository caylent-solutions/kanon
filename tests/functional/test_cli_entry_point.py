"""End-to-end CLI invocation tests via subprocess."""

import pytest

from kanon_cli import __version__
from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestKanonHelp:
    def test_top_level_help(self) -> None:
        result = _run_kanon("--help")
        assert result.returncode == 0
        assert "install" in result.stdout
        assert "clean" in result.stdout
        assert "validate" in result.stdout

    def test_install_help(self) -> None:
        result = _run_kanon("install", "--help")
        assert result.returncode == 0
        assert "kanonenv_path" in result.stdout

    def test_clean_help(self) -> None:
        result = _run_kanon("clean", "--help")
        assert result.returncode == 0
        assert "kanonenv_path" in result.stdout

    def test_validate_help(self) -> None:
        result = _run_kanon("validate", "--help")
        assert result.returncode == 0
        assert "xml" in result.stdout
        assert "marketplace" in result.stdout

    def test_validate_xml_help(self) -> None:
        result = _run_kanon("validate", "xml", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout

    def test_validate_marketplace_help(self) -> None:
        result = _run_kanon("validate", "marketplace", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout


@pytest.mark.functional
class TestKanonVersion:
    def test_version_flag(self) -> None:
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert __version__ in result.stdout


@pytest.mark.functional
class TestKanonBadSubcommand:
    def test_no_subcommand_exits_2(self) -> None:
        result = _run_kanon()
        assert result.returncode == 2

    def test_invalid_subcommand_exits_2(self) -> None:
        result = _run_kanon("nonexistent")
        assert result.returncode == 2

    def test_install_no_arg_no_kanonenv_exits_1(self) -> None:
        result = _run_kanon("install")
        assert result.returncode == 1
        assert ".kanon" in result.stderr

    def test_clean_no_arg_no_kanonenv_exits_1(self) -> None:
        result = _run_kanon("clean")
        assert result.returncode == 1
        assert ".kanon" in result.stderr

    def test_validate_no_target_exits_2(self) -> None:
        result = _run_kanon("validate")
        assert result.returncode == 2


@pytest.mark.functional
class TestKanonRepo:
    def test_repo_is_registered_as_subcommand(self) -> None:
        """'kanon repo' must be a registered subcommand accessible from the CLI."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        assert "repo" in result.stdout.lower()

    def test_repo_help_output_not_empty(self) -> None:
        """'kanon repo --help' must produce non-empty help text."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0
