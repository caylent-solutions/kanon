"""Clean subcommand handler."""

import pathlib
import sys

from kanon_cli.core.clean import clean
from kanon_cli.core.discover import find_kanonenv


def register(subparsers) -> None:
    """Register the clean subcommand.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "clean",
        help="Full teardown: uninstall, remove dirs",
        description=(
            "Execute the full Kanon clean lifecycle.\n\n"
            "If KANON_MARKETPLACE_INSTALL=true, runs the uninstall script\n"
            "and removes the marketplace directory. Then removes .packages/\n"
            "and .kanon-data/ directories."
        ),
        epilog="Example:\n  kanon clean             # auto-discovers .kanon\n  kanon clean .kanon      # explicit path",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "kanonenv_path",
        nargs="?",
        default=None,
        type=pathlib.Path,
        help="Path to the .kanon configuration file (default: auto-discover from current directory)",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the clean command.

    Args:
        args: Parsed arguments with kanonenv_path.
    """
    if args.kanonenv_path is None:
        try:
            args.kanonenv_path = find_kanonenv()
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"kanon clean: found {args.kanonenv_path}")

    try:
        clean(args.kanonenv_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
