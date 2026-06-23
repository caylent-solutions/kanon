"""Multi-source .kanon file parser.

Parses KEY=VALUE configuration files used by Kanon. The .kanon
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

If a partial source definition is found (``_REVISION`` or ``_PATH`` present
without a corresponding ``_URL``), a ``ValueError`` is raised naming the
exact missing ``KANON_SOURCE_<name>_URL`` variable so callers can surface
it to stderr verbatim.

The parser reads the file, applies environment overrides, expands shell
variables, validates required fields, and returns a structured dict.

Security guards are applied before any data is returned:
  - Symlink detection (TOCTOU mitigation): the .kanon file must not be a symlink.
  - Permission check: the .kanon file must not be writable by anyone other than
    its owner. On POSIX this rejects the group-write and world-write mode bits;
    on Windows the ACL-equivalent rejects a discretionary ACL (DACL) that grants
    write access to any principal other than the file owner or the local
    Administrators group. The control is selected per-OS at the check site and
    is never silently skipped on either platform.
  - Path traversal rejection: KANON_SOURCE_<name>_PATH values must not contain '..'.
"""

import os
import pathlib
import re
import stat
import sys

from kanon_cli.constants import (
    SHELL_VAR_PATTERN,
    SOURCE_NON_URL_SUFFIXES,
    SOURCE_PREFIX,
    SOURCE_SUFFIXES,
    SOURCE_URL_SUFFIX,
    SUFFIX_TO_KEY,
)

# Permission bits that indicate group-write or world-write access.
# These are rejected to prevent privilege escalation via tampered .kanon files.
_UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH

# Suffix used to identify PATH variables for path-traversal checking.
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
        owner. On POSIX the group-write and world-write mode bits are rejected;
        on Windows the ACL-equivalent rejects any DACL entry that grants write
        access to a principal other than the owner or local Administrators. The
        per-OS control is selected at the check site and is never skipped.
      - Path traversal: no KANON_SOURCE_<name>_PATH value may contain '..'.

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
        ValueError: If the file is a symlink, if the file has unsafe
            permissions (group-writable or world-writable), if any
            KANON_SOURCE_<name>_PATH value contains '..', if
            KANON_SOURCES is explicitly set (no longer supported),
            if no sources are discovered, if a named source is missing
            required variables (URL, REVISION, PATH), or if a shell
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

    Dispatches to the platform-specific write-permission control selected at
    this single check site (Strategy by OS, not a fallback):

      - On Windows (``sys.platform == "win32"``) the ACL-equivalent
        (``_check_windows_acl``) reads the file's discretionary ACL via
        ``GetFileSecurity`` and rejects any write grant to a principal other
        than the owner or the local Administrators group.
      - On every other platform the POSIX mode-bit control
        (``_check_permissions``) rejects the group-write and world-write bits.

    The Windows branch is never a silent no-op: a non-compliant ACL fails fast
    with the same actionable ``ValueError`` shape the POSIX path raises.

    Args:
        path: Path to the .kanon file.

    Raises:
        ValueError: If the file grants write access beyond its owner (and, on
            Windows, the local Administrators group).
    """
    if sys.platform == "win32":
        _check_windows_acl(path)
    else:
        _check_permissions(path)


def _check_permissions(path: pathlib.Path) -> None:
    """Raise ValueError if the .kanon file has group-write or world-write bits set.

    World-writable or group-writable .kanon files can be tampered with by
    unprivileged users, which could lead to privilege escalation or supply
    chain attacks. Only owner-write access is permitted. This is the POSIX
    branch of the per-OS write-permission control selected by
    ``_check_write_permission``.

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


def _evaluate_acl_write_principals(
    write_principals: list[str],
    allowed_principals: set[str],
    path: pathlib.Path,
) -> None:
    """Reject a Windows ACL that grants write access beyond the allowed principals.

    This is the platform-agnostic policy half of the Windows ACL-equivalent: it
    is given the set of security principals that the file's DACL grants write
    access to (``write_principals``, as string SIDs) and the set of principals
    that are permitted to hold write access (``allowed_principals`` -- the file
    owner SID and the local Administrators SID). Any write grant to a principal
    outside ``allowed_principals`` fails fast with the same actionable error
    shape the POSIX mode-bit path raises. Separating this decision from the
    ``GetFileSecurity`` mechanism (``_check_windows_acl``) keeps the control
    falsifiable and exercisable on every platform.

    Args:
        write_principals: String SIDs that the DACL grants write access to.
        allowed_principals: String SIDs permitted to hold write access (owner
            and local Administrators).
        path: Path to the .kanon file (for the error message).

    Raises:
        ValueError: If any principal in ``write_principals`` is not present in
            ``allowed_principals``.
    """
    disallowed = sorted({sid for sid in write_principals if sid not in allowed_principals})
    if disallowed:
        granted = ", ".join(disallowed)
        msg = (
            f".kanon file has an insecure ACL (write access granted to {granted}): {path}. "
            "Restrict write access to the file owner and Administrators only "
            "(e.g. 'icacls .kanon /inheritance:r /grant:r %USERNAME%:RW Administrators:F')."
        )
        raise ValueError(msg)


def _check_windows_acl(path: pathlib.Path) -> None:
    """Reject a .kanon file whose Windows DACL grants write access beyond owner/admin.

    Windows ACL-equivalent of the POSIX group/world-writable mode-bit check
    (FR-37). Reads the file's owner SID and discretionary ACL (DACL) via
    ``win32security.GetFileSecurity``, derives the local Administrators
    well-known SID, collects every principal that an allow ACE grants a
    write-class right to, and delegates the accept/reject decision to
    ``_evaluate_acl_write_principals``. The ``win32security`` /
    ``ntsecuritycon`` imports live inside this Windows-only branch so the
    module imports cleanly on POSIX (mirroring the per-OS backend import idiom
    used elsewhere in this codebase). A non-compliant ACL fails fast; this
    control is never a silent no-op on Windows.

    Args:
        path: Path to the .kanon file.

    Raises:
        ValueError: If the DACL grants write access to any principal other than
            the file owner or the local Administrators group.
    """
    import ntsecuritycon
    import win32security

    write_mask = (
        ntsecuritycon.FILE_WRITE_DATA
        | ntsecuritycon.FILE_APPEND_DATA
        | ntsecuritycon.WRITE_DAC
        | ntsecuritycon.WRITE_OWNER
        | ntsecuritycon.FILE_GENERIC_WRITE
    )

    descriptor = win32security.GetFileSecurity(
        str(path),
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    owner_sid = descriptor.GetSecurityDescriptorOwner()
    administrators_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
    allowed_principals = {
        win32security.ConvertSidToStringSid(owner_sid),
        win32security.ConvertSidToStringSid(administrators_sid),
    }

    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        msg = (
            f".kanon file has a NULL discretionary ACL (grants full control to everyone): {path}. "
            "Set an explicit ACL that restricts write access to the file owner and Administrators."
        )
        raise ValueError(msg)

    write_principals: list[str] = []
    for index in range(dacl.GetAceCount()):
        ace_type, _ace_flags, access_mask, ace_sid = _split_windows_ace(dacl.GetAce(index))
        if ace_type != win32security.ACCESS_ALLOWED_ACE_TYPE:
            continue
        if access_mask & write_mask:
            write_principals.append(win32security.ConvertSidToStringSid(ace_sid))

    _evaluate_acl_write_principals(write_principals, allowed_principals, path)


def _split_windows_ace(ace: tuple) -> tuple:
    """Decompose a pywin32 ACCESS_ALLOWED ACE tuple into its fields.

    ``win32security.ACL.GetAce`` returns the ACE as
    ``((ace_type, ace_flags), access_mask, sid)``. This helper unpacks that
    nested shape into a flat ``(ace_type, ace_flags, access_mask, sid)`` tuple
    so the caller does not duplicate the indexing. Kept as a module-level pure
    function (no Windows-only imports) for Single Responsibility.

    Args:
        ace: An ACE tuple as returned by ``win32security.ACL.GetAce``.

    Returns:
        A flat tuple ``(ace_type, ace_flags, access_mask, sid)``.
    """
    (ace_type, ace_flags), access_mask, sid = ace
    return ace_type, ace_flags, access_mask, sid


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

    Also scans for keys matching ``KANON_SOURCE_<name>_(REVISION|PATH)``
    to detect sources that are partially defined without a URL; raises
    ``ValueError`` naming the exact missing URL variable so callers can
    surface it verbatim.

    Args:
        expanded: Dict of expanded KEY=VALUE pairs.

    Returns:
        Sorted list of discovered source names.

    Raises:
        NoSourcesError: If no ``KANON_SOURCE_<name>_URL`` keys are found
            (a ``ValueError`` subclass; the zero-source case).
        ValueError: If a source name is inferred from a non-URL suffix but the
            corresponding ``KANON_SOURCE_<name>_URL`` key is absent.
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
            "KANON_SOURCE_<name>_URL, KANON_SOURCE_<name>_REVISION, "
            "and KANON_SOURCE_<name>_PATH variables in .kanon"
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
