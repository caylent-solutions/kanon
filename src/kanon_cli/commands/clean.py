"""Clean subcommand handler."""

import pathlib
import sys

from kanon_cli.core.clean import clean, remove_kanon_home_store
from kanon_cli.core.discover import find_kanonenv


def register(subparsers) -> None:
    """Register the clean subcommand.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "clean",
        add_help=True,
        help="Full teardown: uninstall, remove dirs",
        description=(
            "Execute the full Kanon clean lifecycle.\n\n"
            "If any dependency set KANON_SOURCE_<alias>_MARKETPLACE=true, runs\n"
            "the uninstall script and removes the marketplace directory. Then\n"
            "removes .packages/ and .kanon-data/ directories and prunes the\n"
            "content-addressed entries from the shared KANON_HOME store.\n\n"
            "With --orphans, before the normal teardown kanon also unregisters\n"
            "any kanon-owned marketplaces recorded in .kanon.lock that are no\n"
            "longer referenced by .kanon (pruning them from ~/.claude).\n\n"
            "With --purge, kanon also deletes this project's .kanon and\n"
            ".kanon.lock files. With --purge-all, it additionally removes the\n"
            "shared KANON_HOME store directory (default ~/.kanon-home); this\n"
            "runs even when no .kanon project is present."
        ),
        epilog=(
            "Example:\n"
            "  kanon clean             # auto-discovers .kanon\n"
            "  kanon clean .kanon      # explicit path\n"
            "  kanon clean --orphans   # also unregister orphaned marketplaces\n"
            "  kanon clean --purge     # also delete .kanon and .kanon.lock\n"
            "  kanon clean --purge-all # also remove the KANON_HOME store dir"
        ),
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "kanonenv_path",
        nargs="?",
        default=None,
        type=pathlib.Path,
        help="Path to the .kanon configuration file (default: auto-discover from current directory)",
    )
    parser.add_argument(
        "--orphans",
        action="store_true",
        default=False,
        help=(
            "Also unregister kanon-owned marketplaces no longer referenced by "
            ".kanon/.kanon.lock (prunes them from ~/.claude)."
        ),
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        default=False,
        help=(
            "Also delete this project's .kanon and .kanon.lock files after the "
            "normal teardown (full removal of the project's kanon config)."
        ),
    )
    parser.add_argument(
        "--purge-all",
        action="store_true",
        default=False,
        help=(
            "Everything --purge does, and also remove the shared kanon home store "
            "directory (KANON_HOME, default ~/.kanon-home) used by all projects. "
            "Runs even when no .kanon project is present (removes only the shared store)."
        ),
    )
    parser.set_defaults(func=_run)


def _purge_home_only() -> None:
    """Remove only the shared kanon home store when no project ``.kanon`` is present.

    ``kanon clean --purge-all`` is machine-global: it must still tear down the
    shared ``KANON_HOME`` store even when there is no discoverable project
    ``.kanon`` (e.g. right after ``kanon clean --purge`` deleted it). Delegates to
    ``remove_kanon_home_store`` so all safety refusals (the filesystem root, the
    user home directory, an ancestor of the home or current directory) are
    preserved exactly as in the in-``clean()`` path.
    """
    print("kanon clean --purge-all: no .kanon project found; removing only the shared kanon home store...")
    remove_kanon_home_store()


def _run(args) -> None:
    """Execute the clean command.

    Args:
        args: Parsed arguments with kanonenv_path.
    """
    if args.kanonenv_path is None:
        try:
            args.kanonenv_path = find_kanonenv()
        except FileNotFoundError as exc:
            if args.purge_all:
                _purge_home_only()
                return
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"kanon clean: found {args.kanonenv_path}")

    args.kanonenv_path = args.kanonenv_path.resolve()
    if not args.kanonenv_path.is_file():
        if args.purge_all:
            _purge_home_only()
            return
        print(f"Error: .kanon file not found: {args.kanonenv_path}", file=sys.stderr)
        sys.exit(1)

    try:
        clean(
            args.kanonenv_path,
            orphans=args.orphans,
            purge=(args.purge or args.purge_all),
            purge_home=args.purge_all,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
