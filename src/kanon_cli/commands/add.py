"""kanon add subcommand: append dependency triples to a .kanon file.

Resolves one or more catalog entries from a manifest repo and writes the
three KANON_SOURCE_<source_name>_{URL,REVISION,PATH} lines to the
destination .kanon file. Creates the file with the standard header if it
does not already exist.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.2 (Behaviour steps 1-5), Section 4.0 (last-@ spec split),
Section 2.1 (worked example step 3), Section 1.1 (.kanon file definition).
"""

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    KANON_HEADER_CLAUDE_MARKETPLACES_DIR,
    KANON_HEADER_GITBASE,
    KANON_HEADER_MARKETPLACE_INSTALL,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.core.catalog import _parse_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.metadata import (
    CatalogMetadata,
    CatalogMetadataParseError,
    _parse_catalog_metadata,
    derive_source_name,
)
from kanon_cli.version import _list_tags, _resolve_constraint_from_tags, is_version_constraint, resolve_version


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'add' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "add",
        help="Add one or more catalog entries to the .kanon file.",
        description=(
            "Resolve catalog entries from a manifest repo and append the\n"
            "KANON_SOURCE_<name>_{URL,REVISION,PATH} triple to the destination\n"
            ".kanon file. Creates the file with a standard header when absent.\n\n"
            "Each ENTRY is '<name>' or '<name>@<spec>' where <spec> is a PEP 440\n"
            "constraint (e.g. ==1.0.0, ~=1.2, >=1.0.0,<2.0.0). The last '@' in\n"
            "each argument is the delimiter -- see spec Section 4.0 resolver rules.\n"
            "When <spec> is omitted the highest PEP 440-valid git tag in the\n"
            "manifest repo is selected automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "entries",
        metavar="<name>[@<spec>]",
        nargs="+",
        help=(
            "One or more catalog entry names, optionally suffixed with '@<spec>'\n"
            "where <spec> is a PEP 440 version constraint. The last '@' is the\n"
            "delimiter (spec Section 4.0). Shell-quote constraints containing\n"
            "special characters such as '>' or '<'."
        ),
    )

    add_catalog_source_arg(parser)

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT),
        metavar="<path>",
        help=(
            f"Destination .kanon file path. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    # --force and --dry-run are reserved for E2-F4-S1-T2; registered here so
    # later tasks do not need to re-thread argparse.
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    parser.set_defaults(func=run_add)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_name_spec(raw: str) -> tuple[str, str | None]:
    """Split a raw positional argument on the last '@'.

    Per spec Section 4.0, the split always occurs at the LAST '@' so that
    catalog entry names that include an '@' (e.g. SSH-style git URLs used as
    names) are handled correctly.

    Args:
        raw: The raw positional argument string.

    Returns:
        A 2-tuple (name, spec) where spec is None when no '@' is present.
    """
    idx = raw.rfind("@")
    if idx == -1:
        return raw, None
    name = raw[:idx]
    spec = raw[idx + 1 :]
    return name, spec if spec else None


def _build_triple_lines(
    source_name: str,
    url: str,
    revision: str,
    path: str,
) -> list[str]:
    """Construct the three KANON_SOURCE_<source_name>_* lines.

    Args:
        source_name: Normalised source name (from derive_source_name).
        url: Manifest repo git URL.
        revision: Resolved version spec (e.g. refs/tags/1.2.0).
        path: Repo-relative path to the marketplace XML file.

    Returns:
        A list of exactly three strings: URL, REVISION, PATH lines.
    """
    return [
        f"KANON_SOURCE_{source_name}_URL={url}",
        f"KANON_SOURCE_{source_name}_REVISION={revision}",
        f"KANON_SOURCE_{source_name}_PATH={path}",
    ]


def _write_standard_header(dest: pathlib.Path) -> None:
    """Write the standard .kanon header lines to dest, if dest does not exist.

    Creates dest and writes the three standard header lines drawn from the
    constants module. Does nothing when dest already exists.

    Args:
        dest: Destination .kanon file path.
    """
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = f"{KANON_HEADER_GITBASE}\n{KANON_HEADER_CLAUDE_MARKETPLACES_DIR}\n{KANON_HEADER_MARKETPLACE_INSTALL}\n"
    dest.write_text(header)


def _append_triple_block(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
) -> None:
    """Append the triple lines to dest and print a summary to stdout.

    Args:
        dest: Destination .kanon file path (must exist before calling).
        source_name: Normalised source name, used in the stdout summary.
        lines: The three KANON_SOURCE_* lines to append.
    """
    with dest.open("a") as fh:
        fh.write("\n")
        for line in lines:
            fh.write(line + "\n")
    key_names = ", ".join(
        [
            f"KANON_SOURCE_{source_name}_URL",
            f"KANON_SOURCE_{source_name}_REVISION",
            f"KANON_SOURCE_{source_name}_PATH",
        ]
    )
    print(f"Wrote {key_names} to {dest}")


def _build_entry_catalog(
    manifest_root: pathlib.Path,
    url: str,
) -> list[tuple[CatalogMetadata, pathlib.Path, str]]:
    """Walk repo-specs/**/*-marketplace.xml and parse every entry.

    Raises SystemExit with exit code 1 and the spec-canonical integrity-issues
    error message if any XML file fails parsing (soft-spot rule 1 or rule 3).

    Args:
        manifest_root: Root of the cloned manifest repo.
        url: The manifest repo URL (included in error messages).

    Returns:
        List of (CatalogMetadata, xml_path, url) triples for every entry found.
    """
    repo_specs = manifest_root / "repo-specs"
    if not repo_specs.is_dir():
        return []

    xml_paths = list(repo_specs.rglob("*-marketplace.xml"))
    entries: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
    error_paths: list[str] = []

    for xml_path in sorted(xml_paths):
        try:
            metadata = _parse_catalog_metadata(xml_path)
            entries.append((metadata, xml_path, url))
        except CatalogMetadataParseError as exc:
            error_paths.append(str(xml_path))
            print(f"ERROR: {exc}", file=sys.stderr)

    if error_paths:
        offending = ", ".join(error_paths)
        print(
            f"ERROR: manifest repo `{url}` has integrity issues in the following XML paths: {offending}",
            file=sys.stderr,
        )
        sys.exit(1)

    return entries


def _find_entry_by_name(
    name: str,
    catalog: list[tuple[CatalogMetadata, pathlib.Path, str]],
) -> tuple[CatalogMetadata, pathlib.Path, str]:
    """Find a catalog entry by exact name match.

    Args:
        name: The requested catalog entry name.
        catalog: The list of (CatalogMetadata, xml_path, url) tuples.

    Returns:
        The matching (CatalogMetadata, xml_path, url) tuple.

    Raises:
        SystemExit: When no entry with the given name is found.
    """
    for metadata, xml_path, url in catalog:
        if metadata.name == name:
            return metadata, xml_path, url

    print(
        f"ERROR: Catalog entry '{name}' not found in the manifest repo.\n"
        "Run 'kanon list' to discover available entry names.",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_spec(url: str, spec: str | None) -> str:
    """Resolve the version spec for a catalog entry.

    When spec is None, selects the highest PEP 440-valid git tag on the
    manifest repo via git ls-remote --tags.

    When spec is a non-empty string, delegates to resolve_version() to
    resolve the PEP 440 constraint against the available tags.

    Args:
        url: The manifest repo git URL.
        spec: The version spec string (e.g. '==1.0.0', '~=1.2') or None.

    Returns:
        A full tag ref string (e.g. 'refs/tags/1.2.0').
    """
    if spec is None:
        tags = _list_tags(url)
        if not tags:
            print(
                f"ERROR: No tags found in manifest repo {url!r}.\n"
                "The manifest repo must have at least one PEP 440-valid git tag.",
                file=sys.stderr,
            )
            sys.exit(1)
        return _resolve_constraint_from_tags("*", tags)

    return resolve_version(url, spec)


def _resolve_manifest_repo_for_add(catalog_source: str) -> tuple[pathlib.Path, str, str]:
    """Clone the manifest repo and return (repo_root, url, ref).

    Args:
        catalog_source: A '<git_url>@<ref>' string.

    Returns:
        Tuple of (repo_root_path, url, ref).

    Raises:
        SystemExit: When the git clone fails or catalog source format is invalid.
    """
    try:
        url, ref = _parse_catalog_source(catalog_source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    resolved_ref = ref
    if ref == "latest":
        resolved_ref = "*"
    if is_version_constraint(resolved_ref):
        resolved = resolve_version(url, resolved_ref)
        resolved_ref = resolved.removeprefix("refs/tags/")

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-add-"))
    repo_dir = clone_dir / "repo"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", resolved_ref, url, str(repo_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: Failed to clone manifest repo from {url}@{resolved_ref}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    return repo_dir, url, resolved_ref


def _xml_repo_relative_path(
    manifest_root: pathlib.Path,
    xml_path: pathlib.Path,
) -> str:
    """Return the repo-relative path for the given XML file.

    Args:
        manifest_root: Root of the cloned manifest repo.
        xml_path: Absolute path to the marketplace XML file.

    Returns:
        Repo-relative path string (e.g. 'repo-specs/foo-marketplace.xml').
    """
    return str(xml_path.relative_to(manifest_root))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_add(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon add' subcommand.

    Resolves each requested catalog entry, constructs the three
    KANON_SOURCE_* lines, and appends them to the destination .kanon file.
    Creates the file with a standard header when absent.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure (typically via sys.exit()).
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or os.environ.get(CATALOG_ENV_VAR)
    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="add"),
            file=sys.stderr,
        )
        sys.exit(1)

    kanon_file = pathlib.Path(getattr(args, "kanon_file", KANON_KANON_FILE_DEFAULT))

    # Step 1: Resolve manifest repo.
    manifest_root, url, _ref = _resolve_manifest_repo_for_add(catalog_source)

    # Step 2: Build entry catalog (hard-errors on soft-spot rule 1 / 3 violations).
    catalog = _build_entry_catalog(manifest_root, url)

    # Step 3: Ensure destination file exists (creates with standard header if absent).
    _write_standard_header(kanon_file)

    # Step 4: Process each requested entry in argument order.
    for raw_entry in args.entries:
        name, spec = _split_name_spec(raw_entry)

        metadata, xml_path, entry_url = _find_entry_by_name(name, catalog)

        resolved_revision = _resolve_spec(entry_url, spec)

        source_name = derive_source_name(metadata.name)

        rel_path = _xml_repo_relative_path(manifest_root, xml_path)

        lines = _build_triple_lines(
            source_name=source_name,
            url=entry_url,
            revision=resolved_revision,
            path=rel_path,
        )

        _append_triple_block(
            dest=kanon_file,
            source_name=source_name,
            lines=lines,
        )

    return 0
