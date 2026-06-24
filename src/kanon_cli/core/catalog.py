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

from kanon_cli import constants
from kanon_cli.constants import (
    ANSI_RESET,
    ANSI_YELLOW,
    CATALOG_DEFAULT_BRANCH_AUTO,
    CATALOG_DEFAULT_BRANCH_DEFAULT,
    CATALOG_DEFAULT_BRANCH_ENV_VAR,
    CATALOG_DEFAULT_BRANCH_SYMREF_ABSENT_ERROR_TEMPLATE,
    CATALOG_DEFAULT_BRANCH_WARN_TEMPLATE,
    CATALOG_SOURCES_ENV_VAR,
)
from kanon_cli.version import (
    _list_branch_head,
    _resolve_symref_default_branch,
    is_version_constraint,
    resolve_version,
)


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


class DefaultBranchResolutionError(RuntimeError):
    """Raised when the default-branch precedence cannot resolve a usable branch.

    Covers two fail-fast cases (spec Section 6, no fallback):

    - ``auto`` resolution found no ``ref: refs/heads/...`` HEAD symref advertised
      by the remote (the symref-absent error names the operator's next step).
    - A defaulted branch (chosen by precedence steps 2-4) does not exist on the
      remote when its existence is verified.

    The calling command writes ``str(exc)`` to stderr and exits non-zero.
    """


def resolve_default_branch(
    url: str,
    *,
    inline_ref: str | None,
    flag_value: str | None,
    warned_urls: set[str] | None = None,
) -> str:
    """Resolve the ref for a catalog source via the default-branch precedence.

    Implements the shared precedence used wherever a ref is omitted (spec
    Section 6 / FR-26 / FR-27), first match wins:

    1. Inline ``@ref`` on the source entry / command (``inline_ref``).
    2. ``--catalog-default-branch`` flag value (``flag_value``).
    3. ``KANON_CATALOG_DEFAULT_BRANCH`` env (default ``main``).
    4. If the chosen default is the literal ``auto``, resolve the remote HEAD
       symref via ``git ls-remote --symref <url> HEAD`` (routed through the
       shared :func:`kanon_cli.version._resolve_symref_default_branch`); a remote
       that advertises no HEAD symref fails fast with the actionable
       symref-absent error.

    When the ref comes from an explicit inline ``@ref`` (step 1) it is returned
    verbatim with no existence check and no WARN: the operator pinned it. When
    the ref is *defaulted* (any of steps 2-4) it is verified to exist on the
    remote (reusing :func:`kanon_cli.version._list_branch_head`) and a single
    yellow WARN naming the branch is written to stderr, deduped to once per
    defaulted source per invocation via ``warned_urls`` so ``--format json`` and
    piped stdout stay clean.

    Args:
        url: Git repository URL of the catalog source.
        inline_ref: The inline ``@ref`` pinned on the source entry / command, or
            ``None`` when the source omits a ref.
        flag_value: The ``--catalog-default-branch`` flag value, or ``None`` when
            the flag was not supplied.
        warned_urls: Mutable set of URLs that have already emitted the
            defaulted-branch WARN in this invocation. Each defaulted ``url`` is
            added on first WARN so the warning fires once per defaulted source.
            Pass a shared set across a multi-source ``search`` invocation; omit
            (``None``) for a single-source ``add`` to warn unconditionally.

    Returns:
        The resolved ref: the verbatim ``inline_ref`` when pinned, otherwise the
        verified defaulted branch name.

    Raises:
        DefaultBranchResolutionError: When ``auto`` resolution finds no HEAD
            symref, or when a defaulted branch does not exist on the remote.
    """
    if inline_ref is not None:
        return inline_ref

    default = (
        flag_value
        if flag_value is not None
        else os.environ.get(CATALOG_DEFAULT_BRANCH_ENV_VAR, CATALOG_DEFAULT_BRANCH_DEFAULT)
    )

    if default == CATALOG_DEFAULT_BRANCH_AUTO:
        branch = _resolve_symref_default_branch(url)
        if branch is None:
            raise DefaultBranchResolutionError(CATALOG_DEFAULT_BRANCH_SYMREF_ABSENT_ERROR_TEMPLATE.format(url=url))
    else:
        branch = default

    _verify_defaulted_branch_exists(url, branch)
    _warn_defaulted_branch(url, branch, warned_urls)
    return branch


def _verify_defaulted_branch_exists(url: str, branch: str) -> None:
    """Verify a defaulted branch exists on the remote, failing fast if absent.

    Reuses :func:`kanon_cli.version._list_branch_head` (a single
    ``git ls-remote refs/heads/<branch>`` lookup) so the branch-existence path is
    not duplicated (DRY). A missing branch is re-raised as a
    :class:`DefaultBranchResolutionError` so the calling command surfaces a
    single actionable error type (spec Section 6 "verified to exist (fail fast)").

    Args:
        url: Git repository URL of the catalog source.
        branch: The defaulted branch name (no ``refs/heads/`` prefix).

    Raises:
        DefaultBranchResolutionError: When the branch is not found on the remote,
            or when the underlying ``git ls-remote`` lookup fails.
    """
    try:
        _list_branch_head(url, branch)
    except (ValueError, RuntimeError) as exc:
        raise DefaultBranchResolutionError(str(exc)) from exc


def _warn_defaulted_branch(url: str, branch: str, warned_urls: set[str] | None) -> None:
    """Emit a single deduped yellow WARN naming the defaulted branch to stderr.

    The WARN announces the branch chosen by the default-branch precedence for a
    source that omitted its ``@ref`` (spec Section 6). It is written to stderr
    only, so ``--format json`` / piped stdout is never corrupted, and is deduped
    to once per defaulted ``url`` when ``warned_urls`` is supplied (a multi-source
    ``search`` invocation). The text is rendered in ANSI yellow unless color is
    suppressed via ``constants._NO_COLOR_ACTIVE`` (the ``--no-color`` flag or a
    non-empty ``NO_COLOR`` env var).

    Args:
        url: Git repository URL of the defaulted source.
        branch: The resolved defaulted branch name.
        warned_urls: Mutable dedup set, or ``None`` to warn unconditionally.
    """
    if warned_urls is not None:
        if url in warned_urls:
            return
        warned_urls.add(url)

    message = CATALOG_DEFAULT_BRANCH_WARN_TEMPLATE.format(url=url, branch=branch)
    if not constants._NO_COLOR_ACTIVE:
        message = f"{ANSI_YELLOW}{message}{ANSI_RESET}"
    print(message, file=sys.stderr)


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


def resolve_env_catalog_sources() -> list[str]:
    """Return the full plural ``KANON_CATALOG_SOURCES`` discovery set.

    Reads and parses ``KANON_CATALOG_SOURCES`` (plural) via
    :func:`parse_catalog_sources` and returns every configured source as a raw,
    deduplicated ``<url>@<ref>`` string in first-seen order. Unlike
    :func:`resolve_env_catalog_source` (singular), this resolver is
    multi-source-tolerant: it never raises :class:`MultipleCatalogSourcesError`.
    It is the discovery set consumed by ``kanon search``, which enumerates every
    configured source concurrently (spec Section 4.1 / FR-9 / FR-25).

    Returns:
        Order-preserving, deduplicated list of ``<url>@<ref>`` source strings.
        Empty when the env var is unset or contains only blank lines.

    Raises:
        ValueError: When a configured entry is malformed (propagated from
            :func:`parse_catalog_sources`); a bad entry is never silently
            skipped (fail fast, spec Section 4.1 "Errors").
    """
    raw = os.environ.get(CATALOG_SOURCES_ENV_VAR)
    entries = parse_catalog_sources(raw)
    return [f"{url}@{ref}" for url, ref in entries]


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
