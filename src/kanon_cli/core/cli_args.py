"""Shared argparse argument factories for kanon CLI commands.

This module centralises reusable argument definitions so every command
that needs a given flag registers it through the same factory, ensuring
consistent metavar, help text, and default resolution across the CLI.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md`` Section 3
primitives table row 2 (CLI flag + env var for catalog source) and
Section 3.5 (Standards audit and tightening).

Environment-variable coupling: the ``--catalog-source`` flag carries a lazy
``default=None``; it never reads ``KANON_CATALOG_SOURCES`` at parser-build time.
Each command resolves the env var inside its own handler (single-source commands
via ``kanon_cli.core.catalog.resolve_env_catalog_source`` when exactly one source
is configured; ``search`` via ``resolve_env_catalog_sources`` for the plural
discovery set). Reading the env var at parser-build time is forbidden: a
``KANON_CATALOG_SOURCES`` value listing more than one source would otherwise raise
``MultipleCatalogSourcesError`` while *building* the parser, making the whole CLI
uninvokable for every command (add/search/doctor/why/outdated) -- the resolution
must be deferred to the handler so multi-source configs only fail (or succeed, for
``search``) at the point a single source is actually required.

Global flags factory: ``add_global_flags(parser)`` adds the
spec-required global flags -- ``--quiet``, ``--verbose``, ``--no-color``,
and ``--no-update-check`` -- to any parser. ``--quiet`` and ``--verbose``
are mutually exclusive (argparse enforces this; passing both causes an
immediate non-zero exit per spec Section 7 fail-fast rule).
``--no-color`` is independent and takes precedence over the ``NO_COLOR``
env var (spec Section 7 lines 735-746). ``--no-update-check`` (spec
Section 7.1 / FR-29) suppresses the best-effort "update available" PyPI
lookup for the invocation; it is read directly by the update-check hook
in ``cli.main`` (via ``kanon_cli.core.update_check.should_skip``) and so
needs no translation in ``_apply_global_flags``.

The companion ``_apply_global_flags(args)`` translates the parsed
namespace into runtime state: root logger level and the module-level
color-suppression flag in ``kanon_cli.constants._NO_COLOR_ACTIVE``.
"""

import argparse
import logging
import os
import pathlib

import kanon_cli.constants as constants


_CATALOG_SOURCE_HELP = (
    "Remote catalog source as '<git_url>@<ref>' where ref is a branch, "
    "tag, or 'latest'. Overrides the KANON_CATALOG_SOURCES env var. "
    "Required when KANON_CATALOG_SOURCES configures no single source."
)

_CATALOG_SOURCE_HELP_MULTIPLE = (
    _CATALOG_SOURCE_HELP + " May be repeated to search several sources; "
    "the supplied flags fully replace KANON_CATALOG_SOURCES for this invocation."
)


_CATALOG_DEFAULT_BRANCH_HELP = (
    "Branch to use for a catalog source supplied without an '@ref'. "
    "Precedence: an inline '@ref' on the source > this flag > the "
    "KANON_CATALOG_DEFAULT_BRANCH env var (default 'main') > the literal "
    "'auto', which resolves the remote HEAD symref via "
    "'git ls-remote --symref'. A defaulted branch is verified to exist on the "
    "remote (fail fast) and a single WARNING naming it is written to stderr."
)


def add_catalog_default_branch_arg(parser: argparse.ArgumentParser) -> None:
    """Add the --catalog-default-branch flag to the given argparse parser.

    The flag carries the tier-2 value of the default-branch precedence used
    wherever a ``--catalog-source`` omits its ``@ref`` (spec Section 6 / FR-26 /
    FR-27): an inline ``@ref`` wins over this flag, which wins over the
    ``KANON_CATALOG_DEFAULT_BRANCH`` env var (default ``main``), which falls back
    to the literal ``auto`` (remote HEAD symref resolution). The flag carries a
    lazy ``default=None`` so the env var is consulted only when the flag is
    absent; the resolution itself is performed by
    :func:`kanon_cli.core.catalog.resolve_default_branch` inside each command
    handler, not at parser-build time.

    Args:
        parser: The ``ArgumentParser`` (or sub-parser) to extend.
    """
    parser.add_argument(
        "--catalog-default-branch",
        dest="catalog_default_branch",
        default=None,
        metavar="<branch>",
        help=_CATALOG_DEFAULT_BRANCH_HELP,
    )


def add_catalog_source_arg(parser: argparse.ArgumentParser, *, allow_multiple: bool = False) -> None:
    """Add the --catalog-source flag to the given argparse parser.

    The flag accepts a ``<git-url>@<ref>`` string identifying a manifest repo at
    a specific revision. The flag carries a lazy ``default=None`` and never reads
    ``KANON_CATALOG_SOURCES`` at parser-build time: each command resolves the env
    var inside its own handler (single-source commands when exactly one source is
    configured; ``search`` for the plural discovery set). This deferral is
    mandatory -- reading the env var here would raise ``MultipleCatalogSourcesError``
    while *building* the parser whenever more than one source is configured,
    crashing every command before it can run.

    Args:
        parser: The ``ArgumentParser`` (or sub-parser) to extend.
        allow_multiple: When True (used by ``search``), the flag is repeatable
            (``action="append"``): each ``--catalog-source`` occurrence appends to
            a list, so ``args.catalog_source`` is a ``list[str] | None``. When
            False (the single-source default for add/why/outdated/doctor), the flag
            is single-valued and ``args.catalog_source`` is a ``str | None``.
    """
    if allow_multiple:
        parser.add_argument(
            "--catalog-source",
            dest="catalog_source",
            action="append",
            default=None,
            metavar="<git-url>@<ref>",
            help=_CATALOG_SOURCE_HELP_MULTIPLE,
        )
    else:
        parser.add_argument(
            "--catalog-source",
            dest="catalog_source",
            default=None,
            metavar="<git-url>@<ref>",
            help=_CATALOG_SOURCE_HELP,
        )


def add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Add the global flags --quiet, --verbose, --no-color to the given parser.

    --quiet / --verbose are MUTUALLY EXCLUSIVE; passing both raises an
    argparse error immediately (fail-fast per spec Section 7).

    --no-color disables ANSI color regardless of TTY / NO_COLOR env var
    (precedence: --no-color > NO_COLOR env var > TTY auto-detect).

    --no-update-check skips the best-effort "update available" PyPI lookup
    for the invocation (spec Section 7.1 / FR-29); it is equivalent to
    setting KANON_SKIP_UPDATE_CHECK=1 and is consumed by the update-check
    pre-dispatch hook in cli.main, not by _apply_global_flags.

    Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
    Section 7 lines 735-746 and Section 14 lines 1349-1350; spec
    ``kanon-refinements.md`` Section 7.1 (update alert) for --no-update-check.

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
    parser.add_argument(
        "--no-update-check",
        dest="no_update_check",
        action="store_true",
        default=False,
        help=(
            "Skip the best-effort 'update available' PyPI lookup for this invocation. "
            "Equivalent to setting KANON_SKIP_UPDATE_CHECK=1."
        ),
    )
    parser.add_argument(
        "--home",
        "--store-dir",
        dest="home",
        type=pathlib.Path,
        default=None,
        metavar="<path>",
        help=(
            "Use <path> as the shared kanon home root (the content-addressed store and "
            "caches live under it). Takes precedence over the KANON_HOME environment variable "
            "and the ~/.kanon-home default. --store-dir is an accepted alias."
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
    - Injects the ``--home`` / ``--store-dir`` flag (when given) into
      ``KANON_HOME`` in the process environment so every downstream
      ``constants.resolve_kanon_home()`` reader (the store base dir, the
      completion / catalog-audit caches, the update-check cache) honors it
      with precedence ``--home`` flag > ``KANON_HOME`` env > ``~/.kanon-home``
      default. The flag value fully replaces any inherited ``KANON_HOME``
      for the invocation.

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

    home_override = getattr(args, "home", None)
    if home_override is not None:
        os.environ[constants.KANON_HOME_ENV_VAR] = str(constants.resolve_kanon_home(override=home_override))
