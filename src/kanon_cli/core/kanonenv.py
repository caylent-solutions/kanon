"""Multi-source .kanon file parser.

Parses KEY=VALUE configuration files used by Kanon bootstrap. The .kanon
format supports:
  - Comments (lines starting with #) and blank lines
  - Shell variable expansion (``${VAR}``) resolved from environment
  - Environment variable overrides (env vars take precedence over file values)
  - Auto-discovered named source groups from ``KANON_SOURCE_<name>_URL`` keys
  - Boolean parsing for KANON_MARKETPLACE_INSTALL

Source names are auto-discovered by scanning for keys matching the
``KANON_SOURCE_<name>_URL`` pattern. Names are sorted alphabetically for
deterministic ordering. Each discovered source must also define
``KANON_SOURCE_<name>_REVISION`` and ``KANON_SOURCE_<name>_PATH``.

The parser reads the file, applies environment overrides, expands shell
variables, validates required fields, and returns a structured dict.
"""

import os
import pathlib
import re

from kanon_cli.constants import (
    SHELL_VAR_PATTERN,
    SOURCE_PREFIX,
    SOURCE_SUFFIXES,
    SUFFIX_TO_KEY,
)


def parse_kanonenv(path: pathlib.Path) -> dict:
    """Parse a .kanon file into a structured configuration dict.

    Reads KEY=VALUE pairs from the file, applies environment variable
    overrides, expands shell variables (``${VAR}``), auto-discovers
    source names from ``KANON_SOURCE_<name>_URL`` keys, and groups
    source-specific variables.

    Args:
        path: Path to the .kanon file.

    Returns:
        A dict with the following keys:

        - ``KANON_SOURCES``: list of source names (auto-discovered,
          sorted alphabetically)
        - ``KANON_MARKETPLACE_INSTALL``: bool (defaults to False)
        - ``sources``: dict mapping each source name to a dict with
          ``url``, ``revision``, and ``path`` keys
        - ``globals``: dict of all other KEY=VALUE pairs

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If KANON_SOURCES is explicitly set (no longer supported),
            if no sources are discovered, if a named source is missing
            required variables (URL, REVISION, PATH), or if a shell
            variable reference cannot be resolved.
    """
    if not path.exists():
        msg = f".kanon file not found: {path}"
        raise FileNotFoundError(msg)

    raw_vars = _read_key_value_pairs(path)
    merged = _apply_env_overrides(raw_vars)
    expanded = _expand_shell_variables(merged)

    return _build_result(expanded)


def _read_key_value_pairs(path: pathlib.Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a file, ignoring comments and blanks.

    Args:
        path: Path to the .kanon file.

    Returns:
        Dict of raw string key-value pairs.
    """
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def _apply_env_overrides(raw_vars: dict[str, str]) -> dict[str, str]:
    """Override file values with environment variables of the same name.

    Args:
        raw_vars: Dict of KEY=VALUE pairs from the file.

    Returns:
        Dict with environment overrides applied.
    """
    merged = dict(raw_vars)
    for key in merged:
        env_value = os.environ.get(key)
        if env_value is not None:
            merged[key] = env_value
    # Also check for env vars that define source groups not in the file
    for key, value in os.environ.items():
        if key.startswith(SOURCE_PREFIX) and key not in merged:
            merged[key] = value
    return merged


def _expand_shell_variables(merged: dict[str, str]) -> dict[str, str]:
    """Expand ``${VAR}`` references in values using environment variables.

    Args:
        merged: Dict of KEY=VALUE pairs with overrides applied.

    Returns:
        Dict with shell variables expanded.

    Raises:
        ValueError: If a referenced variable is not defined in
            the environment.
    """
    expanded: dict[str, str] = {}
    for key, value in merged.items():
        expanded[key] = _expand_value(value)
    return expanded


def _expand_value(value: str) -> str:
    """Expand all ``${VAR}`` references in a single value.

    Args:
        value: The raw value string potentially containing ${VAR}.

    Returns:
        The value with all variables expanded.

    Raises:
        ValueError: If a referenced variable is not in the environment.
    """

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            msg = f"Undefined shell variable '${{{var_name}}}' referenced in .kanon value"
            raise ValueError(msg)
        return env_val

    return SHELL_VAR_PATTERN.sub(_replace, value)


def _discover_source_names(expanded: dict[str, str]) -> list[str]:
    """Auto-discover source names from ``KANON_SOURCE_<name>_URL`` keys.

    Scans all keys for the ``KANON_SOURCE_<name>_URL`` pattern, extracts
    the ``<name>`` portion, and returns a sorted list for deterministic
    ordering.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.

    Returns:
        Sorted list of discovered source names.

    Raises:
        ValueError: If no ``KANON_SOURCE_<name>_URL`` keys are found.
    """
    url_suffix = "_URL"
    names: list[str] = []
    for key in expanded:
        if key.startswith(SOURCE_PREFIX) and key.endswith(url_suffix):
            name = key[len(SOURCE_PREFIX) : -len(url_suffix)]
            if name:
                names.append(name)

    if not names:
        msg = (
            "No sources found. Define at least one source using "
            "KANON_SOURCE_<name>_URL, KANON_SOURCE_<name>_REVISION, "
            "and KANON_SOURCE_<name>_PATH variables in .kanon"
        )
        raise ValueError(msg)

    return sorted(names)


def _build_result(expanded: dict[str, str]) -> dict:
    """Build the structured result dict from expanded variables.

    Auto-discovers source names from ``KANON_SOURCE_<name>_URL`` keys
    and sorts them alphabetically. Raises an error if ``KANON_SOURCES``
    is explicitly defined (no longer supported).

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.

    Returns:
        Structured dict with KANON_SOURCES (auto-discovered), sources,
        globals, and KANON_MARKETPLACE_INSTALL.

    Raises:
        ValueError: If KANON_SOURCES is explicitly set, if no sources
            are discovered, or if a named source is missing required
            variables.
    """
    if "KANON_SOURCES" in expanded:
        msg = (
            "KANON_SOURCES is no longer supported. Source names are "
            "auto-discovered from KANON_SOURCE_<name>_URL variables. "
            "Remove the KANON_SOURCES line from your .kanon file."
        )
        raise ValueError(msg)

    source_names = _discover_source_names(expanded)
    sources = _extract_sources(expanded, source_names)
    globals_dict = _extract_globals(expanded, source_names)
    marketplace_install = _parse_bool(expanded.get("KANON_MARKETPLACE_INSTALL", "false"))

    return {
        "KANON_SOURCES": source_names,
        "KANON_MARKETPLACE_INSTALL": marketplace_install,
        "sources": sources,
        "globals": globals_dict,
    }


def validate_sources(
    expanded: dict[str, str],
    source_names: list[str],
) -> None:
    """Validate that all named sources have required variables.

    Each source name in ``source_names`` must have three corresponding
    variables defined in ``expanded``:
      - ``KANON_SOURCE_<name>_URL``
      - ``KANON_SOURCE_<name>_REVISION``
      - ``KANON_SOURCE_<name>_PATH``

    Args:
        expanded: Dict of expanded KEY=VALUE pairs from the .kanon file.
        source_names: List of source names (auto-discovered, alphabetical).

    Raises:
        ValueError: If any named source is missing a required variable.
            The error message includes both the source name and the
            missing variable name for actionable diagnostics.
    """
    for name in source_names:
        for suffix in SOURCE_SUFFIXES:
            var_name = f"{SOURCE_PREFIX}{name}{suffix}"
            if var_name not in expanded:
                msg = f"Missing required variable '{var_name}' for source '{name}'"
                raise ValueError(msg)


def _extract_sources(
    expanded: dict[str, str],
    source_names: list[str],
) -> dict[str, dict[str, str]]:
    """Extract named source groups after validation.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.
        source_names: List of source names (auto-discovered, alphabetical).

    Returns:
        Dict mapping source name to {url, revision, path}.

    Raises:
        ValueError: If a source is missing a required variable.
    """
    validate_sources(expanded, source_names)
    sources: dict[str, dict[str, str]] = {}
    for name in source_names:
        source_data: dict[str, str] = {}
        for suffix in SOURCE_SUFFIXES:
            var_name = f"{SOURCE_PREFIX}{name}{suffix}"
            result_key = SUFFIX_TO_KEY[suffix]
            source_data[result_key] = expanded[var_name]
        sources[name] = source_data
    return sources


def _extract_globals(
    expanded: dict[str, str],
    source_names: list[str],
) -> dict[str, str]:
    """Extract non-source, non-special variables as globals.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.
        source_names: List of source names (auto-discovered, alphabetical).

    Returns:
        Dict of global variables (excludes KANON_MARKETPLACE_INSTALL
        and source-specific variables).
    """
    source_keys: set[str] = set()
    for name in source_names:
        for suffix in SOURCE_SUFFIXES:
            source_keys.add(f"{SOURCE_PREFIX}{name}{suffix}")

    special_keys = {"KANON_MARKETPLACE_INSTALL"}
    exclude = source_keys | special_keys

    return {k: v for k, v in expanded.items() if k not in exclude}


def _parse_bool(value: str) -> bool:
    """Parse a string boolean value (case-insensitive).

    Args:
        value: String value to parse ('true' or 'false').

    Returns:
        True if value is 'true' (case-insensitive), False otherwise.
    """
    return value.strip().lower() == "true"
