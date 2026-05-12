"""kanon remove subcommand: strip dependency triples from a .kanon file.

Accepts one or more names (each may be the canonical source name such as
``foo_bar`` or the original entry name such as ``Foo-Bar``); normalises each
via :func:`derive_source_name` before lookup; and removes the three
``KANON_SOURCE_<normalized>_{URL,REVISION,PATH}`` lines wherever they appear
in the file (they need not be contiguous).

Atomicity guarantee: the file is only written when ALL requested names are
validated successfully. If any name fails the fewer-than-three-keys check the
command exits non-zero and the file is unchanged.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.3 (argument table; Behaviour steps 1-3).
"""

import argparse
import os
import pathlib
import sys

from kanon_cli.constants import (
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
)
from kanon_cli.core.metadata import derive_source_name


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'remove' subcommand on the top-level argparse subparsers.

    Accepts both the canonical source name (e.g. ``foo_bar``) and the
    original entry name (e.g. ``Foo-Bar``); both forms are normalised via
    :func:`derive_source_name` before lookup. Removal is atomic: if any
    requested name is not fully present (fewer than three matching keys)
    the command exits non-zero and the file is unchanged.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "remove",
        help="Remove one or more source-name dependency triples from the .kanon file.",
        description=(
            "Remove the three KANON_SOURCE_<name>_{URL,REVISION,PATH} lines for one\n"
            "or more entries from the .kanon file.\n\n"
            "Each <name> may be EITHER the canonical source name (e.g. foo_bar) OR\n"
            "the original entry name (e.g. Foo-Bar); both are normalised via\n"
            "derive_source_name() before lookup.\n\n"
            "Atomicity rule: if ANY requested name is not fully present (fewer than\n"
            "three matching keys), the command exits non-zero and the file is NOT\n"
            "modified. Either every requested removal succeeds or nothing changes.\n\n"
            f"The --kanon-file path defaults to '{KANON_KANON_FILE_DEFAULT}' and may be overridden by\n"
            f"the {KANON_KANON_FILE_ENV} environment variable (CLI flag takes\n"
            "precedence when both are set)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "names",
        metavar="<name>",
        nargs="+",
        help=(
            "One or more source names to remove. Each may be the canonical source\n"
            "name (e.g. foo_bar) or the original entry name (e.g. Foo-Bar); both\n"
            "forms normalise to the same KANON_SOURCE_<name>_* keys."
        ),
    )

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT),
        metavar="<path>",
        help=(
            f"Path to the .kanon file to modify. "
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
        help=("Reserved for future use (catalog-membership cross-check). Currently accepted and ignored."),
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Preview mode: when implemented, prints the keys that would be removed "
            "without modifying the file. Currently accepted for forward compatibility; "
            "no preview output is produced."
        ),
    )

    parser.set_defaults(func=run_remove)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _scan_source_lines(lines: list[str], normalized: str) -> set[int]:
    """Return the set of line indices that match KANON_SOURCE_<normalized>_* keys.

    Only recognises the three canonical suffixes: ``_URL``, ``_REVISION``,
    and ``_PATH``. Comment lines (stripped content starting with ``#``) are
    ignored even if they contain the prefix string.

    Args:
        lines: All lines of the .kanon file (with newline characters retained).
        normalized: The normalised source name token (e.g. ``foo_bar``).

    Returns:
        A set of zero-based line indices for the matching lines.
    """
    prefix = f"KANON_SOURCE_{normalized}_"
    target_keys = {
        f"{prefix}URL",
        f"{prefix}REVISION",
        f"{prefix}PATH",
    }
    matched: set[int] = set()
    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in target_keys:
            matched.add(idx)
    return matched


def _collect_removal_lines(
    lines: list[str],
    normalized: str,
    input_name: str,
) -> set[int]:
    """Validate that exactly three matching lines exist and return their indices.

    Delegates scanning to :func:`_scan_source_lines`. Hard-errors with the
    spec-canonical message if fewer than three keys are found.

    Args:
        lines: All lines of the .kanon file.
        normalized: The normalised source name token (e.g. ``foo_bar``).
        input_name: The original user-supplied name (used in error messages).

    Returns:
        A set of exactly three line indices to remove.

    Raises:
        SystemExit: When fewer than three matching keys are found.
    """
    matched = _scan_source_lines(lines, normalized)
    found = len(matched)
    if found < 3:
        print(
            f"ERROR: source '{input_name}' (normalized form '{normalized}') "
            f"not fully present in .kanon; "
            f"found {found} of 3 expected KANON_SOURCE_{normalized}_* keys",
            file=sys.stderr,
        )
        sys.exit(1)
    return matched


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_remove(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon remove' subcommand.

    Reads the .kanon file, validates that all requested source names are fully
    present (three matching keys each), then writes the file back with the
    matching lines removed. Atomicity: the file is only written after all
    validations succeed.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; exits non-zero on any validation failure.
    """
    kanon_file = pathlib.Path(getattr(args, "kanon_file", KANON_KANON_FILE_DEFAULT))

    if not kanon_file.exists():
        print(
            f"ERROR: no .kanon file at {kanon_file}; nothing to remove",
            file=sys.stderr,
        )
        sys.exit(1)

    raw_text = kanon_file.read_text()
    lines = raw_text.splitlines(keepends=True)

    # Validate ALL names first (atomicity pre-flight).
    removal_plan: list[tuple[str, str, set[int]]] = []
    for input_name in args.names:
        normalized = derive_source_name(input_name)
        # _collect_removal_lines calls sys.exit on failure -- no write occurs.
        indices = _collect_removal_lines(lines, normalized, input_name)
        removal_plan.append((input_name, normalized, indices))

    # Build the combined set of line indices to remove across all sources.
    all_removal_indices: set[int] = set()
    for _input_name, _normalized, indices in removal_plan:
        all_removal_indices |= indices

    # Write back with matching lines removed.
    kept_lines = [line for idx, line in enumerate(lines) if idx not in all_removal_indices]
    kanon_file.write_text("".join(kept_lines))

    # Emit one summary line per removed source.
    for _input_name, normalized, _indices in removal_plan:
        key_names = f"KANON_SOURCE_{normalized}_URL, KANON_SOURCE_{normalized}_REVISION, KANON_SOURCE_{normalized}_PATH"
        print(f"Removed {key_names} from {kanon_file}")

    return 0
