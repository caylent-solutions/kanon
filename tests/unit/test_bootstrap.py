"""Tests for the bootstrap module."""

import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.bootstrap import (
    BootstrapOutputDirError,
    _print_next_steps,
    bootstrap_package,
    list_packages,
)
from kanon_cli.core.catalog import _get_bundled_catalog_dir

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent
_BOOTSTRAP_PY = _PROJECT_ROOT / "src" / "kanon_cli" / "commands" / "bootstrap.py"
_BOOTSTRAP_HELP_FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "help" / "bootstrap.txt"
# The installed kanon CLI binary lives in the project venv alongside the test runner's python.
_KANON_BIN = _PROJECT_ROOT / ".venv" / "bin" / "kanon"


@pytest.mark.unit
class TestListPackages:
    """Verify list_packages returns available catalog entries."""

    def test_returns_kanon(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert "kanon" in packages

    def test_returns_sorted_list(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert packages == sorted(packages)

    def test_only_contains_kanon(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert packages == ["kanon"]


@pytest.mark.unit
class TestBootstrapKanon:
    """Verify kanon catalog entry package produces .kanon and kanon-readme.md."""

    def test_creates_kanonenv_and_readme(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("kanon", output, catalog_dir)
        assert (output / ".kanon").is_file()
        assert (output / "kanon-readme.md").is_file()
        created_files = sorted(f.name for f in output.iterdir())
        assert created_files == [".kanon", "kanon-readme.md"]

    def test_kanonenv_matches_catalog(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("kanon", output, catalog_dir)
        expected = (catalog_dir / "kanon" / ".kanon").read_text()
        actual = (output / ".kanon").read_text()
        assert actual == expected

    def test_does_not_copy_gitkeep(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("kanon", output, catalog_dir)
        assert not (output / ".gitkeep").exists()

    def test_readme_mentions_standalone(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("kanon", output, catalog_dir)
        content = (output / "kanon-readme.md").read_text()
        assert "kanon install .kanon" in content


@pytest.mark.unit
class TestBootstrapConflicts:
    """Verify fail-fast on existing files raises BootstrapOutputDirError."""

    def test_refuses_overwrite_existing_kanonenv(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text("existing")
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(BootstrapOutputDirError):
            bootstrap_package("kanon", tmp_path, catalog_dir)


@pytest.mark.unit
class TestBootstrapUnknownPackage:
    """Verify fail-fast on unknown package raises BootstrapOutputDirError."""

    def test_unknown_package_raises_typed_exception(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(BootstrapOutputDirError):
            bootstrap_package("nonexistent", tmp_path, catalog_dir)

    def test_unknown_package_message_includes_package_name(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(BootstrapOutputDirError, match="nonexistent"):
            bootstrap_package("nonexistent", tmp_path, catalog_dir)


@pytest.mark.unit
class TestBootstrapMissingParentDir:
    """Verify fail-fast when output-dir parent directory does not exist (AC-TEST-001)."""

    def test_missing_parent_raises_typed_exception(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        output = tmp_path / "nonexistent-parent" / "sub"
        with pytest.raises(BootstrapOutputDirError):
            bootstrap_package("kanon", output, catalog_dir)

    def test_missing_parent_message_names_parent_path(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        output = tmp_path / "nonexistent-parent" / "sub"
        with pytest.raises(BootstrapOutputDirError, match="parent directory"):
            bootstrap_package("kanon", output, catalog_dir)

    def test_missing_parent_message_includes_path(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        output = tmp_path / "nonexistent-parent" / "sub"
        parent_str = str(tmp_path / "nonexistent-parent")
        with pytest.raises(BootstrapOutputDirError, match=parent_str):
            bootstrap_package("kanon", output, catalog_dir)

    def test_no_output_dir_created_on_missing_parent(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        output = tmp_path / "nonexistent-parent" / "sub"
        with pytest.raises(BootstrapOutputDirError):
            bootstrap_package("kanon", output, catalog_dir)
        assert not output.exists()

    def test_existing_parent_with_new_leaf_succeeds(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        output = tmp_path / "sub"
        bootstrap_package("kanon", output, catalog_dir)
        assert (output / ".kanon").is_file()


@pytest.mark.unit
class TestBootstrapMkdirFailure:
    """Verify OSError on mkdir raises BootstrapOutputDirError."""

    def test_mkdir_oserror_raises_typed_exception(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        # Use a path whose parent exists so the is_dir() check passes;
        # the OSError is injected at the mkdir() call itself.
        bad_output = tmp_path / "subdir"
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            with pytest.raises(BootstrapOutputDirError):
                bootstrap_package("kanon", bad_output, catalog_dir)


@pytest.mark.unit
class TestBootstrapCliHandler:
    """Verify the CLI handler catches BootstrapOutputDirError and exits 1 with stderr message."""

    def test_cli_catches_bootstrap_error_and_exits_1(self, tmp_path: pathlib.Path, capsys) -> None:
        import argparse

        from kanon_cli.commands.bootstrap import _run

        args = argparse.Namespace(
            package="nonexistent",
            output_dir=tmp_path,
            catalog_source=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            _run(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "nonexistent" in captured.err

    def test_cli_error_message_written_to_stderr_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        import argparse

        from kanon_cli.commands.bootstrap import _run

        args = argparse.Namespace(
            package="nonexistent",
            output_dir=tmp_path,
            catalog_source=None,
        )
        with pytest.raises(SystemExit):
            _run(args)

        captured = capsys.readouterr()
        assert captured.err != ""
        assert "nonexistent" not in captured.out

    def test_cli_no_traceback_on_error(self, tmp_path: pathlib.Path, capsys) -> None:
        import argparse

        from kanon_cli.commands.bootstrap import _run

        args = argparse.Namespace(
            package="nonexistent",
            output_dir=tmp_path,
            catalog_source=None,
        )
        with pytest.raises(SystemExit):
            _run(args)

        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "Traceback" not in captured.out


@pytest.mark.unit
class TestCatalogKanonenvFiles:
    """Verify the kanon catalog entry .kanon has placeholders for user configuration."""

    def test_kanon_kanonenv_has_source_url_pattern(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "kanon" / ".kanon").read_text()
        assert "KANON_SOURCE_" in content

    def test_kanon_kanonenv_has_gitbase_placeholder(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "kanon" / ".kanon").read_text()
        assert "<YOUR_GIT_ORG_BASE_URL>" in content

    def test_kanon_kanonenv_has_marketplace_toggle_placeholder(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "kanon" / ".kanon").read_text()
        assert "<true|false>" in content

    def test_kanon_kanonenv_has_source_examples(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "kanon" / ".kanon").read_text()
        assert "KANON_SOURCE_" in content
        assert "your-org" in content


@pytest.mark.unit
class TestPrintNextSteps:
    """Verify post-bootstrap instructions."""

    def test_kanon_package_shows_edit_and_install(self, tmp_path: pathlib.Path, capsys) -> None:
        _print_next_steps("kanon", tmp_path, [".kanon"])
        output = capsys.readouterr().out
        assert "Edit .kanon" in output
        assert "kanon install .kanon" in output
        assert "Commit .kanon" in output


@pytest.mark.unit
class TestBootstrapHelpSnapshot:
    """Assert that kanon bootstrap --help output is byte-identical to the committed fixture (AC-FUNC-005, AC-TEST-002)."""

    def test_bootstrap_help_matches_fixture(self) -> None:
        result = subprocess.run(
            [str(_KANON_BIN), "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"kanon bootstrap --help exited {result.returncode}: {result.stderr}"
        expected = _BOOTSTRAP_HELP_FIXTURE.read_text()
        assert result.stdout == expected, (
            "kanon bootstrap --help output has drifted from the fixture at "
            f"{_BOOTSTRAP_HELP_FIXTURE}. Update the fixture if the change is "
            "intentional."
        )


@pytest.mark.unit
class TestBootstrapDelegatesFlag:
    """Assert bootstrap.py imports and delegates --catalog-source to add_catalog_source_arg (AC-TEST-003)."""

    def test_bootstrap_imports_add_catalog_source_arg(self) -> None:
        source = _BOOTSTRAP_PY.read_text()
        assert "from kanon_cli.core.cli_args import add_catalog_source_arg" in source, (
            "bootstrap.py must import add_catalog_source_arg from kanon_cli.core.cli_args"
        )

    def test_bootstrap_does_not_define_catalog_source_inline(self) -> None:
        source = _BOOTSTRAP_PY.read_text()
        # After the refactor the inline add_argument block must be gone.
        assert 'add_argument(\n        "--catalog-source"' not in source, (
            "bootstrap.py still contains an inline add_argument('--catalog-source', ...) call; "
            "it must be replaced with add_catalog_source_arg(parser)"
        )
        assert 'add_argument("--catalog-source"' not in source, (
            'bootstrap.py still contains an inline add_argument("--catalog-source", ...) call; '
            "it must be replaced with add_catalog_source_arg(parser)"
        )
