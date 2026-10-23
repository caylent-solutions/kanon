"""Shared marketplace operations for Claude Code plugin install/uninstall.

Provides functions for locating the claude binary, discovering marketplace
entries and plugins, and orchestrating plugin install/uninstall lifecycles.
Used by both ``core.install`` (install) and ``core.clean`` (uninstall).
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping


def create_dirsymlink(link_path: pathlib.Path, target: pathlib.Path) -> None:
    """Create a directory symlink, with actionable Windows privilege errors."""
    try:
        os.symlink(target, link_path, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            raise OSError(
                "Kanon requires directory symlinks. Enable Windows Developer Mode "
                "or run with the Create symbolic links privilege."
            ) from exc
        raise


def locate_claude_binary() -> str:
    """Locate the claude CLI binary on $PATH.

    Uses shutil.which("claude") to find the binary.

    Returns:
        Absolute path to the claude binary.

    Raises:
        SystemExit: Exits with code 1 if claude is not found on $PATH.
    """
    path = shutil.which("claude")
    if path is None:
        print(
            "ERROR: claude binary not found on $PATH. Ensure claude is installed and available.",
            file=sys.stderr,
        )
        sys.exit(1)
    return os.path.abspath(path)


def get_marketplace_dir(globals_dict: dict[str, str]) -> pathlib.Path:
    """Return Path to marketplace directory from globals_dict.

    Args:
        globals_dict: Parsed .kanon globals containing CLAUDE_MARKETPLACES_DIR.

    Returns:
        pathlib.Path to the marketplace directory.
    """
    env_value = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")
    if env_value:
        return pathlib.Path(env_value)
    return pathlib.Path.home() / ".claude-marketplaces"


def discover_marketplace_entries(marketplace_dir: pathlib.Path) -> list[pathlib.Path]:
    """Discover marketplace entries in the given directory.

    Returns sorted list of non-hidden entries that are directories or
    symlinks to directories. Hidden entries (dot-prefixed) are excluded.
    Broken symlinks are logged as warnings and excluded.

    Args:
        marketplace_dir: Path to the marketplace directory.

    Returns:
        Alphabetically sorted list of Path objects.
    """
    entries = []
    for entry in sorted(marketplace_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink() and not entry.exists():
            print(
                f"Warning: Broken symlink detected and skipped: {entry}",
                file=sys.stderr,
            )
            continue
        if entry.is_dir():
            entries.append(entry)
    return entries


def filter_owned_marketplace_entries(
    entries: Iterable[pathlib.Path],
    source_roots: Iterable[pathlib.Path],
    copied_json_owners: Mapping[pathlib.Path, pathlib.Path] | None = None,
) -> list[pathlib.Path]:
    """Keep entries whose marketplace metadata belongs to a supplied workspace.

    Resolve the JSON path, not only the entry directory: repo linkfiles may
    create a directory containing a symlinked marketplace.json. This also
    handles a symlink of the whole marketplace root. Source aliases and JSON
    marketplace names are deliberately not used as ownership identifiers.
    Regular copied JSON files use the final delivery owner recorded by repo
    sync's copyfile ledger instead of inferring ownership from their contents.
    """
    roots = tuple(root.resolve() for root in source_roots)
    owned = []
    for entry in entries:
        json_path = (entry / ".claude-plugin" / "marketplace.json").resolve()
        copied_owner = (copied_json_owners or {}).get(json_path)
        if copied_owner is not None:
            if copied_owner.resolve() in roots:
                owned.append(entry)
        elif any(json_path.is_relative_to(root) for root in roots):
            owned.append(entry)
    return owned


def copied_marketplace_json_paths(source_dir: pathlib.Path, marketplace_dir: pathlib.Path) -> list[pathlib.Path]:
    """Read exact marketplace JSON copyfile destinations from repo's sync ledger.

    Only direct marketplace entries under the configured directory qualify.
    The ledger was produced from repo's resolved manifest, so include, removal
    and extension semantics need no second XML implementation here.
    """
    ledger = source_dir / ".repo" / "copy-link-files.json"
    if not ledger.is_file():
        return []
    with ledger.open(encoding="utf-8") as stream:
        deliveries = json.load(stream)
    destinations = deliveries.get("copyfile", [])
    if not isinstance(destinations, list) or any(not isinstance(dest, str) for dest in destinations):
        raise ValueError(f"Invalid copyfile destinations in repo sync ledger: {ledger}")
    root = marketplace_dir.resolve()
    result = []
    for destination in destinations:
        path = pathlib.Path(destination)
        if not path.is_absolute():
            path = source_dir / path
        path = path.resolve()
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root)
        if len(relative.parts) == 3 and relative.parts[1:] == (".claude-plugin", "marketplace.json"):
            result.append(path)
    return result


def read_marketplace_name(marketplace_path: pathlib.Path) -> str:
    """Read marketplace name from .claude-plugin/marketplace.json.

    Args:
        marketplace_path: Path to the marketplace directory.

    Returns:
        The 'name' field from marketplace.json.

    Raises:
        FileNotFoundError: If marketplace.json does not exist.
        KeyError: If 'name' field is missing.
        json.JSONDecodeError: If file is not valid JSON.
    """
    manifest_path = marketplace_path / ".claude-plugin" / "marketplace.json"
    with manifest_path.open() as f:
        data = json.load(f)
    return data["name"]


def discover_plugins(marketplace_path: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """Discover plugins declared in a marketplace's marketplace.json.

    Reads the top-level ``plugins`` array from
    ``.claude-plugin/marketplace.json``. Each entry's ``name`` field becomes
    the plugin name. Entries that are not dicts or that lack a ``name``
    field are skipped silently so that future schema additions do not
    break existing marketplaces.

    Args:
        marketplace_path: Path to the marketplace directory.

    Returns:
        List of ``(plugin_name, marketplace_path)`` tuples for each
        declared plugin. Returns an empty list when ``marketplace.json``
        is absent, has no ``plugins`` key, or has an empty ``plugins``
        array.

    Raises:
        json.JSONDecodeError: If ``marketplace.json`` exists but contains
            invalid JSON.
    """
    manifest_path = marketplace_path / ".claude-plugin" / "marketplace.json"
    if not manifest_path.is_file():
        return []
    with manifest_path.open() as f:
        data = json.load(f)
    plugin_entries = data.get("plugins") or []
    plugins: list[tuple[str, pathlib.Path]] = []
    for entry in plugin_entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        plugins.append((name, marketplace_path))
    return plugins


def _get_timeout(env_var: str, default: int = 30) -> int:
    """Read and validate a timeout from an environment variable.

    Args:
        env_var: Name of the environment variable.
        default: Default timeout in seconds.

    Returns:
        Timeout value in seconds.

    Raises:
        SystemExit: If the value is not a valid positive integer.
    """
    timeout_str = os.environ.get(env_var, str(default))
    try:
        value = int(timeout_str)
    except ValueError:
        print(
            f"ERROR: {env_var} must be a positive integer, got: {timeout_str}",
            file=sys.stderr,
        )
        sys.exit(1)
    if value <= 0:
        print(
            f"ERROR: {env_var} must be a positive integer, got: {timeout_str}",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def register_marketplace(claude_bin: str, marketplace_path: pathlib.Path) -> bool:
    """Register a marketplace with Claude Code.

    Runs: claude plugin marketplace add <absolute-path>

    Args:
        claude_bin: Path to claude binary.
        marketplace_path: Absolute path to marketplace directory.

    Returns:
        True if registration succeeded, False otherwise.
    """
    timeout = _get_timeout("CLAUDE_REGISTER_TIMEOUT")
    try:
        result = subprocess.run(
            [claude_bin, "plugin", "marketplace", "add", str(marketplace_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Timed out after {timeout} seconds registering marketplace {marketplace_path}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        print(
            f"ERROR: Failed to register marketplace {marketplace_path}: {result.stderr}",
            file=sys.stderr,
        )
        return False
    return True


def install_plugin(claude_bin: str, plugin_name: str, marketplace_name: str) -> bool:
    """Install a plugin and refresh it from the registered marketplace.

    Runs ``claude plugin install`` followed by ``claude plugin update``, both
    at user scope. Claude treats installing an existing plugin as a successful
    no-op; the update is required to refresh its cached version after a repin.

    Args:
        claude_bin: Path to claude binary.
        plugin_name: Name of the plugin (from the ``plugins`` array in
            ``marketplace.json``).
        marketplace_name: Name of the marketplace (from marketplace.json).

    Returns:
        True if installation and refresh succeeded, False otherwise.
    """
    timeout = _get_timeout("CLAUDE_INSTALL_TIMEOUT")
    plugin_ref = f"{plugin_name}@{marketplace_name}"
    for action in ("install", "update"):
        try:
            result = subprocess.run(
                [claude_bin, "plugin", action, plugin_ref, "--scope", "user"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            print(
                f"ERROR: Timed out after {timeout} seconds running plugin {action} for {plugin_ref}",
                file=sys.stderr,
            )
            return False

        if result.returncode != 0:
            print(
                f"ERROR: Failed to {action} plugin {plugin_ref}: {result.stderr}",
                file=sys.stderr,
            )
            return False
    return True


def uninstall_plugin(claude_bin: str, plugin_name: str, marketplace_name: str) -> bool:
    """Uninstall a plugin via Claude Code CLI.

    Runs: claude plugin uninstall <plugin_name>@<marketplace_name> --scope user

    Args:
        claude_bin: Path to claude binary.
        plugin_name: Name of the plugin (from the ``plugins`` array in
            ``marketplace.json``).
        marketplace_name: Name of the marketplace (from marketplace.json).

    Returns:
        True if uninstall succeeded, False otherwise.
    """
    timeout = _get_timeout("CLAUDE_UNINSTALL_TIMEOUT")
    plugin_ref = f"{plugin_name}@{marketplace_name}"
    try:
        result = subprocess.run(
            [claude_bin, "plugin", "uninstall", plugin_ref, "--scope", "user"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Timed out after {timeout} seconds uninstalling plugin {plugin_ref}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        if "not found" in stderr.lower() or "not installed" in stderr.lower():
            print(f"Plugin already uninstalled (not found): {plugin_ref}")
            return True
        print(
            f"ERROR: Failed to uninstall plugin {plugin_ref}: {stderr}",
            file=sys.stderr,
        )
        return False
    return True


def remove_marketplace(claude_bin: str, marketplace_name: str) -> bool:
    """Remove a marketplace registration from Claude Code.

    Runs: claude plugin marketplace remove <marketplace_name>

    Args:
        claude_bin: Path to claude binary.
        marketplace_name: Marketplace name (from marketplace.json).

    Returns:
        True if removal succeeded, False otherwise.
    """
    timeout = _get_timeout("CLAUDE_UNINSTALL_TIMEOUT")
    try:
        result = subprocess.run(
            [claude_bin, "plugin", "marketplace", "remove", marketplace_name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Timed out after {timeout} seconds removing marketplace {marketplace_name}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        if "not found" in stderr.lower():
            print(f"Marketplace already removed (not found): {marketplace_name}")
            return True
        print(
            f"ERROR: Failed to remove marketplace {marketplace_name}: {stderr}",
            file=sys.stderr,
        )
        return False
    return True


def register_direct_checkout_marketplaces(
    manifest_xml_path: pathlib.Path,
    source_dir: pathlib.Path,
    marketplace_dir: pathlib.Path,
) -> None:
    """Register direct-checkout marketplace entries that carry no ``<linkfile>`` element.

    Scans every ``<project>`` in the manifest XML that has NO ``<linkfile>``
    children.  For each such project whose checkout directory contains a
    ``.claude-plugin/marketplace.json``, creates a symlink in
    ``marketplace_dir/<name>`` pointing at the project checkout directory.
    This allows ``install_marketplace_plugins`` to discover and register the
    marketplace even though no ``<linkfile>`` placed it there automatically.

    A project without a ``.claude-plugin/marketplace.json`` is silently skipped
    (not an error -- it may be a plain data package, not a marketplace).

    A project that already has at least one ``<linkfile>`` child is skipped
    entirely because ``repo sync`` already materialized every ``<linkfile>``
    as a symlink at its ``dest``
    (:meth:`kanon_cli.repo.project._LinkFile._Link`), which is what puts the
    entry into ``marketplace_dir`` when ``dest`` points there.

    Args:
        manifest_xml_path: Absolute path to the manifest XML file to parse.
        source_dir: Root of the source workspace (project paths are resolved
            relative to this directory).
        marketplace_dir: Path to ``CLAUDE_MARKETPLACES_DIR`` where symlinks
            will be created.

    Raises:
        xml.etree.ElementTree.ParseError: If the manifest XML is malformed.
        OSError: If a symlink cannot be created.
        ValueError: If ``marketplace.json`` exists but lacks a ``name`` field.
        json.JSONDecodeError: If ``marketplace.json`` exists but is malformed.
    """
    if not manifest_xml_path.is_file():
        return

    tree = ET.parse(str(manifest_xml_path))
    root = tree.getroot()

    for project_el in root.findall("project"):
        project_path = project_el.get("path", "")
        if not project_path:
            continue

        if project_el.findall("linkfile"):
            continue

        project_dir = source_dir / project_path
        marketplace_json = project_dir / ".claude-plugin" / "marketplace.json"
        if not marketplace_json.is_file():
            continue

        try:
            marketplace_name = read_marketplace_name(project_dir)
        except KeyError as exc:
            raise ValueError(
                f"ERROR: marketplace.json for project '{project_path}' at"
                f" {project_dir / '.claude-plugin' / 'marketplace.json'}"
                f" is missing the required 'name' field.\n"
                f'Remediation: add a top-level "name" key to that file, e.g.'
                f' {{"name": "<marketplace-name>", "plugins": [...]}}.'
            ) from exc

        link_target = marketplace_dir / marketplace_name

        if link_target.exists() or link_target.is_symlink():
            continue

        marketplace_dir.mkdir(parents=True, exist_ok=True)
        create_dirsymlink(link_target, project_dir.resolve())


def discover_registered_marketplace_names(
    marketplace_dir: pathlib.Path,
    *,
    allowed_source_roots: Iterable[pathlib.Path] | None = None,
    copied_json_owners: Mapping[pathlib.Path, pathlib.Path] | None = None,
) -> list[str]:
    """Discover the marketplace names present under ``marketplace_dir``.

    Walks the directory with :func:`discover_marketplace_entries` and reads each
    entry's marketplace ``name`` via :func:`read_marketplace_name`. Entries that
    lack a ``.claude-plugin/marketplace.json`` are skipped (the same tolerance
    :func:`install_marketplace_plugins` applies to linkfile targets that do not
    point at a marketplace root). The result is the authoritative set of
    marketplace names kanon just registered: it feeds the install auto-prune and
    the ``kanon clean --orphans`` reconciliation. When ``allowed_source_roots``
    is supplied, only entries whose JSON belongs to those workspaces contribute.

    Args:
        marketplace_dir: Path to ``CLAUDE_MARKETPLACES_DIR``.

    Returns:
        A sorted, de-duplicated list of marketplace names. Returns an empty list
        when ``marketplace_dir`` does not exist.

    Raises:
        json.JSONDecodeError: If an entry's ``marketplace.json`` exists but is
            malformed.
        KeyError: If an entry's ``marketplace.json`` exists but lacks ``name``.
    """
    if not marketplace_dir.is_dir():
        return []

    names: set[str] = set()
    entries = discover_marketplace_entries(marketplace_dir)
    if allowed_source_roots is not None:
        entries = filter_owned_marketplace_entries(entries, allowed_source_roots, copied_json_owners)
    for entry in entries:
        try:
            names.add(read_marketplace_name(entry))
        except FileNotFoundError:
            continue
    return sorted(names)


def install_marketplace_plugins(
    marketplace_dir: pathlib.Path,
    *,
    allowed_source_roots: Iterable[pathlib.Path] | None = None,
    copied_json_owners: Mapping[pathlib.Path, pathlib.Path] | None = None,
) -> None:
    """Orchestrate marketplace plugin installation.

    Locates claude binary, discovers marketplace entries, registers each
    marketplace, discovers and installs plugins. ``allowed_source_roots`` limits
    registration to entries whose JSON belongs to an enabled source workspace;
    omitting it preserves standalone directory-wide discovery.

    Args:
        marketplace_dir: Path to CLAUDE_MARKETPLACES_DIR.

    Raises:
        SystemExit: If claude binary not found or any operation fails.
    """
    claude_bin = locate_claude_binary()

    if not marketplace_dir.is_dir():
        print(
            f"Warning: Marketplace directory does not exist: {marketplace_dir}. No marketplaces to register.",
            file=sys.stderr,
        )
        return

    entries = discover_marketplace_entries(marketplace_dir)
    if allowed_source_roots is not None:
        entries = filter_owned_marketplace_entries(entries, allowed_source_roots, copied_json_owners)
    if not entries:
        print("Warning: No marketplace entries found. Nothing to do.", file=sys.stderr)
        return

    marketplaces_processed = 0
    marketplaces_registered = 0
    plugins_installed = 0
    any_failures = False

    for entry in entries:
        marketplaces_processed += 1

        try:
            marketplace_name = read_marketplace_name(entry)
        except FileNotFoundError:
            print(
                f"Warning: Skipping non-marketplace entry {entry}: "
                f".claude-plugin/marketplace.json is absent. "
                f"This is expected for linkfile targets that do not point at a marketplace root.",
                file=sys.stderr,
            )
            continue

        reg_success = register_marketplace(claude_bin, entry)
        if reg_success:
            marketplaces_registered += 1
        else:
            any_failures = True
            continue

        plugins = discover_plugins(entry)
        for plugin_name, _plugin_path in plugins:
            success = install_plugin(claude_bin, plugin_name, marketplace_name)
            if success:
                plugins_installed += 1
            else:
                any_failures = True

    print(
        f"Install summary: {marketplaces_processed} marketplaces processed, "
        f"{marketplaces_registered} registered, {plugins_installed} plugins installed"
    )

    if any_failures:
        print(
            "ERROR: Some marketplace operations failed (see errors above).",
            file=sys.stderr,
        )
        sys.exit(1)


def uninstall_marketplace_plugins(
    marketplace_dir: pathlib.Path,
    *,
    allowed_source_roots: Iterable[pathlib.Path] | None = None,
    copied_json_owners: Mapping[pathlib.Path, pathlib.Path] | None = None,
) -> None:
    """Orchestrate marketplace plugin uninstallation.

    Locates claude binary, discovers marketplace entries, uninstalls each
    plugin, then removes marketplace registrations. When ownership roots are
    supplied, only entries delivered by those last-installed sources are used;
    omitting them preserves the legacy directory-wide teardown.

    Args:
        marketplace_dir: Path to CLAUDE_MARKETPLACES_DIR.

    Raises:
        SystemExit: If claude binary not found or any operation fails.
    """
    claude_bin = locate_claude_binary()

    if not marketplace_dir.is_dir():
        print(
            f"Warning: Marketplace directory does not exist: {marketplace_dir}. No marketplaces to uninstall.",
            file=sys.stderr,
        )
        return

    entries = discover_marketplace_entries(marketplace_dir)
    if allowed_source_roots is not None:
        entries = filter_owned_marketplace_entries(entries, allowed_source_roots, copied_json_owners)
    if not entries:
        print("Warning: No marketplace entries found. Nothing to uninstall.", file=sys.stderr)
        return

    marketplaces_processed = 0
    plugins_uninstalled = 0
    any_failures = False

    for entry in entries:
        marketplaces_processed += 1

        try:
            marketplace_name = read_marketplace_name(entry)
        except FileNotFoundError:
            print(
                f"Warning: Skipping non-marketplace entry {entry}: "
                f".claude-plugin/marketplace.json is absent. "
                f"Nothing to uninstall.",
                file=sys.stderr,
            )
            continue

        plugins = discover_plugins(entry)
        for plugin_name, _plugin_path in plugins:
            success = uninstall_plugin(claude_bin, plugin_name, marketplace_name)
            if success:
                plugins_uninstalled += 1
            else:
                any_failures = True

        remove_success = remove_marketplace(claude_bin, marketplace_name)
        if not remove_success:
            any_failures = True

    print(
        f"Uninstall summary: {marketplaces_processed} marketplace(s) processed, "
        f"{plugins_uninstalled} plugin(s) uninstalled"
    )

    if any_failures:
        print(
            "ERROR: Some marketplace operations failed (see errors above).",
            file=sys.stderr,
        )
        sys.exit(1)
