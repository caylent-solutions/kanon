"""kanon outdated subcommand: compare installed sources against catalog versions.

Reads the .kanon file, resolves the catalog, and emits one row per
KANON_SOURCE_<name>_* block containing:

  name | current | latest-matching-spec | latest-available | upgrade-type

The ``current`` column is taken from the lockfile when present (the locked
resolved_ref), or live-resolved against the catalog when no lockfile exists.

Three REVISION shapes are handled (see ``kanon_cli.version.RevisionShape``):

- **Tag-pinned** (PEP 440 constraint or ``refs/tags/...``): ``latest-matching-spec``
  is the highest ref satisfying the constraint; ``latest-available`` is the
  highest ref under the prefix. ``upgrade-type`` is one of ``none``, ``patch``,
  ``minor``, ``major``, or ``prerelease``.
- **Branch-pinned** (plain branch name such as ``main``, ``develop``,
  ``feature/foo``): both ``latest-matching-spec`` and ``latest-available`` are
  the branch HEAD SHA truncated to 12 hex characters. ``upgrade-type`` is
  ``drift`` when the locked SHA differs from the branch HEAD, or ``none``
  otherwise.
- **SHA-pinned** (40 or 64 hex chars): all three columns show the same truncated
  SHA; ``upgrade-type`` is always ``none`` (a pinned SHA cannot drift).

Spec reference:
  ``spec/kanon-list-add-lock-features-spec.md`` Section 4.4
  and Section 7 (``KANON_OUTDATED_FORMAT``, ``--catalog-source``,
  ``--kanon-file``, ``--lock-file``, ``--format`` flags).
"""

import argparse
import json
import os
import pathlib
import sys
from dataclasses import dataclass

from packaging.version import Version

from kanon_cli.constants import (
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    KANON_OUTDATED_FORMAT,
    KANON_OUTDATED_FORMAT_DEFAULT,
    KANON_OUTDATED_FORMAT_JSON,
    KANON_OUTDATED_JSON_INDENT,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.core.catalog import _parse_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.core.lockfile import read_lockfile
from kanon_cli.version import (
    RevisionShape,
    _classify_revision_shape,
    _list_branch_head,
    _list_tags,
    _resolve_constraint_from_tags,
    _truncate_sha,
)


# ---------------------------------------------------------------------------
# Public dataclass -- the typed row returned by _build_row
# ---------------------------------------------------------------------------


@dataclass
class OutdatedRow:
    """One row in the 'kanon outdated' table output.

    Attributes:
        name: The KANON_SOURCE_<name> key (lowercased from the env-var name).
        current: The version string for the currently installed ref (from
            lockfile when present, or live-resolved).
        latest_matching_spec: The highest available version satisfying the
            source's REVISION constraint.
        latest_available: The highest available version under the prefix,
            ignoring the REVISION constraint (equivalent to ``*``).
        upgrade_type: One of ``none``, ``patch``, ``minor``, ``major``,
            or ``prerelease``.
    """

    name: str
    current: str
    latest_matching_spec: str
    latest_available: str
    upgrade_type: str


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_version_from_ref(ref: str) -> str:
    """Return the version string from the last path component of a git ref.

    For example, ``refs/tags/1.0.1`` returns ``1.0.1``.

    Args:
        ref: A full tag ref such as ``refs/tags/1.0.1`` or a bare version
            string such as ``1.0.1``.

    Returns:
        The last path component of ``ref``.
    """
    return ref.rsplit("/", 1)[-1]


def _compute_upgrade_type(current: str, latest_matching: str) -> str:
    """Derive the upgrade category by comparing two version strings.

    Uses ``packaging.version.Version`` for PEP 440 comparison. The rules are:

    1. If the versions are equal, returns ``none``.
    2. If ``latest_matching`` is a pre-release (``a``, ``b``, ``rc``, ``dev``
       segment), returns ``prerelease``.
    3. If the major components differ, returns ``major``.
    4. If the minor components differ, returns ``minor``.
    5. Otherwise, returns ``patch``.

    Args:
        current: Version string for the currently installed ref.
        latest_matching: Version string for the latest ref satisfying the spec.

    Returns:
        One of ``none``, ``prerelease``, ``major``, ``minor``, or ``patch``.

    Raises:
        ValueError: If either version string is not valid PEP 440.
    """
    cur = Version(current)
    lat = Version(latest_matching)

    if cur == lat:
        return "none"

    if lat.is_prerelease:
        return "prerelease"

    if lat.major != cur.major:
        return "major"

    if lat.minor != cur.minor:
        return "minor"

    return "patch"


def _build_row(
    *,
    name: str,
    source: dict[str, str],
    available_tags: list[str],
    lock_ref: str | None,
) -> OutdatedRow:
    """Construct one OutdatedRow for a single source.

    Dispatches to the correct column-building strategy based on the shape of
    the source's REVISION string (see ``kanon_cli.version.RevisionShape``):

    - **Tag-pinned**: uses PEP 440 tag resolution against ``available_tags``.
    - **Branch-pinned**: queries branch HEAD via ``git ls-remote refs/heads/<branch>``;
      both ``latest-*`` columns show the 12-char truncated HEAD SHA.
      ``upgrade-type`` is ``drift`` when the locked SHA differs from HEAD.
    - **SHA-pinned**: all three columns show the same 12-char truncated SHA;
      ``upgrade-type`` is always ``none``.

    Args:
        name: The source name (e.g. ``FOO``).
        source: The source dict from ``parse_kanonenv`` with keys ``url``,
            ``revision``, and ``path``.
        available_tags: Full list of tag refs fetched from the source's git URL.
            Used only for tag-pinned sources; ignored for branch- and SHA-pinned.
        lock_ref: The resolved_ref stored in the lockfile for this source, or
            ``None`` when no lockfile is present.

    Returns:
        A populated :class:`OutdatedRow`.

    Raises:
        ValueError: If the version constraint is invalid, if zero PEP 440-
            parseable tags exist under the source prefix (loud error from
            ``_resolve_constraint_from_tags``), or if no tags match the
            constraint.
        ValueError: If the branch ref is not found on the remote (branch-pinned).
        RuntimeError: If the ``git`` binary is not found or ``git ls-remote``
            exits with a non-zero return code (branch-pinned path).
    """
    revision = source["revision"]
    url = source["url"]
    shape = _classify_revision_shape(revision)

    if shape is RevisionShape.SHA:
        return _build_row_sha_pinned(name=name, revision=revision, lock_ref=lock_ref)

    if shape is RevisionShape.BRANCH:
        return _build_row_branch_pinned(name=name, url=url, branch=revision, lock_ref=lock_ref)

    # Tag-pinned (default T1 path)
    return _build_row_tag_pinned(
        name=name,
        revision=revision,
        available_tags=available_tags,
        lock_ref=lock_ref,
    )


def _build_row_tag_pinned(
    *,
    name: str,
    revision: str,
    available_tags: list[str],
    lock_ref: str | None,
) -> OutdatedRow:
    """Build an OutdatedRow for a tag-pinned source using PEP 440 resolution.

    This is the original T1 implementation, extracted to a dedicated helper so
    the branch-pinned and SHA-pinned paths can be added cleanly.

    Args:
        name: Source name.
        revision: The REVISION string (PEP 440 constraint or ``refs/tags/...``).
        available_tags: Pre-fetched list of tag refs from the source's remote.
        lock_ref: Locked ref from the lockfile, or ``None``.

    Returns:
        A populated :class:`OutdatedRow`.
    """
    # latest-matching-spec: highest ref satisfying the source's REVISION constraint
    latest_matching_ref = _resolve_constraint_from_tags(revision, available_tags)
    latest_matching_ver = _extract_version_from_ref(latest_matching_ref)

    # latest-available: highest ref under the prefix ignoring the constraint (wildcard)
    # Build a wildcard constraint by replacing the last path component with "*"
    if "/" in revision:
        prefix_parts = revision.rsplit("/", 1)[0]
        wildcard_revision = prefix_parts + "/*"
    else:
        wildcard_revision = "*"

    latest_available_ref = _resolve_constraint_from_tags(wildcard_revision, available_tags)
    latest_available_ver = _extract_version_from_ref(latest_available_ref)

    # current: from lockfile when present, else live-resolve against the constraint
    if lock_ref is not None:
        current_ver = _extract_version_from_ref(lock_ref)
    else:
        current_ref = _resolve_constraint_from_tags(revision, available_tags)
        current_ver = _extract_version_from_ref(current_ref)

    upgrade_type = _compute_upgrade_type(current_ver, latest_matching_ver)

    return OutdatedRow(
        name=name,
        current=current_ver,
        latest_matching_spec=latest_matching_ver,
        latest_available=latest_available_ver,
        upgrade_type=upgrade_type,
    )


def _build_row_branch_pinned(
    *,
    name: str,
    url: str,
    branch: str,
    lock_ref: str | None,
) -> OutdatedRow:
    """Build an OutdatedRow for a branch-pinned source.

    Queries the branch HEAD SHA via ``git ls-remote refs/heads/<branch>``,
    truncates to 12 hex chars, and compares with the locked SHA (if any) to
    derive the ``upgrade-type``.

    Per spec Section 4.4: both ``latest-matching-spec`` and ``latest-available``
    show the same truncated branch HEAD SHA (no cross-branch latest-available).

    Args:
        name: Source name.
        url: Git repository URL.
        branch: Branch name (without ``refs/heads/`` prefix).
        lock_ref: Locked resolved_ref from the lockfile, or ``None``.

    Returns:
        A populated :class:`OutdatedRow`.
    """
    head_sha = _list_branch_head(url, branch)
    head_sha_12 = _truncate_sha(head_sha)

    if lock_ref is not None:
        # Locked SHA may be a full 40-char SHA or a short form; compare prefix
        locked_sha_12 = _truncate_sha(lock_ref)
        upgrade_type = "drift" if locked_sha_12 != head_sha_12 else "none"
        current = locked_sha_12
    else:
        # No lockfile: live-resolve equals HEAD; no drift possible
        current = head_sha_12
        upgrade_type = "none"

    return OutdatedRow(
        name=name,
        current=current,
        latest_matching_spec=head_sha_12,
        latest_available=head_sha_12,
        upgrade_type=upgrade_type,
    )


def _build_row_sha_pinned(
    *,
    name: str,
    revision: str,
    lock_ref: str | None,
) -> OutdatedRow:
    """Build an OutdatedRow for a SHA-pinned source.

    A pinned SHA cannot drift: the operator explicitly pinned to that exact
    commit. All three columns (``current``, ``latest-matching-spec``,
    ``latest-available``) display the 12-char truncation of the revision SHA.
    ``upgrade-type`` is always ``none``.

    Per spec Section 4.4: no network call is needed for SHA-pinned sources.

    Args:
        name: Source name.
        revision: The full hexadecimal SHA from REVISION (40 or 64 chars).
        lock_ref: Locked ref from the lockfile (ignored; revision SHA is used
            for all columns since it is already an exact commit reference).

    Returns:
        A populated :class:`OutdatedRow`.
    """
    sha_12 = _truncate_sha(revision)

    return OutdatedRow(
        name=name,
        current=sha_12,
        latest_matching_spec=sha_12,
        latest_available=sha_12,
        upgrade_type="none",
    )


def _format_table(rows: list[OutdatedRow]) -> str:
    """Format OutdatedRow list as a fixed-width ASCII table.

    Columns are: ``name``, ``current``, ``latest-matching-spec``,
    ``latest-available``, ``upgrade-type``. Column widths are computed from
    the widest value (including header) in each column so the output is
    deterministic regardless of content.

    Args:
        rows: The rows to format.

    Returns:
        A multi-line string with a header row, a separator line, and one
        data row per entry. Ends with a trailing newline.
    """
    headers = ["name", "current", "latest-matching-spec", "latest-available", "upgrade-type"]

    # Map rows to tuples of string cells in display order
    cells = [(row.name, row.current, row.latest_matching_spec, row.latest_available, row.upgrade_type) for row in rows]

    # Compute column widths from header and data
    col_widths = [len(h) for h in headers]
    for row_cells in cells:
        for i, cell in enumerate(row_cells):
            col_widths[i] = max(col_widths[i], len(cell))

    def _fmt_row(values: tuple[str, ...]) -> str:
        return " | ".join(v.ljust(col_widths[i]) for i, v in enumerate(values))

    lines: list[str] = []
    lines.append(_fmt_row(tuple(headers)))
    lines.append("-+-".join("-" * w for w in col_widths))
    for row_cells in cells:
        lines.append(_fmt_row(row_cells))

    return "\n".join(lines) + "\n"


def _row_to_dict(row: OutdatedRow) -> dict[str, str]:
    """Convert an OutdatedRow to a JSON-ready dict with spec-canonical hyphenated keys.

    The five keys produced match the table column headers exactly:
    ``name``, ``current``, ``latest-matching-spec``, ``latest-available``,
    ``upgrade-type``.

    Args:
        row: A populated :class:`OutdatedRow`.

    Returns:
        A dict with exactly five string keys and string values.
    """
    return {
        "name": row.name,
        "current": row.current,
        "latest-matching-spec": row.latest_matching_spec,
        "latest-available": row.latest_available,
        "upgrade-type": row.upgrade_type,
    }


def _build_outdated_payload(rows: list[OutdatedRow]) -> list[dict]:
    """Build the JSON-serialisable payload for a list of :class:`OutdatedRow`.

    Returns a list of dicts, one per source, each with exactly five keys
    matching the table column headers: ``name``, ``current``,
    ``latest-matching-spec``, ``latest-available``, ``upgrade-type``.

    Args:
        rows: The rows to convert.

    Returns:
        A list of dicts ready for JSON serialisation.
    """
    return [_row_to_dict(row) for row in rows]


def _format_json(rows: list[OutdatedRow]) -> str:
    """Format OutdatedRow list as a JSON array with one object per source.

    The JSON shape mirrors the table row-for-row: a top-level array; one object
    per source; each object has exactly five keys matching the table column
    headers: ``name``, ``current``, ``latest-matching-spec``,
    ``latest-available``, ``upgrade-type``.

    Output uses ``sort_keys=False`` to preserve insertion order and is
    pretty-printed with ``KANON_OUTDATED_JSON_INDENT`` spaces of indentation
    (default 2). A trailing newline is appended for POSIX-tool friendliness.

    Kept for backward compatibility with callers that need the serialised
    string directly (e.g. unit tests).  The :func:`run` handler calls
    :func:`_emit_json_payload` via :func:`_build_outdated_payload` directly.

    Args:
        rows: The rows to format.

    Returns:
        A JSON string ending with a trailing newline.
    """
    return json.dumps(_build_outdated_payload(rows), sort_keys=False, indent=KANON_OUTDATED_JSON_INDENT) + "\n"


def _derive_lock_file_path(kanon_file: str) -> pathlib.Path:
    """Derive the default lockfile path from the .kanon file path.

    Convention: lockfile is the .kanon file with ``.lock`` appended.
    For example, ``./.kanon`` -> ``./.kanon.lock``.

    Args:
        kanon_file: Path to the .kanon file (str).

    Returns:
        Derived lockfile path as a :class:`pathlib.Path`.
    """
    return pathlib.Path(kanon_file + ".lock")


def _resolve_lock_ref(name: str, lock_file_path: pathlib.Path | None) -> str | None:
    """Look up the resolved_ref for ``name`` in the lockfile, if the file exists.

    Returns ``None`` when the lockfile is absent (optional for ``outdated``),
    when the lockfile contains no entry for ``name``, or when ``lock_file_path``
    is ``None``.

    Used for tag-pinned sources where the ``resolved_ref`` is a full tag ref
    (e.g. ``refs/tags/1.0.0``) from which the version string is extracted.

    Args:
        name: Source name (case-sensitive, matches SourceEntry.name).
        lock_file_path: Lockfile path, or ``None`` if no ``--lock-file`` was
            passed and the derived default does not exist.

    Returns:
        The ``resolved_ref`` string from the matching SourceEntry, or ``None``.
    """
    if lock_file_path is None or not lock_file_path.exists():
        return None

    lockfile = read_lockfile(lock_file_path)
    for entry in lockfile.sources:
        if entry.name == name:
            return entry.resolved_ref
    return None


def _resolve_lock_sha(name: str, lock_file_path: pathlib.Path | None) -> str | None:
    """Look up the resolved_sha for ``name`` in the lockfile, if the file exists.

    Returns the full commit SHA stored in the lockfile's ``resolved_sha`` field
    for the named source. Used for branch-pinned sources where the locked value
    to compare against the branch HEAD is the commit SHA, not the ref name.

    Returns ``None`` when the lockfile is absent, when the lockfile contains no
    entry for ``name``, or when ``lock_file_path`` is ``None``.

    Args:
        name: Source name (case-sensitive, matches SourceEntry.name).
        lock_file_path: Lockfile path, or ``None`` if the default derived path
            does not exist.

    Returns:
        The ``resolved_sha`` string from the matching SourceEntry, or ``None``.
    """
    if lock_file_path is None or not lock_file_path.exists():
        return None

    lockfile = read_lockfile(lock_file_path)
    for entry in lockfile.sources:
        if entry.name == name:
            return entry.resolved_sha
    return None


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'outdated' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "outdated",
        add_help=True,
        help="Show which installed sources are behind the catalog.",
        description=(
            "Compare each KANON_SOURCE_<name>_* block in the .kanon file against\n"
            "the catalog and emit a table of:\n\n"
            "  name | current | latest-matching-spec | latest-available | upgrade-type\n\n"
            "The 'current' column is taken from the lockfile when present, or\n"
            "live-resolved against the catalog when absent.\n\n"
            "Exit code is always 0 unless --fail-on-upgrade is set, in which\n"
            "case the command exits 1 when any source has an available upgrade.\n\n"
            "Catalog source precedence: --catalog-source flag, then\n"
            "KANON_CATALOG_SOURCE env var. Both being absent is a hard error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    add_catalog_source_arg(parser)

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT),
        metavar="<path>",
        help=(
            f"Path to the .kanon file. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--lock-file",
        dest="lock_file",
        default=os.environ.get(KANON_LOCK_FILE),
        metavar="<path>",
        help=(
            "Path to the .kanon.lock file. "
            "When present, provides the current resolved SHA. "
            "When absent, the command live-resolves against the catalog. "
            f"Defaults to <kanon-file>.lock. "
            f"Overridden by the {KANON_LOCK_FILE} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--fail-on-upgrade",
        dest="fail_on_upgrade",
        action="store_true",
        default=False,
        help=(
            "Exit 1 when ANY source has an available upgrade (upgrade-type != 'none'). "
            "Default is to always exit 0 (parity with pip list --outdated, npm outdated, "
            "cargo outdated). Use this flag in CI pipelines to gate on lockfile freshness: "
            "the build fails when any source is upgradable, prompting the operator to "
            "refresh the lockfile. "
            "Spec reference: spec/kanon-list-add-lock-features-spec.md Section 0.2 and "
            "Section 4.4 'Exit code'."
        ),
    )

    parser.add_argument(
        "--format",
        dest="format",
        default=os.environ.get(KANON_OUTDATED_FORMAT, KANON_OUTDATED_FORMAT_DEFAULT),
        choices=(KANON_OUTDATED_FORMAT_DEFAULT, KANON_OUTDATED_FORMAT_JSON),
        metavar="<format>",
        help=(
            "Output format: 'table' (default) or 'json'. "
            "The 'json' format emits a top-level array of objects, one per source, "
            "with keys: name, current, latest-matching-spec, latest-available, upgrade-type. "
            f"Overridden by the {KANON_OUTDATED_FORMAT} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.set_defaults(func=run)


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Execute the 'kanon outdated' command.

    Reads the .kanon file, resolves the catalog, and emits one row per
    KANON_SOURCE_<name>_* block to stdout.

    Args:
        args: Parsed argparse namespace. Expected attributes:
            - ``catalog_source`` (str | None): catalog source string.
            - ``kanon_file`` (str): path to the .kanon file.
            - ``lock_file`` (str | None): path to the lockfile, or None.
            - ``format`` (str): output format -- ``"table"`` or ``"json"``.
            - ``fail_on_upgrade`` (bool): when True, exit 1 if any row has
              an upgrade-type other than ``none``.

    Returns:
        0 when all rows have upgrade-type ``none``, or when ``fail_on_upgrade``
        is False (the default). 1 when ``fail_on_upgrade`` is True and at least
        one row has an upgrade-type other than ``none``.
    """
    # -- Validate catalog source (AC-FUNC-009) --
    if not args.catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="kanon outdated"),
            file=sys.stderr,
            end="",
        )
        sys.exit(1)

    # -- Validate .kanon file existence (AC-FUNC-010) --
    kanon_path = pathlib.Path(args.kanon_file)
    if not kanon_path.exists():
        print(
            f"ERROR: .kanon file not found: {kanon_path}\n"
            f"Provide a valid path via --kanon-file or the {KANON_KANON_FILE_ENV} env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Parse .kanon file --
    kanonenv = parse_kanonenv(kanon_path)

    # -- Validate catalog source format (raises hard error on malformed input) --
    try:
        _parse_catalog_source(args.catalog_source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # -- Determine lockfile path --
    if args.lock_file is not None:
        lock_file_path: pathlib.Path | None = pathlib.Path(args.lock_file)
    else:
        derived = _derive_lock_file_path(args.kanon_file)
        lock_file_path = derived if derived.exists() else None

    # -- Build rows for each source --
    rows: list[OutdatedRow] = []
    for name in kanonenv["KANON_SOURCES"]:
        source = kanonenv["sources"][name]
        url = source["url"]
        revision = source["revision"]

        # Fetch tags only for tag-pinned sources; branch- and SHA-pinned sources
        # do not use the tag list so fetching it would be a wasted network call.
        shape = _classify_revision_shape(revision)
        if shape is RevisionShape.TAG:
            available_tags = _list_tags(url)
        else:
            available_tags = []

        # For branch-pinned sources, the locked value is the commit SHA (resolved_sha),
        # not the ref name (resolved_ref). For tag-pinned sources, the ref name is used.
        if shape is RevisionShape.BRANCH:
            lock_ref = _resolve_lock_sha(name, lock_file_path)
        else:
            lock_ref = _resolve_lock_ref(name, lock_file_path)

        try:
            row = _build_row(
                name=name,
                source={"url": url, "revision": revision, "path": source["path"]},
                available_tags=available_tags,
                lock_ref=lock_ref,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        rows.append(row)

    # -- Emit output --
    if args.format == KANON_OUTDATED_FORMAT_JSON:
        from kanon_cli.cli import _emit_json_payload

        _emit_json_payload(_build_outdated_payload(rows), sort_keys=False, indent=KANON_OUTDATED_JSON_INDENT)
    else:
        print(_format_table(rows), end="")

    # -- Exit code gate (AC-FUNC-002 / AC-FUNC-004) --
    if args.fail_on_upgrade and any(row.upgrade_type != "none" for row in rows):
        return 1
    return 0
