"""Shared argparse argument factories for kanon CLI commands.

This module centralises reusable argument definitions so every command
that needs a given flag registers it through the same factory, ensuring
consistent metavar, help text, and default resolution across the CLI.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md`` Section 3
primitives table row 2 (CLI flag + env var for catalog source) and
Section 3.5 (Standards audit and tightening).

Environment-variable coupling: the catalog source default is the single
entry configured in the plural ``KANON_CATALOG_SOURCES`` env var, resolved
via ``kanon_cli.core.catalog.resolve_env_catalog_source`` -- the env var
name is never hard-coded here.

Global flags factory: ``add_global_flags(parser)`` adds the three
spec-required global flags -- ``--quiet``, ``--verbose``, and
``--no-color`` -- to any parser. ``--quiet`` and ``--verbose`` are
mutually exclusive (argparse enforces this; passing both causes an
immediate non-zero exit per spec Section 7 fail-fast rule).
``--no-color`` is independent and takes precedence over the ``NO_COLOR``
env var (spec Section 7 lines 735-746).

The companion ``_apply_global_flags(args)`` translates the parsed
namespace into runtime state: root logger level and the module-level
color-suppression flag in ``kanon_cli.constants._NO_COLOR_ACTIVE``.
"""

import argparse
import logging
import os

import kanon_cli.constants as constants
from kanon_cli.core.catalog import resolve_env_catalog_source


def add_catalog_source_arg(parser: argparse.ArgumentParser) -> None:
    """Add the --catalog-source flag to the given argparse parser.

    The flag accepts a ``<git-url>@<ref>`` string identifying a manifest
    repo at a specific revision. Couples to the plural ``KANON_CATALOG_SOURCES``
    env var via the ``default=`` mechanism: the default is the single source
    configured in ``KANON_CATALOG_SOURCES`` (resolved at parser build time via
    ``resolve_env_catalog_source``). The CLI flag wins when both are set, per
    spec Section 4 header; a ``KANON_CATALOG_SOURCES`` value listing more than
    one source fails fast (the operator must disambiguate with the flag).

    Args:
        parser: The ``ArgumentParser`` (or sub-parser) to extend.
    """
    parser.add_argument(
        "--catalog-source",
        dest="catalog_source",
        default=resolve_env_catalog_source(),
        metavar="<git-url>@<ref>",
        help=(
            "Remote catalog source as '<git_url>@<ref>' where ref is a branch, "
            "tag, or 'latest'. Overrides the KANON_CATALOG_SOURCES env var. "
            "Required when KANON_CATALOG_SOURCES configures no single source."
        ),
    )


def add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Add the global flags --quiet, --verbose, --no-color to the given parser.

    --quiet / --verbose are MUTUALLY EXCLUSIVE; passing both raises an
    argparse error immediately (fail-fast per spec Section 7).

    --no-color disables ANSI color regardless of TTY / NO_COLOR env var
    (precedence: --no-color > NO_COLOR env var > TTY auto-detect).

    Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
    Section 7 lines 735-746 and Section 14 lines 1349-1350.

    Args:
        parser: The ``ArgumentParser`` to extend with global flags.
    """
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        default=False,
        help="Suppress all output except errors. Mutually exclusive with --verbose.",
    )
    verbosity_group.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Enable debug-level output. Mutually exclusive with --quiet.",
    )
    parser.add_argument(
        "--no-color",
        dest="no_color",
        action="store_true",
        default=False,
        help=(
            "Disable ANSI color output. Takes precedence over the NO_COLOR environment variable and TTY auto-detection."
        ),
    )


def _apply_global_flags(args: argparse.Namespace) -> None:
    """Translate parsed args into runtime state.

    - Sets the root logger level: WARNING if args.quiet, DEBUG if
      args.verbose, INFO otherwise.
    - Sets the module-level color-suppression state used by every
      formatter helper (constants._NO_COLOR_ACTIVE) when --no-color is
      set OR when the NO_COLOR env var is non-empty. Precedence:
      --no-color flag > NO_COLOR env var > TTY auto-detect.

    Idempotent: calling twice with the same args produces the same
    state. Fails fast (raises ValueError) if both args.quiet and
    args.verbose are True (defence-in-depth; argparse's mutually
    exclusive group should prevent this case ever reaching the
    helper).

    Args:
        args: The parsed argument namespace from ``argparse.parse_args()``.

    Raises:
        ValueError: If both ``args.quiet`` and ``args.verbose`` are True
            (defence-in-depth guard; argparse mutual exclusion should
            prevent this in normal usage).
    """
    if args.quiet and args.verbose:
        raise ValueError("--quiet and --verbose are mutually exclusive; pass only one of the two flags.")

    if args.quiet:
        level = logging.WARNING
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.getLogger().setLevel(level)

    no_color_active = args.no_color or bool(os.environ.get(constants.NO_COLOR_ENV, ""))
    constants._NO_COLOR_ACTIVE = no_color_active
