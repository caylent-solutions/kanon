"""Tests verifying the kanon_cli.repo package directory structure exists."""

import importlib

import pytest

from tests.unit.repo.conftest import REPO_ROOT

SRC_KANON_CLI = REPO_ROOT / "src" / "kanon_cli"


@pytest.mark.unit
@pytest.mark.parametrize(
    "directory",
    [
        "repo",
        "repo/subcmds",
        "repo/hooks",
    ],
)
def test_repo_package_structure_exists(directory: str) -> None:
    """Verify each required subdirectory exists under src/kanon_cli/."""
    target = SRC_KANON_CLI / directory
    assert target.is_dir(), f"Expected directory {target} to exist but it does not"


@pytest.mark.unit
@pytest.mark.parametrize(
    "init_file",
    [
        "repo/__init__.py",
        "repo/subcmds/__init__.py",
    ],
)
def test_repo_init_files_exist(init_file: str) -> None:
    """Verify __init__.py files exist for Python packages under src/kanon_cli/."""
    target = SRC_KANON_CLI / init_file
    assert target.is_file(), f"Expected file {target} to exist but it does not"


@pytest.mark.unit
def test_import_kanon_cli_repo() -> None:
    """Verify that 'import kanon_cli.repo' succeeds after package creation."""
    module = importlib.import_module("kanon_cli.repo")
    assert module.__name__ == "kanon_cli.repo", f"Expected module name 'kanon_cli.repo' but got '{module.__name__}'"
