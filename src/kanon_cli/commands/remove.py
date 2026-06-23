"""kanon remove subcommand: strip alias-keyed dependency blocks from a .kanon file.

Accepts one or more aliases (each may be the canonical alias such as
``foo_bar`` or the original entry name such as ``Foo-Bar``); normalises each
via :func:`derive_source_name` before lookup; and removes every alias-keyed
``KANON_SOURCE_<alias>_*`` line of the block (``_URL``, ``_REF``, ``_PATH``,
``_NAME``, ``_GITBASE``) wherever they appear in the file (they need not be
contiguous).

Atomicity guarantee: the file is only written when ALL requested aliases are
validated successfully. If any alias is not fully present (fewer than the
expected number of block keys) the command exits non-zero and the file is
unchanged.

File-writing rules (spec Section 4.3 Behaviour step 4):

1. **Line-ending preservation.** The dominant line ending in the source file
   (``\\n`` vs ``\\r\\n``) is preserved on write. A file with exactly equal
   counts of each (tie) or a genuinely mixed file is normalised to ``\\n``
   and a single-line warning is emitted to stderr.
2. **Blank-run collapse.** Runs of three or more consecutive blank lines
   collapse to exactly two blank lines. Runs of one or two blank lines are
   preserved as-is.
3. **Trailing newline.** The output always ends with exactly one ``\\n`` (or
   ``\\r\\n`` when dominant). Multiple trailing blank lines collapse to a
   single trailing newline.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.3 (argument table; Behaviour steps 1-4).
"""

import argparse
import os
import pathlib
import sys

from kanon_cli.constants import (
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    SOURCE_PREFIX,
    SOURCE_SUFFIXES,
)
from kanon_cli.core.metadata import derive_source_name
from kanon_cli.utils.concurrency import kanon_workspace_lock


# ---------------------------------------------------------------------------
# Module-level private constants
# ---------------------------------------------------------------------------

# Maximum number of consecutive blank lines preserved after blank-run collapse.
# Runs of more than this threshold are collapsed down to this value.
_BLANK_RUN_MAX_PRESERVED = 2


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
        add_help=True,
        help="Remove one or more alias-keyed dependency blocks from the .kanon file.",
        description=(
            "Remove the KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE} block for\n"
            "one or more entries from the .kanon file.\n\n"
            "Each <name> may be EITHER the canonical alias (e.g. foo_bar) OR\n"
            "the original entry name (e.g. Foo-Bar); both are normalised via\n"
            "derive_source_name() before lookup.\n\n"
            "Atomicity rule: if ANY requested alias is not fully present (fewer than\n"
            "the expected number of block keys), the command exits non-zero and the\n"
            "file is NOT modified. Either every requested removal succeeds or\n"
            "nothing changes.\n\n"
            f"The --kanon-file path defaults to '{KANON_KANON_FILE_DEFAULT}' and may be overridden by\n"
            f"the {KANON_KANON_FILE_ENV} environment variable (CLI flag takes\n"
            "precedence when both are set).\n\n"
            "File-writing rules (applied on non-dry-run writes):\n"
            "  - Line-ending preservation: the dominant ending (LF or CRLF) in the\n"
            "    source file is used on write. Mixed files are normalised to LF with\n"
            "    a stderr warning.\n"
            "  - Blank-run collapse: runs of 3 or more consecutive blank lines\n"
            "    collapse to exactly 2 blank lines.\n"
            "  - Trailing newline: the output always ends with exactly one newline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "names",
        metavar="<name>",
        nargs="+",
        help=(
            "One or more source aliases to remove. Each may be the canonical alias\n"
            "(e.g. foo_bar) or the original entry name (e.g. Foo-Bar); both\n"
            "forms normalise to the same KANON_SOURCE_<alias>_* keys."
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
        help=(
            "Silently skip sources that are not fully present in the .kanon file "
            "(used to clean up partially-orphaned entries). "
            "Known sources are still removed atomically."
        ),
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Preview mode: shows which lines would be removed. Each removed line is\n"
            "printed to stdout with a '-' prefix. Makes no on-disk change. Exits 0.\n"
            "The file-writing rules (line-ending preservation, blank-run collapse,\n"
            "trailing-newline normalisation) apply only to the normal write path,\n"
            "not to the dry-run output."
        ),
    )

    parser.set_defaults(func=run_remove)


# ---------------------------------------------------------------------------
# Private helpers -- line scanner
# ---------------------------------------------------------------------------


def _scan_source_lines(lines: list[str], normalized: str) -> set[int]:
    """Return the set of line indices that match KANON_SOURCE_<alias>_* block keys.

    Recognises every canonical block suffix in ``SOURCE_SUFFIXES`` (``_URL``,
    ``_REF``, ``_PATH``, ``_NAME``, ``_GITBASE``). Comment lines (stripped
    content starting with ``#``) are ignored even if they contain the prefix
    string.

    Args:
        lines: All lines of the .kanon file (with newline characters retained).
        normalized: The normalised alias token (e.g. ``foo_bar``).

    Returns:
        A set of zero-based line indices for the matching lines.
    """
    prefix = f"{SOURCE_PREFIX}{normalized}"
    target_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}
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
    """Validate that the full alias block is present and return its line indices.

    Delegates scanning to :func:`_scan_source_lines`. Hard-errors with the
    spec-canonical message if fewer than the expected number of block keys
    (``len(SOURCE_SUFFIXES)``) are found.

    Args:
        lines: All lines of the .kanon file.
        normalized: The normalised alias token (e.g. ``foo_bar``).
        input_name: The original user-supplied name (used in error messages).

    Returns:
        A set of the line indices to remove (one per present block key).

    Raises:
        SystemExit: When fewer than the expected number of block keys are found.
    """
    expected = len(SOURCE_SUFFIXES)
    matched = _scan_source_lines(lines, normalized)
    found = len(matched)
    if found < expected:
        print(
            f"ERROR: source alias '{input_name}' (normalized form '{normalized}') "
            f"not fully present in .kanon; "
            f"found {found} of {expected} expected KANON_SOURCE_{normalized}_* keys",
            file=sys.stderr,
        )
        sys.exit(1)
    return matched


# ---------------------------------------------------------------------------
# Private helpers -- line-ending detection and file-writing rules
# ---------------------------------------------------------------------------


def _detect_dominant_line_ending(raw_text: str) -> str | None:
    """Detect the dominant line ending in raw_text.

    Counts ``\\r\\n`` occurrences first, then bare ``\\n`` (excluding those
    already counted as part of ``\\r\\n``). The ending with a strictly greater
    count is dominant.

    Returns:
        ``'\\r\\n'`` when CRLF is strictly dominant.
        ``'\\n'`` when LF is strictly dominant.
        ``'\\n'`` when neither ending appears (no newlines in text).
        ``None`` when counts are equal and non-zero (mixed/tie -- caller
        should normalise to LF and warn).
    """
    crlf_count = raw_text.count("\r\n")
    lf_count = raw_text.count("\n") - crlf_count  # bare LF only

    if crlf_count == 0 and lf_count == 0:
        # No newlines at all -- default to LF.
        return "\n"
    if crlf_count == lf_count:
        # Tie -- mixed; return None so caller warns and normalises.
        return None
    return "\r\n" if crlf_count > lf_count else "\n"


def _apply_file_writing_rules(raw_text: str, dominant_ending: str) -> str:
    """Apply the three file-writing rules to raw_text.

    Rules applied in order:
    1. Normalise all line endings to LF for processing, then re-apply
       ``dominant_ending`` at the end.
    2. Collapse runs of 3 or more consecutive blank lines to exactly 2 blank
       lines.
    3. Ensure the output ends with exactly one newline.

    Args:
        raw_text: The text content after removal of KANON_SOURCE_* lines.
        dominant_ending: Either ``'\\n'`` or ``'\\r\\n'``.

    Returns:
        The processed text string with the rules applied.
    """
    # Step 1: Normalise to bare LF for processing.
    normalised = raw_text.replace("\r\n", "\n")

    # Step 2: Collapse runs of 3+ consecutive blank lines to exactly 2.
    # A "blank line" is a line that is empty after stripping (i.e. contains
    # only whitespace or nothing). We use a line-by-line approach.
    input_lines = normalised.split("\n")
    output_lines: list[str] = []
    blank_run = 0
    for line in input_lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= _BLANK_RUN_MAX_PRESERVED:
                output_lines.append(line)
            # else: discard the extra blank line (run > max collapses to max)
        else:
            blank_run = 0
            output_lines.append(line)

    # Step 3: Ensure exactly one trailing newline.
    # Reconstruct the text, then strip trailing blank lines and add one newline.
    text = "\n".join(output_lines)
    text = text.rstrip("\n")
    text = text + "\n"

    # Step 4: Re-apply dominant ending.
    if dominant_ending == "\r\n":
        text = text.replace("\n", "\r\n")

    return text


# ---------------------------------------------------------------------------
# Private helpers -- dry-run diff renderer
# ---------------------------------------------------------------------------


def _render_remove_dry_run_diff(
    lines: list[str],
    removal_indices: set[int],
) -> None:
    """Print the unified-diff-like diff for the lines that would be removed.

    Each line in removal_indices is printed to stdout with a ``-`` prefix and
    its trailing newline stripped (matching the ``kanon add --dry-run`` output
    format).

    Args:
        lines: All lines of the .kanon file (with newline characters retained).
        removal_indices: Set of zero-based indices that would be removed.
    """
    for idx in sorted(removal_indices):
        raw_line = lines[idx]
        clean = raw_line.rstrip("\r\n")
        print(f"-{clean}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_remove(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon remove' subcommand.

    Reads the .kanon file, validates that all requested source names are fully
    present (three matching keys each), then either:

    - **dry-run mode**: prints the '-' prefixed lines that WOULD be removed and
      exits 0 without modifying the file; or
    - **normal mode**: writes the file back with the matching lines removed,
      applying line-ending preservation, blank-run collapse, and trailing-newline
      normalisation.

    Atomicity: the file is only written after all validations succeed.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; exits non-zero on any validation failure.
    """
    kanon_file = pathlib.Path(getattr(args, "kanon_file", KANON_KANON_FILE_DEFAULT))
    dry_run: bool = getattr(args, "dry_run", False)
    force: bool = getattr(args, "force", False)

    if not kanon_file.exists():
        print(
            f"ERROR: no .kanon file at {kanon_file}; nothing to remove",
            file=sys.stderr,
        )
        sys.exit(1)

    raw_bytes = kanon_file.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    lines = raw_text.splitlines(keepends=True)

    # Validate ALL names first (atomicity pre-flight).
    # When --force is set, sources that are not fully present (fewer than 3 keys)
    # are silently skipped rather than causing a hard error; known sources are
    # still validated and collected for atomic removal.
    removal_plan: list[tuple[str, str, set[int]]] = []
    for input_name in args.names:
        normalized = derive_source_name(input_name)
        if force:
            matched = _scan_source_lines(lines, normalized)
            if len(matched) < 3:
                # Silently skip this source -- it is not fully present.
                continue
            indices: set[int] = matched
        else:
            # _collect_removal_lines calls sys.exit on failure -- no write occurs.
            indices = _collect_removal_lines(lines, normalized, input_name)
        removal_plan.append((input_name, normalized, indices))

    # Build the combined set of line indices to remove across all sources.
    all_removal_indices: set[int] = set()
    for _input_name, _normalized, indices in removal_plan:
        all_removal_indices |= indices

    if dry_run:
        # Print the diff that WOULD be written; make no on-disk change.
        _render_remove_dry_run_diff(lines, all_removal_indices)
        return 0

    # Normal write path: acquire the workspace exclusive lock before any file
    # write so a concurrent kanon install cannot read a half-written .kanon.
    workspace_root = kanon_file.resolve().parent
    with kanon_workspace_lock(workspace_root):
        # Detect line endings, apply file-writing rules, write.
        dominant_ending = _detect_dominant_line_ending(raw_text)
        if dominant_ending is None:
            # Mixed line endings -- warn and normalise to LF.
            print(
                f".kanon file {kanon_file} has mixed line endings; normalising to LF",
                file=sys.stderr,
            )
            dominant_ending = "\n"

        # Build kept lines (all lines except the removal set).
        kept_lines = [line for idx, line in enumerate(lines) if idx not in all_removal_indices]
        kept_text = "".join(kept_lines)

        # Apply file-writing rules (blank-run collapse, trailing newline, line endings).
        final_text = _apply_file_writing_rules(kept_text, dominant_ending)

        # Write the file using raw bytes to preserve the exact line ending chosen.
        kanon_file.write_bytes(final_text.encode("utf-8"))

    # Emit one summary line per removed source (outside lock -- read-only).
    for _input_name, normalized, _indices in removal_plan:
        key_names = ", ".join(f"{SOURCE_PREFIX}{normalized}{suffix}" for suffix in SOURCE_SUFFIXES)
        print(f"Removed {key_names} from {kanon_file}")

    return 0
