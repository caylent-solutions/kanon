"""End-to-end CLI invocation tests via subprocess."""

import subprocess
import sys

import pytest

from kanon_cli import __version__


def _run_kanon(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


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
class TestKanonBootstrapList:
    def test_bootstrap_list_shows_kanon_package(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0
        assert "kanon" in result.stdout

    def test_bootstrap_list_contains_only_kanon(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0
        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and line.strip() != "Available packages:"
        ]
        assert lines == ["kanon"]


@pytest.mark.functional
class TestKanonBootstrapKanon:
    def test_bootstrap_kanon_creates_kanonenv_and_readme(self, tmp_path) -> None:
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 0
        assert (output_dir / ".kanon").is_file()
        assert (output_dir / "kanon-readme.md").is_file()
        created_files = sorted(f.name for f in output_dir.iterdir())
        assert created_files == [".kanon", "kanon-readme.md"]

    def test_bootstrap_kanon_output_mentions_kanon_install(self, tmp_path) -> None:
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 0
        assert "kanon install .kanon" in result.stdout

    def test_bootstrap_kanon_conflict_on_existing_kanonenv(self, tmp_path) -> None:
        (tmp_path / ".kanon").write_text("existing")
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(tmp_path))
        assert result.returncode == 1
        assert "already exist" in result.stderr


@pytest.mark.functional
class TestKanonBadSubcommand:
    def test_no_subcommand_exits_2(self) -> None:
        result = _run_kanon()
        assert result.returncode == 2

    def test_invalid_subcommand_exits_2(self) -> None:
        result = _run_kanon("nonexistent")
        assert result.returncode == 2

    def test_install_missing_arg_exits_2(self) -> None:
        result = _run_kanon("install")
        assert result.returncode == 2

    def test_clean_missing_arg_exits_2(self) -> None:
        result = _run_kanon("clean")
        assert result.returncode == 2

    def test_validate_no_target_exits_2(self) -> None:
        result = _run_kanon("validate")
        assert result.returncode == 2
