"""Kanon clean business logic for full teardown.

Performs full Kanon teardown in the following order:
  1. Resolve symlinks in kanonenv_path so teardown targets the real project directory
  2. Determine marketplace state: consult .kanon.lock (marketplace_registered field)
     when present; fall back to the .kanon KANON_MARKETPLACE_INSTALL flag for old
     lockfiles or when no lockfile exists (back-compat, AC-8).
  3. If marketplace was registered: uninstall marketplace plugins via claude CLI,
     then remove CLAUDE_MARKETPLACES_DIR.
  4. Remove .packages/ directory (ignore_errors=True)
  5. Remove .kanon-data/ directory (ignore_errors=True)
"""

import pathlib
import shutil
import sys

from kanon_cli.core.marketplace import uninstall_marketplace_plugins
from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.core.lockfile import Lockfile, read_lockfile


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


def _read_lockfile_if_present(lockfile_path: pathlib.Path) -> Lockfile | None:
    """Read the lockfile if it exists; return None when the file is absent.

    A lockfile that predates the marketplace_registered field (schema v1) is
    automatically migrated to v2 by the reader (marketplace_registered=False).
    Schema errors (forward-incompatible lockfile, validation failures) are
    propagated because they indicate a corrupt or incompatible file that the
    operator must fix explicitly.

    Args:
        lockfile_path: Expected path of the .kanon.lock file.

    Returns:
        A parsed Lockfile, or None if the file does not exist.

    Raises:
        LockfileSchemaError: When the lockfile's schema is forward-incompatible
            (written by a newer kanon) and cannot be read.
        LockfileValidationError: When a field value in the lockfile fails
            validation.
    """
    if not lockfile_path.exists():
        return None
    return read_lockfile(lockfile_path)


def clean(kanonenv_path: pathlib.Path) -> None:
    """Execute the full Kanon clean lifecycle.

    Steps:
      1. Resolve kanonenv_path symlinks so .packages/ and .kanon-data/ are removed
         from the real project directory even when .kanon is a symlink.
      2. Parse .kanon.
      3. Determine marketplace state from .kanon.lock (marketplace_registered) when
         present; fall back to the .kanon KANON_MARKETPLACE_INSTALL flag for old
         lockfiles or when no lockfile exists.
      4. If marketplace was registered: run uninstall, remove marketplace dir.
      5. Remove .packages/ and .kanon-data/.

    The lockfile-first lookup ensures that an env-override install
    (KANON_MARKETPLACE_INSTALL=true at install time, while .kanon stores false) is
    cleaned up correctly: the lockfile records the actual install-time state, so
    clean does not rely on the potentially stale .kanon flag.

    Args:
        kanonenv_path: Path to the .kanon configuration file. May be a symlink;
            the path is resolved before use so teardown targets the real project directory.

    Raises:
        SystemExit: On any failure during the clean process.
    """
    kanonenv_path = kanonenv_path.resolve()
    print(f"kanon clean: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)
    base_dir = kanonenv_path.parent
    kanon_flag_marketplace_install = config["KANON_MARKETPLACE_INSTALL"]
    globals_dict = config["globals"]

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    # Determine whether a marketplace was registered, preferring lockfile state
    # over the .kanon flag so that env-override installs are cleaned up correctly.
    lockfile_path = base_dir / ".kanon.lock"
    lockfile = _read_lockfile_if_present(lockfile_path)

    if lockfile is not None and lockfile.marketplace_registered:
        # Lockfile records a registration -- use its stored directory.
        effective_marketplace_install = True
        effective_marketplace_dir_str = lockfile.marketplace_dir
    else:
        # No lockfile, or lockfile lacks a registration (old lockfile migrated to
        # marketplace_registered=False, or fresh install with false).  Fall back to
        # the .kanon flag for back-compat (AC-8).
        effective_marketplace_install = kanon_flag_marketplace_install
        effective_marketplace_dir_str = marketplace_dir_str

    if effective_marketplace_install and not effective_marketplace_dir_str:
        print(
            "Error: KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined in .kanon",
            file=sys.stderr,
        )
        sys.exit(1)

    packages_dir = base_dir / ".packages"
    _print_remove_summary(packages_dir)

    if effective_marketplace_install:
        marketplace_dir = pathlib.Path(effective_marketplace_dir_str)
        if not marketplace_dir.exists():
            print(f"kanon clean: marketplace directory {marketplace_dir} already absent; skipping uninstall.")
        else:
            print("kanon clean: running marketplace uninstall...")
            uninstall_marketplace_plugins(marketplace_dir)
            print("kanon clean: removing marketplace directory...")
            remove_marketplace_dir(marketplace_dir)

    print("kanon clean: removing .packages/...")
    remove_packages_dir(base_dir)
    print("kanon clean: removing .kanon-data/...")
    remove_kanon_dir(base_dir)
    print("kanon clean: done.")
