"""Repo subcommand: passthrough to kanon's repo subsystem.

Delegates all trailing arguments to repo_run() from the Python API layer.
Supports the full repo subcommand surface (init, sync, envsubst, etc.) by
forwarding arbitrary argv to the repo dispatcher without interpretation.
"""

import argparse
import os
import sys

from kanon_cli.constants import KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT
from kanon_cli.repo import RepoCommandError, repo_run


def register(subparsers) -> None:
    """Register the repo subcommand.

    Adds a ``repo`` sub-parser that captures all trailing arguments using
    argparse.REMAINDER and passes them to the repo dispatcher.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "repo",
        help="Run a kanon repo subcommand (manifest-driven sync)",
        description=(
            "Run kanon's repo subcommands.\n\n"
            "All trailing arguments after 'kanon repo' are passed verbatim to\n"
            "the repo dispatcher. Use 'kanon repo --help' to see this help,\n"
            "or 'kanon repo help' to see the per-subcommand help.\n\n"
            "Examples:\n"
            "  kanon repo init -u <url> -b <branch> -m <manifest>\n"
            "  kanon repo sync --jobs=4\n"
            "  kanon repo status\n"
            "  kanon repo help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_repo_dir = os.environ.get(KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT)
    parser.add_argument(
        "--repo-dir",
        dest="repo_dir",
        default=default_repo_dir,
        help=(
            "Path to the .repo directory for the repo tool "
            f"(default: ${{KANON_REPO_DIR}} or {KANONENV_REPO_DIR_DEFAULT!r})"
        ),
    )
    parser.add_argument(
        "repo_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded verbatim to the repo tool",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the repo passthrough command.

    Extracts the trailing arguments from ``args.repo_args`` and delegates them
    to repo_run(). Propagates the exit code from repo_run() directly via
    sys.exit().

    Args:
        args: Parsed arguments with repo_args (list of trailing argv) and
            repo_dir (path to the .repo directory).
    """
    try:
        exit_code = repo_run(args.repo_args, repo_dir=args.repo_dir)
    except RepoCommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code if exc.exit_code is not None else 1)
    sys.exit(exit_code)
