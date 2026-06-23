"""Catalog directory resolution for Kanon.

Resolves the catalog directory from an explicit ``<git_url>@<ref>`` catalog
source (supplied by the ``--catalog-source`` CLI flag, or by the single entry
configured in the plural ``KANON_CATALOG_SOURCES`` environment variable). No
default catalog source exists; when none is supplied, the resolver raises
``MissingCatalogSourceError`` per spec Section 4 and Section 13 decision 19 (no
default manifest repo).

``KANON_CATALOG_SOURCES`` (plural, spec Section 6 / Section 7.1 / FR-9) is a
newline-delimited list of ``url[@ref]`` entries: surrounding whitespace per
line is trimmed, blank lines are skipped, and identical entries are
deduplicated while preserving first-seen order. A malformed (non-blank) entry
fails fast with a clear message naming the offending line. This is the
discovery set that browse/search commands enumerate; the single-source
commands (``add``, ``list``) consume it only when exactly one entry is
configured (spec Section 4.2).

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

from kanon_cli.constants import CATALOG_SOURCES_ENV_VAR
from kanon_cli.version import is_version_constraint, resolve_version


class MissingCatalogSourceError(ValueError):
    """Raised when resolve_catalog_dir cannot determine a catalog source.

    No ``--catalog-source`` CLI flag and no single ``KANON_CATALOG_SOURCES``
    entry were supplied. The calling command catches this exception, formats
    the canonical spec Section 4 missing-source error text with its own command
    name, writes it to stderr, and exits 1.
    """


class MultipleCatalogSourcesError(ValueError):
    """Raised when a single-source command finds more than one configured source.

    Commands that operate on exactly one catalog source (``add``, ``list``)
    read the single entry from ``KANON_CATALOG_SOURCES`` only when exactly one
    is configured (spec Section 4.2). When the env var lists several entries and
    no ``--catalog-source`` flag disambiguates, the command fails fast rather
    than silently picking one. The message names every configured source so the
    operator can re-run with an explicit ``--catalog-source``.
    """


def parse_catalog_sources(raw: str | None) -> list[tuple[str, str]]:
    """Parse the plural ``KANON_CATALOG_SOURCES`` value into ``(url, ref)`` entries.

    The value is a newline-delimited list of ``url[@ref]`` entries (spec
    Section 6 / FR-9). Surrounding whitespace on each line is trimmed, blank
    (whitespace-only) lines are skipped, and identical entries are deduplicated
    while preserving first-seen order. Each surviving entry is split into
    ``(url, ref)`` by the shared :func:`_parse_catalog_source` splitter, so the
    ``<git_url>@<ref>`` ``@``-delimiter logic is defined once (DRY).

    A malformed (non-blank) entry fails fast: the ``ValueError`` raised by
    :func:`_parse_catalog_source` is re-raised with the offending line named, so
    a bad entry is never silently skipped (only blank lines are skipped).

    Args:
        raw: The raw ``KANON_CATALOG_SOURCES`` value, or ``None`` when unset.

    Returns:
        Order-preserving, deduplicated list of ``(url, ref)`` tuples. Empty when
        ``raw`` is ``None`` or contains only blank lines.

    Raises:
        ValueError: When a non-blank entry is not a valid ``<git_url>@<ref>``
            string; the message names the offending line.
    """
    if raw is None:
        return []

    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        entry = line.strip()
        if not entry:
            continue
        if entry in seen:
            continue
        seen.add(entry)
        try:
            parsed.append(_parse_catalog_source(entry))
        except ValueError as exc:
            msg = f"Invalid {CATALOG_SOURCES_ENV_VAR} entry {entry!r}: {exc}"
            raise ValueError(msg) from exc
    return parsed


def resolve_env_catalog_source() -> str | None:
    """Return the single catalog source configured in ``KANON_CATALOG_SOURCES``.

    Reads and parses ``KANON_CATALOG_SOURCES`` (plural) via
    :func:`parse_catalog_sources`. The single-source commands (``add``,
    ``list``) use this when no ``--catalog-source`` flag was supplied; per spec
    Section 4.2 the env var is consumed only when it configures exactly one
    source.

    Returns:
        The single configured ``<url>@<ref>`` source string (the raw,
        deduplicated entry), or ``None`` when the env var is unset or contains
        only blank lines.

    Raises:
        MultipleCatalogSourcesError: When more than one distinct source is
            configured (the caller must disambiguate with ``--catalog-source``).
        ValueError: When a configured entry is malformed (propagated from
            :func:`parse_catalog_sources`).
    """
    raw = os.environ.get(CATALOG_SOURCES_ENV_VAR)
    entries = parse_catalog_sources(raw)
    if not entries:
        return None
    if len(entries) > 1:
        rendered = ", ".join(f"{url}@{ref}" for url, ref in entries)
        msg = (
            f"{CATALOG_SOURCES_ENV_VAR} configures {len(entries)} catalog sources "
            f"({rendered}); this command operates on a single source. "
            "Pass --catalog-source <git-url>@<ref> to select one."
        )
        raise MultipleCatalogSourcesError(msg)
    url, ref = entries[0]
    return f"{url}@{ref}"


def resolve_catalog_dir(catalog_source: str | None = None) -> pathlib.Path:
    """Resolve the catalog directory from a ``<git_url>@<ref>`` catalog source.

    When ``catalog_source`` is ``None`` the single entry configured in
    ``KANON_CATALOG_SOURCES`` is used (spec Section 4.2). Raises
    ``MissingCatalogSourceError`` when no source is supplied. See spec Section 4.

    Args:
        catalog_source: Remote catalog source (``<git_url>@<ref>``). When
            ``None``, the single ``KANON_CATALOG_SOURCES`` entry is resolved.

    Returns:
        Path to the resolved catalog directory.

    Raises:
        MissingCatalogSourceError: When no catalog source is supplied or
            configured.
        MultipleCatalogSourcesError: When ``KANON_CATALOG_SOURCES`` lists more
            than one source and no explicit ``catalog_source`` disambiguates.
        SystemExit: If the remote catalog cannot be cloned or has no ``catalog/`` dir.
        ValueError: If the catalog source format is invalid.
    """
    source = catalog_source or resolve_env_catalog_source()

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
