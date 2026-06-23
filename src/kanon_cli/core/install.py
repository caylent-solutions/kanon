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

Lockfile state machine
----------------------
Every ``kanon install`` invocation inspects the state matrix:

  LOCKFILE_ABSENT        -- .kanon.lock absent; resolve fresh, write lockfile.
  LOCKFILE_CONSISTENT    -- .kanon.lock present and kanon_hash matches; replay SHAs.
  LOCKFILE_HASH_MISMATCH -- .kanon.lock present but kanon_hash differs.  Default
                            install derives RECONCILE; --strict-lock turns it into
                            a clean hard error (npm ci).
  RECONCILE              -- npm install: prune orphans, resolve added/changed sources
                            fresh, replay unchanged sources, rebuild + write the lock
                            once at the end on success only.
  LOCKFILE_UNREACHABLE   -- lockfile SHA no longer reachable on remote; hard error.
  REFRESH_LOCK_SOURCE    -- operator requested partial lockfile rebuild via --refresh-lock-source.

``kanon install`` is hermetic (spec Section 4.3 / FR-14): the schema-v4 lock carries
no ``[catalog]`` block, so install neither resolves nor records a catalog source.  It
is driven solely by the committed ``.kanon`` (+ ``.kanon.lock``); ``--catalog-source``
is not accepted by the install parser (passing it exits non-zero), and a populated
``KANON_CATALOG_SOURCES`` environment variable has no effect on install (it is ignored,
not read).

Exception hierarchy:

  InstallError                -- base class for all install-state hard errors (defined in
                                 core/include_walker.py; re-exported here for backwards compatibility).
  KanonHashMismatchError      -- kanon_hash in lockfile != freshly-computed hash.
  LockfileUnreachableShaError -- a lockfile SHA is no longer reachable on remote.
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
import sys
import xml.etree.ElementTree as ET
from typing import NamedTuple, cast

from packaging.specifiers import SpecifierSet, InvalidSpecifier

import kanon_cli.repo as _repo
from kanon_cli.repo.git_command import GitCommandError
from kanon_cli import __version__
from kanon_cli.constants import (
    KANON_ALLOW_INSECURE_REMOTES,
    KANON_GIT_LS_REMOTE_TIMEOUT,
    WORKSPACE_DIR_ENV_VAR,
)
from kanon_cli.core.git_runner import run_git_ls_remote
from kanon_cli.core.kanon_hash import kanon_hash as _kanon_hash
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
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
from kanon_cli.core.marketplace import (
    create_dirsymlink,
    discover_registered_marketplace_names,
    install_marketplace_plugins,
    locate_claude_binary,
    register_direct_checkout_marketplaces,
    remove_marketplace,
)
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
    "resolve_workspace_base_dir",
]


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

    The rows are:
    - LOCKFILE_ABSENT:          .kanon.lock absent; resolve fresh, write lockfile.
    - LOCKFILE_CONSISTENT:      .kanon.lock present and kanon_hash matches; replay SHAs.
    - LOCKFILE_HASH_MISMATCH:   .kanon.lock present but kanon_hash differs; classification
                                result only.  Default install derives ``RECONCILE`` from it;
                                ``--strict-lock`` turns it into a clean hard error.
    - RECONCILE:                default install with a hash mismatch; reconcile .kanon <-> lock
                                npm-style (prune orphans, resolve added/changed sources fresh,
                                replay unchanged sources, rebuild + write the lock once on success).
    - LOCKFILE_UNREACHABLE:     lockfile SHA no longer reachable on remote; hard error.
    - REFRESH_LOCK:             operator requested a full lockfile rebuild via --refresh-lock;
                                short-circuits the normal state classification.
    - REFRESH_LOCK_SOURCE:      operator requested partial rebuild via --refresh-lock-source;
                                re-resolves exactly one source chain, preserves all others.
    """

    LOCKFILE_ABSENT = "lockfile-absent"
    LOCKFILE_CONSISTENT = "lockfile-consistent"
    LOCKFILE_HASH_MISMATCH = "lockfile-hash-mismatch"
    RECONCILE = "reconcile"
    LOCKFILE_UNREACHABLE = "lockfile-unreachable"
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
    install has not yet run) or when the directory exists but is not a git
    working tree (integration tests use a plain directory in place of a real
    repo; there is nothing to reset in that case).

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``. The manifests
            working tree is at ``source_dir / ".repo" / "manifests"``.

    Raises:
        OSError: If the ``git checkout -- .`` or ``.bak`` cleanup fails due
            to a file-system error on a valid git working tree. The exception
            message names the path and the underlying OS error.
    """
    manifests_dir = source_dir / ".repo" / "manifests"
    if not manifests_dir.is_dir():
        return

    # Detect whether manifests_dir is a git working tree by checking for the
    # presence of a .git entry (file or directory).  This check must not
    # raise and must not write to stderr on the no-op path; a plain directory
    # check is the safest cross-platform approach that reuses no new helpers.
    if not (manifests_dir / ".git").exists():
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

    The LOCKFILE_UNREACHABLE row requires resolver output (live git ls-remote
    results) and is detected elsewhere in the install pipeline.

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


def _emit_install_state(
    state: InstallState,
    sources: int,
    projects: int,
    refreshed_source_name: str | None = None,
    refreshed_count: int = 0,
    preserved_count: int = 0,
) -> None:
    """Print the spec's verbatim info-line for the given install state to stdout.

    Five states produce an info-line:
    - LOCKFILE_ABSENT:        ``"lockfile rebuilt from .kanon (N sources, M projects)"``
    - LOCKFILE_CONSISTENT:    ``"installing from lockfile (N sources, M projects)"``
    - RECONCILE:              ``"lockfile reconciled with .kanon (N sources, M projects)"``
      (default install on a hash mismatch: prune orphans, resolve added/changed,
      replay unchanged, then rebuild + write the lock once on success)
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
    elif state is InstallState.RECONCILE:
        print(f"lockfile reconciled with .kanon ({sources} sources, {projects} projects)")
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
    resolved_revision = resolve_version(source_data["url"], source_data["ref"])
    ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
    return SourceEntry(
        alias=source_name,
        name=source_name,
        url=source_data["url"],
        ref_spec=source_data["ref"],
        resolved_ref=ref_resolution.resolved_ref,
        resolved_sha=ref_resolution.sha,
        path=source_data["path"],
    )


def _merge_partial_lockfile(
    old_lockfile: Lockfile,
    refreshed_source: SourceEntry,
    new_kanon_hash: str,
    attributed_marketplaces: dict[str, list[str]],
) -> Lockfile:
    """Replace exactly one ``SourceEntry`` in the lockfile, preserving all others.

    All other ``SourceEntry`` objects are carried over verbatim from
    ``old_lockfile``.  The top-level ``kanon_hash`` is updated to the
    freshly-computed value so the rewritten lockfile passes the consistency check
    on the next ``kanon install``.

    Every source's per-source ``registered_marketplaces`` ledger is refreshed
    from ``attributed_marketplaces``: install wiped and repopulated
    ``CLAUDE_MARKETPLACES_DIR`` for ALL current sources this run, so the freshly
    attributed set is authoritative for each.  A source not present in the dict
    (e.g. marketplace install disabled) is reset to an empty ledger.

    Args:
        old_lockfile: The existing parsed lockfile.
        refreshed_source: The rebuilt ``SourceEntry`` for the refreshed source.
            Its ``name`` must match exactly one entry in ``old_lockfile.sources``.
        new_kanon_hash: The freshly-computed ``kanon_hash`` for the current
            ``.kanon`` content.
        attributed_marketplaces: Mapping of current source name to the sorted
            marketplace names it registered this install.

    Returns:
        A new ``Lockfile`` instance with the refreshed source replaced and all
        other fields preserved from ``old_lockfile``.

    Raises:
        UnknownSourceError: If ``refreshed_source.name`` is not found in
            ``old_lockfile.sources``.
    """
    known = [e.name for e in old_lockfile.sources]
    if refreshed_source.name not in known:
        raise UnknownSourceError(name=refreshed_source.name, known_names=known)

    new_sources = [refreshed_source if e.name == refreshed_source.name else e for e in old_lockfile.sources]
    # Refresh every source's per-source ledger from the fresh attribution.
    for entry in new_sources:
        entry.registered_marketplaces = attributed_marketplaces.get(entry.name, [])
    return Lockfile(
        schema_version=old_lockfile.schema_version,
        generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generator=old_lockfile.generator,
        kanon_hash=new_kanon_hash,
        sources=new_sources,
        marketplace_registered=old_lockfile.marketplace_registered,
        marketplace_dir=old_lockfile.marketplace_dir,
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
    returncode, stdout, _stderr = run_git_ls_remote(
        ["git", "ls-remote", url],
        timeout=KANON_GIT_LS_REMOTE_TIMEOUT,
        retry_count=1,
    )
    if returncode != 0:
        raise LockfileUnreachableShaError(
            source_name=source_name,
            sha=sha,
            remote_url=url,
        )
    # Check the first column (SHA) of each tab-delimited line; a substring search
    # against the full stdout would produce false positives when a SHA appears in
    # a ref name (unlikely but possible with partial hashes or test fixtures).
    sha_found = any(line.split("\t")[0] == sha for line in stdout.strip().splitlines() if "\t" in line)
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
    returncode, stdout, stderr = run_git_ls_remote(
        ["git", "ls-remote", url, ref],
        timeout=KANON_GIT_LS_REMOTE_TIMEOUT,
        retry_count=1,
    )
    if returncode != 0:
        raise ValueError(f"ERROR: git ls-remote failed for url={url!r}, ref={ref!r}.\n  stderr: {stderr.strip()}")
    for line in stdout.strip().splitlines():
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


def resolve_workspace_base_dir(kanonenv_parent: pathlib.Path) -> pathlib.Path:
    """Resolve the base directory for .packages/ and .kanon-data/ artifacts.

    When the ``KANON_WORKSPACE_DIR`` environment variable is set, the value is
    resolved to an absolute path and used as the base directory.  The directory
    is created if it does not yet exist.  If creation fails or the resulting
    directory is not writable, the function calls ``sys.exit(1)`` with an
    actionable error message naming the path and the environment variable name.
    There is no silent fallback to ``kanonenv_parent``; the contract is strict
    fail-fast.

    When ``KANON_WORKSPACE_DIR`` is not set, the function returns
    ``kanonenv_parent`` -- the directory that contains the ``.kanon`` file --
    which is the original pre-env-var behavior.

    This function is the single resolution point shared by both ``install`` and
    ``clean`` so that the two commands agree on where artifacts are placed and
    removed.  ``clean.py`` imports this function from ``install.py``.

    Args:
        kanonenv_parent: The resolved parent directory of the ``.kanon`` file.
            Used as the fallback when ``KANON_WORKSPACE_DIR`` is unset.

    Returns:
        The absolute ``pathlib.Path`` to use as the base directory.

    Raises:
        SystemExit: With exit code 1 when ``KANON_WORKSPACE_DIR`` is set to an
            uncreatable or non-writable path.
    """
    raw = os.environ.get(WORKSPACE_DIR_ENV_VAR)
    if not raw:
        return kanonenv_parent

    workspace_path = pathlib.Path(raw).resolve()
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"ERROR: Cannot create {WORKSPACE_DIR_ENV_VAR} directory {workspace_path}: {exc.strerror}.\n"
            f"  Set {WORKSPACE_DIR_ENV_VAR} to a path that can be created, or unset the variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.access(workspace_path, os.W_OK):
        print(
            f"ERROR: {WORKSPACE_DIR_ENV_VAR} directory {workspace_path} is not writable.\n"
            f"  Fix permissions or set {WORKSPACE_DIR_ENV_VAR} to a writable path.",
            file=sys.stderr,
        )
        sys.exit(1)

    return workspace_path


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
            create_dirsymlink(link_path, pkg.resolve())

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
        existing_content = gitignore.read_text(encoding="utf-8")

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


def _strict_lock_drift_error(
    lockfile: "Lockfile",
    kanon_sources: list[str],
    computed_hash: str,
    kanon_revision_specs: "dict[str, str] | None" = None,
) -> InstallError:
    """Return the clean error to raise for a hash mismatch under ``--strict-lock``.

    ``--strict-lock`` is the ``npm ci`` analogue: it errors on ANY drift and never
    mutates the lockfile.  This helper only decides WHICH error to raise; the
    caller raises it without writing anything.

    The drift is "purely orphans" iff the operator's only change was removing one
    or more sources: at least one lockfile source is absent from ``.kanon`` (the
    orphans), NO ``.kanon`` source is absent from the lockfile (no additions), and
    every surviving source's ``.kanon`` revision spec still equals its locked
    ``revision_spec`` (no changed specs).  In that case ``OrphanedLockEntryError``
    -- which names each orphan and the remediation -- is the precise error.

    Any other mismatch (a newly-added source, or a changed revision spec on an
    existing source -- which keeps the same source-name set but still changes the
    ``kanon_hash``) is reported as ``KanonHashMismatchError``; its message already
    advises ``--refresh-lock`` / ``--refresh-lock-source``.

    Args:
        lockfile: The parsed lockfile whose ``kanon_hash`` no longer matches.
        kanon_sources: Source names declared in the current ``.kanon`` file.
        computed_hash: The freshly-computed ``kanon_hash`` of the current ``.kanon``.
        kanon_revision_specs: Optional mapping of source name to its current
            ``.kanon`` ``REVISION`` value.  When provided, a surviving source whose
            spec changed (relative to the locked entry) downgrades the decision from
            orphan-only to ``KanonHashMismatchError``.  When ``None``, only the
            name-set comparison (orphans vs additions) is used.

    Returns:
        An ``OrphanedLockEntryError`` for a pure-removal drift, otherwise a
        ``KanonHashMismatchError``.
    """
    orphans = _detect_orphaned_lock_entries(lockfile, kanon_sources)
    locked_names = {entry.name for entry in lockfile.sources}
    additions = [name for name in kanon_sources if name not in locked_names]
    spec_changed = False
    if kanon_revision_specs is not None:
        spec_changed = any(
            name in locked_names and not _should_replay_source(name, kanon_revision_specs.get(name), lockfile)
            for name in kanon_sources
        )
    if orphans and not additions and not spec_changed:
        return OrphanedLockEntryError(orphaned_names=orphans)
    return KanonHashMismatchError(
        lockfile_hash=lockfile.kanon_hash,
        computed_hash=computed_hash,
    )


def _should_replay_source(
    name: str,
    kanon_revision_spec: str | None,
    lockfile: "Lockfile | None",
) -> bool:
    """Decide whether a source should be replayed (preserve SHA) or resolved fresh.

    Replay iff the source exists in ``lockfile`` AND the current ``.kanon`` revision
    spec equals the locked entry's recorded ``revision_spec``.  Otherwise resolve
    fresh: the source is new (absent from the lock) or its revision spec changed.

    Args:
        name: The source name to look up.
        kanon_revision_spec: The ``REVISION`` value from the current ``.kanon`` for
            this source, or ``None`` when it cannot be compared (forces resolve).
        lockfile: The existing parsed lockfile, or ``None`` when absent (forces resolve).

    Returns:
        ``True`` to replay the locked SHA; ``False`` to resolve fresh.
    """
    if lockfile is None or kanon_revision_spec is None:
        return False
    pinned = next((entry for entry in lockfile.sources if entry.name == name), None)
    if pinned is None:
        return False
    return pinned.ref_spec == kanon_revision_spec


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
        if not _is_branch_shaped_spec(entry.ref_spec):
            continue
        # Determine the ref to query.  Use resolved_ref when available;
        # fall back to ref_spec for plain branch names.
        ref_to_query = entry.resolved_ref if entry.resolved_ref else entry.ref_spec

        returncode, stdout, _stderr = run_git_ls_remote(
            ["git", "ls-remote", entry.url, ref_to_query],
            timeout=KANON_GIT_LS_REMOTE_TIMEOUT,
            retry_count=1,
        )
        if returncode != 0:
            # ls-remote failure for drift check is non-fatal in strict-drift mode;
            # the caller handles BranchDriftError based on the reports list.
            # A reachability failure will surface separately via _check_sha_reachable.
            continue

        current_sha: str | None = None
        for line in stdout.strip().splitlines():
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
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
    strict_lock: bool = False,
    strict_drift: bool = False,
) -> None:
    """Execute the install lifecycle without acquiring the concurrency lock.

    This is the inner implementation called by install() after the exclusive
    file lock is held. All filesystem mutations happen here.

    Implements the lockfile state-machine branching:
    - LOCKFILE_ABSENT: resolve fresh, install, write lockfile.
    - LOCKFILE_CONSISTENT: install exactly the SHAs in the lockfile; skip resolve.
    - LOCKFILE_HASH_MISMATCH (default, npm install): derive RECONCILE -- prune
      orphans, resolve added/changed sources fresh, replay unchanged sources,
      rebuild + write the lockfile once at the end on success only.
    - LOCKFILE_HASH_MISMATCH (--strict-lock, npm ci): raise a clean error
      (OrphanedLockEntryError for a pure removal, else KanonHashMismatchError)
      WITHOUT mutating the lockfile.
    - REFRESH_LOCK: ignore lockfile entirely, re-resolve fresh, overwrite lockfile.
    - REFRESH_LOCK_SOURCE: re-resolve exactly one source chain, preserve all others.

    All errors propagate unconditionally. There is no fallback logic.

    ``kanon install`` is hermetic (spec Section 4.3 / FR-14): it is driven solely
    by the committed ``.kanon`` (+ ``.kanon.lock``).  No catalog source is threaded
    through this function; a populated ``KANON_CATALOG_SOURCES`` env var is ignored
    (never read here), and ``--catalog-source`` is not registered on the install
    parser so it cannot reach this code path.

    Args:
        kanonenv_path: Resolved absolute path to the .kanon configuration file.
        lockfile_path: Path to the .kanon.lock file (may or may not exist).
        refresh_lock: When ``True``, short-circuit to ``InstallState.REFRESH_LOCK``
            regardless of lockfile presence or hash state.
        refresh_lock_source: When set, re-resolve exactly the named source chain
            while preserving all other lockfile entries.
        strict_lock: When ``True``, upgrade orphaned lock entries (sources in the
            lockfile but absent from ``.kanon``) to ``OrphanedLockEntryError``
            instead of pruning with an info-line.  Only applies in the consistent state.
        strict_drift: When ``True``, upgrade branch drift (branch tip on remote
            differs from locked SHA) to ``BranchDriftError`` instead of reusing
            the locked SHA with an info-line.  Only applies in the consistent state.

    Raises:
        KanonHashMismatchError: Only when ``strict_lock=True`` and the lockfile's
            kanon_hash differs from the freshly-computed hash for a reason other
            than a pure source removal (an addition or a changed revision spec).
            Default install reconciles instead of raising.
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

    # _consistent_has_orphans: set True when orphans were detected and pruned in the
    # LOCKFILE_CONSISTENT state so Step 7 knows to rewrite the lockfile without the
    # orphaned entries.  The RECONCILE path does NOT use this flag -- it always
    # rebuilds and writes a full lockfile in Step 7.
    _consistent_has_orphans: bool = False

    # reconcile_computed_hash: the freshly-computed kanon_hash for the current
    # .kanon, carried into Step 7 so the rebuilt lockfile records it.  Set only on
    # the RECONCILE path.
    reconcile_computed_hash: str | None = None

    # Step 2: On a hash mismatch, decide between npm-ci (strict) and npm-install
    # (reconcile) semantics.
    #
    # --strict-lock (npm ci): error cleanly on ANY drift and NEVER mutate the lock.
    #   Pure-removal drift -> OrphanedLockEntryError (names each orphan); any other
    #   drift (addition and/or changed spec) -> KanonHashMismatchError.
    #
    # default install (npm install): reconcile .kanon <-> lock.  Set the state to
    #   RECONCILE, KEEP the existing lockfile for replay, and emit one
    #   "pruned orphaned lock entry: <name>" line per orphan.  Nothing is written to
    #   disk here; the per-source loop replays unchanged sources and resolves
    #   added/changed sources fresh, and Step 7 rebuilds + writes the full lockfile
    #   once on success.
    if install_state is InstallState.LOCKFILE_HASH_MISMATCH:
        # Both fields are populated by _classify_install_state in the HASH_MISMATCH
        # branch (assigned above).  cast() communicates non-None to the type checker.
        existing_lockfile_nn = cast(Lockfile, lockfile_hash_mismatch_lockfile)
        computed_hash_nn = cast(str, lockfile_hash_mismatch_computed)

        # Parse .kanon to get the current source set and their revision specs so we
        # can classify the drift (orphans vs additions vs changed specs).
        mismatch_config = parse_kanonenv(kanonenv_path)
        mismatch_source_names: list[str] = mismatch_config["KANON_SOURCES"]
        mismatch_revision_specs: dict[str, str] = {
            name: mismatch_config["sources"][name]["ref"] for name in mismatch_source_names
        }

        if strict_lock:
            # npm ci: pick the precise clean error and raise it WITHOUT writing.
            raise _strict_lock_drift_error(
                existing_lockfile_nn,
                mismatch_source_names,
                computed_hash=computed_hash_nn,
                kanon_revision_specs=mismatch_revision_specs,
            )

        # npm install: reconcile.  Emit one info-line per orphaned lock entry
        # (lockfile sources absent from the current .kanon).  Orphans are excluded
        # naturally by the per-source loop (it iterates .kanon source names only),
        # so this is purely informational; nothing is pruned-and-written here.
        orphaned_on_mismatch = _detect_orphaned_lock_entries(existing_lockfile_nn, mismatch_source_names)
        for orphan_name in orphaned_on_mismatch:
            print(f"{INFO_PRUNED_ORPHAN_LOCK_ENTRY}: {orphan_name}")
        install_state = InstallState.RECONCILE
        existing_lockfile = existing_lockfile_nn
        reconcile_computed_hash = computed_hash_nn

    # kanon install is hermetic (spec Section 4.3 / FR-14).  The v4 lock carries no
    # [catalog] block, so install neither resolves nor records a catalog source: it
    # reads .kanon + .kanon.lock and reconciles sources only.  A populated
    # KANON_CATALOG_SOURCES env var has no effect here (it is ignored, never read),
    # and --catalog-source is not registered on the install parser.
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

    base_dir = resolve_workspace_base_dir(kanonenv_path.parent)
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
    # Both checks run only in the consistent state; reconcile, refresh, and absent
    # paths skip them (reconcile prunes orphans in Step 2 and rebuilds the lock in
    # Step 7, so it does not use _consistent_has_orphans).
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

    # Per-source marketplace attribution (schema v3): maps each current source
    # name to the sorted list of marketplace names it registered this install.
    # Built from the before/after discover() diff inside the per-source loop and
    # attached to each source's SourceEntry.registered_marketplaces.  Empty for
    # every source when marketplace install is disabled.
    attributed_marketplaces: dict[str, list[str]] = {}

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

        # Per-source marketplace attribution (schema v3): snapshot the
        # discoverable marketplace-name set BEFORE this source does anything that
        # could deposit a marketplace (repo sync's native <linkfile> processing,
        # kanon's _process_manifest_linkfiles, and register_direct_checkout_
        # marketplaces).  The AFTER snapshot is taken once this source's
        # marketplace registration completes; the set-difference is exactly the
        # marketplaces THIS source contributed.  prepare_marketplace_dir wiped the
        # directory before the loop, so per-source diffs cleanly isolate each
        # source's contribution.
        before_marketplace_names: set[str] = set()
        if marketplace_install:
            before_marketplace_names = set(discover_registered_marketplace_names(pathlib.Path(marketplace_dir_str)))

        # On the RECONCILE path, decide replay-vs-resolve for this source by
        # comparing its .kanon revision spec to the locked entry's recorded spec.
        # Computed once here so the HTTPS-enforcement URL selection and the
        # resolution branch below agree.
        reconcile_replay = install_state is InstallState.RECONCILE and _should_replay_source(
            name,
            source_data["ref"],
            existing_lockfile,
        )

        # HTTPS enforcement (Section 3.6 trust model).
        # On the lockfile-consistent replay path -- and on the RECONCILE path for a
        # source being replayed -- check the LOCKED URL so a malicious lockfile that
        # records an HTTP remote is rejected before any clone attempt.  On all other
        # paths (fresh resolve, refresh) check the .kanon source URL.
        if install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
            _replay_candidate = next(
                (e for e in existing_lockfile.sources if e.name == name),
                None,
            )
            if _replay_candidate is None:
                # Defensive invariant: in LOCKFILE_CONSISTENT the kanon_hash matched,
                # so every .kanon source must be present in the lockfile.  RECONCILE
                # never reaches this branch (it resolves missing sources fresh).
                raise InstallError(
                    f"BUG: source {name!r} not found in lockfile under LOCKFILE_CONSISTENT state"
                    " -- kanon_hash consistency violation"
                )
            _url_to_check = _replay_candidate.url
        elif reconcile_replay and existing_lockfile is not None:
            _reconcile_pinned = next((e for e in existing_lockfile.sources if e.name == name), None)
            # reconcile_replay is True only when the source is present in the lock.
            _url_to_check = cast(SourceEntry, _reconcile_pinned).url
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
        elif install_state is InstallState.RECONCILE:
            # npm install reconcile: replay unchanged sources (preserve the locked
            # SHA), resolve added/changed sources fresh.  Orphans never reach this
            # branch -- the loop iterates .kanon source names only.
            if reconcile_replay and existing_lockfile is not None:
                # reconcile_replay implies the source is present in the lock with an
                # identical revision spec.  Apply the same reachability validation the
                # CONSISTENT branch does before replaying the locked SHA.
                pinned = cast(SourceEntry, next(e for e in existing_lockfile.sources if e.name == name))
                _check_sha_reachable(
                    url=pinned.url,
                    sha=pinned.resolved_sha,
                    source_name=name,
                )
                resolved_revision = pinned.resolved_sha
                resolved_entries.append(pinned)
            else:
                # New source or changed spec -- re-resolve fresh, mirroring the
                # REFRESH_LOCK_SOURCE re-resolve so the .repo/manifests working tree
                # is reset before repo_init (see the reset block below).
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
                resolved_revision = resolve_version(source_data["url"], source_data["ref"])
                ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
                resolved_entries.append(
                    SourceEntry(
                        alias=name,
                        name=name,
                        url=source_data["url"],
                        ref_spec=source_data["ref"],
                        resolved_ref=ref_resolution.resolved_ref,
                        resolved_sha=ref_resolution.sha,
                        path=source_data["path"],
                    )
                )
        else:
            resolved_revision = resolve_version(source_data["url"], source_data["ref"])
            # Resolve the actual commit SHA and the matched ref for the lockfile entry.
            # ValueError propagates unconditionally (fail-fast; no silent degradation).
            ref_resolution = _resolve_ref_to_sha(source_data["url"], resolved_revision)
            resolved_entries.append(
                SourceEntry(
                    alias=name,
                    name=name,
                    url=source_data["url"],
                    ref_spec=source_data["ref"],
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
        # Re-resolved sources need the working-tree reset: REFRESH_LOCK and
        # REFRESH_LOCK_SOURCE always re-resolve, and RECONCILE re-resolves any
        # added/changed source (a replayed RECONCILE source keeps its manifest
        # commit, so it follows the plain repo_init path like CONSISTENT replay).
        _is_reresolve = install_state in (
            InstallState.REFRESH_LOCK,
            InstallState.REFRESH_LOCK_SOURCE,
        ) or (install_state is InstallState.RECONCILE and not reconcile_replay)
        if _is_reresolve:
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
        #
        if marketplace_install:
            marketplace_dir = pathlib.Path(marketplace_dir_str)
            _process_manifest_linkfiles(manifest_xml_path, source_dir)
            # Also register direct-checkout entries that carry a
            # .claude-plugin/marketplace.json but have NO <linkfile> element
            # (BUG-3: builders-plugins pattern). For each such project, a
            # symlink from CLAUDE_MARKETPLACES_DIR/<name> to the project
            # checkout dir is created so install_marketplace_plugins can find it.
            register_direct_checkout_marketplaces(manifest_xml_path, source_dir, marketplace_dir)
            # AFTER snapshot for per-source attribution (see the BEFORE snapshot
            # at the top of the loop).  The diff is exactly the marketplaces this
            # source deposited via repo sync's linkfiles, kanon's linkfile copy,
            # or a direct-checkout registration.
            after_names = set(discover_registered_marketplace_names(marketplace_dir))
            attributed_marketplaces[name] = sorted(after_names - before_marketplace_names)
            resolved_entries[-1].registered_marketplaces = attributed_marketplaces[name]
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

    # Marketplace ownership reconciliation (per-source, schema v3).
    #
    # NEW = union of every current source's attributed marketplace names (the
    # marketplaces present under CLAUDE_MARKETPLACES_DIR after this install).
    # When marketplace install is disabled, no source is attributed anything, so
    # NEW is empty.
    #
    # OLD = union of every source's recorded ``registered_marketplaces`` in the
    # existing lockfile (empty when there is no prior lock).
    #
    # Auto-prune: any name in OLD that is absent from NEW is an orphan -- a
    # marketplace whose source was reconciled away (or whose registration was
    # toggled off).  Each orphan is unregistered from ~/.claude via
    # ``remove_marketplace`` (idempotent).  The claude binary is located lazily,
    # only when at least one orphan exists, so a no-orphan run never requires
    # claude on PATH.  This diff runs even when marketplace install is DISABLED
    # so toggling KANON_MARKETPLACE_INSTALL off prunes everything kanon
    # previously registered (NEW=[], orphans=OLD).
    new_marketplace_set: set[str] = set()
    for _names in attributed_marketplaces.values():
        new_marketplace_set.update(_names)

    old_marketplace_set: set[str] = set()
    if existing_lockfile is not None:
        for _src in existing_lockfile.sources:
            old_marketplace_set.update(_src.registered_marketplaces)

    orphaned_marketplaces = sorted(old_marketplace_set - new_marketplace_set)
    if orphaned_marketplaces:
        print("\nkanon install: pruning marketplaces no longer referenced by .kanon...")
        claude_bin = locate_claude_binary()
        for name in orphaned_marketplaces:
            print(f"  - unregistering marketplace: {name}")
            remove_marketplace(claude_bin, name)

    # Step 7: Write the lockfile.  Schema v4 (spec Section 5.2 / FR-7) has no
    # [catalog] block, so no write path resolves or records a catalog source.
    # - LOCKFILE_ABSENT: write fresh lockfile.
    # - REFRESH_LOCK: full rebuild; overwrite lockfile.
    # - RECONCILE: full rebuild from the resolved+replayed entries (orphans dropped,
    #   added/changed resolved fresh, unchanged replayed), recording the new
    #   kanon_hash.  Written once, on success only -- nothing was written earlier
    #   on this path.
    # - REFRESH_LOCK_SOURCE: partial rebuild; merge one source into old lockfile.
    # - LOCKFILE_CONSISTENT with orphans pruned: rewrite without orphaned entries.
    # - LOCKFILE_CONSISTENT (no orphans): lockfile is authoritative; do NOT rewrite.
    if install_state in (InstallState.LOCKFILE_ABSENT, InstallState.REFRESH_LOCK):
        # In the LOCKFILE_ABSENT state, computed_hash is always None because
        # _classify_install_state does not call kanon_hash when there is no
        # lockfile to compare against. Compute it now.
        computed_hash = _kanon_hash(kanonenv_path)

        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=f"kanon-cli/{__version__}",
            kanon_hash=computed_hash,
            sources=resolved_entries,
            marketplace_registered=marketplace_install,
            marketplace_dir=marketplace_dir_str if marketplace_install else "",
        )
        write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.RECONCILE:
        # Full rebuild from the reconciled source set.  The new kanon_hash is the
        # value computed during Step 2 classification.
        reconcile_hash_nn = cast(str, reconcile_computed_hash)
        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=f"kanon-cli/{__version__}",
            kanon_hash=reconcile_hash_nn,
            sources=resolved_entries,
            marketplace_registered=marketplace_install,
            marketplace_dir=marketplace_dir_str if marketplace_install else "",
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
                attributed_marketplaces=attributed_marketplaces,
            )
            write_lockfile(merged_lf, lockfile_path)
        else:
            # No existing lockfile -- write a full lockfile as if LOCKFILE_ABSENT.
            lf = Lockfile(
                schema_version=CURRENT_SCHEMA_VERSION,
                generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                generator=f"kanon-cli/{__version__}",
                kanon_hash=new_kanon_hash,
                sources=resolved_entries,
                marketplace_registered=marketplace_install,
                marketplace_dir=marketplace_dir_str if marketplace_install else "",
            )
            write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.LOCKFILE_CONSISTENT and _consistent_has_orphans:
        # Orphans were pruned from the consistent-state run.  Rewrite the lockfile
        # without the orphaned entries so subsequent installs do not re-detect them.
        # The kanon_hash and all non-orphan source entries are preserved verbatim
        # from the existing lockfile (it is still consistent).
        pruned_lf_nn = cast(Lockfile, existing_lockfile)
        active_names = set(source_names)
        # These entry objects were appended to resolved_entries as ``pinned`` and
        # mutated in the per-source loop with fresh per-source attribution, so
        # their ``registered_marketplaces`` is already authoritative.
        pruned_sources = [e for e in pruned_lf_nn.sources if e.name in active_names]
        pruned_lockfile = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=pruned_lf_nn.generator,
            kanon_hash=pruned_lf_nn.kanon_hash,
            sources=pruned_sources,
            marketplace_registered=marketplace_install,
            marketplace_dir=marketplace_dir_str if marketplace_install else "",
        )
        write_lockfile(pruned_lockfile, lockfile_path)

    print("\nkanon install: done.")


def install(
    kanonenv_path: pathlib.Path,
    lock_file_path: pathlib.Path,
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
      3. Parse .kanon and validate sources.  install is hermetic and resolves
         solely from the committed .kanon (+ .kanon.lock); a populated
         KANON_CATALOG_SOURCES env var is ignored and --catalog-source is not
         registered on the install parser.
      3a. In LOCKFILE_CONSISTENT state: detect orphans and branch drift.
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
      11. Write .kanon.lock: full write for LOCKFILE_ABSENT/REFRESH_LOCK/RECONCILE;
          partial merge for REFRESH_LOCK_SOURCE; pruned rewrite for
          LOCKFILE_CONSISTENT with orphans; unchanged for LOCKFILE_CONSISTENT
          without orphans.  On the RECONCILE path the lockfile is written once at
          the end on success only (nothing is persisted earlier).

    Args:
        kanonenv_path: Path to the .kanon configuration file.
        lock_file_path: Pre-resolved path to the .kanon.lock file. The caller
            is responsible for resolution via ``derive_lock_file_path``; this
            function does not apply any fallback or derivation.
        refresh_lock: When ``True``, ignore the existing lockfile entirely and
            rebuild it from scratch.  Default ``False`` preserves prior behaviour.
        refresh_lock_source: When set to a source name or catalog entry name,
            re-resolve exactly that source's chain while preserving every other
            lockfile entry verbatim.  Mutually exclusive with ``refresh_lock``
            (enforced at the CLI level by argparse).  Default ``None`` preserves
            prior behaviour.
        strict_lock: When ``True``, upgrade orphaned lock entries to
            ``OrphanedLockEntryError`` instead of pruning with an info-line.  Only
            applies in the ``LOCKFILE_CONSISTENT`` state.  Default ``False``
            preserves prior behaviour (prune + info-line).
        strict_drift: When ``True``, upgrade branch drift to
            ``BranchDriftError`` instead of reusing the locked SHA with an info-line.
            Only applies in the ``LOCKFILE_CONSISTENT`` state.  Default
            ``False`` preserves prior behaviour (reuse + info-line).

    Raises:
        KanonHashMismatchError: Only when ``strict_lock=True`` and the lockfile's
            kanon_hash differs from the freshly-computed hash for a reason other
            than a pure source removal (an addition or a changed revision spec).
            Default install reconciles instead of raising.
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
    base_dir = resolve_workspace_base_dir(kanonenv_path.parent)

    with kanon_workspace_lock(base_dir):
        _run_install(
            kanonenv_path,
            lock_file_path,
            refresh_lock=refresh_lock,
            refresh_lock_source=refresh_lock_source,
            strict_lock=strict_lock,
            strict_drift=strict_drift,
        )
