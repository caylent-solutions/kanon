"""kanon list subcommand: list catalog entry names from a manifest repo.

Reads ``*-marketplace.xml`` files under ``repo-specs/`` in the resolved
manifest repo and prints one entry name per line to stdout, sorted
lexicographically.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.1 (data source + default output) and Section 4 header
(canonical missing-catalog error and env-var precedence).

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
from kanon_cli.core.metadata import _parse_catalog_metadata
from kanon_cli.version import is_version_constraint, resolve_version


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


def run_list(args: argparse.Namespace) -> int:
    """Entry-point function for the ``kanon list`` subcommand.

    Resolves the catalog source, clones the manifest repo, builds the sorted
    entry-name index, and prints one name per line to stdout. Returns 0 in all
    successful cases (including empty catalogs). Writes the canonical
    missing-catalog error to stderr and returns 1 when no catalog source is
    configured.

    Entry names are fully collected and sorted in memory, then printed
    line-by-line with ``flush=True`` per spec Section 4.1.

    Args:
        args: Parsed argument namespace. Expected attributes:
            - ``catalog_source`` (``str | None``): from ``--catalog-source``.

    Returns:
        Exit code: 0 on success (including empty catalog), 1 when no catalog
        source is configured.
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or os.environ.get(CATALOG_ENV_VAR)

    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="list"),
            file=sys.stderr,
        )
        return 1

    manifest_root = _resolve_manifest_repo(catalog_source)
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
            "  KANON_CATALOG_SOURCE=https://example.com/org/repo.git@v1.0.0 kanon list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    add_catalog_source_arg(parser)

    parser.set_defaults(func=run_list)
