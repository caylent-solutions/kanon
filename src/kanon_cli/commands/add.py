"""kanon add subcommand: append alias-keyed dependency blocks to a .kanon file.

Resolves one or more catalog entries from a manifest repo and writes the
alias-keyed KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE} block to the
destination .kanon file (spec Section 5.1 / FR-5, FR-6). There is no global
``[catalog]`` block and no standard header: the per-dependency blocks fully
replace the single global header, so ``add`` writes neither a
``KANON_MARKETPLACE_INSTALL`` header line nor a ``GITBASE`` header line. The
``GITBASE`` org base is recorded per dependency in ``KANON_SOURCE_<alias>_GITBASE``.

Spec reference: ``specs/kanon-refinements.md`` Section 5.1 (alias-keyed
``.kanon`` blocks, ``_REVISION`` -> ``_REF``, ``_NAME`` / ``_GITBASE``, no
``[catalog]``), Section 4.2 (``add`` alias keying), plus
``spec/kanon-list-add-lock-features-spec.md`` Section 4.0 (last-@ spec split),
Section 4.2 collision detection pre-flight, Section 4.2 flag-table rows
--force and --dry-run.
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

from packaging.version import InvalidVersion, Version

from kanon_cli.constants import (
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    MISSING_CATALOG_ERROR_TEMPLATE,
    SOURCE_PATH_SUFFIX,
    SOURCE_PREFIX,
    SOURCE_REF_SUFFIX,
    SOURCE_SUFFIXES,
    SOURCE_URL_SUFFIX,
    TAG_ERROR_DISPLAY_CAP,
)
from kanon_cli.core.catalog import _parse_catalog_source, resolve_env_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.utils.concurrency import kanon_workspace_lock
from kanon_cli.core.metadata import (
    CatalogMetadata,
    CatalogMetadataParseError,
    _parse_catalog_metadata,
    derive_source_name,
    find_catalog_entry_files,
)
from kanon_cli.version import _list_tags, _resolve_constraint_from_tags, is_version_constraint, resolve_version

# Spec-verbatim error emitted when the manifest repo has no PEP 440-valid tags
# and the operator did not supply an explicit @<spec> constraint.
# Spec reference: kanon-list-add-lock-features-spec.md Section 4.2, step 4.
_ZERO_PEP440_TAGS_ERROR = (
    "manifest repo has no PEP 440-valid tags; pin to a branch or SHA"
    " explicitly (e.g., 'kanon add foo@main') or ask the catalog author"
    " to publish a release tag."
)

# Pre-compiled regex for SCP-shorthand git URLs: git@host:org/repo[.git]
# Compiled at module load time to avoid re-compiling on every derivation call.
_SCP_URL_PATTERN = re.compile(r"^(git@[^:]+):([^/]+)/[^/]+(?:\.git)?$")


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'add' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "add",
        add_help=True,
        help="Add one or more catalog entries to the .kanon file.",
        description=(
            "Resolve catalog entries from a manifest repo and append the\n"
            "alias-keyed KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE} block\n"
            "to the destination .kanon file. No global header is written.\n\n"
            "Each ENTRY is '<name>' or '<name>@<spec>' where <spec> is a PEP 440\n"
            "constraint (e.g. ==1.0.0, ~=1.2, >=1.0.0,<2.0.0). The last '@' in\n"
            "each argument is the delimiter -- see spec Section 4.0 resolver rules.\n"
            "When <spec> is omitted the highest PEP 440-valid git tag in the\n"
            "manifest repo is selected automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Note: when supplying a PEP 440 range, quote the spec to avoid shell parsing:\n"
            "   kanon add 'package-a@>=1.0,<2.0'"
        ),
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

    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help=(
            "Overwrite an existing KANON_SOURCE_<name>_* block in the\n"
            "destination .kanon file. Without this flag, any collision\n"
            "between a requested source name and an existing block is a\n"
            "hard error. Collision detection pre-flight runs before any\n"
            "write whether or not --force is set."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Print the diff that WOULD be written to the destination\n"
            ".kanon file ('+' for added lines, '-' for removed lines\n"
            "under --force). Makes no on-disk change. Exits 0. Collision\n"
            "detection pre-flight still runs, so within-request and\n"
            "against-existing collisions are reported before a diff is\n"
            "shown (unless --force is also passed)."
        ),
    )

    # The per-dependency KANON_SOURCE_<alias>_MARKETPLACE field and its
    # --marketplace-install / --no-marketplace-install flags are introduced by
    # the add source-explicit task (E4-F1-S3, AC-25). This task removes the
    # global KANON_MARKETPLACE_INSTALL header writer, so no marketplace flag is
    # registered here.

    parser.set_defaults(func=run_add)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CatalogSourceURLDerivationError(ValueError):
    """Raised when GITBASE cannot be derived from the catalog-source URL.

    Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
    Section 4 E28 + CLAUDE.md Error Handling Contract.

    Args:
        url: The catalog-source URL that could not be parsed.
        reason: A human-readable explanation of why derivation failed.
    """

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: cannot derive GITBASE from catalog-source URL {self.url}: {self.reason}\n"
            "Pass an explicit GITBASE via the KANON_GITBASE env var or"
            " hand-edit .kanon after running kanon add."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_gitbase_from_catalog_source(url: str) -> str:
    """Derive the GITBASE value from a catalog-source URL.

    Extracts the scheme + authority (host + optional org/user prefix) from
    the supplied URL. Supports the following URL forms:

    - ``https://host/org/repo(.git)?`` -> ``https://host/org`` (or ``https://host``
      when there is no org path segment before the repo)
    - ``http://host/org/repo(.git)?`` -> ``http://host/org``
    - ``ssh://user@host/org/repo(.git)?`` -> ``ssh://user@host/org``
    - ``git@host:org/repo(.git)?`` (SCP shorthand) -> ``git@host:org``
    - ``file:///path/to/bare-repo`` -> ``file:///path/to`` (parent directory of the repo)

    Args:
        url: The catalog-source URL (without the ``@<ref>`` suffix).

    Returns:
        The derived GITBASE string.

    Raises:
        CatalogSourceURLDerivationError: When no scheme+host can be extracted.
        ValueError: When url is empty or None.
    """
    if not url:
        raise ValueError("catalog-source URL is required for kanon add")

    # SCP-shorthand form: git@host:org/repo(.git)?
    # urllib.parse.urlsplit does not recognise this form, so handle it first.
    scp_match = _SCP_URL_PATTERN.match(url)
    if scp_match:
        host_part = scp_match.group(1)  # e.g. git@github.com
        org_part = scp_match.group(2)  # e.g. my-org
        return f"{host_part}:{org_part}"

    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme:
        raise CatalogSourceURLDerivationError(
            url,
            "URL has no scheme; expected https://, http://, ssh://, git@host:, or file://",
        )

    # file:// URLs have an empty netloc; return scheme:// + parent directory.
    # e.g. file:///tmp/bare-repo.git -> file:///tmp
    if parsed.scheme == "file":
        parent_path = str(pathlib.PurePosixPath(parsed.path).parent)
        return f"{parsed.scheme}://{parsed.netloc}{parent_path}"

    if not parsed.netloc:
        raise CatalogSourceURLDerivationError(
            url,
            f"URL scheme '{parsed.scheme}' has no host/authority component",
        )

    # For https/http/ssh, extract the leading path segment (the org/owner part)
    # before the repository name. The path looks like /org/repo[.git].
    # Strip a leading slash, then take the first segment.
    path_segments = [s for s in parsed.path.split("/") if s]
    if len(path_segments) >= 2:
        # At least org/repo present -- include the org segment.
        org_segment = path_segments[0]
        return f"{parsed.scheme}://{parsed.netloc}/{org_segment}"

    # Only a single path segment (just the repo, no org prefix) or no path.
    return f"{parsed.scheme}://{parsed.netloc}"


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


def _build_source_block_lines(
    source_name: str,
    url: str,
    ref: str,
    path: str,
    name: str,
    gitbase: str,
) -> list[str]:
    """Construct the alias-keyed KANON_SOURCE_<alias>_* block lines.

    Emits the alias-keyed per-dependency block (spec Section 5.1 / FR-5, FR-6):
    ``_URL``, ``_REF`` (the verbatim version spec), ``_PATH``, ``_NAME`` (the
    original catalog manifest name), and ``_GITBASE`` (the org base for
    ``${GITBASE}`` resolution). There is no ``_REVISION`` line and no global
    ``[catalog]`` block.

    Args:
        source_name: The local alias (from ``derive_source_name``).
        url: Manifest repo git URL.
        ref: Verbatim version spec (e.g. ``1.2.0``, ``main``, ``>=1.0,<2.0``).
        path: Repo-relative path to the marketplace XML file.
        name: Original catalog manifest name (the pre-sanitization entry name).
        gitbase: Org base for ``${GITBASE}`` resolution (derived from the URL).

    Returns:
        A list of exactly five strings: URL, REF, PATH, NAME, GITBASE lines.
    """
    prefix = f"{SOURCE_PREFIX}{source_name}"
    # The suffix tokens are written as literals (rather than interpolated from
    # the suffix constants) so this single canonical writer states the on-disk
    # alias-block schema verbatim: _URL, _REF, _PATH, _NAME, _GITBASE.
    return [
        f"{prefix}_URL={url}",
        f"{prefix}_REF={ref}",
        f"{prefix}_PATH={path}",
        f"{prefix}_NAME={name}",
        f"{prefix}_GITBASE={gitbase}",
    ]


def _source_block_key_names(source_name: str) -> str:
    """Return the comma-joined KANON_SOURCE_<alias>_* key names for a summary line.

    Args:
        source_name: The local alias.

    Returns:
        The comma-joined list of every key in the alias-keyed source block, in
        the canonical suffix order from ``SOURCE_SUFFIXES``.
    """
    return ", ".join(f"{SOURCE_PREFIX}{source_name}{suffix}" for suffix in SOURCE_SUFFIXES)


def _append_source_block(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
) -> None:
    """Append the alias-keyed block lines to dest and print a summary to stdout.

    Creates the destination file (and parent directories) when it does not yet
    exist. A blank separator line is written before the block only when the file
    already has content, so a freshly-created ``.kanon`` does not start with a
    leading blank line.

    Args:
        dest: Destination .kanon file path (created if absent).
        source_name: The local alias, used in the stdout summary.
        lines: The KANON_SOURCE_<alias>_* block lines to append.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    needs_separator = dest.exists() and dest.read_text(encoding="utf-8").strip() != ""
    with dest.open("a", encoding="utf-8") as fh:
        if needs_separator:
            fh.write("\n")
        for line in lines:
            fh.write(line + "\n")
    print(f"Wrote {_source_block_key_names(source_name)} to {dest}")


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
    xml_paths = find_catalog_entry_files(manifest_root)
    entries: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
    error_paths: list[str] = []

    for xml_path in sorted(xml_paths):
        try:
            metadata = _parse_catalog_metadata(xml_path)
            entries.append((metadata, xml_path, url))
        except CatalogMetadataParseError as exc:
            # Use the manifest-relative path in all error output so messages
            # are reproducible regardless of the temp clone directory.
            # Canonical fixture: tests/fixtures/errors/missing-required-metadata-field.txt
            # Spec section: spec/kanon-list-add-lock-features-spec.md Section 3.
            rel_path = str(xml_path.relative_to(manifest_root))
            error_paths.append(rel_path)
            error_msg = str(exc).replace(str(xml_path), rel_path)
            print(f"ERROR: {error_msg}", file=sys.stderr)

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
        "Run 'kanon search' to discover available entry names.",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_spec(url: str, spec: str | None) -> str:
    """Resolve the version spec for a catalog entry.

    When spec is None (default-spec path), selects the highest PEP 440-valid
    git tag on the manifest repo via git ls-remote --tags. Raises SystemExit
    with the spec-verbatim error if:

    - The repo has zero tags total (AC-FUNC-002), or
    - The repo has tags but none parse as ``packaging.version.Version``
      (AC-FUNC-003). In this subcase the first up-to-10 skipped tag names
      are printed so the operator can identify the offending tags.

    When spec is a non-empty string, delegates to resolve_version() to
    resolve the PEP 440 constraint against the available tags (AC-FUNC-005).

    Args:
        url: The manifest repo git URL.
        spec: The version spec string (e.g. '==1.0.0', '~=1.2') or None.

    Returns:
        A full tag ref string (e.g. 'refs/tags/1.2.0').
    """
    if spec is None:
        tags = _list_tags(url)
        if not tags:
            # Zero tags total -- emit spec-verbatim error (AC-FUNC-002).
            print(f"ERROR: {_ZERO_PEP440_TAGS_ERROR}", file=sys.stderr)
            sys.exit(1)

        # Check whether at least one tag has a PEP 440-valid last component.
        # Collect skipped names so the loud error can list them (AC-FUNC-003).
        skipped: list[str] = []
        has_pep440 = False
        for tag in tags:
            last = tag.rsplit("/", 1)[-1]
            try:
                Version(last)
                has_pep440 = True
                break
            except InvalidVersion:
                skipped.append(tag)

        if not has_pep440:
            # Zero PEP 440-valid tags -- emit spec-verbatim error plus skipped
            # tag names (first up-to-TAG_ERROR_DISPLAY_CAP, sorted) (AC-FUNC-003).
            sorted_skipped = sorted(skipped)
            display = sorted_skipped[:TAG_ERROR_DISPLAY_CAP]
            lines = [f"ERROR: {_ZERO_PEP440_TAGS_ERROR}", "Skipped non-PEP-440 tags:"]
            for tag_name in display:
                lines.append(f"  - {tag_name}")
            if len(skipped) > TAG_ERROR_DISPLAY_CAP:
                lines.append(f"  ... (showing first {TAG_ERROR_DISPLAY_CAP} of {len(skipped)})")
            print("\n".join(lines), file=sys.stderr)
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
# Collision detection helpers
# ---------------------------------------------------------------------------


def _check_within_request_collisions(entry_names: list[str]) -> None:
    """Detect duplicates within the requested set before any catalog work.

    Normalises each raw entry name (via derive_source_name) and hard-errors
    on the first pair that maps to the same source name token.

    Args:
        entry_names: Raw positional argument strings (names only, no spec).

    Raises:
        SystemExit: When two or more names normalise to the same source name.
    """
    seen: dict[str, str] = {}  # source_name -> first raw name
    for raw in entry_names:
        source = derive_source_name(raw)
        if source in seen:
            first = seen[source]
            print(
                f"ERROR: within-request collision: '{first}' and '{raw}' both "
                f"normalise to source name '{source}'.\n"
                "Remove duplicate entries from your command arguments.",
                file=sys.stderr,
            )
            sys.exit(1)
        seen[source] = raw


def _read_existing_source_block(
    kanon_file: pathlib.Path,
    source_name: str,
) -> tuple[str | None, str | None, str | None]:
    """Read the URL, REF, and PATH values for an existing alias block.

    Scans the destination .kanon file for the alias-keyed block lines
    KANON_SOURCE_<alias>_{URL,REF,PATH}=<value>. The ``_NAME`` and ``_GITBASE``
    lines are not surfaced here because the collision message and the dry-run
    diff report only the source coordinates (URL / REF / PATH); presence of any
    block line is what drives collision detection.

    Args:
        kanon_file: Path to the .kanon file (may not exist).
        source_name: The local alias (output of derive_source_name).

    Returns:
        A 3-tuple (url, ref, path). Each element is the value string if found,
        or None when absent.
    """
    if not kanon_file.exists():
        return None, None, None

    prefix = f"{SOURCE_PREFIX}{source_name}"
    url: str | None = None
    ref: str | None = None
    path: str | None = None

    for raw_line in kanon_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(f"{prefix}{SOURCE_URL_SUFFIX}="):
            url = line[len(f"{prefix}{SOURCE_URL_SUFFIX}=") :]
        elif line.startswith(f"{prefix}{SOURCE_REF_SUFFIX}="):
            ref = line[len(f"{prefix}{SOURCE_REF_SUFFIX}=") :]
        elif line.startswith(f"{prefix}{SOURCE_PATH_SUFFIX}="):
            path = line[len(f"{prefix}{SOURCE_PATH_SUFFIX}=") :]

    return url, ref, path


def _check_against_existing_blocks(
    kanon_file: pathlib.Path,
    source_name: str,
    new_url: str,
    new_ref: str,
    new_path: str,
    force: bool,
) -> None:
    """Detect a collision between the alias and an existing block in the file.

    Per spec Section 4.2 pre-flight paragraph: if the destination .kanon file
    already contains any KANON_SOURCE_<alias>_* line, and --force is not set,
    print the spec-canonical error message and exit non-zero.

    Args:
        kanon_file: Path to the .kanon file (may not exist).
        source_name: The local alias (output of derive_source_name).
        new_url: Requested manifest repo URL.
        new_ref: Requested verbatim ref spec.
        new_path: Requested repo-relative XML path.
        force: When True, collision is permitted (no error).

    Raises:
        SystemExit: When the alias already has a block and force is False.
    """
    if force:
        return

    existing_url, existing_ref, existing_path = _read_existing_source_block(kanon_file, source_name)

    if existing_url is None and existing_ref is None and existing_path is None:
        return

    # At least one line exists -- collision detected.
    print(
        f"ERROR: source alias '{source_name}' already mapped to "
        f"{existing_url}/{existing_path} "
        f"(ref {existing_ref}); requested mapping is "
        f"{new_url}/{new_path} (ref {new_ref}).\n"
        "Use --force to overwrite, or 'kanon remove "
        f"{source_name}' first.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Force-overwrite helper
# ---------------------------------------------------------------------------


def _overwrite_source_block(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
) -> None:
    """Replace the KANON_SOURCE_<alias>_* block lines in dest.

    Reads the entire file, removes any line whose key is one of the alias-keyed
    block keys (every suffix in ``SOURCE_SUFFIXES``), and inserts the new block
    lines in place of the first removed line (preserving order).

    Args:
        dest: Destination .kanon file (must exist and contain the block).
        source_name: The local alias.
        lines: The replacement KANON_SOURCE_<alias>_* block lines.
    """
    prefix = f"{SOURCE_PREFIX}{source_name}"
    block_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}

    existing_lines = dest.read_text(encoding="utf-8").splitlines(keepends=True)
    result: list[str] = []
    inserted = False

    for raw_line in existing_lines:
        stripped = raw_line.rstrip("\n").rstrip("\r")
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in block_keys:
            if not inserted:
                # Insert replacement block at the position of the first matched line.
                for new_line in lines:
                    result.append(new_line + "\n")
                inserted = True
            # Skip old line (replaced above).
        else:
            result.append(raw_line)

    dest.write_text("".join(result), encoding="utf-8")

    print(f"Overwrote {_source_block_key_names(source_name)} in {dest}")


# ---------------------------------------------------------------------------
# Dry-run renderer
# ---------------------------------------------------------------------------


def _existing_block_lines(dest: pathlib.Path, source_name: str) -> list[str]:
    """Return every existing KANON_SOURCE_<alias>_* line in dest, in file order.

    Args:
        dest: Destination .kanon file path (may not exist).
        source_name: The local alias.

    Returns:
        The stripped block lines for the alias in their original file order;
        empty when the file is absent or contains no block lines for the alias.
    """
    if not dest.exists():
        return []
    prefix = f"{SOURCE_PREFIX}{source_name}"
    block_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}
    matched: list[str] = []
    for raw_line in dest.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in block_keys:
            matched.append(stripped)
    return matched


def _render_dry_run_diff(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
    force: bool,
) -> None:
    """Print the diff that WOULD be applied to dest without modifying the file.

    When force is False (no collision expected), each block line is printed with
    a '+' prefix. When force is True and a block already exists, the existing
    block lines appear with a '-' prefix first, then the replacement lines with
    a '+' prefix.

    Args:
        dest: Destination .kanon file path.
        source_name: The local alias.
        lines: The replacement KANON_SOURCE_<alias>_* block lines.
        force: Whether the operation would overwrite an existing block.
    """
    if force:
        old_lines = _existing_block_lines(dest, source_name)
        if old_lines:
            for old_line in old_lines:
                print(f"-{old_line}")
            for new_line in lines:
                print(f"+{new_line}")
            return

    for new_line in lines:
        print(f"+{new_line}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_add(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon add' subcommand.

    Resolves each requested catalog entry, constructs the alias-keyed
    KANON_SOURCE_<alias>_* block lines, and appends (or overwrites) them in the
    destination .kanon file. Creates the file when absent; no standard header is
    written (spec Section 5.1).

    The implementation uses a two-phase approach to satisfy AC-FUNC-004
    (destination .kanon is unchanged after any error):

    - **Resolution phase** (Steps 1-4): all catalog lookups, tag resolution,
      and against-existing collision detection run first. No file writes occur.
    - **Write phase** (Step 5): only after every entry is fully resolved and
      validated does the alias-block append/overwrite execute. There is no
      standard-header write (spec Section 5.1): the per-dependency block carries
      its own ``_GITBASE`` and there is no global ``[catalog]`` /
      ``KANON_MARKETPLACE_INSTALL`` header line.

    When --dry-run is set, prints the diff that would be applied and exits 0
    without modifying any file.

    When --force is set, an existing KANON_SOURCE_<alias>_* block is
    overwritten rather than treated as a hard error.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure (typically via sys.exit()).
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or resolve_env_catalog_source()
    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="add"),
            file=sys.stderr,
        )
        sys.exit(1)

    kanon_file = pathlib.Path(getattr(args, "kanon_file", KANON_KANON_FILE_DEFAULT))
    force: bool = getattr(args, "force", False)
    dry_run: bool = getattr(args, "dry_run", False)

    # Validate that a GITBASE org base is derivable from the catalog-source URL
    # early (before any file writes) so a malformed URL fails fast before cloning
    # the manifest repo. The per-dependency _GITBASE written into each block is
    # derived from that dependency's own entry URL in the resolution loop below.
    # The catalog_source has the form <url>@<ref>; strip the trailing @<ref> to
    # obtain the bare URL for the early derivation guard.
    catalog_source_url = catalog_source[: catalog_source.rfind("@")] if "@" in catalog_source else catalog_source
    try:
        _derive_gitbase_from_catalog_source(catalog_source_url)
    except CatalogSourceURLDerivationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Pre-flight: within-request collision detection (before any catalog work).
    raw_names = [_split_name_spec(raw)[0] for raw in args.entries]
    _check_within_request_collisions(raw_names)

    # Step 1: Resolve manifest repo.
    manifest_root, url, _ref = _resolve_manifest_repo_for_add(catalog_source)

    # Step 2: Build entry catalog (hard-errors on soft-spot rule 1 / 3 violations).
    catalog = _build_entry_catalog(manifest_root, url)

    # Step 3-4: Resolution phase -- resolve every entry and run against-existing
    # collision detection BEFORE any file write. This ensures that if any entry
    # fails (e.g. zero PEP 440-valid tags, unknown entry name, collision), the
    # destination .kanon file is not modified at all (AC-FUNC-004).
    resolved_entries: list[tuple[str, str, list[str]]] = []
    for raw_entry in args.entries:
        name, spec = _split_name_spec(raw_entry)

        metadata, xml_path, entry_url = _find_entry_by_name(name, catalog)

        resolved_revision = _resolve_spec(entry_url, spec)

        source_name = derive_source_name(metadata.name)

        rel_path = _xml_repo_relative_path(manifest_root, xml_path)

        # Per-dependency GITBASE org base, derived from this entry's own URL
        # (spec Section 5.1). Failure to derive fails fast (no silent default).
        try:
            entry_gitbase = _derive_gitbase_from_catalog_source(entry_url)
        except CatalogSourceURLDerivationError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        lines = _build_source_block_lines(
            source_name=source_name,
            url=entry_url,
            ref=resolved_revision,
            path=rel_path,
            name=metadata.name,
            gitbase=entry_gitbase,
        )

        # Against-existing collision detection (runs for both normal and dry-run paths).
        # Use the user's original version spec in the collision message so the
        # error shows intent (e.g. "==2.0.0") rather than the resolved git ref
        # (e.g. "refs/tags/v2.0.0").  When the user gave no explicit spec
        # (spec is None), the resolved_revision is the auto-selected latest
        # version and is the most informative value to display.
        # Canonical fixture: tests/fixtures/errors/source-collision.txt.
        # Spec section: spec/kanon-list-add-lock-features-spec.md Section 4.0.
        _check_against_existing_blocks(
            kanon_file=kanon_file,
            source_name=source_name,
            new_url=entry_url,
            new_ref=spec if spec is not None else resolved_revision,
            new_path=rel_path,
            force=force,
        )

        resolved_entries.append((source_name, rel_path, lines))

    # Step 5: Write phase -- all entries resolved successfully; now write to disk.
    # For --dry-run: print diffs without any file modification (no lock needed).
    # For normal runs: acquire the workspace lock, then append/overwrite each
    # alias block in argument order. No standard-header is written (spec Section
    # 5.1): _append_source_block creates the file when absent.
    if dry_run:
        for source_name, _rel_path, lines in resolved_entries:
            _render_dry_run_diff(
                dest=kanon_file,
                source_name=source_name,
                lines=lines,
                force=force,
            )
        return 0

    # Normal (non-dry-run) write path: acquire the workspace exclusive lock
    # before any file write so a concurrent kanon install cannot read a
    # half-written .kanon file.
    workspace_root = kanon_file.resolve().parent
    with kanon_workspace_lock(workspace_root):
        for source_name, _rel_path, lines in resolved_entries:
            if force and kanon_file.exists():
                # Check whether an existing block is present; if so, overwrite it.
                existing_url, _, _ = _read_existing_source_block(kanon_file, source_name)
                if existing_url is not None:
                    _overwrite_source_block(
                        dest=kanon_file,
                        source_name=source_name,
                        lines=lines,
                    )
                else:
                    _append_source_block(
                        dest=kanon_file,
                        source_name=source_name,
                        lines=lines,
                    )
            else:
                _append_source_block(
                    dest=kanon_file,
                    source_name=source_name,
                    lines=lines,
                )

    return 0
