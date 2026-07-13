"""Kanon clean business logic for full teardown.

Performs full Kanon teardown in the following order:
  1. Resolve symlinks in kanonenv_path so teardown targets the real project directory
  2. Determine marketplace state: consult .kanon.lock (marketplace_registered field)
     when present; fall back to the .kanon per-dependency
     KANON_SOURCE_<alias>_MARKETPLACE flags (registered when ANY dependency opts
     in) for old lockfiles or when no lockfile exists (back-compat, AC-8).
  3. Resolve the artifact base directory via resolve_workspace_base_dir: the
     shared KANON_HOME store (<KANON_HOME>/store, default ~/.kanon-home/store), from
     which .packages/ and .kanon-data/ are removed.
  4. If marketplace was registered: uninstall marketplace plugins via claude CLI,
     then remove CLAUDE_MARKETPLACES_DIR.
  5. Remove .packages/ directory (ignore_errors=True)
  6. Remove .kanon-data/ directory (ignore_errors=True)
  7. Prune the content-addressed store entries via prune_store (spec Section 3.5)
"""

import pathlib
import shutil
import sys

from kanon_cli.constants import (
    KANON_HOME_CACHE_SUBDIR,
    KANON_HOME_STORE_SUBDIR,
    SOURCE_MARKETPLACE_KEY,
    resolve_kanon_home,
)
from kanon_cli.core.install import prune_store, resolve_workspace_base_dir
from kanon_cli.core.marketplace import (
    locate_claude_binary,
    remove_marketplace,
    uninstall_marketplace_plugins,
)
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


def remove_store_entries(base_dir: pathlib.Path) -> None:
    """Prune the content-addressed store entries from the KANON_HOME store.

    Delegates to ``prune_store`` (spec Section 3.5 / FR-16): removes the
    content-addressed entries directory plus the per-entry lock roots and the
    publish temp dir, leaving the store base directory itself in place. This is
    the store-prune half of ``kanon clean`` alongside the per-project
    ``.packages/`` and ``.kanon-data/`` removal.

    Args:
        base_dir: The resolved store base directory (``<KANON_HOME>/store``).
    """
    prune_store(base_dir)


def remove_project_config(kanonenv_path: pathlib.Path, lockfile_path: pathlib.Path) -> None:
    """Delete the project ``.kanon`` config file and its ``.kanon.lock`` (``--purge``).

    Both deletes are no-ops when the file is already absent. Removing the
    ``.kanon`` (the project's declared kanon configuration and source of truth)
    plus its lockfile is a full teardown of kanon for the project, invoked only by
    ``kanon clean --purge`` / ``--purge-all``.

    Args:
        kanonenv_path: Resolved path to the project ``.kanon`` file.
        lockfile_path: Path to the sibling ``.kanon.lock``.
    """
    if kanonenv_path.exists():
        print(f"kanon clean: removing .kanon config file {kanonenv_path}...")
    kanonenv_path.unlink(missing_ok=True)
    if lockfile_path.exists():
        print(f"kanon clean: removing {lockfile_path}...")
    lockfile_path.unlink(missing_ok=True)


def remove_kanon_home_store() -> None:
    """Remove the shared kanon home store directory (``kanon clean --purge-all``).

    Removes ONLY kanon-owned content, never arbitrary user data behind a
    misconfigured ``KANON_HOME``. Fails fast (exit 1) when the resolved home is the
    filesystem root, the user home directory, or an ancestor of the user home or
    the current directory. Otherwise it removes only the known kanon-owned subdirs
    (``store/`` and ``cache/``) and then the home root itself, and only when that
    root is left empty; any non-kanon entries are kept with a warning.

    Raises:
        SystemExit: Exit code 1 when the resolved ``KANON_HOME`` is an unsafe path.
    """
    home = resolve_kanon_home().resolve()
    user_home = pathlib.Path.home().resolve()
    cwd = pathlib.Path.cwd().resolve()
    if home == pathlib.Path(home.anchor) or home == user_home or home in user_home.parents or home in cwd.parents:
        print(
            f"Error: refusing to remove the kanon home store at {home}: it resolves to the "
            "filesystem root, your home directory, or a parent of your home or current "
            "directory. Check the KANON_HOME environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not home.exists():
        print(f"kanon clean: kanon home store {home} already absent; skipping.")
        return
    print(f"kanon clean: removing kanon home store {home}...")
    for subdir_name in (KANON_HOME_STORE_SUBDIR, KANON_HOME_CACHE_SUBDIR):
        shutil.rmtree(home / subdir_name, ignore_errors=True)
    remaining = sorted(entry.name for entry in home.iterdir())
    if remaining:
        print(
            f"kanon clean: keeping {home}: it holds non-kanon entries: {', '.join(remaining)}",
            file=sys.stderr,
        )
        return
    home.rmdir()


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


def _prune_orphaned_marketplaces(lockfile: Lockfile | None, current_source_names: list[str]) -> None:
    """Unregister marketplaces of sources removed from ``.kanon`` (orphaned-source prune).

    An orphaned source is a ``[[sources]]`` entry recorded in ``.kanon.lock``
    whose ``name`` no longer appears in the current ``.kanon`` (i.e. it was
    removed via ``kanon remove`` but not yet reconciled away by ``kanon
    install``).  This prunes the marketplaces THOSE sources registered.

    SAFETY INVARIANT: removal candidates are drawn ONLY from the per-source
    ``registered_marketplaces`` ledgers in the lockfile -- the marketplace names
    kanon itself registered.  The directory is never enumerated to remove by
    exclusion, so user/keep-set marketplaces (which were never written to any
    ledger) can never be unregistered.  A marketplace that is ALSO provided by a
    still-referenced source is retained (subtracted from the prune set).

    Each prune candidate is removed via ``remove_marketplace`` (idempotent:
    tolerates an already-absent registration).  The claude binary is located
    lazily -- only when at least one candidate exists -- so an invocation with
    nothing to prune never requires claude on PATH.

    Args:
        lockfile: The parsed lockfile, or None when .kanon.lock is absent.
        current_source_names: Source names declared in the current ``.kanon``.
    """
    if lockfile is None:
        print("kanon clean: no .kanon.lock present; nothing to prune.")
        return

    current = set(current_source_names)
    orphaned_sources = [s for s in lockfile.sources if s.name not in current]
    if not orphaned_sources:
        print("kanon clean: no orphaned sources in .kanon.lock; nothing to prune.")
        return

    referenced: set[str] = set()
    for source in lockfile.sources:
        if source.name in current:
            referenced.update(source.registered_marketplaces)

    orphan_marketplaces: set[str] = set()
    for source in orphaned_sources:
        orphan_marketplaces.update(source.registered_marketplaces)

    prune = sorted(orphan_marketplaces - referenced)
    if not prune:
        print("kanon clean: orphaned sources registered no prunable marketplaces; nothing to prune.")
        return

    print(f"kanon clean: pruning {len(prune)} orphaned marketplace(s)...")
    claude_bin = locate_claude_binary()
    for name in prune:
        print(f"  - unregistering marketplace: {name}")
        remove_marketplace(claude_bin, name)


def clean(
    kanonenv_path: pathlib.Path,
    orphans: bool = False,
    purge: bool = False,
    purge_home: bool = False,
) -> None:
    """Execute the full Kanon clean lifecycle.

    Steps:
      1. Resolve kanonenv_path symlinks so .packages/ and .kanon-data/ are removed
         from the real project directory even when .kanon is a symlink.
      2. Parse .kanon.
      3. Resolve the artifact base directory via ``resolve_workspace_base_dir``:
         the shared ``KANON_HOME`` store (``<KANON_HOME>/store``, default
         ``~/.kanon-home/store``).  This mirrors the resolution used by install so
         clean removes exactly what install wrote.
      4. Determine marketplace state from .kanon.lock (marketplace_registered) when
         present; fall back to the .kanon per-dependency
         KANON_SOURCE_<alias>_MARKETPLACE flags (registered when ANY dependency
         opts in) for old lockfiles or when no lockfile exists.
      5. If marketplace was registered: run uninstall, remove marketplace dir.
      6. Remove .packages/ and .kanon-data/, then prune the content-addressed
         store entries (spec Section 3.5 / FR-16).

    The lockfile-first lookup ensures that an install whose registered set differs
    from the current .kanon flags (e.g. a dependency's
    KANON_SOURCE_<alias>_MARKETPLACE was flipped off after install) is cleaned up
    correctly: the lockfile records the actual install-time state, so clean does
    not rely on the potentially stale .kanon flags.

    Args:
        kanonenv_path: Path to the .kanon configuration file. May be a symlink;
            the path is resolved before use so teardown targets the real project directory.
        orphans: When True, before the normal teardown, unregister the
            marketplaces of any sources recorded in ``.kanon.lock`` that are no
            longer declared in the current ``.kanon`` (pruning them from
            ``~/.claude``).  A marketplace also provided by a still-referenced
            source is retained.  The default (False) leaves the teardown path
            byte-for-byte unchanged.
        purge: When True (``kanon clean --purge`` / ``--purge-all``), also delete
            this project's ``.kanon`` file and ``.kanon.lock`` after the artifact
            teardown. No-op for files that are already absent.
        purge_home: When True (``kanon clean --purge-all``), also remove the shared
            kanon home store directory (``KANON_HOME``): only its kanon-owned
            subdirs (``store/``, ``cache/``) plus the emptied root, refusing unsafe
            paths. Implies ``purge``.

    Raises:
        SystemExit: On any failure during the clean process.
    """
    kanonenv_path = kanonenv_path.resolve()
    print(f"kanon clean: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)
    base_dir = resolve_workspace_base_dir()

    kanon_flag_marketplace_install = any(bool(source[SOURCE_MARKETPLACE_KEY]) for source in config["sources"].values())
    globals_dict = config["globals"]

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    lockfile_path = kanonenv_path.parent / ".kanon.lock"
    lockfile = _read_lockfile_if_present(lockfile_path)

    if orphans:
        current_source_names = config["KANON_SOURCES"]
        _prune_orphaned_marketplaces(lockfile, current_source_names)

    if lockfile is not None and lockfile.marketplace_registered:
        effective_marketplace_install = True
        effective_marketplace_dir_str = lockfile.marketplace_dir
    else:
        effective_marketplace_install = kanon_flag_marketplace_install
        effective_marketplace_dir_str = marketplace_dir_str

    if effective_marketplace_install and not effective_marketplace_dir_str:
        print(
            "Error: a KANON_SOURCE_<alias>_MARKETPLACE=true dependency is declared "
            "but CLAUDE_MARKETPLACES_DIR is not defined in .kanon",
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
    print("kanon clean: pruning content-addressed store entries...")
    remove_store_entries(base_dir)
    if purge:
        remove_project_config(kanonenv_path, lockfile_path)
    if purge_home:
        remove_kanon_home_store()
    print("kanon clean: done.")
