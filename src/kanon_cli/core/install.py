"""Multi-source Kanon install business logic.

Parses .kanon, validates sources, creates isolated source workspaces
under ``.kanon-data/sources/<name>/``, runs ``repo init``/``envsubst``/``sync``
per source, aggregates symlinks into ``.packages/``, detects collisions,
updates ``.gitignore``, and optionally installs marketplace plugins.
"""

import pathlib
import shutil
import sys

import kanon_cli.repo as _repo
from kanon_cli.core.marketplace import install_marketplace_plugins
from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.repo import RepoCommandError
from kanon_cli.version import resolve_version


def create_source_dirs(
    source_names: list[str],
    base_dir: pathlib.Path,
) -> dict[str, pathlib.Path]:
    """Create .kanon-data/sources/<name>/ directories for each source.

    Args:
        source_names: Ordered list of source names (auto-discovered, alphabetical).
        base_dir: Project root directory.

    Returns:
        Dict mapping source name to its directory path.
    """
    result: dict[str, pathlib.Path] = {}
    for name in source_names:
        source_dir = base_dir / ".kanon-data" / "sources" / name
        source_dir.mkdir(parents=True, exist_ok=True)
        result[name] = source_dir
    return result


def run_repo_init(
    source_dir: pathlib.Path,
    url: str,
    revision: str,
    manifest_path: str,
    repo_rev: str = "",
) -> None:
    """Run ``repo init -u <URL> -b <REVISION> -m <PATH>`` in source directory.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.
        url: Repository URL for repo init.
        revision: Branch/tag/revision for repo init.
        manifest_path: Manifest file path for repo init.
        repo_rev: Repo tool version tag for ``--repo-rev``.

    Raises:
        SystemExit: If repo init exits non-zero.
    """
    try:
        _repo.repo_init(str(source_dir), url, revision, manifest_path, repo_rev)
    except RepoCommandError as exc:
        print(
            f"Error: repo init failed in {source_dir}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def run_repo_envsubst(
    source_dir: pathlib.Path,
    env_vars: dict[str, str],
) -> None:
    """Run ``repo envsubst`` in source directory with exported env vars.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.
        env_vars: Environment variables to export (GITBASE, CLAUDE_MARKETPLACES_DIR).

    Raises:
        SystemExit: If repo envsubst exits non-zero.
    """
    try:
        _repo.repo_envsubst(str(source_dir), env_vars)
    except RepoCommandError as exc:
        print(
            f"Error: repo envsubst failed in {source_dir}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def run_repo_sync(source_dir: pathlib.Path) -> None:
    """Run ``repo sync`` in source directory.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.

    Raises:
        SystemExit: If repo sync exits non-zero.
    """
    try:
        _repo.repo_sync(str(source_dir))
    except RepoCommandError as exc:
        print(
            f"Error: repo sync failed in {source_dir}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def aggregate_symlinks(
    source_names: list[str],
    base_dir: pathlib.Path,
) -> dict[str, str]:
    """Aggregate packages from all sources into ``.packages/``.

    For each ``.kanon-data/sources/<name>/.packages/*``, creates a symlink in
    the top-level ``.packages/`` directory. Detects collisions when two
    sources produce the same package name.

    Args:
        source_names: Ordered list of source names.
        base_dir: Project root directory.

    Returns:
        Dict mapping package name to source name.

    Raises:
        SystemExit: If two sources produce the same package name.
    """
    packages_dir = base_dir / ".packages"
    packages_dir.mkdir(exist_ok=True)

    package_owners: dict[str, str] = {}

    for name in source_names:
        source_packages = base_dir / ".kanon-data" / "sources" / name / ".packages"
        if not source_packages.exists():
            continue
        for pkg in source_packages.iterdir():
            pkg_name = pkg.name
            if pkg_name in package_owners:
                print(
                    f"Error: Package collision for '{pkg_name}': "
                    f"provided by both '{package_owners[pkg_name]}' "
                    f"and '{name}'",
                    file=sys.stderr,
                )
                sys.exit(1)
            package_owners[pkg_name] = name
            link_path = packages_dir / pkg_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(pkg.resolve())

    return package_owners


def update_gitignore(
    base_dir: pathlib.Path,
    entries: list[str] | None = None,
) -> None:
    """Ensure ``.gitignore`` contains the required entries.

    Creates ``.gitignore`` if it does not exist. Appends missing entries
    without duplicating existing ones.

    Args:
        base_dir: Project root directory.
        entries: List of gitignore entries to ensure. Defaults to
            ``.packages/`` and ``.kanon-data/``.
    """
    gitignore = base_dir / ".gitignore"
    required_entries = entries if entries is not None else [".packages/", ".kanon-data/"]

    existing_content = ""
    if gitignore.exists():
        existing_content = gitignore.read_text()

    existing_lines = existing_content.splitlines()
    missing = [entry for entry in required_entries if entry not in existing_lines]

    if missing:
        with gitignore.open("a") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            for entry in missing:
                f.write(f"{entry}\n")


def prepare_marketplace_dir(marketplace_dir: pathlib.Path) -> None:
    """Create and clean the marketplace directory for pre-sync setup.

    Creates the directory if it does not exist, then removes all
    contents for a clean slate before sync.

    Args:
        marketplace_dir: Path to CLAUDE_MARKETPLACES_DIR.
    """
    marketplace_dir.mkdir(parents=True, exist_ok=True)
    for item in marketplace_dir.iterdir():
        if item.is_symlink() or not item.is_dir():
            item.unlink()
        else:
            shutil.rmtree(item)


def _print_package_summary(
    package_owners: dict[str, str],
    source_names: list[str],
) -> None:
    """Print a structured summary of synced packages grouped by source.

    Args:
        package_owners: Dict mapping package name to source name.
        source_names: Ordered list of source names.
    """
    if not package_owners:
        print("\nkanon install: no packages synced.")
        return

    # Group packages by source, preserving source order
    by_source: dict[str, list[str]] = {name: [] for name in source_names}
    for pkg_name, source_name in sorted(package_owners.items()):
        by_source[source_name].append(pkg_name)

    total = len(package_owners)
    print(f"\nkanon install: {total} packages synced to .packages/")
    for source_name in source_names:
        pkgs = by_source[source_name]
        if not pkgs:
            continue
        print(f"\n  [{source_name}] ({len(pkgs)} packages)")
        for pkg in pkgs:
            print(f"    - {pkg}")


def install(kanonenv_path: pathlib.Path) -> None:
    """Execute the full Kanon install lifecycle.

    Steps:
      1. Parse .kanon and validate sources
      2. If KANON_MARKETPLACE_INSTALL=true: create and clean marketplace dir
      3. For each source: mkdir, repo init, envsubst, sync
      4. Aggregate symlinks into .packages/
      5. Update .gitignore
      6. If KANON_MARKETPLACE_INSTALL=true: run install script

    Args:
        kanonenv_path: Path to the .kanon configuration file.

    Raises:
        SystemExit: On any failure during the install process.
    """
    print(f"kanon install: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)
    base_dir = kanonenv_path.parent
    source_names = config["KANON_SOURCES"]
    sources = config["sources"]
    marketplace_install = config["KANON_MARKETPLACE_INSTALL"]
    globals_dict = config["globals"]

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    if marketplace_install and not marketplace_dir_str:
        print(
            "Error: KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined in .kanon",
            file=sys.stderr,
        )
        sys.exit(1)

    if marketplace_install:
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        print("kanon install: preparing marketplace directory...")
        prepare_marketplace_dir(marketplace_dir)

    repo_rev = globals_dict.get("REPO_REV", "")

    env_vars: dict[str, str] = {}
    if "GITBASE" in globals_dict:
        env_vars["GITBASE"] = globals_dict["GITBASE"]
    if marketplace_dir_str:
        env_vars["CLAUDE_MARKETPLACES_DIR"] = marketplace_dir_str

    source_dirs = create_source_dirs(source_names, base_dir)

    for name in source_names:
        source_dir = source_dirs[name]
        source_data = sources[name]
        print(f"kanon install: syncing source '{name}'...")
        resolved_revision = resolve_version(source_data["url"], source_data["revision"])
        print(f"  repo init ({source_data['path']})...")
        run_repo_init(
            source_dir,
            source_data["url"],
            resolved_revision,
            source_data["path"],
            repo_rev,
        )
        print("  repo envsubst...")
        run_repo_envsubst(source_dir, env_vars)
        print("  repo sync...")
        run_repo_sync(source_dir)

    print("kanon install: aggregating packages into .packages/...")
    package_owners = aggregate_symlinks(source_names, base_dir)
    update_gitignore(base_dir)

    _print_package_summary(package_owners, source_names)

    if marketplace_install:
        print("\nkanon install: installing marketplace plugins...")
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        install_marketplace_plugins(marketplace_dir)

    print("\nkanon install: done.")
