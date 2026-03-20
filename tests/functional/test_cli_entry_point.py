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
class TestRpmBootstrapList:
    def test_bootstrap_list_shows_rpm_package(self) -> None:
        result = _run_rpm("bootstrap", "list")
        assert result.returncode == 0
        assert "rpm" in result.stdout

    def test_bootstrap_list_contains_only_rpm(self) -> None:
        result = _run_rpm("bootstrap", "list")
        assert result.returncode == 0
        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and line.strip() != "Available packages:"
        ]
        assert lines == ["rpm"]


@pytest.mark.functional
class TestRpmBootstrapRpm:
    def test_bootstrap_rpm_creates_rpmenv_and_readme(self, tmp_path) -> None:
        output_dir = tmp_path / "test-project"
        result = _run_rpm("bootstrap", "rpm", "--output-dir", str(output_dir))
        assert result.returncode == 0
        assert (output_dir / ".rpmenv").is_file()
        assert (output_dir / "rpm-readme.md").is_file()
        created_files = sorted(f.name for f in output_dir.iterdir())
        assert created_files == [".rpmenv", "rpm-readme.md"]

    def test_bootstrap_rpm_output_mentions_rpm_configure(self, tmp_path) -> None:
        output_dir = tmp_path / "test-project"
        result = _run_rpm("bootstrap", "rpm", "--output-dir", str(output_dir))
        assert result.returncode == 0
        assert "rpm configure .rpmenv" in result.stdout

    def test_bootstrap_rpm_conflict_on_existing_rpmenv(self, tmp_path) -> None:
        (tmp_path / ".rpmenv").write_text("existing")
        result = _run_rpm("bootstrap", "rpm", "--output-dir", str(tmp_path))
        assert result.returncode == 1
        assert "already exist" in result.stderr


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
