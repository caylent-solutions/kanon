"""Integration tests for the kanon bootstrap workflow (16 tests).

Verifies bootstrap business logic against the bundled catalog, exercising
list_packages, bootstrap_package, and CLI dispatch through the main() entry
point.  No subprocess calls to external processes are made -- all assertions
target the Python API directly.
"""

import pathlib

import pytest

from kanon_cli.cli import main
from kanon_cli.core.bootstrap import bootstrap_package, list_packages
from kanon_cli.core.catalog import _get_bundled_catalog_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundled_catalog() -> pathlib.Path:
    """Return the bundled catalog directory path."""
    return _get_bundled_catalog_dir()


# ---------------------------------------------------------------------------
# AC-FUNC-001: Bootstrap integration tests (16 tests)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBootstrapListPackages:
    """Verify list_packages behaviour against the bundled catalog."""

    def test_bundled_catalog_is_accessible(self) -> None:
        catalog = _bundled_catalog()
        assert catalog.is_dir(), f"Bundled catalog directory does not exist: {catalog}"

    def test_list_packages_returns_at_least_one(self) -> None:
        packages = list_packages(_bundled_catalog())
        assert len(packages) >= 1, "Expected at least one bundled package"

    def test_list_packages_contains_kanon(self) -> None:
        packages = list_packages(_bundled_catalog())
        assert "kanon" in packages, f"Expected 'kanon' in packages, got {packages!r}"

    def test_list_packages_is_sorted(self) -> None:
        packages = list_packages(_bundled_catalog())
        assert packages == sorted(packages), "Expected packages in alphabetical order"

    def test_list_packages_returns_only_kanon(self) -> None:
        packages = list_packages(_bundled_catalog())
        assert packages == ["kanon"], f"Expected only 'kanon' package, got {packages!r}"

    def test_bundled_catalog_kanon_dir_has_kanonenv(self) -> None:
        catalog = _bundled_catalog()
        kanonenv = catalog / "kanon" / ".kanon"
        assert kanonenv.is_file(), f"Expected .kanon in bundled kanon package, missing: {kanonenv}"

    def test_bundled_catalog_kanon_dir_has_readme(self) -> None:
        catalog = _bundled_catalog()
        readme = catalog / "kanon" / "kanon-readme.md"
        assert readme.is_file(), f"Expected kanon-readme.md in bundled kanon package, missing: {readme}"


@pytest.mark.integration
class TestBootstrapPackageCreation:
    """Verify bootstrap_package creates expected files in output directory."""

    def test_creates_kanonenv_file(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        bootstrap_package("kanon", output, _bundled_catalog())
        assert (output / ".kanon").is_file()

    def test_creates_readme_file(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        bootstrap_package("kanon", output, _bundled_catalog())
        assert (output / "kanon-readme.md").is_file()

    def test_does_not_create_gitkeep(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        bootstrap_package("kanon", output, _bundled_catalog())
        assert not (output / ".gitkeep").exists()

    def test_kanonenv_content_matches_catalog(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        bootstrap_package("kanon", output, _bundled_catalog())
        expected = (_bundled_catalog() / "kanon" / ".kanon").read_text()
        actual = (output / ".kanon").read_text()
        assert actual == expected

    def test_output_dir_created_if_not_exists(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "new" / "nested" / "dir"
        assert not output.exists()
        bootstrap_package("kanon", output, _bundled_catalog())
        assert output.is_dir()

    def test_unknown_package_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            bootstrap_package("nonexistent-package", tmp_path, _bundled_catalog())
        assert exc_info.value.code != 0

    def test_conflict_on_existing_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text("existing content\n")
        with pytest.raises(SystemExit) as exc_info:
            bootstrap_package("kanon", tmp_path, _bundled_catalog())
        assert exc_info.value.code != 0


@pytest.mark.integration
class TestBootstrapCLIDispatch:
    """Verify bootstrap subcommand via main() dispatch."""

    def test_bootstrap_list_exit_zero(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        main(["bootstrap", "list"])

    def test_bootstrap_kanon_creates_files(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        main(["bootstrap", "kanon"])
        assert (tmp_path / ".kanon").is_file()
        assert (tmp_path / "kanon-readme.md").is_file()
