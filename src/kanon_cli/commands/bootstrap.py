"""Bootstrap subcommand: deprecation shim.

Any invocation other than ``--help`` prints a WARN to stderr (verbatim text
from spec Section 4.9 behaviour table) and exits with status 3
(EXIT_CODE_DEPRECATED).  No work is performed and no catalog or filesystem
access is made.

The argparse parser still declares ``<package>``, ``--catalog-source``, and
``--output-dir`` so ``--help`` discoverability is preserved.  ``--help``
exits 0 (informational) and the output is prepended with the verbatim
DEPRECATED notice from spec Section 4.9 before the ``usage:`` line.
"""

import argparse
import pathlib
import sys

from kanon_cli.constants import EXIT_CODE_DEPRECATED
from kanon_cli.core.cli_args import add_catalog_source_arg

# Note text for --output-dir when the add arm is selected.
# Spec Section 4.9: --output-dir has no equivalent in 'kanon add'.
_NOTE_OUTPUT_DIR_ADD = (
    "Note: --output-dir has no direct equivalent in 'kanon add'; "
    "the install workspace is the current directory or KANON_WORKSPACE_DIR if set."
)

# Note text for --output-dir when the list arm is selected.
# Spec Section 4.9: --output-dir has no equivalent in 'kanon list'.
_NOTE_OUTPUT_DIR_LIST = "Note: --output-dir has no equivalent in 'kanon list'."

# Verbatim DEPRECATED notice (spec Section 4.9 behaviour table, last row).
# This is the single source of truth for the notice text; both the parser
# configuration and any referencing tests import this constant.
_DEPRECATED_NOTICE = (
    "DEPRECATED: 'kanon bootstrap' is replaced by 'kanon add' and 'kanon list'. See docs/migration-bootstrap-to-add.md."
)

# Flag translation table (pipe-delimited) from spec Section 4.9.
# Embedded verbatim in the --help epilog via RawDescriptionHelpFormatter.
# This constant is the single source of truth for the table text (DRY).
_FLAG_TRANSLATION_TABLE_HELP = (
    "Flag translation table (spec Section 4.9):\n"
    "\n"
    "| Bootstrap flag      | kanon add equivalent      | kanon list equivalent                          | Notes              |\n"
    "|---------------------|---------------------------|------------------------------------------------|--------------------|\n"
    "| <package> positional| <name> positional         | (n/a -- bootstrap list triggers kanon list)    | identical semantics|\n"
    "| --catalog-source <v>| --catalog-source <v>      | --catalog-source <v>                           | identical          |\n"
    "| --output-dir <v>    | (no equivalent)           | (no equivalent)                                | See notes below    |"
)

# Exit codes section for bootstrap --help (spec Section 4.9 + Section 14).
# bootstrap is the only command that lists exit code 3 in its help output.
_BOOTSTRAP_EXIT_CODES_HELP = "Exit codes:\n  0  help output\n  3  deprecated invocation; any non-help call"

# Description body shown under the usage line in --help output.
# The argparse ``description`` field is rendered AFTER the usage line;
# the DEPRECATED notice is injected BEFORE usage by _DeprecatedPrefixParser.
_BOOTSTRAP_DESCRIPTION = (
    "DEPRECATED command. Use the replacements below.\n\n"
    "Use 'kanon add <package>' instead of 'kanon bootstrap <package>'.\n"
    "Use 'kanon list' instead of 'kanon bootstrap list'.\n\n"
    "See docs/migration-bootstrap-to-add.md for the migration guide."
)


class _DeprecatedPrefixParser(argparse.ArgumentParser):
    """ArgumentParser subclass that prepends the DEPRECATED notice before the usage line.

    Spec Section 4.9 (last row) requires the DEPRECATED notice to appear as the
    first non-empty line of ``--help`` output, before ``usage:``.  Standard
    argparse places the ``description`` after the usage line; this subclass
    overrides ``format_help`` to inject the notice above usage.
    """

    def format_help(self) -> str:
        """Return help text with DEPRECATED notice prepended before the usage line.

        Returns:
            Full help string: DEPRECATED notice, blank line, standard argparse help.
        """
        base_help = super().format_help()
        return _DEPRECATED_NOTICE + "\n\n" + base_help


def register(subparsers) -> None:
    """Register the bootstrap subcommand.

    The parser is constructed directly as a ``_DeprecatedPrefixParser`` instance
    so that ``--help`` output begins with the verbatim DEPRECATED notice
    (spec Section 4.9, last row) before the ``usage:`` line.  The instance is
    then inserted into the subparsers map directly, matching the public contract
    of ``subparsers.choices``.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    # Build the prog string the same way add_parser would: "<parent_prog> bootstrap".
    prog = f"{subparsers._prog_prefix} bootstrap"
    epilog = _FLAG_TRANSLATION_TABLE_HELP + "\n\n" + _BOOTSTRAP_EXIT_CODES_HELP

    parser = _DeprecatedPrefixParser(
        prog=prog,
        add_help=True,
        description=_BOOTSTRAP_DESCRIPTION,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Register into the subparsers choice map.
    # This mirrors exactly what add_parser() does internally (Python 3.9+).
    subparsers._name_parser_map["bootstrap"] = parser

    # Register a pseudo-action so the subparser appears in the parent --help list.
    choice_action = subparsers._ChoicesPseudoAction(
        "bootstrap",
        (),
        "[DEPRECATED] Use 'kanon add' instead. See docs/migration-bootstrap-to-add.md.",
    )
    subparsers._choices_actions.append(choice_action)
    parser.add_argument(
        "package",
        help="Catalog entry package name (e.g. kanon) or 'list' to show available packages",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path("."),
        help="[DEPRECATED] Target directory for bootstrapped files (default: current directory)",
    )
    add_catalog_source_arg(parser)
    parser.set_defaults(func=_run)


def _translate_bootstrap_argv_tail(args: argparse.Namespace) -> str:
    """Translate today's ``kanon bootstrap`` flags into the equivalent replacement tail.

    This is a pure function: deterministic, no side effects, no I/O.
    The returned string is the flags-only portion of the replacement command
    (without the leading ``kanon add <name>`` or ``kanon list`` prefix).

    Translation rules (spec Section 4.9 flag translation table):

    - ``--catalog-source <v>`` maps to ``--catalog-source <v>`` for both arms.
      The value is emitted verbatim (shell-quoting is the operator's responsibility).
    - ``--output-dir <v>`` has no direct equivalent. A ``Note:`` line is
      appended to the tail -- distinct text per arm -- instead of a flag.
    - The ``<package>`` positional is NOT included in the tail (it is prepended
      by the caller as part of the base command).

    Args:
        args: Parsed arguments from argparse. Must have ``package``,
            ``catalog_source`` (str or None), and ``output_dir``
            (pathlib.Path, default ``pathlib.Path(".")``).

    Returns:
        A string containing translated flags and any ``Note:`` lines,
        separated by ``\\n``. Returns an empty string when no flags require
        translation.
    """
    is_list_arm = args.package == "list"
    parts: list[str] = []

    if args.catalog_source is not None:
        parts.append(f"--catalog-source {args.catalog_source}")

    if args.output_dir != pathlib.Path("."):
        note = _NOTE_OUTPUT_DIR_LIST if is_list_arm else _NOTE_OUTPUT_DIR_ADD
        parts.append(note)

    return "\n".join(parts)


def _format_deprecated_warn(invocation: str, replacement_argv_tail: str) -> str:
    """Format the deprecation WARN message for a bootstrap invocation.

    Constructs the verbatim WARN text per spec Section 4.9 behaviour table.
    The caller provides the full replacement command (including any translated
    flags produced by ``_translate_bootstrap_argv_tail``).

    Args:
        invocation: The full deprecated invocation string, e.g.
            ``'kanon bootstrap list'`` or ``'kanon bootstrap kanon'``.
        replacement_argv_tail: The recommended replacement command, e.g.
            ``'kanon list'`` or ``'kanon add kanon --catalog-source <url>'``.

    Returns:
        The formatted multi-line WARN string (without a trailing newline).
    """
    lines = [
        f"WARN: '{invocation}' is deprecated. Run instead:",
        f"    {replacement_argv_tail}",
        "See docs/migration-bootstrap-to-add.md.",
    ]
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> None:
    """Execute the bootstrap deprecation shim.

    For any non-help invocation, prints a WARN to stderr and raises
    SystemExit(EXIT_CODE_DEPRECATED). No catalog resolution, filesystem
    mutation, or business logic is performed.

    Args:
        args: Parsed arguments. ``args.package`` selects the WARN variant;
            ``args.catalog_source`` and ``args.output_dir`` feed the translator.
    """
    translated_tail = _translate_bootstrap_argv_tail(args)
    invocation = f"kanon bootstrap {args.package}"

    if args.package == "list":
        base_replacement = "kanon list"
    else:
        base_replacement = f"kanon add {args.package}"

    # Partition the translated tail into flag tokens and Note: lines.
    # Flag tokens are appended to the replacement command; Note: lines are
    # appended after the WARN block so the operator sees them as separate notices.
    tail_lines = translated_tail.splitlines() if translated_tail else []
    flag_lines = [ln for ln in tail_lines if not ln.startswith("Note:")]
    note_lines = [ln for ln in tail_lines if ln.startswith("Note:")]

    flags_str = " ".join(flag_lines)
    replacement_cmd = f"{base_replacement} {flags_str}".rstrip()
    warn_text = _format_deprecated_warn(invocation, replacement_cmd)
    if note_lines:
        warn_text = warn_text + "\n" + "\n".join(note_lines)

    print(warn_text, file=sys.stderr)
    raise SystemExit(EXIT_CODE_DEPRECATED)
