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
            "Error: claude binary not found on $PATH. Ensure claude is installed and available.",
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
    """Discover plugins within a marketplace directory.

    Scans immediate subdirectories for .claude-plugin/plugin.json files.

    Args:
        marketplace_path: Path to the marketplace directory.

    Returns:
        List of (plugin_name, plugin_path) tuples for each discovered plugin.

    Raises:
        json.JSONDecodeError: If plugin.json exists but contains invalid JSON.
        KeyError: If plugin.json exists but lacks the 'name' field.
    """
    plugins = []
    for entry in sorted(marketplace_path.iterdir()):
        if not entry.is_dir():
            continue
        plugin_json = entry / ".claude-plugin" / "plugin.json"
        if not plugin_json.is_file():
            continue
        with plugin_json.open() as f:
            data = json.load(f)
        plugins.append((data["name"], entry))
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
            f"Error: {env_var} must be a positive integer, got: {timeout_str}",
            file=sys.stderr,
        )
        sys.exit(1)
    if value <= 0:
        print(
            f"Error: {env_var} must be a positive integer, got: {timeout_str}",
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
            f"Error: Timed out after {timeout} seconds registering marketplace {marketplace_path}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        print(
            f"Error: Failed to register marketplace {marketplace_path}: {result.stderr}",
            file=sys.stderr,
        )
        return False
    return True


def install_plugin(claude_bin: str, plugin_name: str, marketplace_name: str) -> bool:
    """Install a plugin via Claude Code CLI.

    Runs: claude plugin install <plugin_name>@<marketplace_name> --scope user

    Args:
        claude_bin: Path to claude binary.
        plugin_name: Name of the plugin (from plugin.json).
        marketplace_name: Name of the marketplace (from marketplace.json).

    Returns:
        True if install succeeded, False otherwise.
    """
    timeout = _get_timeout("CLAUDE_INSTALL_TIMEOUT")
    plugin_ref = f"{plugin_name}@{marketplace_name}"
    try:
        result = subprocess.run(
            [claude_bin, "plugin", "install", plugin_ref, "--scope", "user"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"Error: Timed out after {timeout} seconds installing plugin {plugin_ref}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        print(
            f"Error: Failed to install plugin {plugin_ref}: {result.stderr}",
            file=sys.stderr,
        )
        return False
    return True


def uninstall_plugin(claude_bin: str, plugin_name: str, marketplace_name: str) -> bool:
    """Uninstall a plugin via Claude Code CLI.

    Runs: claude plugin uninstall <plugin_name>@<marketplace_name> --scope user

    Args:
        claude_bin: Path to claude binary.
        plugin_name: Name of the plugin (from plugin.json).
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
            f"Error: Timed out after {timeout} seconds uninstalling plugin {plugin_ref}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        if "not found" in stderr.lower() or "not installed" in stderr.lower():
            print(f"Plugin already uninstalled (not found): {plugin_ref}")
            return True
        print(
            f"Error: Failed to uninstall plugin {plugin_ref}: {stderr}",
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
            f"Error: Timed out after {timeout} seconds removing marketplace {marketplace_name}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        if "not found" in stderr.lower():
            print(f"Marketplace already removed (not found): {marketplace_name}")
            return True
        print(
            f"Error: Failed to remove marketplace {marketplace_name}: {stderr}",
            file=sys.stderr,
        )
        return False
    return True


def install_marketplace_plugins(marketplace_dir: pathlib.Path) -> None:
    """Orchestrate marketplace plugin installation.

    Locates claude binary, discovers marketplace entries, registers each
    marketplace, discovers and installs plugins.

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
    if not entries:
        print("Warning: No marketplace entries found. Nothing to do.", file=sys.stderr)
        return

    marketplaces_processed = 0
    marketplaces_registered = 0
    plugins_installed = 0
    any_failures = False

    for entry in entries:
        marketplaces_processed += 1
        marketplace_name = read_marketplace_name(entry)

        reg_success = register_marketplace(claude_bin, entry)
        if reg_success:
            marketplaces_registered += 1
        else:
            any_failures = True

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
            "Error: Some marketplace operations failed (see errors above).",
            file=sys.stderr,
        )
        sys.exit(1)


def uninstall_marketplace_plugins(marketplace_dir: pathlib.Path) -> None:
    """Orchestrate marketplace plugin uninstallation.

    Locates claude binary, discovers marketplace entries, uninstalls each
    plugin, then removes marketplace registrations.

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
    if not entries:
        print("Warning: No marketplace entries found. Nothing to uninstall.", file=sys.stderr)
        return

    marketplaces_processed = 0
    plugins_uninstalled = 0
    any_failures = False

    for entry in entries:
        marketplaces_processed += 1
        marketplace_name = read_marketplace_name(entry)

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
            "Error: Some marketplace operations failed (see errors above).",
            file=sys.stderr,
        )
        sys.exit(1)
