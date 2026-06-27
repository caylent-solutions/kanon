"""kanon search subcommand: discover catalog entry names from a manifest repo.

Reads ``*-marketplace.xml`` files under ``repo-specs/`` in the resolved
manifest repo and prints one entry name per line to stdout, sorted
lexicographically, with a per-source group header on stderr.

``kanon search`` is the hard rename of the former ``list`` command (no
deprecation alias): it inherits the full former list query surface unchanged
(substring positional, ``--regex``, ``--match-fields``, ``--format json``,
``--detail``, ``--tree``, ``--since-version``, ``--limit``) and adds:
(a) grouping of results by catalog source; (b) ``-A/--all`` to show all tagged
versions of each matching manifest vs. the latest-only default.

Spec reference: ``specs/kanon-refinements.md`` Section 4.1 (``kanon search``
query surface + grouping by source + ``-A/--all``) and Section 4 header
(canonical missing-catalog error and env-var precedence).
Section 4.1 flag-table row ``--detail`` for the per-entry detail formatter.
Section 4.1 flag-table rows ``--tree``, ``--max-depth N``,
``--no-filter-required`` and the threshold guardrail.
Section 4.1 flag-table rows ``-A/--all``, ``--limit N``,
``--no-limit``, ``--since-version <spec>`` for the historical-versions walker.
Section 4.1 flag-table row ``--format {names,json}`` for JSON output.
Section 4.1 flag-table rows ``<substring>`` (positional), ``--regex <pattern>``,
``--match-fields <csv>`` for the filter framework.

The per-source group header is written to stderr (never stdout) so the stdout
stream stays pipeable into ``kanon add`` and a JSON document on stdout stays
machine-parseable.

Environment variables:
- ``KANON_CATALOG_SOURCES``: catalog discovery set (CLI flag wins); the single
  configured entry is used when ``--catalog-source`` is absent.
- ``KANON_TREE_NO_FILTER_THRESHOLD``: overrides the default threshold (20)
  above which ``kanon search --tree`` requires a filter.
- ``KANON_LIST_LIMIT``: overrides the default version-walk cap (50).
- ``KANON_LIST_FORMAT``: overrides the output format (CLI flag wins).
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

import defusedxml.ElementTree as ET
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from kanon_cli.completions.cache import (
    Freshness,
    read_search_versions_with_freshness,
    write_search_versions,
)
from kanon_cli.constants import (
    KANON_COMPLETION_CACHE_TTL,
    KANON_LIST_LIMIT,
    KANON_SEARCH_MAX_WORKERS,
    KANON_TREE_NO_FILTER_THRESHOLD,
    LIST_EMPTY_CATALOG_NOTE,
    MISSING_CATALOG_ERROR_TEMPLATE,
    SEARCH_NO_MATCHES_NOTE,
    SEARCH_UNREACHABLE_SOURCE_WARN_TEMPLATE,
)
from kanon_cli.core.catalog import (
    DefaultBranchResolutionError,
    _parse_catalog_source,
    normalize_catalog_source_ref,
    resolve_env_catalog_sources,
)
from kanon_cli.core.cli_args import add_catalog_default_branch_arg, add_catalog_source_arg
from kanon_cli.core.metadata import (
    CatalogMetadata,
    CatalogMetadataParseError,
    _parse_catalog_metadata,
    find_catalog_entry_files,
)
from kanon_cli.version import _list_branch_head, is_version_constraint, resolve_version, select_entry_namespace


_LATEST_TIP_MARKER = "latest"


_RELEASE_BRANCH = "main"


_DETAIL_MISSING_PLACEHOLDER = "<missing>"
_DETAIL_LABEL_WIDTH = 12


_KANON_LIST_FORMAT_ENV_VAR = "KANON_LIST_FORMAT"


_ALL_VERSIONS_PARSE_WARNING_FORMAT = (
    "WARNING: malformed catalog-metadata for entry {entry} at revision {revision}: {reason}"
)


_ALL_VERSIONS_LEGACY_SKIPPED_NOTE_FORMAT = (
    "NOTE: {count} marketplace XML(s) at revision {revision} use the unsupported old "
    "flat-attribute scheme (no nested <catalog-metadata><name>); skipped"
)


_ALL_VERSIONS_NO_NEW_SCHEME_NOTE = (
    "NOTE: no new-scheme version tags found; only releases that carry the nested "
    "<catalog-metadata><name> scheme are listed (old flat-attribute tags are skipped)"
)


LIST_FILTER_ZERO_MATCH_NOTE = "0 entries match filter"


MATCH_FIELDS_LEGAL: tuple[str, ...] = ("name", "display-name", "description", "keywords")


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


_TREE_CONNECTOR_INTERMEDIATE = "+--"
_TREE_CONNECTOR_LAST = "\\--"
_TREE_COLUMN_CONTINUATION = "|   "
_TREE_COLUMN_BLANK = "    "


_TREE_GUARDRAIL_ERROR = (
    "ERROR: kanon search --tree requires a filter when the catalog has more than "
    "{threshold} entries.\n"
    "The catalog at the given source has {count} entries, which exceeds the threshold.\n"
    "\n"
    "Supply one of the following to proceed:\n"
    "  <name>                  positional substring filter (e.g. kanon search --tree mylib)\n"
    "  --regex <pattern>       regular-expression filter\n"
    "  --max-depth 0           show only root entry nodes (no XML or project layers)\n"
    "  --no-filter-required    bypass this guardrail entirely\n"
    "\n"
    "Or raise the threshold:\n"
    "  KANON_TREE_NO_FILTER_THRESHOLD={threshold_plus} kanon search --tree ...\n"
)


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


@dataclass(frozen=True)
class SourceEnumeration:
    """Result of enumerating the versions of one matching entry within one source.

    Attributes:
        source: The resolved catalog source string (``<url>@<ref>``) the entry
            was enumerated from. Used for the per-source group header.
        entry_name: The catalog entry (manifest) name.
        versions: PEP 440 release-tag version strings for this entry, sorted
            newest-first. Empty when the entry has no ``refs/tags/<name>/*`` tags.
        has_latest: True when a branch-tip "latest" was resolved for this entry
            (``_list_branch_head`` succeeded), False otherwise.
    """

    source: str
    entry_name: str
    versions: tuple[str, ...]
    has_latest: bool


class SourceUnreachableError(RuntimeError):
    """Raised when a catalog source cannot be reached during enumeration.

    Carries the resolved source string so the caller can emit the spec
    skip+warn diagnostic (Section 4.1 / FLAG-B) without hard-failing the whole
    search.
    """

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"catalog source {source} is unreachable: {reason}")


def _resolve_search_ttl() -> int:
    """Return the env-driven TTL (seconds) for the search enumeration cache.

    Reuses the completion-cache TTL knob (spec Section 4.1: reuse the
    ``completions/cache.py`` TTL pattern). The value is read from
    ``KANON_COMPLETION_CACHE_TTL`` at call time so the env override is honoured;
    no TTL value is hard-coded in the enumeration code path.

    Returns:
        The cache TTL in seconds.

    Raises:
        ValueError: When the env override is set to a non-integer value
            (fail fast; never silently fall back to the default).
    """
    raw = os.environ.get("KANON_COMPLETION_CACHE_TTL")
    if raw is None:
        return KANON_COMPLETION_CACHE_TTL
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"KANON_COMPLETION_CACHE_TTL={raw!r} is not a valid integer (expected seconds)") from exc


def _list_namespaced_version_tags(url: str, entry_name: str) -> list[str]:
    """Return a catalog entry's PEP 440 version strings, newest-first.

    Lists the manifest repo's tags once via ``git ls-remote --tags`` and scopes
    them with :func:`kanon_cli.version.select_entry_namespace`, the rule shared
    with ``kanon add`` (spec Section 4.1 / Section 6): when the entry has
    ``refs/tags/<entry_name>/<pep440>`` tags those are used; otherwise the bare
    ``refs/tags/<pep440>`` tags are used (a single-purpose, poly repo). Peeled
    ``^{}`` deref lines, other entries' namespaced tags, and non-PEP-440 last
    components are dropped. Listing once and selecting the namespace keeps
    ``kanon search`` consistent with what ``kanon add`` would resolve.

    Args:
        url: Git repository URL of the catalog manifest repo.
        entry_name: The catalog entry name whose versions are enumerated.

    Returns:
        Newest-first list of PEP 440 version strings. Empty when the entry has no
        namespaced and no bare version tags.

    Raises:
        SourceUnreachableError: When the underlying ``git ls-remote`` exits
            non-zero or the git binary is missing (the caller decides whether to
            skip+warn or propagate).
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceUnreachableError(url, "git binary not found on PATH") from exc

    if result.returncode != 0:
        raise SourceUnreachableError(url, result.stderr.strip() or f"git ls-remote exited {result.returncode}")

    refs: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        _sha, ref = line.split("\t", 1)
        ref = ref.strip()
        if ref.endswith("^{}") or not ref.startswith("refs/tags/"):
            continue
        refs.append(ref)

    namespace = select_entry_namespace(refs, entry_name)
    prefix = f"refs/tags/{namespace}/" if namespace is not None else "refs/tags/"
    versions: list[Version] = []
    for ref in refs:
        if not ref.startswith(prefix):
            continue
        suffix = ref[len(prefix) :]
        if namespace is None and "/" in suffix:
            continue
        try:
            versions.append(Version(suffix))
        except InvalidVersion:
            continue
    versions.sort(reverse=True)
    return [str(v) for v in versions]


def _enumerate_entry_versions(url: str, ref: str, entry_name: str) -> SourceEnumeration:
    """Enumerate the versions of one matching entry within one source (uncached).

    Versions = the catalog release tags under ``refs/tags/<entry_name>/`` plus the
    branch-tip "latest" via ``_list_branch_head`` (spec Section 4.1). Release
    enumeration applies to ``main`` only: when ``ref`` is ``main`` (or ``latest``,
    which resolves to the release branch tip), every ``refs/tags/<entry_name>/*``
    tag is listed regardless of ``@ref``; for any other branch there is no release
    enumeration -- only that branch's tip is shown (Section 6 / FR-25).

    Args:
        url: Catalog manifest repo URL.
        ref: The catalog source ref (branch / tag / ``latest``).
        entry_name: The catalog entry name to enumerate.

    Returns:
        A :class:`SourceEnumeration` for this entry.

    Raises:
        SourceUnreachableError: Propagated from the underlying git calls when the
            source is unreachable.
    """
    branch = _RELEASE_BRANCH if ref == "latest" else ref
    is_release_branch = branch == _RELEASE_BRANCH

    versions: list[str] = []
    if is_release_branch:
        versions = _list_namespaced_version_tags(url, entry_name)

    try:
        _list_branch_head(url, branch)
        has_latest = True
    except ValueError:
        has_latest = False
    except RuntimeError as exc:
        raise SourceUnreachableError(url, str(exc)) from exc

    return SourceEnumeration(
        source=f"{url}@{ref}",
        entry_name=entry_name,
        versions=tuple(versions),
        has_latest=has_latest,
    )


_CACHE_LINE_DELIMITER = "@"


def _encode_entry_versions(enumeration: SourceEnumeration) -> list[str]:
    """Encode one entry's enumeration into cache lines for ``versions.txt``.

    Each line is ``<entry_name>@<version-or-latest>`` so a single per-source cache
    entry can hold the enumeration of every matching entry, round-tripping through
    the existing newline-delimited cache primitives (DRY). The ``@`` delimiter
    survives the completion-cache sanitizer (which drops control characters such
    as a tab).

    Args:
        enumeration: The entry enumeration to encode.

    Returns:
        Encoded cache lines (release tags newest-first, then the latest tip
        marker when a branch tip was resolved).
    """
    lines = [f"{enumeration.entry_name}{_CACHE_LINE_DELIMITER}{version}" for version in enumeration.versions]
    if enumeration.has_latest:
        lines.append(f"{enumeration.entry_name}{_CACHE_LINE_DELIMITER}{_LATEST_TIP_MARKER}")
    return lines


def _decode_source_versions(source: str, lines: list[str]) -> dict[str, SourceEnumeration]:
    """Decode cached ``versions.txt`` lines back into per-entry enumerations.

    Inverse of :func:`_encode_entry_versions`. Lines that do not carry the
    ``<entry>@<token>`` shape are ignored (defensive against a manually edited or
    partially written cache file).

    Args:
        source: The resolved source string (``<url>@<ref>``) for the decoded
            enumerations.
        lines: Cached lines read from ``versions.txt``.

    Returns:
        Mapping of entry name -> :class:`SourceEnumeration`.
    """
    versions_by_entry: dict[str, list[str]] = {}
    latest_by_entry: dict[str, bool] = {}
    for line in lines:
        if _CACHE_LINE_DELIMITER not in line:
            continue
        entry_name, token = line.split(_CACHE_LINE_DELIMITER, 1)
        entry_name = entry_name.strip()
        token = token.strip()
        if not entry_name or not token:
            continue
        latest_by_entry.setdefault(entry_name, False)
        versions_by_entry.setdefault(entry_name, [])
        if token == _LATEST_TIP_MARKER:
            latest_by_entry[entry_name] = True
        else:
            versions_by_entry[entry_name].append(token)
    return {
        entry_name: SourceEnumeration(
            source=source,
            entry_name=entry_name,
            versions=tuple(versions),
            has_latest=latest_by_entry[entry_name],
        )
        for entry_name, versions in versions_by_entry.items()
    }


def _enumerate_source(
    source: str,
    entry_names: list[str],
    ttl_seconds: int,
    now: int,
) -> dict[str, SourceEnumeration]:
    """Enumerate (TTL-cached) the versions of every matching entry in one source.

    Reads the per-source@ref enumeration through the ``completions/cache.py`` TTL
    cache (spec Section 4.1 / FR-25): a FRESH cached entry is reused directly; a
    MISSING (or STALE) entry triggers a fresh enumeration that is written back to
    the cache stamped with ``now``. The cache is keyed by source@ref, so repeated
    ``search`` invocations within the TTL reuse the cached tag enumeration.

    Args:
        source: The resolved source string (``<url>@<ref>``).
        entry_names: The matching catalog entry names to enumerate.
        ttl_seconds: The cache TTL in seconds (env-driven, never hard-coded).
        now: Current epoch seconds (injected for testability and cache stamping).

    Returns:
        Mapping of entry name -> :class:`SourceEnumeration`.

    Raises:
        SourceUnreachableError: When the source is unreachable during a fresh
            enumeration (the caller decides skip+warn vs propagate).
    """
    url, ref = _parse_catalog_source(source)

    cached, freshness = read_search_versions_with_freshness(url, ref, ttl_seconds=ttl_seconds, now=now)
    if freshness is Freshness.FRESH:
        decoded = _decode_source_versions(source, cached)

        return {name: decoded[name] for name in entry_names if name in decoded}

    enumerations: dict[str, SourceEnumeration] = {}
    cache_lines: list[str] = []
    for entry_name in entry_names:
        enumeration = _enumerate_entry_versions(url, ref, entry_name)
        enumerations[entry_name] = enumeration
        cache_lines.extend(_encode_entry_versions(enumeration))

    write_search_versions(url, ref, cache_lines, now)
    return enumerations


def _enumerate_sources_concurrently(
    source_entry_names: dict[str, list[str]],
    ttl_seconds: int,
    now: int,
    max_workers: int,
) -> tuple[dict[str, dict[str, SourceEnumeration]], list[tuple[str, str]]]:
    """Enumerate versions across the configured sources concurrently.

    Runs one :func:`_enumerate_source` task per source in a thread pool (the work
    is I/O-bound ``git ls-remote`` calls). An unreachable source is skipped with a
    warning recorded for the caller (spec Section 4.1 / FLAG-B skip+warn) and does
    NOT hard-fail the whole search. No ``time.sleep`` is used; readiness is the
    natural completion of each future (``as_completed``).

    Args:
        source_entry_names: Mapping of resolved source string -> matching entry
            names to enumerate in that source.
        ttl_seconds: Cache TTL in seconds.
        now: Current epoch seconds.
        max_workers: Upper bound on worker threads (clamped to the source count).

    Returns:
        A ``(results, warnings)`` tuple where ``results`` maps source ->
        {entry_name -> SourceEnumeration} and ``warnings`` is a list of
        ``(source, reason)`` pairs for the skipped unreachable sources.
    """
    results: dict[str, dict[str, SourceEnumeration]] = {}
    warnings: list[tuple[str, str]] = []

    sources = list(source_entry_names)
    if not sources:
        return results, warnings

    workers = min(max_workers, len(sources))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_source = {
            executor.submit(
                _enumerate_source,
                source,
                source_entry_names[source],
                ttl_seconds,
                now,
            ): source
            for source in sources
        }
        for future in concurrent.futures.as_completed(future_to_source):
            source = future_to_source[future]
            try:
                results[source] = future.result()
            except SourceUnreachableError as exc:
                warnings.append((source, exc.reason))

    return results, warnings


def _format_version_summary(enumeration: SourceEnumeration) -> str:
    """Render the version summary for one entry in default (latest-only) mode.

    Default mode shows only the latest: the branch tip is labelled
    ``<name> (latest)`` and, when no branch tip resolved, the newest release tag
    is shown. An entry with neither a tip nor any release tag renders the bare
    name (spec Section 4.1: latest-only default).

    Args:
        enumeration: The entry enumeration to render.

    Returns:
        The single-line summary for stdout.
    """
    if enumeration.has_latest:
        return f"{enumeration.entry_name} (latest)"
    if enumeration.versions:
        return f"{enumeration.entry_name}@{enumeration.versions[0]}"
    return enumeration.entry_name


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


def _is_xml_well_formed(xml_path: pathlib.Path) -> bool:
    """Return True when xml_path contains structurally valid (well-formed) XML.

    Uses :func:`defusedxml.ElementTree.parse` to attempt a parse. Returns
    False when the parser raises :class:`xml.etree.ElementTree.ParseError`,
    which indicates genuinely non-well-formed XML.

    Args:
        xml_path: Path to the file to check.

    Returns:
        True when the file parses without error; False otherwise.
    """
    try:
        ET.parse(xml_path)
        return True
    except ET.ParseError:
        return False


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

    New-scheme-only: only canonical ``<catalog-metadata><name>`` values are
    emitted. Version tags using the unsupported old flat-attribute scheme (no
    nested ``<name>``) are SKIPPED, with a single diagnostic line per revision
    noting how many were skipped. Genuinely non-well-formed XML continues to be
    skipped with a stderr warning. When no walked tag carries a new-scheme entry
    (e.g. the entire release history predates the nested scheme), the function
    returns an EMPTY list and emits a clear "no new-scheme version tags" note to
    stderr -- this is exit 0, not an error.

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
        SystemExit: On git ls-remote failure or git clone failure for any
            individual revision. An all-old-scheme history is NOT an error -- the
            function returns an empty list with a note instead of exiting.
        ValueError: When ``since_version`` is not a valid PEP 440 specifier.
    """
    url, _ref = _parse_catalog_source(catalog_source)

    pairs = _list_tags_from_url(url)
    if not pairs:
        return []

    sorted_triples = _sort_version_pairs_newest_first(pairs)
    if not sorted_triples:
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

    if limit > 0:
        sorted_triples = sorted_triples[:limit]

    if not sorted_triples:
        return []

    rows: list[VersionRow] = []
    successful_count = 0
    for ref, ver, sha in sorted_triples:
        version_str = ref.rsplit("/", 1)[-1]
        clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-search-av-"))
        repo_dir = clone_dir / "repo"

        clone_result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", version_str, url, str(repo_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if clone_result.returncode != 0:
            print(
                f"ERROR: Failed to clone manifest repo from {url}@{version_str}: {clone_result.stderr}",
                file=sys.stderr,
            )
            sys.exit(1)

        xml_paths = find_catalog_entry_files(repo_dir)
        version_names: list[str] = []
        legacy_skipped_count = 0
        for xml_path in xml_paths:
            try:
                metadata = _parse_catalog_metadata(xml_path)
                version_names.append(metadata.name)
            except CatalogMetadataParseError as exc:
                if _is_xml_well_formed(xml_path):
                    legacy_skipped_count += 1
                else:
                    print(
                        _ALL_VERSIONS_PARSE_WARNING_FORMAT.format(
                            entry=xml_path.stem.removesuffix("-marketplace"),
                            revision=version_str,
                            reason=str(exc),
                        ),
                        file=sys.stderr,
                    )

        if legacy_skipped_count > 0:
            print(
                _ALL_VERSIONS_LEGACY_SKIPPED_NOTE_FORMAT.format(
                    count=legacy_skipped_count,
                    revision=version_str,
                ),
                file=sys.stderr,
            )

        if not version_names:
            continue

        successful_count += 1
        for name in sorted(version_names):
            rows.append(VersionRow(name=name, version=str(ver), ref=ref, sha=sha))

    if successful_count == 0 and sorted_triples:
        print(_ALL_VERSIONS_NO_NEW_SCHEME_NOTE, file=sys.stderr)
        return rows

    return rows


def _resolve_manifest_repo(catalog_source: str) -> pathlib.Path:
    """Resolve the manifest repo root directory from a catalog source string.

    Clones the manifest repo at the given ``<git_url>@<ref>`` source into a
    temporary directory and returns the root of that clone (NOT the
    ``catalog/`` subdirectory -- ``kanon search`` needs the full repo root to
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

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-search-"))
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
    xml_paths = find_catalog_entry_files(manifest_root)
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
    xml_paths = find_catalog_entry_files(manifest_root)
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


def _build_catalog_payload(entries: list[CatalogMetadata]) -> list[dict]:
    """Build the JSON-serialisable payload for a list of :class:`CatalogMetadata`.

    Each element is an object with the five fields specified in Section 4.1:
    ``name``, ``display-name``, ``type``, ``description``, ``version``.
    The ``type`` field is ``null`` in JSON when the metadata slot is ``None``.

    Used by :func:`_format_json_catalog` (for tests that inspect the JSON string)
    and by the :func:`run_search` handler that calls :func:`_emit_json_payload`
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
    xml_files = find_catalog_entry_files(manifest_root)
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
            f"No catalog entry manifest found for entry '{entry_name}' under {manifest_root / 'repo-specs'}"
        )

    sha = _sha12_from_path(entry_xml)
    lines: list[str] = [f"entry {entry_name}@{entry_version} ({sha})"]

    if max_depth is not None and max_depth == 0:
        return lines

    show_projects = max_depth is None or max_depth >= 2

    root_includes, root_projects = _parse_xml_includes_and_projects(entry_xml)

    include_paths: list[pathlib.Path] = []
    include_placeholders: list[str] = []
    for inc_name in root_includes:
        resolved = _resolve_include_path(inc_name, entry_xml, manifest_root)
        if resolved is not None:
            include_paths.append(resolved)
        else:
            include_placeholders.append(inc_name)

    has_includes = bool(include_paths) or bool(include_placeholders)

    if has_includes:
        total_d1 = len(include_paths) + len(include_placeholders)

        for idx, inc_path in enumerate(include_paths):
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

        if show_projects and root_projects:
            if include_paths:
                last_inc_idx = len(include_paths) - 1
                last_inc_is_last_d1 = last_inc_idx == total_d1 - 1
                last_inc_indent = _TREE_COLUMN_BLANK if last_inc_is_last_d1 else _TREE_COLUMN_CONTINUATION
            else:
                last_inc_indent = ""
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last_rp = j == len(root_projects) - 1
                proj_prefix = last_inc_indent + (_TREE_CONNECTOR_LAST if is_last_rp else _TREE_CONNECTOR_INTERMEDIATE)
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    else:
        if show_projects and root_projects:
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last = j == len(root_projects) - 1
                proj_prefix = _TREE_CONNECTOR_LAST if is_last else _TREE_CONNECTOR_INTERMEDIATE
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    return lines


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


_SOURCE_GROUP_HEADER_FORMAT = "Source: {source}"


def _format_source_group_header(source: str) -> str:
    """Return the per-source group header line for ``kanon search`` output.

    Args:
        source: The resolved catalog source string (``<git_url>@<ref>``).

    Returns:
        The header line (no trailing newline), e.g. ``Source: https://...@main``.

    Raises:
        ValueError: When ``source`` is empty; a group header without a source
            is meaningless and must fail fast rather than emit a blank label.
    """
    if not source:
        raise ValueError("_format_source_group_header requires a non-empty catalog source")
    return _SOURCE_GROUP_HEADER_FORMAT.format(source=source)


def _emit_source_group_header(source: str) -> None:
    """Write the per-source group header to stderr.

    Grouping headers are diagnostics, not data: they go to stderr so the stdout
    stream remains pipeable / JSON-parseable. See :func:`_format_source_group_header`.

    Args:
        source: The resolved catalog source string (``<git_url>@<ref>``).
    """
    print(_format_source_group_header(source), file=sys.stderr)


def _resolve_search_sources(
    flag_value: list[str] | str | None,
    *,
    catalog_default_branch: str | None = None,
) -> list[str]:
    """Resolve the ordered, deduplicated catalog discovery set for ``search``.

    The ``--catalog-source`` flag(s) FULLY REPLACE ``KANON_CATALOG_SOURCES`` for
    the invocation (spec Section 4.1: "not additive"). ``flag_value`` is the
    parsed ``args.catalog_source``: a ``list[str]`` (repeated ``--catalog-source``
    flags, via the search parser's ``action="append"``), a bare ``str`` (defence
    against a single-valued namespace), or ``None`` when the flag was absent.
    When no flag is supplied, the plural env discovery set is used via
    :func:`resolve_env_catalog_sources`. Duplicate sources are collapsed while
    preserving first-seen order.

    Each surviving source whose ``@ref`` is omitted has its ref supplied by the
    default-branch precedence (spec Section 6 / FR-26 / FR-27) via
    :func:`normalize_catalog_source_ref`, sharing a single ``warned_urls`` dedup
    set so the defaulted-branch WARNING fires at most once per defaulted source
    across the whole discovery set.

    Args:
        flag_value: The parsed ``--catalog-source`` value (list, str, or None).
        catalog_default_branch: The ``--catalog-default-branch`` flag value
            (tier-2 of the default-branch precedence), or ``None`` when absent.

    Returns:
        Order-preserving, deduplicated list of fully-pinned ``<url>@<ref>``
        source strings. Empty when neither the flag nor the env var supplies a
        source.

    Raises:
        ValueError: When a configured env entry is malformed (propagated from
            :func:`resolve_env_catalog_sources`); a bad entry is never silently
            skipped (fail fast).
        DefaultBranchResolutionError: When a ref-less source's default branch
            cannot be resolved or does not exist on the remote (fail fast).
    """
    if flag_value is None:
        raw_sources = resolve_env_catalog_sources()
    elif isinstance(flag_value, str):
        raw_sources = [flag_value]
    else:
        raw_sources = list(flag_value)

    seen: set[str] = set()
    deduped: list[str] = []
    for source in raw_sources:
        if source in seen:
            continue
        seen.add(source)
        deduped.append(source)

    warned_urls: set[str] = set()
    return [
        normalize_catalog_source_ref(source, flag_value=catalog_default_branch, warned_urls=warned_urls)
        for source in deduped
    ]


def _run_search_multi_source(
    *,
    sources: list[str],
    detail: bool,
    tree: bool,
    max_depth: int | None,
    no_filter_required: bool,
    all_versions: bool,
    limit: int,
    no_limit: bool,
    since_version: str | None,
    substring: str | None,
    regex: str | None,
    match_fields: list[str] | None,
    filter_present: bool,
    list_format: str,
) -> int:
    """Render ``kanon search`` across more than one configured source.

    Enumeration runs CONCURRENTLY across the sources and is backed by the TTL
    cache (spec Section 4.1 / FR-25). Results are grouped per source: a
    ``Source: <url>@<ref>`` header is written to stderr before that source's
    entries. An unreachable source is skipped with a stderr warning (skip+warn,
    FLAG-B) and does not hard-fail the whole search. When every source yields no
    matching entry, the function exits 0 with a "no matches" stderr note.

    Per source the matching entry names are discovered by cloning the manifest
    repo and applying the same name/regex filter as the single-source path
    (DRY: ``_build_sorted_metadata`` + ``_build_filter_predicate``). The version
    enumeration of those entries (release tags under ``refs/tags/<name>/`` +
    branch-tip latest) is then performed concurrently across sources through the
    TTL cache. In default (latest-only) mode each matching entry renders its
    latest; in ``-A``/``--all`` mode the full release history is rendered.

    Args:
        sources: The deduplicated discovery set (length >= 2 by construction).
        detail / tree / max_depth / no_filter_required / all_versions / limit /
        no_limit / since_version / substring / regex / match_fields /
        filter_present / list_format: the already-validated ``run_search`` flags.

    Returns:
        Exit code: 0 on success (including a no-matches result), 1 on a flag
        combination unsupported in multi-source mode.
    """

    if tree:
        print(
            "ERROR: --tree is not supported across multiple catalog sources. "
            "Re-run with a single --catalog-source to render a dependency tree.",
            file=sys.stderr,
        )
        return 1
    if list_format == "json":
        print(
            "ERROR: --format json is not supported across multiple catalog sources. "
            "Re-run with a single --catalog-source for machine-readable output.",
            file=sys.stderr,
        )
        return 1

    predicate = (
        _build_filter_predicate(substring=substring, regex=regex, match_fields=match_fields) if filter_present else None
    )

    source_entry_names: dict[str, list[str]] = {}
    source_metadata: dict[str, list[CatalogMetadata]] = {}
    warnings: list[tuple[str, str]] = []
    for source in sources:
        try:
            manifest_root = _resolve_manifest_repo(source)
        except SystemExit as exc:
            warnings.append((source, f"manifest repo clone failed (exit {exc.code})"))
            continue
        except ValueError as exc:
            warnings.append((source, str(exc)))
            continue
        try:
            entries = _build_sorted_metadata(manifest_root)
        except CatalogMetadataParseError as exc:
            warnings.append((source, str(exc)))
            continue
        if predicate is not None:
            entries = _apply_filter(entries, predicate)
        source_metadata[source] = entries
        source_entry_names[source] = [m.name for m in entries]

    ttl_seconds = _resolve_search_ttl()
    now = int(time.time())
    max_workers = KANON_SEARCH_MAX_WORKERS
    enumerations, enum_warnings = _enumerate_sources_concurrently(
        {s: names for s, names in source_entry_names.items() if names},
        ttl_seconds=ttl_seconds,
        now=now,
        max_workers=max_workers,
    )
    warnings.extend(enum_warnings)

    for source, reason in warnings:
        print(
            SEARCH_UNREACHABLE_SOURCE_WARN_TEMPLATE.format(source=source, reason=reason),
            file=sys.stderr,
        )

    any_match = False
    for source in sources:
        if source not in source_entry_names:
            continue
        _emit_source_group_header(source)
        names = source_entry_names[source]
        if not names:
            continue
        source_enum = enumerations.get(source, {})
        for name in names:
            any_match = True
            enumeration = source_enum.get(name)
            if all_versions:
                _print_entry_all_versions(name, enumeration)
            else:
                if enumeration is not None:
                    print(_format_version_summary(enumeration), flush=True)
                else:
                    print(name, flush=True)

    if not any_match:
        print(SEARCH_NO_MATCHES_NOTE, file=sys.stderr)

    return 0


def _print_entry_all_versions(entry_name: str, enumeration: SourceEnumeration | None) -> None:
    """Print the full release history for one entry in ``-A``/``--all`` mode.

    Renders one ``<name>@<version>`` row per release tag (newest-first) and a
    trailing ``<name> (latest)`` row when a branch tip was resolved. An entry with
    no release tags and no resolvable tip renders its bare name so the operator
    still sees the entry under its source group.

    Args:
        entry_name: The catalog entry name.
        enumeration: The entry's enumeration, or ``None`` when enumeration was
            skipped (e.g. the source had no reachable enumeration result).
    """
    if enumeration is None:
        print(entry_name, flush=True)
        return
    if enumeration.has_latest:
        print(f"{entry_name} (latest)", flush=True)
    for version in enumeration.versions:
        print(f"{entry_name}@{version}", flush=True)
    if not enumeration.has_latest and not enumeration.versions:
        print(entry_name, flush=True)


def run_search(args: argparse.Namespace) -> int:
    """Entry-point function for the ``kanon search`` subcommand.

    Resolves the catalog source, clones the manifest repo, builds the sorted
    entry index, and writes output to stdout grouped under a per-source header
    on stderr. Returns 0 in all successful cases (including empty catalogs).
    Writes the canonical missing-catalog error to stderr and returns 1 when no
    catalog source is configured.

    Source grouping: a ``Source: <url>@<ref>`` header is written to stderr via
    :func:`_emit_source_group_header` before the entries discovered for the
    resolved catalog source (spec Section 4.1 / FR-10). The header is on stderr,
    never stdout, so the stdout stream stays pipeable into ``kanon add`` and any
    JSON document on stdout stays machine-parseable.

    Default mode: prints one entry name per line with ``flush=True`` per spec
    Section 4.1 (latest version only).

    Detail mode (``--detail``): prints a multi-line record per entry via
    :func:`_format_detail_record`. Human-readable; not pipeable into
    ``kanon add``.

    Tree mode (``--tree``): renders a three-layer ASCII dependency tree per
    entry via :func:`_render_tree`. Subject to the threshold guardrail unless
    a filter or ``--no-filter-required`` is supplied.

    All-versions mode (``-A``/``--all``): walks historical catalog versions
    via ``git ls-remote --tags`` and emits one ``<name>@<version>`` row per
    catalog entry per version (all tagged versions of each matching manifest
    rather than the latest-only default). Mutually exclusive with ``--tree``.

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
            - ``all_versions`` (``bool``): from ``-A``/``--all``.
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

    try:
        sources: list[str] = _resolve_search_sources(
            getattr(args, "catalog_source", None),
            catalog_default_branch=getattr(args, "catalog_default_branch", None),
        )
    except DefaultBranchResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    catalog_source: str | None = sources[0] if sources else None
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

    if substring is not None and regex is not None:
        print(
            "ERROR: <substring> and --regex are mutually exclusive. "
            "Supply the positional substring OR --regex <pattern>, not both.",
            file=sys.stderr,
        )
        return 1

    if match_fields is not None and substring is None and regex is None:
        print(
            "ERROR: --match-fields requires a filter. "
            "Supply a positional <substring> or --regex <pattern> together with --match-fields.",
            file=sys.stderr,
        )
        return 1

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

    if regex is not None:
        try:
            re.compile(regex)
        except re.error as exc:
            print(
                f"ERROR: invalid --regex pattern {regex!r}: {exc}",
                file=sys.stderr,
            )
            return 1

    filter_present: bool = substring is not None or regex is not None

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

    if list_format == "json" and tree:
        print(
            "ERROR: --format json and --tree are mutually exclusive. "
            "JSON output is not defined for tree mode. "
            "Use --format json without --tree, or use --tree without --format json.",
            file=sys.stderr,
        )
        return 1

    if tree and all_versions:
        print(
            "ERROR: --tree and -A/--all are mutually exclusive. "
            "Use --tree for dependency tree rendering, or -A/--all to "
            "list all available versions. These flags cannot be combined.",
            file=sys.stderr,
        )
        return 1

    if no_limit and limit != KANON_LIST_LIMIT:
        print(
            "ERROR: --limit and --no-limit are mutually exclusive. "
            "Pass --limit N to cap at N versions, or --no-limit to walk all versions.",
            file=sys.stderr,
        )
        return 1

    if not sources:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="search"),
            file=sys.stderr,
        )
        return 1

    if len(sources) > 1:
        return _run_search_multi_source(
            sources=sources,
            detail=detail,
            tree=tree,
            max_depth=max_depth,
            no_filter_required=no_filter_required,
            all_versions=all_versions,
            limit=limit,
            no_limit=no_limit,
            since_version=since_version,
            substring=substring,
            regex=regex,
            match_fields=match_fields,
            filter_present=filter_present,
            list_format=list_format,
        )

    _emit_source_group_header(catalog_source)

    if all_versions:
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
        try:
            all_entries = _build_sorted_metadata(manifest_root)
        except CatalogMetadataParseError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        entry_count = len(all_entries)

        guardrail_msg = _check_tree_guardrail(entry_count, max_depth, no_filter_required, filter_present=filter_present)
        if guardrail_msg is not None:
            print(guardrail_msg, file=sys.stderr, end="")
            return 1

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

    try:
        all_entries = _build_sorted_metadata(manifest_root)
    except CatalogMetadataParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

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
    """Register the ``search`` subcommand on the top-level argparse parser.

    ``kanon search`` is the hard rename of the former ``list`` command (no
    deprecation alias); ``list`` is no longer a registered subcommand and
    ``kanon`` with that token yields the argparse unknown-command exit 2.

    Adds the ``search`` subparser with:
    - ``<substring>`` optional positional filter (substring, case-sensitive).
    - ``--catalog-source`` from the shared factory.
    - ``--format {names,json}`` to select the output format (default: ``names``).
    - ``--detail`` for human-readable per-entry records.
    - ``--tree`` for the three-layer ASCII dependency tree renderer.
    - ``--max-depth N`` to cap the rendered tree depth (0 = root only).
    - ``--no-filter-required`` to bypass the threshold guardrail.
    - ``-A``/``--all`` to walk all historical tagged versions (vs. latest-only).
    - ``--limit N`` to cap the number of versions walked (default: ``KANON_LIST_LIMIT``).
    - ``--no-limit`` to walk all PEP 440-valid tags without a cap.
    - ``--since-version <spec>`` to filter walked versions by a PEP 440 constraint.
    - ``--regex <pattern>`` for regex-based entry filtering.
    - ``--match-fields <csv>`` to narrow the filter to specific fields.

    Results are grouped by catalog source: a ``Source: <url>@<ref>`` header is
    written to stderr before the entries for the resolved source (spec
    Section 4.1 / FR-10).

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
        "search",
        add_help=True,
        help="Discover catalog entries from a manifest repo, grouped by source.",
        description=(
            "Print one catalog entry name per line to stdout, sorted\n"
            "lexicographically and grouped under a per-source header on stderr.\n"
            "Reads *-marketplace.xml files under repo-specs/ in the manifest repo\n"
            "identified by the catalog source.\n\n"
            "Requires a catalog source via --catalog-source or the\n"
            "KANON_CATALOG_SOURCES environment variable (the single configured\n"
            "entry is used). The CLI flag takes precedence when both are set.\n\n"
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
            "    -A/--all mode emits {name, version, ref, sha}.\n"
            "The KANON_LIST_FORMAT environment variable sets the format when the\n"
            "CLI flag is absent; the CLI flag takes precedence when both are set.\n"
            "--format json is incompatible with --tree (hard error).\n\n"
            "Tree mode (--tree): renders a three-layer ASCII dependency tree\n"
            "per entry. Subject to a threshold guardrail: when the catalog has\n"
            f"more than KANON_TREE_NO_FILTER_THRESHOLD (default {KANON_TREE_NO_FILTER_THRESHOLD})\n"
            "entries, a filter is required unless --no-filter-required is passed.\n"
            "Resolution paths: positional <name> substring, --regex <pattern>,\n"
            "--max-depth 0, or --no-filter-required.\n\n"
            "All-versions mode (-A/--all): walks historical catalog versions\n"
            "via git ls-remote --tags. Emits one <name>@<version> row per catalog\n"
            "entry per version, newest version first (default: latest-only).\n"
            f"Default version cap: KANON_LIST_LIMIT (default {KANON_LIST_LIMIT}, "
            "overridable via env var).\n"
            "Use --limit N to cap at N versions, --no-limit to walk all versions.\n"
            "Use --since-version <spec> to filter by a PEP 440 constraint\n"
            "(e.g. '>=1.0,<2.0'). Mutually exclusive with --tree."
        ),
        epilog=(
            "Examples:\n"
            "  kanon search --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search foo --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search --regex '^foo' --catalog-source ...\n"
            "  kanon search foo --match-fields keywords --catalog-source ...\n"
            "  kanon search --format json --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search --format json -A --catalog-source ...\n"
            "  kanon search --detail --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search --tree --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search --tree --max-depth 0 --catalog-source ...\n"
            "  kanon search --tree --no-filter-required --catalog-source ...\n"
            "  kanon search -A --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon search -A --limit 3 --catalog-source ...\n"
            "  kanon search -A --no-limit --catalog-source ...\n"
            "  kanon search -A --since-version '>=1.0,<2.0' --catalog-source ...\n"
            "  KANON_CATALOG_SOURCES=https://example.com/org/repo.git@v1.0.0 kanon search\n"
            "  KANON_LIST_FORMAT=json kanon search --catalog-source ..."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    add_catalog_source_arg(parser, allow_multiple=True)
    add_catalog_default_branch_arg(parser)

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
            "objects; -A/--all mode emits {name, version, ref, sha} objects. "
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
            "Mutually exclusive with -A/--all. Subject to the threshold "
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
        "-A",
        "--all",
        dest="all_versions",
        action="store_true",
        default=False,
        help=(
            "Show all tagged versions of each matching manifest instead of the "
            "latest-only default. Walks all historical tagged versions of the "
            "manifest repo and emits one <name>@<version> row per catalog entry "
            "per version. Versions are ordered newest-first by PEP 440 natural "
            "sort; entries within each version are sorted lexicographically. "
            "Mutually exclusive with --tree. Default cap: KANON_LIST_LIMIT "
            "(default 50, overridable via env var). Use --limit N or --no-limit "
            "to control the number of versions walked."
        ),
    )

    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=KANON_LIST_LIMIT,
        metavar="N",
        help=(
            "Cap the number of versions walked by -A/--all. "
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
            "Walk all PEP 440-valid tags when using -A/--all, with no cap. "
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
            "Filter the versions walked by -A/--all to those matching "
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

    parser.set_defaults(func=run_search)
