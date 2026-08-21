"""Clean subcommand handler."""

import pathlib
import sys

from kanon_cli.core.clean import (
    clean,
    find_lockfile,
    remove_kanon_home_store,
    remove_project_config,
    unregister_marketplaces_from_lockfile,
)
from kanon_cli.constants import LOCKFILE_FILENAME
from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.kanonenv import NoSourcesError


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
            "Execute the full Kanon clean lifecycle for THIS project.\n\n"
            "If any dependency set KANON_SOURCE_<alias>_MARKETPLACE=true, runs\n"
            "the uninstall script and removes the marketplace directory. Then\n"
            "removes this project's source workspace under the shared store and\n"
            "the aggregated package links this project created.\n\n"
            "Other projects sharing the same KANON_HOME are left alone: their\n"
            "workspaces, their package links, and the shared content-addressed\n"
            "store entries all survive. Use --purge-all for machine-wide\n"
            "teardown.\n\n"
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
    lockfile_path = find_lockfile()
    if lockfile_path is not None:
        unregister_marketplaces_from_lockfile(lockfile_path)
    remove_kanon_home_store()
    if lockfile_path is not None and lockfile_path.is_file():
        print(f"kanon clean: removing {lockfile_path}...")
        lockfile_path.unlink()


def _purge_sourceless_project(kanonenv_path: pathlib.Path) -> None:
    """Tear down when ``--purge-all`` meets a ``.kanon`` that declares no sources.

    ``--purge-all`` already falls back to a store-only teardown when no ``.kanon``
    is discoverable at all. A ``.kanon`` that exists but declares nothing is the
    same situation for teardown purposes: there is no source to uninstall, so
    refusing would leave the machine-wide escape hatch unusable in exactly the
    state an operator reaches for it, and the "define at least one source"
    diagnostic tells them the opposite of what they asked for.

    Removes what a normal ``--purge-all`` would still remove: this project's
    config files and the shared home store. There is no per-source work to do.

    Args:
        kanonenv_path: Path to the sourceless ``.kanon`` file.
    """
    print("kanon clean --purge-all: .kanon declares no sources; nothing to uninstall.")
    lockfile_path = kanonenv_path.parent / LOCKFILE_FILENAME
    unregister_marketplaces_from_lockfile(lockfile_path)
    remove_project_config(kanonenv_path, lockfile_path)
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
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"kanon clean: found {args.kanonenv_path}")

    args.kanonenv_path = args.kanonenv_path.resolve()
    if not args.kanonenv_path.is_file():
        if args.purge_all:
            _purge_home_only()
            return
        print(f"ERROR: .kanon file not found: {args.kanonenv_path}", file=sys.stderr)
        sys.exit(1)

    try:
        clean(
            args.kanonenv_path,
            orphans=args.orphans,
            purge=(args.purge or args.purge_all),
            purge_home=args.purge_all,
        )
    except NoSourcesError as exc:
        if not args.purge_all:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        _purge_sourceless_project(args.kanonenv_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
