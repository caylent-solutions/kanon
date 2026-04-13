"""Clean subcommand handler."""

import pathlib

from kanon_cli.core.clean import clean


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
        epilog="Example:\n  kanon clean .kanon",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "kanonenv_path",
        type=pathlib.Path,
        help="Path to the .kanon configuration file",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the clean command.

    Args:
        args: Parsed arguments with kanonenv_path.
    """
    clean(args.kanonenv_path)
