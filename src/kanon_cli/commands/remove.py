"""kanon remove subcommand: strip alias-keyed dependency blocks from a .kanon file.

Accepts one or more aliases (each may be the canonical alias such as
``foo_bar`` or the original entry name such as ``Foo-Bar``); normalises each
via :func:`derive_source_name` before lookup; and removes every alias-keyed
``KANON_SOURCE_<alias>_*`` line of the block (the required structural keys
``_URL``, ``_REF``, ``_PATH``, ``_NAME``, plus any optional per-dependency
env-var line such as ``_GITBASE`` and the optional ``_MARKETPLACE`` flag)
wherever they appear in the file (they need not be contiguous).

Atomicity guarantee: the file is only written when ALL requested aliases are
validated successfully. Presence is judged by the required STRUCTURAL keys
only: if any alias is missing one of its required structural keys (fewer than
``len(SOURCE_SUFFIXES)`` present) the command exits non-zero and the file is
unchanged. Optional env-var and ``_MARKETPLACE`` lines never affect presence
but are removed along with the structural block.

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
    SOURCE_RESERVED_SUFFIXES,
    SOURCE_SUFFIXES,
)
from kanon_cli.core.install import resolve_kanon_lock_root
from kanon_cli.core.kanonenv_writer import (
    guard_kanon_file_not_dir,
    prune_claude_marketplaces_dir_if_unused,
)
from kanon_cli.core.metadata import derive_source_name
from kanon_cli.utils.concurrency import kanon_workspace_lock


_BLANK_RUN_MAX_PRESERVED = 2


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'remove' subcommand on the top-level argparse subparsers.

    Accepts both the canonical source name (e.g. ``foo_bar``) and the
    original entry name (e.g. ``Foo-Bar``); both forms are normalised via
    :func:`derive_source_name` before lookup. Removal is atomic: if any
    requested name is not fully present (fewer than the required structural
    keys) the command exits non-zero and the file is unchanged.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "remove",
        add_help=True,
        help="Remove one or more alias-keyed dependency blocks from the .kanon file.",
        description=(
            "Remove the KANON_SOURCE_<alias>_{URL,REF,PATH,NAME} block (plus any\n"
            "optional per-dependency env-var and _MARKETPLACE lines) for one or\n"
            "more entries from the .kanon file.\n\n"
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


def _discover_aliases(lines: list[str]) -> set[str]:
    """Return every source alias that has a ``KANON_SOURCE_<alias>_URL`` line.

    Used to detect prefix-collision aliases (one alias name being a textual
    prefix of another) so a longer alias' keys are not swallowed into a shorter
    alias' block during removal. Comment lines are ignored.

    Args:
        lines: All lines of the .kanon file.

    Returns:
        The set of discovered alias tokens.
    """
    aliases: set[str] = set()
    url_prefix = SOURCE_PREFIX
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0]
        if key.startswith(url_prefix) and key.endswith(SOURCE_SUFFIXES[0]):
            alias = key[len(url_prefix) : -len(SOURCE_SUFFIXES[0])]
            if alias:
                aliases.add(alias)
    return aliases


def _key_belongs_to_alias(key: str, normalized: str, all_aliases: set[str]) -> bool:
    """Return True when ``key`` is a ``KANON_SOURCE_<normalized>_*`` block key.

    A block key is any ``KANON_SOURCE_<normalized>_<VAR>`` key: the required
    structural suffixes, the optional ``_MARKETPLACE`` flag, and every open
    per-dependency env-var line. A key is rejected when its ``<VAR>`` portion is
    instead a structural/marketplace suffix of a longer alias in ``all_aliases``
    whose name begins with ``normalized``.

    Args:
        key: The ``.kanon`` line key (text before ``=``).
        normalized: The normalised alias token being removed.
        all_aliases: All aliases present in the file.

    Returns:
        True iff ``key`` belongs to ``normalized``'s alias-keyed block.
    """
    prefix = f"{SOURCE_PREFIX}{normalized}_"
    if not key.startswith(prefix):
        return False
    for other in all_aliases:
        if other == normalized or not other.startswith(normalized):
            continue
        for suffix in SOURCE_RESERVED_SUFFIXES:
            if key == f"{SOURCE_PREFIX}{other}{suffix}":
                return False
    return True


def _scan_source_lines(lines: list[str], normalized: str) -> set[int]:
    """Return the set of line indices for the full KANON_SOURCE_<alias>_* block.

    Matches every line of the alias block: the required structural suffixes
    (``_URL``/``_REF``/``_PATH``/``_NAME``), the optional ``_MARKETPLACE`` flag,
    and every open per-dependency env-var line (e.g. ``_GITBASE`` or a custom
    ``_MYBASE``). Comment lines (stripped content starting with ``#``) are
    ignored even if they contain the prefix string.

    Args:
        lines: All lines of the .kanon file (with newline characters retained).
        normalized: The normalised alias token (e.g. ``foo_bar``).

    Returns:
        A set of zero-based line indices for the matching lines.
    """
    all_aliases = _discover_aliases(lines)
    matched: set[int] = set()
    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if _key_belongs_to_alias(key, normalized, all_aliases):
            matched.add(idx)
    return matched


def _count_structural_keys(lines: list[str], normalized: str) -> int:
    """Count how many required structural block keys the alias has present.

    Only the required structural suffixes (``SOURCE_SUFFIXES``:
    ``_URL``/``_REF``/``_PATH``/``_NAME``) are counted; optional env-var lines
    and the ``_MARKETPLACE`` flag do not contribute. Comment lines are ignored.

    Args:
        lines: All lines of the .kanon file.
        normalized: The normalised alias token.

    Returns:
        The number of distinct required structural keys present for the alias.
    """
    prefix = f"{SOURCE_PREFIX}{normalized}"
    target_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}
    present: set[str] = set()
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in target_keys:
            present.add(key)
    return len(present)


def _collect_removal_lines(
    lines: list[str],
    normalized: str,
    input_name: str,
) -> set[int]:
    """Validate that the required structural block is present and return block indices.

    Hard-errors with the spec-canonical message if fewer than the expected
    number of required structural keys (``len(SOURCE_SUFFIXES)``) are found.
    When the structural block is fully present, the returned indices cover the
    WHOLE alias block (structural keys plus any optional env-var and
    ``_MARKETPLACE`` lines) so removal leaves no orphaned lines behind.

    Args:
        lines: All lines of the .kanon file.
        normalized: The normalised alias token (e.g. ``foo_bar``).
        input_name: The original user-supplied name (used in error messages).

    Returns:
        A set of the line indices to remove (the full alias block).

    Raises:
        SystemExit: When fewer than the expected number of structural keys are
            found.
    """
    expected = len(SOURCE_SUFFIXES)
    found = _count_structural_keys(lines, normalized)
    if found < expected:
        print(
            f"ERROR: source alias '{input_name}' (normalized form '{normalized}') "
            f"not fully present in .kanon; "
            f"found {found} of {expected} expected KANON_SOURCE_{normalized}_* keys",
            file=sys.stderr,
        )
        sys.exit(1)
    return _scan_source_lines(lines, normalized)


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
    lf_count = raw_text.count("\n") - crlf_count

    if crlf_count == 0 and lf_count == 0:
        return "\n"
    if crlf_count == lf_count:
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

    normalised = raw_text.replace("\r\n", "\n")

    input_lines = normalised.split("\n")
    output_lines: list[str] = []
    blank_run = 0
    for line in input_lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= _BLANK_RUN_MAX_PRESERVED:
                output_lines.append(line)

        else:
            blank_run = 0
            output_lines.append(line)

    text = "\n".join(output_lines)
    text = text.rstrip("\n")
    text = text + "\n"

    if dominant_ending == "\r\n":
        text = text.replace("\n", "\r\n")

    return text


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


def run_remove(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon remove' subcommand.

    Reads the .kanon file, validates that all requested source names are fully
    present (every required structural key present), then either:

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
    guard_kanon_file_not_dir(kanon_file)
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

    removal_plan: list[tuple[str, str, set[int]]] = []
    for input_name in args.names:
        normalized = derive_source_name(input_name)
        if force:
            if _count_structural_keys(lines, normalized) == 0:
                continue
            indices: set[int] = _scan_source_lines(lines, normalized)
        else:
            indices = _collect_removal_lines(lines, normalized, input_name)
        removal_plan.append((input_name, normalized, indices))

    all_removal_indices: set[int] = set()
    for _input_name, _normalized, indices in removal_plan:
        all_removal_indices |= indices

    if dry_run:
        _render_remove_dry_run_diff(lines, all_removal_indices)
        return 0

    with kanon_workspace_lock(resolve_kanon_lock_root(kanon_file)):
        dominant_ending = _detect_dominant_line_ending(raw_text)
        if dominant_ending is None:
            print(
                f".kanon file {kanon_file} has mixed line endings; normalising to LF",
                file=sys.stderr,
            )
            dominant_ending = "\n"

        kept_lines = [line for idx, line in enumerate(lines) if idx not in all_removal_indices]
        kept_text = "".join(kept_lines)

        final_text = _apply_file_writing_rules(kept_text, dominant_ending)

        kanon_file.write_bytes(final_text.encode("utf-8"))

        prune_claude_marketplaces_dir_if_unused(kanon_file, hold_lock=False)

    for _input_name, normalized, _indices in removal_plan:
        key_names = ", ".join(f"{SOURCE_PREFIX}{normalized}{suffix}" for suffix in SOURCE_SUFFIXES)
        print(f"Removed {key_names} from {kanon_file}")

    return 0
