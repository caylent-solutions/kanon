"""kanon list subcommand: list catalog entry names from a manifest repo.

Reads ``*-marketplace.xml`` files under ``repo-specs/`` in the resolved
manifest repo and prints one entry name per line to stdout, sorted
lexicographically.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.1 (data source + default output) and Section 4 header
(canonical missing-catalog error and env-var precedence).
Section 4.1 flag-table row ``--detail`` for the per-entry detail formatter.
Section 4.1 flag-table rows ``--tree``, ``--max-depth N``,
``--no-filter-required`` and the threshold guardrail.
Section 4.1 flag-table rows ``--all-versions``, ``--limit N``,
``--no-limit``, ``--since-version <spec>`` for the historical-versions walker.
Section 4.1 flag-table row ``--format {names,json}`` for JSON output.
Section 4.1 flag-table rows ``<substring>`` (positional), ``--regex <pattern>``,
``--match-fields <csv>`` for the filter framework.

Environment variables:
- ``KANON_CATALOG_SOURCE``: catalog source override (CLI flag wins).
- ``KANON_TREE_NO_FILTER_THRESHOLD``: overrides the default threshold (20)
  above which ``kanon list --tree`` requires a filter.
- ``KANON_LIST_LIMIT``: overrides the default version-walk cap (50).
- ``KANON_LIST_FORMAT``: overrides the output format (CLI flag wins).
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

import defusedxml.ElementTree as ET
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    KANON_LIST_LIMIT,
    KANON_TREE_NO_FILTER_THRESHOLD,
    LIST_EMPTY_CATALOG_NOTE,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.core.catalog import _parse_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.metadata import CatalogMetadata, _parse_catalog_metadata
from kanon_cli.version import is_version_constraint, resolve_version

# -- Detail formatter private constants --
_DETAIL_MISSING_PLACEHOLDER = "<missing>"
_DETAIL_LABEL_WIDTH = 12

# -- Format flag private constants --
# Environment variable that sets the output format for 'kanon list'.
# Choices: 'names' (default), 'json'.
# CLI flag --format takes precedence when both are set.
_KANON_LIST_FORMAT_ENV_VAR = "KANON_LIST_FORMAT"

# ---------------------------------------------------------------------------
# Filter framework public constants
# ---------------------------------------------------------------------------

# Spec canonical phrasing for zero-match stderr note (Section 4.1).
LIST_FILTER_ZERO_MATCH_NOTE = "0 entries match filter"

# Legal field names for --match-fields (in the same order as the spec table).
MATCH_FIELDS_LEGAL: tuple[str, ...] = ("name", "display-name", "description", "keywords")


# ---------------------------------------------------------------------------
# All-versions walker data types
# ---------------------------------------------------------------------------


@dataclass
class VersionRow:
    """A single row of output for ``--all-versions`` mode.

    Carries the data needed for both human-readable output (``<name>@<version>``)
    and the structured JSON renderer in E2-F2-S1-T5 (``{name, version, ref, sha}``).

    Attributes:
        name: Catalog entry name.
        version: Version string (e.g. ``1.2.3``).
        ref: Full git tag ref (e.g. ``refs/tags/1.2.3``).
        sha: Commit SHA or abbreviated SHA associated with this tag. May be
            an empty string when the SHA is not available.
    """

    name: str
    version: str
    ref: str
    sha: str

    def __str__(self) -> str:
        """Return the spec-canonical per-row text: ``<name>@<version>``."""
        return f"{self.name}@{self.version}"


# -- Tree renderer private constants --
_TREE_CONNECTOR_INTERMEDIATE = "+--"
_TREE_CONNECTOR_LAST = "\\--"
_TREE_COLUMN_CONTINUATION = "|   "
_TREE_COLUMN_BLANK = "    "

# Guardrail error template (no em-dashes, no hardcoded values).
_TREE_GUARDRAIL_ERROR = (
    "ERROR: kanon list --tree requires a filter when the catalog has more than "
    "{threshold} entries.\n"
    "The catalog at the given source has {count} entries, which exceeds the threshold.\n"
    "\n"
    "Supply one of the following to proceed:\n"
    "  <name>                  positional substring filter (e.g. kanon list --tree mylib)\n"
    "  --regex <pattern>       regular-expression filter\n"
    "  --max-depth 0           show only root entry nodes (no XML or project layers)\n"
    "  --no-filter-required    bypass this guardrail entirely\n"
    "\n"
    "Or raise the threshold:\n"
    "  KANON_TREE_NO_FILTER_THRESHOLD={threshold_plus} kanon list --tree ...\n"
)


# ---------------------------------------------------------------------------
# All-versions walker helpers
# ---------------------------------------------------------------------------


def _list_tags_from_url(url: str) -> list[tuple[str, str]]:
    """Return ``(ref, sha)`` pairs from ``git ls-remote --tags <url>``.

    Runs ``git ls-remote --tags`` and filters out ``^{}`` peeled refs.

    Args:
        url: Git repository URL.

    Returns:
        List of ``(ref, sha)`` tuples where ``ref`` is the full tag ref
        (e.g. ``refs/tags/1.0.0``) and ``sha`` is the associated commit SHA.

    Raises:
        SystemExit: When git ls-remote fails.
    """
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: git ls-remote failed for {url}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    pairs: list[tuple[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sha, ref = parts[0], parts[1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            pairs.append((ref, sha))
    return pairs


def _sort_versions_newest_first(
    tags: list[str],
) -> list[tuple[str, Version, str]]:
    """Parse and sort tag refs newest-first by PEP 440 version.

    Each tag's last ``/``-delimited path component is parsed as a PEP 440
    ``packaging.version.Version``. Tags whose last component does not parse
    are silently skipped (the loud-error for zero parseable tags is raised
    higher up in ``_walk_all_versions``).

    Args:
        tags: List of full git tag ref strings (e.g. ``refs/tags/1.0.0``).

    Returns:
        List of ``(ref, Version, sha)`` triples, sorted newest-first.
        The ``sha`` field is an empty string because this function operates
        on bare ref strings without SHA information. Use
        ``_sort_version_pairs_newest_first`` when SHAs are available.
    """
    parsed: list[tuple[str, Version, str]] = []
    for ref in tags:
        version_str = ref.rsplit("/", 1)[-1]
        try:
            parsed.append((ref, Version(version_str), ""))
        except InvalidVersion:
            continue
    parsed.sort(key=lambda t: t[1], reverse=True)
    return parsed


def _sort_version_pairs_newest_first(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, Version, str]]:
    """Parse and sort ``(ref, sha)`` pairs newest-first by PEP 440 version.

    Parses each tag's last ``/``-delimited path component as a PEP 440
    version. Tags that do not parse are silently skipped here; the caller
    is responsible for raising a loud error when zero PEP 440 tags remain.

    Args:
        pairs: List of ``(ref, sha)`` tuples from ``git ls-remote``.

    Returns:
        List of ``(ref, Version, sha)`` triples sorted newest-first.
    """
    parsed: list[tuple[str, Version, str]] = []
    for ref, sha in pairs:
        version_str = ref.rsplit("/", 1)[-1]
        try:
            parsed.append((ref, Version(version_str), sha))
        except InvalidVersion:
            continue
    parsed.sort(key=lambda t: t[1], reverse=True)
    return parsed


def _filter_versions_by_constraint(
    sorted_triples: list[tuple[str, Version, str]],
    constraint: str,
) -> list[tuple[str, Version, str]]:
    """Filter version triples by a PEP 440 specifier constraint.

    Args:
        sorted_triples: List of ``(ref, Version, sha)`` triples.
        constraint: A PEP 440 specifier string (e.g. ``>=1.0,<2.0``).

    Returns:
        Filtered list preserving the original order.

    Raises:
        ValueError: When the constraint string is not valid PEP 440.
    """
    try:
        specifier = SpecifierSet(constraint)
    except InvalidSpecifier as exc:
        raise ValueError(f"invalid PEP 440 constraint '{constraint}': {exc}") from exc

    return [(ref, ver, sha) for ref, ver, sha in sorted_triples if ver in specifier]


def _build_all_versions_rows(
    catalog_names: list[str],
    sorted_versions: list[tuple[str, Version, str]],
) -> list[VersionRow]:
    """Build the flat list of ``VersionRow`` objects for ``--all-versions`` output.

    Emits one ``VersionRow`` per catalog entry per version, in newest-first
    version order. Within each version, entries are sorted lexicographically.

    Args:
        catalog_names: Catalog entry names. Need not be pre-sorted; this
            function sorts them lexicographically.
        sorted_versions: List of ``(ref, Version, sha)`` triples in
            newest-first order.

    Returns:
        Flat list of :class:`VersionRow` objects ready for output.
    """
    sorted_names = sorted(catalog_names)
    rows: list[VersionRow] = []
    for ref, ver, sha in sorted_versions:
        for name in sorted_names:
            rows.append(VersionRow(name=name, version=str(ver), ref=ref, sha=sha))
    return rows


def _walk_all_versions(
    catalog_source: str,
    limit: int,
    since_version: str | None,
) -> list[VersionRow]:
    """Walk historical catalog versions and return all-versions rows.

    Fetches tags from the manifest repo via ``git ls-remote --tags``,
    sorts them newest-first, applies the ``--limit`` cap and optional
    ``--since-version`` PEP 440 filter, clones each version, and builds
    the flat ``VersionRow`` list.

    Args:
        catalog_source: A ``<git_url>@<ref>`` string. The ``@<ref>`` part
            is used only as a default ref for initial tag discovery; the
            actual walking iterates over all PEP 440-valid tags.
        limit: Maximum number of versions to walk. ``0`` means unlimited.
        since_version: Optional PEP 440 specifier string. When provided,
            only versions satisfying the specifier are walked.

    Returns:
        Flat list of :class:`VersionRow` objects, newest version first.

    Raises:
        SystemExit: On git ls-remote or git clone failure.
        ValueError: When ``since_version`` is not a valid PEP 440 specifier.
    """
    url, _ref = _parse_catalog_source(catalog_source)

    pairs = _list_tags_from_url(url)
    if not pairs:
        return []

    sorted_triples = _sort_version_pairs_newest_first(pairs)
    if not sorted_triples:
        # Zero PEP 440-parseable tags -- surface the skipped tags via a loud error.
        skipped = [ref for ref, _ in pairs]
        from kanon_cli.version import _format_zero_pep440_tags_error

        msg = _format_zero_pep440_tags_error("refs/tags", skipped)
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)

    if since_version is not None:
        try:
            sorted_triples = _filter_versions_by_constraint(sorted_triples, since_version)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    # Apply version cap. limit=0 means unlimited.
    if limit > 0:
        sorted_triples = sorted_triples[:limit]

    if not sorted_triples:
        return []

    # For the all-versions output we do NOT clone each version individually --
    # we clone the repo once at the newest version to obtain the catalog entry
    # names, then emit one row per (name, version) combination for all versions.
    # This matches the spec worked-example which shows the entry names as they
    # exist in the manifest repo's HEAD, attributed to each historical version.
    newest_ref = sorted_triples[0][0]
    newest_version_str = newest_ref.rsplit("/", 1)[-1]

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-list-av-"))
    repo_dir = clone_dir / "repo"

    clone_result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", newest_version_str, url, str(repo_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if clone_result.returncode != 0:
        print(
            f"ERROR: Failed to clone manifest repo from {url}@{newest_version_str}: {clone_result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    catalog_names = _build_sorted_index(repo_dir)
    return _build_all_versions_rows(catalog_names, sorted_triples)


def _resolve_manifest_repo(catalog_source: str) -> pathlib.Path:
    """Resolve the manifest repo root directory from a catalog source string.

    Clones the manifest repo at the given ``<git_url>@<ref>`` source into a
    temporary directory and returns the root of that clone (NOT the
    ``catalog/`` subdirectory -- ``kanon list`` needs the full repo root to
    walk ``repo-specs/``).

    Args:
        catalog_source: A non-empty ``<git_url>@<ref>`` string. Callers must
            validate that this is non-empty and print the canonical
            missing-catalog error before calling this function.

    Returns:
        Path to the cloned manifest repo root directory.

    Raises:
        SystemExit: When the git clone fails.
        ValueError: When the catalog source format is invalid.
    """
    url, ref = _parse_catalog_source(catalog_source)

    if ref == "latest":
        ref = "*"
    if is_version_constraint(ref):
        resolved = resolve_version(url, ref)
        ref = resolved.removeprefix("refs/tags/")

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-list-"))
    repo_dir = clone_dir / "repo"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, url, str(repo_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: Failed to clone manifest repo from {url}@{ref}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    return repo_dir


def _walk_marketplace_xmls(manifest_root: pathlib.Path) -> list[pathlib.Path]:
    """Walk ``repo-specs/**/*-marketplace.xml`` under manifest_root.

    Reads ONLY files under the ``repo-specs/`` directory. The legacy
    ``catalog/<name>/`` directory is explicitly excluded per spec Section 4.1.

    Args:
        manifest_root: Root directory of the cloned manifest repo.

    Returns:
        List of :class:`pathlib.Path` objects pointing to discovered XML
        files. Empty when ``repo-specs/`` is absent or contains no
        ``*-marketplace.xml`` files.
    """
    repo_specs = manifest_root / "repo-specs"
    if not repo_specs.is_dir():
        return []
    return list(repo_specs.rglob("*-marketplace.xml"))


def _build_sorted_index(manifest_root: pathlib.Path) -> list[str]:
    """Build a lexicographically sorted list of catalog entry names.

    Walks ``repo-specs/**/*-marketplace.xml`` in manifest_root, parses each
    file with :func:`_parse_catalog_metadata`, collects the ``name`` field,
    and returns the names sorted.

    Args:
        manifest_root: Root directory of the cloned manifest repo.

    Returns:
        Sorted list of entry name strings. Empty when the catalog has no
        ``*-marketplace.xml`` files.
    """
    xml_paths = _walk_marketplace_xmls(manifest_root)
    names: list[str] = []
    for xml_path in xml_paths:
        metadata = _parse_catalog_metadata(xml_path)
        names.append(metadata.name)
    return sorted(names)


def _build_sorted_metadata(manifest_root: pathlib.Path) -> list[CatalogMetadata]:
    """Build a lexicographically sorted list of CatalogMetadata instances.

    Walks ``repo-specs/**/*-marketplace.xml`` in manifest_root, parses each
    file with :func:`_parse_catalog_metadata`, and returns the results sorted
    by entry name. Used by ``--detail`` mode to obtain both names and field
    values in a single pass.

    Recommended-field warnings are emitted to stderr by
    :func:`_parse_catalog_metadata` as a side effect; this function does not
    add or suppress them.

    Args:
        manifest_root: Root directory of the cloned manifest repo.

    Returns:
        Sorted list of :class:`CatalogMetadata` instances. Empty when the
        catalog has no ``*-marketplace.xml`` files.
    """
    xml_paths = _walk_marketplace_xmls(manifest_root)
    entries: list[CatalogMetadata] = []
    for xml_path in xml_paths:
        metadata = _parse_catalog_metadata(xml_path)
        entries.append(metadata)
    return sorted(entries, key=lambda m: m.name)


def _format_detail_record(metadata: CatalogMetadata) -> str:
    """Format a single catalog entry as a human-readable multi-line record.

    Output shape (per spec Section 2.1 step 2)::

        <name>
          display-name : <display-name>
          description  : <description>
          version      : <version>
          type         : <type>

    Field labels are right-padded to :data:`_DETAIL_LABEL_WIDTH` so the
    ``' : '`` separator is at a consistent column position across all four
    field lines. Missing recommended fields (``type=None``) render as the
    :data:`_DETAIL_MISSING_PLACEHOLDER` constant (``<missing>``).

    Args:
        metadata: A parsed :class:`CatalogMetadata` instance.

    Returns:
        The formatted record string (no trailing newline).
    """
    type_value = metadata.type if metadata.type is not None else _DETAIL_MISSING_PLACEHOLDER

    def _field(label: str, value: str) -> str:
        padded_label = label.ljust(_DETAIL_LABEL_WIDTH)
        return f"  {padded_label} : {value}"

    lines = [
        metadata.name,
        _field("display-name", metadata.display_name),
        _field("description", metadata.description),
        _field("version", metadata.version),
        _field("type", type_value),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON renderers (--format json)
# ---------------------------------------------------------------------------


def _build_catalog_payload(entries: list[CatalogMetadata]) -> list[dict]:
    """Build the JSON-serialisable payload for a list of :class:`CatalogMetadata`.

    Each element is an object with the five fields specified in Section 4.1:
    ``name``, ``display-name``, ``type``, ``description``, ``version``.
    The ``type`` field is ``null`` in JSON when the metadata slot is ``None``.

    Used by :func:`_format_json_catalog` (for tests that inspect the JSON string)
    and by the :func:`run_list` handler that calls :func:`_emit_json_payload`
    directly.

    Args:
        entries: Sorted list of :class:`CatalogMetadata` instances.

    Returns:
        A list of dicts ready for JSON serialisation.
    """
    return [
        {
            "name": m.name,
            "display-name": m.display_name,
            "type": m.type,
            "description": m.description,
            "version": m.version,
        }
        for m in entries
    ]


def _format_json_catalog(entries: list[CatalogMetadata]) -> str:
    """Serialise a list of :class:`CatalogMetadata` to a JSON array string.

    Delegates to :func:`_build_catalog_payload` for the data structure and
    then calls ``json.dumps``.  Kept for backward compatibility with callers
    that need the serialised string directly (e.g. unit tests).

    Args:
        entries: Sorted list of :class:`CatalogMetadata` instances.

    Returns:
        A JSON-serialised string terminated by exactly one newline.
    """
    return json.dumps(_build_catalog_payload(entries)) + "\n"


def _build_all_versions_payload(rows: list[VersionRow]) -> list[dict]:
    """Build the JSON-serialisable payload for a list of :class:`VersionRow`.

    Each element is an object with the four fields specified in Section 4.1
    worked-example footer: ``name``, ``version``, ``ref``, ``sha``.

    Args:
        rows: List of :class:`VersionRow` instances.

    Returns:
        A list of dicts ready for JSON serialisation.
    """
    return [
        {
            "name": r.name,
            "version": r.version,
            "ref": r.ref,
            "sha": r.sha,
        }
        for r in rows
    ]


def _format_json_all_versions(rows: list[VersionRow]) -> str:
    """Serialise a list of :class:`VersionRow` to a JSON array string.

    Delegates to :func:`_build_all_versions_payload` for the data structure.
    Kept for backward compatibility with callers that need the serialised
    string directly (e.g. unit tests).

    Args:
        rows: List of :class:`VersionRow` instances.

    Returns:
        A JSON-serialised string terminated by exactly one newline.
    """
    return json.dumps(_build_all_versions_payload(rows)) + "\n"


# ---------------------------------------------------------------------------
# Tree renderer helpers
# ---------------------------------------------------------------------------


def _sha12_from_content(content: str) -> str:
    """Return a 12-character lowercase hex SHA-256 digest of ``content``.

    Used to produce the ``(<sha-12>)`` suffix on each tree node. The digest
    is deterministic and content-addressed.

    Args:
        content: The string content to hash.

    Returns:
        A 12-character lowercase hexadecimal string.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _sha12_from_path(path: pathlib.Path) -> str:
    """Return a 12-character lowercase hex SHA-256 digest of the file at ``path``.

    Args:
        path: Path to the file whose content is hashed.

    Returns:
        A 12-character lowercase hexadecimal string.

    Raises:
        OSError: When the file cannot be read.
    """
    return _sha12_from_content(path.read_text(encoding="utf-8"))


def _parse_xml_includes_and_projects(
    xml_path: pathlib.Path,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Parse ``<include>`` and ``<project>`` elements from a manifest XML file.

    Reads the XML at ``xml_path`` using :mod:`defusedxml.ElementTree` and
    returns two sequences:

    - ``includes``: list of ``name`` attribute values from ``<include>``
      elements.
    - ``projects``: list of ``(project_name, remote_fetch, revision)`` tuples
      from ``<project>`` elements. ``remote_fetch`` is resolved by looking up
      the ``<remote name="...">`` element whose ``name`` matches the
      ``<project remote="...">`` attribute. When no matching remote is found
      the fetch URL is reported as the literal remote name.

    This function never clones any repository; it reads only the local XML.

    Args:
        xml_path: Path to the manifest XML file.

    Returns:
        A ``(includes, projects)`` tuple.
    """
    try:
        tree = ET.parse(xml_path)
    except Exception:
        return [], []

    root = tree.getroot()
    if root is None:
        return [], []

    remotes: dict[str, str] = {}
    for remote_el in root.iter("remote"):
        name_attr = remote_el.get("name")
        fetch_attr = remote_el.get("fetch", "")
        if name_attr:
            remotes[name_attr] = fetch_attr

    includes: list[str] = []
    for include_el in root.iter("include"):
        inc_name = include_el.get("name")
        if inc_name:
            includes.append(inc_name)

    projects: list[tuple[str, str, str]] = []
    for project_el in root.iter("project"):
        proj_name = project_el.get("name", "")
        proj_remote = project_el.get("remote", "")
        proj_revision = project_el.get("revision", "")
        fetch_url = remotes.get(proj_remote, proj_remote)
        projects.append((proj_name, fetch_url, proj_revision))

    return includes, projects


def _resolve_include_path(
    inc_name: str,
    xml_path: pathlib.Path,
    manifest_root: pathlib.Path,
) -> pathlib.Path | None:
    """Resolve an include name to a filesystem path.

    Tries the path relative to ``xml_path``'s directory first, then relative
    to ``manifest_root``. Returns ``None`` when the file does not exist at
    either location.

    Args:
        inc_name: The ``name`` attribute value from an ``<include>`` element.
        xml_path: The XML file that contains the ``<include>`` directive.
        manifest_root: Root directory of the cloned manifest repo.

    Returns:
        Resolved :class:`pathlib.Path` when found, or ``None``.
    """
    for candidate in (xml_path.parent / inc_name, manifest_root / inc_name):
        if candidate.exists():
            return candidate
    return None


def _render_tree(
    manifest_root: pathlib.Path,
    entry_name: str,
    max_depth: int | None,
) -> list[str]:
    """Render a three-layer ASCII dependency tree for one catalog entry.

    The three conceptual layers map to depths as follows:

    - Depth 0 (layer a): ``entry <name>@<version> (<sha-12>)``
    - Depth 1 (layer b): ``+-- xml <include-name>@included (<sha-12>)``
    - Depth 2 (layer c): ``    +-- project <proj>@<revision> (<sha-12>)``

    ``max_depth=0`` renders only the root line (layer a).
    ``max_depth=1`` renders layers a and b (entry + XML includes).
    ``max_depth=None`` (unlimited) renders all three layers.

    ALL ``<project>`` entries -- whether in the root marketplace XML or in
    transitively included XMLs -- are treated as depth-2 nodes and suppressed
    by ``max_depth=1``.

    Box-drawing uses only ``+--``, ``|   ``, and ``\\--`` (ASCII-safe).
    No em-dash characters (U+2014) are used.

    The renderer does NOT clone any ``<project>`` repositories; it reads only
    local XML files from the manifest repo and reports the URL + ref recorded
    in the XML.

    Args:
        manifest_root: Root directory of the cloned manifest repo.
        entry_name: Catalog entry name.
        max_depth: Maximum tree depth to render. ``None`` means unlimited.
            ``0`` renders only the root entry node.

    Returns:
        List of formatted tree-line strings.

    Raises:
        FileNotFoundError: When no ``*-marketplace.xml`` for ``entry_name``
            is found under ``repo-specs/``.
    """
    xml_files = _walk_marketplace_xmls(manifest_root)
    entry_xml: pathlib.Path | None = None
    entry_version = "unknown"

    for xml_path in xml_files:
        try:
            metadata = _parse_catalog_metadata(xml_path)
        except Exception:
            continue
        if metadata.name == entry_name:
            entry_xml = xml_path
            entry_version = metadata.version
            break

    if entry_xml is None:
        raise FileNotFoundError(
            f"No *-marketplace.xml found for entry '{entry_name}' under {manifest_root / 'repo-specs'}"
        )

    sha = _sha12_from_path(entry_xml)
    lines: list[str] = [f"entry {entry_name}@{entry_version} ({sha})"]

    if max_depth is not None and max_depth == 0:
        return lines

    show_projects = max_depth is None or max_depth >= 2

    root_includes, root_projects = _parse_xml_includes_and_projects(entry_xml)

    # Resolve include names to paths (or track as placeholders when not found).
    include_paths: list[pathlib.Path] = []
    include_placeholders: list[str] = []
    for inc_name in root_includes:
        resolved = _resolve_include_path(inc_name, entry_xml, manifest_root)
        if resolved is not None:
            include_paths.append(resolved)
        else:
            include_placeholders.append(inc_name)

    # Determine if root projects (directly in the marketplace XML) should appear.
    # Per the three-layer model, projects are ALWAYS layer c (depth 2).
    # They are suppressed when max_depth < 2.

    # Total depth-1 items: xml includes + placeholders.
    # When no includes exist, root projects are promoted to depth-1 direct children
    # (conceptually still layer c but no intermediate xml node to attach them to).
    has_includes = bool(include_paths) or bool(include_placeholders)

    if has_includes:
        # Includes present: render includes at depth 1, their projects + root projects at depth 2.
        total_d1 = len(include_paths) + len(include_placeholders)

        for idx, inc_path in enumerate(include_paths):
            # The include node is last only if it is the last item AND there are no placeholders.
            is_last = idx == total_d1 - 1
            inc_prefix = _TREE_CONNECTOR_LAST if is_last else _TREE_CONNECTOR_INTERMEDIATE
            inc_indent = _TREE_COLUMN_BLANK if is_last else _TREE_COLUMN_CONTINUATION

            inc_sha = _sha12_from_path(inc_path)
            lines.append(f"{inc_prefix}xml {inc_path.stem}@included ({inc_sha})")

            if show_projects:
                _, inc_proj_list = _parse_xml_includes_and_projects(inc_path)
                for j, (proj_name, fetch_url, revision) in enumerate(inc_proj_list):
                    is_last_proj = j == len(inc_proj_list) - 1
                    proj_prefix = inc_indent + (_TREE_CONNECTOR_LAST if is_last_proj else _TREE_CONNECTOR_INTERMEDIATE)
                    proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                    proj_spec = revision if revision else "unspecified"
                    lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

        for idx, ph_name in enumerate(include_placeholders):
            abs_idx = len(include_paths) + idx
            is_last = abs_idx == total_d1 - 1
            ph_prefix = _TREE_CONNECTOR_LAST if is_last else _TREE_CONNECTOR_INTERMEDIATE
            lines.append(f"{ph_prefix}xml {ph_name}@unknown (000000000000)")

        # Root projects (from the root marketplace XML) at depth 2.
        # They appear after all include nodes, indented under the last include's indent.
        if show_projects and root_projects:
            # Use the indent of the last include node for nesting root projects.
            if include_paths:
                last_inc_idx = len(include_paths) - 1
                last_inc_is_last_d1 = last_inc_idx == total_d1 - 1
                last_inc_indent = _TREE_COLUMN_BLANK if last_inc_is_last_d1 else _TREE_COLUMN_CONTINUATION
            else:
                # Only placeholders exist; use empty indent for root projects.
                last_inc_indent = ""
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last_rp = j == len(root_projects) - 1
                proj_prefix = last_inc_indent + (_TREE_CONNECTOR_LAST if is_last_rp else _TREE_CONNECTOR_INTERMEDIATE)
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    else:
        # No includes: root projects appear as direct depth-1 children.
        if show_projects and root_projects:
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last = j == len(root_projects) - 1
                proj_prefix = _TREE_CONNECTOR_LAST if is_last else _TREE_CONNECTOR_INTERMEDIATE
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    return lines


# ---------------------------------------------------------------------------
# Filter framework helpers
# ---------------------------------------------------------------------------


def _build_filter_predicate(
    substring: str | None,
    regex: str | None,
    match_fields: list[str] | None,
) -> Callable[[CatalogMetadata], bool]:
    """Build a filter predicate for catalog entries.

    Returns a callable that accepts a :class:`CatalogMetadata` instance and
    returns ``True`` when the entry matches the filter.

    The default match-set (when ``match_fields`` is ``None``) checks all four
    fields: ``name``, ``display-name``, ``description``, ``keywords``.

    For ``keywords``, substring matching checks each element; regex matching
    uses ``re.search`` against each element.

    Args:
        substring: Case-sensitive substring to match against field values.
            Exactly one of ``substring`` or ``regex`` must be non-``None``.
        regex: Regular-expression pattern (``re.search``) to match against
            field values. Exactly one of ``substring`` or ``regex`` must be
            non-``None``.
        match_fields: Optional list of field names restricting the search.
            When ``None``, all four default fields are checked. Each element
            must be one of ``MATCH_FIELDS_LEGAL``.

    Returns:
        A predicate callable ``(CatalogMetadata) -> bool``.
    """
    effective_fields: tuple[str, ...] = tuple(match_fields) if match_fields is not None else MATCH_FIELDS_LEGAL

    def _get_field_values(entry: CatalogMetadata) -> list[str | list[str]]:
        values: list[str | list[str]] = []
        for field_name in effective_fields:
            if field_name == "name":
                values.append(entry.name)
            elif field_name == "display-name":
                values.append(entry.display_name)
            elif field_name == "description":
                values.append(entry.description)
            elif field_name == "keywords":
                values.append(entry.keywords)
        return values

    if substring is not None:

        def _substring_predicate(entry: CatalogMetadata) -> bool:
            for val in _get_field_values(entry):
                if isinstance(val, list):
                    if any(substring in kw for kw in val):
                        return True
                else:
                    if substring in val:
                        return True
            return False

        return _substring_predicate

    # regex path: caller guarantees exactly one of substring/regex is non-None.
    # When substring is None the caller must have passed a non-None regex string.
    if regex is None:
        raise ValueError("_build_filter_predicate requires exactly one of substring or regex to be non-None")
    compiled = re.compile(regex)

    def _regex_predicate(entry: CatalogMetadata) -> bool:
        for val in _get_field_values(entry):
            if isinstance(val, list):
                if any(compiled.search(kw) is not None for kw in val):
                    return True
            else:
                if compiled.search(val) is not None:
                    return True
        return False

    return _regex_predicate


def _apply_filter(
    entries: list[CatalogMetadata],
    predicate: Callable[[CatalogMetadata], bool],
) -> list[CatalogMetadata]:
    """Apply ``predicate`` to ``entries`` and return matching entries in order.

    Args:
        entries: List of :class:`CatalogMetadata` instances.
        predicate: Callable that returns ``True`` for entries to keep.

    Returns:
        Filtered list preserving the original order of matching entries.
    """
    return [e for e in entries if predicate(e)]


# ---------------------------------------------------------------------------
# Threshold guardrail
# ---------------------------------------------------------------------------


def _check_tree_guardrail(
    entry_count: int,
    max_depth: int | None,
    no_filter_required: bool,
    filter_present: bool = False,
) -> str | None:
    """Return an error message string when the threshold guardrail should fire.

    Returns ``None`` when the guardrail does not apply (either the catalog is
    small enough, a valid filter is present, or ``--no-filter-required`` was
    passed).

    ``--max-depth 0`` counts as a valid filter per spec Section 4.1, so the
    guardrail does NOT fire when ``max_depth == 0``.

    A positional ``<substring>`` or ``--regex`` pattern also counts as a
    filter (``filter_present=True``), satisfying the guardrail requirement.

    Args:
        entry_count: Number of catalog entries in the manifest repo.
        max_depth: Value of ``--max-depth``, or ``None`` for unlimited.
        no_filter_required: ``True`` when ``--no-filter-required`` was passed.
        filter_present: ``True`` when a substring or regex filter was supplied.

    Returns:
        An error message string when the guardrail fires, or ``None``.
    """
    if no_filter_required:
        return None
    if max_depth is not None and max_depth == 0:
        return None
    if filter_present:
        return None
    threshold = KANON_TREE_NO_FILTER_THRESHOLD
    if entry_count > threshold:
        return _TREE_GUARDRAIL_ERROR.format(
            threshold=threshold,
            count=entry_count,
            threshold_plus=threshold + 1,
        )
    return None


def run_list(args: argparse.Namespace) -> int:
    """Entry-point function for the ``kanon list`` subcommand.

    Resolves the catalog source, clones the manifest repo, builds the sorted
    entry index, and writes output to stdout. Returns 0 in all successful
    cases (including empty catalogs). Writes the canonical missing-catalog
    error to stderr and returns 1 when no catalog source is configured.

    Default mode: prints one entry name per line with ``flush=True`` per spec
    Section 4.1.

    Detail mode (``--detail``): prints a multi-line record per entry via
    :func:`_format_detail_record`. Human-readable; not pipeable into
    ``kanon add``.

    Tree mode (``--tree``): renders a three-layer ASCII dependency tree per
    entry via :func:`_render_tree`. Subject to the threshold guardrail unless
    a filter or ``--no-filter-required`` is supplied.

    All-versions mode (``--all-versions``): walks historical catalog versions
    via ``git ls-remote --tags`` and emits one ``<name>@<version>`` row per
    catalog entry per version. Mutually exclusive with ``--tree``.

    Filter mode: the positional ``<substring>`` or ``--regex <pattern>`` flag
    narrows the catalog entries before any renderer runs. ``--match-fields``
    restricts the filter to a subset of the four default fields.

    Args:
        args: Parsed argument namespace. Expected attributes:
            - ``catalog_source`` (``str | None``): from ``--catalog-source``.
            - ``detail`` (``bool``): from ``--detail`` (default ``False``).
            - ``tree`` (``bool``): from ``--tree`` (default ``False``).
            - ``max_depth`` (``int | None``): from ``--max-depth``.
            - ``no_filter_required`` (``bool``): from ``--no-filter-required``.
            - ``all_versions`` (``bool``): from ``--all-versions``.
            - ``limit`` (``int``): from ``--limit`` (default ``KANON_LIST_LIMIT``).
            - ``no_limit`` (``bool``): from ``--no-limit`` (default ``False``).
            - ``since_version`` (``str | None``): from ``--since-version``.
            - ``list_format`` (``str``): from ``--format`` (default ``"names"``);
              ``KANON_LIST_FORMAT`` env var is consulted when the flag is at its
              default. CLI flag takes precedence.
            - ``substring`` (``str | None``): positional substring filter.
            - ``regex`` (``str | None``): from ``--regex``.
            - ``match_fields`` (``list[str] | None``): from ``--match-fields`` CSV.

    Returns:
        Exit code: 0 on success (including empty catalog), 1 when no catalog
        source is configured or a flag conflict is detected.
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or os.environ.get(CATALOG_ENV_VAR)
    detail: bool = getattr(args, "detail", False)
    tree: bool = getattr(args, "tree", False)
    max_depth: int | None = getattr(args, "max_depth", None)
    no_filter_required: bool = getattr(args, "no_filter_required", False)
    all_versions: bool = getattr(args, "all_versions", False)
    limit: int = getattr(args, "limit", KANON_LIST_LIMIT)
    no_limit: bool = getattr(args, "no_limit", False)
    since_version: str | None = getattr(args, "since_version", None)
    substring: str | None = getattr(args, "substring", None)
    regex: str | None = getattr(args, "regex", None)
    match_fields: list[str] | None = getattr(args, "match_fields", None)

    # -- Filter mutual-exclusion checks (fail-fast, before catalog work) --

    # <substring> and --regex are mutually exclusive.
    if substring is not None and regex is not None:
        print(
            "ERROR: <substring> and --regex are mutually exclusive. "
            "Supply the positional substring OR --regex <pattern>, not both.",
            file=sys.stderr,
        )
        return 1

    # --match-fields requires <substring> or --regex.
    if match_fields is not None and substring is None and regex is None:
        print(
            "ERROR: --match-fields requires a filter. "
            "Supply a positional <substring> or --regex <pattern> together with --match-fields.",
            file=sys.stderr,
        )
        return 1

    # Unknown values in --match-fields are a hard error.
    if match_fields is not None:
        unknown = [f for f in match_fields if f not in MATCH_FIELDS_LEGAL]
        if unknown:
            legal_str = ", ".join(MATCH_FIELDS_LEGAL)
            unknown_str = ", ".join(unknown)
            print(
                f"ERROR: unknown --match-fields value(s): {unknown_str}. Legal values are: {legal_str}.",
                file=sys.stderr,
            )
            return 1

    # Validate the --regex pattern early (fail-fast, before catalog work).
    if regex is not None:
        try:
            re.compile(regex)
        except re.error as exc:
            print(
                f"ERROR: invalid --regex pattern {regex!r}: {exc}",
                file=sys.stderr,
            )
            return 1

    # -- Determine whether a user-supplied filter is active --
    filter_present: bool = substring is not None or regex is not None

    # Resolve the output format: CLI flag > env var > default "names".
    # The argparse default is None (not "names") so we can detect when the
    # flag was explicitly set vs. defaulted. Precedence:
    #   1. CLI flag (args.list_format is not None) -- use it.
    #   2. KANON_LIST_FORMAT env var (when CLI flag was absent) -- use it if valid.
    #   3. Default: "names".
    # Fail-fast: an unrecognized KANON_LIST_FORMAT value is an immediate error.
    _arg_format: str | None = getattr(args, "list_format", None)
    _env_format: str | None = os.environ.get(_KANON_LIST_FORMAT_ENV_VAR)
    if _arg_format is not None:
        list_format: str = _arg_format
    elif _env_format is None:
        list_format = "names"
    elif _env_format in ("names", "json"):
        list_format = _env_format
    else:
        print(
            f"ERROR: {_KANON_LIST_FORMAT_ENV_VAR}={_env_format!r} is not a recognised format. "
            f"Valid values are: 'names', 'json'.",
            file=sys.stderr,
        )
        return 1

    # Mutual exclusion: --format json and --tree cannot be combined.
    if list_format == "json" and tree:
        print(
            "ERROR: --format json and --tree are mutually exclusive. "
            "JSON output is not defined for tree mode. "
            "Use --format json without --tree, or use --tree without --format json.",
            file=sys.stderr,
        )
        return 1

    # Mutual exclusion: --tree and --all-versions cannot be combined.
    if tree and all_versions:
        print(
            "ERROR: --tree and --all-versions are mutually exclusive. "
            "Use --tree for dependency tree rendering, or --all-versions to "
            "list all available versions. These flags cannot be combined.",
            file=sys.stderr,
        )
        return 1

    # Mutual exclusion: --limit and --no-limit cannot be combined.
    # ``limit`` defaults to KANON_LIST_LIMIT in the parser. When --no-limit is
    # present alongside an explicitly different --limit value, the user has
    # supplied both flags, which is an error.
    if no_limit and limit != KANON_LIST_LIMIT:
        print(
            "ERROR: --limit and --no-limit are mutually exclusive. "
            "Pass --limit N to cap at N versions, or --no-limit to walk all versions.",
            file=sys.stderr,
        )
        return 1

    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="list"),
            file=sys.stderr,
        )
        return 1

    if all_versions:
        # Determine the effective cap: no_limit -> 0 (unlimited), else use limit.
        effective_limit = 0 if no_limit else limit
        rows = _walk_all_versions(catalog_source, effective_limit, since_version)
        if not rows:
            print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
            if list_format == "json":
                from kanon_cli.cli import _emit_json_payload

                _emit_json_payload(_build_all_versions_payload([]))
            return 0
        if list_format == "json":
            from kanon_cli.cli import _emit_json_payload

            _emit_json_payload(_build_all_versions_payload(rows))
        else:
            for row in rows:
                print(str(row), flush=True)
        return 0

    manifest_root = _resolve_manifest_repo(catalog_source)

    if tree:
        # Build the full metadata list first so the filter can be applied.
        all_entries = _build_sorted_metadata(manifest_root)
        entry_count = len(all_entries)

        guardrail_msg = _check_tree_guardrail(entry_count, max_depth, no_filter_required, filter_present=filter_present)
        if guardrail_msg is not None:
            print(guardrail_msg, file=sys.stderr, end="")
            return 1

        # Apply filter to narrow the tree entries.
        if filter_present:
            predicate = _build_filter_predicate(substring=substring, regex=regex, match_fields=match_fields)
            filtered_entries = _apply_filter(all_entries, predicate)
        else:
            filtered_entries = all_entries

        if not filtered_entries:
            if filter_present:
                print(LIST_FILTER_ZERO_MATCH_NOTE, file=sys.stderr)
            else:
                print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
            return 0

        for entry in filtered_entries:
            tree_lines = _render_tree(manifest_root, entry.name, max_depth)
            for line in tree_lines:
                print(line, flush=True)

        return 0

    # Non-tree modes: build full metadata, apply filter, render.
    all_entries = _build_sorted_metadata(manifest_root)

    if filter_present:
        predicate = _build_filter_predicate(substring=substring, regex=regex, match_fields=match_fields)
        entries = _apply_filter(all_entries, predicate)

        if not entries:
            print(LIST_FILTER_ZERO_MATCH_NOTE, file=sys.stderr)
            if list_format == "json":
                from kanon_cli.cli import _emit_json_payload

                _emit_json_payload(_build_catalog_payload([]))
            return 0
    else:
        entries = all_entries

    if not entries:
        print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
        if list_format == "json":
            from kanon_cli.cli import _emit_json_payload

            _emit_json_payload(_build_catalog_payload([]))
        return 0

    if list_format == "json":
        from kanon_cli.cli import _emit_json_payload

        _emit_json_payload(_build_catalog_payload(entries))
    elif detail:
        for metadata in entries:
            print(_format_detail_record(metadata), flush=True)
    else:
        for metadata in entries:
            print(metadata.name, flush=True)

    return 0


def register(subparsers) -> None:
    """Register the ``list`` subcommand on the top-level argparse parser.

    Adds the ``list`` subparser with:
    - ``<substring>`` optional positional filter (substring, case-sensitive).
    - ``--catalog-source`` from the shared factory.
    - ``--format {names,json}`` to select the output format (default: ``names``).
    - ``--detail`` for human-readable per-entry records.
    - ``--tree`` for the three-layer ASCII dependency tree renderer.
    - ``--max-depth N`` to cap the rendered tree depth (0 = root only).
    - ``--no-filter-required`` to bypass the threshold guardrail.
    - ``--all-versions`` to walk all historical tagged versions.
    - ``--limit N`` to cap the number of versions walked (default: ``KANON_LIST_LIMIT``).
    - ``--no-limit`` to walk all PEP 440-valid tags without a cap.
    - ``--since-version <spec>`` to filter walked versions by a PEP 440 constraint.
    - ``--regex <pattern>`` for regex-based entry filtering.
    - ``--match-fields <csv>`` to narrow the filter to specific fields.

    Threshold guardrail: when the catalog has more than
    ``KANON_TREE_NO_FILTER_THRESHOLD`` entries (default 20, overridable via
    the ``KANON_TREE_NO_FILTER_THRESHOLD`` env var) and the operator has not
    supplied a filter (positional substring, ``--regex``, or ``--max-depth 0``)
    and has not passed ``--no-filter-required``, ``--tree`` exits non-zero with
    an error naming the threshold, the actual count, and the four resolution
    paths: positional substring, ``--regex``, ``--max-depth 0``,
    ``--no-filter-required``.

    Format flag (``--format``): selects between ``names`` (default, one entry
    name per line) and ``json`` (structured JSON array). The ``KANON_LIST_FORMAT``
    environment variable sets the format when the CLI flag is absent; the CLI
    flag takes precedence when both are set. ``--format json`` is incompatible
    with ``--tree`` (hard error at validation time).

    Args:
        subparsers: The subparsers action from the parent parser.
    """
    parser = subparsers.add_parser(
        "list",
        add_help=True,
        help="List catalog entry names from a manifest repo.",
        description=(
            "Print one catalog entry name per line to stdout, sorted\n"
            "lexicographically. Reads *-marketplace.xml files under\n"
            "repo-specs/ in the manifest repo identified by the catalog source.\n\n"
            "Requires a catalog source via --catalog-source or the\n"
            "KANON_CATALOG_SOURCE environment variable. The CLI flag takes\n"
            "precedence when both are set.\n\n"
            "Filter mode: supply an optional positional <substring> or --regex\n"
            "<pattern> to narrow the catalog entries returned. The filter checks\n"
            "the entry name, display-name, description, and keywords by default.\n"
            "Use --match-fields <csv> to restrict to a subset of those fields.\n"
            "  <substring> and --regex are mutually exclusive.\n"
            "  --match-fields requires <substring> or --regex.\n"
            "Zero matches: exits 0 with empty stdout and '0 entries match filter'\n"
            "on stderr.\n\n"
            "Format mode (--format): selects the output format. Choices:\n"
            "  names (default) -- one entry name per line, pipeable into kanon add.\n"
            "  json -- structured JSON array of entry objects. Default mode and\n"
            "    --detail mode emit {name, display-name, type, description, version};\n"
            "    --all-versions mode emits {name, version, ref, sha}.\n"
            "The KANON_LIST_FORMAT environment variable sets the format when the\n"
            "CLI flag is absent; the CLI flag takes precedence when both are set.\n"
            "--format json is incompatible with --tree (hard error).\n\n"
            "Tree mode (--tree): renders a three-layer ASCII dependency tree\n"
            "per entry. Subject to a threshold guardrail: when the catalog has\n"
            f"more than KANON_TREE_NO_FILTER_THRESHOLD (default {KANON_TREE_NO_FILTER_THRESHOLD})\n"
            "entries, a filter is required unless --no-filter-required is passed.\n"
            "Resolution paths: positional <name> substring, --regex <pattern>,\n"
            "--max-depth 0, or --no-filter-required.\n\n"
            "All-versions mode (--all-versions): walks historical catalog versions\n"
            "via git ls-remote --tags. Emits one <name>@<version> row per catalog\n"
            "entry per version, newest version first. Default version cap:\n"
            f"KANON_LIST_LIMIT (default {KANON_LIST_LIMIT}, overridable via env var).\n"
            "Use --limit N to cap at N versions, --no-limit to walk all versions.\n"
            "Use --since-version <spec> to filter by a PEP 440 constraint\n"
            "(e.g. '>=1.0,<2.0'). Mutually exclusive with --tree."
        ),
        epilog=(
            "Examples:\n"
            "  kanon list --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list foo --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --regex '^foo' --catalog-source ...\n"
            "  kanon list foo --match-fields keywords --catalog-source ...\n"
            "  kanon list --format json --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --format json --all-versions --catalog-source ...\n"
            "  kanon list --detail --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --tree --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --tree --max-depth 0 --catalog-source ...\n"
            "  kanon list --tree --no-filter-required --catalog-source ...\n"
            "  kanon list --all-versions --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --all-versions --limit 3 --catalog-source ...\n"
            "  kanon list --all-versions --no-limit --catalog-source ...\n"
            "  kanon list --all-versions --since-version '>=1.0,<2.0' --catalog-source ...\n"
            "  KANON_CATALOG_SOURCE=https://example.com/org/repo.git@v1.0.0 kanon list\n"
            "  KANON_LIST_FORMAT=json kanon list --catalog-source ..."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    add_catalog_source_arg(parser)

    parser.add_argument(
        "substring",
        nargs="?",
        default=None,
        metavar="<substring>",
        help=(
            "Optional case-sensitive substring filter. When supplied, only entries "
            "whose name, display-name, description, or keywords contain the substring "
            "are returned. Mutually exclusive with --regex. "
            "Use --match-fields to restrict the fields checked."
        ),
    )

    parser.add_argument(
        "--format",
        dest="list_format",
        choices=["names", "json"],
        default=None,
        metavar="{names,json}",
        help=(
            "Output format. 'names' (default): one entry name per line, pipeable "
            "into kanon add. 'json': structured JSON array. Default mode and "
            "--detail mode emit {name, display-name, type, description, version} "
            "objects; --all-versions mode emits {name, version, ref, sha} objects. "
            "The KANON_LIST_FORMAT environment variable sets the format when this "
            "flag is absent; the CLI flag takes precedence when both are set. "
            "--format json is incompatible with --tree (hard error at validation time)."
        ),
    )

    parser.add_argument(
        "--detail",
        action="store_true",
        default=False,
        help=(
            "Print a human-readable multi-line record per entry (display-name, "
            "description, version, type). Human-readable only -- not pipeable "
            "into kanon add. For machine consumers, combine with --format json."
        ),
    )

    parser.add_argument(
        "--tree",
        action="store_true",
        default=False,
        help=(
            "Render a three-layer ASCII dependency tree per entry: the catalog "
            "entry (root), the XML manifests reachable via transitive <include> "
            "directives, and the <project> repos referenced by those manifests. "
            "Each node shows the version resolved at command-execution time. "
            "Mutually exclusive with --all-versions. Subject to the threshold "
            f"guardrail (KANON_TREE_NO_FILTER_THRESHOLD, default {KANON_TREE_NO_FILTER_THRESHOLD}): "
            "when the catalog exceeds the threshold, supply a filter -- positional "
            "substring, --regex, --max-depth 0 -- or pass --no-filter-required."
        ),
    )

    parser.add_argument(
        "--max-depth",
        dest="max_depth",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Cap the tree depth rendered by --tree. "
            "0 = root entry node only (no XML or project layers). "
            "1 = root + XML layer only. Default: unlimited. "
            "--max-depth 0 also satisfies the threshold guardrail as a valid filter."
        ),
    )

    parser.add_argument(
        "--no-filter-required",
        dest="no_filter_required",
        action="store_true",
        default=False,
        help=(
            "Bypass the threshold guardrail for --tree. "
            f"Normally, catalogs with more than KANON_TREE_NO_FILTER_THRESHOLD "
            f"(default {KANON_TREE_NO_FILTER_THRESHOLD}) entries require a filter "
            "(positional substring, --regex, or --max-depth 0) to avoid accidental "
            "full-catalog tree renders. Pass this flag to bypass the check."
        ),
    )

    parser.add_argument(
        "--all-versions",
        dest="all_versions",
        action="store_true",
        default=False,
        help=(
            "Walk all historical tagged versions of the manifest repo and emit "
            "one <name>@<version> row per catalog entry per version. Versions are "
            "ordered newest-first by PEP 440 natural sort; entries within each "
            "version are sorted lexicographically. Mutually exclusive with --tree. "
            "Default cap: KANON_LIST_LIMIT (default 50, overridable via env var). "
            "Use --limit N or --no-limit to control the number of versions walked."
        ),
    )

    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=KANON_LIST_LIMIT,
        metavar="N",
        help=(
            "Cap the number of versions walked by --all-versions. "
            f"Default: KANON_LIST_LIMIT (default {KANON_LIST_LIMIT}, "
            "overridable via the KANON_LIST_LIMIT environment variable). "
            "Mutually exclusive with --no-limit."
        ),
    )

    parser.add_argument(
        "--no-limit",
        dest="no_limit",
        action="store_true",
        default=False,
        help=(
            "Walk all PEP 440-valid tags when using --all-versions, with no cap. "
            "Equivalent to --limit <very-large-number>. "
            "Mutually exclusive with --limit."
        ),
    )

    parser.add_argument(
        "--since-version",
        dest="since_version",
        default=None,
        metavar="<spec>",
        help=(
            "Filter the versions walked by --all-versions to those matching "
            "a PEP 440 specifier constraint (e.g. '>=1.0,<2.0'). "
            "The constraint is evaluated against the PEP 440 version parsed "
            "from each tag name. Tags that do not parse as PEP 440 are skipped. "
            "Example: --since-version '>=1.0,<2.0'"
        ),
    )

    parser.add_argument(
        "--regex",
        dest="regex",
        default=None,
        metavar="<pattern>",
        help=(
            "Regular-expression filter (Python re.search). When supplied, only "
            "entries whose name, display-name, description, or keywords match the "
            "pattern are returned. The keywords field matches when any element "
            "satisfies re.search. Mutually exclusive with the positional <substring>. "
            "Use --match-fields to restrict the fields checked. "
            "Example: --regex '^foo'"
        ),
    )

    parser.add_argument(
        "--match-fields",
        dest="match_fields",
        default=None,
        metavar="<csv>",
        type=lambda v: [f.strip() for f in v.split(",") if f.strip()],
        help=(
            "Comma-separated list of fields to check when filtering. "
            "Legal values: name, display-name, description, keywords. "
            "Default (when --match-fields is not supplied): all four fields. "
            "Requires the positional <substring> or --regex to be present; "
            "supplying --match-fields without a filter is a hard error. "
            "Example: --match-fields keywords"
        ),
    )

    parser.set_defaults(func=run_list)
