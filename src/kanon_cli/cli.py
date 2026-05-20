"""Kanon CLI entry point with argparse subcommands.

Provides the top-level ``kanon`` command with subcommands:
  - ``kanon add <name>[@<spec>] ...`` -- Add catalog entries to .kanon file
  - ``kanon remove <name> ...`` -- Remove dependency triples from .kanon file
  - ``kanon install <kanonenv-path>`` -- Full lifecycle: prereqs + repo install + multi-source sync
  - ``kanon clean <kanonenv-path>`` -- Full teardown: uninstall, remove dirs
  - ``kanon validate xml [--repo-root PATH]`` -- Validate manifest XML files
  - ``kanon validate marketplace [--repo-root PATH]`` -- Validate marketplace XML manifests
  - ``kanon bootstrap <package>`` -- Scaffold a new Kanon project from a catalog entry package
  - ``kanon bootstrap list`` -- List available catalog entry packages
  - ``kanon repo <repo-args>`` -- Passthrough to the embedded repo tool
  - ``kanon why <project-url>`` -- Explain why a project is in the resolved tree
"""

import argparse
import os
import signal
import sys
from collections.abc import Callable, Sequence
from typing import Any
from types import FrameType

from kanon_cli import __version__
from kanon_cli.commands.add import register as register_add
from kanon_cli.commands.bootstrap import register as register_bootstrap
from kanon_cli.commands.catalog import register as register_catalog
from kanon_cli.commands.clean import register as register_clean
from kanon_cli.commands.completion import register as register_completion
from kanon_cli.commands.doctor import register as register_doctor
from kanon_cli.commands.install import register as register_install
from kanon_cli.commands.list import register as register_list
from kanon_cli.commands.outdated import register as register_outdated
from kanon_cli.commands.remove import register as register_remove
from kanon_cli.commands.why import register as register_why
from kanon_cli.commands.repo import register as register_repo
from kanon_cli.commands.validate import register as register_validate
from kanon_cli.completions.catalog_entries import register as register_complete_catalog_entries
from kanon_cli.completions.catalog_versions import register as register_complete_catalog_versions
from kanon_cli.completions.lockfile_names import register as register_complete_lockfile_names
from kanon_cli.completions.project_versions import register as register_complete_project_versions
from kanon_cli.completions.source_names import register as register_complete_source_names
from kanon_cli.core.cli_args import _apply_global_flags, add_global_flags

# ---------------------------------------------------------------------------
# Top-level help text (spec Section 14)
# ---------------------------------------------------------------------------

_TOP_LEVEL_HELP: str = """\
kanon -- declarative dependency manager for git-hosted assets

Usage: kanon <command> [options]

Discovery & management:
  list             Discover catalog entries
  add              Add catalog entries to .kanon
  remove           Remove sources from .kanon
  outdated         Report installable upgrades
  why              Explain why a transitive dep is in the tree

Lifecycle:
  install          Install/sync everything in .kanon
  clean            Remove installed artifacts (use --orphans to also prune unreferenced)
  validate         Validate XML manifests (subcommands: xml, marketplace, metadata)
  doctor           Diagnose .kanon / .kanon.lock health

Manifest repo (catalog author):
  catalog audit    Audit a manifest repo against the standards contract
  repo             Catalog-author repo subcommands (see kanon repo --help)

Shell integration:
  completion       Generate shell completion script

Deprecated:
  bootstrap        DEPRECATED -- use 'kanon add' / 'kanon list'. See docs/migration-bootstrap-to-add.md.

Global options (always available):
  --version                      Print kanon version and exit.
  --help                         Show this and exit.
  --quiet / --verbose            Logging verbosity (mutually exclusive).
  --no-color                     Disable ANSI color (also respects NO_COLOR env var).

Catalog source (required by commands that resolve a manifest repo; see each subcommand's --help):
  --catalog-source <url>@<ref>   Override KANON_CATALOG_SOURCE. No default; one of
                                 --catalog-source or KANON_CATALOG_SOURCE is required
                                 for list/add/outdated/why/catalog audit. For install
                                 and doctor, .kanon.lock [catalog].source is used as
                                 fallback when present and consistent.
"""


class _TopLevelHelpAction(argparse.Action):
    """Argparse action that prints ``_TOP_LEVEL_HELP`` to stdout and exits 0.

    Registered on the top-level parser in place of the default ``-h``/``--help``
    action (``add_help=False``) so that ``kanon --help`` produces the verbatim
    spec Section 14 format rather than argparse's auto-generated layout.

    Single Responsibility: this class only prints the constant and exits.
    It has no knowledge of the parser structure and introduces no side-effects
    beyond the I/O to stdout and the ``SystemExit(0)`` raise.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Print the top-level help text and exit with code 0.

        Args:
            parser: The ArgumentParser instance (unused; help text is the
                constant, not derived from parser state).
            namespace: The argparse namespace being populated (unused).
            values: The option values parsed (always empty for nargs=0).
            option_string: The option string used to invoke this action.
        """
        sys.stdout.write(_TOP_LEVEL_HELP)
        raise SystemExit(0)


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
        add_help=False,
    )
    parser.add_argument(
        "--help",
        nargs=0,
        action=_TopLevelHelpAction,
        default=argparse.SUPPRESS,
        help="Show this and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    add_global_flags(parser)

    subparsers = parser.add_subparsers(
        dest="command",
        title="subcommands",
        description="Available subcommands",
    )

    register_add(subparsers)
    register_bootstrap(subparsers)
    register_catalog(subparsers)
    register_clean(subparsers)
    register_completion(subparsers)
    register_doctor(subparsers)
    register_install(subparsers)
    register_list(subparsers)
    register_outdated(subparsers)
    register_remove(subparsers)
    register_validate(subparsers)
    register_repo(subparsers)
    register_why(subparsers)
    register_complete_catalog_entries(subparsers)
    register_complete_catalog_versions(subparsers)
    register_complete_lockfile_names(subparsers)
    register_complete_project_versions(subparsers)
    register_complete_source_names(subparsers)

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

    _apply_global_flags(args)

    if args.command is None:
        parser.print_help()
        sys.exit(2)

    # Inject the root parser so subcommands that need to introspect the full
    # argument tree (e.g., the completion subcommand) can access it without
    # a circular import.
    args.parser = parser

    exit_code = args.func(args)
    if exit_code:
        sys.exit(exit_code)
