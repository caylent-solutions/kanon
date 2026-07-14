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
  LOCKFILE_CONSISTENT    -- .kanon.lock present and kanon_hash matches; replay SHAs
                            and replay the locked content pins (v5).
  LOCKFILE_HASH_MISMATCH -- .kanon.lock present but kanon_hash differs.  Default
                            install FAILS FAST (the FR-24 .kanon <-> .kanon.lock
                            consistency check runs before resolving and the lock is
                            never mutated; npm ci).  --reconcile opts back in to the
                            lenient RECONCILE; --refresh-lock rebuilds the whole lock.
  RECONCILE              -- --reconcile opt-in: prune orphans, resolve added/changed
                            sources fresh, replay unchanged sources, rebuild + write
                            the lock once at the end on success only.
  LOCKFILE_UNREACHABLE   -- lockfile SHA no longer reachable on remote; hard error.
  REFRESH_LOCK_SOURCE    -- operator requested partial lockfile rebuild via --refresh-lock-source.

``kanon install`` is hermetic (spec Section 4.3 / FR-14): the schema-v5 lock carries
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
  PackagePathConflictError    -- two+ sources resolve the same package path to different content SHAs.
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
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import NamedTuple, cast

from packaging.specifiers import SpecifierSet, InvalidSpecifier

import kanon_cli.repo as _repo
from kanon_cli.repo.git_command import GitCommandError
from kanon_cli import __version__
from kanon_cli.constants import (
    KANON_ALLOW_INSECURE_REMOTES,
    KANON_GIT_LS_REMOTE_TIMEOUT,
    KANON_HOME_ENV_VAR,
    KANON_HOME_STORE_ENTRIES_SUBDIR,
    KANON_HOME_STORE_GITIGNORE_ENTRY,
    KANON_HOME_STORE_LOCKS_SUBDIR,
    KANON_HOME_STORE_SUBDIR,
    KANON_HOME_STORE_TMP_SUBDIR,
    SOURCE_ENV_KEY,
    SOURCE_MARKETPLACE_KEY,
    SOURCE_PREFIX,
    resolve_kanon_home,
)
from kanon_cli.core.git_runner import run_git_ls_remote
from kanon_cli.core.kanon_hash import kanon_hash as _kanon_hash
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    ContentPinEntry,
    IncludeEntry,
    Lockfile,
    LockfileConsistencyError,
    ProjectEntry,
    SourceEntry,
    check_lockfile_consistency,
    read_lockfile,
    write_lockfile,
)
from kanon_cli.core.manifest import join_project_repo_url, walk_includes_collecting_remotes
from kanon_cli.core.include_walker import (
    IncludeCycleError,
    IncludeTree,
    InstallError,
    MalformedIncludeError,
    _canonicalize_include_path,
    _walk_includes,
)
from kanon_cli.core.manifest_vars import functional_vars_in_manifest_files
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


__all__ = [
    "IncludeCycleError",
    "IncludeTree",
    "InstallError",
    "MalformedIncludeError",
    "_canonicalize_include_path",
    "_walk_includes",
    "compute_store_entry_address",
    "kanon_home_inside_git_repo",
    "prune_store",
    "publish_store_entry",
    "resolve_kanon_lock_root",
    "resolve_workspace_base_dir",
    "store_entries_dir",
    "write_store_gitignore_if_in_git_repo",
]


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


_ORPHAN_HEADER_SINGULAR = "ERROR: {count} orphaned lockfile entry: {names}"


_ORPHAN_HEADER_PLURAL = "ERROR: {count} orphaned lockfile entries: {names}"


_ORPHAN_CONTEXT = "These lockfile entries have no matching KANON_SOURCE_*_URL triple in .kanon."


_ORPHAN_REMEDIATION = (
    "Remediation:\n"
    "  Run `kanon install --reconcile` to prune the orphan(s), or\n"
    "  restore the missing KANON_SOURCE_<name>_* triples in .kanon, or\n"
    "  run `kanon remove <name>` for each orphan to clean the lockfile."
)


INFO_PRUNED_ORPHAN_LOCK_ENTRY = "pruned orphaned lock entry"


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


class PackagePin(NamedTuple):
    """A resolved package destination: which source put which content where.

    A ``<project>`` checks out to a ``.packages/<name>`` slot.  Two projects
    that resolve to the SAME slot with different content are a destination
    collision; the same repository resolved to DIFFERENT slots is not
    (independent packages from a mono-repo).  Source manifests themselves are
    never package pins -- they are cloned into ``sources/<alias>/`` and occupy
    no ``.packages/`` slot.

    Fields:
        source_alias: The alias of the source whose manifest declares the
            project (for diagnostics; names the ``.kanon`` source to adjust).
        name: The manifest ``<project name>``.
        path: The project destination path (``<project path>``, e.g.
            ``.packages/foo``) -- the slot the project occupies.
        resolved_sha: The resolved content commit SHA at that path.
    """

    source_alias: str
    name: str
    path: str
    resolved_sha: str


class PackagePathConflictReport(NamedTuple):
    """A single package-destination conflict: one ``.packages/<path>`` slot
    resolved to two or more different content SHAs across sources.

    Fields:
        path: The shared project destination path (``<project path>``) that two
            or more sources resolve to different content.
        entries: The ``PackagePin`` rows claiming this path.  The caller ensures
            at least two distinct SHAs are present before constructing a report.
    """

    path: str
    entries: list[PackagePin]


class PackagePathConflictError(InstallError):
    """Raised when two or more sources resolve the same package destination path
    to different content SHAs.

    The destination invariant: no two installed ``<project>`` entries may occupy
    the same ``.packages/<path>`` slot with different content.  The SAME
    repository may be installed at DIFFERENT commits for DIFFERENT paths
    (independent packages from a mono-repo catalog) -- that is allowed; only a
    true same-path / different-content clash is a hard error.  The operator must
    remove one source or align the project revisions so the shared path resolves
    to a single content SHA.

    Canonical error text: ``tests/fixtures/errors/conflict-detected.txt``.

    Args:
        reports: One or more ``PackagePathConflictReport`` instances, one per
            conflicting destination path.
    """

    def __init__(self, reports: list[PackagePathConflictReport]) -> None:
        self.reports = reports
        super().__init__(str(self))

    def __str__(self) -> str:
        lines: list[str] = [
            "ERROR: Package destination conflict -- two or more sources resolve the same package path to different content.",
        ]
        for report in self.reports:
            lines.append(f"  Conflict for package path: {report.path}")
            for entry in report.entries:
                lines.append(f"  {entry.source_alias} ({entry.name}): {entry.path} @ {entry.resolved_sha}")
            lines.append(
                "  Remediation: remove one source or align the project revisions so "
                f"'{report.path}' resolves to a single content SHA."
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


class UnresolvedManifestVarError(InstallError):
    """Raised when a synced manifest still references an unprovided ``${VAR}``.

    The repo-tool ``envsubst`` only warns (and exits 0) when a ``${VAR}``
    placeholder cannot be resolved from the environment, leaving it verbatim in
    the manifest XML. Proceeding to ``repo sync`` with an unresolved fetch URL
    would surface as an opaque git-remote error, so kanon performs its own
    post-envsubst scan of the resolved manifest (and its ``<include>`` chain)
    and fails fast with an actionable diagnostic naming the exact ``.kanon`` key
    to set.

    A source declares an env var only when its manifest references the matching
    ``${VAR}``; ``kanon add`` writes the per-dependency key (auto-derived for
    ``GITBASE``, empty placeholder otherwise) so the operator only needs to fill
    in a value.

    Args:
        source_name: The source alias whose manifest carries the unresolved
            var(s).
        var_names: The sorted list of unresolved ``${VAR}`` names found in the
            source's resolved manifest after envsubst.
    """

    def __init__(self, source_name: str, var_names: list[str]) -> None:
        self.source_name = source_name
        self.var_names = var_names
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = []
        for var in self.var_names:
            lines.append(
                f"ERROR: source '{self.source_name}' manifest needs ${{{var}}} but no value was provided; "
                f"set {SOURCE_PREFIX}{self.source_name}_{var} in .kanon"
            )
        return "\n".join(lines)


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

    if not (manifests_dir / ".git").exists():
        return

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

    for bak_file in manifests_dir.rglob("*.bak"):
        bak_file.unlink()


def _detect_package_path_conflicts(
    all_pins: list[PackagePin],
) -> list[PackagePathConflictReport]:
    """Detect package-destination conflicts across resolved sources.

    Groups package pins by their destination ``path`` (the ``.packages/<name>``
    slot a ``<project>`` checks out to).  A conflict exists when one path is
    claimed with two or more differing ``resolved_sha`` values -- two sources
    would write different content to the same slot.  The same repository
    resolved at different commits to DIFFERENT paths is NOT a conflict
    (independent packages from a mono-repo), and the same path at the same SHA
    is a benign diamond (allowed).  ``aggregate_symlinks`` is the on-disk
    backstop that rejects any duplicate ``.packages/`` slot at link time; this
    pre-flight is the content-aware check that fails early with a clear message.

    Args:
        all_pins: Every resolved package pin to inspect, across all sources.

    Returns:
        A list of ``PackagePathConflictReport`` instances -- one per destination
        path claimed with more than one SHA, sorted by path with each report's
        entries sorted by ``(source_alias, resolved_sha)`` for deterministic
        output.  Returns ``[]`` when no conflicts exist; never returns ``None``.
    """

    groups: dict[str, list[PackagePin]] = {}
    for pin in all_pins:
        groups.setdefault(pin.path, []).append(pin)

    reports: list[PackagePathConflictReport] = []
    for path in sorted(groups):
        entries = groups[path]
        shas = {e.resolved_sha for e in entries}
        if len(shas) > 1:
            ordered = sorted(entries, key=lambda e: (e.source_alias, e.resolved_sha))
            reports.append(PackagePathConflictReport(path=path, entries=ordered))
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


def _gather_package_pins(resolved_entries: list[SourceEntry]) -> list[PackagePin]:
    """Flatten every source's content pins into ``PackagePin`` rows.

    Each source's checked-out ``<project>`` contributes one pin carrying the
    source alias (for diagnostics), the project name, its destination path
    (``<project path>`` -- the ``.packages/<name>`` slot it occupies), and the
    resolved content SHA.  Source manifests themselves are deliberately NOT
    included: a source's manifest repo is cloned into ``sources/<alias>/`` and
    never occupies a ``.packages/`` slot, so two sources sharing a repo at
    different commits is not a destination conflict.  Shared ``<include>``
    files likewise produce no package pin.

    Args:
        resolved_entries: Resolved top-level source entries (from the current
            install run or a lockfile replay), each carrying its ``content_pins``.

    Returns:
        A flat list of ``PackagePin`` instances across all sources.
    """
    pins: list[PackagePin] = []
    for entry in resolved_entries:
        for pin in entry.content_pins:
            pins.append(
                PackagePin(
                    source_alias=entry.alias,
                    name=pin.name,
                    path=pin.path,
                    resolved_sha=pin.resolved_sha,
                )
            )
    return pins


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

    for entry in lockfile.sources:
        if entry.name == name:
            return entry

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

            if matched_ref == ref or matched_ref.endswith(f"/{ref}"):
                return _RefResolution(sha=matched_sha, resolved_ref=matched_ref)
    raise ValueError(
        f"ERROR: ref {ref!r} not found in remote {url!r}.\n"
        f"  Remediation: verify the ref exists on the remote with "
        f"'git ls-remote {url} {ref}'."
    )


def resolve_workspace_base_dir() -> pathlib.Path:
    """Resolve the base directory for .packages/ and .kanon-data/ artifacts.

    The base directory is the artifact store under the shared ``KANON_HOME``
    root (spec Section 7.1 / Section 8 / FR-15): ``<KANON_HOME>/store``, where
    ``KANON_HOME`` resolves with precedence ``KANON_HOME`` env > default
    ``~/.kanon-home`` (the default is derived from the real user home directory, never
    a hard-coded absolute path). All fetched data is content-addressed under this
    shared store and deduped across projects, replacing the removed per-project
    ``.packages/`` / ``.kanon-data/`` location and the two location env vars it
    subsumed.

    The resolved store directory is created if it does not yet exist.  If
    creation fails or the resulting directory is not writable, the function
    calls ``sys.exit(1)`` with an actionable error message naming the path and
    the ``KANON_HOME`` environment variable.  There is no silent relocation; the
    contract is strict fail-fast.

    This function is the single resolution point shared by both ``install`` and
    ``clean`` so that the two commands agree on where artifacts are placed and
    removed.  ``clean.py`` imports this function from ``install.py``.

    Returns:
        The absolute ``pathlib.Path`` to use as the artifact store base
        directory.

    Raises:
        SystemExit: With exit code 1 when the resolved ``KANON_HOME`` store is
            uncreatable or not writable.
    """
    store_path = (pathlib.Path(resolve_kanon_home()) / KANON_HOME_STORE_SUBDIR).resolve()
    try:
        store_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"ERROR: Cannot create {KANON_HOME_ENV_VAR} store directory {store_path}: {exc.strerror}.\n"
            f"  Set {KANON_HOME_ENV_VAR} to a path that can be created, or fix permissions on the parent.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.access(store_path, os.W_OK):
        print(
            f"ERROR: {KANON_HOME_ENV_VAR} store directory {store_path} is not writable.\n"
            f"  Fix permissions or set {KANON_HOME_ENV_VAR} to a writable path.",
            file=sys.stderr,
        )
        sys.exit(1)

    return store_path


def resolve_kanon_lock_root(kanon_file: pathlib.Path) -> pathlib.Path:
    """Return the store-side lock root for serialising edits to one .kanon file.

    Keyed by a stable hash of the RESOLVED .kanon path so concurrent edits to the
    same file serialise, while the CWD stays free of a .kanon-data lock dir (spec
    G8: the CWD holds only .kanon + .kanon.lock). The lock lives under the shared
    KANON_HOME store, so it follows KANON_HOME and only lands in the CWD when the
    operator deliberately points KANON_HOME there.
    """
    store_base = resolve_workspace_base_dir()
    address = hashlib.sha256(str(kanon_file.resolve()).encode("utf-8")).hexdigest()
    return store_base / KANON_HOME_STORE_LOCKS_SUBDIR / address


def store_entries_dir(store_base: pathlib.Path) -> pathlib.Path:
    """Return the directory under ``store_base`` that holds content-addressed entries.

    The entries directory is ``<store_base>/<KANON_HOME_STORE_ENTRIES_SUBDIR>``.
    Each immutable store entry is published into a content-addressed
    subdirectory of this path. The directory is the single prune surface for
    ``kanon clean`` (spec Section 3.5).

    Args:
        store_base: The resolved store base directory (``<KANON_HOME>/store``).

    Returns:
        The absolute path to the store-entries directory. The directory is not
        created here; ``publish_store_entry`` creates it on demand.
    """
    return store_base / KANON_HOME_STORE_ENTRIES_SUBDIR


def compute_store_entry_address(url: str, resolved_sha: str) -> str:
    """Compute the content address for an immutable store entry.

    The address is the lowercase hex SHA-256 digest of the canonicalized
    repository URL joined to the resolved commit SHA. Two project directories
    that install the same ``manifest@SHA`` from the same canonical remote
    therefore compute an identical address and dedup to a single store entry
    (spec Section 3.5 / FR-16). The address is a single path component (no
    directory separators) so it is safe to use as a store subdirectory name.

    Args:
        url: The source repository URL as declared in ``.kanon`` (any scheme;
            canonicalized before hashing so SSH/HTTPS/SCP variants of the same
            remote collapse to one address).
        resolved_sha: The resolved commit SHA the entry materializes
            (40 or 64 lowercase hex characters).

    Returns:
        A 64-character lowercase hex string -- the content address.

    Raises:
        ValueError: If ``url`` or ``resolved_sha`` is empty; a content address
            for an unidentified entry is a logic error and must fail fast.
    """
    if not url:
        raise ValueError("compute_store_entry_address: url must be a non-empty string")
    if not resolved_sha:
        raise ValueError("compute_store_entry_address: resolved_sha must be a non-empty string")
    canonical = canonicalize_repo_url(url)
    digest = hashlib.sha256(f"{canonical}@{resolved_sha}".encode("utf-8"))
    return digest.hexdigest()


def kanon_home_inside_git_repo(store_base: pathlib.Path) -> bool:
    """Return ``True`` when the resolved ``KANON_HOME`` store sits inside a git repo.

    Walks ``store_base`` and each of its ancestors looking for a ``.git`` entry
    (a directory for a normal clone, or a file for a worktree / submodule). The
    walk terminates at the filesystem root. The check is a pure filesystem
    inspection: it never shells out to git and never raises on a missing path.

    A positive result means a ``.gitignore`` safety net must be written into the
    store so the fetched-artifact cache is never accidentally committed
    (spec Section 3.5 conditional ``.gitignore``).

    Args:
        store_base: The resolved store base directory (``<KANON_HOME>/store``).

    Returns:
        ``True`` if ``store_base`` or any ancestor contains a ``.git`` entry;
        ``False`` otherwise.
    """
    current = store_base.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
    return False


def write_store_gitignore_if_in_git_repo(store_base: pathlib.Path) -> bool:
    """Ensure a ``.gitignore`` safety net in the store, only when inside a git repo.

    When ``store_base`` (or an ancestor) is a git working tree, the whole-store
    ignore entry (``KANON_HOME_STORE_GITIGNORE_ENTRY``) is ensured present in
    ``store_base/.gitignore`` so the fetched-artifact cache is never committed.
    When the store is NOT inside a git repo, nothing is added (the safety net is
    conditional, spec Section 3.5).

    The write is idempotent and additive: the entry is appended only when absent,
    reusing ``update_gitignore`` so any pre-existing entries in the file are
    preserved. ``store_base`` is created if absent so the safety net can always be
    ensured when required.

    Args:
        store_base: The resolved store base directory (``<KANON_HOME>/store``).

    Returns:
        ``True`` if the safety-net entry was ensured because the store is inside a
        git repo; ``False`` if the store is not inside a git repo and nothing was
        added.

    Raises:
        OSError: If the ``.gitignore`` file cannot be written (e.g. permission
            denied). The error is not swallowed; the caller sees the failure.
    """
    if not kanon_home_inside_git_repo(store_base):
        return False
    store_base.mkdir(parents=True, exist_ok=True)
    update_gitignore(store_base, entries=[KANON_HOME_STORE_GITIGNORE_ENTRY])
    return True


def publish_store_entry(
    store_base: pathlib.Path,
    address: str,
    materialize: Callable[[pathlib.Path], None],
) -> pathlib.Path:
    """Publish an immutable content-addressed entry into the store atomically.

    Concurrency-safe publish (spec Section 3.5 / FR-16):

    1. Readiness via final-path existence -- if the final content-addressed path
       already exists, the entry is already published (a dedup hit) and the path
       is returned immediately. There is NO poll-sleep; existence is the readiness
       signal.
    2. Otherwise a per-entry lock is acquired through the E2 cross-platform lock
       interface (``kanon_workspace_lock``) on a per-address lock root, with the
       configurable fail-fast acquisition timeout
       (``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS``) and stale-lock recovery
       diagnostics (pid / host / timestamp) the interface already carries
       (spec Section 7.3). Distinct addresses use distinct lock roots, so
       publishes of different entries never serialise against one another.
    3. Inside the lock the existence check is repeated -- a racing publisher may
       have completed between step 1 and lock acquisition; if so the freshly
       published path is returned without re-materializing.
    4. The content is materialized into a private temp directory inside the store
       (same filesystem as the final path) via the caller-supplied ``materialize``
       callback, then moved into the final content-addressed path with
       ``Path.replace`` (an atomic rename). A partially-materialized temp dir is
       removed on any failure so a crash never leaves a half-written final entry.

    Args:
        store_base: The resolved store base directory (``<KANON_HOME>/store``).
        address: The content address (a single path component) produced by
            ``compute_store_entry_address``.
        materialize: A callback that populates the passed temp directory with the
            entry's content. It must not assume any particular starting state
            beyond the directory existing and being empty.

    Returns:
        The absolute path to the published content-addressed entry directory.

    Raises:
        ValueError: If ``address`` is empty or contains a path separator (a
            non-single-component address is a logic error and must fail fast).
        WorkspaceLockTimeoutError: If the per-entry lock cannot be acquired within
            ``KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS`` (carries pid/host/timestamp).
        OSError: If a store directory cannot be created or the rename fails.
    """
    if not address or os.sep in address or (os.altsep and os.altsep in address) or "/" in address:
        raise ValueError(f"publish_store_entry: address must be a single path component; got {address!r}")

    entries_dir = store_entries_dir(store_base)
    final_path = entries_dir / address

    if final_path.exists():
        return final_path

    entries_dir.mkdir(parents=True, exist_ok=True)
    lock_root = store_base / KANON_HOME_STORE_LOCKS_SUBDIR / address
    lock_root.mkdir(parents=True, exist_ok=True)

    with kanon_workspace_lock(lock_root):
        if final_path.exists():
            return final_path

        tmp_root = store_base / KANON_HOME_STORE_TMP_SUBDIR
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_dir = tmp_root / address
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)
        try:
            materialize(tmp_dir)
            tmp_dir.replace(final_path)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    return final_path


def prune_store(store_base: pathlib.Path) -> None:
    """Remove every published content-addressed entry from the store.

    Removes the store-entries directory (``store_entries_dir``) and the private
    publish-scratch directories (the per-address lock roots and the temp dir).
    The store base directory itself is preserved so a subsequent install can
    repopulate it without re-resolving ``KANON_HOME``. This is the prune surface
    invoked by ``kanon clean`` (spec Section 3.5 / FR-16).

    The removals tolerate an already-absent directory (a clean before any
    install is a no-op), but any other OS error during removal is NOT swallowed:
    a store that cannot be pruned must surface to the operator.

    Args:
        store_base: The resolved store base directory (``<KANON_HOME>/store``).
    """
    for subdir in (
        store_entries_dir(store_base),
        store_base / KANON_HOME_STORE_LOCKS_SUBDIR,
        store_base / KANON_HOME_STORE_TMP_SUBDIR,
    ):
        if subdir.exists():
            shutil.rmtree(subdir)


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


def _ensure_color_default_for_interactive_repo() -> None:
    """Default the global git ``color.ui`` to ``auto`` in an interactive shell.

    The vendored repo tool's ``repo init`` shows an interactive
    "Enable color display in this user account (y/N)?" prompt the first time it
    runs in a TTY with no ``color.ui`` configured. Pre-setting ``color.ui=auto``
    makes ``repo init`` skip that prompt and default to colorized output, so
    ``kanon install`` is non-interactive in every shell (interactive shells get
    color, piped/non-TTY runs get none, which is what ``auto`` already means).

    Gated on a TTY -- the only context where the prompt fires -- so
    non-interactive runs and the test suite never write the global git config.
    Idempotent and best-effort: it only sets ``color.ui`` when unset and never
    fails the install if git config cannot be written (the prompt is a UX nicety,
    not a correctness requirement).
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    existing = subprocess.run(
        ["git", "config", "--global", "--get", "color.ui"],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode == 0 and existing.stdout.strip():
        return
    subprocess.run(["git", "config", "--global", "color.ui", "auto"], check=False)


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
    _ensure_color_default_for_interactive_repo()
    _repo.repo_init(str(source_dir), url, revision, manifest_path, repo_rev)


def build_source_envsubst_vars(
    base_env_vars: dict[str, str],
    source_env: dict[str, str],
) -> dict[str, str]:
    """Build the envsubst environment for one source's manifest substitution.

    Each source declares its own open, optional per-dependency env-var map
    (spec Section 5.1 / FR-5): ``kanon add`` records a
    ``KANON_SOURCE_<alias>_<VAR>`` line for every ``${VAR}`` the entry's
    manifest references (``GITBASE`` is the common case, auto-derived from the
    source URL; any other var name is written empty as a placeholder). The
    repo-tool ``envsubst`` resolves ``${VAR}`` from the process environment, so
    install promotes each source's per-dependency env vars into that source's
    substitution environment.

    Per-source env vars take precedence over any same-named value carried in
    ``base_env_vars`` (e.g. a hand-written global ``GITBASE`` line) because they
    are the source-targeted values. The merge is per-source and isolated: only
    the vars this source declares are injected, with no global set leaking
    across sources.

    Args:
        base_env_vars: Shared envsubst variables (``CLAUDE_MARKETPLACES_DIR`` and
            an optional global ``GITBASE``). Not mutated.
        source_env: The source's open per-dependency env-var map
            (``source_data["env"]``); each key is a bare ``${VAR}`` name and the
            value is the substitution value (possibly empty).

    Returns:
        A new dict combining the base variables with this source's per-dependency
        env vars overlaid on top.
    """
    source_env_vars = dict(base_env_vars)
    source_env_vars.update(source_env)
    return source_env_vars


def run_repo_envsubst(
    source_dir: pathlib.Path,
    env_vars: dict[str, str],
) -> None:
    """Run ``repo envsubst`` in source directory with exported env vars.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/``.
        env_vars: Environment variables to export (the source's per-dependency
            env vars, e.g. ``GITBASE``, plus ``CLAUDE_MARKETPLACES_DIR``).

    Raises:
        RepoCommandError: If repo envsubst exits non-zero.
    """
    _repo.repo_envsubst(str(source_dir), env_vars)


def _collect_manifest_tree_paths(
    include_tree: IncludeTree,
    manifest_repo_root: pathlib.Path,
) -> list[pathlib.Path]:
    """Flatten an ``IncludeTree`` into absolute manifest file paths.

    The root node and every transitively-included node carry a repo-relative
    ``path``; this resolves each against ``manifest_repo_root`` and returns the
    deduplicated absolute paths in DFS pre-order.

    Args:
        include_tree: The resolved include tree for the source's root manifest.
        manifest_repo_root: Absolute path to the synced ``.repo/manifests`` dir.

    Returns:
        The deduplicated list of absolute manifest file paths in the tree.
    """
    ordered: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()

    def _visit(node: IncludeTree) -> None:
        abs_path = manifest_repo_root / node.path
        if abs_path not in seen:
            seen.add(abs_path)
            ordered.append(abs_path)
        for child in node.includes:
            _visit(child)

    _visit(include_tree)
    return ordered


def _iter_manifest_projects(
    manifest_paths: list[pathlib.Path],
) -> list[tuple[str, str]]:
    """Yield the ``(project_name, project_path)`` pairs across a manifest tree.

    Parses every resolved manifest XML in *manifest_paths* and collects each
    ``<project name=... path=...>`` element.  A project with no ``path`` falls
    back to its ``name`` (the repo-tool convention).  Duplicate ``(name, path)``
    pairs across the include chain are de-duplicated, preserving first-seen
    order, so a diamond-included manifest contributes each project once.

    Args:
        manifest_paths: Absolute paths to the source's resolved manifest files
            (the root manifest plus its ``<include>`` chain).

    Returns:
        The de-duplicated list of ``(project_name, project_path)`` pairs.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for manifest_path in manifest_paths:
        if not manifest_path.is_file():
            continue
        try:
            tree = ET.parse(str(manifest_path))
        except ET.ParseError:
            continue
        root = tree.getroot()
        for project_el in root.findall("project"):
            name = project_el.get("name", "")
            if not name:
                continue
            path = project_el.get("path", "") or name
            key = (name, path)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
    return pairs


def capture_content_pins(
    source_dir: pathlib.Path,
    manifest_paths: list[pathlib.Path],
) -> list[ContentPinEntry]:
    """Capture each synced project's resolved content commit SHA (spec v5).

    After ``repo sync`` checks out every ``<project>`` under *source_dir*, this
    records the resolved content SHA of each project by running
    ``git rev-parse HEAD`` in the project's checkout directory
    (``source_dir/<project path>``).  The captured pins are recorded in
    ``.kanon.lock`` and replayed byte-for-byte on a subsequent install
    (npm-style content-SHA locking; spec Section 5.2 / FR-22).

    A project whose checkout directory does not exist or is not a git working
    tree (e.g. a mocked ``repo sync`` in a unit/integration test that never
    materialises real checkouts) is skipped: it contributes no pin rather than
    failing.  Replay only rewrites the revision of a project that has a captured
    pin, so a source with no capturable checkouts simply behaves as it did
    before content pinning.

    Args:
        source_dir: Path to ``.kanon-data/sources/<name>/`` (the ``repo init``
            workspace; project paths are resolved relative to this).
        manifest_paths: Absolute paths to the source's resolved manifest files
            (the root manifest plus its ``<include>`` chain).

    Returns:
        A list of ``ContentPinEntry`` rows, one per project whose checkout SHA
        could be resolved, sorted by ``(name, path)`` for deterministic output.
    """
    pins: list[ContentPinEntry] = []
    for project_name, project_path in _iter_manifest_projects(manifest_paths):
        checkout_dir = source_dir / project_path
        if not (checkout_dir / ".git").exists():
            continue
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(checkout_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        sha = result.stdout.strip()
        if not sha:
            continue
        pins.append(ContentPinEntry(name=project_name, path=project_path, resolved_sha=sha))
    return sorted(pins, key=lambda p: (p.name, p.path))


def build_project_entries(
    manifest_xml_path: pathlib.Path,
    manifest_repo_root: pathlib.Path,
    manifest_paths: list[pathlib.Path],
    content_pins: list[ContentPinEntry],
) -> list[ProjectEntry]:
    """Resolve every synced repo package to a fully-provenanced ``ProjectEntry``.

    Populates the previously-empty ``SourceEntry.projects`` layer of the lockfile
    so the complete resolved graph -- every transitive repo package with its
    name, source URL, canonical URL, and resolved content SHA -- is recorded
    first-class. This also fixes ``kanon why`` showing an empty project layer on
    install-written lockfiles.

    URLs are resolved from the already-synced local manifests (no extra network)
    with the same helpers the live ``why`` resolver uses:
    ``walk_includes_collecting_remotes`` builds the ``<remote name> -> fetch``
    map, ``join_project_repo_url`` joins the remote base to the ``<project name>``
    repo path, and ``canonicalize_repo_url`` canonicalizes the result. The
    resolved content SHA of each project is taken from the ``content_pins`` the
    caller captured after ``repo sync`` (keyed by project name), so a project only
    yields a ``ProjectEntry`` when its checkout SHA was captured. Projects whose
    ``remote`` cannot be resolved to a concrete fetch URL, or whose joined URL is
    not canonicalizable, are skipped -- matching the live ``why`` resolver, which
    also skips unresolvable remotes (a separate audit concern).

    The per-project ``ref_spec`` is recorded as the wildcard ``*`` (a transitively
    pulled project carries no ``.kanon`` version constraint of its own); the
    manifest-declared ``revision`` (or the resolved SHA when no revision is
    declared) is recorded as ``resolved_ref`` for provenance.

    Args:
        manifest_xml_path: Absolute path to the source's root manifest XML.
        manifest_repo_root: Absolute path to the synced ``.repo/manifests`` dir;
            ``<include>`` paths and the ``<remote>`` map resolve against it.
        manifest_paths: Absolute paths to the source's resolved manifest files
            (the root manifest plus its ``<include>`` chain).
        content_pins: The ``ContentPinEntry`` rows captured after ``repo sync``;
            supplies each project's resolved content SHA.

    Returns:
        A list of ``ProjectEntry`` rows -- one per resolvable synced project --
        sorted by project name for deterministic, byte-stable lockfile output.
    """
    sha_by_name = {pin.name: pin.resolved_sha for pin in content_pins}
    if not sha_by_name:
        return []

    try:
        remote_map = walk_includes_collecting_remotes(manifest_xml_path, manifest_repo_root)
    except (ET.ParseError, FileNotFoundError, OSError):
        remote_map = {}

    entries: list[ProjectEntry] = []
    seen: set[str] = set()
    for manifest_path in manifest_paths:
        if not manifest_path.is_file():
            continue
        try:
            tree = ET.parse(str(manifest_path))
        except ET.ParseError:
            continue
        root = tree.getroot()
        default_el = root.find("default")
        default_remote = default_el.get("remote") if default_el is not None else None
        default_revision = default_el.get("revision") if default_el is not None else None

        for project_el in root.findall("project"):
            name = project_el.get("name", "")
            if not name or name in seen:
                continue
            resolved_sha = sha_by_name.get(name)
            if resolved_sha is None:
                continue
            remote_name = project_el.get("remote") or default_remote
            if not remote_name:
                continue
            fetch_url = remote_map.get(remote_name)
            if not fetch_url:
                continue
            raw_url = join_project_repo_url(fetch_url, name)
            try:
                canonical_url = canonicalize_repo_url(raw_url)
            except ValueError:
                continue
            revision = project_el.get("revision") or default_revision or ""
            entries.append(
                ProjectEntry(
                    name=name,
                    url=raw_url,
                    canonical_url=canonical_url,
                    ref_spec="*",
                    resolved_ref=revision or resolved_sha,
                    resolved_sha=resolved_sha,
                )
            )
            seen.add(name)

    return sorted(entries, key=lambda p: p.name)


def apply_content_pins_to_manifests(
    manifest_paths: list[pathlib.Path],
    content_pins: list[ContentPinEntry],
) -> None:
    """Rewrite each pinned ``<project revision>`` to its locked content SHA.

    Replay path (spec Section 5.2 / FR-22): when a source's locked
    ``content_pins`` are present, this rewrites the ``revision`` attribute of
    every matching ``<project>`` element (matched by project ``name``) in the
    resolved manifest XML files to the locked 40/64-hex content SHA, BEFORE
    ``repo sync`` runs.  The vendored repo tool accepts a bare SHA revision and
    checks out exactly that commit, so the exact locked content is materialised
    and the declared branch/tag tip is NOT re-resolved.

    Only projects with a captured pin are rewritten; a project absent from
    *content_pins* keeps its declared revision.  A manifest file is rewritten in
    place only when at least one of its projects was repinned.

    Args:
        manifest_paths: Absolute paths to the source's resolved manifest files.
        content_pins: The locked ``ContentPinEntry`` rows for this source.

    Raises:
        OSError: If a manifest file cannot be rewritten.
    """
    sha_by_name = {pin.name: pin.resolved_sha for pin in content_pins}
    if not sha_by_name:
        return
    for manifest_path in manifest_paths:
        if not manifest_path.is_file():
            continue
        try:
            tree = ET.parse(str(manifest_path))
        except ET.ParseError:
            continue
        root = tree.getroot()
        changed = False
        for project_el in root.findall("project"):
            name = project_el.get("name", "")
            locked_sha = sha_by_name.get(name)
            if locked_sha is None:
                continue
            if project_el.get("revision") != locked_sha:
                project_el.set("revision", locked_sha)
                changed = True
        if changed:
            tree.write(str(manifest_path), encoding="unicode", xml_declaration=True)


def assert_manifest_vars_resolved(
    source_name: str,
    manifest_paths: list[pathlib.Path],
) -> None:
    """Fail fast when any synced manifest still references an unprovided ``${VAR}``.

    The repo-tool ``envsubst`` only warns on an unresolved ``${VAR}`` and exits
    0, leaving the placeholder verbatim in the manifest XML. This parses each
    resolved manifest's XML and flags a remaining ``${VAR}`` ONLY when it appears
    in a *functional* attribute value -- the attributes of the ``<remote>``
    elements a ``<project>`` references and the projects' own attributes -- which
    are exactly what ``repo sync`` consumes. ``${VAR}`` in XML comments,
    ``<![CDATA[...]]>`` blocks, or element text is documentation prose and is
    ignored, so a manifest whose functional substitution succeeded never fails on
    a placeholder that survives only in prose.

    Detection (:func:`kanon_cli.commands.add._detect_manifest_env_vars`) and this
    guard call the SAME shared helper
    (:func:`kanon_cli.core.manifest_vars.functional_vars_in_manifest_files`), so
    the set of var names ``add`` records and the set this guard checks are
    consistent by construction. On an unresolved functional ``${VAR}`` this
    raises :class:`UnresolvedManifestVarError` (naming the exact ``.kanon`` key to
    set) BEFORE ``repo sync`` so kanon never proceeds with an unresolved fetch
    URL.

    Args:
        source_name: The source alias (used in the diagnostic).
        manifest_paths: Absolute paths to the source's resolved manifest files
            (the root manifest plus its ``<include>`` chain).

    Raises:
        UnresolvedManifestVarError: If any functional attribute value in the
            resolved manifest tree still contains a ``${VAR}`` placeholder after
            envsubst.
    """
    unresolved = functional_vars_in_manifest_files(manifest_paths)
    if unresolved:
        raise UnresolvedManifestVarError(source_name=source_name, var_names=sorted(unresolved))


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
    entries: list[str],
) -> None:
    """Ensure ``base_dir/.gitignore`` contains the given entries.

    Creates ``.gitignore`` if it does not exist. Appends missing entries without
    duplicating existing ones. ``entries`` is always supplied by the caller; the
    sole caller is the in-git-repo store safety net, which passes the whole-store
    ignore entry (``KANON_HOME_STORE_GITIGNORE_ENTRY``).

    Args:
        base_dir: Directory whose ``.gitignore`` is ensured.
        entries: List of gitignore entries to ensure are present.
    """
    gitignore = base_dir / ".gitignore"

    existing_content = ""
    if gitignore.exists():
        existing_content = gitignore.read_text(encoding="utf-8")

    existing_lines = existing_content.splitlines()
    missing = [entry for entry in entries if entry not in existing_lines]

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

    if revision_spec.startswith("refs/tags/"):
        return False

    if revision_spec.startswith("refs/heads/"):
        return True

    if revision_spec.startswith("refs/"):
        return True

    try:
        SpecifierSet(revision_spec)

        parsed = SpecifierSet(revision_spec)
        if len(list(parsed)) > 0:
            return False
    except (InvalidSpecifier, ValueError):
        pass

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


def _assert_lockfile_consistent_or_fail(
    kanon_aliases: list[str],
    kanon_ref_specs: dict[str, str],
    lockfile: "Lockfile",
) -> None:
    """Fail fast when ``.kanon`` and ``.kanon.lock`` have drifted (spec FR-24).

    Runs the shared :func:`check_lockfile_consistency` -- the SAME alias-set /
    per-alias ref-spec parity check ``kanon validate lockfile`` runs -- before
    the default install resolves anything.  A drifted pair (an added/removed
    source alias, or a changed ``<source revision>``) raises
    :class:`LockfileConsistencyError`, which the install CLI converts to a
    non-zero exit with the check's actionable message (spec Section 4.3 /
    Section 4.5).

    This is the wiring the lockfile module docstring always claimed existed:
    ``kanon install`` now genuinely runs the consistency check before resolving,
    instead of silently auto-pruning a drifted lock.  Reconciliation is opt-in
    via ``--reconcile`` (lenient prune + re-resolve of changed sources) or
    ``--refresh-lock`` (full rebuild).

    Args:
        kanon_aliases: Source aliases declared in the current ``.kanon``.
        kanon_ref_specs: Mapping of each ``.kanon`` alias to its declared
            ``<source revision>``.
        lockfile: The parsed ``.kanon.lock`` to compare against.

    Raises:
        LockfileConsistencyError: If the ``.kanon`` and ``.kanon.lock`` alias
            sets differ, an alias is duplicated, or a per-alias ref-spec drifted.
    """
    check_lockfile_consistency(kanon_aliases, kanon_ref_specs, lockfile)


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

        ref_to_query = entry.resolved_ref if entry.resolved_ref else entry.ref_spec

        returncode, stdout, _stderr = run_git_ls_remote(
            ["git", "ls-remote", entry.url, ref_to_query],
            timeout=KANON_GIT_LS_REMOTE_TIMEOUT,
            retry_count=1,
        )
        if returncode != 0:
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
            continue

        if current_sha != entry.resolved_sha:
            branch_name = entry.resolved_ref
            if branch_name.startswith("refs/heads/"):
                branch_name = branch_name[len("refs/heads/") :]
            elif branch_name.startswith("refs/"):
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
    reconcile: bool = False,
) -> None:
    """Execute the install lifecycle without acquiring the concurrency lock.

    This is the inner implementation called by install() after the exclusive
    file lock is held. All filesystem mutations happen here.

    Implements the lockfile state-machine branching:
    - LOCKFILE_ABSENT: resolve fresh, install, write lockfile.
    - LOCKFILE_CONSISTENT: install exactly the SHAs in the lockfile; skip resolve.
    - LOCKFILE_HASH_MISMATCH (default, npm ci): FAIL FAST -- the .kanon <-> .kanon.lock
      consistency check (FR-24) runs before resolving, so a drifted pair exits 1
      with an actionable error and the lock is never mutated.  Reconciliation is
      opt-in via ``--reconcile``; a full rebuild is opt-in via ``--refresh-lock``.
    - LOCKFILE_HASH_MISMATCH (--reconcile, npm install): derive RECONCILE -- prune
      orphans, resolve added/changed sources fresh, replay unchanged sources,
      rebuild + write the lockfile once at the end on success only.
    - REFRESH_LOCK: ignore lockfile entirely, re-resolve fresh, overwrite lockfile.
    - REFRESH_LOCK_SOURCE: re-resolve exactly one source chain, preserve all others.

    Content-SHA locking (spec Section 5.2, AMENDED 2026-06-25): on a fresh
    resolve (LOCKFILE_ABSENT / REFRESH_LOCK / a re-resolved source) each project's
    content commit SHA is captured after ``repo sync`` and recorded as a v5
    content pin.  On a replay (LOCKFILE_CONSISTENT / RECONCILE replay / preserved
    REFRESH_LOCK_SOURCE entry) the locked content SHAs are written onto the synced
    manifest before sync, so the exact locked content is checked out byte-for-byte
    and a branch/tag tip is never silently re-resolved.

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
            instead of pruning with an info-line.  Only applies in the consistent
            state; on a hash mismatch the default is already fail-fast.
        strict_drift: When ``True``, upgrade branch drift (branch tip on remote
            differs from locked SHA) to ``BranchDriftError`` instead of reusing
            the locked SHA with an info-line.  Only applies in the consistent state.
        reconcile: When ``True``, opt back in to the lenient npm-install reconcile
            on a hash mismatch (prune orphans, re-resolve added/changed sources,
            replay unchanged ones, rewrite the lock on success).  Default ``False``
            fails fast on drift via the FR-24 consistency check before resolving.

    Raises:
        LockfileConsistencyError: On the default (non-``--reconcile``) path when the
            ``.kanon`` and ``.kanon.lock`` alias sets or per-alias ref-specs have
            drifted (the FR-24 consistency check runs before resolving).
        KanonHashMismatchError: On the default path when the lockfile's kanon_hash
            differs for a reason the consistency check does not cover (e.g. a PATH
            change) other than a pure source removal.  ``--reconcile`` reconciles
            instead of raising.
        UnknownSourceError: If ``refresh_lock_source`` does not match any known
            top-level source name (by literal or derive_source_name match).
        OrphanedLockEntryError: If ``strict_lock=True`` and the lockfile contains
            sources absent from the current ``.kanon`` source declarations.
        BranchDriftError: If ``strict_drift=True`` and a branch-shaped source's
            remote tip differs from the locked SHA.
        PackagePathConflictError: If two or more sources resolve the same package
            destination path (``.packages/<name>``) to different content SHAs.
            Raised on both the absent-lockfile path (after fresh resolution) and
            the consistent path (against the existing lockfile content pins).
        ValueError: If the catalog source is not in ``url@ref`` form, if
            git ls-remote fails or a ref is not found, if marketplace install
            is requested but CLAUDE_MARKETPLACES_DIR is not configured, or on
            package collision.
        OSError: If a source directory cannot be created.
        RepoCommandError: If any repo sub-command exits non-zero.
    """

    install_state: InstallState
    existing_lockfile: Lockfile | None
    lockfile_hash_mismatch_lockfile: Lockfile | None = None
    lockfile_hash_mismatch_computed: str | None = None

    if refresh_lock_source is not None:
        install_state = InstallState.REFRESH_LOCK_SOURCE
        existing_lockfile = read_lockfile_if_present(lockfile_path)
    else:
        classification = _classify_install_state(kanonenv_path, lockfile_path, refresh_lock=refresh_lock)
        install_state = classification.state
        existing_lockfile = classification.lockfile
        if install_state is InstallState.LOCKFILE_HASH_MISMATCH:
            lockfile_hash_mismatch_lockfile = classification.lockfile
            lockfile_hash_mismatch_computed = classification.computed_hash

    _consistent_has_orphans: bool = False

    reconcile_computed_hash: str | None = None

    if install_state is InstallState.LOCKFILE_HASH_MISMATCH:
        existing_lockfile_nn = cast(Lockfile, lockfile_hash_mismatch_lockfile)
        computed_hash_nn = cast(str, lockfile_hash_mismatch_computed)

        mismatch_config = parse_kanonenv(kanonenv_path)
        mismatch_source_names: list[str] = mismatch_config["KANON_SOURCES"]
        mismatch_revision_specs: dict[str, str] = {
            name: mismatch_config["sources"][name]["ref"] for name in mismatch_source_names
        }

        if not reconcile:
            _assert_lockfile_consistent_or_fail(
                mismatch_source_names,
                mismatch_revision_specs,
                existing_lockfile_nn,
            )
            raise _strict_lock_drift_error(
                existing_lockfile_nn,
                mismatch_source_names,
                computed_hash=computed_hash_nn,
                kanon_revision_specs=mismatch_revision_specs,
            )

        orphaned_on_mismatch = _detect_orphaned_lock_entries(existing_lockfile_nn, mismatch_source_names)
        for orphan_name in orphaned_on_mismatch:
            print(f"{INFO_PRUNED_ORPHAN_LOCK_ENTRY}: {orphan_name}")
        install_state = InstallState.RECONCILE
        existing_lockfile = existing_lockfile_nn
        reconcile_computed_hash = computed_hash_nn

    print(f"kanon install: parsing {kanonenv_path}...")
    config = parse_kanonenv(kanonenv_path)

    placeholder_findings = _scan_kanonenv_for_unresolved_placeholders(kanonenv_path)
    if placeholder_findings:
        first_line_no, first_placeholder = placeholder_findings[0]
        raise UnresolvedPlaceholderError(
            line_number=first_line_no,
            placeholder=first_placeholder,
            all_findings=placeholder_findings,
        )

    base_dir = resolve_workspace_base_dir()
    source_names = config["KANON_SOURCES"]
    sources = config["sources"]
    globals_dict = config["globals"]

    source_marketplace: dict[str, bool] = {name: bool(sources[name][SOURCE_MARKETPLACE_KEY]) for name in source_names}
    any_marketplace = any(source_marketplace.values())

    marketplace_dir_str = globals_dict.get("CLAUDE_MARKETPLACES_DIR", "")

    if any_marketplace and not marketplace_dir_str:
        raise ValueError(
            "a KANON_SOURCE_<alias>_MARKETPLACE=true dependency is declared but "
            "CLAUDE_MARKETPLACES_DIR is not defined in .kanon"
        )

    if any_marketplace:
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        print("kanon install: preparing marketplace directory...")
        prepare_marketplace_dir(marketplace_dir)

    repo_rev = globals_dict.get("REPO_REV", "")

    base_env_vars: dict[str, str] = {}
    if "GITBASE" in globals_dict:
        base_env_vars["GITBASE"] = globals_dict["GITBASE"]
    if marketplace_dir_str:
        base_env_vars["CLAUDE_MARKETPLACES_DIR"] = marketplace_dir_str

    source_dirs = create_source_dirs(source_names, base_dir)

    allow_insecure: bool = os.environ.get(KANON_ALLOW_INSECURE_REMOTES) == "1"

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

        lockfile_pins = _gather_package_pins(existing_lockfile.sources)
        path_conflict_reports = _detect_package_path_conflicts(lockfile_pins)
        if path_conflict_reports:
            raise PackagePathConflictError(reports=path_conflict_reports)

    resolved_entries: list[SourceEntry] = []

    attributed_marketplaces: dict[str, list[str]] = {}

    refresh_lock_source_nn: str = cast(str, refresh_lock_source)
    target_source_entry: SourceEntry | None = None
    if install_state is InstallState.REFRESH_LOCK_SOURCE and existing_lockfile is not None:
        target_source_entry = _resolve_source_name(refresh_lock_source_nn, existing_lockfile)
    elif install_state is InstallState.REFRESH_LOCK_SOURCE and existing_lockfile is None:
        if refresh_lock_source_nn not in source_names:
            normalised = derive_source_name(refresh_lock_source_nn)
            if normalised not in source_names:
                raise UnknownSourceError(name=refresh_lock_source_nn, known_names=source_names)

    for name in source_names:
        source_dir = source_dirs[name]
        source_data = sources[name]
        print(f"kanon install: syncing source '{name}'...")

        before_marketplace_names: set[str] = set()
        if source_marketplace[name]:
            before_marketplace_names = set(discover_registered_marketplace_names(pathlib.Path(marketplace_dir_str)))

        reconcile_replay = install_state is InstallState.RECONCILE and _should_replay_source(
            name,
            source_data["ref"],
            existing_lockfile,
        )

        if install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
            _replay_candidate = next(
                (e for e in existing_lockfile.sources if e.name == name),
                None,
            )
            if _replay_candidate is None:
                raise LockfileConsistencyError(
                    f"ERROR: source {name!r} is declared in .kanon but missing from .kanon.lock,"
                    f" yet the kanon_hash matched.\n"
                    f"  This means .kanon.lock was edited out of sync with .kanon.\n"
                    f"  Remediation: run 'kanon install --refresh-lock' to rebuild the lock, or"
                    f" restore the missing [[sources]] entry for {name!r}."
                )
            _url_to_check = _replay_candidate.url
        elif reconcile_replay and existing_lockfile is not None:
            _reconcile_pinned = next((e for e in existing_lockfile.sources if e.name == name), None)

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
            is_refresh_target = (target_source_entry is not None and target_source_entry.name == name) or (
                existing_lockfile is None
                and (name == refresh_lock_source_nn or name == derive_source_name(refresh_lock_source_nn))
            )

            if is_refresh_target:
                new_entry = _refresh_one_source(name, source_data)
                resolved_entries.append(new_entry)
                resolved_revision = new_entry.resolved_sha
            elif existing_lockfile is not None:
                pinned = next(
                    (e for e in existing_lockfile.sources if e.name == name),
                    None,
                )
                if pinned is not None:
                    resolved_revision = pinned.resolved_sha
                    resolved_entries.append(pinned)
                else:
                    new_entry = _refresh_one_source(name, source_data)
                    resolved_entries.append(new_entry)
                    resolved_revision = new_entry.resolved_sha
            else:
                new_entry = _refresh_one_source(name, source_data)
                resolved_entries.append(new_entry)
                resolved_revision = new_entry.resolved_sha
        elif install_state is InstallState.RECONCILE:
            if reconcile_replay and existing_lockfile is not None:
                pinned = cast(SourceEntry, next(e for e in existing_lockfile.sources if e.name == name))
                _check_sha_reachable(
                    url=pinned.url,
                    sha=pinned.resolved_sha,
                    source_name=name,
                )
                resolved_revision = pinned.resolved_sha
                resolved_entries.append(pinned)
            else:
                new_entry = _refresh_one_source(name, source_data)
                resolved_entries.append(new_entry)
                resolved_revision = new_entry.resolved_sha
        elif install_state is InstallState.LOCKFILE_CONSISTENT and existing_lockfile is not None:
            pinned = next(
                (e for e in existing_lockfile.sources if e.name == name),
                None,
            )
            if pinned is not None:
                if name not in _drifted_source_names:
                    _check_sha_reachable(
                        url=pinned.url,
                        sha=pinned.resolved_sha,
                        source_name=name,
                    )
                resolved_revision = pinned.resolved_sha
                resolved_entries.append(pinned)
            else:
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

        _is_reresolve = install_state in (
            InstallState.REFRESH_LOCK,
            InstallState.REFRESH_LOCK_SOURCE,
        ) or (install_state is InstallState.RECONCILE and not reconcile_replay)
        if _is_reresolve:
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
        source_env_vars = build_source_envsubst_vars(
            base_env_vars,
            cast(dict[str, str], source_data[SOURCE_ENV_KEY]),
        )
        run_repo_envsubst(source_dir, source_env_vars)

        manifest_repo_root = source_dir / ".repo" / "manifests"
        manifest_xml_path = manifest_repo_root / source_data["path"]

        include_tree = _walk_includes(manifest_xml_path, manifest_repo_root)

        _manifest_tree_paths = _collect_manifest_tree_paths(include_tree, manifest_repo_root)

        assert_manifest_vars_resolved(name, _manifest_tree_paths)

        _replay_locked_pins = not _is_reresolve and bool(resolved_entries[-1].content_pins)
        if _replay_locked_pins:
            apply_content_pins_to_manifests(_manifest_tree_paths, resolved_entries[-1].content_pins)

        print("  repo sync...")
        run_repo_sync(source_dir)

        if not _replay_locked_pins:
            resolved_entries[-1].content_pins = capture_content_pins(source_dir, _manifest_tree_paths)
            resolved_entries[-1].projects = build_project_entries(
                manifest_xml_path,
                manifest_repo_root,
                _manifest_tree_paths,
                resolved_entries[-1].content_pins,
            )

        if source_marketplace[name]:
            marketplace_dir = pathlib.Path(marketplace_dir_str)
            _process_manifest_linkfiles(manifest_xml_path, source_dir)

            register_direct_checkout_marketplaces(manifest_xml_path, source_dir, marketplace_dir)

            after_names = set(discover_registered_marketplace_names(marketplace_dir))
            attributed_marketplaces[name] = sorted(after_names - before_marketplace_names)
            resolved_entries[-1].registered_marketplaces = attributed_marketplaces[name]

        resolved_entries[-1].includes = _include_tree_to_entries(
            include_tree,
            source_url=source_data["url"],
            resolved_sha=resolved_entries[-1].resolved_sha,
        )

        entry_address = compute_store_entry_address(source_data["url"], resolved_entries[-1].resolved_sha)
        publish_store_entry(
            base_dir,
            entry_address,
            lambda dest, src=source_dir: shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True),
        )

    if install_state is not InstallState.LOCKFILE_CONSISTENT:
        fresh_pins = _gather_package_pins(resolved_entries)
        path_conflict_reports = _detect_package_path_conflicts(fresh_pins)
        if path_conflict_reports:
            raise PackagePathConflictError(reports=path_conflict_reports)

    print("kanon install: aggregating packages into .packages/...")
    package_owners = aggregate_symlinks(source_names, base_dir)

    write_store_gitignore_if_in_git_repo(base_dir)

    if install_state is InstallState.REFRESH_LOCK_SOURCE and target_source_entry is not None:
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

    if any_marketplace:
        print("\nkanon install: installing marketplace plugins...")
        marketplace_dir = pathlib.Path(marketplace_dir_str)
        install_marketplace_plugins(marketplace_dir)

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

    if install_state in (InstallState.LOCKFILE_ABSENT, InstallState.REFRESH_LOCK):
        computed_hash = _kanon_hash(kanonenv_path)

        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=f"kanon-cli/{__version__}",
            kanon_hash=computed_hash,
            sources=resolved_entries,
            marketplace_registered=any_marketplace,
            marketplace_dir=marketplace_dir_str if any_marketplace else "",
        )
        write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.RECONCILE:
        reconcile_hash_nn = cast(str, reconcile_computed_hash)
        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=f"kanon-cli/{__version__}",
            kanon_hash=reconcile_hash_nn,
            sources=resolved_entries,
            marketplace_registered=any_marketplace,
            marketplace_dir=marketplace_dir_str if any_marketplace else "",
        )
        write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.REFRESH_LOCK_SOURCE:
        new_kanon_hash = _kanon_hash(kanonenv_path)
        if existing_lockfile is not None and target_source_entry is not None:
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
            lf = Lockfile(
                schema_version=CURRENT_SCHEMA_VERSION,
                generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                generator=f"kanon-cli/{__version__}",
                kanon_hash=new_kanon_hash,
                sources=resolved_entries,
                marketplace_registered=any_marketplace,
                marketplace_dir=marketplace_dir_str if any_marketplace else "",
            )
            write_lockfile(lf, lockfile_path)

    elif install_state is InstallState.LOCKFILE_CONSISTENT and _consistent_has_orphans:
        pruned_lf_nn = cast(Lockfile, existing_lockfile)
        active_names = set(source_names)

        pruned_sources = [e for e in pruned_lf_nn.sources if e.name in active_names]
        pruned_lockfile = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator=pruned_lf_nn.generator,
            kanon_hash=pruned_lf_nn.kanon_hash,
            sources=pruned_sources,
            marketplace_registered=any_marketplace,
            marketplace_dir=marketplace_dir_str if any_marketplace else "",
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
    reconcile: bool = False,
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
      5. If any dependency sets KANON_SOURCE_<alias>_MARKETPLACE=true: create
         and clean the marketplace dir.
      6. For each source: mkdir, repo init (or lockfile replay), envsubst, sync.
         On the REFRESH_LOCK_SOURCE path, only the named source is re-resolved;
         all other sources replay their pinned SHAs from the existing lockfile.
      7. Aggregate symlinks into .packages/.
      8. Update .gitignore.
      9. Emit state info-line via _emit_install_state.
      10. If any dependency sets KANON_SOURCE_<alias>_MARKETPLACE=true: run the
          marketplace install script.
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
        reconcile: When ``True``, opt in to the lenient npm-install reconcile on a
            hash mismatch (prune orphans, re-resolve added/changed sources, replay
            unchanged ones).  Default ``False`` fails fast on ``.kanon`` <->
            ``.kanon.lock`` drift via the FR-24 consistency check before resolving.

    Raises:
        LockfileConsistencyError: On the default (non-``--reconcile``) path when
            ``.kanon`` and ``.kanon.lock`` have drifted (alias-set or per-alias
            ref-spec mismatch) -- the FR-24 consistency check runs before resolving.
        KanonHashMismatchError: On the default path when the kanon_hash differs for
            a reason the consistency check does not cover, other than a pure source
            removal.  ``reconcile=True`` reconciles instead of raising.
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
    base_dir = resolve_workspace_base_dir()

    with kanon_workspace_lock(base_dir):
        _run_install(
            kanonenv_path,
            lock_file_path,
            refresh_lock=refresh_lock,
            refresh_lock_source=refresh_lock_source,
            strict_lock=strict_lock,
            strict_drift=strict_drift,
            reconcile=reconcile,
        )
