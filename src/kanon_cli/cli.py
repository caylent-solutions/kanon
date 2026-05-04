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
import os
import signal
import sys
from collections.abc import Callable
from types import FrameType

from kanon_cli import __version__
from kanon_cli.commands.bootstrap import register as register_bootstrap
from kanon_cli.commands.clean import register as register_clean
from kanon_cli.commands.install import register as register_install
from kanon_cli.commands.repo import register as register_repo
from kanon_cli.commands.validate import register as register_validate


def _make_signal_handler(signum: int) -> "Callable[[int, FrameType | None], None]":
    """Return a signal handler that exits with the POSIX shell convention code.

    The POSIX shell convention for a process terminated by signal N is to
    exit with code 128 + N. Using ``os._exit()`` instead of ``sys.exit()``
    ensures the exit propagates immediately without being intercepted by any
    enclosing ``except SystemExit`` clause in library code (e.g., the embedded
    repo tool's ``run_from_args`` wrapper).

    Args:
        signum: The signal number for which to create the handler.

    Returns:
        A callable suitable for ``signal.signal(signum, handler)``.
    """

    def _handler(received_signum: int, frame: "FrameType | None") -> None:
        os._exit(128 + received_signum)

    return _handler


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

    Installs POSIX-compliant signal handlers for SIGTERM and SIGINT before
    dispatching so that a signal received during a long-running subcommand
    (e.g., ``kanon install`` blocked on a network operation) exits with the
    standard shell convention code of 128 + signal_number, rather than the
    Python default of a negative returncode (OS-killed) or 1 (wrapped error).

    SIGHUP is intentionally left at its default disposition so that hangup
    events behave according to the platform default (terminate the process
    with a signal-killed exit code).

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    signal.signal(signal.SIGTERM, _make_signal_handler(signal.SIGTERM))
    signal.signal(signal.SIGINT, _make_signal_handler(signal.SIGINT))

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(2)

    args.func(args)
