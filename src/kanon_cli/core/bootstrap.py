"""Bootstrap business logic for scaffolding new Kanon projects.

Provides functions to list available catalog entry packages and copy
them into a target directory with a pre-configured ``.kanon``
configuration file from the catalog.
"""

import pathlib
import shutil
import sys


def list_packages(catalog_dir: pathlib.Path) -> list[str]:
    """List available catalog entry packages from the catalog.

    Args:
        catalog_dir: Path to the catalog directory.

    Returns:
        Sorted list of package names (catalog subdirectory names).
    """
    return sorted(d.name for d in catalog_dir.iterdir() if d.is_dir())


def bootstrap_package(package: str, output_dir: pathlib.Path, catalog_dir: pathlib.Path) -> None:
    """Copy catalog entry package files into the output directory.

    Copies all files from the catalog package directory (including a
    pre-configured ``.kanon``) into the output directory. Refuses to
    overwrite existing files.

    Args:
        package: Name of the catalog entry package (e.g. ``make``, ``gradle``, ``kanon``).
        output_dir: Target directory for the bootstrapped files.
        catalog_dir: Path to the catalog directory.

    Raises:
        SystemExit: If the package is unknown, files already exist, or
            the output directory cannot be created.
    """
    package_dir = catalog_dir / package

    if not package_dir.is_dir():
        available = list_packages(catalog_dir)
        print(
            f"Error: Unknown package '{package}'. Available packages: {', '.join(available)}",
            file=sys.stderr,
        )
        sys.exit(1)

    all_files = [f.name for f in package_dir.iterdir() if f.is_file() and f.name != ".gitkeep"]

    _check_no_conflicts(all_files, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    for src_file in package_dir.iterdir():
        if src_file.is_file() and src_file.name != ".gitkeep":
            shutil.copy2(src_file, output_dir / src_file.name)

    _print_next_steps(package, output_dir, all_files)


def _check_no_conflicts(files: list[str], output_dir: pathlib.Path) -> None:
    """Verify no target files already exist in the output directory.

    Args:
        files: List of filenames to check.
        output_dir: Target directory.

    Raises:
        SystemExit: If any file already exists, listing all conflicts.
    """
    conflicts = [f for f in files if (output_dir / f).exists()]
    if conflicts:
        print("Error: The following files already exist:", file=sys.stderr)
        for f in conflicts:
            print(f"  {output_dir / f}", file=sys.stderr)
        print(
            "\nRemove them first or use a different --output-dir.",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_next_steps(
    package: str,
    output_dir: pathlib.Path,
    files: list[str],
) -> None:
    """Print post-bootstrap instructions.

    Args:
        package: Catalog entry package name.
        output_dir: Directory where files were created.
        files: List of created filenames.
    """
    print(f"kanon bootstrap: created {package} project in {output_dir}/")
    print("\nFiles created:")
    for f in sorted(files):
        print(f"  {output_dir / f}")

    print("\nNext steps:")

    print("  1. Edit .kanon — set GITBASE, KANON_MARKETPLACE_INSTALL, and source variables")
    print("  2. Run: kanon install .kanon")
    print("  3. Commit .kanon to your repository")
