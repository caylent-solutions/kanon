"""Bootstrap subcommand: deprecation shim.

Any invocation other than ``--help`` prints a WARN to stderr (verbatim text
from spec Section 4.9 behaviour table) and exits with status 3
(EXIT_CODE_DEPRECATED).  No work is performed and no catalog or filesystem
access is made.

The argparse parser still declares ``<package>``, ``--catalog-source``, and
``--output-dir`` so ``--help`` discoverability is preserved for T3 to extend.
"""

import argparse
import pathlib
import sys

from kanon_cli.constants import EXIT_CODE_DEPRECATED
from kanon_cli.core.cli_args import add_catalog_source_arg


def register(subparsers) -> None:
    """Register the bootstrap subcommand.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "bootstrap",
        help="[DEPRECATED] Use 'kanon add' instead. See docs/migration-bootstrap-to-add.md.",
        description=(
            "[DEPRECATED] 'kanon bootstrap' is deprecated.\n\n"
            "Use 'kanon add <package>' instead of 'kanon bootstrap <package>'.\n"
            "Use 'kanon list' instead of 'kanon bootstrap list'.\n\n"
            "See docs/migration-bootstrap-to-add.md for the migration guide."
        ),
        epilog="Examples:\n  kanon add kanon\n  kanon list\n  kanon add kanon --kanon-file my-project/.kanon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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


def _format_deprecated_warn(invocation: str, replacement_argv_tail: str) -> str:
    """Format the deprecation WARN message for a bootstrap invocation.

    Constructs the verbatim WARN text per spec Section 4.9 behaviour table.
    The replacement_argv_tail parameter is accepted as a pre-translated argv
    string; T2 will supply the real translated tail. T1's call sites pass
    the concrete replacement command directly.

    Args:
        invocation: The full deprecated invocation string, e.g.
            ``'kanon bootstrap list'`` or ``'kanon bootstrap kanon'``.
        replacement_argv_tail: The recommended replacement command, e.g.
            ``'kanon list'`` or ``'kanon add kanon'``.

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
        args: Parsed arguments. Only ``args.package`` is read to select
            the correct WARN message variant.
    """
    if args.package == "list":
        warn_text = _format_deprecated_warn(
            "kanon bootstrap list",
            "kanon list",
        )
    else:
        warn_text = _format_deprecated_warn(
            f"kanon bootstrap {args.package}",
            f"kanon add {args.package}",
        )
    print(warn_text, file=sys.stderr)
    raise SystemExit(EXIT_CODE_DEPRECATED)
