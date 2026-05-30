"""Multi-source Kanon install business logic.

Parses .kanon, validates sources, creates isolated source workspaces
under ``.kanon-data/sources/<name>/``, runs ``repo init``/``envsubst``/``sync``
per source, aggregates symlinks into ``.packages/``, detects collisions,
updates ``.gitignore``, and optionally installs marketplace plugins.

Concurrent installs on the same project directory are serialized via an
exclusive workspace lock on ``.kanon-data/.kanon-install.lock`` (via
``kanon_workspace_lock`` in ``utils/concurrency.py``). The same lock is
shared with ``kanon add``, ``kanon remove``, and
``kanon doctor --refresh-completion-cache`` so all mutating commands
serialise on a single per-workspace lock.

Lockfile state machine (spec Section 4.7)
-----------------------------------------
Every ``kanon install`` invocation inspects the five-row state matrix:

  LOCKFILE_ABSENT        -- .kanon.lock absent; resolve fresh, write lockfile.
  LOCKFILE_CONSISTENT    -- .kanon.lock present and kanon_hash matches; replay SHAs.
  LOCKFILE_HASH_MISMATCH -- .kanon.lock present but kanon_hash differs; hard error.
  LOCKFILE_UNREACHABLE   -- lockfile SHA no longer reachable on remote; hard error.
  LOCKFILE_SOURCE_MISMATCH -- lockfile catalog source differs from CLI/env; hard error.
  REFRESH_LOCK_SOURCE    -- operator requested partial lockfile rebuild via --refresh-lock-source.

Exception hierarchy:

  InstallError                -- base class for all install-state hard errors (defined in
                                 core/include_walker.py; re-exported here for backwards compatibility).
  KanonHashMismatchError      -- kanon_hash in lockfile != freshly-computed hash.
  LockfileUnreachableShaError -- a lockfile SHA is no longer reachable on remote.
  CatalogSourceMismatchError  -- lockfile catalog source differs from CLI/env source.
  MissingCatalogSourceError   -- no catalog source from CLI, env, or lockfile fallback.
  UnknownSourceError          -- --refresh-lock-source name does not match any source.
  OrphanedLockEntryError      -- --strict-lock: lockfile source absent from .kanon.
  BranchDriftError            -- --strict-drift: branch tip differs from locked SHA.
  CanonicalUrlConflictError   -- two+ sources declare the same canonical URL with different SHAs.
  IncludeCycleError           -- <include> chain contains a cycle (re-exported from include_walker).

Include-tree resolution:

  _walk_includes and IncludeTree are implemented in core/include_walker.py and
  re-exported here so call-sites can use either import path.  The walker uses a
  two-set DFS algorithm to detect cycles (raises IncludeCycleError) and
  deduplicate diamond paths (shared nodes appear only at their first-walked
  position).
"""

from __future__ import annotations

import datetime
import enum
import os
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import NamedTuple, cast

from packaging.specifiers import SpecifierSet, InvalidSpecifier

import kanon_cli.repo as _repo
from kanon_cli.repo.git_command import GitCommandError
from kanon_cli import __version__
from kanon_cli.constants import (
    CATALOG_ENV_VAR,
    KANON_ALLOW_INSECURE_REMOTES,
    KANON_CATALOG_BLOCK_HEADER,
    KANON_CATALOG_BLOCK_KEY,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.core.kanon_hash import kanon_hash as _kanon_hash
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    CatalogBlock,
    IncludeEntry,
    Lockfile,
    SourceEntry,
    read_lockfile,
    write_lockfile,
)
from kanon_cli.core.include_walker import (
    IncludeCycleError,
    IncludeTree,
    InstallError,
    MalformedIncludeError,
    _canonicalize_include_path,
    _walk_includes,
)
from kanon_cli.core.marketplace import install_marketplace_plugins
from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.core.metadata import derive_source_name
from kanon_cli.core.remote_url import _enforce_remote_url_policy
from kanon_cli.core.url import canonicalize_repo_url
from kanon_cli.utils.concurrency import kanon_workspace_lock
from kanon_cli.version import resolve_version

# Re-export include-walker symbols so call-sites can import from either module.
# InstallError is defined in include_walker to avoid circular imports; re-exporting
# it here preserves backwards compatibility for all existing import sites.
__all__ = [
    "IncludeCycleError",
    "IncludeTree",
    "InstallError",
    "MalformedIncludeError",
    "_canonicalize_include_path",
    "_walk_includes",
]


# ---------------------------------------------------------------------------
# Module-private constants
# ---------------------------------------------------------------------------

# Timeout (seconds) for git ls-remote calls in _check_sha_reachable and
# _resolve_ref_to_sha.  Override via KANON_GIT_LS_REMOTE_TIMEOUT env var.
# constants.py is claimed by multiple non-terminal tasks (PRE_CONFLICT);
# a module-private constant is used here to avoid the merge surface.
_GIT_LS_REMOTE_TIMEOUT: int = int(
    os.environ.get("KANON_GIT_LS_REMOTE_TIMEOUT", "30"),
)

# Remediation text appended to MissingCatalogSourceError when --refresh-lock is
# the active install state.  The lockfile fallback is disabled on the refresh path
# because the operator is explicitly rebuilding the lockfile.
_REFRESH_LOCK_MISSING_CATALOG_REMEDIATION = (
    "--refresh-lock requires a CLI or env-var catalog source; the lockfile fallback is disabled on this path."
)

# Remediation text for --refresh-lock-source missing catalog (same constraint).
_REFRESH_LOCK_SOURCE_MISSING_CATALOG_REMEDIATION = (
    "--refresh-lock-source requires a CLI or env-var catalog source; the lockfile fallback is disabled on this path."
)

# ---------------------------------------------------------------------------
# Unresolved-placeholder detection (spec Section 4 E28 Change (b))
# ---------------------------------------------------------------------------

# Compiled regex matching uppercase-with-underscores-or-pipes tokens enclosed
# in angle brackets -- the canonical kanon placeholder shape.  The character
# class is intentionally restricted to [A-Z_|] so the pattern does NOT match
# lowercase XML element tags such as <remote> or <default>.
_UNRESOLVED_PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(r"<[A-Z_|]+>")


def _scan_kanonenv_for_unresolved_placeholders(
    kanonenv_path: pathlib.Path,
) -> list[tuple[int, str]]:
    """Return ``[(line_number, placeholder_text), ...]`` for each unresolved
    placeholder found in the env-var-value half of a ``.kanon`` file.

    Scans every KEY=VALUE line (1-indexed).  Lines that start with ``#``
    (comments) and lines that contain no ``=`` character are skipped.  The
    scan operates on the value portion only (the text after the first ``=``),
    so placeholder-shaped tokens on the key side are never flagged.

    Args:
        kanonenv_path: Absolute path to the ``.kanon`` file.

    Returns:
        A list of ``(line_number, matched_placeholder)`` tuples, one per
        regex match.  The list is empty when no unresolved placeholders are
        present.  Multiple matches on the same line each produce a separate
        tuple.
    """
    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(kanonenv_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        _, _, value = line.partition("=")
        for match in _UNRESOLVED_PLACEHOLDER_PATTERN.finditer(value):
            findings.append((line_number, match.group(0)))
    return findings


# ---------------------------------------------------------------------------
# OrphanedLockEntryError message templates (spec Section 4 E26)
# ---------------------------------------------------------------------------

# Header line template for a single orphaned lockfile entry (N == 1).
_ORPHAN_HEADER_SINGULAR = "ERROR: {count} orphaned lockfile entry: {names}"

# Header line template for multiple orphaned lockfile entries (N >= 2).
_ORPHAN_HEADER_PLURAL = "ERROR: {count} orphaned lockfile entries: {names}"

# Context line explaining why the entries are orphaned.
_ORPHAN_CONTEXT = "These lockfile entries have no matching KANON_SOURCE_*_URL triple in .kanon."

# Remediation block (three options) presented after the context line.
_ORPHAN_REMEDIATION = (
    "Remediation:\n"
    "  Run `kanon install` (without --strict-lock) to auto-prune, or\n"
    "  restore the missing KANON_SOURCE_<name>_* triples in .kanon, or\n"
    "  run `kanon remove <name>` for each orphan to clean the lockfile."
)

# INFO-line prefix emitted once per orphaned lock entry that is auto-pruned
# on default install (no --strict-lock).  Spec Section 4 E34 Change.
# Rendered as: f"{INFO_PRUNED_ORPHAN_LOCK_ENTRY}: {name}"
INFO_PRUNED_ORPHAN_LOCK_ENTRY = "pruned orphaned lock entry"


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class InstallState(enum.Enum):
    """Enumeration of the lockfile state-machine rows (spec Section 4.7).

    The seven rows are:
    - LOCKFILE_ABSENT:          .kanon.lock absent; resolve fresh, write lockfile.
    - LOCKFILE_CONSISTENT:      .kanon.lock present and kanon_hash matches; replay SHAs.
    - LOCKFILE_HASH_MISMATCH:   .kanon.lock present but kanon_hash differs; hard error.
    - LOCKFILE_UNREACHABLE:     lockfile SHA no longer reachable on remote; hard error.
    - LOCKFILE_SOURCE_MISMATCH: lockfile catalog source differs from CLI/env; hard error.
    - REFRESH_LOCK:             operator requested a full lockfile rebuild via --refresh-lock;
                                short-circuits the normal state classification.
    - REFRESH_LOCK_SOURCE:      operator requested partial rebuild via --refresh-lock-source;
                                re-resolves exactly one source chain, preserves all others.
    """

    LOCKFILE_ABSENT = "lockfile-absent"
    LOCKFILE_CONSISTENT = "lockfile-consistent"
    LOCKFILE_HASH_MISMATCH = "lockfile-hash-mismatch"
    LOCKFILE_UNREACHABLE = "lockfile-unreachable"
    LOCKFILE_SOURCE_MISMATCH = "lockfile-catalog-source-mismatch"
    REFRESH_LOCK = "refresh-lock"
    REFRESH_LOCK_SOURCE = "refresh-lock-source"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class KanonHashMismatchError(InstallError):
    """Raised when the lockfile's kanon_hash does not match the freshly-computed value.

    Spec row: ``.kanon modified (hash mismatch)``.
    Remediation: ``kanon install --refresh-lock`` or ``--refresh-lock-source <name>``.

    Canonical error text: ``tests/fixtures/errors/lockfile-hash-mismatch.txt``.
    Spec section: ``spec/kanon-list-add-lock-features-spec.md`` Section 6.

    Args:
        lockfile_hash: The ``kanon_hash`` value stored in the lockfile.
        computed_hash: The ``kanon_hash`` freshly computed from the current ``.kanon``.
    """

    def __init__(self, lockfile_hash: str, computed_hash: str) -> None:
        self.lockfile_hash = lockfile_hash
        self.computed_hash = computed_hash
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            "ERROR: .kanon has been modified since the lockfile was written.\n"
            f"  Lockfile kanon_hash : {self.lockfile_hash}\n"
            f"  Current  kanon_hash : {self.computed_hash}\n"
            "  Remediation: run 'kanon install --refresh-lock' to rebuild the entire\n"
            "  lockfile, or 'kanon install --refresh-lock-source <name>' to re-resolve\n"
            "  one source chain while preserving all other lockfile entries."
        )


class LockfileUnreachableShaError(InstallError):
    """Raised when a SHA recorded in the lockfile is no longer reachable on the remote.

    Spec row: ``.kanon.lock references a SHA no longer reachable on remote``.
    Remediation: ``kanon install --refresh-lock-source <name>``.

    Canonical error text: ``tests/fixtures/errors/lockfile-sha-unreachable.txt``.
    Spec section: ``spec/kanon-list-add-lock-features-spec.md`` Section 6.

    Args:
        source_name: The top-level source name whose SHA is unreachable.
        sha: The pinned SHA that the remote no longer exposes.
        remote_url: The remote git URL where the SHA was expected.
    """

    def __init__(self, source_name: str, sha: str, remote_url: str) -> None:
        self.source_name = source_name
        self.sha = sha
        self.remote_url = remote_url
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: Lockfile SHA for source '{self.source_name}' is no longer reachable.\n"
            f"  Source  : {self.source_name}\n"
            f"  SHA     : {self.sha}\n"
            f"  Remote  : {self.remote_url}\n"
            f"  Remediation: run 'kanon install --refresh-lock-source {self.source_name}'\n"
            f"  to re-resolve this source's full chain and update the lockfile entry."
        )


class CatalogSourceMismatchError(InstallError):
    """Raised when the lockfile's [catalog].source differs from the CLI/env source.

    Spec row: ``.kanon.lock records a different [catalog].source than the CLI/env source``.
    Remediation: ``kanon install --refresh-lock``.

    Args:
        lockfile_source: The ``[catalog].source`` value from the lockfile.
        cli_env_source: The catalog source resolved from the CLI flag or env var.
    """

    def __init__(self, lockfile_source: str, cli_env_source: str) -> None:
        self.lockfile_source = lockfile_source
        self.cli_env_source = cli_env_source
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            "ERROR: Catalog source in lockfile does not match the CLI/env catalog source.\n"
            f"  Lockfile [catalog].source : {self.lockfile_source}\n"
            f"  CLI/env catalog source    : {self.cli_env_source}\n"
            "  The lockfile is authoritative; if you intentionally changed catalogs,\n"
            "  run 'kanon install --refresh-lock' to rebuild the lockfile from the new source."
        )


class MissingCatalogSourceError(InstallError):
    """Raised when no catalog source is available from CLI, env var, or lockfile fallback.

    Spec reference: Section 4 header -- canonical missing-catalog error.

    Args:
        command: The command name to embed in the error message (e.g. ``"install"``).
        remediation: Optional override for the remediation line.  When set,
            this text is appended to the standard error body.  Used by the
            ``--refresh-lock`` path to explain that the lockfile fallback is
            disabled on the rebuild path.
    """

    def __init__(self, command: str, remediation: str | None = None) -> None:
        self.command = command
        self.remediation = remediation
        super().__init__(str(self))

    def __str__(self) -> str:
        base = MISSING_CATALOG_ERROR_TEMPLATE.format(command=self.command)
        if self.remediation is not None:
            return base + "\n" + self.remediation
        return base


class CatalogBlockParseError(InstallError):
    """Raised when a .kanon [catalog] block is present but malformed.

    A malformed block is one where the ``[catalog]`` header is present but
    the immediately-following line is not a valid
    ``KANON_CATALOG_SOURCE=<value>`` assignment, or the value is empty.

    This is a hard error: the operator must fix the block rather than having
    the CLI silently fall back to the next precedence layer.

    Args:
        line_number: 1-based line number of the offending line in .kanon.
        reason: Human-readable description of what is wrong with the line.
        kanon_path: Path to the .kanon file containing the malformed block.
    """

    def __init__(self, line_number: int, reason: str, kanon_path: pathlib.Path) -> None:
        self.line_number = line_number
        self.reason = reason
        self.kanon_path = kanon_path
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: malformed [catalog] block at {self.kanon_path}:{self.line_number}: {self.reason}\n"
            f"Remove the block or supply a value of the form "
            f"`{KANON_CATALOG_BLOCK_KEY}=<url>@<ref>`."
        )


class UnknownSourceError(InstallError):
    """Raised when --refresh-lock-source <name> does not match any top-level source.

    Spec row: ``--refresh-lock-source <name>`` where ``<name>`` is not a known
    KANON_SOURCE_<name> key and does not match via ``derive_source_name``.

    Args:
        name: The name supplied by the operator.
        known_names: The list of known source names from the lockfile.
    """

    def __init__(self, name: str, known_names: list[str]) -> None:
        self.name = name
        self.known_names = known_names
        super().__init__(str(self))

    def __str__(self) -> str:
        known_list = ", ".join(sorted(self.known_names)) if self.known_names else "(none)"
        return (
            f"ERROR: Source name {self.name!r} not found.\n"
            f"  Known source names: {known_list}\n"
            f"  Resolution: '{self.name}' was tried as a literal KANON_SOURCE_<name> key "
            f"and via derive_source_name (lowercased, hyphens to underscores).\n"
            f"  Remediation: use one of the known source names above, or the catalog "
            f"entry name that normalises to one of them."
        )


class OrphanedLockEntryError(InstallError):
    """Raised by --strict-lock when the lockfile contains sources absent from .kanon.

    An orphaned lock entry is a ``[[sources]]`` row in ``.kanon.lock`` whose
    ``name`` no longer appears in the current ``.kanon`` source declarations.
    This happens when a source is removed from ``.kanon`` (via ``kanon remove``)
    but the lockfile is not yet pruned.

    Default behaviour (without ``--strict-lock``): prune the orphaned entry and
    emit an info-line per orphan.  With ``--strict-lock``: this error is raised listing
    every orphaned entry so the operator can decide intentionally.

    Args:
        orphaned_names: Non-empty iterable of source names present in the lockfile
            but absent from the current ``.kanon`` source declarations.

    Raises:
        ValueError: When ``orphaned_names`` is empty; constructing this exception
            with zero names is a logic error -- the caller must only raise it
            when at least one orphan is detected.
    """

    def __init__(self, orphaned_names: list[str]) -> None:
        deduplicated = tuple(sorted(set(orphaned_names)))
        if not deduplicated:
            raise ValueError("OrphanedLockEntryError requires at least one orphan name; received an empty sequence.")
        self.orphaned_names: tuple[str, ...] = deduplicated
        super().__init__(str(self))

    def __str__(self) -> str:
        count = len(self.orphaned_names)
        names_csv = ", ".join(self.orphaned_names)
        header_template = _ORPHAN_HEADER_SINGULAR if count == 1 else _ORPHAN_HEADER_PLURAL
        header = header_template.format(count=count, names=names_csv)
        return f"{header}\n{_ORPHAN_CONTEXT}\n\n{_ORPHAN_REMEDIATION}"


class BranchDriftReport(NamedTuple):
    """Payload for a single branch-drift observation.

    Fields:
        source_name: The top-level source name that has drifted.
        branch: The branch name (short form, e.g. ``main``) that drifted.
        locked_sha: The SHA recorded in the lockfile for this source.
        current_sha: The current branch tip SHA on the remote.
    """

    source_name: str
    branch: str
    locked_sha: str
    current_sha: str


class BranchDriftError(InstallError):
    """Raised by --strict-drift when a branch's remote tip differs from the locked SHA.

    Branch drift occurs when the lockfile records a SHA for a source whose
    ``revision_spec`` is a branch name (e.g. ``main``), but the branch's
    current tip on the remote is a different SHA.

    Default behaviour (without ``--strict-drift``): reuse the locked SHA and
    emit an info-line per drifted source.  With ``--strict-drift``: this error
    is raised listing every drifted source.

    Args:
        reports: List of ``BranchDriftReport`` instances, one per drifted source.
    """

    def __init__(self, reports: list[BranchDriftReport]) -> None:
        self.reports = reports
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [
            "ERROR: Branch drift detected -- locked SHAs differ from remote branch tips.",
        ]
        for r in self.reports:
            lines.append(
                f"  Source '{r.source_name}': branch '{r.branch}' "
                f"locked at {r.locked_sha}, remote tip is {r.current_sha}."
            )
        lines.append(
            "  Remediation: run 'kanon install --refresh-lock-source <source>'\n"
            "  for each drifted source to accept the new branch tip."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Canonical-URL conflict detection types and exception
# ---------------------------------------------------------------------------


class ResolvedProject(NamedTuple):
    """A single project entry with the context needed for canonical-URL conflict detection.

    Fields:
        source_path: The source path in the form ``<source-name>/<xml-path>``,
            identifying which top-level source and which XML manifest file
            declared this project.
        raw_url: The raw project URL as declared in the manifest (may be
            SSH, HTTPS, or SCP shorthand).
        canonical_url: The canonical form of ``raw_url`` produced by
            ``canonicalize_repo_url``.
        resolved_sha: The commit SHA resolved for this project.
    """

    source_path: str
    raw_url: str
    canonical_url: str
    resolved_sha: str


class CanonicalUrlConflictReport(NamedTuple):
    """A single canonical-URL conflict: multiple projects sharing the same
    canonical URL but resolving to different SHAs.

    Fields:
        canonical_url: The shared canonical URL that triggered the conflict.
        entries: Every ``ResolvedProject`` whose ``canonical_url`` matches,
            including all sources (even those that happen to share a SHA).
            The caller is responsible for ensuring at least two distinct SHAs
            are present before constructing a report.
    """

    canonical_url: str
    entries: list[ResolvedProject]


class CanonicalUrlConflictError(InstallError):
    """Raised when two or more sources declare the same canonical URL with different SHAs.

    Spec Section 4.7 "Transitive conflict" row: two ``<project>`` entries
    pointing at the same canonicalized repo URL but pinning different SHAs
    is a hard error. The operator must either remove one source or align the
    REVISION values so all sources pin the same SHA.

    Canonical error text: ``tests/fixtures/errors/conflict-detected.txt``.
    Spec section: ``spec/kanon-list-add-lock-features-spec.md`` Section 6.

    Args:
        reports: One or more ``CanonicalUrlConflictReport`` instances.
            Each report represents a single canonical URL with conflicting SHAs.
    """

    def __init__(self, reports: list[CanonicalUrlConflictReport]) -> None:
        self.reports = reports
        super().__init__(str(self))

    def __str__(self) -> str:
        lines: list[str] = [
            "ERROR: Canonical-URL conflict -- two or more sources declare the same repository URL with different SHAs.",
        ]
        for report in self.reports:
            lines.append(f"  Conflict for canonical URL: {report.canonical_url}")
            for entry in report.entries:
                lines.append(f"  {entry.source_path}: {entry.raw_url} @ {entry.resolved_sha}")
            lines.append(f"  both URLs canonicalize to: {report.canonical_url}")
            lines.append(
                f"  Remediation: Use `kanon why {report.canonical_url}` to investigate; "
                f"resolve by removing one source or aligning REVISION values across sources."
            )
        return "\n".join(lines)


class UnresolvedPlaceholderError(InstallError):
    """Raised when a ``.kanon`` env-var value contains an unresolved placeholder token.

    An unresolved placeholder is a token matching ``<[A-Z_|]+>`` (uppercase
    letters, underscores, and pipes enclosed in angle brackets) that appears in
    a ``.kanon`` env-var value before ``repo envsubst`` is invoked.  Example:
    ``<YOUR_GIT_ORG_BASE_URL>``.

    The validator runs BEFORE ``repo envsubst`` so the operator receives a
    structured diagnostic instead of an opaque ``repo sync`` 404 or git-remote
    error.

    Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
    Section 4 E28 Change (b).

    Args:
        line_number: 1-indexed line number in the ``.kanon`` file where the
            first (or only) placeholder was found.
        placeholder: The matched placeholder token (e.g. ``<YOUR_GIT_ORG_BASE_URL>``).
        all_findings: Full list of ``(line_number, placeholder)`` tuples for every
            unresolved placeholder detected in the file.  Defaults to the single
            finding described by ``line_number`` and ``placeholder`` when omitted.
    """

    def __init__(
        self,
        line_number: int,
        placeholder: str,
        all_findings: list[tuple[int, str]] | None = None,
    ) -> None:
        self.line_number = line_number
        self.placeholder = placeholder
        self.all_findings: list[tuple[int, str]] = (
            all_findings if all_findings is not None else [(line_number, placeholder)]
        )
        super().__init__(str(self))

    def __str__(self) -> str:
        extra_count = len(self.all_findings) - 1
        suffix = f" (and {extra_count} more unresolved placeholder(s) in .kanon)" if extra_count > 0 else ""
        return (
            f"unresolved placeholder {self.placeholder} at .kanon:{self.line_number}"
            f"{suffix}\n"
            "  Remediation: replace all placeholder tokens with real values before "
            "running kanon install. See docs/configuration.md for details."
        )


class RefreshRepoInitError(InstallError):
    """Raised when repo re-init fails on the --refresh-lock[-source] path.

    On the refresh path, kanon re-runs ``repo init`` with the new manifest revision
    to advance the source manifest checkout to the moved branch tip. If this
    re-init fails for any reason (e.g., a residual git state issue after restoring
    the manifests working tree), the raw exception is caught here and re-raised
    with the offending source name and a remediation hint so the operator receives
    a structured diagnostic instead of a raw traceback.

    Args:
        source_name: The KANON_SOURCE_<name> key of the source that failed.
        cause: The underlying exception that caused the failure.
    """

    def __init__(self, source_name: str, cause: BaseException) -> None:
        self.source_name = source_name
        self.cause = cause
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: refresh failed for source '{self.source_name}': "
            f"{self.cause}\n"
            "  Remediation: remove the source's .kanon-data directory entry and "
            "re-run 'kanon install --refresh-lock'."
        )


def _reset_manifests_working_tree(source_dir: pathlib.Path) -> None:
    """Reset the .repo/manifests working tree to a clean state before re-init.

    kanon's ``repo envsubst`` step rewrites manifest XML files in-place (via
    ``minidom.toprettyxml``) and creates ``.bak`` sibling files, leaving the
    ``.repo/manifests`` git working tree dirty. When ``repo init`` is re-run
    with a new revision on the same branch, git refuses to checkout the new
    commit if the new commit changes ``manifest.xml`` and the working tree copy
    is already modified ("Your local changes to the following files would be
    overwritten by checkout"). The refused checkout leaves HEAD pointing to the
    deleted ``default`` branch ref, causing the subsequent
    ``git rev-list ^HEAD <sha>`` to raise an unhandled ``GitCommandError``
    ("fatal: bad revision '^HEAD'").

    This function restores all tracked files to their HEAD state and removes
    untracked ``.bak`` files from ``.repo/manifests``, so the subsequent
    ``repo init`` can checkout the new revision cleanly.

    The function is a no-op when ``.repo/manifests`` does not exist (first
    install has not yet run).

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``. The manifests
            working tree is at ``source_dir / ".repo" / "manifests"``.

    Raises:
        OSError: If the ``git checkout -- .`` or ``.bak`` cleanup fails due
            to a file-system error. The exception message names the path and
            the underlying OS error.
    """
    manifests_dir = source_dir / ".repo" / "manifests"
    if not manifests_dir.is_dir():
        return

    # Restore all tracked files to HEAD state.  ``git checkout -- .`` discards
    # local modifications to tracked files; it does NOT affect untracked files.
    result = subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=str(manifests_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(
            f"_reset_manifests_working_tree: git checkout -- . failed in {manifests_dir!r}: {result.stderr!r}"
        )

    # Remove .bak files created by envsubst (untracked; git checkout leaves them).
    for bak_file in manifests_dir.rglob("*.bak"):
        bak_file.unlink()


def _detect_canonical_url_conflicts(
    all_projects: list[ResolvedProject],
) -> list[CanonicalUrlConflictReport]:
    """Detect canonical-URL conflicts across a list of resolved projects.

    Groups projects by their ``canonical_url`` field.  A conflict exists when
    a group contains two or more entries with differing ``resolved_sha`` values
    (same SHA across multiple sources is a benign diamond and is allowed).

    Args:
        all_projects: Every resolved project to inspect.  Each entry carries the
            source path, raw URL, canonical URL, and resolved SHA.

    Returns:
        A list of ``CanonicalUrlConflictReport`` instances -- one per canonical URL
        that has at least two entries with different SHAs.  Returns ``[]`` when no
        conflicts exist; never returns ``None``.
    """
    # Group entries by canonical URL.
    groups: dict[str, list[ResolvedProject]] = {}
    for project in all_projects:
        groups.setdefault(project.canonical_url, []).append(project)

    reports: list[CanonicalUrlConflictReport] = []
    for canonical_url, entries in groups.items():
        shas = {e.resolved_sha for e in entries}
        if len(shas) > 1:
            reports.append(
                CanonicalUrlConflictReport(
                    canonical_url=canonical_url,
                    entries=entries,
                )
            )
    return reports


def _include_tree_to_entries(
    tree: IncludeTree,
    source_url: str,
    resolved_sha: str,
) -> list[IncludeEntry]:
    """Convert the children of an ``IncludeTree`` node to ``IncludeEntry`` objects.

    The root of ``tree`` represents the source's own manifest XML (recorded as
    a ``[[sources]]`` entry).  Only the root's children become
    ``[[sources.includes]]`` entries, so callers pass the root node and this
    function converts its ``includes`` list recursively.

    Each ``IncludeEntry`` records:
    - ``name``: the file stem of the XML path (display name for error messages).
    - ``path_in_repo``: the repo-relative path string as produced by
      ``_canonicalize_include_path``.
    - ``url``: the parent source's URL (all includes live in the same repo).
    - ``resolved_sha``: the parent source's locked SHA (same repo, same commit).
    - ``includes``: recursively converted child entries (preserves DFS order and
      diamond deduplication performed by ``_walk_includes``).

    Args:
        tree: An ``IncludeTree`` node whose ``includes`` list should be converted.
            Typically the root node returned by ``_walk_includes``.
        source_url: The URL of the parent source's manifest repository.
        resolved_sha: The commit SHA locked for the parent source.

    Returns:
        A list of ``IncludeEntry`` objects parallel to ``tree.includes``,
        preserving DFS pre-order and diamond deduplication from the walker.
    """
    entries: list[IncludeEntry] = []
    for child in tree.includes:
        child_path_str = str(child.path)
        entries.append(
            IncludeEntry(
                name=pathlib.Path(child_path_str).stem,
                path_in_repo=child_path_str,
                url=source_url,
                resolved_sha=resolved_sha,
                includes=_include_tree_to_entries(child, source_url, resolved_sha),
            )
        )
    return entries


def _gather_resolved_projects(resolved_entries: list[SourceEntry]) -> list[ResolvedProject]:
    """Build a ``ResolvedProject`` list from resolved ``SourceEntry`` objects.

    Constructs the canonical URL for each source's raw URL via
    ``canonicalize_repo_url``, then also walks each source's ``projects``
    list (``ProjectEntry`` rows populated from lockfile XML parsing) to
    include project-level entries.

    The ``source_path`` for each entry is formed as
    ``<source-name>/<manifest-path>`` so operators can trace each entry
    back to its declaring manifest.

    Args:
        resolved_entries: Resolved top-level source entries from the
            current install run or lockfile replay.

    Returns:
        A flat list of ``ResolvedProject`` instances covering every source
        entry and every project within each source.
    """
    result: list[ResolvedProject] = []
    for entry in resolved_entries:
        source_path = f"{entry.name}/{entry.path}"
        canonical = canonicalize_repo_url(entry.url)
        result.append(
            ResolvedProject(
                source_path=source_path,
                raw_url=entry.url,
                canonical_url=canonical,
                resolved_sha=entry.resolved_sha,
            )
        )
        for proj in entry.projects:
            result.append(
                ResolvedProject(
                    source_path=source_path,
                    raw_url=proj.url,
                    canonical_url=proj.canonical_url,
                    resolved_sha=proj.resolved_sha,
                )
            )
    return result


# ---------------------------------------------------------------------------
# Lockfile helpers (public API consumed by sibling tasks)
# ---------------------------------------------------------------------------


def read_lockfile_if_present(path: pathlib.Path) -> Lockfile | None:
    """Return the parsed Lockfile if ``path`` exists, or ``None`` if absent.

    Returns ``None`` only for a path that does not exist.  Any other error
    (parse failure, permission error, schema error) is raised through
    immediately so the caller sees a clear exception instead of a silent skip.

    Args:
        path: Filesystem path to the ``.kanon.lock`` file.

    Returns:
        A fully parsed and validated ``Lockfile`` dataclass, or ``None`` if
        the path does not exist.

    Raises:
        LockfileSchemaError: If the lockfile's schema version is unsupported.
        LockfileValidationError: If a field value fails validation.
        OSError: If the file exists but cannot be opened (permission error, etc.).
    """
    if not path.exists():
        return None
    return read_lockfile(path)


class InstallClassification(NamedTuple):
    """Result of ``_classify_install_state``.

    Carries the state, pre-computed kanon_hash, and parsed lockfile (when present)
    to avoid recomputing them in the install pipeline (DRY).

    Fields:
        state: The ``InstallState`` enum value for the current install invocation.
        computed_hash: The ``kanon_hash`` freshly computed from the ``.kanon`` file,
            or ``None`` when the lockfile was absent (hash not yet needed).
        lockfile: The parsed ``Lockfile`` when the lockfile exists, or ``None``
            when ``state`` is ``LOCKFILE_ABSENT``.
    """

    state: InstallState
    computed_hash: str | None
    lockfile: Lockfile | None


def _classify_install_state(
    kanon_path: pathlib.Path,
    lockfile_path: pathlib.Path,
    refresh_lock: bool = False,
) -> InstallClassification:
    """Return the ``InstallClassification`` for the given ``.kanon`` + ``.kanon.lock`` combination.

    When ``refresh_lock=True``, short-circuits the normal hash comparison and
    returns ``InstallState.REFRESH_LOCK`` regardless of lockfile presence or
    hash state (spec Section 4.7 -- ``--refresh-lock`` flag).

    Otherwise, implements the first three rows of the spec Section 4.7 state matrix:
    - LOCKFILE_ABSENT: lockfile path does not exist.
    - LOCKFILE_CONSISTENT: lockfile exists and its kanon_hash matches the
      freshly-computed hash of the ``.kanon`` file.
    - LOCKFILE_HASH_MISMATCH: lockfile exists but hashes differ.

    The LOCKFILE_UNREACHABLE and LOCKFILE_SOURCE_MISMATCH rows require
    resolver output (live git ls-remote results) and are detected elsewhere
    in the install pipeline.

    The returned ``InstallClassification`` carries the pre-computed hash and the
    parsed lockfile so the caller (``_run_install``) does not need to recompute
    or re-read them.

    Args:
        kanon_path: Path to the ``.kanon`` configuration file.
        lockfile_path: Path to the ``.kanon.lock`` file (may not exist).
        refresh_lock: When ``True``, always return ``InstallState.REFRESH_LOCK``
            regardless of lockfile state (spec Section 4.7 -- ``--refresh-lock``).

    Returns:
        An ``InstallClassification`` named tuple with ``state``, ``computed_hash``,
        and ``lockfile`` fields.

    Raises:
        KanonHashError: If the ``.kanon`` source fields contain forbidden characters.
        LockfileSchemaError: If the lockfile's schema_version is unsupported.
        LockfileValidationError: If a lockfile field fails validation.
    """
    # Short-circuit: operator requested a full lockfile rebuild.
    # The lockfile state (present, consistent, mismatched) is irrelevant.
    if refresh_lock:
        return InstallClassification(
            state=InstallState.REFRESH_LOCK,
            computed_hash=None,
            lockfile=None,
        )

    lockfile = read_lockfile_if_present(lockfile_path)
    if lockfile is None:
        return InstallClassification(
            state=InstallState.LOCKFILE_ABSENT,
            computed_hash=None,
            lockfile=None,
        )

    computed_hash = _kanon_hash(kanon_path)
    if computed_hash == lockfile.kanon_hash:
        return InstallClassification(
            state=InstallState.LOCKFILE_CONSISTENT,
            computed_hash=computed_hash,
            lockfile=lockfile,
        )
    return InstallClassification(
        state=InstallState.LOCKFILE_HASH_MISMATCH,
        computed_hash=computed_hash,
        lockfile=lockfile,
    )


def _parse_catalog_block(kanon_path: pathlib.Path) -> str | None:
    """Parse the optional ``[catalog]`` block from a ``.kanon`` file.

    Scans the file for a line equal to ``KANON_CATALOG_BLOCK_HEADER`` (``[catalog]``).
    When found, reads the immediately-following non-blank line and expects it to
    be a ``KANON_CATALOG_BLOCK_KEY=<value>`` assignment with a non-empty value.

    Returns ``None`` when no ``[catalog]`` header is present -- absence of the
    block is a normal condition on projects that were created before E22 and does
    NOT trigger a fallback error.

    Raises:
        CatalogBlockParseError: When the ``[catalog]`` header is present but the
            follow-up assignment is missing, malformed, or has an empty value.
            The error includes the 1-based line number of the offending line.

    Args:
        kanon_path: Path to the ``.kanon`` file to read.

    Returns:
        The catalog source value string (``<url>@<ref>`` form), or ``None`` when
        the block is absent.
    """
    if not kanon_path.exists():
        return None

    lines = kanon_path.read_text().splitlines()
    expected_key_prefix = f"{KANON_CATALOG_BLOCK_KEY}="

    for idx, line in enumerate(lines):
        if line.strip() == KANON_CATALOG_BLOCK_HEADER:
            header_line_number = idx + 1  # 1-based

            # Find the immediately-following non-blank line.
            next_idx = idx + 1
            while next_idx < len(lines) and lines[next_idx].strip() == "":
                next_idx += 1

            if next_idx >= len(lines):
                # Header at end of file with no follow-up line.
                raise CatalogBlockParseError(
                    line_number=header_line_number,
                    reason=f"[catalog] header at line {header_line_number} has no following {KANON_CATALOG_BLOCK_KEY}= line",
                    kanon_path=kanon_path,
                )

            follow_line = lines[next_idx].strip()
            follow_line_number = next_idx + 1  # 1-based

            if not follow_line.startswith(expected_key_prefix):
                raise CatalogBlockParseError(
                    line_number=follow_line_number,
                    reason=f"expected {KANON_CATALOG_BLOCK_KEY}=<url>@<ref>, got {follow_line!r}",
                    kanon_path=kanon_path,
                )

            value = follow_line[len(expected_key_prefix) :]
            if not value:
                raise CatalogBlockParseError(
                    line_number=follow_line_number,
                    reason=f"{KANON_CATALOG_BLOCK_KEY} value is empty; expected <url>@<ref>",
                    kanon_path=kanon_path,
                )

            return value

    return None


def _resolve_catalog_source(
    cli_arg: str | None,
    env_value: str | None,
    lockfile_catalog_source: str | None,
    install_state: InstallState,
    kanon_path: pathlib.Path | None = None,
) -> str:
    """Resolve the effective catalog source following the spec's precedence rule.

    Precedence (highest to lowest, spec Section 4 header):
    1. ``cli_arg`` -- the ``--catalog-source`` CLI flag value.
    2. ``env_value`` -- the ``KANON_CATALOG_SOURCE`` environment variable.
    3. ``lockfile_catalog_source`` -- the ``[catalog].source`` field from the
       lockfile. This fallback applies ONLY in the ``LOCKFILE_CONSISTENT`` state
       and ONLY when both ``cli_arg`` and ``env_value`` are unset.
    4. ``kanon_path`` -- the ``[catalog]`` block inside the ``.kanon`` file
       written by ``kanon add``. This fallback applies when the block is present
       and the three higher-priority layers all return ``None``. The refresh-lock
       paths disable this fallback (same constraint as the lockfile fallback).

    When ``cli_arg`` or ``env_value`` is set and the lockfile's source differs,
    ``CatalogSourceMismatchError`` is raised (spec Section 4.7 -- the lockfile
    is authoritative; a deliberate catalog change requires ``--refresh-lock``).

    When all four sources are unset (or their fallbacks are not applicable
    for the current state), ``MissingCatalogSourceError`` is raised.

    Args:
        cli_arg: The ``--catalog-source`` CLI argument value, or ``None``.
        env_value: The ``KANON_CATALOG_SOURCE`` env var value, or ``None``.
        lockfile_catalog_source: The ``[catalog].source`` from a parsed lockfile,
            or ``None`` when no lockfile is available.
        install_state: The ``InstallState`` returned by ``_classify_install_state``.
        kanon_path: Path to the ``.kanon`` file for the fourth fallback layer.
            When ``None``, the ``.kanon`` block fallback is skipped.

    Returns:
        The effective catalog source string (``<url>@<ref>`` form).

    Raises:
        CatalogBlockParseError: If the .kanon [catalog] block is malformed.
        CatalogSourceMismatchError: If CLI/env source differs from the lockfile source
            in the consistent state (AC-FUNC-005).
        MissingCatalogSourceError: If no catalog source can be resolved (AC-FUNC-007).
    """
    # Determine the effective CLI/env source (highest priority wins)
    cli_env_source: str | None = cli_arg if cli_arg is not None else env_value

    if cli_env_source is not None:
        # In the consistent state, validate that lockfile source agrees (if present).
        if (
            install_state is InstallState.LOCKFILE_CONSISTENT
            and lockfile_catalog_source is not None
            and lockfile_catalog_source != cli_env_source
        ):
            raise CatalogSourceMismatchError(
                lockfile_source=lockfile_catalog_source,
                cli_env_source=cli_env_source,
            )
        return cli_env_source

    # On the refresh-lock and refresh-lock-source paths the lockfile fallback is
    # DISABLED.  The operator is explicitly rebuilding (part of) the lockfile and
    # must supply a source via CLI or env var; falling back to a stale lockfile
    # entry would silently reuse the old catalog, defeating the purpose of the flag.
    if install_state is InstallState.REFRESH_LOCK:
        raise MissingCatalogSourceError(
            command="install",
            remediation=_REFRESH_LOCK_MISSING_CATALOG_REMEDIATION,
        )
    if install_state is InstallState.REFRESH_LOCK_SOURCE:
        raise MissingCatalogSourceError(
            command="install",
            remediation=_REFRESH_LOCK_SOURCE_MISSING_CATALOG_REMEDIATION,
        )

    # No CLI/env source -- use lockfile fallback only in the consistent state.
    if install_state is InstallState.LOCKFILE_CONSISTENT and lockfile_catalog_source is not None:
        return lockfile_catalog_source

    # Fourth precedence layer: read the [catalog] block from the .kanon file.
    # This block is written by `kanon add` when creating a fresh .kanon file.
    # _parse_catalog_block returns None when the block is absent (not an error),
    # and raises CatalogBlockParseError when the block is present but malformed.
    if kanon_path is not None:
        kanon_block_source = _parse_catalog_block(kanon_path)
        if kanon_block_source is not None:
            return kanon_block_source

    raise MissingCatalogSourceError(command="install")


def _emit_install_state(
    state: InstallState,
    sources: int,
    projects: int,
    refreshed_source_name: str | None = None,
    refreshed_count: int = 0,
    preserved_count: int = 0,
) -> None:
    """Print the spec's verbatim info-line for the given install state to stdout.

    Four states produce an info-line (spec Section 4.7):
    - LOCKFILE_ABSENT:        ``"lockfile rebuilt from .kanon (N sources, M projects)"``
    - LOCKFILE_CONSISTENT:    ``"installing from lockfile (N sources, M projects)"``
    - REFRESH_LOCK:           ``"lockfile rebuilt from .kanon (N sources, M projects)"``
      (same text as LOCKFILE_ABSENT -- the operator's intent is equivalent)
    - REFRESH_LOCK_SOURCE:    ``"lockfile partially rebuilt: source <name> (M projects refreshed; K projects preserved)"``

    Other states are not emitted by this helper (they result in exceptions).

    Args:
        state: The ``InstallState`` for the current install invocation.
        sources: The number of top-level sources declared in ``.kanon``.
        projects: The total number of resolved projects across all sources.
        refreshed_source_name: The source name that was refreshed. Required when
            ``state`` is ``REFRESH_LOCK_SOURCE``; ignored for other states.
        refreshed_count: The number of top-level sources that were refreshed.
            Used when ``state`` is ``REFRESH_LOCK_SOURCE``.
        preserved_count: The number of top-level sources that were preserved
            (kept as-is from the existing lockfile). Used when ``state`` is
            ``REFRESH_LOCK_SOURCE``.
    """
    if state in (InstallState.LOCKFILE_ABSENT, InstallState.REFRESH_LOCK):
        print(f"lockfile rebuilt from .kanon ({sources} sources, {projects} projects)")
    elif state is InstallState.LOCKFILE_CONSISTENT:
        print(f"installing from lockfile ({sources} sources, {projects} projects)")
    elif state is InstallState.REFRESH_LOCK_SOURCE:
        assert refreshed_count >= 0, f"refreshed_count must be >= 0; got {refreshed_count}"
        assert preserved_count >= 0, f"preserved_count must be >= 0; got {preserved_count}"
        refreshed_noun = "project" if refreshed_count == 1 else "projects"
        preserved_noun = "project" if preserved_count == 1 else "projects"
        print(
            f"lockfile partially rebuilt: source {refreshed_source_name} "
            f"({refreshed_count} {refreshed_noun} refreshed; {preserved_count} {preserved_noun} preserved)"
        )


class _RefResolution(NamedTuple):
    """Result of resolving a git ref to a commit SHA via ``git ls-remote``."""

    sha: str
    resolved_ref: str


# ---------------------------------------------------------------------------
# --refresh-lock-source helpers
# ---------------------------------------------------------------------------


def _resolve_source_name(name: str, lockfile: Lockfile) -> SourceEntry:
    """Resolve a --refresh-lock-source name to a ``SourceEntry`` in two steps.

    Step 1: Try ``name`` as a literal KANON_SOURCE_<name> key by comparing it
    directly to each ``SourceEntry.name`` in the lockfile.

    Step 2: If no direct match, normalise ``name`` via ``derive_source_name``
    (lowercase, hyphens to underscores) and compare to each
    ``SourceEntry.name``.

    If neither step matches, raises ``UnknownSourceError`` listing the known
    source names.

    Args:
        name: The value supplied to ``--refresh-lock-source``.
        lockfile: The currently parsed lockfile containing known ``SourceEntry`` objects.

    Returns:
        The ``SourceEntry`` whose ``name`` matches, either directly or via
        ``derive_source_name``.

    Raises:
        UnknownSourceError: If ``name`` does not match any source in the lockfile
            by either the direct or the ``derive_source_name`` resolution path.
    """
    # Step 1: direct literal match.
    for entry in lockfile.sources:
        if entry.name == name:
            return entry

    # Step 2: normalise via derive_source_name and compare.
    normalised = derive_source_name(name)
    for entry in lockfile.sources:
        if entry.name == normalised:
            return entry

    known = [e.name for e in lockfile.sources]
    raise UnknownSourceError(name=name, known_names=known)


def _refresh_one_source(
    source_name: str,
    source_data: dict,
) -> SourceEntry:
    """Re-resolve one source's manifest chain and return a rebuilt ``SourceEntry``.

    Resolves the source URL and revision to a concrete git ref + SHA via
    ``git ls-remote``, constructing a fresh ``SourceEntry``.  Any transitive
    ``<include>`` chain resolution happens in the subsequent ``repo init`` /
    ``repo sync`` steps; this function only records the top-level source's
    resolved SHA.

    Args:
        source_name: The KANON_SOURCE_<name> key for this source.
        source_data: The parsed source dict from ``parse_kanonenv`` containing
            ``url``, ``revision``, and ``path`` keys.

    Returns:
        A freshly-resolved ``SourceEntry`` for the named source.

    Raises:
        ValueError: If the ref is not found on the remote or if git ls-remote fails.
    """
    resolved_revision = resolve_version(source_data["url"], source_data["revision"])
    ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
    return SourceEntry(
        name=source_name,
        url=source_data["url"],
        revision_spec=source_data["revision"],
        resolved_ref=ref_resolution.resolved_ref,
        resolved_sha=ref_resolution.sha,
        path=source_data["path"],
    )


def _merge_partial_lockfile(
    old_lockfile: Lockfile,
    refreshed_source: SourceEntry,
    new_kanon_hash: str,
) -> Lockfile:
    """Replace exactly one ``SourceEntry`` in the lockfile, preserving all others.

    The ``[catalog]`` block and all other ``SourceEntry`` objects are carried
    over verbatim from ``old_lockfile``.  The top-level ``kanon_hash`` is
    updated to the freshly-computed value so the rewritten lockfile passes the
    consistency check on the next ``kanon install``.

    Args:
        old_lockfile: The existing parsed lockfile.
        refreshed_source: The rebuilt ``SourceEntry`` for the refreshed source.
            Its ``name`` must match exactly one entry in ``old_lockfile.sources``.
        new_kanon_hash: The freshly-computed ``kanon_hash`` for the current
            ``.kanon`` content.

    Returns:
        A new ``Lockfile`` instance with the refreshed source replaced and all
        other fields (including ``catalog``) preserved from ``old_lockfile``.

    Raises:
        UnknownSourceError: If ``refreshed_source.name`` is not found in
            ``old_lockfile.sources``.
    """
    known = [e.name for e in old_lockfile.sources]
    if refreshed_source.name not in known:
        raise UnknownSourceError(name=refreshed_source.name, known_names=known)

    new_sources = [refreshed_source if e.name == refreshed_source.name else e for e in old_lockfile.sources]
    return Lockfile(
        schema_version=old_lockfile.schema_version,
        generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generator=old_lockfile.generator,
        kanon_hash=new_kanon_hash,
        catalog=old_lockfile.catalog,
        sources=new_sources,
    )


def _check_sha_reachable(url: str, sha: str, source_name: str) -> None:
    """Verify that a pinned SHA is still reachable on the remote.

    Lists all refs from the remote via ``git ls-remote <url>`` (no pattern
    argument) and searches the first column of every output line for the
    pinned SHA.  If the SHA does not appear in any line, or if git ls-remote
    returns a non-zero exit code, the SHA is considered unreachable and
    ``LockfileUnreachableShaError`` is raised.

    This approach avoids the limitation of ``git ls-remote <url> <pattern>``,
    which only matches ref names -- not bare SHAs -- and would always return
    empty output for SHA lookups, making every SHA appear unreachable.

    Args:
        url: Git repository URL to query.
        sha: The pinned commit SHA to search for in remote refs.
        source_name: The top-level source name (used in the error payload).

    Raises:
        LockfileUnreachableShaError: If the SHA is not found in any remote
            ref or if git ls-remote exits with a non-zero return code.
    """
    result = subprocess.run(
        ["git", "ls-remote", url],
        capture_output=True,
        text=True,
        timeout=_GIT_LS_REMOTE_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        raise LockfileUnreachableShaError(
            source_name=source_name,
            sha=sha,
            remote_url=url,
        )
    # Check the first column (SHA) of each tab-delimited line; a substring search
    # against the full stdout would produce false positives when a SHA appears in
    # a ref name (unlikely but possible with partial hashes or test fixtures).
    sha_found = any(line.split("\t")[0] == sha for line in result.stdout.strip().splitlines() if "\t" in line)
    if not sha_found:
        raise LockfileUnreachableShaError(
            source_name=source_name,
            sha=sha,
            remote_url=url,
        )


def _resolve_ref_to_sha(url: str, ref: str) -> _RefResolution:
    """Resolve a git ref to its commit SHA and the matched ref string via ``git ls-remote``.

    Used when writing the lockfile to record the exact commit SHA and the
    fully-qualified ref that the resolved ref points to.  The ref may be a tag
    name (``1.0.0``), a branch name (``main``), a fully-qualified tag ref
    (``refs/tags/1.0.0``), a fully-qualified branch ref (``refs/heads/main``),
    or any other valid git ref.

    When ``ref`` is not fully qualified (does not start with ``refs/``), the
    ls-remote output is searched for any matching entry.  The first match's
    fully-qualified ref is returned as ``resolved_ref`` so callers never need
    to guess the ``refs/heads/`` vs ``refs/tags/`` prefix.

    Args:
        url: Git repository URL (local path or remote URL).
        ref: A git ref (fully-qualified or short name).

    Returns:
        A ``_RefResolution`` named tuple with fields:
        - ``sha``: The commit SHA that ``ref`` resolves to.
        - ``resolved_ref``: The fully-qualified ref string returned by ls-remote.

    Raises:
        ValueError: If the ref is not found in the remote or if git ls-remote
            fails.
    """
    result = subprocess.run(
        ["git", "ls-remote", url, ref],
        capture_output=True,
        text=True,
        timeout=_GIT_LS_REMOTE_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"ERROR: git ls-remote failed for url={url!r}, ref={ref!r}.\n  stderr: {result.stderr.strip()}"
        )
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            matched_sha = parts[0]
            matched_ref = parts[1]
            # Accept a match when the ref is fully-qualified and equals the
            # matched_ref, OR when the ref is a short name and is the suffix
            # of the matched_ref (e.g. "main" matches "refs/heads/main").
            if matched_ref == ref or matched_ref.endswith(f"/{ref}"):
                return _RefResolution(sha=matched_sha, resolved_ref=matched_ref)
    raise ValueError(
        f"ERROR: ref {ref!r} not found in remote {url!r}.\n"
        f"  Remediation: verify the ref exists on the remote with "
        f"'git ls-remote {url} {ref}'."
    )


def create_source_dirs(
    source_names: list[str],
    base_dir: pathlib.Path,
) -> dict[str, pathlib.Path]:
    """Create .kanon-data/sources/<name>/ directories for each source.

    Args:
        source_names: Ordered list of source names (auto-discovered, alphabetical).
        base_dir: Project root directory.

    Returns:
        Dict mapping source name to its directory path.

    Raises:
        OSError: If a source directory cannot be created, with the failing path
            and OS error message included in the exception message.
    """
    result: dict[str, pathlib.Path] = {}
    for name in source_names:
        source_dir = base_dir / ".kanon-data" / "sources" / name
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(f"Cannot create source directory {source_dir}: {exc.strerror}") from exc
        result[name] = source_dir
    return result


def run_repo_init(
    source_dir: pathlib.Path,
    url: str,
    revision: str,
    manifest_path: str,
    repo_rev: str = "",
) -> None:
    """Run ``repo init -u <URL> -b <REVISION> -m <PATH>`` in source directory.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.
        url: Repository URL for repo init.
        revision: Branch/tag/revision for repo init.
        manifest_path: Manifest file path for repo init.
        repo_rev: Repo tool version tag for ``--repo-rev``.

    Raises:
        RepoCommandError: If repo init exits non-zero.
    """
    _repo.repo_init(str(source_dir), url, revision, manifest_path, repo_rev)


def run_repo_envsubst(
    source_dir: pathlib.Path,
    env_vars: dict[str, str],
) -> None:
    """Run ``repo envsubst`` in source directory with exported env vars.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.
        env_vars: Environment variables to export (GITBASE, CLAUDE_MARKETPLACES_DIR).

    Raises:
        RepoCommandError: If repo envsubst exits non-zero.
    """
    _repo.repo_envsubst(str(source_dir), env_vars)


def run_repo_sync(source_dir: pathlib.Path) -> None:
    """Run ``repo sync`` in source directory.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.

    Raises:
        RepoCommandError: If repo sync exits non-zero.
    """
    _repo.repo_sync(str(source_dir))


def aggregate_symlinks(
    source_names: list[str],
    base_dir: pathlib.Path,
) -> dict[str, str]:
    """Aggregate packages from all sources into ``.packages/``.

    For each ``.kanon-data/sources/<name>/.packages/*``, creates a symlink in
    the top-level ``.packages/`` directory. Detects collisions when two
    sources produce the same package name.

    Args:
        source_names: Ordered list of source names.
        base_dir: Project root directory.

    Returns:
        Dict mapping package name to source name.

    Raises:
        ValueError: If two sources produce the same package name.
    """
    packages_dir = base_dir / ".packages"
    packages_dir.mkdir(exist_ok=True)

    package_owners: dict[str, str] = {}

    for name in source_names:
        source_packages = base_dir / ".kanon-data" / "sources" / name / ".packages"
        if not source_packages.exists():
            continue
        for pkg in source_packages.iterdir():
            pkg_name = pkg.name
            if pkg_name in package_owners:
                raise ValueError(
                    f"Package collision for '{pkg_name}': provided by both '{package_owners[pkg_name]}' and '{name}'"
                )
            package_owners[pkg_name] = name
            link_path = packages_dir / pkg_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(pkg.resolve())

    return package_owners


def update_gitignore(
    base_dir: pathlib.Path,
    entries: list[str] | None = None,
) -> None:
    """Ensure ``.gitignore`` contains the required entries.

    Creates ``.gitignore`` if it does not exist. Appends missing entries
    without duplicating existing ones.

    Args:
        base_dir: Project root directory.
        entries: List of gitignore entries to ensure. Defaults to
            ``.packages/`` and ``.kanon-data/``.
    """
    gitignore = base_dir / ".gitignore"
    required_entries = entries if entries is not None else [".packages/", ".kanon-data/"]

    existing_content = ""
    if gitignore.exists():
        existing_content = gitignore.read_text()

    existing_lines = existing_content.splitlines()
    missing = [entry for entry in required_entries if entry not in existing_lines]

    if missing:
        with gitignore.open("a") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            for entry in missing:
                f.write(f"{entry}\n")


def prepare_marketplace_dir(marketplace_dir: pathlib.Path) -> None:
    """Create and clean the marketplace directory for pre-sync setup.

    Creates the directory if it does not exist, then removes all
    contents for a clean slate before sync.

    Args:
        marketplace_dir: Path to CLAUDE_MARKETPLACES_DIR.
    """
    marketplace_dir.mkdir(parents=True, exist_ok=True)
    for item in marketplace_dir.iterdir():
        if item.is_symlink() or not item.is_dir():
            item.unlink()
        else:
            shutil.rmtree(item)


def _process_manifest_linkfiles(
    manifest_xml_path: pathlib.Path,
    source_dir: pathlib.Path,
) -> None:
    """Process ``<linkfile>`` elements in a repo manifest XML after sync.

    Reads every ``<project>`` element in the manifest and for each child
    ``<linkfile>`` element copies the ``src`` file (resolved relative to
    the project checkout path under ``source_dir``) to the ``dest`` path
    (treated as an absolute path when it is absolute, otherwise resolved
    relative to ``source_dir``).

    Only linkfiles whose ``src`` file exists on disk are processed; missing
    source files are silently skipped so that manifests that reference
    projects not checked out by a partial sync do not cause hard failures.

    This function supplements the repo tool's native linkfile processing to
    ensure that marketplace plugin manifests are copied into
    ``CLAUDE_MARKETPLACES_DIR`` even when the repo tool's linkfile step did
    not run (e.g., in test environments where ``repo_sync`` is mocked).

    Args:
        manifest_xml_path: Absolute path to the root manifest XML file.
        source_dir: Root of the source workspace (the directory passed to
            ``repo init``; project paths are resolved relative to this).

    Raises:
        xml.etree.ElementTree.ParseError: If the manifest XML is malformed.
    """
    if not manifest_xml_path.is_file():
        return

    tree = ET.parse(str(manifest_xml_path))
    root = tree.getroot()

    for project_el in root.findall("project"):
        project_path = project_el.get("path", "")
        if not project_path:
            continue
        project_dir = source_dir / project_path

        for linkfile_el in project_el.findall("linkfile"):
            src_rel = linkfile_el.get("src", "")
            dest_str = linkfile_el.get("dest", "")
            if not src_rel or not dest_str:
                continue

            src_abs = project_dir / src_rel
            dest_path = pathlib.Path(dest_str) if pathlib.Path(dest_str).is_absolute() else source_dir / dest_str

            if not src_abs.is_file():
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_abs), str(dest_path))


def _is_branch_shaped_spec(revision_spec: str) -> bool:
    """Return True if ``revision_spec`` is branch-shaped (not a tag or PEP 440 specifier).

    A ``revision_spec`` is branch-shaped when it could refer to a moving branch
    tip.  The following are NOT branch-shaped (tags are immutable, drift is not
    a concept for them):

    - PEP 440 specifiers (e.g. ``==1.0.0``, ``~=2.0.0``).
    - ``refs/tags/...`` fully-qualified tag refs.

    The following ARE branch-shaped:

    - Plain branch names matching ``^[a-zA-Z0-9_./+-]+$`` (e.g. ``main``,
      ``feature/foo``) that are NOT valid PEP 440 specifiers.
    - ``refs/heads/...`` fully-qualified branch refs.

    Args:
        revision_spec: The ``revision_spec`` value from a ``SourceEntry``.

    Returns:
        ``True`` if the spec is branch-shaped; ``False`` otherwise.
    """
    # refs/tags/ -- clearly a tag ref, immutable
    if revision_spec.startswith("refs/tags/"):
        return False
    # refs/heads/ -- a fully-qualified branch ref
    if revision_spec.startswith("refs/heads/"):
        return True
    # other refs/ prefixes (e.g. refs/pull/) -- treat as branch-shaped
    if revision_spec.startswith("refs/"):
        return True
    # PEP 440 specifier -- a pinned version, not a branch
    try:
        SpecifierSet(revision_spec)
        # A successful parse means it is a version specifier -- not branch-shaped.
        # However, a plain string like "main" also parses as a SpecifierSet with
        # zero specifiers (empty set), so we must check that the set is non-empty.
        parsed = SpecifierSet(revision_spec)
        if len(list(parsed)) > 0:
            return False
    except (InvalidSpecifier, ValueError):
        pass
    # Branch-charset names: plain alphanumeric + _ . / + -
    # These are the branch-shaped specs we care about for drift.
    return True


def _detect_orphaned_lock_entries(
    lockfile: "Lockfile",
    kanon_sources: list[str],
) -> list[str]:
    """Return source names that are in the lockfile but absent from kanon_sources.

    An orphaned lock entry is a ``[[sources]]`` row in ``.kanon.lock`` whose
    ``name`` no longer appears in the ``KANON_SOURCE_*`` triples of the current
    ``.kanon`` file.  This happens after ``kanon remove`` when the operator has
    removed a source but the lockfile has not yet been pruned.

    Args:
        lockfile: The currently-parsed ``Lockfile`` for the consistent state.
        kanon_sources: The list of source names discovered from the current
            ``.kanon`` file (``config["KANON_SOURCES"]``).

    Returns:
        A sorted list of source names that are present in ``lockfile.sources``
        but absent from ``kanon_sources``.  An empty list means no orphans.
    """
    kanon_set = set(kanon_sources)
    return sorted(entry.name for entry in lockfile.sources if entry.name not in kanon_set)


def _detect_branch_drift(
    lockfile: "Lockfile",
) -> list[BranchDriftReport]:
    """Return one report per branch-shaped source whose remote tip differs from the locked SHA.

    Queries each branch-shaped source's remote via ``git ls-remote`` using the
    source's ``url`` and the short branch name extracted from ``resolved_ref``.
    Tag-shaped specs (PEP 440 or ``refs/tags/...``) are skipped because tags
    are immutable and drift is not a concept for them.

    This helper is only meaningful in the ``LOCKFILE_CONSISTENT`` state where
    the locked SHAs are trustworthy.  Callers on the refresh or absent-lockfile
    paths should not invoke this function.

    Args:
        lockfile: The currently-parsed ``Lockfile`` for the consistent state.

    Returns:
        A list of ``BranchDriftReport`` instances, one per branch-shaped source
        whose current remote tip differs from the locked SHA.  An empty list
        means no drift.
    """
    reports: list[BranchDriftReport] = []
    for entry in lockfile.sources:
        if not _is_branch_shaped_spec(entry.revision_spec):
            continue
        # Determine the ref to query.  Use resolved_ref when available;
        # fall back to revision_spec for plain branch names.
        ref_to_query = entry.resolved_ref if entry.resolved_ref else entry.revision_spec

        result = subprocess.run(
            ["git", "ls-remote", entry.url, ref_to_query],
            capture_output=True,
            text=True,
            timeout=_GIT_LS_REMOTE_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            # ls-remote failure for drift check is non-fatal in strict-drift mode;
            # the caller handles BranchDriftError based on the reports list.
            # A reachability failure will surface separately via _check_sha_reachable.
            continue

        current_sha: str | None = None
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                matched_sha = parts[0]
                matched_ref = parts[1]
                if matched_ref == ref_to_query or matched_ref.endswith(f"/{ref_to_query}"):
                    current_sha = matched_sha
                    break

        if current_sha is None:
            # Ref not found on remote -- cannot determine drift; skip.
            continue

        if current_sha != entry.resolved_sha:
            # Extract a human-readable branch name from resolved_ref.
            branch_name = entry.resolved_ref
            if branch_name.startswith("refs/heads/"):
                branch_name = branch_name[len("refs/heads/") :]
            elif branch_name.startswith("refs/"):
                # Other ref types: keep last segment
                branch_name = branch_name.split("/")[-1]
            reports.append(
                BranchDriftReport(
                    source_name=entry.name,
                    branch=branch_name,
                    locked_sha=entry.resolved_sha,
                    current_sha=current_sha,
                )
            )
    return reports


def _print_package_summary(
    package_owners: dict[str, str],
    source_names: list[str],
) -> None:
    """Print a structured summary of synced packages grouped by source.

    Args:
        package_owners: Dict mapping package name to source name.
        source_names: Ordered list of source names.
    """
    if not package_owners:
        print("\nkanon install: no packages synced.")
        return

    # Group packages by source, preserving source order
    by_source: dict[str, list[str]] = {name: [] for name in source_names}
    for pkg_name, source_name in sorted(package_owners.items()):
        by_source[source_name].append(pkg_name)

    total = len(package_owners)
    print(f"\nkanon install: {total} packages synced to .packages/")
    for source_name in source_names:
        pkgs = by_source[source_name]
        if not pkgs:
            continue
        print(f"\n  [{source_name}] ({len(pkgs)} packages)")
        for pkg in pkgs:
            print(f"    - {pkg}")


def _run_install(
    kanonenv_path: pathlib.Path,
    lockfile_path: pathlib.Path,
    catalog_source: str | None,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
    strict_lock: bool = False,
    strict_drift: bool = False,
) -> None:
    """Execute the install lifecycle without acquiring the concurrency lock.

    This is the inner implementation called by install() after the exclusive
    file lock is held. All filesystem mutations happen here.

    Implements the lockfile state-machine branching (spec Section 4.7):
    - LOCKFILE_ABSENT: resolve fresh, install, write lockfile.
    - LOCKFILE_CONSISTENT: install exactly the SHAs in the lockfile; skip resolve.
    - LOCKFILE_HASH_MISMATCH: raise KanonHashMismatchError immediately.
    - REFRESH_LOCK: ignore lockfile entirely, re-resolve fresh, overwrite lockfile.
    - REFRESH_LOCK_SOURCE: re-resolve exactly one source chain, preserve all others.

    All errors propagate unconditionally. There is no fallback logic.

    Args:
        kanonenv_path: Resolved absolute path to the .kanon configuration file.
        lockfile_path: Path to the .kanon.lock file (may or may not exist).
        catalog_source: Catalog source string from the CLI flag, or None when
            the caller did not provide one (the env var is consulted automatically).
        refresh_lock: When ``True``, short-circuit to ``InstallState.REFRESH_LOCK``
            regardless of lockfile presence or hash state.  The lockfile fallback
            in ``_resolve_catalog_source`` is disabled on this path.
        refresh_lock_source: When set, re-resolve exactly the named source chain
            while preserving all other lockfile entries.  The lockfile fallback
            in ``_resolve_catalog_source`` is disabled on this path.
        strict_lock: When ``True``, upgrade orphaned lock entries (sources in the
            lockfile but absent from ``.kanon``) to ``OrphanedLockEntryError``
            instead of pruning with an info-line.  Only applies in the consistent state.
        strict_drift: When ``True``, upgrade branch drift (branch tip on remote
            differs from locked SHA) to ``BranchDriftError`` instead of reusing
            the locked SHA with an info-line.  Only applies in the consistent state.

    Raises:
        KanonHashMismatchError: If the lockfile exists but its kanon_hash does
            not match the freshly-computed hash of the .kanon file.
        MissingCatalogSourceError: If no catalog source can be resolved from
            cli arg, env var, or lockfile fallback (AC-FUNC-007). Always raised;
            never swallowed.  On the REFRESH_LOCK path, the lockfile fallback is
            disabled and the remediation text explains this constraint.
        CatalogSourceMismatchError: If the resolved catalog source differs from
            the lockfile's recorded source in the consistent state.
        UnknownSourceError: If ``refresh_lock_source`` does not match any known
            top-level source name (by literal or derive_source_name match).
        OrphanedLockEntryError: If ``strict_lock=True`` and the lockfile contains
            sources absent from the current ``.kanon`` source declarations.
        BranchDriftError: If ``strict_drift=True`` and a branch-shaped source's
            remote tip differs from the locked SHA.
        CanonicalUrlConflictError: If two or more sources declare the same
            canonical URL with different resolved SHAs.  Raised on both the
            absent-lockfile path (after fresh resolution) and the consistent
            path (against the existing lockfile contents).
        ValueError: If the catalog source is not in ``url@ref`` form, if
            git ls-remote fails or a ref is not found, if marketplace install
            is requested but CLAUDE_MARKETPLACES_DIR is not configured, or on
            package collision.
        OSError: If a source directory cannot be created.
        RepoCommandError: If any repo sub-command exits non-zero.
    """
    # Step 1: Classify the lockfile state.
    # When refresh_lock_source is set, we short-circuit to REFRESH_LOCK_SOURCE.
    # When refresh_lock=True, _classify_install_state short-circuits to REFRESH_LOCK.
    # Otherwise run the normal five-row classification.
    install_state: InstallState
    existing_lockfile: Lockfile | None
    lockfile_hash_mismatch_lockfile: Lockfile | None = None
    lockfile_hash_mismatch_computed: str | None = None

    if refresh_lock_source is not None:
        # REFRESH_LOCK_SOURCE path: read the existing lockfile for the partial merge.
        # If absent, proceed as REFRESH_LOCK_SOURCE with no existing lockfile
        # (the partial merge step falls back to a full write in that case).
        install_state = InstallState.REFRESH_LOCK_SOURCE
        existing_lockfile = read_lockfile_if_present(lockfile_path)
    else:
        classification = _classify_install_state(kanonenv_path, lockfile_path, refresh_lock=refresh_lock)
        install_state = classification.state
        existing_lockfile = classification.lockfile
        if install_state is InstallState.LOCKFILE_HASH_MISMATCH:
            lockfile_hash_mismatch_lockfile = classification.lockfile
            lockfile_hash_mismatch_computed = classification.computed_hash

    # _consistent_has_orphans: set True when orphans were detected and pruned so
    # step 7 knows to rewrite the lockfile without the orphaned entries.
    # Declared here (before Step 2) so the hash-mismatch orphan-rescue path in
    # Step 2 can set it when reclassifying a LOCKFILE_HASH_MISMATCH caused solely
    # by orphan-triple removal from .kanon.
    _consistent_has_orphans: bool = False

    # Step 2: On hash mismatch, check whether the mismatch is caused solely by
    # orphaned lock entries (sources in .kanon.lock absent from .kanon).  If so
    # and strict_lock is False, auto-prune the orphans and continue as if the
    # lockfile were consistent.  If strict_lock is True, raise OrphanedLockEntryError
    # so the operator can decide.  If orphans do NOT explain the mismatch (i.e.
    # the .kanon content changed for a reason other than orphan removal), raise
    # KanonHashMismatchError.
    if install_state is InstallState.LOCKFILE_HASH_MISMATCH:
        # Both fields are populated by _classify_install_state in the HASH_MISMATCH
        # branch (assigned above).  cast() communicates non-None to the type checker.
        existing_lockfile_nn = cast(Lockfile, lockfile_hash_mismatch_lockfile)
        computed_hash_nn = cast(str, lockfile_hash_mismatch_computed)

        # Parse .kanon to get the current set of source names so we can detect
        # orphaned lock entries (lockfile sources absent from the current .kanon).
        mismatch_config = parse_kanonenv(kanonenv_path)
        mismatch_source_names: list[str] = mismatch_config["KANON_SOURCES"]
        orphaned_on_mismatch = _detect_orphaned_lock_entries(existing_lockfile_nn, mismatch_source_names)
        if orphaned_on_mismatch:
            if strict_lock:
                raise OrphanedLockEntryError(orphaned_names=orphaned_on_mismatch)
            # Non-strict path: auto-prune the orphaned entries and continue as
            # LOCKFILE_CONSISTENT so the install replays the remaining locked SHAs.
            # The pruned lockfile carries the new kanon_hash (computed from the
            # current .kanon, which already has the orphan triples removed).
            for orphan_name in orphaned_on_mismatch:
                print(f"{INFO_PRUNED_ORPHAN_LOCK_ENTRY}: {orphan_name}")
            # Build the pruned lockfile with the current kanon_hash so the next
            # install sees it as LOCKFILE_CONSISTENT.
            active_names_set = set(mismatch_source_names)
            pruned_sources_early = [e for e in existing_lockfile_nn.sources if e.name in active_names_set]
            pruned_lockfile_early = Lockfile(
                schema_version=existing_lockfile_nn.schema_version,
                generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                generator=existing_lockfile_nn.generator,
                kanon_hash=computed_hash_nn,
                catalog=existing_lockfile_nn.catalog,
                sources=pruned_sources_early,
            )
            write_lockfile(pruned_lockfile_early, lockfile_path)
            # Reclassify: treat this run as LOCKFILE_CONSISTENT using the pruned lockfile.
            # _consistent_has_orphans stays False here: the lockfile has already been
            # written above, so Step 7's orphan-rewrite branch must NOT fire a second
            # time for the same prune.
            install_state = InstallState.LOCKFILE_CONSISTENT
            existing_lockfile = pruned_lockfile_early
        else:
            raise KanonHashMismatchError(
                lockfile_hash=existing_lockfile_nn.kanon_hash,
                computed_hash=computed_hash_nn,
            )

    # Step 3: Read catalog source from env var if not supplied by caller.
    env_catalog = os.environ.get(CATALOG_ENV_VAR)
    lockfile_catalog_source: str | None = existing_lockfile.catalog.source if existing_lockfile is not None else None

    # Step 4: Resolve the effective catalog source following precedence rules.
    # _resolve_catalog_source enforces the four-tier precedence (CLI > env > lockfile
    # fallback > .kanon [catalog] block) and raises MissingCatalogSourceError when
    # all tiers are unset (AC-FUNC-007). The lockfile fallback applies only in
    # LOCKFILE_CONSISTENT state. The .kanon block fallback applies in LOCKFILE_ABSENT
    # state when the block was written by a preceding `kanon add` invocation.
    effective_catalog_source: str = _resolve_catalog_source(
        cli_arg=catalog_source,
        env_value=env_catalog,
        lockfile_catalog_source=lockfile_catalog_source,
        install_state=install_state,
        kanon_path=kanonenv_path,
    )

    print(f"kanon install: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)

    # Scan .kanon for unresolved placeholders BEFORE repo envsubst (spec E28 Change (b)).
    # Any value matching <[A-Z_|]+> is a literal placeholder the operator forgot to
    # replace.  Raising here gives a structured diagnostic rather than an opaque
    # repo sync 404 or git-remote error.
    placeholder_findings = _scan_kanonenv_for_unresolved_placeholders(kanonenv_path)
    if placeholder_findings:
        first_line_no, first_placeholder = placeholder_findings[0]
        raise UnresolvedPlaceholderError(
            line_number=first_line_no,
            placeholder=first_placeholder,
            all_findings=placeholder_findings,
        )

    base_dir = kanonenv_path.parent
    source_names = config["KANON_SOURCES"]
    sources = config["sources"]
    marketplace_install = config["KANON_MARKETPLACE_INSTALL"]
    globals_dict = config["globals"]

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    if marketplace_install and not marketplace_dir_str:
        raise ValueError("KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined in .kanon")

    if marketplace_install:
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        print("kanon install: preparing marketplace directory...")
        prepare_marketplace_dir(marketplace_dir)

    repo_rev = globals_dict.get("REPO_REV", "")

    env_vars: dict[str, str] = {}
    if "GITBASE" in globals_dict:
        env_vars["GITBASE"] = globals_dict["GITBASE"]
    if marketplace_dir_str:
        env_vars["CLAUDE_MARKETPLACES_DIR"] = marketplace_dir_str

    source_dirs = create_source_dirs(source_names, base_dir)

    # Compute the allow_insecure flag once: True only when the env var is exactly "1".
    # This is used by _enforce_remote_url_policy for every encountered source URL.
    allow_insecure: bool = os.environ.get(KANON_ALLOW_INSECURE_REMOTES) == "1"

    # Step 5a: In the LOCKFILE_CONSISTENT state, apply strictness checks and
    # drift detection BEFORE entering the per-source loop.
    # Orphan check: sources in the lockfile but absent from .kanon.
    # Drift check: branch-shaped sources whose remote tip differs from locked SHA.
    # Both checks run only in the consistent state; refresh and absent paths skip them.
    # _consistent_has_orphans is declared before Step 2 so the hash-mismatch
    # orphan-rescue path can set it when reclassifying to LOCKFILE_CONSISTENT.
    # _drifted_source_names: set of source names with detected branch drift in
    # the consistent state.  Used to skip SHA reachability checks for those
    # sources (the locked SHA is not a current ref head after the branch moved,
    # but we are intentionally reusing it in the default drift-reuse path).
    _drifted_source_names: set[str] = set()
    if install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
        orphaned = _detect_orphaned_lock_entries(existing_lockfile, source_names)
        if orphaned:
            if strict_lock:
                raise OrphanedLockEntryError(orphaned_names=orphaned)
            _consistent_has_orphans = True
            for orphan_name in orphaned:
                print(f"{INFO_PRUNED_ORPHAN_LOCK_ENTRY}: {orphan_name}")

        drift_reports = _detect_branch_drift(existing_lockfile)
        if drift_reports:
            if strict_drift:
                raise BranchDriftError(reports=drift_reports)
            for report in drift_reports:
                _drifted_source_names.add(report.source_name)
                print(
                    f"branch drift: {report.source_name}: {report.branch} tip "
                    f"{report.current_sha} differs from locked {report.locked_sha}; "
                    f"reusing locked SHA"
                )

        # Canonical-URL conflict check on the consistent path: run the detector
        # against the lockfile contents before replaying SHAs.  A conflict baked
        # into the lockfile surfaces here so the operator sees the error and can
        # remediate without waiting for a full re-resolve.
        lockfile_projects = _gather_resolved_projects(existing_lockfile.sources)
        canonical_conflict_reports = _detect_canonical_url_conflicts(lockfile_projects)
        if canonical_conflict_reports:
            raise CanonicalUrlConflictError(reports=canonical_conflict_reports)

    # Step 5: Resolve SHAs and sync sources.
    # In the LOCKFILE_CONSISTENT state, replay the pinned SHAs from the lockfile
    # instead of calling resolve_version() (which would query the remote).
    # In the REFRESH_LOCK_SOURCE state, re-resolve only the named source; replay
    # all others from the existing lockfile verbatim.
    # resolved_entries: populated for lockfile writing.
    resolved_entries: list[SourceEntry] = []

    # For REFRESH_LOCK_SOURCE: resolve the target entry from the existing lockfile.
    # Do this before the per-source loop so we can fail fast with UnknownSourceError
    # before touching any source directories.
    # refresh_lock_source is non-None when install_state is REFRESH_LOCK_SOURCE.
    refresh_lock_source_nn: str = cast(str, refresh_lock_source)
    target_source_entry: SourceEntry | None = None
    if install_state is InstallState.REFRESH_LOCK_SOURCE and existing_lockfile is not None:
        target_source_entry = _resolve_source_name(refresh_lock_source_nn, existing_lockfile)
    elif install_state is InstallState.REFRESH_LOCK_SOURCE and existing_lockfile is None:
        # No lockfile exists -- treat the named source as a synthetic lookup against
        # the .kanon source names directly, then resolve fresh.
        if refresh_lock_source_nn not in source_names:
            normalised = derive_source_name(refresh_lock_source_nn)
            if normalised not in source_names:
                raise UnknownSourceError(name=refresh_lock_source_nn, known_names=source_names)
        # target_source_entry remains None; the per-source loop resolves fresh.

    for name in source_names:
        source_dir = source_dirs[name]
        source_data = sources[name]
        print(f"kanon install: syncing source '{name}'...")

        # HTTPS enforcement (spec Section 4.7 / Section 3.6 trust model).
        # On the lockfile-consistent replay path, check the locked URL so a
        # malicious lockfile that records an HTTP remote is rejected before any
        # clone attempt.  On all other paths, check the .kanon source URL.
        if install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
            _replay_candidate = next(
                (e for e in existing_lockfile.sources if e.name == name),
                None,
            )
            if _replay_candidate is None:
                raise InstallError(
                    f"BUG: source {name!r} not found in lockfile under LOCKFILE_CONSISTENT state"
                    " -- kanon_hash consistency violation"
                )
            _url_to_check = _replay_candidate.url
        else:
            _url_to_check = source_data["url"]
        _enforce_remote_url_policy(
            url=_url_to_check,
            allow_insecure=allow_insecure,
            remote_name=name,
            source_path=name,
        )

        if install_state is InstallState.REFRESH_LOCK_SOURCE:
            # Determine whether this source is the one being refreshed.
            is_refresh_target = (target_source_entry is not None and target_source_entry.name == name) or (
                # Lockfile-absent path: match by name or derive_source_name.
                existing_lockfile is None
                and (name == refresh_lock_source_nn or name == derive_source_name(refresh_lock_source_nn))
            )

            if is_refresh_target:
                # Re-resolve this source fresh.
                new_entry = _refresh_one_source(name, source_data)
                resolved_entries.append(new_entry)
                resolved_revision = new_entry.resolved_sha
            elif existing_lockfile is not None:
                # Preserve this source's entry verbatim from the existing lockfile.
                pinned = next(
                    (e for e in existing_lockfile.sources if e.name == name),
                    None,
                )
                if pinned is not None:
                    resolved_revision = pinned.resolved_sha
                    resolved_entries.append(pinned)
                else:
                    # Source not in lockfile -- resolve fresh.
                    new_entry = _refresh_one_source(name, source_data)
                    resolved_entries.append(new_entry)
                    resolved_revision = new_entry.resolved_sha
            else:
                # No lockfile -- resolve all sources fresh.
                new_entry = _refresh_one_source(name, source_data)
                resolved_entries.append(new_entry)
                resolved_revision = new_entry.resolved_sha
        elif install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
            # Replay: find the pinned entry for this source.
            pinned = next(
                (e for e in existing_lockfile.sources if e.name == name),
                None,
            )
            if pinned is not None:
                # Verify SHA reachability before replaying: list all remote refs
                # and check whether the pinned SHA appears in the first column.
                # git ls-remote with a bare SHA pattern always returns empty output
                # (only ref names are matched), so we list all refs and grep the SHA.
                # Skip reachability check for drifted branch-shaped sources: after
                # the branch tip has moved, the locked SHA is no longer a ref head
                # and would falsely fail the reachability check.  The drift info-line
                # was already emitted (or BranchDriftError was raised) above.
                if name not in _drifted_source_names:
                    _check_sha_reachable(
                        url=pinned.url,
                        sha=pinned.resolved_sha,
                        source_name=name,
                    )
                resolved_revision = pinned.resolved_sha
                resolved_entries.append(pinned)
            else:
                # Source in .kanon but not in lockfile -- resolve fresh.
                resolved_revision = resolve_version(source_data["url"], source_data["revision"])
                ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
                resolved_entries.append(
                    SourceEntry(
                        name=name,
                        url=source_data["url"],
                        revision_spec=source_data["revision"],
                        resolved_ref=ref_resolution.resolved_ref,
                        resolved_sha=ref_resolution.sha,
                        path=source_data["path"],
                    )
                )
        else:
            resolved_revision = resolve_version(source_data["url"], source_data["revision"])
            # Resolve the actual commit SHA and the matched ref for the lockfile entry.
            # ValueError propagates unconditionally (fail-fast; no silent degradation).
            ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
            resolved_entries.append(
                SourceEntry(
                    name=name,
                    url=source_data["url"],
                    revision_spec=source_data["revision"],
                    resolved_ref=ref_resolution.resolved_ref,
                    resolved_sha=ref_resolution.sha,
                    path=source_data["path"],
                )
            )

        print(f"  repo init ({source_data['path']})...")
        # On the refresh path, reset the .repo/manifests working tree before
        # re-init. kanon's own repo envsubst step (from the previous install)
        # dirtied the working tree by rewriting manifest XML files and leaving
        # .bak sibling files. If the new manifest commit also changes manifest.xml,
        # git refuses the checkout ("local changes would be overwritten"), leaves
        # HEAD pointing to the deleted 'default' branch ref, and the subsequent
        # rev-list ^HEAD <sha> raises an unhandled GitCommandError. Resetting the
        # working tree to HEAD state before re-init lets git checkout the new
        # manifest commit cleanly. (AC-FUNC-001)
        if install_state in (InstallState.REFRESH_LOCK, InstallState.REFRESH_LOCK_SOURCE):
            # On the refresh path, reset the .repo/manifests working tree before
            # re-init, then wrap repo init so that any git-level failure
            # (including the GitCommandError from rev-list ^HEAD on a deleted branch ref)
            # is caught and re-raised as a handled kanon ERROR: with the offending source
            # name and a remediation hint, never as a raw traceback. (AC-FUNC-001, AC-FUNC-002)
            try:
                _reset_manifests_working_tree(source_dir)
            except OSError as exc:
                raise RefreshRepoInitError(source_name=name, cause=exc) from exc
            try:
                run_repo_init(
                    source_dir,
                    source_data["url"],
                    resolved_revision,
                    source_data["path"],
                    repo_rev,
                )
            except GitCommandError as exc:
                raise RefreshRepoInitError(source_name=name, cause=exc) from exc
        else:
            run_repo_init(
                source_dir,
                source_data["url"],
                resolved_revision,
                source_data["path"],
                repo_rev,
            )
        print("  repo envsubst...")
        run_repo_envsubst(source_dir, env_vars)
        print("  repo sync...")
        run_repo_sync(source_dir)

        # Walk the <include> chain from the checked-out manifest XML.
        # After repo init + repo sync, manifest files live under
        # source_dir/.repo/manifests/ (the repo tool's manifest checkout dir).
        # _walk_includes uses that directory as the manifest repo root so all
        # <include name=...> values (relative to the repo root) resolve correctly.
        # The walker raises IncludeCycleError on cycles and MalformedIncludeError
        # on malformed elements -- both propagate unconditionally (fail-fast).
        # Only the root's children become [[sources.includes]] entries; the root
        # itself is already recorded in the [[sources]] entry above.
        manifest_repo_root = source_dir / ".repo" / "manifests"
        manifest_xml_path = manifest_repo_root / source_data["path"]

        # Process <linkfile> elements from the manifest XML to ensure that
        # marketplace plugin manifests are copied into CLAUDE_MARKETPLACES_DIR.
        # This supplements the repo tool's native linkfile processing so that
        # marketplace entries are present for install_marketplace_plugins even
        # when the repo tool's linkfile step did not run (spec Section 4 E35).
        if marketplace_install:
            _process_manifest_linkfiles(manifest_xml_path, source_dir)
        include_tree = _walk_includes(manifest_xml_path, manifest_repo_root)
        # resolved_entries[-1] is the SourceEntry appended for this source
        # in the resolution branches above. Populate its includes list with
        # the DFS-ordered, diamond-deduped tree the walker produced.
        resolved_entries[-1].includes = _include_tree_to_entries(
            include_tree,
            source_url=source_data["url"],
            resolved_sha=resolved_entries[-1].resolved_sha,
        )

    # Canonical-URL conflict check on the absent/refresh paths: run the detector
    # against the freshly-resolved entries now that all sources have been resolved.
    # The consistent path already ran this check against the lockfile contents above.
    if install_state is not InstallState.LOCKFILE_CONSISTENT:
        fresh_projects = _gather_resolved_projects(resolved_entries)
        canonical_conflict_reports = _detect_canonical_url_conflicts(fresh_projects)
        if canonical_conflict_reports:
            raise CanonicalUrlConflictError(reports=canonical_conflict_reports)

    print("kanon install: aggregating packages into .packages/...")
    package_owners = aggregate_symlinks(source_names, base_dir)
    update_gitignore(base_dir)

    # Step 6: Emit the spec's info-line for the current state.
    if install_state is InstallState.REFRESH_LOCK_SOURCE and target_source_entry is not None:
        # Count refreshed vs preserved top-level source entries.
        # A source is refreshed when its name matches the target; all other
        # top-level sources in resolved_entries are preserved (kept as-is).
        refreshed_name = target_source_entry.name
        refreshed_count = sum(1 for e in resolved_entries if e.name == refreshed_name)
        preserved_count = sum(1 for e in resolved_entries if e.name != refreshed_name)
        _emit_install_state(
            install_state,
            sources=len(source_names),
            projects=len(package_owners),
            refreshed_source_name=refreshed_name,
            refreshed_count=refreshed_count,
            preserved_count=preserved_count,
        )
    else:
        _emit_install_state(install_state, sources=len(source_names), projects=len(package_owners))

    _print_package_summary(package_owners, source_names)

    if marketplace_install:
        print("\nkanon install: installing marketplace plugins...")
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        install_marketplace_plugins(marketplace_dir)

    # Step 7: Write the lockfile.
    # - LOCKFILE_ABSENT: write fresh lockfile.
    # - REFRESH_LOCK: full rebuild; overwrite lockfile.
    # - REFRESH_LOCK_SOURCE: partial rebuild; merge one source into old lockfile.
    # - LOCKFILE_CONSISTENT with orphans pruned: rewrite without orphaned entries.
    # - LOCKFILE_CONSISTENT (no orphans): lockfile is authoritative; do NOT rewrite.
    if install_state in (InstallState.LOCKFILE_ABSENT, InstallState.REFRESH_LOCK):
        # In the LOCKFILE_ABSENT state, computed_hash is always None because
        # _classify_install_state does not call kanon_hash when there is no
        # lockfile to compare against. Compute it now.
        computed_hash = _kanon_hash(kanonenv_path)

        # Build the catalog block.  effective_catalog_source is always a non-empty
        # string here: _resolve_catalog_source raised MissingCatalogSourceError above
        # when all tiers were unset.  Fail fast if the value lacks the '@' separator.
        if "@" not in effective_catalog_source:
            raise ValueError(
                f"catalog source must be in <url>@<ref> form; got: {effective_catalog_source!r}",
            )
        catalog_url, catalog_ref = effective_catalog_source.rsplit("@", 1)

        # Resolve the catalog ref to a SHA and its fully-qualified ref string.
        catalog_resolution = _resolve_ref_to_sha(catalog_url, catalog_ref)
        catalog_block = CatalogBlock(
            source=effective_catalog_source,
            url=catalog_url,
            revision_spec=catalog_ref,
            resolved_ref=catalog_resolution.resolved_ref,
            resolved_sha=catalog_resolution.sha,
        )

        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=f"kanon-cli/{__version__}",
            kanon_hash=computed_hash,
            catalog=catalog_block,
            sources=resolved_entries,
        )
        write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.REFRESH_LOCK_SOURCE:
        # Partial rebuild: merge the refreshed source into the existing lockfile.
        new_kanon_hash = _kanon_hash(kanonenv_path)
        if existing_lockfile is not None and target_source_entry is not None:
            # Find the freshly-resolved entry for the target source.
            refreshed_entry = next(
                (e for e in resolved_entries if e.name == target_source_entry.name),
                None,
            )
            if refreshed_entry is None:
                raise ValueError(
                    f"Internal error: refreshed entry for source "
                    f"'{target_source_entry.name}' not found in resolved_entries."
                )
            merged_lf = _merge_partial_lockfile(
                old_lockfile=existing_lockfile,
                refreshed_source=refreshed_entry,
                new_kanon_hash=new_kanon_hash,
            )
            write_lockfile(merged_lf, lockfile_path)
        else:
            # No existing lockfile -- write a full lockfile as if LOCKFILE_ABSENT.
            if "@" not in effective_catalog_source:
                raise ValueError(
                    f"catalog source must be in <url>@<ref> form; got: {effective_catalog_source!r}",
                )
            catalog_url, catalog_ref = effective_catalog_source.rsplit("@", 1)
            catalog_resolution = _resolve_ref_to_sha(catalog_url, catalog_ref)
            catalog_block = CatalogBlock(
                source=effective_catalog_source,
                url=catalog_url,
                revision_spec=catalog_ref,
                resolved_ref=catalog_resolution.resolved_ref,
                resolved_sha=catalog_resolution.sha,
            )
            lf = Lockfile(
                schema_version=CURRENT_SCHEMA_VERSION,
                generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                generator=f"kanon-cli/{__version__}",
                kanon_hash=new_kanon_hash,
                catalog=catalog_block,
                sources=resolved_entries,
            )
            write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.LOCKFILE_CONSISTENT and _consistent_has_orphans:
        # Orphans were pruned from the consistent-state run.  Rewrite the lockfile
        # without the orphaned entries so subsequent installs do not re-detect them.
        # The kanon_hash, catalog block, and all non-orphan source entries are
        # preserved verbatim from the existing lockfile (it is still consistent).
        pruned_lf_nn = cast(Lockfile, existing_lockfile)
        active_names = set(source_names)
        pruned_sources = [e for e in pruned_lf_nn.sources if e.name in active_names]
        pruned_lockfile = Lockfile(
            schema_version=pruned_lf_nn.schema_version,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=pruned_lf_nn.generator,
            kanon_hash=pruned_lf_nn.kanon_hash,
            catalog=pruned_lf_nn.catalog,
            sources=pruned_sources,
        )
        write_lockfile(pruned_lockfile, lockfile_path)

    print("\nkanon install: done.")


def install(
    kanonenv_path: pathlib.Path,
    lock_file_path: pathlib.Path,
    catalog_source: str | None = None,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
    strict_lock: bool = False,
    strict_drift: bool = False,
) -> None:
    """Execute the full Kanon install lifecycle.

    Acquires an exclusive workspace lock via ``kanon_workspace_lock`` on
    ``.kanon-data/.kanon-install.lock`` before performing any filesystem
    mutations. This serializes concurrent invocations so that two simultaneous
    ``kanon install`` runs on the same project directory do not interleave their
    writes. The same lock is acquired by ``kanon add``, ``kanon remove``, and
    ``kanon doctor --refresh-completion-cache`` so all mutating commands
    serialise on a single per-workspace lock.

    The ``.kanon-data/`` directory is created eagerly before the lock is
    acquired (inside ``kanon_workspace_lock``) so that a first invocation in a
    fresh workspace does not fail with ``FileNotFoundError``.

    Steps:
      1. Acquire exclusive workspace lock (creates .kanon-data/ if absent).
      2. Classify the lockfile state via _classify_install_state.
         When refresh_lock=True, short-circuits to InstallState.REFRESH_LOCK.
         When refresh_lock_source is set, uses InstallState.REFRESH_LOCK_SOURCE.
      3. Resolve the effective catalog source via _resolve_catalog_source.
         On the REFRESH_LOCK and REFRESH_LOCK_SOURCE paths, the lockfile
         fallback is disabled.
      4. Parse .kanon and validate sources.
      4a. In LOCKFILE_CONSISTENT state: detect orphans and branch drift.
         Prune orphans (or raise OrphanedLockEntryError with --strict-lock).
         Log drift info-lines (or raise BranchDriftError with --strict-drift).
      5. If KANON_MARKETPLACE_INSTALL=true: create and clean marketplace dir.
      6. For each source: mkdir, repo init (or lockfile replay), envsubst, sync.
         On the REFRESH_LOCK_SOURCE path, only the named source is re-resolved;
         all other sources replay their pinned SHAs from the existing lockfile.
      7. Aggregate symlinks into .packages/.
      8. Update .gitignore.
      9. Emit state info-line via _emit_install_state.
      10. If KANON_MARKETPLACE_INSTALL=true: run install script.
      11. Write .kanon.lock: full write for LOCKFILE_ABSENT/REFRESH_LOCK;
          partial merge for REFRESH_LOCK_SOURCE; pruned rewrite for
          LOCKFILE_CONSISTENT with orphans; unchanged for LOCKFILE_CONSISTENT
          without orphans.

    Args:
        kanonenv_path: Path to the .kanon configuration file.
        lock_file_path: Pre-resolved path to the .kanon.lock file. The caller
            is responsible for resolution via ``derive_lock_file_path``; this
            function does not apply any fallback or derivation.
        catalog_source: Effective catalog source (cli flag value takes
            precedence over the KANON_CATALOG_SOURCE env var, which is read
            automatically inside _run_install). Pass None when no CLI flag
            is present; the env var will be consulted automatically.
        refresh_lock: When ``True``, ignore the existing lockfile entirely and
            rebuild it from scratch.  The lockfile fallback for catalog source
            resolution is disabled on this path.  Default ``False`` preserves
            prior behaviour.
        refresh_lock_source: When set to a source name or catalog entry name,
            re-resolve exactly that source's chain while preserving every other
            lockfile entry verbatim.  Mutually exclusive with ``refresh_lock``
            (enforced at the CLI level by argparse).  The lockfile fallback for
            catalog source resolution is disabled on this path.  Default ``None``
            preserves prior behaviour.
        strict_lock: When ``True``, upgrade orphaned lock entries to
            ``OrphanedLockEntryError`` instead of pruning with an info-line.  Only
            applies in the ``LOCKFILE_CONSISTENT`` state.  Default ``False``
            preserves prior behaviour (prune + info-line).
        strict_drift: When ``True``, upgrade branch drift to
            ``BranchDriftError`` instead of reusing the locked SHA with an info-line.
            Only applies in the ``LOCKFILE_CONSISTENT`` state.  Default
            ``False`` preserves prior behaviour (reuse + info-line).

    Raises:
        KanonHashMismatchError: If the lockfile exists but its kanon_hash does
            not match the freshly-computed hash of the .kanon file.
        MissingCatalogSourceError: If the consistent state requires a catalog
            source but none can be resolved from cli arg, env var, or lockfile.
            On the REFRESH_LOCK and REFRESH_LOCK_SOURCE paths the lockfile
            fallback is disabled and the error message includes the
            refresh-specific remediation text.
        CatalogSourceMismatchError: If the CLI/env catalog source differs from
            the lockfile's recorded source in the consistent state.
        UnknownSourceError: If ``refresh_lock_source`` does not match any known
            top-level source name by direct lookup or via ``derive_source_name``.
        OrphanedLockEntryError: If ``strict_lock=True`` and the lockfile has
            sources absent from the current ``.kanon`` declarations.
        BranchDriftError: If ``strict_drift=True`` and a branch-shaped source's
            remote tip differs from the locked SHA.
        ValueError: If marketplace install is requested but
            CLAUDE_MARKETPLACES_DIR is not configured, or on package collision.
        OSError: If the managed data directory or a source directory cannot be
            created, with the failing path and OS error message included.
        RepoCommandError: If any repo sub-command exits non-zero.
    """
    kanonenv_path = kanonenv_path.resolve()
    base_dir = kanonenv_path.parent

    with kanon_workspace_lock(base_dir):
        _run_install(
            kanonenv_path,
            lock_file_path,
            catalog_source,
            refresh_lock=refresh_lock,
            refresh_lock_source=refresh_lock_source,
            strict_lock=strict_lock,
            strict_drift=strict_drift,
        )
