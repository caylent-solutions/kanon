"""Tests for the bootstrap module."""

import pathlib

import pytest

from kanon_cli.core.bootstrap import (
    _print_next_steps,
    bootstrap_package,
    list_packages,
)
from kanon_cli.core.catalog import _get_bundled_catalog_dir


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
    """Verify fail-fast on existing files."""

    def test_refuses_overwrite_existing_kanonenv(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text("existing")
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(SystemExit):
            bootstrap_package("kanon", tmp_path, catalog_dir)


@pytest.mark.unit
class TestBootstrapUnknownPackage:
    """Verify fail-fast on unknown package."""

    def test_unknown_package_fails(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(SystemExit):
            bootstrap_package("nonexistent", tmp_path, catalog_dir)


@pytest.mark.unit
class TestCatalogKanonenvFiles:
    """Verify the kanon catalog entry .kanon has placeholders for user configuration."""

    def test_kanon_kanonenv_has_repo_url(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "kanon" / ".kanon").read_text()
        assert "REPO_URL=" in content

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
