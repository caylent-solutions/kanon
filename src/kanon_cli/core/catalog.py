"""Catalog directory resolution for Kanon.

Resolves the catalog directory from the ``--catalog-source`` CLI flag or
the ``KANON_CATALOG_SOURCE`` environment variable. No default catalog source
exists; when neither is set, the resolver raises ``MissingCatalogSourceError``
per spec Section 4 and Section 13 decision 19 (no default manifest repo).

Remote catalog sources use the format ``<git_url>@<ref>`` where ref
can be a branch name, tag, or ``latest`` (resolves to highest semver tag).
The ``@`` delimiter is always the LAST ``@`` in the source string, which
allows SSH URLs containing a user-info ``@`` (e.g. ``git@host:org/repo.git@main``)
to be parsed unambiguously.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

from kanon_cli.constants import CATALOG_ENV_VAR
from kanon_cli.version import is_version_constraint, resolve_version


class MissingCatalogSourceError(ValueError):
    """Raised when resolve_catalog_dir cannot determine a catalog source.

    Neither the ``--catalog-source`` CLI flag nor the ``KANON_CATALOG_SOURCE``
    environment variable was set. The calling command catches this exception,
    formats the canonical spec Section 4 missing-source error text with its
    own command name, writes it to stderr, and exits 1.
    """


def resolve_catalog_dir(catalog_source: str | None = None) -> pathlib.Path:
    """Resolve the catalog directory from the ``--catalog-source`` flag or ``KANON_CATALOG_SOURCE`` env var.

    Raises ``MissingCatalogSourceError`` when neither is set. See spec Section 4.

    Args:
        catalog_source: Remote catalog source from CLI flag (``<git_url>@<ref>``).

    Returns:
        Path to the resolved catalog directory.

    Raises:
        MissingCatalogSourceError: When neither the CLI flag nor the env var is set.
        SystemExit: If the remote catalog cannot be cloned or has no ``catalog/`` dir.
        ValueError: If the catalog source format is invalid.
    """
    source = catalog_source or os.environ.get(CATALOG_ENV_VAR)

    if source:
        return _clone_remote_catalog(source)

    raise MissingCatalogSourceError()


def _parse_catalog_source(source: str) -> tuple[str, str]:
    """Parse a catalog source string into URL and ref.

    The format is ``<git_url>@<ref>`` where the last ``@`` is the delimiter.
    This handles SSH URLs like ``git@github.com:org/repo.git@main``.

    Args:
        source: Catalog source string.

    Returns:
        Tuple of (url, ref).

    Raises:
        ValueError: If the format is invalid (no ``@`` or empty ref), if the
            ref or URL component is empty, or if the URL portion contains
            neither ``://`` nor ``@`` (indicating the source is an SSH-shorthand
            URL with no ref separator, e.g. ``git@host:org/repo.git`` with no
            trailing ``@<ref>``).
    """
    idx = source.rfind("@")
    if idx == -1:
        msg = (
            f"Invalid catalog source format: '{source}'. "
            "Expected '<git_url>@<ref>' (e.g. 'https://github.com/org/repo.git@main')"
        )
        raise ValueError(msg)

    url = source[:idx]
    ref = source[idx + 1 :]

    if not ref:
        msg = (
            f"Empty ref in catalog source: '{source}'. "
            "Expected '<git_url>@<ref>' (e.g. 'https://github.com/org/repo.git@v1.0.0')"
        )
        raise ValueError(msg)

    if not url:
        msg = f"Empty URL in catalog source: '{source}'"
        raise ValueError(msg)

    # Guard: if the URL portion contains neither '://' (scheme separator) nor '@'
    # (user-info separator), the rfind hit a user-info '@' that is part of the URL
    # itself (e.g. 'git@host:org/repo.git' with no ref), not a ref delimiter.
    # Spec Section 4.0: the ref separator is always the LAST '@'; if no unambiguous
    # ref delimiter exists, the source is malformed.
    if "://" not in url and "@" not in url:
        msg = (
            f"Invalid catalog source format: '{source}'. "
            "No ref separator '@' found after the URL -- "
            "expected '<git_url>@<ref>' (e.g. 'git@host:org/repo.git@main')"
        )
        raise ValueError(msg)

    return url, ref


def _clone_remote_catalog(source: str) -> pathlib.Path:
    """Clone a remote catalog repo and return the catalog directory path.

    Args:
        source: Catalog source string (``<git_url>@<ref>``).

    Returns:
        Path to the ``catalog/`` directory inside the cloned repo.

    Raises:
        SystemExit: If git clone fails or the repo has no ``catalog/`` directory.
        ValueError: If the source format is invalid.
    """
    url, ref = _parse_catalog_source(source)

    if ref == "latest":
        ref = "*"
    if is_version_constraint(ref):
        resolved = resolve_version(url, ref)
        ref = resolved.removeprefix("refs/tags/")

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-catalog-"))

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, url, str(clone_dir / "repo")],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"Error: Failed to clone catalog from {url}@{ref}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    catalog_path = clone_dir / "repo" / "catalog"
    if not catalog_path.is_dir():
        print(
            f"Error: Remote repo {url}@{ref} does not contain a 'catalog/' directory",
            file=sys.stderr,
        )
        sys.exit(1)

    return catalog_path
