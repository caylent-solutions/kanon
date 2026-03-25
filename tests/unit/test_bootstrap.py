"""Tests for the bootstrap module."""

import pathlib

import pytest

from rpm_cli.core.bootstrap import (
    _print_next_steps,
    bootstrap_package,
    list_packages,
)
from rpm_cli.core.catalog import _get_bundled_catalog_dir


@pytest.mark.unit
class TestListPackages:
    """Verify list_packages returns available catalog entries."""

    def test_returns_rpm(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert "rpm" in packages

    def test_returns_sorted_list(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert packages == sorted(packages)

    def test_only_contains_rpm(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        packages = list_packages(catalog_dir)
        assert packages == ["rpm"]


@pytest.mark.unit
class TestBootstrapRpm:
    """Verify rpm catalog entry package produces .rpmenv and rpm-readme.md."""

    def test_creates_rpmenv_and_readme(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("rpm", output, catalog_dir)
        assert (output / ".rpmenv").is_file()
        assert (output / "rpm-readme.md").is_file()
        created_files = sorted(f.name for f in output.iterdir())
        assert created_files == [".rpmenv", "rpm-readme.md"]

    def test_rpmenv_matches_catalog(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("rpm", output, catalog_dir)
        expected = (catalog_dir / "rpm" / ".rpmenv").read_text()
        actual = (output / ".rpmenv").read_text()
        assert actual == expected

    def test_does_not_copy_gitkeep(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("rpm", output, catalog_dir)
        assert not (output / ".gitkeep").exists()

    def test_readme_mentions_standalone(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        catalog_dir = _get_bundled_catalog_dir()
        bootstrap_package("rpm", output, catalog_dir)
        content = (output / "rpm-readme.md").read_text()
        assert "rpm configure .rpmenv" in content


@pytest.mark.unit
class TestBootstrapConflicts:
    """Verify fail-fast on existing files."""

    def test_refuses_overwrite_existing_rpmenv(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".rpmenv").write_text("existing")
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(SystemExit):
            bootstrap_package("rpm", tmp_path, catalog_dir)


@pytest.mark.unit
class TestBootstrapUnknownPackage:
    """Verify fail-fast on unknown package."""

    def test_unknown_package_fails(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        with pytest.raises(SystemExit):
            bootstrap_package("nonexistent", tmp_path, catalog_dir)


@pytest.mark.unit
class TestCatalogRpmenvFiles:
    """Verify the rpm catalog entry .rpmenv has placeholders for user configuration."""

    def test_rpm_rpmenv_has_repo_url(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "rpm" / ".rpmenv").read_text()
        assert "REPO_URL=" in content

    def test_rpm_rpmenv_has_gitbase_placeholder(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "rpm" / ".rpmenv").read_text()
        assert "<YOUR_GIT_ORG_BASE_URL>" in content

    def test_rpm_rpmenv_has_marketplace_toggle_placeholder(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "rpm" / ".rpmenv").read_text()
        assert "<true|false>" in content

    def test_rpm_rpmenv_has_source_examples(self) -> None:
        catalog_dir = _get_bundled_catalog_dir()
        content = (catalog_dir / "rpm" / ".rpmenv").read_text()
        assert "RPM_SOURCE_" in content
        assert "your-org" in content


@pytest.mark.unit
class TestPrintNextSteps:
    """Verify post-bootstrap instructions."""

    def test_rpm_package_shows_edit_and_configure(self, tmp_path: pathlib.Path, capsys) -> None:
        _print_next_steps("rpm", tmp_path, [".rpmenv"])
        output = capsys.readouterr().out
        assert "Edit .rpmenv" in output
        assert "rpm configure .rpmenv" in output
        assert "Commit .rpmenv" in output
