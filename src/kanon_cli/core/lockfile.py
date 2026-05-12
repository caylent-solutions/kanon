"""TOML lockfile parser and atomic writer -- schema v1.

Public entry points:
  - ``read_lockfile(path: Path) -> Lockfile``: parse and validate a TOML lockfile.
  - ``write_lockfile(lockfile: Lockfile, path: Path) -> None``: atomically serialise
    a Lockfile to disk using a write-temp-then-rename pattern.

Exception hierarchy:
  - ``LockfileSchemaError``: raised when the schema_version is not supported.
  - ``LockfileValidationError``: raised when a field value violates a validation rule.

Spec source: spec Section 5 (Lockfile format and validation rules) and
Section 4.7.1 (atomicity contract for the lockfile writer).
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w
from packaging.requirements import InvalidRequirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from kanon_cli.core.url import canonicalize_repo_url

# -- Compiled validation patterns --

# resolved_sha must be exactly 40 or 64 lowercase hex digits (SHA-1 or SHA-256).
_SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")

# branch-name charset for the third accept rule of revision_spec validation.
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9_./+-]+$")

# Characters forbidden in path / path_in_repo fields.
_FORBIDDEN_PATH_CHARS: tuple[tuple[str, str], ...] = (
    ("\x00", "U+0000 (NUL)"),
    ("\n", "U+000A (newline)"),
    ("\t", "U+0009 (tab)"),
)


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Dataclass tree (mirrors the TOML schema exactly)
# ---------------------------------------------------------------------------


@dataclass
class ProjectEntry:
    """A single row under ``[[sources.projects]]``."""

    name: str
    url: str
    canonical_url: str
    revision_spec: str
    resolved_ref: str
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
    """A single row under ``[[sources]]``."""

    name: str
    url: str
    revision_spec: str
    resolved_ref: str
    resolved_sha: str
    path: str
    includes: list[IncludeEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)


@dataclass
class CatalogBlock:
    """The ``[catalog]`` block."""

    source: str
    url: str
    revision_spec: str
    resolved_ref: str
    resolved_sha: str


@dataclass
class Lockfile:
    """Root lockfile dataclass mirroring the top-level TOML structure."""

    schema_version: int
    generated_at: str
    generator: str
    kanon_hash: str
    catalog: CatalogBlock
    sources: list[SourceEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Private validation helpers
# ---------------------------------------------------------------------------


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


def _validate_revision_spec(spec: str, field_path: str) -> None:
    """Raise ``LockfileValidationError`` if ``spec`` fails all three accept rules.

    Accept rules (any one suffices):
      1. Parses as ``packaging.specifiers.SpecifierSet`` (PEP 440), optionally
         preceded by a monorepo path prefix ending with ``/``.
      2. Starts with ``refs/`` (literal git ref).
      3. Matches the branch-charset regex ``^[a-zA-Z0-9_./+-]+$``.

    Args:
        spec: The revision_spec value to validate.
        field_path: Dot-path of the field for the error message.

    Raises:
        LockfileValidationError: If none of the three rules accept the value.
    """
    if not spec:
        raise LockfileValidationError(
            f"ERROR: Empty revision_spec at '{field_path}'.\n"
            f"  Value: {spec!r}\n"
            f"  Expected: a PEP 440 specifier (e.g. '==1.0.0'), a git ref "
            f"(e.g. 'refs/heads/main'), or a branch name (e.g. 'main').\n"
            f"  Remediation: update the revision_spec in your .kanon file and re-lock."
        )

    # Rule 2: refs/ prefix
    if spec.startswith("refs/"):
        return

    # Rule 3: branch-charset regex
    if _BRANCH_RE.match(spec):
        return

    # Rule 1: PEP 440 SpecifierSet -- strip monorepo path prefix if present
    suffix = spec
    if "/" in spec:
        # Strip the leading path component(s) up to the last "/" before the specifier
        # e.g. "subpackage/==1.0.0" -> "==1.0.0"
        last_slash = spec.rfind("/")
        suffix = spec[last_slash + 1 :]

    try:
        SpecifierSet(suffix)
        return
    except (InvalidSpecifier, InvalidRequirement, ValueError):
        pass

    raise LockfileValidationError(
        f"ERROR: Invalid revision_spec at '{field_path}'.\n"
        f"  Value: {spec!r}\n"
        f"  Expected one of:\n"
        f"    - PEP 440 SpecifierSet (e.g. '==1.0.0', '~=2.0.0', '>=1.0,<2.0')\n"
        f"    - Optional monorepo prefix: 'subpackage/==1.0.0'\n"
        f"    - Git ref: 'refs/heads/main'\n"
        f"    - Branch name matching ^[a-zA-Z0-9_./+-]+$\n"
        f"  Remediation: update the revision_spec in your .kanon file and re-lock."
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


# ---------------------------------------------------------------------------
# Private parsing helpers
# ---------------------------------------------------------------------------


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

    revision_spec = raw["revision_spec"]
    _validate_revision_spec(revision_spec, f"{field_path}.revision_spec")

    url = raw["url"]
    canonical_url = raw["canonical_url"]
    _validate_canonical_url(url, canonical_url, f"{field_path}.canonical_url")

    return ProjectEntry(
        name=raw["name"],
        url=url,
        canonical_url=canonical_url,
        revision_spec=revision_spec,
        resolved_ref=raw["resolved_ref"],
        resolved_sha=resolved_sha,
    )


def _parse_source_entry(raw: dict[str, Any], source_idx: int) -> SourceEntry:
    """Parse a raw TOML dict into a ``SourceEntry``, validating all fields.

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

    revision_spec = raw["revision_spec"]
    _validate_revision_spec(revision_spec, f"{field_path}.revision_spec")

    path = raw["path"]
    _validate_path_chars(path, f"{field_path}.path")

    raw_includes: list[dict[str, Any]] = raw.get("includes", [])
    includes = [_parse_include_entry(item, f"{field_path}.includes[{i}]") for i, item in enumerate(raw_includes)]

    raw_projects: list[dict[str, Any]] = raw.get("projects", [])
    projects = [_parse_project_entry(item, f"{field_path}.projects[{i}]") for i, item in enumerate(raw_projects)]

    return SourceEntry(
        name=raw["name"],
        url=raw["url"],
        revision_spec=revision_spec,
        resolved_ref=raw["resolved_ref"],
        resolved_sha=resolved_sha,
        path=path,
        includes=includes,
        projects=projects,
    )


def _parse_catalog_block(raw: dict[str, Any]) -> CatalogBlock:
    """Parse the ``[catalog]`` TOML block into a ``CatalogBlock``, validating all fields.

    Args:
        raw: The TOML dict for the ``[catalog]`` block.

    Returns:
        A validated ``CatalogBlock`` dataclass instance.

    Raises:
        LockfileValidationError: If any field fails validation.
    """
    resolved_sha = raw["resolved_sha"]
    _validate_resolved_sha(resolved_sha, "catalog.resolved_sha")

    revision_spec = raw["revision_spec"]
    _validate_revision_spec(revision_spec, "catalog.revision_spec")

    return CatalogBlock(
        source=raw["source"],
        url=raw["url"],
        revision_spec=revision_spec,
        resolved_ref=raw["resolved_ref"],
        resolved_sha=resolved_sha,
    )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _include_entry_to_dict(entry: IncludeEntry) -> dict[str, Any]:
    """Convert an ``IncludeEntry`` to a plain dict suitable for ``tomli_w``.

    Recursively converts nested ``includes`` lists.

    Args:
        entry: The ``IncludeEntry`` to serialise.

    Returns:
        A dict with all fields in TOML-compatible types.
    """
    d: dict[str, Any] = {
        "name": entry.name,
        "path_in_repo": entry.path_in_repo,
        "url": entry.url,
        "resolved_sha": entry.resolved_sha,
    }
    if entry.includes:
        d["includes"] = [_include_entry_to_dict(child) for child in entry.includes]
    return d


def _project_entry_to_dict(entry: ProjectEntry) -> dict[str, Any]:
    """Convert a ``ProjectEntry`` to a plain dict suitable for ``tomli_w``.

    Args:
        entry: The ``ProjectEntry`` to serialise.

    Returns:
        A dict with all fields in TOML-compatible types.
    """
    return {
        "name": entry.name,
        "url": entry.url,
        "canonical_url": entry.canonical_url,
        "revision_spec": entry.revision_spec,
        "resolved_ref": entry.resolved_ref,
        "resolved_sha": entry.resolved_sha,
    }


def _source_entry_to_dict(entry: SourceEntry) -> dict[str, Any]:
    """Convert a ``SourceEntry`` to a plain dict suitable for ``tomli_w``.

    Args:
        entry: The ``SourceEntry`` to serialise.

    Returns:
        A dict with all fields in TOML-compatible types.
    """
    d: dict[str, Any] = {
        "name": entry.name,
        "url": entry.url,
        "revision_spec": entry.revision_spec,
        "resolved_ref": entry.resolved_ref,
        "resolved_sha": entry.resolved_sha,
        "path": entry.path,
    }
    if entry.includes:
        d["includes"] = [_include_entry_to_dict(inc) for inc in entry.includes]
    if entry.projects:
        d["projects"] = [_project_entry_to_dict(proj) for proj in entry.projects]
    return d


def _lockfile_to_dict(lockfile: Lockfile) -> dict[str, Any]:
    """Convert a ``Lockfile`` to a plain dict suitable for ``tomli_w``.

    Args:
        lockfile: The ``Lockfile`` to serialise.

    Returns:
        An ordered dict with the top-level TOML keys in spec-canonical order.
    """
    return {
        "schema_version": lockfile.schema_version,
        "generated_at": lockfile.generated_at,
        "generator": lockfile.generator,
        "kanon_hash": lockfile.kanon_hash,
        "catalog": {
            "source": lockfile.catalog.source,
            "url": lockfile.catalog.url,
            "revision_spec": lockfile.catalog.revision_spec,
            "resolved_ref": lockfile.catalog.resolved_ref,
            "resolved_sha": lockfile.catalog.resolved_sha,
        },
        "sources": [_source_entry_to_dict(src) for src in lockfile.sources],
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def read_lockfile(path: Path) -> Lockfile:
    """Parse a TOML lockfile from disk into the ``Lockfile`` dataclass tree.

    Applies every validation rule from spec Section 5:
      - ``resolved_sha``: exactly 40 or 64 lowercase hex digits.
      - ``revision_spec``: PEP 440 SpecifierSet, ``refs/...`` prefix, or
        branch-charset regex -- with optional monorepo path prefix.
      - ``canonical_url`` on every ``ProjectEntry``: must equal
        ``canonicalize_repo_url(entry.url)``.
      - ``path`` and ``path_in_repo``: must not contain NUL, newline, or tab.
      - ``schema_version``: must be 1; any other value raises ``LockfileSchemaError``.

    Args:
        path: Filesystem path to the TOML lockfile.

    Returns:
        A fully populated ``Lockfile`` dataclass instance.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        LockfileSchemaError: If ``schema_version`` is not 1.
        LockfileValidationError: If any field value violates a validation rule,
            with an error message naming the offending field path and value.
    """
    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    schema_version = data["schema_version"]
    if schema_version != 1:
        raise LockfileSchemaError(f"lockfile schema v{schema_version} not supported by this kanon version")

    kanon_hash = data["kanon_hash"]
    _validate_resolved_sha(kanon_hash, "kanon_hash")

    catalog = _parse_catalog_block(data["catalog"])

    raw_sources: list[dict[str, Any]] = data.get("sources", [])
    sources = [_parse_source_entry(raw, i) for i, raw in enumerate(raw_sources)]

    return Lockfile(
        schema_version=schema_version,
        generated_at=data["generated_at"],
        generator=data["generator"],
        kanon_hash=kanon_hash,
        catalog=catalog,
        sources=sources,
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
    import random
    import string
    import tempfile

    data = _lockfile_to_dict(lockfile)
    toml_bytes = tomli_w.dumps(data).encode("utf-8")

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
