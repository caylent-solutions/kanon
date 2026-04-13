"""Kanon clean business logic for full teardown.

Performs full Kanon teardown in the following order:
  1. If KANON_MARKETPLACE_INSTALL=true:
     uninstall marketplace plugins via claude CLI
  2. If KANON_MARKETPLACE_INSTALL=true:
     remove CLAUDE_MARKETPLACES_DIR
  3. Remove .packages/ directory (ignore_errors=True)
  4. Remove .kanon-data/ directory (ignore_errors=True)
"""

import pathlib
import shutil
import sys

from kanon_cli.core.marketplace import uninstall_marketplace_plugins
from kanon_cli.core.kanonenv import parse_kanonenv


def remove_marketplace_dir(marketplace_dir: pathlib.Path) -> None:
    """Remove the marketplace directory if it exists.

    Args:
        marketplace_dir: Path to CLAUDE_MARKETPLACES_DIR.
    """
    if marketplace_dir.exists():
        shutil.rmtree(marketplace_dir)


def remove_packages_dir(base_dir: pathlib.Path) -> None:
    """Remove .packages/ directory with ignore_errors.

    Args:
        base_dir: Project root directory.
    """
    shutil.rmtree(base_dir / ".packages", ignore_errors=True)


def remove_kanon_dir(base_dir: pathlib.Path) -> None:
    """Remove .kanon-data/ directory with ignore_errors.

    Args:
        base_dir: Project root directory.
    """
    shutil.rmtree(base_dir / ".kanon-data", ignore_errors=True)


def _print_remove_summary(packages_dir: pathlib.Path) -> None:
    """Print a summary of packages that will be removed.

    Args:
        packages_dir: Path to ``.packages/`` directory.
    """
    if not packages_dir.exists():
        print("kanon clean: no packages to remove.")
        return

    pkgs = sorted(p.name for p in packages_dir.iterdir() if not p.name.startswith("."))
    if not pkgs:
        print("kanon clean: no packages to remove.")
        return

    print(f"kanon clean: removing {len(pkgs)} packages...")
    for pkg in pkgs:
        print(f"  - {pkg}")


def clean(kanonenv_path: pathlib.Path) -> None:
    """Execute the full Kanon clean lifecycle.

    Steps:
      1. Parse .kanon
      2. If KANON_MARKETPLACE_INSTALL=true: run uninstall, remove marketplace dir
      3. Remove .packages/ and .kanon-data/

    Args:
        kanonenv_path: Path to the .kanon configuration file.

    Raises:
        SystemExit: On any failure during the clean process.
    """
    print(f"kanon clean: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)
    base_dir = kanonenv_path.parent
    marketplace_install = config["KANON_MARKETPLACE_INSTALL"]
    globals_dict = config["globals"]

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    if marketplace_install and not marketplace_dir_str:
        print(
            "Error: KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined in .kanon",
            file=sys.stderr,
        )
        sys.exit(1)

    packages_dir = base_dir / ".packages"
    _print_remove_summary(packages_dir)

    if marketplace_install:
        print("kanon clean: running marketplace uninstall...")
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        uninstall_marketplace_plugins(marketplace_dir)
        print("kanon clean: removing marketplace directory...")
        remove_marketplace_dir(marketplace_dir)

    print("kanon clean: removing .packages/...")
    remove_packages_dir(base_dir)
    print("kanon clean: removing .kanon-data/...")
    remove_kanon_dir(base_dir)
    print("kanon clean: done.")
