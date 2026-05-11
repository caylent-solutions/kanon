"""Shared argparse argument factories for kanon CLI commands.

This module centralises reusable argument definitions so every command
that needs a given flag registers it through the same factory, ensuring
consistent metavar, help text, and default resolution across the CLI.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md`` Section 3
primitives table row 2 (CLI flag + env var for catalog source) and
Section 3.5 (Standards audit and tightening).

Environment-variable coupling: the ``KANON_CATALOG_SOURCE`` env var
name is sourced from ``kanon_cli.constants.CATALOG_ENV_VAR`` -- never
hard-coded here.
"""

import argparse
import os

from kanon_cli.constants import CATALOG_ENV_VAR


def add_catalog_source_arg(parser: argparse.ArgumentParser) -> None:
    """Add the --catalog-source flag to the given argparse parser.

    The flag accepts a ``<git-url>@<ref>`` string identifying a manifest
    repo at a specific revision. Couples to the ``KANON_CATALOG_SOURCE``
    env var via the ``default=`` mechanism (the env var is read at parser
    build time; CLI flag wins when both are set, per spec Section 4
    header).

    Args:
        parser: The ``ArgumentParser`` (or sub-parser) to extend.
    """
    parser.add_argument(
        "--catalog-source",
        dest="catalog_source",
        default=os.environ.get(CATALOG_ENV_VAR),
        metavar="<git-url>@<ref>",
        help=(
            "Remote catalog source as '<git_url>@<ref>' where ref is a branch, "
            "tag, or 'latest'. Overrides KANON_CATALOG_SOURCE env var. "
            "Default: bundled catalog."
        ),
    )
