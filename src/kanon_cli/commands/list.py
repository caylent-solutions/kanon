"""kanon list subcommand: list catalog entry names from a manifest repo.

Reads ``*-marketplace.xml`` files under ``repo-specs/`` in the resolved
manifest repo and prints one entry name per line to stdout, sorted
lexicographically.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.1 (data source + default output) and Section 4 header
(canonical missing-catalog error and env-var precedence).
Section 4.1 flag-table row ``--detail`` for the per-entry detail formatter.

Environment variables:
- ``KANON_CATALOG_SOURCE``: catalog source override (CLI flag wins).
"""

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    LIST_EMPTY_CATALOG_NOTE,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.core.catalog import _parse_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.metadata import CatalogMetadata, _parse_catalog_metadata
from kanon_cli.version import is_version_constraint, resolve_version

# -- Detail formatter private constants --
# Placeholder rendered in place of a missing recommended field (type=None).
# Matches the spec-canonical text from spec Section 2.1 step 2.
_DETAIL_MISSING_PLACEHOLDER = "<missing>"
# Width to which all field labels are padded so the ' : ' separator is
# column-aligned across the four field lines in a detail record.
_DETAIL_LABEL_WIDTH = 12


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

    Args:
        args: Parsed argument namespace. Expected attributes:
            - ``catalog_source`` (``str | None``): from ``--catalog-source``.
            - ``detail`` (``bool``): from ``--detail`` (default ``False``).

    Returns:
        Exit code: 0 on success (including empty catalog), 1 when no catalog
        source is configured.
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or os.environ.get(CATALOG_ENV_VAR)
    detail: bool = getattr(args, "detail", False)

    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="list"),
            file=sys.stderr,
        )
        return 1

    manifest_root = _resolve_manifest_repo(catalog_source)

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
    - ``--catalog-source`` from the shared factory in
      ``kanon_cli.core.cli_args`` (so there is no flag-definition collision
      with ``bootstrap`` or any other command that also uses the factory).
    - ``--detail`` for human-readable per-entry records (not pipeable into
      ``kanon add``; machine consumers should combine with ``--format json``).

    Args:
        subparsers: The subparsers action from the parent parser (returned by
            ``ArgumentParser.add_subparsers()``).
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
            "precedence when both are set."
        ),
        epilog=(
            "Examples:\n"
            "  kanon list --catalog-source https://example.com/org/repo.git@main\n"
            "  kanon list --detail --catalog-source https://example.com/org/repo.git@main\n"
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

    parser.set_defaults(func=run_list)
