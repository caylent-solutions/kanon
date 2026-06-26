"""TOML lockfile parser and atomic writer -- schema v5.

Public entry points:
  - ``read_lockfile(path: Path) -> Lockfile``: parse and validate a TOML lockfile.
    Applies schema migration policy (spec Section 5.2) when schema_version differs
    from CURRENT_SCHEMA_VERSION.
  - ``write_lockfile(lockfile: Lockfile, path: Path) -> None``: atomically serialise
    a Lockfile to disk using a write-temp-then-rename pattern.
  - ``check_lockfile_consistency(kanon_aliases, kanon_ref_specs, lockfile) -> None``:
    verify the ``.kanon`` alias declarations agree with the ``.kanon.lock`` entries
    (alias uniqueness, alias-set parity, per-alias ref-spec parity; spec FR-24,
    Section 4.5).  ``kanon validate lockfile`` runs this check, and ``kanon install``
    runs it implicitly before resolving (spec Section 4.3).

Exception hierarchy:
  - ``LockfileSchemaError``: raised when the schema_version is not supported or has
    no upgrade path to the current schema.
  - ``LockfileValidationError``: raised when a field value violates a validation rule.
  - ``LockfileConsistencyError``: raised when ``.kanon`` and ``.kanon.lock`` have
    drifted apart (duplicate alias, alias-set drift, or per-alias ref-spec drift).

Schema migration registry (spec Section 5.2):
  - ``_register_upgrader(from_version, to_version, fn)``: register an upgrader function.
  - ``_unregister_upgrader(from_version, to_version)``: remove a registered upgrader.
  - ``_dispatch_migration(data)``: walk the upgrader chain from data's schema_version
    to CURRENT_SCHEMA_VERSION, raising LockfileSchemaError if no chain exists.

Schema changelog:
  - v1: original schema (catalog, sources, kanon_hash).
  - v2: added ``marketplace_registered`` (bool) and ``marketplace_dir`` (str) to record
    whether install registered a marketplace plugin and which directory it used.  Old
    v1 lockfiles are migrated transparently by setting both fields to their default
    (false / empty string), preserving backward compatibility.
  - v3: added a PER-SOURCE ``registered_marketplaces`` (list[str]) field to each
    ``[[sources]]`` table -- the sorted set of marketplace names THAT source
    registered during install.  ``kanon clean --orphans`` and the install
    auto-prune consult these per-source ledgers to attribute and prune the
    marketplaces of a removed source.
  - v4 (spec Section 5.2, Section 13 FLAG-C, FR-7 / FR-21): the breaking major.
    Each ``[[sources]]`` lock entry is re-keyed BY ALIAS and carries the per-entry
    fields ``alias, name, url, ref_spec, resolved_ref, resolved_sha, path``.  The
    per-entry version-constraint field (named ``ref_spec`` from v4 onward) is the
    rename of the former v3 field name on every lock entry (source and project).
    The global ``[catalog]`` block is removed
    entirely: the lock no longer serialises or parses a ``[catalog]`` inline table.
    There is NO silent v3 -> v4 upgrader: a loaded v3 (or older) lock fails fast
    with an actionable ``LockfileSchemaError`` instructing the operator to
    regenerate the lock via ``kanon add`` / ``kanon install``.
  - v5 (spec Section 5.2, Section 3.6, FR-22, AMENDED 2026-06-25): npm-style
    content-SHA locking.  Each ``[[sources]]`` entry gains a per-source
    ``[[sources.content_pins]]`` array; each pin row carries ``name`` (the
    manifest ``<project name>``), ``path`` (the project's checkout path), and
    ``resolved_sha`` (the project's resolved content commit SHA captured after
    ``repo sync``).  Reinstalls replay the locked content SHA byte-for-byte; a
    branch ``<project revision>`` only advances on an explicit ``--refresh-lock``.
    The content pins are RESOLVED outputs (like ``resolved_sha``), so they are
    EXCLUDED from ``kanon_hash`` -- ``kanon_hash`` covers only the ``.kanon``
    source triples, never lockfile resolved fields, so a captured pin never
    perturbs the digest or triggers spurious drift.  Like v4, there is NO silent
    v4 -> v5 upgrader: a loaded v4 (or older) lock fails fast with the same
    "regenerate via ``kanon add`` / ``kanon install``" message.

Spec source: spec Section 5 (Lockfile format and validation rules),
Section 4.7.1 (atomicity contract for the lockfile writer), and
Section 5.2 (Lockfile schema migration policy).
"""

from __future__ import annotations

import os
import random
import re
import string
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from kanon_cli.core.url import canonicalize_repo_url


CURRENT_SCHEMA_VERSION: int = 5


_UPGRADERS: dict[tuple[int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}


_SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")


_KANON_HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


_TOML_CONTROL_ESCAPES: dict[str, str] = {
    "\x00": "\\u0000",
    "\x01": "\\u0001",
    "\x02": "\\u0002",
    "\x03": "\\u0003",
    "\x04": "\\u0004",
    "\x05": "\\u0005",
    "\x06": "\\u0006",
    "\x07": "\\u0007",
    "\x08": "\\b",
    "\x09": "\\t",
    "\x0a": "\\n",
    "\x0b": "\\u000B",
    "\x0c": "\\f",
    "\x0d": "\\r",
    "\x0e": "\\u000E",
    "\x0f": "\\u000F",
    "\x10": "\\u0010",
    "\x11": "\\u0011",
    "\x12": "\\u0012",
    "\x13": "\\u0013",
    "\x14": "\\u0014",
    "\x15": "\\u0015",
    "\x16": "\\u0016",
    "\x17": "\\u0017",
    "\x18": "\\u0018",
    "\x19": "\\u0019",
    "\x1a": "\\u001A",
    "\x1b": "\\u001B",
    "\x1c": "\\u001C",
    "\x1d": "\\u001D",
    "\x1e": "\\u001E",
    "\x1f": "\\u001F",
    "\x7f": "\\u007F",
}


_BRANCH_RE = re.compile(r"^[a-zA-Z0-9_./+-]+$")


_FORBIDDEN_PATH_CHARS: tuple[tuple[str, str], ...] = (
    ("\x00", "U+0000 (NUL)"),
    ("\n", "U+000A (newline)"),
    ("\t", "U+0009 (tab)"),
)


def _register_upgrader(
    from_version: int,
    to_version: int,
    fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Register an upgrader function for the (from_version, to_version) pair.

    The upgrader receives a raw TOML dict and must return a raw dict with
    schema_version set to ``to_version``. Callers are responsible for ensuring
    the returned dict is valid for ``to_version`` parsing.

    Raises:
        ValueError: If an upgrader for the same (from_version, to_version) pair
            is already registered. Duplicate registrations are rejected to prevent
            accidental shadowing in tests.

    Args:
        from_version: The schema version the upgrader reads.
        to_version: The schema version the upgrader produces.
        fn: The upgrader function.
    """
    key = (from_version, to_version)
    if key in _UPGRADERS:
        raise ValueError(
            f"Upgrader for schema ({from_version} -> {to_version}) is already registered. "
            f"Unregister the existing upgrader before registering a replacement."
        )
    _UPGRADERS[key] = fn


def _unregister_upgrader(from_version: int, to_version: int) -> None:
    """Remove the upgrader for (from_version, to_version) from the registry.

    Used by test teardown to prevent registry state leaking across tests.

    Args:
        from_version: The schema version the upgrader reads.
        to_version: The schema version the upgrader produces.

    Raises:
        KeyError: If no upgrader is registered for the given (from_version, to_version)
            pair. Fail-fast: a missing key indicates a programming error (mismatched
            register/unregister calls or a double-unregister in test teardown).
    """
    key = (from_version, to_version)
    if key not in _UPGRADERS:
        raise KeyError(
            f"No upgrader registered for schema ({from_version} -> {to_version}). "
            f"Ensure _register_upgrader was called before _unregister_upgrader."
        )
    del _UPGRADERS[key]


def _dispatch_migration(data: dict[str, Any]) -> dict[str, Any]:
    """Walk the upgrader chain from data's schema_version to CURRENT_SCHEMA_VERSION.

    Applies upgraders one step at a time, following the (N, N+1) chain until the
    data's schema_version reaches CURRENT_SCHEMA_VERSION.

    Args:
        data: Raw TOML dict with ``schema_version`` set to a version older than
            CURRENT_SCHEMA_VERSION.

    Returns:
        The raw TOML dict after all upgrader functions have been applied, with
        ``schema_version`` equal to ``CURRENT_SCHEMA_VERSION``.

    Raises:
        LockfileSchemaError: If no registered upgrader exists for a required step
            in the chain from data's ``schema_version`` to ``CURRENT_SCHEMA_VERSION``.
    """
    current = data
    from_ver: int = current["schema_version"]
    while from_ver < CURRENT_SCHEMA_VERSION:
        to_ver = from_ver + 1
        key = (from_ver, to_ver)
        if key not in _UPGRADERS:
            raise LockfileSchemaError(
                f"no upgrade path from lockfile schema v{from_ver} "
                f"to v{CURRENT_SCHEMA_VERSION}; this is a kanon bug; please report."
            )
        current = _UPGRADERS[key](current)
        if current["schema_version"] <= from_ver:
            raise LockfileSchemaError(
                f"upgrader for schema v{from_ver}->v{to_ver} did not advance "
                f"schema_version (returned {current['schema_version']}); "
                f"this is a kanon bug; please report."
            )
        from_ver = current["schema_version"]
    return current


class LockfileSchemaError(Exception):
    """Raised when the lockfile's schema_version is not supported by this kanon version.

    This exception is intentionally distinct from ``LockfileValidationError`` so
    downstream callers (e.g., the T2 migration policy) can dispatch on it.
    """


class LockfileValidationError(Exception):
    """Raised when a lockfile field value violates a schema-v1 validation rule.

    The error message always:
      - Names the offending field path (e.g., ``sources[0].projects[2].resolved_sha``).
      - Includes the offending value.
      - Suggests the operator's likely remediation step.
    """


class LockfileConsistencyError(Exception):
    """Raised when ``.kanon`` and ``.kanon.lock`` have drifted apart (spec FR-24).

    Distinct from ``LockfileValidationError`` (a single lock field is malformed)
    and ``LockfileSchemaError`` (the lock schema version is unsupported): this
    exception signals that the lock no longer agrees with the consumer ``.kanon``
    declarations, which is the condition ``kanon validate lockfile`` flags and
    ``kanon install`` rejects before it resolves (spec Section 4.3 / Section 4.5).

    The three drift conditions, each producing a specific message:
      - a duplicate alias in the ``.kanon`` declarations,
      - the alias set in ``.kanon.lock`` differs from the alias set in ``.kanon``,
      - a per-alias ``ref_spec`` in ``.kanon.lock`` differs from the matching
        ``.kanon`` revision.

    The message always names the offending alias(es) and the operator's likely
    remediation step.
    """


@dataclass
class ProjectEntry:
    """A single row under ``[[sources.projects]]``.

    Schema v4 renamed the per-entry version-constraint field to ``ref_spec`` (spec
    Section 5.2); the attribute and the on-disk TOML key are both ``ref_spec``.
    """

    name: str
    url: str
    canonical_url: str
    ref_spec: str
    resolved_ref: str
    resolved_sha: str


@dataclass
class ContentPinEntry:
    """A single row under ``[[sources.content_pins]]`` (schema v5).

    Records the resolved content commit SHA of one ``<project>`` in a source's
    resolved manifest tree, captured after ``repo sync``.  Reinstalls replay this
    SHA byte-for-byte so a branch or tag ``<project revision>`` is frozen to the
    locked commit until an explicit ``--refresh-lock`` (npm-style content-SHA
    locking; spec Section 5.2 / FR-22, AMENDED 2026-06-25).

    Fields:
        name: The manifest ``<project name>`` the pin is for.
        path: The project's checkout path (``<project path>``), used to locate
            the checkout when re-capturing and to rewrite the replay revision.
        resolved_sha: The 40- or 64-hex content commit SHA captured at lock time.
    """

    name: str
    path: str
    resolved_sha: str


@dataclass
class IncludeEntry:
    """A single row under ``[[sources.includes]]`` -- recursive, unbounded depth."""

    name: str
    path_in_repo: str
    url: str
    resolved_sha: str
    includes: list[IncludeEntry] = field(default_factory=list)


@dataclass
class SourceEntry:
    """A single row under ``[[sources]]``.

    Fields added in schema v3:
      - ``registered_marketplaces``: the sorted set of marketplace names THIS
        source registered during install.  Defaults to an empty list.  ``kanon
        clean --orphans`` and the install auto-prune consult this per-source
        ledger to attribute and prune the marketplaces of a removed source.

    Schema v4 (spec Section 5.2, FR-7 / FR-21) re-keys each ``[[sources]]`` entry
    BY ALIAS and renames the per-source version-constraint field to ``ref_spec``:
      - ``alias``: the local alias the source is keyed by in the alias-keyed
        ``.kanon`` / ``.kanon.lock``.  It is the lock key and is written first in
        the serialised entry.
      - ``ref_spec``: the version / ref constraint (PEP 440 specifier, the ``*``
        wildcard, a ``refs/...`` ref, or a branch name).  This is the v4 rename of
        the former v3 version-constraint field; both the attribute and the on-disk
        TOML key are ``ref_spec``.

    Schema v5 (spec Section 5.2, AMENDED 2026-06-25) adds a per-source
    ``content_pins`` field:
      - ``content_pins``: the list of :class:`ContentPinEntry` rows recording the
        resolved content commit SHA of each ``<project>`` in this source's
        resolved manifest tree, captured after ``repo sync``.  Reinstalls replay
        these SHAs byte-for-byte (npm-style content-SHA locking).  Defaults to an
        empty list (a source whose checkouts were not materialised -- e.g. a
        mocked test sync -- captures no pins).  Like ``resolved_sha`` it is a
        RESOLVED output and is excluded from ``kanon_hash``.
    """

    alias: str
    name: str
    url: str
    ref_spec: str
    resolved_ref: str
    resolved_sha: str
    path: str
    includes: list[IncludeEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    registered_marketplaces: list[str] = field(default_factory=list)
    content_pins: list[ContentPinEntry] = field(default_factory=list)


@dataclass
class Lockfile:
    """Root lockfile dataclass mirroring the top-level TOML structure.

    Fields added in schema v2:
      - ``marketplace_registered``: True when install registered a marketplace plugin.
      - ``marketplace_dir``: The CLAUDE_MARKETPLACES_DIR path used at install time;
        non-empty only when marketplace_registered is True.

    Schema v3 added a PER-SOURCE ``registered_marketplaces`` field to each
    ``SourceEntry`` (see :class:`SourceEntry`); the root lockfile carries no
    marketplace ownership ledger of its own.

    Schema v4 (spec Section 5.2, FR-7 / FR-21) removed the global ``[catalog]``
    block entirely: the lockfile no longer carries a catalog field and the lock
    neither serialises nor parses a ``[catalog]`` inline table.  The ``[[sources]]``
    entries are alias-keyed (see :class:`SourceEntry`).

    Schema v5 (spec Section 5.2, AMENDED 2026-06-25) adds the per-source
    ``content_pins`` array (see :class:`SourceEntry`); the root lockfile shape is
    otherwise unchanged from v4.
    """

    schema_version: int
    generated_at: str
    generator: str
    kanon_hash: str
    sources: list[SourceEntry] = field(default_factory=list)
    marketplace_registered: bool = False
    marketplace_dir: str = ""


def _validate_kanon_hash(value: str) -> None:
    """Raise ``LockfileValidationError`` if ``value`` is not a valid kanon_hash string.

    A valid kanon_hash (spec Rule 1a) is a 71-character string of the form
    ``sha256:<64 lowercase hex chars>``. Bare hex strings without the prefix are
    rejected; uppercase hex characters are rejected.

    Args:
        value: The ``kanon_hash`` field value to validate.

    Raises:
        LockfileValidationError: If the value does not match the required pattern.
    """
    if not _KANON_HASH_RE.match(value):
        raise LockfileValidationError(
            f"ERROR: Invalid kanon_hash at 'kanon_hash'.\n"
            f"  Value: {value!r}\n"
            f"  Expected: 'sha256:' followed by exactly 64 lowercase hex digits (a-f0-9).\n"
            f"  Total expected length: 71 characters.\n"
            f"  Remediation: regenerate the lockfile with 'kanon install' to obtain "
            f"a valid kanon_hash."
        )


def _validate_resolved_sha(sha: str, field_path: str) -> None:
    """Raise ``LockfileValidationError`` if ``sha`` is not 40 or 64 lowercase hex digits.

    Args:
        sha: The resolved_sha value to validate.
        field_path: Dot-path of the field in the lockfile (for the error message).

    Raises:
        LockfileValidationError: If the value does not match the SHA pattern.
    """
    if not _SHA_RE.match(sha):
        raise LockfileValidationError(
            f"ERROR: Invalid resolved_sha at '{field_path}'.\n"
            f"  Value: {sha!r}\n"
            f"  Expected: exactly 40 or 64 lowercase hex digits (a-f0-9).\n"
            f"  Remediation: regenerate the lockfile with 'kanon lock' to obtain "
            f"a valid SHA-1 (40 chars) or SHA-256 (64 chars) git object ID."
        )


def _validate_ref_spec(spec: str, field_path: str) -> None:
    """Raise ``LockfileValidationError`` if ``spec`` fails all accept rules.

    Accept rules (any one suffices):
      0. The bare wildcard ``*`` ("any version"), written verbatim by add/install.
      1. Parses as ``packaging.specifiers.SpecifierSet`` (PEP 440), optionally
         preceded by a monorepo path prefix ending with ``/``.
      2. Starts with ``refs/`` (literal git ref).
      3. Matches the branch-charset regex ``^[a-zA-Z0-9_./+-]+$``.

    Args:
        spec: The ref_spec value to validate.
        field_path: Dot-path of the field for the error message.

    Raises:
        LockfileValidationError: If none of the three rules accept the value.
    """
    if not spec:
        raise LockfileValidationError(
            f"ERROR: Empty ref_spec at '{field_path}'.\n"
            f"  Value: {spec!r}\n"
            f"  Expected: a PEP 440 specifier (e.g. '==1.0.0'), the wildcard '*' "
            f"(any version), a git ref (e.g. 'refs/heads/main'), or a branch name "
            f"(e.g. 'main').\n"
            f"  Remediation: update the ref_spec in your .kanon file and re-lock."
        )

    if spec == "*":
        return

    if spec.startswith("refs/"):
        return

    if _BRANCH_RE.match(spec):
        return

    suffix = spec
    if "/" in spec:
        last_slash = spec.rfind("/")
        suffix = spec[last_slash + 1 :]

    try:
        SpecifierSet(suffix)
        return
    except (InvalidSpecifier, InvalidRequirement, ValueError):
        pass

    raise LockfileValidationError(
        f"ERROR: Invalid ref_spec at '{field_path}'.\n"
        f"  Value: {spec!r}\n"
        f"  Expected one of:\n"
        f"    - PEP 440 SpecifierSet (e.g. '==1.0.0', '~=2.0.0', '>=1.0,<2.0')\n"
        f"    - Bare wildcard '*' (any version)\n"
        f"    - Optional monorepo prefix: 'subpackage/==1.0.0'\n"
        f"    - Git ref: 'refs/heads/main'\n"
        f"    - Branch name matching ^[a-zA-Z0-9_./+-]+$\n"
        f"  Remediation: update the ref_spec in your .kanon file and re-lock."
    )


def _validate_canonical_url(url: str, canonical_url: str, field_path: str) -> None:
    """Raise ``LockfileValidationError`` if ``canonical_url`` does not match ``canonicalize_repo_url(url)``.

    Args:
        url: The raw URL from the ProjectEntry.
        canonical_url: The recorded canonical_url from the ProjectEntry.
        field_path: Dot-path of the ProjectEntry for the error message.

    Raises:
        LockfileValidationError: If the recorded canonical_url does not equal the
            computed canonical form of ``url``.
    """
    computed = canonicalize_repo_url(url)
    if canonical_url != computed:
        raise LockfileValidationError(
            f"ERROR: canonical_url mismatch at '{field_path}'.\n"
            f"  Recorded canonical_url: {canonical_url!r}\n"
            f"  Computed  canonical_url: {computed!r}\n"
            f"  (computed from url={url!r})\n"
            f"  Remediation: regenerate the lockfile with 'kanon lock' to update "
            f"the canonical_url field."
        )


def _validate_registered_marketplaces(value: Any, field_path: str) -> list[str]:
    """Validate and normalise a source's ``registered_marketplaces`` ledger.

    The field (schema v3, per-source) must be a list whose every element is a
    string. Fail-fast: a non-list value, or a list containing a non-string
    element, raises ``LockfileValidationError`` naming the offending source's
    field -- we never silently coerce or drop malformed entries.

    Args:
        value: The raw ``registered_marketplaces`` value from a source's TOML dict.
        field_path: Dot-path of the field for the error message (e.g.
            ``sources[0].registered_marketplaces``).

    Returns:
        The validated list of marketplace names.

    Raises:
        LockfileValidationError: If ``value`` is not a list of strings.
    """
    if not isinstance(value, list):
        raise LockfileValidationError(
            f"ERROR: Invalid registered_marketplaces at '{field_path}'.\n"
            f"  Value (repr): {value!r}\n"
            f'  Expected: an array of marketplace-name strings (e.g. ["a-mp", "b-mp"]).\n'
            f"  Remediation: regenerate the lockfile with 'kanon install'."
        )
    for index, element in enumerate(value):
        if not isinstance(element, str):
            raise LockfileValidationError(
                f"ERROR: Invalid entry in registered_marketplaces at "
                f"'{field_path}[{index}]'.\n"
                f"  Value (repr): {element!r}\n"
                f"  Expected: a marketplace-name string.\n"
                f"  Remediation: regenerate the lockfile with 'kanon install'."
            )
    return list(value)


def _validate_path_chars(path_value: str, field_path: str) -> None:
    """Raise ``LockfileValidationError`` if ``path_value`` contains NUL, newline, or tab.

    Args:
        path_value: The path string to validate.
        field_path: Dot-path of the field for the error message (e.g. ``sources[0].path``).

    Raises:
        LockfileValidationError: If any forbidden character is found.
    """
    for char, codepoint_desc in _FORBIDDEN_PATH_CHARS:
        if char in path_value:
            raise LockfileValidationError(
                f"ERROR: Forbidden character in '{field_path}'.\n"
                f"  Character: {codepoint_desc}\n"
                f"  Value (repr): {path_value!r}\n"
                f"  Paths must not contain NUL (\\x00), newline (\\n), or tab (\\t).\n"
                f"  Remediation: correct the path value in your .kanon file and re-lock."
            )


def _parse_include_entry(raw: dict[str, Any], field_path: str) -> IncludeEntry:
    """Parse a raw TOML dict into an ``IncludeEntry``, validating all fields.

    Recursively parses nested ``includes`` entries.

    Args:
        raw: A dict from the TOML parser representing one include entry.
        field_path: Dot-path for error messages (e.g. ``sources[0].includes[1]``).

    Returns:
        A validated ``IncludeEntry`` dataclass instance.

    Raises:
        LockfileValidationError: If any field fails validation.
    """
    resolved_sha = raw["resolved_sha"]
    _validate_resolved_sha(resolved_sha, f"{field_path}.resolved_sha")

    path_in_repo = raw["path_in_repo"]
    _validate_path_chars(path_in_repo, f"{field_path}.path_in_repo")

    nested_raws: list[dict[str, Any]] = raw.get("includes", [])
    nested_includes = [_parse_include_entry(item, f"{field_path}.includes[{i}]") for i, item in enumerate(nested_raws)]

    return IncludeEntry(
        name=raw["name"],
        path_in_repo=path_in_repo,
        url=raw["url"],
        resolved_sha=resolved_sha,
        includes=nested_includes,
    )


def _parse_project_entry(raw: dict[str, Any], field_path: str) -> ProjectEntry:
    """Parse a raw TOML dict into a ``ProjectEntry``, validating all fields.

    Args:
        raw: A dict from the TOML parser representing one project entry.
        field_path: Dot-path for error messages.

    Returns:
        A validated ``ProjectEntry`` dataclass instance.

    Raises:
        LockfileValidationError: If any field fails validation.
    """
    resolved_sha = raw["resolved_sha"]
    _validate_resolved_sha(resolved_sha, f"{field_path}.resolved_sha")

    ref_spec = raw["ref_spec"]
    _validate_ref_spec(ref_spec, f"{field_path}.ref_spec")

    url = raw["url"]
    canonical_url = raw["canonical_url"]
    _validate_canonical_url(url, canonical_url, f"{field_path}.canonical_url")

    return ProjectEntry(
        name=raw["name"],
        url=url,
        canonical_url=canonical_url,
        ref_spec=ref_spec,
        resolved_ref=raw["resolved_ref"],
        resolved_sha=resolved_sha,
    )


def _parse_content_pin_entry(raw: dict[str, Any], field_path: str) -> ContentPinEntry:
    """Parse a raw TOML dict into a ``ContentPinEntry``, validating all fields.

    Args:
        raw: A dict from the TOML parser representing one content-pin row.
        field_path: Dot-path for error messages (e.g.
            ``sources[0].content_pins[1]``).

    Returns:
        A validated ``ContentPinEntry`` dataclass instance.

    Raises:
        LockfileValidationError: If any field fails validation.
    """
    resolved_sha = raw["resolved_sha"]
    _validate_resolved_sha(resolved_sha, f"{field_path}.resolved_sha")

    path = raw["path"]
    _validate_path_chars(path, f"{field_path}.path")

    return ContentPinEntry(
        name=raw["name"],
        path=path,
        resolved_sha=resolved_sha,
    )


def _parse_source_entry(raw: dict[str, Any], source_idx: int) -> SourceEntry:
    """Parse a raw schema-v5 ``[[sources]]`` TOML dict into a ``SourceEntry``.

    Validates every field.  The on-disk source carries the alias-keyed per-entry
    fields ``alias, name, url, ref_spec, resolved_ref, resolved_sha, path`` (spec
    Section 5.2), the ``[[sources.includes]]`` / ``[[sources.projects]]`` arrays,
    and the v5 ``[[sources.content_pins]]`` array.

    Args:
        raw: A dict from the TOML parser representing one source entry.
        source_idx: The zero-based index of this source in the ``[[sources]]`` array
            (used in field-path strings for error messages).

    Returns:
        A validated ``SourceEntry`` dataclass instance.

    Raises:
        LockfileValidationError: If any field fails validation.
    """
    field_path = f"sources[{source_idx}]"

    resolved_sha = raw["resolved_sha"]
    _validate_resolved_sha(resolved_sha, f"{field_path}.resolved_sha")

    ref_spec = raw["ref_spec"]
    _validate_ref_spec(ref_spec, f"{field_path}.ref_spec")

    path = raw["path"]
    _validate_path_chars(path, f"{field_path}.path")

    raw_includes: list[dict[str, Any]] = raw.get("includes", [])
    includes = [_parse_include_entry(item, f"{field_path}.includes[{i}]") for i, item in enumerate(raw_includes)]

    raw_projects: list[dict[str, Any]] = raw.get("projects", [])
    projects = [_parse_project_entry(item, f"{field_path}.projects[{i}]") for i, item in enumerate(raw_projects)]

    raw_content_pins: list[dict[str, Any]] = raw.get("content_pins", [])
    content_pins = [
        _parse_content_pin_entry(item, f"{field_path}.content_pins[{i}]") for i, item in enumerate(raw_content_pins)
    ]

    registered_marketplaces = _validate_registered_marketplaces(
        raw.get("registered_marketplaces", []),
        f"{field_path}.registered_marketplaces",
    )

    return SourceEntry(
        alias=raw["alias"],
        name=raw["name"],
        url=raw["url"],
        ref_spec=ref_spec,
        resolved_ref=raw["resolved_ref"],
        resolved_sha=resolved_sha,
        path=path,
        includes=includes,
        projects=projects,
        registered_marketplaces=registered_marketplaces,
        content_pins=content_pins,
    )


def _toml_str(value: str) -> str:
    """Encode a Python string as a TOML basic string literal.

    Escapes backslash, double-quote, and the control characters that TOML
    requires to be escaped in basic strings (U+0000-U+001F, U+007F).

    Args:
        value: The string to encode.

    Returns:
        A quoted TOML basic string, e.g. ``"hello"`` or ``"line\\nbreak"``.
    """
    result = value.replace("\\", "\\\\").replace('"', '\\"')

    for char, escape in _TOML_CONTROL_ESCAPES.items():
        result = result.replace(char, escape)
    return f'"{result}"'


def _toml_str_array(values: list[str]) -> str:
    """Encode a list of strings as a single-line TOML array of basic strings.

    Each element is encoded with ``_toml_str`` so backslash, double-quote, and
    control characters are escaped consistently with scalar string fields. An empty
    list serialises to ``[]``.

    Args:
        values: The list of strings to encode.

    Returns:
        A TOML array literal, e.g. ``["a-mp", "b-mp"]`` or ``[]``.
    """
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _serialize_include_entries(
    includes: list[IncludeEntry],
    table_path: str,
    lines: list[str],
) -> None:
    """Append TOML lines for an ``includes`` array-of-tables at the given path.

    Each ``IncludeEntry`` is serialised as a ``[[<table_path>]]`` header followed
    by its scalar fields. Nested includes are serialised recursively under the
    extended path ``<table_path>.includes``.

    A depth-3 chain under ``sources`` yields headers
    ``[[sources.includes]]``, ``[[sources.includes.includes]]``,
    and ``[[sources.includes.includes.includes]]``.

    Args:
        includes: The list of ``IncludeEntry`` objects to serialise.
        table_path: Dot-separated TOML table-array path for the header,
            e.g. ``"sources.includes"`` or ``"sources.includes.includes"``.
        lines: Mutable list of output lines to append to.
    """
    for entry in includes:
        lines.append(f"[[{table_path}]]")
        lines.append(f"name = {_toml_str(entry.name)}")
        lines.append(f"path_in_repo = {_toml_str(entry.path_in_repo)}")
        lines.append(f"url = {_toml_str(entry.url)}")
        lines.append(f"resolved_sha = {_toml_str(entry.resolved_sha)}")
        if entry.includes:
            _serialize_include_entries(entry.includes, f"{table_path}.includes", lines)


def _serialize_toml(lockfile: Lockfile) -> str:
    """Serialise a ``Lockfile`` to a TOML string without any third-party library.

    The output format matches the fixed schema v5 structure exactly (spec
    Section 5.2):

    - Top-level scalar fields (schema_version, generated_at, generator, kanon_hash,
      marketplace_registered, marketplace_dir)
    - NO ``[catalog]`` block: the global ``[catalog]`` block was removed in v4
      (spec Section 5.2 / FR-7), so the lock never serialises a ``[catalog]``
      inline table.
    - ``[[sources]]`` array-of-tables entries keyed by alias, each written with the
      per-entry fields ``alias, name, url, ref_spec, resolved_ref, resolved_sha,
      path`` plus a per-source ``registered_marketplaces`` array (written sorted
      for deterministic, byte-stable output) and followed by ``[[sources.includes]]``
      chains (recursively), ``[[sources.projects]]`` entries, and the v5
      ``[[sources.content_pins]]`` array (written sorted by project name + path so
      the serialised lock is byte-stable regardless of capture order).

    String values are encoded as TOML basic strings with all required control-
    character escapes applied.

    Args:
        lockfile: The ``Lockfile`` to serialise.

    Returns:
        A TOML-formatted string representing the lockfile, ending with a newline.
    """
    lines: list[str] = []

    lines.append(f"schema_version = {lockfile.schema_version}")
    lines.append(f"generated_at = {_toml_str(lockfile.generated_at)}")
    lines.append(f"generator = {_toml_str(lockfile.generator)}")
    lines.append(f"kanon_hash = {_toml_str(lockfile.kanon_hash)}")
    lines.append(f"marketplace_registered = {str(lockfile.marketplace_registered).lower()}")
    lines.append(f"marketplace_dir = {_toml_str(lockfile.marketplace_dir)}")

    for source in lockfile.sources:
        lines.append("")
        lines.append("[[sources]]")
        lines.append(f"alias = {_toml_str(source.alias)}")
        lines.append(f"name = {_toml_str(source.name)}")
        lines.append(f"url = {_toml_str(source.url)}")
        lines.append(f"ref_spec = {_toml_str(source.ref_spec)}")
        lines.append(f"resolved_ref = {_toml_str(source.resolved_ref)}")
        lines.append(f"resolved_sha = {_toml_str(source.resolved_sha)}")
        lines.append(f"path = {_toml_str(source.path)}")

        lines.append(f"registered_marketplaces = {_toml_str_array(sorted(source.registered_marketplaces))}")
        if source.includes:
            _serialize_include_entries(source.includes, "sources.includes", lines)
        for project in source.projects:
            lines.append("")
            lines.append("[[sources.projects]]")
            lines.append(f"name = {_toml_str(project.name)}")
            lines.append(f"url = {_toml_str(project.url)}")
            lines.append(f"canonical_url = {_toml_str(project.canonical_url)}")
            lines.append(f"ref_spec = {_toml_str(project.ref_spec)}")
            lines.append(f"resolved_ref = {_toml_str(project.resolved_ref)}")
            lines.append(f"resolved_sha = {_toml_str(project.resolved_sha)}")
        for pin in sorted(source.content_pins, key=lambda p: (p.name, p.path)):
            lines.append("")
            lines.append("[[sources.content_pins]]")
            lines.append(f"name = {_toml_str(pin.name)}")
            lines.append(f"path = {_toml_str(pin.path)}")
            lines.append(f"resolved_sha = {_toml_str(pin.resolved_sha)}")

    return "\n".join(lines) + "\n"


def read_lockfile(path: Path) -> Lockfile:
    """Parse a TOML lockfile from disk into the ``Lockfile`` dataclass tree.

    Applies every validation rule from spec Section 5 and the migration policy
    from spec Section 5.2:
      - ``resolved_sha``: exactly 40 or 64 lowercase hex digits.
      - ``ref_spec`` (per source and per project): PEP 440 SpecifierSet,
        ``refs/...`` prefix, or branch-charset regex -- with optional monorepo
        path prefix.
      - ``canonical_url`` on every ``ProjectEntry``: must equal
        ``canonicalize_repo_url(entry.url)``.
      - ``path`` and ``path_in_repo``: must not contain NUL, newline, or tab.
      - ``schema_version > CURRENT_SCHEMA_VERSION``: raises ``LockfileSchemaError``
        with message "lockfile schema v<N> written by newer kanon; upgrade kanon-cli."
      - ``schema_version < CURRENT_SCHEMA_VERSION``: schema v5 (spec Section 5.2,
        AMENDED 2026-06-25) follows the same no-silent-upgrader policy as the v4
        breaking major.  Any older lock (v1, v2, v3, v4) fails fast with an
        actionable ``LockfileSchemaError`` instructing the operator to regenerate
        the lock via ``kanon add`` / ``kanon install``.
      - ``schema_version == CURRENT_SCHEMA_VERSION``: parsed and validated directly.

    Args:
        path: Filesystem path to the TOML lockfile.

    Returns:
        A fully populated ``Lockfile`` dataclass instance.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        LockfileSchemaError: If ``schema_version > CURRENT_SCHEMA_VERSION`` (forward-
            incompatible) or if ``schema_version < CURRENT_SCHEMA_VERSION`` (an older
            lock under the v4 breaking major, which is a hard fail-fast regenerate).
        LockfileValidationError: If any field value violates a validation rule,
            with an error message naming the offending field path and value.
    """
    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    schema_version = data["schema_version"]
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise LockfileSchemaError(f"lockfile schema v{schema_version} written by newer kanon; upgrade kanon-cli.")
    if schema_version < CURRENT_SCHEMA_VERSION:
        raise LockfileSchemaError(
            f"ERROR: lockfile schema v{schema_version} is incompatible with this kanon "
            f"version (schema v{CURRENT_SCHEMA_VERSION}).\n"
            f"  Path: {path}\n"
            f"  Schema v{CURRENT_SCHEMA_VERSION} adds per-source content-SHA pins "
            f"([[sources.content_pins]]) on top of the v4 alias-keyed source entries; "
            f"older locks carry no content pins and are not silently upgraded.\n"
            f"  There is no automatic upgrade from schema v{schema_version}.\n"
            f"  Remediation: regenerate the lockfile by running 'kanon add' to refresh the "
            f"alias-keyed declarations, then 'kanon install' to rewrite the lock at schema "
            f"v{CURRENT_SCHEMA_VERSION}."
        )

    kanon_hash = data["kanon_hash"]
    _validate_kanon_hash(kanon_hash)

    raw_sources: list[dict[str, Any]] = data.get("sources", [])
    sources = [_parse_source_entry(raw, i) for i, raw in enumerate(raw_sources)]

    return Lockfile(
        schema_version=schema_version,
        generated_at=data["generated_at"],
        generator=data["generator"],
        kanon_hash=kanon_hash,
        sources=sources,
        marketplace_registered=bool(data.get("marketplace_registered", False)),
        marketplace_dir=str(data.get("marketplace_dir", "")),
    )


def write_lockfile(lockfile: Lockfile, path: Path) -> None:
    """Serialise ``lockfile`` to TOML and atomically replace ``path``.

    Atomicity contract (spec Section 4.7.1):
      - A temp file is created in ``path.parent`` with a ``.tmp.<pid>.<rand>`` suffix.
      - The TOML content is written and fsynced to the temp file.
      - ``os.replace`` renames the temp file over ``path`` in a single kernel call.
      - A reader observing ``path`` sees either the prior full content or the new
        full content, never a truncated intermediate state.
      - Two concurrent writers use different pids/rand suffixes, so they never
        collide on the temp path.

    Args:
        lockfile: The ``Lockfile`` to serialise.
        path: Destination path for the lockfile.

    Raises:
        OSError: If the temp file cannot be created, written, fsynced, or renamed.
    """
    toml_bytes = _serialize_toml(lockfile).encode("utf-8")

    rand_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    tmp_suffix = f".tmp.{os.getpid()}.{rand_suffix}"

    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=path.parent, suffix=tmp_suffix)
    tmp_path = Path(tmp_path_str)
    try:
        try:
            with os.fdopen(tmp_fd, "wb") as tmp_f:
                tmp_f.write(toml_bytes)
                tmp_f.flush()
                os.fsync(tmp_f.fileno())
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def check_lockfile_consistency(
    kanon_aliases: list[str],
    kanon_ref_specs: dict[str, str],
    lockfile: Lockfile,
) -> None:
    """Verify ``.kanon`` and ``.kanon.lock`` agree (spec FR-24, Section 4.5).

    The shared consistency check that ``kanon validate lockfile`` runs and that
    ``kanon install`` runs before it resolves (spec Section 4.3): a drifted pair
    makes the default install fail fast (exit 1) without mutating the lock.  It
    operates on already-parsed inputs so this module stays a pure lockfile
    component and does not depend on the ``.kanon`` parser.

    Three independent drift conditions are checked, each raising a
    ``LockfileConsistencyError`` naming the offending alias(es):

      1. Alias uniqueness -- ``kanon_aliases`` must contain no duplicate alias.
         A duplicate means two source declarations in ``.kanon`` share an alias,
         which makes the alias-keyed lock ambiguous.
      2. Alias-set parity -- the set of aliases in ``.kanon.lock`` must equal the
         set of aliases declared in ``.kanon``.  An alias present in only one of
         the two files is reported (added in ``.kanon`` but missing from the lock,
         or orphaned in the lock but removed from ``.kanon``).
      3. Per-alias ref-spec parity -- for every shared alias, the ``ref_spec``
         recorded in ``.kanon.lock`` must equal the revision declared for that
         alias in ``.kanon``.

    Args:
        kanon_aliases: The ordered list of source aliases declared in ``.kanon``.
            Passed as a list (not a set) so duplicates are visible and condition
            (1) is checkable.  Every alias must have a matching key in
            ``kanon_ref_specs``.
        kanon_ref_specs: Mapping of each ``.kanon`` alias to its declared revision
            (the ref-spec). The revision is the value compared against the lock
            entry's ``ref_spec`` field.
        lockfile: The parsed ``.kanon.lock`` whose ``sources`` carry the
            alias-keyed entries (schema v5).

    Raises:
        LockfileConsistencyError: If a ``.kanon`` alias is duplicated, if the
            ``.kanon`` and ``.kanon.lock`` alias sets differ, or if any shared
            alias has a mismatched ref-spec.
    """

    seen: set[str] = set()
    duplicates: list[str] = []
    for alias in kanon_aliases:
        if alias in seen and alias not in duplicates:
            duplicates.append(alias)
        seen.add(alias)
    if duplicates:
        raise LockfileConsistencyError(
            f"ERROR: duplicate source alias in .kanon: {', '.join(sorted(duplicates))}.\n"
            f"  Each source alias in .kanon must be unique; the alias keys the entry "
            f"in .kanon.lock.\n"
            f"  Remediation: rename the conflicting KANON_SOURCE_<alias>_* declarations "
            f"in .kanon so every alias is distinct, then re-run 'kanon install'."
        )

    kanon_alias_set = set(kanon_aliases)
    lock_alias_set = {source.alias for source in lockfile.sources}

    missing_in_lock = sorted(kanon_alias_set - lock_alias_set)
    orphaned_in_lock = sorted(lock_alias_set - kanon_alias_set)
    if missing_in_lock or orphaned_in_lock:
        raise LockfileConsistencyError(
            f"ERROR: .kanon and .kanon.lock alias sets differ.\n"
            f"  Declared in .kanon but missing from .kanon.lock: "
            f"{', '.join(missing_in_lock) if missing_in_lock else '(none)'}\n"
            f"  Present in .kanon.lock but not declared in .kanon: "
            f"{', '.join(orphaned_in_lock) if orphaned_in_lock else '(none)'}\n"
            f"  Remediation: run 'kanon install --reconcile' to reconcile .kanon.lock "
            f"with the current .kanon declarations, or 'kanon install --refresh-lock' "
            f"to rebuild the lock from scratch."
        )

    mismatches: list[str] = []
    for source in lockfile.sources:
        declared_ref_spec = kanon_ref_specs[source.alias]
        if source.ref_spec != declared_ref_spec:
            mismatches.append(
                f"    alias {source.alias!r}: .kanon revision={declared_ref_spec!r} "
                f"!= .kanon.lock ref_spec={source.ref_spec!r}"
            )
    if mismatches:
        joined = "\n".join(sorted(mismatches))
        raise LockfileConsistencyError(
            f"ERROR: .kanon and .kanon.lock ref-specs differ for one or more aliases.\n"
            f"{joined}\n"
            f"  Remediation: run 'kanon install --reconcile' to re-resolve and rewrite "
            f".kanon.lock with the current .kanon revisions, or "
            f"'kanon install --refresh-lock' to rebuild the lock from scratch."
        )
