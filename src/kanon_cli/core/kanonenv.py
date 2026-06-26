"""Multi-source .kanon file parser.

Parses KEY=VALUE configuration files used by Kanon. The .kanon
format supports:
  - Comments (lines starting with #) and blank lines
  - Shell variable expansion (``${VAR}``) resolved from environment
  - Environment variable overrides (env vars take precedence over file values)
  - Auto-discovered alias-keyed source groups from ``KANON_SOURCE_<alias>_URL`` keys
  - Per-dependency boolean parsing for the optional
    ``KANON_SOURCE_<alias>_MARKETPLACE`` flag (absence == false)

Source aliases are auto-discovered by scanning for keys matching the
``KANON_SOURCE_<alias>_URL`` pattern. Aliases are sorted alphabetically for
deterministic ordering. Each discovered source must also define
``KANON_SOURCE_<alias>_REF`` (the verbatim version spec),
``KANON_SOURCE_<alias>_PATH`` (the repo-relative manifest path), and
``KANON_SOURCE_<alias>_NAME`` (the original catalog manifest name).

Beyond the required structural suffixes (``_URL``/``_REF``/``_PATH``/``_NAME``)
and the reserved ``_MARKETPLACE`` flag, any other
``KANON_SOURCE_<alias>_<VAR>`` key is collected into the source's open,
optional per-dependency env-var map (``source_data["env"][VAR] = value``).
These env vars feed the manifest's ``${VAR}`` substitution at install time
(``GITBASE`` is the common case). Missing env vars never fail the parse: a
source declares an env var only when its manifest references the matching
``${VAR}`` placeholder.

If a partial source definition is found (any required non-URL structural
suffix present without a corresponding ``_URL``), a ``ValueError`` is raised
naming the exact missing ``KANON_SOURCE_<alias>_URL`` variable so callers can
surface it to stderr verbatim.

The parser reads the file, applies environment overrides, expands shell
variables, validates required fields, and returns a structured dict.

Security guards are applied before any data is returned:
  - Symlink detection (TOCTOU mitigation): the .kanon file must not be a symlink.
  - Permission check: the .kanon file must not be writable by anyone other than
    its owner. On POSIX this rejects the group-write and world-write mode bits.
    The control is never silently skipped.
  - Path traversal rejection: KANON_SOURCE_<name>_PATH values must not contain '..'.
"""

import os
import pathlib
import re
import stat

from kanon_cli.constants import (
    MARKETPLACE_DIR_GLOBAL_KEY,
    SHELL_VAR_PATTERN,
    SOURCE_ENV_KEY,
    SOURCE_MARKETPLACE_KEY,
    SOURCE_MARKETPLACE_SUFFIX,
    SOURCE_NON_URL_SUFFIXES,
    SOURCE_PREFIX,
    SOURCE_RESERVED_SUFFIXES,
    SOURCE_SUFFIXES,
    SOURCE_URL_SUFFIX,
    SUFFIX_TO_KEY,
)


_UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH


_PATH_SUFFIX = "_PATH"


class NoSourcesError(ValueError):
    """Raised when a .kanon file declares zero source triples.

    Subclasses ``ValueError`` so that every existing ``except ValueError``
    handler (e.g. commands/install.py::_run, commands/clean.py::_run) and the
    top-level CLI user-error boundary continue to treat it as a clean user
    error. The dedicated type lets callers that need to distinguish the
    zero-source case (e.g. ``kanon doctor``'s structured NO_SOURCES finding)
    catch it precisely without matching on the message string.
    """


def parse_kanonenv(path: pathlib.Path) -> dict:
    """Parse a .kanon file into a structured configuration dict.

    Reads KEY=VALUE pairs from the file, applies environment variable
    overrides, expands shell variables (``${VAR}``), auto-discovers
    source names from ``KANON_SOURCE_<name>_URL`` keys, and groups
    source-specific variables.

    Security guards are applied before returning:
      - Symlink TOCTOU: the file must not be a symlink.
      - Permissions: the file must not be writable by anyone other than its
        owner. On POSIX the group-write and world-write mode bits are rejected.
        The control is never skipped.
      - Path traversal: no KANON_SOURCE_<name>_PATH value may contain '..'.

    Args:
        path: Path to the .kanon file.

    Returns:
        A dict with the following keys:

        - ``KANON_SOURCES``: list of source names (auto-discovered,
          sorted alphabetically)
        - ``sources``: dict mapping each source alias to a dict with the
          required ``url``, ``ref``, ``path``, ``name`` keys, a
          ``marketplace`` bool (the per-dependency
          ``KANON_SOURCE_<alias>_MARKETPLACE`` flag; defaults to False), and an
          ``env`` dict mapping each optional per-dependency env-var name to its
          value (every ``KANON_SOURCE_<alias>_<VAR>`` key whose ``<VAR>`` is not
          a reserved structural/marketplace suffix; empty when the source
          declares no env vars)
        - ``globals``: dict of all other KEY=VALUE pairs

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is a symlink, if the file has unsafe
            permissions (group-writable or world-writable), if any
            KANON_SOURCE_<alias>_PATH value contains '..', if
            KANON_SOURCES is explicitly set (no longer supported),
            if no sources are discovered, if a named source is missing a
            required structural variable (URL, REF, PATH, NAME), or if a shell
            variable reference cannot be resolved.
    """
    if not path.exists():
        msg = f".kanon file not found: {path}"
        raise FileNotFoundError(msg)

    _check_no_symlink(path)
    _check_write_permission(path)

    raw_vars = _read_key_value_pairs(path)
    _check_no_path_traversal(raw_vars)
    merged = _apply_env_overrides(raw_vars)
    expanded = _expand_shell_variables(merged)

    return _build_result(expanded)


def _check_no_symlink(path: pathlib.Path) -> None:
    """Raise ValueError if the .kanon file is a symbolic link.

    Any symlink introduces a TOCTOU (time-of-check/time-of-use) race
    because the target can be replaced between the resolution check and
    the open call. All symlinks are rejected regardless of target location.

    Args:
        path: Path to the .kanon file.

    Raises:
        ValueError: If the path is a symbolic link.
    """
    if path.is_symlink():
        msg = (
            f".kanon file must not be a symlink: {path}. "
            "Symlinks introduce a TOCTOU race -- use a regular file instead."
        )
        raise ValueError(msg)


def _check_write_permission(path: pathlib.Path) -> None:
    """Reject a .kanon file that is writable by anyone other than its owner.

    Applies the POSIX mode-bit write-permission control
    (``_check_permissions``), which rejects the group-write and world-write
    bits. The control fails fast with an actionable ``ValueError`` and is never
    a silent no-op.

    Args:
        path: Path to the .kanon file.

    Raises:
        ValueError: If the file grants write access beyond its owner
            (group-writable or world-writable).
    """
    _check_permissions(path)


def _check_permissions(path: pathlib.Path) -> None:
    """Raise ValueError if the .kanon file has group-write or world-write bits set.

    World-writable or group-writable .kanon files can be tampered with by
    unprivileged users, which could lead to privilege escalation or supply
    chain attacks. Only owner-write access is permitted.

    Args:
        path: Path to the .kanon file.

    Raises:
        ValueError: If the file has group-write or world-write permission bits.
    """
    mode = path.stat().st_mode
    if mode & _UNSAFE_WRITE_BITS:
        insecure_bits: list[str] = []
        if mode & stat.S_IWGRP:
            insecure_bits.append("group-writable")
        if mode & stat.S_IWOTH:
            insecure_bits.append("world-writable")
        bits_description = " and ".join(insecure_bits)
        msg = (
            f".kanon file has insecure permissions ({bits_description}): {path}. "
            "Remove group-write and world-write bits (e.g. chmod 600 or chmod 644)."
        )
        raise ValueError(msg)


def _check_no_path_traversal(raw_vars: dict[str, str]) -> None:
    """Raise ValueError if any KANON_SOURCE_<name>_PATH value contains '..'.

    Path traversal sequences allow an attacker to reference files outside
    the intended project directory. All PATH values are validated before
    any further processing occurs.

    Args:
        raw_vars: Dict of raw KEY=VALUE pairs read from the .kanon file.

    Raises:
        ValueError: If any KANON_SOURCE_<name>_PATH value contains '..'.
    """
    for key, value in raw_vars.items():
        if key.startswith(SOURCE_PREFIX) and key.endswith(_PATH_SUFFIX):
            if ".." in value.split("/"):
                msg = (
                    f"Path traversal detected in {key}={value!r}. "
                    "KANON_SOURCE_<name>_PATH values must not contain '..' components."
                )
                raise ValueError(msg)


def _read_key_value_pairs(path: pathlib.Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a file, ignoring comments and blanks.

    Args:
        path: Path to the .kanon file.

    Returns:
        Dict of raw string key-value pairs.

    Raises:
        PermissionError: If the file cannot be read due to insufficient permissions.
        ValueError: If the same key appears more than once in the file.
    """
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        clean_key = key.strip()
        if clean_key in result:
            msg = f"Duplicate key '{clean_key}' in {path}"
            raise ValueError(msg)
        result[clean_key] = value.strip()
    return result


def _apply_env_overrides(raw_vars: dict[str, str]) -> dict[str, str]:
    """Override file values with environment variables of the same name.

    Every key already present in the file is overridden by an OS environment
    variable of the same name when one is set. Beyond that, two classes of key
    are *adopted* from the OS environment even when absent from the file:

    - any ``KANON_SOURCE_<alias>_<VAR>`` key (the alias-scoped source model); and
    - the single global ``CLAUDE_MARKETPLACES_DIR`` key.

    ``CLAUDE_MARKETPLACES_DIR`` is a single, environment-specific path (one per
    machine / user), so per 12-factor it is resolved from the OS environment
    rather than requiring a hand-written ``.kanon`` line. A ``.kanon`` value
    takes precedence as an explicit override when present: it is exempt from the
    same-name-override pass so the file value is never clobbered by the OS env;
    the adoption pass below only fills the key from the OS env when ``.kanon``
    declares no value for it.

    Args:
        raw_vars: Dict of KEY=VALUE pairs from the file.

    Returns:
        Dict with environment overrides applied.
    """
    merged = dict(raw_vars)
    for key in merged:
        if key == MARKETPLACE_DIR_GLOBAL_KEY:
            continue
        env_value = os.environ.get(key)
        if env_value is not None:
            merged[key] = env_value

    for key, value in os.environ.items():
        if key.startswith(SOURCE_PREFIX) and key not in merged:
            merged[key] = value

    if MARKETPLACE_DIR_GLOBAL_KEY not in merged:
        marketplace_dir_value = os.environ.get(MARKETPLACE_DIR_GLOBAL_KEY)
        if marketplace_dir_value is not None:
            merged[MARKETPLACE_DIR_GLOBAL_KEY] = marketplace_dir_value
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
    """Auto-discover source aliases from ``KANON_SOURCE_<alias>_URL`` keys.

    Scans all keys for the ``KANON_SOURCE_<alias>_URL`` pattern, extracts
    the ``<alias>`` portion, and returns a sorted list for deterministic
    ordering.

    Also scans for keys matching any required structural non-URL suffix
    (``KANON_SOURCE_<alias>_(REF|PATH|NAME)``) to detect sources that are
    partially defined without a URL; raises ``ValueError`` naming the exact
    missing URL variable so callers can surface it verbatim. Optional
    per-dependency env-var keys (e.g. ``_GITBASE``) never imply a source on
    their own and never trigger this partial-source error.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.

    Returns:
        Sorted list of discovered source aliases.

    Raises:
        NoSourcesError: If no ``KANON_SOURCE_<alias>_URL`` keys are found
            (a ``ValueError`` subclass; the zero-source case).
        ValueError: If a source alias is inferred from a non-URL suffix but the
            corresponding ``KANON_SOURCE_<alias>_URL`` key is absent.
    """
    url_names: set[str] = set()
    for key in expanded:
        if key.startswith(SOURCE_PREFIX) and key.endswith(SOURCE_URL_SUFFIX):
            name = key[len(SOURCE_PREFIX) : -len(SOURCE_URL_SUFFIX)]
            if name:
                url_names.add(name)

    candidate_names: set[str] = set()
    for key in expanded:
        if key.startswith(SOURCE_PREFIX):
            for suffix in SOURCE_NON_URL_SUFFIXES:
                if key.endswith(suffix):
                    name = key[len(SOURCE_PREFIX) : -len(suffix)]
                    if name:
                        candidate_names.add(name)

    for name in sorted(candidate_names - url_names):
        url_var = f"{SOURCE_PREFIX}{name}{SOURCE_URL_SUFFIX}"
        msg = f"{url_var} is required but not set"
        raise ValueError(msg)

    if not url_names:
        msg = (
            "No sources found. Define at least one source using "
            "KANON_SOURCE_<alias>_URL, KANON_SOURCE_<alias>_REF, "
            "KANON_SOURCE_<alias>_PATH, and KANON_SOURCE_<alias>_NAME "
            "variables in .kanon"
        )
        raise NoSourcesError(msg)

    return sorted(url_names)


def _build_result(expanded: dict[str, str]) -> dict:
    """Build the structured result dict from expanded variables.

    Auto-discovers source names from ``KANON_SOURCE_<name>_URL`` keys
    and sorts them alphabetically. Raises an error if ``KANON_SOURCES``
    is explicitly defined (no longer supported).

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.

    Returns:
        Structured dict with KANON_SOURCES (auto-discovered), sources (each
        carrying its per-dependency ``marketplace`` flag and open ``env`` map),
        and globals. There is no global ``KANON_MARKETPLACE_INSTALL`` key:
        marketplace install is a per-dependency
        ``KANON_SOURCE_<alias>_MARKETPLACE`` flag (spec Section 0 item 8 /
        Section 5.1 / FR-17), surfaced inside each source group.

    Raises:
        ValueError: If KANON_SOURCES is explicitly set, if no sources
            are discovered, or if a named source is missing a required
            structural variable.
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

    return {
        "KANON_SOURCES": source_names,
        "sources": sources,
        "globals": globals_dict,
    }


def validate_sources(
    expanded: dict[str, str],
    source_names: list[str],
) -> None:
    """Validate that all aliased sources have the required structural variables.

    Each alias in ``source_names`` must have every required structural suffix
    defined in ``expanded`` (the alias-keyed block, spec Section 5.1):
      - ``KANON_SOURCE_<alias>_URL``
      - ``KANON_SOURCE_<alias>_REF``
      - ``KANON_SOURCE_<alias>_PATH``
      - ``KANON_SOURCE_<alias>_NAME``

    Per-dependency env-var keys (e.g. ``KANON_SOURCE_<alias>_GITBASE``) are
    optional and are never required by this validation.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs from the .kanon file.
        source_names: List of source aliases (auto-discovered, alphabetical).

    Raises:
        ValueError: If any aliased source is missing a required structural
            variable. The error message includes both the alias and the
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
) -> dict[str, dict[str, str | bool | dict[str, str]]]:
    """Extract named source groups after validation.

    Each source group carries the four required structural string fields (url,
    ref, path, name), the optional per-dependency ``marketplace`` boolean parsed
    from ``KANON_SOURCE_<alias>_MARKETPLACE`` (spec Section 5.1 / FR-17), and an
    ``env`` dict holding every optional per-dependency env var: each
    ``KANON_SOURCE_<alias>_<VAR>`` key whose ``<VAR>`` is not a reserved
    structural/marketplace suffix is collected as ``env[VAR] = value`` (e.g.
    ``GITBASE``). The ``env`` dict is empty when the source declares no env vars.
    The marketplace flag is absent-means-false: a missing line yields ``False``,
    an explicit ``=true`` yields ``True``, and a hand-written ``=false`` is
    tolerated on read (also ``False``) though kanon never emits it.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.
        source_names: List of source names (auto-discovered, alphabetical).

    Returns:
        Dict mapping source alias to {url, ref, path, name, marketplace, env}.

    Raises:
        ValueError: If a source is missing a required structural variable.
    """
    validate_sources(expanded, source_names)
    sources: dict[str, dict[str, str | bool | dict[str, str]]] = {}
    for name in source_names:
        source_data: dict[str, str | bool | dict[str, str]] = {}
        for suffix in SOURCE_SUFFIXES:
            var_name = f"{SOURCE_PREFIX}{name}{suffix}"
            result_key = SUFFIX_TO_KEY[suffix]
            source_data[result_key] = expanded[var_name]
        marketplace_var = f"{SOURCE_PREFIX}{name}{SOURCE_MARKETPLACE_SUFFIX}"
        source_data[SOURCE_MARKETPLACE_KEY] = _parse_bool(expanded.get(marketplace_var, "false"))
        source_data[SOURCE_ENV_KEY] = _extract_source_env(expanded, name, source_names)
        sources[name] = source_data
    return sources


def _extract_source_env(
    expanded: dict[str, str],
    name: str,
    source_names: list[str],
) -> dict[str, str]:
    """Collect the open, optional per-dependency env-var map for one source.

    Every ``KANON_SOURCE_<name>_<VAR>`` key whose ``<VAR>`` is not a reserved
    structural suffix (``_URL``/``_REF``/``_PATH``/``_NAME``) or the
    ``_MARKETPLACE`` flag is collected as ``{VAR: value}``. The ``<VAR>`` token
    is the key text after the ``KANON_SOURCE_<name>_`` prefix (e.g. ``GITBASE``,
    ``MYBASE``). Missing env vars never fail: an absent key simply does not
    appear in the returned map.

    Keys that are reserved structural/marketplace keys of any other discovered
    source are excluded so that, when one alias is a textual prefix of another
    (aliases may contain single underscores), a longer alias' structural keys do
    not leak into the shorter alias' env map.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.
        name: The source alias whose env vars are collected.
        source_names: All discovered source aliases (used to exclude other
            sources' reserved keys).

    Returns:
        Dict mapping each declared env-var name to its value (possibly empty).
    """
    prefix = f"{SOURCE_PREFIX}{name}_"
    reserved_keys: set[str] = set()
    for other in source_names:
        for suffix in SOURCE_RESERVED_SUFFIXES:
            reserved_keys.add(f"{SOURCE_PREFIX}{other}{suffix}")
    env: dict[str, str] = {}
    for key, value in expanded.items():
        if key in reserved_keys:
            continue
        if key.startswith(prefix):
            var = key[len(prefix) :]
            if var:
                env[var] = value
    return env


def _extract_globals(
    expanded: dict[str, str],
    source_names: list[str],
) -> dict[str, str]:
    """Extract non-source variables as globals.

    Every per-dependency key is excluded so that no alias-scoped key leaks into
    the global namespace: the required structural ``SOURCE_SUFFIXES`` block, the
    optional ``KANON_SOURCE_<alias>_MARKETPLACE`` flag, and every open
    per-dependency env-var key (any other ``KANON_SOURCE_<alias>_<VAR>``). The
    former global ``KANON_MARKETPLACE_INSTALL`` field no longer exists (spec
    Section 0 item 8 / FR-17), so there is no global marketplace key to exclude.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.
        source_names: List of source names (auto-discovered, alphabetical).

    Returns:
        Dict of global variables (excludes every source-specific variable,
        including each source's optional ``_MARKETPLACE`` flag and open env
        vars).
    """
    alias_prefixes = tuple(f"{SOURCE_PREFIX}{name}_" for name in source_names)

    return {k: v for k, v in expanded.items() if not k.startswith(alias_prefixes)}


def _parse_bool(value: str) -> bool:
    """Parse a string boolean value (case-insensitive).

    Args:
        value: String value to parse ('true' or 'false').

    Returns:
        True if value is 'true' (case-insensitive), False otherwise.
    """
    return value.strip().lower() == "true"
