"""Catalog directory resolution for Kanon bootstrap.

Resolves the catalog directory from multiple sources in priority order:
  1. ``--catalog-source`` CLI flag
  2. ``KANON_CATALOG_SOURCE`` environment variable
  3. Bundled catalog shipped with the ``kanon_cli`` package

Remote catalog sources use the format ``<git_url>@<ref>`` where ref
can be a branch name, tag, or ``latest`` (resolves to highest semver tag).
"""

import os
import pathlib
import subprocess
import sys
import tempfile

from kanon_cli.constants import CATALOG_ENV_VAR
from kanon_cli.version import resolve_version


def resolve_catalog_dir(catalog_source: str | None = None) -> pathlib.Path:
    """Resolve the catalog directory from flag, env var, or bundled fallback.

    Args:
        catalog_source: Remote catalog source from CLI flag (``<git_url>@<ref>``).

    Returns:
        Path to the resolved catalog directory.

    Raises:
        SystemExit: If the remote catalog cannot be cloned or has no ``catalog/`` dir.
        ValueError: If the catalog source format is invalid.
    """
    source = catalog_source or os.environ.get(CATALOG_ENV_VAR)

    if source:
        return _clone_remote_catalog(source)

    return _get_bundled_catalog_dir()


def _get_bundled_catalog_dir() -> pathlib.Path:
    """Return the path to the bundled catalog shipped with the package.

    Returns:
        Absolute path to the bundled catalog directory.
    """
    return pathlib.Path(__file__).parent.parent / "catalog"


def _parse_catalog_source(source: str) -> tuple[str, str]:
    """Parse a catalog source string into URL and ref.

    The format is ``<git_url>@<ref>`` where the last ``@`` is the delimiter.
    This handles SSH URLs like ``git@github.com:org/repo.git@main``.

    Args:
        source: Catalog source string.

    Returns:
        Tuple of (url, ref).

    Raises:
        ValueError: If the format is invalid (no ``@`` or empty ref).
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
        resolved = resolve_version(url, "*")
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
