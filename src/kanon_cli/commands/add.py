"""kanon add subcommand: append alias-keyed dependency blocks to a .kanon file.

Resolves one or more catalog entries from a manifest repo and writes the
alias-keyed KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE} block to the
destination .kanon file (spec Section 5.1 / FR-5, FR-6), plus an optional
per-dependency ``KANON_SOURCE_<alias>_MARKETPLACE=true`` line when the entry is
(or is forced to) a Claude marketplace (spec Section 4.2 / FR-17). There is no
global ``[catalog]`` block and no standard header: the per-dependency blocks
fully replace the single global header, so ``add`` writes neither a global
marketplace-install header line nor a ``GITBASE`` header line. The ``GITBASE``
org base is recorded per dependency in ``KANON_SOURCE_<alias>_GITBASE``.

Spec reference: ``specs/kanon-refinements.md`` Section 5.1 (alias-keyed
``.kanon`` blocks, ``_REVISION`` -> ``_REF``, ``_NAME`` / ``_GITBASE``, no
``[catalog]``), Section 4.2 (``add`` alias keying), plus
``spec/kanon-list-add-lock-features-spec.md`` Section 4.0 (last-@ spec split),
Section 4.2 collision detection pre-flight, Section 4.2 flag-table rows
--force and --dry-run.
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

from packaging.version import InvalidVersion, Version

from kanon_cli.constants import (
    CATALOG_TYPE_CLAUDE_MARKETPLACE,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    MARKETPLACE_FLAG_TRUE,
    MISSING_CATALOG_ERROR_TEMPLATE,
    SOURCE_MARKETPLACE_SUFFIX,
    SOURCE_PATH_SUFFIX,
    SOURCE_PREFIX,
    SOURCE_REF_SUFFIX,
    SOURCE_SUFFIXES,
    SOURCE_URL_SUFFIX,
    TAG_ERROR_DISPLAY_CAP,
)
from kanon_cli.core.catalog import _parse_catalog_source, resolve_env_catalog_source
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.kanon_hash import kanon_hash
from kanon_cli.core.install import _resolve_ref_to_sha, read_lockfile_if_present
from kanon_cli.core.lockfile import write_lockfile
from kanon_cli.utils.concurrency import kanon_workspace_lock
from kanon_cli.utils.lock_file_path import derive_lock_file_path
from kanon_cli.core.metadata import (
    CatalogMetadata,
    CatalogMetadataParseError,
    _parse_catalog_metadata,
    derive_source_name,
    find_catalog_entry_files,
)
from kanon_cli.version import _list_tags, _resolve_constraint_from_tags, is_version_constraint, resolve_version

# Spec-verbatim error emitted when the manifest repo has no PEP 440-valid tags
# and the operator did not supply an explicit @<spec> constraint.
# Spec reference: kanon-list-add-lock-features-spec.md Section 4.2, step 4.
_ZERO_PEP440_TAGS_ERROR = (
    "manifest repo has no PEP 440-valid tags; pin to a branch or SHA"
    " explicitly (e.g., 'kanon add foo@main') or ask the catalog author"
    " to publish a release tag."
)

# Pre-compiled regex for SCP-shorthand git URLs: git@host:org/repo[.git]
# Compiled at module load time to avoid re-compiling on every derivation call.
_SCP_URL_PATTERN = re.compile(r"^(git@[^:]+):([^/]+)/[^/]+(?:\.git)?$")

# Alias charset (spec Section 4.2 / 5.1): a local alias uses only [A-Za-z0-9_]
# with single underscores (never a "__" run). This pattern matches a legal
# fully-formed alias; it is reused to validate the --as override and to verify
# the auto-computed alias never emits a "__".
_ALIAS_CHARSET_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Run of one or more characters that are NOT in the alias charset. Used by the
# suffix sanitizer (spec Section 4.2 / 5.1): every such run collapses to a
# single underscore so a constraint ref like ">=0.1.0,<1.0.0" maps to the alias
# fragment "0_1_0_1_0_0" (never "__").
_NON_ALIAS_CHARS_RE = re.compile(r"[^A-Za-z0-9_]+")


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'add' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "add",
        add_help=True,
        help="Add one or more catalog entries to the .kanon file.",
        description=(
            "Resolve catalog entries from a manifest repo and append the\n"
            "alias-keyed KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE} block\n"
            "to the destination .kanon file. No global header is written.\n\n"
            "Each ENTRY is '<name>' or '<name>@<spec>' where <spec> is a PEP 440\n"
            "constraint (e.g. ==1.0.0, ~=1.2, >=1.0.0,<2.0.0). The last '@' in\n"
            "each argument is the delimiter -- see spec Section 4.0 resolver rules.\n"
            "When <spec> is omitted the highest PEP 440-valid git tag in the\n"
            "manifest repo is selected automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Note: when supplying a PEP 440 range, quote the spec to avoid shell parsing:\n"
            "   kanon add 'package-a@>=1.0,<2.0'"
        ),
    )

    parser.add_argument(
        "entries",
        metavar="<name>[@<spec>]",
        nargs="+",
        help=(
            "One or more catalog entry names, optionally suffixed with '@<spec>'\n"
            "where <spec> is a PEP 440 version constraint. The last '@' is the\n"
            "delimiter (spec Section 4.0). Shell-quote constraints containing\n"
            "special characters such as '>' or '<'."
        ),
    )

    add_catalog_source_arg(parser)

    parser.add_argument(
        "--as",
        dest="alias_override",
        metavar="<alias>",
        default=None,
        help=(
            "Override the auto-computed local alias for the (single) added\n"
            "entry. The alias charset is [A-Za-z0-9_] with no '__' run. When\n"
            "the alias is already mapped to a different source it is a hard\n"
            "error (use --force to overwrite, or 'kanon remove <alias>'\n"
            "first). Without --as, the alias is the sanitized manifest name,\n"
            "auto-suffixed deterministically on a cross-source collision."
        ),
    )

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT),
        metavar="<path>",
        help=(
            f"Destination .kanon file path. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help=(
            "Overwrite an existing alias block when re-adding the same\n"
            "package (same source@ref), and re-pin its .kanon.lock entry\n"
            "while keeping the dep's NAME. Without this flag, a re-add of an\n"
            "existing alias is a hard error (with a diff and the guiding\n"
            "message). A cross-source collision (a different source for the\n"
            "same manifest name) is auto-suffixed deterministically and is\n"
            "never an error, with or without --force."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Print the diff that WOULD be written to the destination\n"
            ".kanon file ('+' for added lines, '-' for removed lines when a\n"
            "--force overwrite replaces an existing block). Makes no on-disk\n"
            "change. Exits 0. Alias resolution still runs first, so a\n"
            "within-request duplicate or a re-add of an existing alias\n"
            "(without --force) is reported before any diff is shown."
        ),
    )

    # Per-dependency marketplace-install override flags (spec Section 4.2 /
    # FR-17). They are mutually exclusive: --marketplace-install forces the added
    # dependency's KANON_SOURCE_<alias>_MARKETPLACE line on (a pretty error, not a
    # crash, when the catalog entry is not a marketplace type);
    # --no-marketplace-install forces it off (the line is omitted). When neither
    # flag is supplied the value is auto-detected from <catalog-metadata><type>.
    marketplace_group = parser.add_mutually_exclusive_group()
    marketplace_group.add_argument(
        "--marketplace-install",
        dest="marketplace_install",
        action="store_const",
        const=True,
        default=None,
        help=(
            "Force the added dependency to register as a Claude marketplace\n"
            "(write KANON_SOURCE_<alias>_MARKETPLACE=true), overriding the\n"
            "auto-detected <catalog-metadata><type>. Errors if the entry is not\n"
            f"a '{CATALOG_TYPE_CLAUDE_MARKETPLACE}' type. Mutually exclusive with\n"
            "--no-marketplace-install."
        ),
    )
    marketplace_group.add_argument(
        "--no-marketplace-install",
        dest="marketplace_install",
        action="store_const",
        const=False,
        help=(
            "Force the added dependency to NOT register as a marketplace (omit\n"
            "the KANON_SOURCE_<alias>_MARKETPLACE line), overriding the\n"
            "auto-detected <catalog-metadata><type>. Mutually exclusive with\n"
            "--marketplace-install."
        ),
    )

    parser.set_defaults(func=run_add)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CatalogSourceURLDerivationError(ValueError):
    """Raised when GITBASE cannot be derived from the catalog-source URL.

    Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
    Section 4 E28 + CLAUDE.md Error Handling Contract.

    Args:
        url: The catalog-source URL that could not be parsed.
        reason: A human-readable explanation of why derivation failed.
    """

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: cannot derive GITBASE from catalog-source URL {self.url}: {self.reason}\n"
            "Pass an explicit GITBASE via the KANON_GITBASE env var or"
            " hand-edit .kanon after running kanon add."
        )


class AliasOverrideError(ValueError):
    """Raised when an explicit ``--as`` alias is not a legal local alias.

    Spec reference: ``specs/kanon-refinements.md`` Section 4.2 (``--as <alias>``
    override; charset ``[A-Za-z0-9_]``, no ``__``) + CLAUDE.md Error Handling
    Contract.

    Args:
        alias: The rejected ``--as`` value.
        reason: A human-readable explanation of why the alias is illegal.
    """

    def __init__(self, alias: str, reason: str) -> None:
        self.alias = alias
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: invalid --as alias {self.alias!r}: {self.reason}\n"
            "An alias may contain only [A-Za-z0-9_] and must not contain a"
            " '__' run; pick a different --as value."
        )


class MarketplaceInstallError(ValueError):
    """Raised when ``--marketplace-install`` is forced on a non-marketplace entry.

    Spec reference: ``specs/kanon-refinements.md`` Section 4.2 (``add``
    marketplace auto-detect / FR-17: ``--marketplace-install`` is a pretty error,
    not a crash, when the catalog entry is not a ``claude-marketplace`` type) +
    CLAUDE.md Error Handling Contract.

    Args:
        entry_name: The catalog entry name the operator tried to force on.
        entry_type: The entry's ``<catalog-metadata><type>`` value (``None`` when
            the recommended ``type`` field is absent).
    """

    def __init__(self, entry_name: str, entry_type: str | None) -> None:
        self.entry_name = entry_name
        self.entry_type = entry_type
        super().__init__(str(self))

    def __str__(self) -> str:
        found = "absent" if self.entry_type is None else repr(self.entry_type)
        return (
            f"ERROR: --marketplace-install requires catalog entry "
            f"{self.entry_name!r} to declare "
            f"<catalog-metadata><type>{CATALOG_TYPE_CLAUDE_MARKETPLACE}</type>, "
            f"but its type is {found}.\n"
            "Remove --marketplace-install to add it as a regular package, or pick "
            "a marketplace-typed entry."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_gitbase_from_catalog_source(url: str) -> str:
    """Derive the GITBASE value from a catalog-source URL.

    Extracts the scheme + authority (host + optional org/user prefix) from
    the supplied URL. Supports the following URL forms:

    - ``https://host/org/repo(.git)?`` -> ``https://host/org`` (or ``https://host``
      when there is no org path segment before the repo)
    - ``http://host/org/repo(.git)?`` -> ``http://host/org``
    - ``ssh://user@host/org/repo(.git)?`` -> ``ssh://user@host/org``
    - ``git@host:org/repo(.git)?`` (SCP shorthand) -> ``git@host:org``
    - ``file:///path/to/bare-repo`` -> ``file:///path/to`` (parent directory of the repo)

    Args:
        url: The catalog-source URL (without the ``@<ref>`` suffix).

    Returns:
        The derived GITBASE string.

    Raises:
        CatalogSourceURLDerivationError: When no scheme+host can be extracted.
        ValueError: When url is empty or None.
    """
    if not url:
        raise ValueError("catalog-source URL is required for kanon add")

    # SCP-shorthand form: git@host:org/repo(.git)?
    # urllib.parse.urlsplit does not recognise this form, so handle it first.
    scp_match = _SCP_URL_PATTERN.match(url)
    if scp_match:
        host_part = scp_match.group(1)  # e.g. git@github.com
        org_part = scp_match.group(2)  # e.g. my-org
        return f"{host_part}:{org_part}"

    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme:
        raise CatalogSourceURLDerivationError(
            url,
            "URL has no scheme; expected https://, http://, ssh://, git@host:, or file://",
        )

    # file:// URLs have an empty netloc; return scheme:// + parent directory.
    # e.g. file:///tmp/bare-repo.git -> file:///tmp
    if parsed.scheme == "file":
        parent_path = str(pathlib.PurePosixPath(parsed.path).parent)
        return f"{parsed.scheme}://{parsed.netloc}{parent_path}"

    if not parsed.netloc:
        raise CatalogSourceURLDerivationError(
            url,
            f"URL scheme '{parsed.scheme}' has no host/authority component",
        )

    # For https/http/ssh, extract the leading path segment (the org/owner part)
    # before the repository name. The path looks like /org/repo[.git].
    # Strip a leading slash, then take the first segment.
    path_segments = [s for s in parsed.path.split("/") if s]
    if len(path_segments) >= 2:
        # At least org/repo present -- include the org segment.
        org_segment = path_segments[0]
        return f"{parsed.scheme}://{parsed.netloc}/{org_segment}"

    # Only a single path segment (just the repo, no org prefix) or no path.
    return f"{parsed.scheme}://{parsed.netloc}"


def _split_name_spec(raw: str) -> tuple[str, str | None]:
    """Split a raw positional argument on the last '@'.

    Per spec Section 4.0, the split always occurs at the LAST '@' so that
    catalog entry names that include an '@' (e.g. SSH-style git URLs used as
    names) are handled correctly.

    Args:
        raw: The raw positional argument string.

    Returns:
        A 2-tuple (name, spec) where spec is None when no '@' is present.
    """
    idx = raw.rfind("@")
    if idx == -1:
        return raw, None
    name = raw[:idx]
    spec = raw[idx + 1 :]
    return name, spec if spec else None


def _sanitize_alias_fragment(value: str) -> str:
    """Map an arbitrary string to the alias charset as a single fragment.

    Implements the spec Section 4.2 / 5.1 ref-sanitization rule, applied to both
    the source-repo suffix and the ref suffix: lowercase, replace every run of
    one or more characters outside ``[A-Za-z0-9_]`` with a single ``_``, then
    trim leading / trailing ``_``. The result never contains a ``__`` run.

    Examples:
        ``main`` -> ``main``;
        ``>=0.1.0,<1.0.0`` -> ``0_1_0_1_0_0``;
        ``caylent-private-kanon`` -> ``caylent_private_kanon``.

    Args:
        value: The raw fragment (a ref spec or a source-repo name).

    Returns:
        The sanitized alias fragment (possibly empty when ``value`` carried no
        charset characters).
    """
    collapsed = _NON_ALIAS_CHARS_RE.sub("_", value.lower())
    return collapsed.strip("_")


def _source_repo_fragment(url: str) -> str:
    """Return the sanitized source-repo name for the cross-source alias suffix.

    Extracts the repository name from the catalog-source URL -- the last path
    segment with any trailing ``.git`` removed -- and sanitizes it to the alias
    charset (spec Section 4.2: ``caylent/caylent-private-kanon.git`` ->
    ``caylent_private_kanon``). Both ``/`` (https/ssh/file) and ``:`` (SCP
    shorthand ``git@host:org/repo``) are treated as path separators so the bare
    repo name is isolated before sanitization.

    Args:
        url: The catalog-source URL (without the ``@<ref>`` suffix).

    Returns:
        The sanitized source-repo fragment for use as an alias suffix.
    """
    # Normalise both separators so the final segment is the repo name regardless
    # of URL form. SCP shorthand (git@host:org/repo) uses ':' before the path.
    tail = url.replace(":", "/").rstrip("/").rsplit("/", 1)[-1]
    repo_name = tail.removesuffix(".git")
    return _sanitize_alias_fragment(repo_name)


def _validate_alias_override(alias: str) -> str:
    """Validate an explicit ``--as`` override and return it unchanged.

    Enforces the spec Section 4.2 alias charset: non-empty, only ``[A-Za-z0-9_]``,
    and no ``__`` run. Fails fast with :class:`AliasOverrideError` (a no-silent
    rejection) rather than silently sanitizing the operator's chosen alias.

    Args:
        alias: The raw ``--as`` value.

    Returns:
        The validated alias (identical to the input).

    Raises:
        AliasOverrideError: When the alias is empty, carries an out-of-charset
            character, or contains a ``__`` run.
    """
    if not alias:
        raise AliasOverrideError(alias, "the alias is empty")
    if not _ALIAS_CHARSET_RE.fullmatch(alias):
        raise AliasOverrideError(alias, "the alias contains a character outside [A-Za-z0-9_]")
    if "__" in alias:
        raise AliasOverrideError(alias, "the alias contains a '__' run")
    return alias


def _read_all_source_aliases(kanon_file: pathlib.Path) -> dict[str, tuple[str | None, str | None]]:
    """Map every alias in the .kanon file to its ``(url, ref)`` coordinates.

    Scans the destination file once for ``KANON_SOURCE_<alias>_URL`` and
    ``KANON_SOURCE_<alias>_REF`` lines and groups them by alias. The returned
    mapping is the authoritative set of already-taken aliases used by the
    alias-resolution algorithm (so a colliding add can deterministically pick
    the next free suffix). An alias appears in the mapping when it has at least
    one block line; a missing ``_URL`` / ``_REF`` is recorded as ``None``.

    Args:
        kanon_file: Path to the .kanon file (may not exist).

    Returns:
        Ordered mapping ``alias -> (url, ref)`` for every alias present in the
        file (insertion order = first-seen line order). Empty when the file is
        absent or carries no source blocks.
    """
    aliases: dict[str, tuple[str | None, str | None]] = {}
    if not kanon_file.exists():
        return aliases

    url_re = re.compile(rf"^{re.escape(SOURCE_PREFIX)}(.+?){re.escape(SOURCE_URL_SUFFIX)}=(.*)$")
    ref_re = re.compile(rf"^{re.escape(SOURCE_PREFIX)}(.+?){re.escape(SOURCE_REF_SUFFIX)}=(.*)$")

    for raw_line in kanon_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        url_match = url_re.match(line)
        if url_match:
            alias = url_match.group(1)
            prev_url, prev_ref = aliases.get(alias, (None, None))
            aliases[alias] = (url_match.group(2), prev_ref)
            continue
        ref_match = ref_re.match(line)
        if ref_match:
            alias = ref_match.group(1)
            prev_url, prev_ref = aliases.get(alias, (None, None))
            aliases[alias] = (prev_url, ref_match.group(2))
    return aliases


def _alias_candidate_sequence(base_alias: str, entry_url: str, entry_ref: str) -> list[str]:
    """Build the deterministic alias-candidate sequence for an entry.

    Per spec Section 4.2 the first-added of two colliding entries keeps the bare
    alias; each subsequent colliding add gets the sanitized source-repo suffix,
    then the sanitized ref suffix if it still collides. This returns the ordered
    candidates ``[base, base_repo, base_repo_ref]`` with empty sanitized
    fragments skipped so a ``__`` run can never appear.

    Args:
        base_alias: The sanitized manifest name (``derive_source_name`` output).
        entry_url: This entry's catalog-source URL (for the repo suffix).
        entry_ref: This entry's verbatim ref spec (for the ref suffix).

    Returns:
        The ordered list of candidate aliases to try, most-bare first.
    """
    candidates = [base_alias]
    repo_fragment = _source_repo_fragment(entry_url)
    if repo_fragment:
        with_repo = f"{base_alias}_{repo_fragment}"
        candidates.append(with_repo)
        ref_fragment = _sanitize_alias_fragment(entry_ref)
        if ref_fragment:
            candidates.append(f"{with_repo}_{ref_fragment}")
    return candidates


def _resolve_entry_alias(
    existing: dict[str, tuple[str | None, str | None]],
    base_alias: str,
    entry_url: str,
    entry_ref: str,
    force: bool,
) -> tuple[str, str]:
    """Resolve the local alias for an auto-computed (no ``--as``) entry.

    Walks the deterministic candidate sequence (spec Section 4.2). For each
    candidate, in order:

    - free (not in ``existing``) -> use it; mode ``"new"``.
    - taken by the SAME url+ref -> this is a re-add of the existing package:
      ``"duplicate"`` without ``--force`` (the caller errors with a diff and the
      guiding message), or ``"force_overwrite"`` with ``--force``.
    - taken by a DIFFERENT source (different url, or same url + different ref)
      -> advance to the next candidate (cross-source / same-repo-different-ref
      collision is auto-suffixed, never an error).

    Args:
        existing: The alias -> (url, ref) map from :func:`_read_all_source_aliases`.
        base_alias: The sanitized manifest name.
        entry_url: This entry's catalog-source URL.
        entry_ref: This entry's verbatim ref spec.
        force: The ``--force`` flag.

    Returns:
        A ``(alias, mode)`` tuple where mode is ``"new"``, ``"duplicate"``, or
        ``"force_overwrite"``.

    Raises:
        SystemExit: When every candidate is exhausted (all taken by genuinely
            different sources), which cannot be disambiguated automatically.
    """
    for candidate in _alias_candidate_sequence(base_alias, entry_url, entry_ref):
        if candidate not in existing:
            return candidate, "new"
        existing_url, existing_ref = existing[candidate]
        if existing_url == entry_url and existing_ref == entry_ref:
            return candidate, ("force_overwrite" if force else "duplicate")
        # Same alias, different source coordinates -> try the next suffix.
    print(
        f"ERROR: cannot auto-compute a unique alias for {entry_url}@{entry_ref}: "
        f"every candidate alias ({base_alias} and its source-repo / ref suffixes) "
        "is already mapped to a different source.\n"
        "Pass --as <alias> to choose an explicit alias.",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_override_alias(
    existing: dict[str, tuple[str | None, str | None]],
    alias: str,
    entry_url: str,
    entry_ref: str,
    force: bool,
) -> tuple[str, str]:
    """Resolve the alias for an explicit ``--as`` override (spec Section 4.2).

    Unlike the auto-compute path, an explicit ``--as`` alias is never suffixed:

    - free -> use it; mode ``"new"``.
    - taken by the SAME url+ref -> re-add of the existing package: ``"duplicate"``
      without ``--force`` (the caller errors with a diff), ``"force_overwrite"``
      with ``--force``.
    - taken by a DIFFERENT source -> the ``--as`` alias is already taken: a hard
      error without ``--force`` (no silent suffixing of an operator-chosen
      alias), ``"force_overwrite"`` with ``--force`` (the operator's explicit
      repoint).

    Args:
        existing: The alias -> (url, ref) map.
        alias: The validated ``--as`` alias.
        entry_url: This entry's catalog-source URL.
        entry_ref: This entry's verbatim ref spec.
        force: The ``--force`` flag.

    Returns:
        A ``(alias, mode)`` tuple where mode is ``"new"``, ``"duplicate"``, or
        ``"force_overwrite"``.

    Raises:
        SystemExit: When the ``--as`` alias is already mapped to a different
            source and ``--force`` is not set.
    """
    if alias not in existing:
        return alias, "new"
    existing_url, existing_ref = existing[alias]
    if existing_url == entry_url and existing_ref == entry_ref:
        return alias, ("force_overwrite" if force else "duplicate")
    if force:
        return alias, "force_overwrite"
    print(
        f"ERROR: --as alias '{alias}' is already mapped to {existing_url} "
        f"(ref {existing_ref}); it cannot be reused for {entry_url} "
        f"(ref {entry_ref}).\n"
        f"Pick a different --as alias, use --force to overwrite, or "
        f"'kanon remove {alias}' first.",
        file=sys.stderr,
    )
    sys.exit(1)


def _is_marketplace_type(entry_type: str | None) -> bool:
    """Return True when a catalog entry's ``<type>`` marks it as a marketplace.

    The comparison is exact against :data:`CATALOG_TYPE_CLAUDE_MARKETPLACE`
    (spec Section 4.2 / FR-17); a ``None`` type (the recommended field absent)
    is not a marketplace.

    Args:
        entry_type: The entry's ``<catalog-metadata><type>`` value, or ``None``.

    Returns:
        True iff ``entry_type`` equals the Claude marketplace type token.
    """
    return entry_type == CATALOG_TYPE_CLAUDE_MARKETPLACE


def _resolve_marketplace_flag(
    entry_name: str,
    entry_type: str | None,
    flag_override: bool | None,
) -> bool:
    """Resolve the per-dependency marketplace-install flag for one added entry.

    Precedence (spec Section 4.2 / FR-17):

    - ``flag_override is True`` (``--marketplace-install``): force on, but raise
      :class:`MarketplaceInstallError` when the entry is not a marketplace type
      (a pretty error, never a silent write of a bogus marketplace flag).
    - ``flag_override is False`` (``--no-marketplace-install``): force off.
    - ``flag_override is None`` (neither flag): auto-detect from ``entry_type``.

    Args:
        entry_name: The catalog entry name (used in the forced-on error).
        entry_type: The entry's ``<catalog-metadata><type>`` value, or ``None``.
        flag_override: ``True`` for ``--marketplace-install``, ``False`` for
            ``--no-marketplace-install``, ``None`` when neither flag was given.

    Returns:
        The resolved marketplace boolean for this dependency.

    Raises:
        MarketplaceInstallError: When ``--marketplace-install`` is forced on an
            entry whose ``<type>`` is not the marketplace type.
    """
    if flag_override is True:
        if not _is_marketplace_type(entry_type):
            raise MarketplaceInstallError(entry_name=entry_name, entry_type=entry_type)
        return True
    if flag_override is False:
        return False
    return _is_marketplace_type(entry_type)


def _build_source_block_lines(
    source_name: str,
    url: str,
    ref: str,
    path: str,
    name: str,
    gitbase: str,
    marketplace: bool,
) -> list[str]:
    """Construct the alias-keyed KANON_SOURCE_<alias>_* block lines.

    Emits the alias-keyed per-dependency block (spec Section 5.1 / FR-5, FR-6):
    ``_URL``, ``_REF`` (the verbatim version spec), ``_PATH``, ``_NAME`` (the
    original catalog manifest name), and ``_GITBASE`` (the org base for
    ``${GITBASE}`` resolution). The optional ``_MARKETPLACE`` flag (spec Section
    5.1 / FR-17) is appended as ``=true`` only when ``marketplace`` is true;
    when false the line is omitted entirely (absence is the canonical false, so
    kanon never emits ``=false``). There is no ``_REVISION`` line and no global
    ``[catalog]`` block.

    Args:
        source_name: The local alias (from ``derive_source_name``).
        url: Manifest repo git URL.
        ref: Verbatim version spec (e.g. ``1.2.0``, ``main``, ``>=1.0,<2.0``).
        path: Repo-relative path to the marketplace XML file.
        name: Original catalog manifest name (the pre-sanitization entry name).
        gitbase: Org base for ``${GITBASE}`` resolution (derived from the URL).
        marketplace: Whether this dependency registers as a Claude marketplace.
            ``True`` appends ``_MARKETPLACE=true``; ``False`` omits the line.

    Returns:
        A list of the URL, REF, PATH, NAME, GITBASE lines, plus a trailing
        ``_MARKETPLACE=true`` line when ``marketplace`` is true.
    """
    prefix = f"{SOURCE_PREFIX}{source_name}"
    # The suffix tokens are written as literals (rather than interpolated from
    # the suffix constants) so this single canonical writer states the on-disk
    # alias-block schema verbatim: _URL, _REF, _PATH, _NAME, _GITBASE.
    lines = [
        f"{prefix}_URL={url}",
        f"{prefix}_REF={ref}",
        f"{prefix}_PATH={path}",
        f"{prefix}_NAME={name}",
        f"{prefix}_GITBASE={gitbase}",
    ]
    if marketplace:
        lines.append(f"{prefix}{SOURCE_MARKETPLACE_SUFFIX}={MARKETPLACE_FLAG_TRUE}")
    return lines


def _source_block_key_names(source_name: str) -> str:
    """Return the comma-joined KANON_SOURCE_<alias>_* key names for a summary line.

    Args:
        source_name: The local alias.

    Returns:
        The comma-joined list of every key in the alias-keyed source block, in
        the canonical suffix order from ``SOURCE_SUFFIXES``.
    """
    return ", ".join(f"{SOURCE_PREFIX}{source_name}{suffix}" for suffix in SOURCE_SUFFIXES)


def _append_source_block(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
) -> None:
    """Append the alias-keyed block lines to dest and print a summary to stdout.

    Creates the destination file (and parent directories) when it does not yet
    exist. A blank separator line is written before the block only when the file
    already has content, so a freshly-created ``.kanon`` does not start with a
    leading blank line.

    Args:
        dest: Destination .kanon file path (created if absent).
        source_name: The local alias, used in the stdout summary.
        lines: The KANON_SOURCE_<alias>_* block lines to append.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    needs_separator = dest.exists() and dest.read_text(encoding="utf-8").strip() != ""
    with dest.open("a", encoding="utf-8") as fh:
        if needs_separator:
            fh.write("\n")
        for line in lines:
            fh.write(line + "\n")
    print(f"Wrote {_source_block_key_names(source_name)} to {dest}")


def _build_entry_catalog(
    manifest_root: pathlib.Path,
    url: str,
) -> list[tuple[CatalogMetadata, pathlib.Path, str]]:
    """Walk repo-specs/**/*-marketplace.xml and parse every entry.

    Raises SystemExit with exit code 1 and the spec-canonical integrity-issues
    error message if any XML file fails parsing (soft-spot rule 1 or rule 3).

    Args:
        manifest_root: Root of the cloned manifest repo.
        url: The manifest repo URL (included in error messages).

    Returns:
        List of (CatalogMetadata, xml_path, url) triples for every entry found.
    """
    xml_paths = find_catalog_entry_files(manifest_root)
    entries: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
    error_paths: list[str] = []

    for xml_path in sorted(xml_paths):
        try:
            metadata = _parse_catalog_metadata(xml_path)
            entries.append((metadata, xml_path, url))
        except CatalogMetadataParseError as exc:
            # Use the manifest-relative path in all error output so messages
            # are reproducible regardless of the temp clone directory.
            # Canonical fixture: tests/fixtures/errors/missing-required-metadata-field.txt
            # Spec section: spec/kanon-list-add-lock-features-spec.md Section 3.
            rel_path = str(xml_path.relative_to(manifest_root))
            error_paths.append(rel_path)
            error_msg = str(exc).replace(str(xml_path), rel_path)
            print(f"ERROR: {error_msg}", file=sys.stderr)

    if error_paths:
        offending = ", ".join(error_paths)
        print(
            f"ERROR: manifest repo `{url}` has integrity issues in the following XML paths: {offending}",
            file=sys.stderr,
        )
        sys.exit(1)

    return entries


def _find_entry_by_name(
    name: str,
    catalog: list[tuple[CatalogMetadata, pathlib.Path, str]],
) -> tuple[CatalogMetadata, pathlib.Path, str]:
    """Find a catalog entry by exact name match.

    Args:
        name: The requested catalog entry name.
        catalog: The list of (CatalogMetadata, xml_path, url) tuples.

    Returns:
        The matching (CatalogMetadata, xml_path, url) tuple.

    Raises:
        SystemExit: When no entry with the given name is found.
    """
    for metadata, xml_path, url in catalog:
        if metadata.name == name:
            return metadata, xml_path, url

    print(
        f"ERROR: Catalog entry '{name}' not found in the manifest repo.\n"
        "Run 'kanon search' to discover available entry names.",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_spec(url: str, spec: str | None) -> str:
    """Resolve the version spec for a catalog entry.

    When spec is None (default-spec path), selects the highest PEP 440-valid
    git tag on the manifest repo via git ls-remote --tags. Raises SystemExit
    with the spec-verbatim error if:

    - The repo has zero tags total (AC-FUNC-002), or
    - The repo has tags but none parse as ``packaging.version.Version``
      (AC-FUNC-003). In this subcase the first up-to-10 skipped tag names
      are printed so the operator can identify the offending tags.

    When spec is a non-empty string, delegates to resolve_version() to
    resolve the PEP 440 constraint against the available tags (AC-FUNC-005).

    Args:
        url: The manifest repo git URL.
        spec: The version spec string (e.g. '==1.0.0', '~=1.2') or None.

    Returns:
        A full tag ref string (e.g. 'refs/tags/1.2.0').
    """
    if spec is None:
        tags = _list_tags(url)
        if not tags:
            # Zero tags total -- emit spec-verbatim error (AC-FUNC-002).
            print(f"ERROR: {_ZERO_PEP440_TAGS_ERROR}", file=sys.stderr)
            sys.exit(1)

        # Check whether at least one tag has a PEP 440-valid last component.
        # Collect skipped names so the loud error can list them (AC-FUNC-003).
        skipped: list[str] = []
        has_pep440 = False
        for tag in tags:
            last = tag.rsplit("/", 1)[-1]
            try:
                Version(last)
                has_pep440 = True
                break
            except InvalidVersion:
                skipped.append(tag)

        if not has_pep440:
            # Zero PEP 440-valid tags -- emit spec-verbatim error plus skipped
            # tag names (first up-to-TAG_ERROR_DISPLAY_CAP, sorted) (AC-FUNC-003).
            sorted_skipped = sorted(skipped)
            display = sorted_skipped[:TAG_ERROR_DISPLAY_CAP]
            lines = [f"ERROR: {_ZERO_PEP440_TAGS_ERROR}", "Skipped non-PEP-440 tags:"]
            for tag_name in display:
                lines.append(f"  - {tag_name}")
            if len(skipped) > TAG_ERROR_DISPLAY_CAP:
                lines.append(f"  ... (showing first {TAG_ERROR_DISPLAY_CAP} of {len(skipped)})")
            print("\n".join(lines), file=sys.stderr)
            sys.exit(1)

        return _resolve_constraint_from_tags("*", tags)

    return resolve_version(url, spec)


def _resolve_manifest_repo_for_add(catalog_source: str) -> tuple[pathlib.Path, str, str]:
    """Clone the manifest repo and return (repo_root, url, ref).

    Args:
        catalog_source: A '<git_url>@<ref>' string.

    Returns:
        Tuple of (repo_root_path, url, ref).

    Raises:
        SystemExit: When the git clone fails or catalog source format is invalid.
    """
    try:
        url, ref = _parse_catalog_source(catalog_source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    resolved_ref = ref
    if ref == "latest":
        resolved_ref = "*"
    if is_version_constraint(resolved_ref):
        resolved = resolve_version(url, resolved_ref)
        resolved_ref = resolved.removeprefix("refs/tags/")

    clone_dir = pathlib.Path(tempfile.mkdtemp(prefix="kanon-add-"))
    repo_dir = clone_dir / "repo"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", resolved_ref, url, str(repo_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: Failed to clone manifest repo from {url}@{resolved_ref}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    return repo_dir, url, resolved_ref


def _xml_repo_relative_path(
    manifest_root: pathlib.Path,
    xml_path: pathlib.Path,
) -> str:
    """Return the repo-relative path for the given XML file.

    Args:
        manifest_root: Root of the cloned manifest repo.
        xml_path: Absolute path to the marketplace XML file.

    Returns:
        Repo-relative path string (e.g. 'repo-specs/foo-marketplace.xml').
    """
    return str(xml_path.relative_to(manifest_root))


# ---------------------------------------------------------------------------
# Collision detection helpers
# ---------------------------------------------------------------------------


def _check_within_request_collisions(entry_names: list[str]) -> None:
    """Detect duplicates within the requested set before any catalog work.

    Normalises each raw entry name (via derive_source_name) and hard-errors
    on the first pair that maps to the same source name token.

    Args:
        entry_names: Raw positional argument strings (names only, no spec).

    Raises:
        SystemExit: When two or more names normalise to the same source name.
    """
    seen: dict[str, str] = {}  # source_name -> first raw name
    for raw in entry_names:
        source = derive_source_name(raw)
        if source in seen:
            first = seen[source]
            print(
                f"ERROR: within-request collision: '{first}' and '{raw}' both "
                f"normalise to source name '{source}'.\n"
                "Remove duplicate entries from your command arguments.",
                file=sys.stderr,
            )
            sys.exit(1)
        seen[source] = raw


def _read_existing_source_block(
    kanon_file: pathlib.Path,
    source_name: str,
) -> tuple[str | None, str | None, str | None]:
    """Read the URL, REF, and PATH values for an existing alias block.

    Scans the destination .kanon file for the alias-keyed block lines
    KANON_SOURCE_<alias>_{URL,REF,PATH}=<value>. The ``_NAME`` and ``_GITBASE``
    lines are not surfaced here because the collision message and the dry-run
    diff report only the source coordinates (URL / REF / PATH); presence of any
    block line is what drives collision detection.

    Args:
        kanon_file: Path to the .kanon file (may not exist).
        source_name: The local alias (output of derive_source_name).

    Returns:
        A 3-tuple (url, ref, path). Each element is the value string if found,
        or None when absent.
    """
    if not kanon_file.exists():
        return None, None, None

    prefix = f"{SOURCE_PREFIX}{source_name}"
    url: str | None = None
    ref: str | None = None
    path: str | None = None

    for raw_line in kanon_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(f"{prefix}{SOURCE_URL_SUFFIX}="):
            url = line[len(f"{prefix}{SOURCE_URL_SUFFIX}=") :]
        elif line.startswith(f"{prefix}{SOURCE_REF_SUFFIX}="):
            ref = line[len(f"{prefix}{SOURCE_REF_SUFFIX}=") :]
        elif line.startswith(f"{prefix}{SOURCE_PATH_SUFFIX}="):
            path = line[len(f"{prefix}{SOURCE_PATH_SUFFIX}=") :]

    return url, ref, path


def _emit_same_name_guard_error(
    kanon_file: pathlib.Path,
    source_name: str,
    new_url: str,
    new_ref: str,
    new_path: str,
) -> None:
    """Fail fast on a re-add of an existing package (the same-NAME guard).

    Reached when the resolved alias is already mapped to the SAME source@ref
    (spec Section 4.2 "re-add of existing package"). Prints the canonical error,
    a unified-style diff of the existing block against the requested block, and
    the guiding remediation message, then exits non-zero. A cross-source
    collision never reaches this guard: it is auto-suffixed to a fresh alias by
    :func:`_resolve_entry_alias`.

    Args:
        kanon_file: Path to the .kanon file (must contain the alias block).
        source_name: The resolved local alias that collides.
        new_url: Requested manifest repo URL.
        new_ref: Requested verbatim ref spec.
        new_path: Requested repo-relative XML path.

    Raises:
        SystemExit: Always (exit code 1).
    """
    existing_url, existing_ref, existing_path = _read_existing_source_block(kanon_file, source_name)
    prefix = f"{SOURCE_PREFIX}{source_name}"
    diff_lines = [
        f"-{prefix}{SOURCE_URL_SUFFIX}={existing_url}",
        f"-{prefix}{SOURCE_REF_SUFFIX}={existing_ref}",
        f"-{prefix}{SOURCE_PATH_SUFFIX}={existing_path}",
        f"+{prefix}{SOURCE_URL_SUFFIX}={new_url}",
        f"+{prefix}{SOURCE_REF_SUFFIX}={new_ref}",
        f"+{prefix}{SOURCE_PATH_SUFFIX}={new_path}",
    ]
    print(
        f"ERROR: source alias '{source_name}' is already mapped to "
        f"{existing_url}/{existing_path} (ref {existing_ref}); this is a re-add "
        "of an existing package.\n" + "\n".join(diff_lines) + "\n"
        f"Use --force to overwrite and re-pin its lock entry, or "
        f"'kanon remove {source_name}' first.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Force-overwrite helper
# ---------------------------------------------------------------------------


def _overwrite_source_block(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
) -> None:
    """Replace the KANON_SOURCE_<alias>_* block lines in dest.

    Reads the entire file, removes any line whose key is one of the alias-keyed
    block keys (every suffix in ``SOURCE_SUFFIXES`` plus the optional
    ``_MARKETPLACE`` flag), and inserts the new block lines in place of the first
    removed line (preserving order). Including ``_MARKETPLACE`` in the removed set
    means a ``--no-marketplace-install`` overwrite drops a previously written
    ``_MARKETPLACE=true`` line rather than leaving it stale.

    Args:
        dest: Destination .kanon file (must exist and contain the block).
        source_name: The local alias.
        lines: The replacement KANON_SOURCE_<alias>_* block lines.
    """
    prefix = f"{SOURCE_PREFIX}{source_name}"
    block_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}
    block_keys.add(f"{prefix}{SOURCE_MARKETPLACE_SUFFIX}")

    existing_lines = dest.read_text(encoding="utf-8").splitlines(keepends=True)
    result: list[str] = []
    inserted = False

    for raw_line in existing_lines:
        stripped = raw_line.rstrip("\n").rstrip("\r")
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in block_keys:
            if not inserted:
                # Insert replacement block at the position of the first matched line.
                for new_line in lines:
                    result.append(new_line + "\n")
                inserted = True
            # Skip old line (replaced above).
        else:
            result.append(raw_line)

    dest.write_text("".join(result), encoding="utf-8")

    print(f"Overwrote {_source_block_key_names(source_name)} in {dest}")


# ---------------------------------------------------------------------------
# Lock re-pin helper (spec Section 4.2: --force re-pins the alias lock entry)
# ---------------------------------------------------------------------------


def _repin_lock_entry(
    kanon_file: pathlib.Path,
    alias: str,
    url: str,
    ref_spec: str,
) -> None:
    """Re-pin the ``alias`` lock entry after a ``--force`` overwrite.

    When a ``.kanon.lock`` exists and already carries a ``[[sources]]`` entry for
    ``alias``, the entry's ``url`` / ``ref_spec`` / ``resolved_ref`` /
    ``resolved_sha`` are re-resolved against the new source coordinates while its
    ``name`` (the dep's manifest NAME) is preserved (spec Section 4.2: an
    overwrite keeps the dep's NAME; repointing to a different manifest is
    ``remove`` + ``add``). The lockfile's ``kanon_hash`` is recomputed from the
    just-overwritten ``.kanon`` so the lock does not drift from ``.kanon``.

    The function is a deliberate no-op (returns without touching the lock) when
    no lockfile exists or the lockfile carries no entry for ``alias``: ``add``
    never manufactures a lock from scratch (that is ``install``'s role); it only
    re-pins an already-locked alias.

    Args:
        kanon_file: Path to the ``.kanon`` file (its sibling lock is derived).
        alias: The local alias whose lock entry is re-pinned.
        url: The new manifest repo URL for the alias.
        ref_spec: The new verbatim ref spec recorded as ``ref_spec``.

    Raises:
        SystemExit: When the new ref cannot be resolved to a SHA on the remote
            (fail fast; the overwritten ``.kanon`` and the lock would otherwise
            drift silently).
    """
    lock_path = derive_lock_file_path(
        kanon_file,
        cli_lock_file=None,
        env_lock_file=os.environ.get(KANON_LOCK_FILE),
    )
    lockfile = read_lockfile_if_present(lock_path)
    if lockfile is None:
        return

    target = next((entry for entry in lockfile.sources if entry.alias == alias), None)
    if target is None:
        return

    try:
        resolution = _resolve_ref_to_sha(url, ref_spec)
    except ValueError as exc:
        print(
            f"ERROR: cannot re-pin lock entry for alias '{alias}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Re-pin the source coordinates; keep the dep's manifest NAME unchanged.
    target.url = url
    target.ref_spec = ref_spec
    target.resolved_ref = resolution.resolved_ref
    target.resolved_sha = resolution.sha

    # Recompute the kanon_hash from the just-overwritten .kanon so .kanon and
    # .kanon.lock stay consistent (the validate-lockfile drift check, FR-24).
    lockfile.kanon_hash = kanon_hash(kanon_file)

    write_lockfile(lockfile, lock_path)
    print(f"Re-pinned lock entry for alias '{alias}' in {lock_path}")


# ---------------------------------------------------------------------------
# Dry-run renderer
# ---------------------------------------------------------------------------


def _existing_block_lines(dest: pathlib.Path, source_name: str) -> list[str]:
    """Return every existing KANON_SOURCE_<alias>_* line in dest, in file order.

    Args:
        dest: Destination .kanon file path (may not exist).
        source_name: The local alias.

    Returns:
        The stripped block lines for the alias in their original file order;
        empty when the file is absent or contains no block lines for the alias.
    """
    if not dest.exists():
        return []
    prefix = f"{SOURCE_PREFIX}{source_name}"
    block_keys = {f"{prefix}{suffix}" for suffix in SOURCE_SUFFIXES}
    block_keys.add(f"{prefix}{SOURCE_MARKETPLACE_SUFFIX}")
    matched: list[str] = []
    for raw_line in dest.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped else stripped
        if key in block_keys:
            matched.append(stripped)
    return matched


def _render_dry_run_diff(
    dest: pathlib.Path,
    source_name: str,
    lines: list[str],
    force: bool,
) -> None:
    """Print the diff that WOULD be applied to dest without modifying the file.

    When force is False (no collision expected), each block line is printed with
    a '+' prefix. When force is True and a block already exists, the existing
    block lines appear with a '-' prefix first, then the replacement lines with
    a '+' prefix.

    Args:
        dest: Destination .kanon file path.
        source_name: The local alias.
        lines: The replacement KANON_SOURCE_<alias>_* block lines.
        force: Whether the operation would overwrite an existing block.
    """
    if force:
        old_lines = _existing_block_lines(dest, source_name)
        if old_lines:
            for old_line in old_lines:
                print(f"-{old_line}")
            for new_line in lines:
                print(f"+{new_line}")
            return

    for new_line in lines:
        print(f"+{new_line}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_add(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon add' subcommand.

    Resolves each requested catalog entry, constructs the alias-keyed
    KANON_SOURCE_<alias>_* block lines, and appends (or overwrites) them in the
    destination .kanon file. Creates the file when absent; no standard header is
    written (spec Section 5.1).

    The implementation uses a two-phase approach to satisfy AC-FUNC-004
    (destination .kanon is unchanged after any error):

    - **Resolution phase** (Steps 1-4): all catalog lookups, tag resolution,
      and against-existing collision detection run first. No file writes occur.
    - **Write phase** (Step 5): only after every entry is fully resolved and
      validated does the alias-block append/overwrite execute. There is no
      standard-header write (spec Section 5.1): the per-dependency block carries
      its own ``_GITBASE`` and there is no global ``[catalog]`` header line.

    Marketplace auto-detect (FR-17, spec Section 4.2): each entry's
    ``KANON_SOURCE_<alias>_MARKETPLACE`` flag is auto-detected from its
    ``<catalog-metadata><type>`` (a ``claude-marketplace`` type writes ``=true``
    plus a notice naming the override flag; any other type writes no line).
    ``--marketplace-install`` forces the flag on (a pretty error, not a crash,
    when the entry is not a marketplace type); ``--no-marketplace-install``
    forces it off (omit the line).

    When --dry-run is set, prints the diff that would be applied and exits 0
    without modifying any file.

    Alias keying (FR-6, spec Section 4.2): each entry's local alias is the
    sanitized manifest name. A cross-source collision (the bare alias already
    maps to a different source / ref) auto-suffixes deterministically -- the
    sanitized source-repo name, then the sanitized ref -- so re-reading the
    committed .kanon reproduces the same aliases. ``--as <alias>`` overrides the
    auto-computed alias for the (single) entry. A re-add of the same alias at
    the same source@ref is a true duplicate: a hard error (with a diff and the
    guiding message) without ``--force``; with ``--force`` the block is
    overwritten and its lock entry re-pinned while keeping the dep's ``NAME``.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure (typically via sys.exit()).
    """
    catalog_source: str | None = getattr(args, "catalog_source", None) or resolve_env_catalog_source()
    if not catalog_source:
        print(
            MISSING_CATALOG_ERROR_TEMPLATE.format(command="add"),
            file=sys.stderr,
        )
        sys.exit(1)

    kanon_file = pathlib.Path(getattr(args, "kanon_file", KANON_KANON_FILE_DEFAULT))
    force: bool = getattr(args, "force", False)
    dry_run: bool = getattr(args, "dry_run", False)
    alias_override: str | None = getattr(args, "alias_override", None)
    # None == auto-detect from <catalog-metadata><type>; True/False == forced by
    # --marketplace-install / --no-marketplace-install (spec Section 4.2 / FR-17).
    marketplace_override: bool | None = getattr(args, "marketplace_install", None)

    # An --as override targets a single alias; rejecting the multi-entry case up
    # front (fail fast) avoids silently aliasing only one of several entries.
    if alias_override is not None and len(args.entries) != 1:
        print(
            "ERROR: --as <alias> overrides the alias for a single entry; "
            f"{len(args.entries)} entries were requested.\n"
            "Run a separate 'kanon add <entry> --as <alias>' per overridden entry.",
            file=sys.stderr,
        )
        sys.exit(1)

    if alias_override is not None:
        try:
            alias_override = _validate_alias_override(alias_override)
        except AliasOverrideError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

    # Validate that a GITBASE org base is derivable from the catalog-source URL
    # early (before any file writes) so a malformed URL fails fast before cloning
    # the manifest repo. The per-dependency _GITBASE written into each block is
    # derived from that dependency's own entry URL in the resolution loop below.
    # The catalog_source has the form <url>@<ref>; strip the trailing @<ref> to
    # obtain the bare URL for the early derivation guard.
    catalog_source_url = catalog_source[: catalog_source.rfind("@")] if "@" in catalog_source else catalog_source
    try:
        _derive_gitbase_from_catalog_source(catalog_source_url)
    except CatalogSourceURLDerivationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Pre-flight: within-request collision detection (before any catalog work).
    # add is single-source per invocation, so two entries normalising to the
    # same manifest name from the one source are a genuine duplicate request.
    raw_names = [_split_name_spec(raw)[0] for raw in args.entries]
    _check_within_request_collisions(raw_names)

    # Step 1: Resolve manifest repo.
    manifest_root, url, _ref = _resolve_manifest_repo_for_add(catalog_source)

    # Step 2: Build entry catalog (hard-errors on soft-spot rule 1 / 3 violations).
    catalog = _build_entry_catalog(manifest_root, url)

    # Step 3-4: Resolution phase -- resolve every entry, compute its deterministic
    # alias, and run the same-NAME guard BEFORE any file write. This ensures that
    # if any entry fails (zero PEP 440-valid tags, unknown name, --as taken, or a
    # re-add without --force), the destination .kanon is not modified at all
    # (AC-FUNC-004). The ``existing`` alias map seeds from the committed .kanon
    # and is updated per resolved entry so two entries in one invocation also
    # auto-suffix deterministically.
    existing_aliases = _read_all_source_aliases(kanon_file)
    # Each resolved entry: (alias, mode, entry_url, lock_ref_spec, lines).
    resolved_entries: list[tuple[str, str, str, str, list[str]]] = []
    for raw_entry in args.entries:
        name, spec = _split_name_spec(raw_entry)

        metadata, xml_path, entry_url = _find_entry_by_name(name, catalog)

        resolved_revision = _resolve_spec(entry_url, spec)

        base_alias = derive_source_name(metadata.name)
        # The lock ref-spec records the operator's intent (the verbatim spec when
        # supplied), falling back to the auto-resolved revision for the bare add.
        lock_ref_spec = spec if spec is not None else resolved_revision

        rel_path = _xml_repo_relative_path(manifest_root, xml_path)

        # Per-dependency GITBASE org base, derived from this entry's own URL
        # (spec Section 5.1). Failure to derive fails fast (no silent default).
        try:
            entry_gitbase = _derive_gitbase_from_catalog_source(entry_url)
        except CatalogSourceURLDerivationError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        if alias_override is not None:
            alias, mode = _resolve_override_alias(existing_aliases, alias_override, entry_url, resolved_revision, force)
        else:
            alias, mode = _resolve_entry_alias(existing_aliases, base_alias, entry_url, resolved_revision, force)

        if mode == "duplicate":
            # Re-add of the existing package at the same source@ref without
            # --force: fail fast with a diff and the guiding message.
            _emit_same_name_guard_error(
                kanon_file=kanon_file,
                source_name=alias,
                new_url=entry_url,
                new_ref=lock_ref_spec,
                new_path=rel_path,
            )

        # Resolve the per-dependency marketplace flag (auto-detect from the
        # entry's <type>, overridden by --[no-]marketplace-install). Forcing
        # --marketplace-install on a non-marketplace entry is a pretty error
        # (fail fast, before any file write -- AC-FUNC-004 holds).
        try:
            marketplace = _resolve_marketplace_flag(
                entry_name=metadata.name,
                entry_type=metadata.type,
                flag_override=marketplace_override,
            )
        except MarketplaceInstallError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        # Auto-detected marketplace entries print a notice naming the override
        # flag (spec Section 4.2 / FR-17). The notice is emitted only on
        # auto-detect (override unset); an explicit flag already states intent.
        if marketplace and marketplace_override is None:
            print(
                f"Note: catalog entry '{metadata.name}' is a "
                f"'{CATALOG_TYPE_CLAUDE_MARKETPLACE}' type; writing "
                f"{SOURCE_PREFIX}{alias}{SOURCE_MARKETPLACE_SUFFIX}="
                f"{MARKETPLACE_FLAG_TRUE}.\n"
                "       Pass --no-marketplace-install to skip marketplace "
                "registration for this dependency."
            )

        lines = _build_source_block_lines(
            source_name=alias,
            url=entry_url,
            ref=resolved_revision,
            path=rel_path,
            name=metadata.name,
            gitbase=entry_gitbase,
            marketplace=marketplace,
        )

        # Record the resolved alias so a later entry in this same invocation
        # auto-suffixes against it (deterministic within-request collision).
        existing_aliases[alias] = (entry_url, resolved_revision)
        resolved_entries.append((alias, mode, entry_url, lock_ref_spec, lines))

    # Step 5: Write phase -- all entries resolved successfully; now write to disk.
    # For --dry-run: print diffs without any file modification (no lock needed).
    if dry_run:
        for alias, mode, _entry_url, _lock_ref_spec, lines in resolved_entries:
            _render_dry_run_diff(
                dest=kanon_file,
                source_name=alias,
                lines=lines,
                force=(mode == "force_overwrite"),
            )
        return 0

    # Normal (non-dry-run) write path: acquire the workspace exclusive lock
    # before any file write so a concurrent kanon install cannot read a
    # half-written .kanon file.
    workspace_root = kanon_file.resolve().parent
    with kanon_workspace_lock(workspace_root):
        for alias, mode, entry_url, lock_ref_spec, lines in resolved_entries:
            if mode == "force_overwrite":
                _overwrite_source_block(
                    dest=kanon_file,
                    source_name=alias,
                    lines=lines,
                )
                # Re-pin the alias's lock entry (keeping its NAME) so .kanon and
                # .kanon.lock do not drift after a --force overwrite (spec
                # Section 4.2). No-op when no .kanon.lock exists or the alias is
                # absent from it.
                _repin_lock_entry(
                    kanon_file=kanon_file,
                    alias=alias,
                    url=entry_url,
                    ref_spec=lock_ref_spec,
                )
            else:
                _append_source_block(
                    dest=kanon_file,
                    source_name=alias,
                    lines=lines,
                )

    return 0
