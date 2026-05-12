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

Environment variables:
- ``KANON_CATALOG_SOURCE``: catalog source override (CLI flag wins).
- ``KANON_TREE_NO_FILTER_THRESHOLD``: overrides the default threshold (20)
  above which ``kanon list --tree`` requires a filter.
"""

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile

import defusedxml.ElementTree as ET

from kanon_cli.constants import (
    CATALOG_ENV_VAR,
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

# -- Tree renderer private constants --
_TREE_PREFIX_MID = "+--"
_TREE_PREFIX_LAST = "\\--"
_TREE_INDENT_MID = "|  "
_TREE_INDENT_LAST = "   "

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

    Box-drawing uses only ``+--``, ``|  ``, and ``\\--`` (ASCII-safe).
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
            inc_prefix = _TREE_PREFIX_LAST if is_last else _TREE_PREFIX_MID
            inc_indent = _TREE_INDENT_LAST if is_last else _TREE_INDENT_MID

            inc_sha = _sha12_from_path(inc_path)
            lines.append(f"{inc_prefix}xml {inc_path.stem}@included ({inc_sha})")

            if show_projects:
                _, inc_proj_list = _parse_xml_includes_and_projects(inc_path)
                for j, (proj_name, fetch_url, revision) in enumerate(inc_proj_list):
                    is_last_proj = j == len(inc_proj_list) - 1
                    proj_prefix = inc_indent + (_TREE_PREFIX_LAST if is_last_proj else _TREE_PREFIX_MID)
                    proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                    proj_spec = revision if revision else "unspecified"
                    lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

        for idx, ph_name in enumerate(include_placeholders):
            abs_idx = len(include_paths) + idx
            is_last = abs_idx == total_d1 - 1
            ph_prefix = _TREE_PREFIX_LAST if is_last else _TREE_PREFIX_MID
            lines.append(f"{ph_prefix}xml {ph_name}@unknown (000000000000)")

        # Root projects (from the root marketplace XML) at depth 2.
        # They appear after all include nodes, indented under the last include's indent.
        if show_projects and root_projects:
            # Use the indent of the last include node for nesting root projects.
            if include_paths:
                last_inc_idx = len(include_paths) - 1
                last_inc_is_last_d1 = last_inc_idx == total_d1 - 1
                last_inc_indent = _TREE_INDENT_LAST if last_inc_is_last_d1 else _TREE_INDENT_MID
            else:
                # Only placeholders exist; use empty indent for root projects.
                last_inc_indent = ""
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last_rp = j == len(root_projects) - 1
                proj_prefix = last_inc_indent + (_TREE_PREFIX_LAST if is_last_rp else _TREE_PREFIX_MID)
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    else:
        # No includes: root projects appear as direct depth-1 children.
        if show_projects and root_projects:
            for j, (proj_name, fetch_url, revision) in enumerate(root_projects):
                is_last = j == len(root_projects) - 1
                proj_prefix = _TREE_PREFIX_LAST if is_last else _TREE_PREFIX_MID
                proj_sha = _sha12_from_content(f"{proj_name}@{fetch_url}@{revision}")
                proj_spec = revision if revision else "unspecified"
                lines.append(f"{proj_prefix}project {proj_name}@{proj_spec} ({proj_sha})")

    return lines


# ---------------------------------------------------------------------------
# Threshold guardrail
# ---------------------------------------------------------------------------


def _check_tree_guardrail(
    entry_count: int,
    max_depth: int | None,
    no_filter_required: bool,
) -> str | None:
    """Return an error message string when the threshold guardrail should fire.

    Returns ``None`` when the guardrail does not apply (either the catalog is
    small enough, a valid filter is present, or ``--no-filter-required`` was
    passed).

    ``--max-depth 0`` counts as a valid filter per spec Section 4.1, so the
    guardrail does NOT fire when ``max_depth == 0``.

    Args:
        entry_count: Number of catalog entries in the manifest repo.
        max_depth: Value of ``--max-depth``, or ``None`` for unlimited.
        no_filter_required: ``True`` when ``--no-filter-required`` was passed.

    Returns:
        An error message string when the guardrail fires, or ``None``.
    """
    if no_filter_required:
        return None
    if max_depth is not None and max_depth == 0:
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

    Args:
        args: Parsed argument namespace. Expected attributes:
            - ``catalog_source`` (``str | None``): from ``--catalog-source``.
            - ``detail`` (``bool``): from ``--detail`` (default ``False``).
            - ``tree`` (``bool``): from ``--tree`` (default ``False``).
            - ``max_depth`` (``int | None``): from ``--max-depth``.
            - ``no_filter_required`` (``bool``): from ``--no-filter-required``.
            - ``all_versions`` (``bool``): from ``--all-versions``.

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

    if tree and all_versions:
        print(
            "ERROR: --tree and --all-versions are mutually exclusive. "
            "Use --tree for dependency tree rendering, or --all-versions to "
            "list all available versions. These flags cannot be combined.",
            file=sys.stderr,
        )
        return 1

    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="list"),
            file=sys.stderr,
        )
        return 1

    manifest_root = _resolve_manifest_repo(catalog_source)

    if tree:
        index = _build_sorted_index(manifest_root)
        entry_count = len(index)

        guardrail_msg = _check_tree_guardrail(entry_count, max_depth, no_filter_required)
        if guardrail_msg is not None:
            print(guardrail_msg, file=sys.stderr, end="")
            return 1

        if not index:
            print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
            return 0

        for entry_name in index:
            tree_lines = _render_tree(manifest_root, entry_name, max_depth)
            for line in tree_lines:
                print(line, flush=True)

        return 0

    if detail:
        entries = _build_sorted_metadata(manifest_root)
        if not entries:
            print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
            return 0
        for metadata in entries:
            print(_format_detail_record(metadata), flush=True)
    else:
        index = _build_sorted_index(manifest_root)
        if not index:
            print(LIST_EMPTY_CATALOG_NOTE, file=sys.stderr)
            return 0
        for name in index:
            print(name, flush=True)

    return 0


def register(subparsers) -> None:
    """Register the ``list`` subcommand on the top-level argparse parser.

    Adds the ``list`` subparser with:
    - ``--catalog-source`` from the shared factory.
    - ``--detail`` for human-readable per-entry records.
    - ``--tree`` for the three-layer ASCII dependency tree renderer.
    - ``--max-depth N`` to cap the rendered tree depth (0 = root only).
    - ``--no-filter-required`` to bypass the threshold guardrail.

    Threshold guardrail: when the catalog has more than
    ``KANON_TREE_NO_FILTER_THRESHOLD`` entries (default 20, overridable via
    the ``KANON_TREE_NO_FILTER_THRESHOLD`` env var) and the operator has not
    supplied a filter (positional substring, ``--regex``, or ``--max-depth 0``)
    and has not passed ``--no-filter-required``, ``--tree`` exits non-zero with
    an error naming the threshold, the actual count, and the four resolution
    paths: positional substring, ``--regex``, ``--max-depth 0``,
    ``--no-filter-required``.

    Args:
        subparsers: The subparsers action from the parent parser.
    """
    parser = subparsers.add_parser(
        "list",
        help="List catalog entry names from a manifest repo.",
        description=(
            "Print one catalog entry name per line to stdout, sorted\n"
            "lexicographically. Reads *-marketplace.xml files under\n"
            "repo-specs/ in the manifest repo identified by the catalog source.\n\n"
            "Requires a catalog source via --catalog-source or the\n"
            "KANON_CATALOG_SOURCE environment variable. The CLI flag takes\n"
            "precedence when both are set.\n\n"
            "Tree mode (--tree): renders a three-layer ASCII dependency tree\n"
            "per entry. Subject to a threshold guardrail: when the catalog has\n"
            f"more than KANON_TREE_NO_FILTER_THRESHOLD (default {KANON_TREE_NO_FILTER_THRESHOLD})\n"
            "entries, a filter is required unless --no-filter-required is passed.\n"
            "Resolution paths: positional <name> substring, --regex <pattern>,\n"
            "--max-depth 0, or --no-filter-required."
        ),
        epilog=(
            "Examples:\n"
            "  kanon list --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --detail --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --tree --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --tree --max-depth 0 --catalog-source ...\n"
            "  kanon list --tree --no-filter-required --catalog-source ...\n"
            "  KANON_CATALOG_SOURCE=https://example.com/org/repo.git@v1.0.0 kanon list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    add_catalog_source_arg(parser)

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

    parser.set_defaults(func=run_list)
