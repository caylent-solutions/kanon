"""End-to-end CLI invocation tests via subprocess."""

import subprocess
import sys

import pytest

from rpm_cli import __version__


def _run_rpm(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "rpm_cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.functional
class TestRpmHelp:
    def test_top_level_help(self) -> None:
        result = _run_rpm("--help")
        assert result.returncode == 0
        assert "configure" in result.stdout
        assert "clean" in result.stdout
        assert "validate" in result.stdout

    def test_configure_help(self) -> None:
        result = _run_rpm("configure", "--help")
        assert result.returncode == 0
        assert "rpmenv_path" in result.stdout

    def test_clean_help(self) -> None:
        result = _run_rpm("clean", "--help")
        assert result.returncode == 0
        assert "rpmenv_path" in result.stdout

    def test_validate_help(self) -> None:
        result = _run_rpm("validate", "--help")
        assert result.returncode == 0
        assert "xml" in result.stdout
        assert "marketplace" in result.stdout

    def test_validate_xml_help(self) -> None:
        result = _run_rpm("validate", "xml", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout

    def test_validate_marketplace_help(self) -> None:
        result = _run_rpm("validate", "marketplace", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout


@pytest.mark.functional
class TestRpmVersion:
    def test_version_flag(self) -> None:
        result = _run_rpm("--version")
        assert result.returncode == 0
        assert __version__ in result.stdout


@pytest.mark.functional
class TestRpmBadSubcommand:
    def test_no_subcommand_exits_2(self) -> None:
        result = _run_rpm()
        assert result.returncode == 2

    def test_invalid_subcommand_exits_2(self) -> None:
        result = _run_rpm("nonexistent")
        assert result.returncode == 2

    def test_configure_missing_arg_exits_2(self) -> None:
        result = _run_rpm("configure")
        assert result.returncode == 2

    def test_clean_missing_arg_exits_2(self) -> None:
        result = _run_rpm("clean")
        assert result.returncode == 2

    def test_validate_no_target_exits_2(self) -> None:
        result = _run_rpm("validate")
        assert result.returncode == 2
