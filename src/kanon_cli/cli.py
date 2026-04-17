"""Kanon CLI entry point with argparse subcommands.

Provides the top-level ``kanon`` command with subcommands:
  - ``kanon install <kanonenv-path>`` -- Full lifecycle: prereqs + repo install + multi-source sync
  - ``kanon clean <kanonenv-path>`` -- Full teardown: uninstall, remove dirs
  - ``kanon validate xml [--repo-root PATH]`` -- Validate manifest XML files
  - ``kanon validate marketplace [--repo-root PATH]`` -- Validate marketplace XML manifests
  - ``kanon bootstrap <package>`` -- Scaffold a new Kanon project from a catalog entry package
  - ``kanon bootstrap list`` -- List available catalog entry packages
  - ``kanon repo <repo-args>`` -- Passthrough to the embedded repo tool
"""

import argparse
import sys

from kanon_cli import __version__
from kanon_cli.commands.bootstrap import register as register_bootstrap
from kanon_cli.commands.clean import register as register_clean
from kanon_cli.commands.install import register as register_install
from kanon_cli.commands.repo import register as register_repo
from kanon_cli.commands.validate import register as register_validate


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands.

    Returns:
        The configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="kanon",
        description="Kanon (Kanon Package Manager) CLI tool. Manages the full Kanon lifecycle: install, clean, and validate.",
        epilog=(
            "Examples:\n"
            "  kanon install              # Auto-discover .kanon from cwd\n"
            "  kanon install .kanon       # Explicit path\n"
            "  kanon clean                # Auto-discover .kanon from cwd\n"
            "  kanon clean .kanon         # Explicit path\n"
            "  kanon validate xml\n"
            "  kanon validate marketplace --repo-root /path/to/repo\n"
            "  kanon repo version         # Show embedded repo tool version\n"
            "  kanon repo init -u <url> -b <branch> -m <manifest>\n"
            "  kanon repo sync --jobs=4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="subcommands",
        description="Available subcommands",
    )

    register_bootstrap(subparsers)
    register_install(subparsers)
    register_clean(subparsers)
    register_validate(subparsers)
    register_repo(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the appropriate subcommand.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(2)

    args.func(args)
