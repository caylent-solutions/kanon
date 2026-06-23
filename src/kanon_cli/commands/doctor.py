"""kanon doctor subcommand: workspace health checks and cache refresh.

Performs workspace health checks and optionally refreshes the completion cache
or prunes stale cache files.
The --refresh-completion-cache flag invalidates all files under
${KANON_CACHE_DIR}/completion-cache/ when KANON_CACHE_DIR is set.
The --prune-cache flag removes cache files whose atime is older than
KANON_CACHE_PRUNE_AGE_DAYS days and reports stale install-lock advisories.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.6 (kanon doctor subchecks 1-5, 7-11), Section 5.1 (kanon_hash),
Section 7 (retry policy, KANON_RESOLVE_TIMEOUT),
Section 11 (cache layout), Section 3.6 (cache files user-private mode 0700).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import re
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from kanon_cli.core.lockfile import Lockfile

from kanon_cli.constants import (
    CATALOG_SOURCES_ENV_VAR,
    FINDING_PREFIX_FAIL,
    FINDING_PREFIX_INFO,
    FINDING_PREFIX_OK,
    FINDING_SEVERITY_FAIL,
    FINDING_SEVERITY_INFO,
    FINDING_SEVERITY_OK,
    GIT_RETRY_COUNT_DEFAULT,
    GIT_RETRY_COUNT_ENV_VAR,
    GIT_RETRY_DELAY_DEFAULT,
    GIT_RETRY_DELAY_ENV_VAR,
    INSTALL_LOCK_FILENAME,
    KANON_CACHE_DIR_ENV,
    KANON_CACHE_DIR_MODE,
    KANON_CACHE_PRUNE_AGE_DAYS,
    KANON_COMPLETION_CACHE_DIR,
    KANON_COMPLETION_ERRORS_LOG_FILENAME,
    KANON_COMPLETION_ERRORS_REPORT_LIMIT,
    KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS,
    KANON_DOCTOR_STALE_LOCK_AGE_HOURS,
    KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    KANON_STALE_COMPLETION_SCRIPT_WARNING,
    KANON_STATIC_COMPLETION_SEARCH_PATHS,
    _KANON_RESOLVE_TIMEOUT_DEFAULT,
    _KANON_RESOLVE_TIMEOUT_ENV,
)
from kanon_cli.core.catalog import parse_catalog_sources
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.git_runner import run_git_ls_remote

# Sentinel for detecting whether --catalog-source was explicitly supplied on the
# command line versus left at the argparse default.  argparse sets catalog_source
# to _UNSET when the user did not supply the flag; any other value (including the
# single source resolved from KANON_CATALOG_SOURCES) means the user typed it on
# the CLI.
_UNSET: object = object()

# ---------------------------------------------------------------------------
# Workspace-free flag names
# ---------------------------------------------------------------------------

# Flags whose actions operate solely on KANON_CACHE_DIR and require no
# per-project .kanon workspace. When the set of active (truthy) flag names is
# non-empty AND a subset of WORKSPACE_FREE_FLAGS, workspace discovery is
# skipped entirely. Mixed invocations (any cache flag combined with any
# subcheck flag) still require the workspace and are NOT short-circuited.
WORKSPACE_FREE_FLAGS: frozenset[str] = frozenset({"refresh_completion_cache", "prune_cache"})


# ---------------------------------------------------------------------------
# DoctorArgsTypeError exception
# ---------------------------------------------------------------------------


class DoctorArgsTypeError(TypeError):
    """Raised when doctor_command receives args that is not an argparse.Namespace.

    The CLI layer is responsible for catching this and emitting a structured
    ERROR message with non-zero exit code.

    Attributes:
        received_type: The type that was passed instead of argparse.Namespace.
    """

    def __init__(self, received_type: type) -> None:
        self.received_type = received_type
        super().__init__(
            f"args must be an argparse.Namespace; got {received_type!r}. Supply a valid Namespace from argparse."
        )


# ---------------------------------------------------------------------------
# Subcheck name constants (DEFECT-012 fix)
# ---------------------------------------------------------------------------

# Canonical name strings emitted by the dispatcher for each subcheck on success.
# These identifiers appear in `[ok] <name>` / `[fail] <name>: <reason>` output.
# All code that constructs a Finding for a named subcheck MUST reference these
# constants rather than inline string literals (CLAUDE.md NO HARD-CODED VALUES).
DOCTOR_SUBCHECK_KANON_HASH = "kanon_hash consistency"
DOCTOR_SUBCHECK_ORPHAN_LOCKS = "no orphaned lock entries"
DOCTOR_SUBCHECK_BRANCH_DRIFT = "no branch drift"


# ---------------------------------------------------------------------------
# DoctorContractError exception
# ---------------------------------------------------------------------------


class DoctorContractError(RuntimeError):
    """Raised when a subcheck handler returns a value that is not a Finding.

    This exception surfaces a programming-contract violation immediately so
    that a refactor miss is caught at runtime rather than silently degrading
    the structured output.

    Attributes:
        handler_name: Name of the subcheck handler that violated the contract.
        received: The unexpected return value.
    """

    def __init__(self, handler_name: str, received: object) -> None:
        self.handler_name = handler_name
        self.received = received
        super().__init__(
            f"Subcheck handler '{handler_name}' returned {type(received)!r} instead of Finding. "
            "All subcheck handlers must return a Finding instance."
        )


# ---------------------------------------------------------------------------
# Finding dataclass (DEFECT-012 fix)
# ---------------------------------------------------------------------------

_VALID_FINDING_SEVERITIES: frozenset[str] = frozenset(
    {FINDING_SEVERITY_OK, FINDING_SEVERITY_FAIL, FINDING_SEVERITY_INFO}
)


@dataclass(frozen=True)
class Finding:
    """A structured output record produced by the doctor dispatcher.

    Each Finding corresponds to one named subcheck. The dispatcher iterates
    findings and prints them per the severity-to-prefix map:
      - ok   -> "[ok] <name>"
      - fail -> "[fail] <name>: <reason>"
      - info -> "[info] <name>" or "[info] <name>: <reason>" when reason is set

    Attributes:
        severity: One of FINDING_SEVERITY_OK, FINDING_SEVERITY_FAIL, or
            FINDING_SEVERITY_INFO. Validated in __post_init__.
        name: Subcheck identifier string (e.g. DOCTOR_SUBCHECK_KANON_HASH).
        reason: Optional detail string. Populated for fail/info severities;
            None for ok findings.
    """

    severity: str
    name: str
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate that severity is one of the three allowed values."""
        if self.severity not in _VALID_FINDING_SEVERITIES:
            raise ValueError(
                f"Finding.severity must be one of {sorted(_VALID_FINDING_SEVERITIES)!r}; got {self.severity!r}"
            )


# ---------------------------------------------------------------------------
# DoctorFinding dataclass
# ---------------------------------------------------------------------------


@dataclass
class DoctorFinding:
    """A single finding produced by one kanon doctor subcheck.

    Attributes:
        kind: Severity of the finding -- one of "info", "warn", or "error".
        code: A short machine-readable identifier for the finding type.
        message: Human-readable description of the finding.
        remediation: Suggested command or action to resolve the finding.
    """

    kind: str
    code: str
    message: str
    remediation: str


# ---------------------------------------------------------------------------
# Utility: _is_branch_revision
# ---------------------------------------------------------------------------

# SHA-1 (40 chars) and SHA-256 (64 chars) hex digits.
_SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")


def _is_branch_revision(revision_spec: str) -> bool:
    """Return True if revision_spec looks like a branch name (not a SHA or refs/ ref).

    A revision is treated as branch-pinned when it does NOT match a full SHA
    (40 or 64 lowercase hex chars) and does NOT start with ``refs/``.

    Args:
        revision_spec: The revision string from the lockfile.

    Returns:
        True if the revision should be treated as a branch ref to drift-check.
    """
    if _SHA_RE.match(revision_spec):
        return False
    if revision_spec.startswith("refs/"):
        return False
    return True


# ---------------------------------------------------------------------------
# Utility: _run_ls_remote
# ---------------------------------------------------------------------------


def _run_ls_remote(
    url: str,
    ref: str,
    timeout: int,
    retry_count: int,
    retry_delay: float,
) -> tuple[int, str, str]:
    """Run ``git ls-remote <url> <ref>`` with retry and timeout policy.

    Delegates to ``kanon_cli.core.git_runner.run_git_ls_remote``.

    When ``ref`` is an empty string, runs ``git ls-remote <url>`` (no ref
    pattern) to list all refs. This is required for SHA reachability checks
    since ``git ls-remote --exit-code <url> <sha>`` only matches against
    ref *names*, not against SHA values in the first column.

    Args:
        url: The git remote URL to query.
        ref: The ref to look up (branch name or refs/... path). Pass an empty
            string to list all refs without filtering.
        timeout: Per-attempt timeout in seconds.
        retry_count: Maximum number of attempts (1 means no retries).
        retry_delay: Unused. Retained for call-site compatibility while
            existing callers are migrated. The retry loop in git_runner uses
            no time-based delay (spec Section 3.5 / issue #64).

    Returns:
        A tuple (returncode, stdout, stderr) from the final attempt.
    """
    if ref:
        cmd = ["git", "ls-remote", url, ref]
    else:
        cmd = ["git", "ls-remote", url]
    return run_git_ls_remote(cmd, timeout, retry_count)


def _run_ls_remote_exit_code(
    url: str,
    ref: str,
    timeout: int,
    retry_count: int,
    retry_delay: float,
) -> tuple[int, str, str]:
    """Run ``git ls-remote --exit-code <url> <ref>`` with retry and timeout policy.

    This variant always passes ``--exit-code`` so that git returns a non-zero
    exit code when the remote exists but the requested ref is absent (in
    addition to the normal non-zero on network/auth failures).  Used by
    subcheck 11 (remote reachability) per spec Section 4.6.

    Delegates to ``kanon_cli.core.git_runner.run_git_ls_remote``.

    Args:
        url: The git remote URL to query.
        ref: The ref to look up (e.g. ``HEAD``).
        timeout: Per-attempt timeout in seconds.
        retry_count: Maximum number of attempts (1 means no retries).
        retry_delay: Unused. Retained for call-site compatibility while
            existing callers are migrated. The retry loop in git_runner uses
            no time-based delay (spec Section 3.5 / issue #64).

    Returns:
        A tuple (returncode, stdout, stderr) from the final attempt.
    """
    cmd = ["git", "ls-remote", "--exit-code", url, ref]
    return run_git_ls_remote(cmd, timeout, retry_count)


# ---------------------------------------------------------------------------
# Subcheck 1: .kanon / .kanon.lock consistency
# ---------------------------------------------------------------------------


def _check_kanon_hash(
    kanon_file: pathlib.Path,
    lock_file: pathlib.Path,
) -> DoctorFinding | None:
    """Check .kanon file existence and kanon_hash match against the lockfile.

    Subcheck 1 in spec Section 4.6:
    - If .kanon is absent: returns an error finding (code=NO_KANON).
    - If .kanon.lock is absent: returns an info finding (code=NO_LOCKFILE).
    - If the .kanon declares zero sources: returns an error finding
      (code=NO_SOURCES). The kanon_hash recompute re-parses the .kanon file and
      a zero-source workspace raises NoSourcesError; this is converted to a
      structured finding rather than allowed to escape.
    - If kanon_hash in lockfile differs from the recomputed hash: returns error
      (code=HASH_MISMATCH).
    - Otherwise: returns None (no finding -- checks 2-5 may proceed).

    This function is pure: it performs no I/O on stdout/stderr. It catches the
    zero-source NoSourcesError and reports it as a finding; any other parser
    exception propagates to the caller.

    Args:
        kanon_file: Path to the .kanon file.
        lock_file: Path to the .kanon.lock file.

    Returns:
        A DoctorFinding instance on failure/notice, or None on success.
    """
    if not kanon_file.exists():
        cwd = kanon_file.parent
        return DoctorFinding(
            kind="error",
            code="NO_KANON",
            message=f"no kanon workspace in {cwd}: '{kanon_file.name}' not found",
            remediation=("Run 'kanon add ...' to create a .kanon file, or 'cd' to a directory that contains one."),
        )

    if not lock_file.exists():
        return DoctorFinding(
            kind="info",
            code="NO_LOCKFILE",
            message="No lockfile present; run `kanon install` to generate one.",
            remediation="kanon install",
        )

    from kanon_cli.core.kanon_hash import kanon_hash
    from kanon_cli.core.kanonenv import NoSourcesError
    from kanon_cli.core.lockfile import read_lockfile

    lockfile = read_lockfile(lock_file)
    # Recomputing kanon_hash re-parses the .kanon file; a zero-source workspace
    # (no KANON_SOURCE_<name>_* triples) raises NoSourcesError. Convert it to a
    # structured finding so doctor reports a clean error and exits non-zero
    # instead of leaking the raw exception (which would surface as a traceback).
    try:
        computed = kanon_hash(kanon_file)
    except NoSourcesError:
        return DoctorFinding(
            kind="error",
            code="NO_SOURCES",
            message="no sources declared in .kanon; add one with 'kanon add <entry>'",
            remediation="Run 'kanon add <entry>' to declare at least one source.",
        )
    if computed != lockfile.kanon_hash:
        return DoctorFinding(
            kind="error",
            code="HASH_MISMATCH",
            message=("kanon_hash mismatch: .kanon was hand-edited since the last 'kanon install'."),
            remediation="Run 'kanon install --refresh-lock' to rebuild the lockfile.",
        )

    return None


# ---------------------------------------------------------------------------
# Subcheck 3: Orphaned lock entries
# ---------------------------------------------------------------------------


def _check_orphan_locks(
    kanon_file: pathlib.Path,
    lockfile: Lockfile,
) -> list[DoctorFinding]:
    """Check for lockfile entries whose source triples are absent from .kanon.

    Subcheck 3 in spec Section 4.6: For every source recorded in the lockfile,
    verify that the matching KANON_SOURCE_<name>_{URL,REVISION,PATH} triple
    exists in .kanon. Missing triples produce one error finding per orphan.

    This function is pure: no stdout/stderr side effects.

    Args:
        kanon_file: Path to the .kanon file.
        lockfile: A Lockfile dataclass instance (from core/lockfile.py).

    Returns:
        List of DoctorFinding instances (empty when all sources are present).
    """
    from kanon_cli.core.kanonenv import parse_kanonenv

    parsed = parse_kanonenv(kanon_file)
    kanon_sources: set[str] = set(parsed["sources"].keys())

    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        if source.name not in kanon_sources:
            findings.append(
                DoctorFinding(
                    kind="error",
                    code="ORPHAN_LOCK",
                    message=(f"orphan lock entry: source '{source.name}' is in .kanon.lock but absent from .kanon"),
                    remediation=(
                        "Run 'kanon install' to prune (or 'kanon install --strict-lock' "
                        "to keep the lockfile authoritative)."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# RetryPolicy: shared named tuple for git ls-remote retry parameters
# ---------------------------------------------------------------------------


class RetryPolicy(NamedTuple):
    """Parameters controlling retry behaviour for git ls-remote calls.

    Attributes:
        timeout: Per-attempt timeout in seconds.
        retry_count: Maximum number of attempts (1 means no retries).
        retry_delay: Value read from ``KANON_GIT_RETRY_DELAY`` (seconds).
            Not applied to the ``git ls-remote`` retry path: the doctor
            delegates those calls to ``kanon_cli.core.git_runner.run_git_ls_remote``,
            which uses immediate retries with no inter-attempt delay (spec 3.5 /
            issue #64).
    """

    timeout: int
    retry_count: int
    retry_delay: float


def _read_retry_policy() -> RetryPolicy:
    """Read the git ls-remote retry policy from environment variables.

    Reads the three environment variables that govern the retry and timeout
    behaviour for all ``git ls-remote`` calls issued by ``kanon doctor``:

    - ``KANON_RESOLVE_TIMEOUT`` -- per-attempt timeout in seconds (default
      ``_KANON_RESOLVE_TIMEOUT_DEFAULT``).
    - ``KANON_GIT_RETRY_COUNT`` -- maximum number of attempts, 1 means no
      retries (default ``GIT_RETRY_COUNT_DEFAULT``).
    - ``KANON_GIT_RETRY_DELAY`` -- read from the environment (default
      ``GIT_RETRY_DELAY_DEFAULT``). Stored in ``RetryPolicy.retry_delay`` but
      NOT applied to the ``git ls-remote`` retry path: those calls delegate to
      ``kanon_cli.core.git_runner.run_git_ls_remote``, which performs immediate
      retries with no inter-attempt delay (spec 3.5 / issue #64).

    Extracting this into a factory keeps each call site DRY and makes it easy
    to override all three values in a single place for testing.

    Returns:
        A ``RetryPolicy`` named tuple populated from the current environment.
    """
    timeout = int(os.environ.get(_KANON_RESOLVE_TIMEOUT_ENV, str(_KANON_RESOLVE_TIMEOUT_DEFAULT)))
    retry_count = int(os.environ.get(GIT_RETRY_COUNT_ENV_VAR, str(GIT_RETRY_COUNT_DEFAULT)))
    retry_delay = float(os.environ.get(GIT_RETRY_DELAY_ENV_VAR, str(GIT_RETRY_DELAY_DEFAULT)))
    return RetryPolicy(timeout=timeout, retry_count=retry_count, retry_delay=retry_delay)


# ---------------------------------------------------------------------------
# Subcheck 4: Branch drift
# ---------------------------------------------------------------------------


def _check_branch_drift(
    lockfile: Lockfile,
    strict_drift: bool,
) -> list[DoctorFinding]:
    """Check branch-pinned sources for drift between locked SHA and current tip.

    Subcheck 4 in spec Section 4.6: For every lockfile entry whose ref_spec
    resolves to a branch ref (not a SHA, not refs/...), query
    ``git ls-remote refs/heads/<branch>`` against the source URL. When the
    branch tip SHA differs from the lockfile-recorded SHA:
    - Without ``--strict-drift``: emit an info-level finding.
    - With ``--strict-drift``: emit an error-level finding.

    SHA-pinned sources (40/64 hex-char ref_spec) are skipped.

    This function is pure: no stdout/stderr side effects.

    Args:
        lockfile: A Lockfile dataclass instance.
        strict_drift: When True, drift findings are promoted to error level.

    Returns:
        List of DoctorFinding instances (empty when no drift detected).
    """
    _policy = _read_retry_policy()

    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        if not _is_branch_revision(source.ref_spec):
            continue

        branch = source.ref_spec
        ref = f"refs/heads/{branch}"
        returncode, stdout, stderr = _run_ls_remote(
            url=source.url,
            ref=ref,
            timeout=_policy.timeout,
            retry_count=_policy.retry_count,
            retry_delay=_policy.retry_delay,
        )

        if returncode != 0:
            # Cannot query the remote -- skip (network issues are not drift errors)
            continue

        # Parse the SHA from ls-remote output: "<sha>\t<ref>\n"
        current_sha: str | None = None
        for line in stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                current_sha = parts[0].strip()
                break

        if current_sha is None:
            continue

        if current_sha != source.resolved_sha:
            kind = "error" if strict_drift else "info"
            findings.append(
                DoctorFinding(
                    kind=kind,
                    code="BRANCH_DRIFT",
                    message=(
                        f"branch drift: source '{source.name}' is locked to "
                        f"{source.resolved_sha[:12]} but '{branch}' is now at "
                        f"{current_sha[:12]}"
                    ),
                    remediation="Run 'kanon install --refresh-lock' to update the lockfile.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Subcheck 5: Dangling SHA
# ---------------------------------------------------------------------------


def _check_dangling_shas(
    lockfile: Lockfile,
) -> list[DoctorFinding]:
    """Check that every locked SHA is still reachable via git ls-remote.

    Subcheck 5 in spec Section 4.6: For every lockfile source entry, run
    ``git ls-remote <url>`` (no pattern) to list all remote refs, then
    search the first column of each line for the locked SHA. A SHA that
    does not appear in any ref's first column is considered dangling
    (force-pushed or pruned). A non-zero exit from git ls-remote is also
    treated as a dangling-SHA error.

    Note: ``git ls-remote --exit-code <url> <sha>`` is NOT used here
    because it matches against ref *names* (second column), not against
    SHA values (first column). A bare SHA will never match any ref name,
    causing every SHA to appear unreachable. The correct approach is to
    list all refs and search the first column, mirroring the strategy
    used by ``kanon install``'s ``_check_sha_reachable`` function.

    This function is pure: no stdout/stderr side effects.

    Args:
        lockfile: A Lockfile dataclass instance.

    Returns:
        List of DoctorFinding instances with kind=error for each dangling SHA.
    """
    _policy = _read_retry_policy()

    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        sha = source.resolved_sha
        # Skip branch-pinned sources: the locked SHA is an old branch tip that
        # may no longer be referenced by any remote ref even though the commit
        # still exists in the repo. Branch drift (subcheck 4) already covers
        # this case. The dangling SHA check is meaningful only for SHA-pinned
        # sources (40/64 hex-char ref_spec) where the operator intended to
        # lock a specific commit that must remain accessible.
        if _is_branch_revision(source.ref_spec):
            continue

        # Pass empty ref to list all refs -- needed because ls-remote only
        # matches on ref names (second column), not SHAs (first column).
        returncode, stdout, stderr = _run_ls_remote(
            url=source.url,
            ref="",
            timeout=_policy.timeout,
            retry_count=_policy.retry_count,
            retry_delay=_policy.retry_delay,
        )

        if returncode != 0:
            findings.append(
                DoctorFinding(
                    kind="error",
                    code="DANGLING_SHA",
                    message=(
                        f"dangling SHA: {sha} is no longer reachable from {source.url}; "
                        f"the remote may have force-pushed or pruned the commit."
                    ),
                    remediation="Run 'kanon install --refresh-lock' to rebuild.",
                )
            )
            continue

        # Search first column of each tab-delimited line for the locked SHA.
        sha_found = any(line.split("\t")[0] == sha for line in stdout.strip().splitlines() if "\t" in line)
        if not sha_found:
            findings.append(
                DoctorFinding(
                    kind="error",
                    code="DANGLING_SHA",
                    message=(
                        f"dangling SHA: {sha} is no longer reachable from {source.url}; "
                        f"the remote may have force-pushed or pruned the commit."
                    ),
                    remediation="Run 'kanon install --refresh-lock' to rebuild.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Subcheck 11: Remote reachability sanity check
# ---------------------------------------------------------------------------


def _check_remote_reachability(
    lockfile: "Lockfile",
    ls_remote_callable: Callable[[str, str, int, int, float], tuple[int, str, str]],
    retry_policy: RetryPolicy,
) -> list[DoctorFinding]:
    """Check that every distinct remote URL in the lockfile is reachable.

    Subcheck 11 in spec Section 4.6: For each distinct canonicalized URL
    recorded in the lockfile, run ``ls_remote_callable(url, 'HEAD', ...)``
    subject to ``retry_policy``. A non-zero exit code from any call produces
    a WARNING finding (not an error) including:
    - The canonicalized URL.
    - The exit code.
    - The first line of stderr truncated at
      ``KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS`` characters.
    - A remediation hint referencing ``docs/git-auth-setup.md``.

    Deduplication uses ``canonicalize_repo_url`` so that SSH and HTTPS forms
    of the same repository are treated as one remote.

    Auth-error patterns (``GIT_AUTH_ERROR_PATTERNS``) skip retries (enforced
    inside ``ls_remote_callable``) but still produce a warning finding.

    This function is pure: no stdout/stderr side effects.

    Args:
        lockfile: A Lockfile dataclass instance.
        ls_remote_callable: Callable with signature
            ``(url, ref, timeout, retry_count, retry_delay) -> (returncode, stdout, stderr)``.
            Unit tests inject a stub; production wires ``_run_ls_remote_exit_code``.
        retry_policy: Named tuple with timeout, retry_count, retry_delay fields.

    Returns:
        List of DoctorFinding instances with kind="warn" for each unreachable
        remote URL. Empty list when all remotes are reachable.
    """
    from kanon_cli.core.url import canonicalize_repo_url

    # Build a mapping from canonical URL -> raw URL (first occurrence wins).
    # Deduplication ensures each distinct remote is checked exactly once.
    # A URL that cannot be canonicalized is malformed; emit a warning finding
    # and skip it (it cannot be de-duplicated against other entries).
    seen: dict[str, str] = {}
    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        try:
            canonical = canonicalize_repo_url(source.url)
        except ValueError as exc:
            findings.append(
                DoctorFinding(
                    kind="warn",
                    code="REMOTE_URL_INVALID",
                    message=f"lockfile source '{source.name}' has an unrecognized URL format: {source.url!r} ({exc})",
                    remediation=(
                        "Update the lockfile source URL to use https:// or git@ (SCP) format. "
                        "See docs/git-auth-setup.md for supported URL schemes."
                    ),
                )
            )
            continue
        if canonical not in seen:
            seen[canonical] = source.url

    for canonical_url, raw_url in seen.items():
        returncode, _stdout, stderr = ls_remote_callable(
            raw_url,
            "HEAD",
            retry_policy.timeout,
            retry_policy.retry_count,
            retry_policy.retry_delay,
        )

        if returncode == 0:
            continue

        # Extract and truncate the first line of stderr.
        first_stderr_line = stderr.splitlines()[0] if stderr.strip() else ""
        stderr_preview = first_stderr_line[:KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS]

        findings.append(
            DoctorFinding(
                kind="warn",
                code="REMOTE_UNREACHABLE",
                message=(
                    f"remote unreachable: {canonical_url} "
                    f"(exit code {returncode})" + (f"; stderr: {stderr_preview}" if stderr_preview else "")
                ),
                remediation=(
                    f"Check network access and git credentials for {canonical_url}. "
                    f"See docs/git-auth-setup.md for SSH key and credential helper setup."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Subcheck 6: Effective catalog source resolution
# ---------------------------------------------------------------------------


def _check_effective_catalog_source(
    args: argparse.Namespace,
    env: dict[str, str],
    lockfile: "Lockfile | None",
) -> DoctorFinding:
    """Resolve and report the effective catalog source with its provenance.

    Implements subcheck 6 from spec Section 4.6: determines the effective
    catalog source by walking the precedence chain (first non-empty wins):

      1. ``--catalog-source`` CLI flag (highest precedence).
      2. The single source configured in the ``KANON_CATALOG_SOURCES`` env var.
      3. None (no catalog source configured).

    ``KANON_CATALOG_SOURCES`` (plural, spec Section 6 / FR-9) is a
    newline-delimited list; when it configures exactly one source that source is
    the effective value, and when it configures several the finding reports the
    ambiguity (single-source commands require ``--catalog-source`` to select one).

    Schema v4 (spec Section 5.2 / FR-7) removed the lockfile ``[catalog]`` block,
    so the lockfile no longer participates in catalog-source provenance.  The
    catalog source for ``kanon add`` / ``kanon list`` / ``kanon outdated`` /
    ``kanon why`` is supplied only by the CLI flag or the env var; ``kanon
    install`` is hermetic and does not consult a catalog source at all.

    This function is pure: it reads no global state directly. All inputs are
    passed as parameters to enable unit testing without environment mutation.

    The provenance suffix is mandatory in every output path -- without it an
    operator can read the effective value but cannot tell WHERE it came from.
    This is the primary mechanism for detecting ``KANON_CATALOG_SOURCES``
    leakage from a shell profile into an unrelated workspace (spec Section 3.6).

    Precedence disambiguation: ``args.catalog_source`` is set to the
    ``_UNSET`` sentinel by the argparse default when the user did not supply
    ``--catalog-source`` on the command line.  Any other value means the user
    explicitly supplied the flag; that value is attributed to the CLI flag
    regardless of whether the env var holds an identical string.

    Args:
        args: Parsed argument namespace. The ``catalog_source`` attribute is
            the ``_UNSET`` sentinel when the CLI flag was not supplied, or the
            user-supplied string when it was.
        env: The process environment dict (pass ``dict(os.environ)`` or a test
            substitute). Read-only: this function never mutates the dict.
        lockfile: Optional Lockfile object. Accepted for call-site symmetry with
            the other subchecks; the v4 lock carries no catalog source, so it does
            not participate in the precedence chain.

    Returns:
        A DoctorFinding with kind="info" whose message contains both the
        effective value and the provenance suffix.
    """
    raw_catalog_source = getattr(args, "catalog_source", _UNSET)
    cli_value: str | None = None if raw_catalog_source is _UNSET else str(raw_catalog_source)
    env_sources = parse_catalog_sources(env.get(CATALOG_SOURCES_ENV_VAR))

    # Determine provenance by walking the precedence chain.
    # CLI flag wins unambiguously: catalog_source is not the _UNSET sentinel
    # only when the user typed --catalog-source on the command line.
    if cli_value is not None:
        effective = cli_value
        provenance = "(from --catalog-source CLI flag)"
        message = f"Effective catalog source: {effective} {provenance}"
    elif len(env_sources) == 1:
        url, ref = env_sources[0]
        effective = f"{url}@{ref}"
        provenance = "(from KANON_CATALOG_SOURCES env var)"
        message = f"Effective catalog source: {effective} {provenance}"
    elif len(env_sources) > 1:
        rendered = ", ".join(f"{url}@{ref}" for url, ref in env_sources)
        provenance = "(from KANON_CATALOG_SOURCES env var)"
        message = (
            f"KANON_CATALOG_SOURCES configures {len(env_sources)} catalog sources "
            f"({rendered}) {provenance}; single-source commands require "
            "--catalog-source to select one."
        )
    else:
        provenance = "(none configured)"
        message = f"Effective catalog source: {provenance}; commands requiring a catalog source will fail."

    return DoctorFinding(
        kind="info",
        code="EFFECTIVE_CATALOG_SOURCE",
        message=message,
        remediation="",
    )


# ---------------------------------------------------------------------------
# Subcheck 7: Completion errors report
# ---------------------------------------------------------------------------


def _check_completion_errors_report(
    cache_dir: pathlib.Path,
    limit: int,
) -> DoctorFinding:
    """Read recent entries from the completion-errors log and produce a finding.

    Subcheck 7 in spec Section 4.6:
    - If ``${cache_dir}/completion-errors.log`` is absent or empty, return an
      info finding with code=NO_COMPLETION_ERRORS.
    - If present and non-empty, return a warn finding whose message contains
      the header "Recent completion errors (N):" followed by the last ``limit``
      lines verbatim. N equals min(total_lines, limit).

    This function is non-mutating: it never writes to, truncates, or rotates
    the log file.

    Args:
        cache_dir: Directory where the completion-errors log is stored.
            Typically the value of the KANON_CACHE_DIR environment variable.
        limit: Maximum number of recent log lines to include in the finding.

    Returns:
        A DoctorFinding with kind="info" when no errors are recorded, or
        kind="warn" when recent errors exist.
    """
    log_file = cache_dir / KANON_COMPLETION_ERRORS_LOG_FILENAME

    if not log_file.exists():
        return DoctorFinding(
            kind="info",
            code="NO_COMPLETION_ERRORS",
            message="no completion errors recorded",
            remediation="",
        )

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line]

    if not lines:
        return DoctorFinding(
            kind="info",
            code="NO_COMPLETION_ERRORS",
            message="no completion errors recorded",
            remediation="",
        )

    recent = lines[-limit:]
    count = len(recent)
    body = "\n".join(recent)
    message = f"Recent completion errors ({count}):\n{body}"

    return DoctorFinding(
        kind="warn",
        code="COMPLETION_ERRORS",
        message=message,
        remediation=f"Inspect {log_file} for details.",
    )


# ---------------------------------------------------------------------------
# Subcheck 9: Completion-script staleness
# ---------------------------------------------------------------------------


def _check_completion_script_staleness(
    search_paths: list[tuple[str, str]],
    completion_generator: Callable[[str], str],
) -> list[DoctorFinding]:
    """Check static completion scripts for staleness against a fresh generation.

    Subcheck 9 in spec Section 4.6: For each ``(shell, path)`` pair in
    ``search_paths``, if the file exists on disk, compute its SHA-256 hash
    and compare it to the SHA-256 hash of a freshly generated completion script
    for that shell. When the hashes differ, a warn-level finding is emitted
    naming the shell and the on-disk path.

    Files that do not exist are silently skipped (no finding emitted).
    In-sync files produce no finding.

    Args:
        search_paths: Sequence of (shell, path) pairs to inspect. Each path
            is checked independently. Multiple pairs may share the same shell
            name if the shell installs to multiple locations.
        completion_generator: Callable that accepts a shell name (e.g. "bash"
            or "zsh") and returns the completion script text for that shell.
            No subprocess is spawned; this callable runs in-process.

    Returns:
        List of DoctorFinding instances with kind="warn" for each stale script.
        Empty when no installed scripts are stale (or none are installed).
    """
    findings: list[DoctorFinding] = []

    for shell, path_str in search_paths:
        script_path = pathlib.Path(path_str)
        if not script_path.exists():
            continue

        on_disk_content = script_path.read_text(encoding="utf-8")
        on_disk_hash = hashlib.sha256(on_disk_content.encode("utf-8")).hexdigest()

        fresh_content = completion_generator(shell)
        fresh_hash = hashlib.sha256(fresh_content.encode("utf-8")).hexdigest()

        if on_disk_hash != fresh_hash:
            findings.append(
                DoctorFinding(
                    kind="warn",
                    code="STALE_COMPLETION_SCRIPT",
                    message=KANON_STALE_COMPLETION_SCRIPT_WARNING.format(
                        shell_name=shell,
                        path=path_str,
                    ),
                    remediation=f"kanon completion {shell} > {path_str}",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------


def _print_finding(finding: DoctorFinding) -> None:
    """Print a DoctorFinding to stderr.

    Info-level findings are printed with prefix ``INFO:``, warnings with
    ``WARN:``, and errors with ``ERROR:``. The remediation (if non-empty)
    is appended on the next line, indented.

    Args:
        finding: The finding to print.
    """
    prefix_map = {"info": "INFO", "warn": "WARN", "error": "ERROR"}
    prefix = prefix_map.get(finding.kind, "ERROR")
    print(f"{prefix}: {finding.message}", file=sys.stderr)
    if finding.remediation:
        print(f"  Remediation: {finding.remediation}", file=sys.stderr)


_FINDING_PREFIX_MAP: dict[str, str] = {
    FINDING_SEVERITY_OK: FINDING_PREFIX_OK,
    FINDING_SEVERITY_FAIL: FINDING_PREFIX_FAIL,
    FINDING_SEVERITY_INFO: FINDING_PREFIX_INFO,
}


def _print_structured_finding(finding: Finding, quiet: bool = False) -> None:
    """Print a structured Finding to stdout per the severity-to-prefix map.

    Format:
      - ok   -> "[ok] <name>"
      - fail -> "[fail] <name>: <reason>"
      - info -> "[info] <name>" or "[info] <name>: <reason>" when reason is set

    When ``quiet`` is True, INFO-level findings are suppressed (not printed).

    Args:
        finding: The Finding to print.
        quiet: When True, INFO-severity findings are suppressed.
    """
    if quiet and finding.severity == FINDING_SEVERITY_INFO:
        return
    prefix = _FINDING_PREFIX_MAP[finding.severity]
    if finding.reason:
        print(f"{prefix} {finding.name}: {finding.reason}")
    else:
        print(f"{prefix} {finding.name}")


def _emit_subcheck_result(
    subcheck_name: str,
    doctor_findings: list[DoctorFinding],
    quiet: bool,
) -> bool:
    """Emit the structured Finding for a multi-result subcheck and return whether errors exist.

    Iterates the DoctorFinding list via _print_finding (for detailed diagnostics to
    stderr), then emits a single structured Finding on stdout summarizing the outcome:
      - Any error-level DoctorFinding -> Finding(fail, <name>, reason=<first error message>)
      - No error-level DoctorFindings -> Finding(ok, <name>)

    Args:
        subcheck_name: The subcheck identifier constant (e.g. DOCTOR_SUBCHECK_ORPHAN_LOCKS).
        doctor_findings: List of DoctorFinding objects returned by the subcheck handler.
        quiet: Passed through to _print_structured_finding for INFO suppression.

    Returns:
        True if any error-level DoctorFinding was present; False otherwise.
    """
    first_error: DoctorFinding | None = None
    for df in doctor_findings:
        _print_finding(df)
        if df.kind == "error" and first_error is None:
            first_error = df
    if first_error is not None:
        _print_structured_finding(
            Finding(
                severity=FINDING_SEVERITY_FAIL,
                name=subcheck_name,
                reason=first_error.message,
            ),
            quiet=quiet,
        )
        return True
    _print_structured_finding(
        Finding(severity=FINDING_SEVERITY_OK, name=subcheck_name),
        quiet=quiet,
    )
    return False


# ---------------------------------------------------------------------------
# Completion subchecks runner (7 + 9)
# ---------------------------------------------------------------------------


def _run_completion_subchecks(
    completion_generator: Callable[[str], str] | None,
) -> None:
    """Run completion subchecks 7 and 9, printing findings to stderr.

    Subcheck 7 reads the completion-errors log from the KANON_CACHE_DIR when
    that environment variable is set. Subcheck 9 checks static completion
    scripts for staleness when a completion_generator is provided.

    Both subchecks always run when invoked (no flag gates). This function
    encapsulates their logic so both the normal and NO_LOCKFILE code paths
    in doctor_command can call it without duplication.

    Args:
        completion_generator: Optional callable for subcheck 9. When None,
            the staleness check is skipped.
    """
    # -- Check 7: completion errors report --
    cache_dir_str = os.environ.get(KANON_CACHE_DIR_ENV)
    if cache_dir_str is not None:
        errors_finding = _check_completion_errors_report(
            pathlib.Path(cache_dir_str),
            limit=KANON_COMPLETION_ERRORS_REPORT_LIMIT,
        )
        _print_finding(errors_finding)

    # -- Check 9: completion-script staleness --
    if completion_generator is not None:
        staleness_findings = _check_completion_script_staleness(
            search_paths=list(KANON_STATIC_COMPLETION_SEARCH_PATHS),
            completion_generator=completion_generator,
        )
        for finding in staleness_findings:
            _print_finding(finding)


# ---------------------------------------------------------------------------
# doctor_command -- main entrypoint for 'kanon doctor' (checks 1-5, 7, 9)
# ---------------------------------------------------------------------------


def doctor_command(
    args: argparse.Namespace,
    completion_generator: Callable[[str], str] | None = None,
    now: Callable[[], datetime.datetime] | None = None,
) -> int:
    """Entry-point for 'kanon doctor' implementing subchecks 1-5, 7-11.

    Orchestrates the consistency checks in order. Prints findings to
    stderr via _print_finding. Returns exit code 0 unless at least one
    finding with kind="error" is found.

    Check 8 (--refresh-completion-cache) runs first when the flag is set.
    Check 10 (--prune-cache) runs next when the flag is set.

    Check 1 (kanon_hash / lockfile presence):
    - .kanon absent: hard error, return immediately.
    - .kanon.lock absent: info notice to stderr; skip checks 2-5 and 11;
      return 0.

    Checks 2-5 and 11 are only run when both files are present and the
    hash is valid.

    Check 7 runs when KANON_CACHE_DIR is set in the environment.

    Check 9 runs when completion_generator is provided (not None).

    Check 10 (--prune-cache) also emits an advisory for stale install
    locks found under the cwd up to KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH.

    Check 11 runs for every distinct canonicalized remote URL recorded in
    the lockfile. Findings are always warning-level (never error-level);
    the command still exits 0 when only check 11 produces findings.

    Args:
        args: Parsed argument namespace from argparse. Expected attributes:
            - kanon_file (str | None): path to .kanon file.
            - lock_file (str | None): path to .kanon.lock file.
            - strict_drift (bool): promote drift findings to errors.
            - no_color (bool): suppress ANSI color (passed through from
              global flags).
            - refresh_completion_cache (bool): subcheck 8 flag.
            - prune_cache (bool): subcheck 10 flag.
        completion_generator: Optional callable accepting a shell name and
            returning the completion script text for that shell. When
            provided, subcheck 9 (static-script staleness) is executed.
            When None, subcheck 9 is skipped.
        now: Optional callable returning the current UTC datetime. When None,
            defaults to ``datetime.datetime.now(tz=datetime.timezone.utc)``.
            Tests inject a fixed value to avoid wall-clock dependencies.

    Returns:
        0 on success (no error-level findings); 1 when any error is found.
    """
    if now is None:

        def now() -> datetime.datetime:
            return datetime.datetime.now(tz=datetime.timezone.utc)

    kanon_file_str: str | None = getattr(args, "kanon_file", None) or os.environ.get(KANON_KANON_FILE_ENV)
    if kanon_file_str is None:
        kanon_file_str = KANON_KANON_FILE_DEFAULT

    lock_file_override: str | None = getattr(args, "lock_file", None) or os.environ.get(KANON_LOCK_FILE)

    from kanon_cli.utils.lock_file_path import derive_lock_file_path

    kanon_file = pathlib.Path(kanon_file_str)
    lock_file = derive_lock_file_path(
        kanon_file,
        cli_lock_file=pathlib.Path(lock_file_override) if lock_file_override else None,
        env_lock_file=os.environ.get(KANON_LOCK_FILE),
    )

    strict_drift: bool = getattr(args, "strict_drift", False)
    do_refresh: bool = getattr(args, "refresh_completion_cache", False)
    do_prune: bool = getattr(args, "prune_cache", False)

    # Resolve cache_dir from environment (used by subchecks 7, 8, 10).
    cache_dir_str: str | None = os.environ.get(KANON_CACHE_DIR_ENV)
    cache_dir: pathlib.Path | None = pathlib.Path(cache_dir_str) if cache_dir_str is not None else None

    # -- Check 8: completion-cache invalidation (--refresh-completion-cache) --
    if do_refresh and cache_dir is not None:
        completion_cache_dir = cache_dir / KANON_COMPLETION_CACHE_DIR
        try:
            removed = _refresh_completion_cache(completion_cache_dir)
        except OSError as exc:
            print(f"ERROR: Failed to refresh completion cache: {exc}", file=sys.stderr)
            return 1
        _print_finding(
            DoctorFinding(
                kind="info",
                code="COMPLETION_CACHE_REFRESHED",
                message=f"Completion cache refreshed: {removed} file(s) removed from {completion_cache_dir}",
                remediation="",
            )
        )

    # -- Check 10a: cache prune (--prune-cache) --
    if do_prune and cache_dir is not None:
        age_days = KANON_CACHE_PRUNE_AGE_DAYS
        count_pruned, total_bytes = _prune_cache(cache_dir, age_days, now)
        _print_finding(
            DoctorFinding(
                kind="info",
                code="CACHE_PRUNED",
                message=(
                    f"Cache pruned: {count_pruned} file(s) removed "
                    f"({total_bytes} bytes) with atime older than {age_days} days"
                ),
                remediation="",
            )
        )

    # -- Check 10b: stale install-lock advisory (--prune-cache) --
    if do_prune:
        stale_locks = list(
            _scan_stale_install_locks(
                root=pathlib.Path.cwd(),
                max_depth=KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH,
                age_hours=KANON_DOCTOR_STALE_LOCK_AGE_HOURS,
                now=now,
            )
        )
        for lock_path in stale_locks:
            _print_finding(
                DoctorFinding(
                    kind="info",
                    code="STALE_INSTALL_LOCK",
                    message=(
                        f"Advisory: stale install lock found at {lock_path} "
                        f"(mtime older than {KANON_DOCTOR_STALE_LOCK_AGE_HOURS}h). "
                        f"fcntl.flock self-cleans on process exit; this file is harmless."
                    ),
                    remediation="",
                )
            )

    # -- Short-circuit for workspace-free flags --
    # When only workspace-free flags (e.g. --refresh-completion-cache,
    # --prune-cache) are active, skip all workspace-dependent checks and return
    # 0 immediately. Mixed invocations (cache flag + any subcheck flag) fall
    # through to the full workspace-dependent path below.
    #
    # active_flag_names uses `value is True` (not just `if value`) to exclude
    # non-boolean attributes injected by argparse set_defaults(): catalog_source
    # is set to the _UNSET sentinel object (truthy but not True) and func is
    # set to run_doctor (a callable, also truthy but not True). Using `if value`
    # caused those attributes to be included in active_flag_names, which
    # prevented the subset check from firing and caused _check_kanon_hash to
    # be reached even when only cache flags were active (DEFECT-013).
    if not isinstance(args, argparse.Namespace):
        raise DoctorArgsTypeError(type(args))
    active_flag_names = {name for name, value in vars(args).items() if value is True}
    if active_flag_names and active_flag_names.issubset(WORKSPACE_FREE_FLAGS):
        return 0

    quiet: bool = bool(getattr(args, "quiet", False))

    # -- Check 1: .kanon / .kanon.lock presence + hash match --
    consistency_finding = _check_kanon_hash(kanon_file, lock_file)

    if consistency_finding is not None:
        if consistency_finding.code == "NO_KANON":
            _print_finding(consistency_finding)
            _print_structured_finding(
                Finding(
                    severity=FINDING_SEVERITY_FAIL,
                    name=DOCTOR_SUBCHECK_KANON_HASH,
                    reason=consistency_finding.message,
                ),
                quiet=quiet,
            )
            return 1

        if consistency_finding.code == "NO_LOCKFILE":
            _print_finding(consistency_finding)
            # Lockfile absent: run subchecks 6, 7, 9 with no lockfile; skip 2-5 and 11.
            source_finding = _check_effective_catalog_source(args, dict(os.environ), None)
            print(source_finding.message)
            _run_completion_subchecks(completion_generator)
            return 0

        if consistency_finding.code == "HASH_MISMATCH":
            _print_finding(consistency_finding)
            _print_structured_finding(
                Finding(
                    severity=FINDING_SEVERITY_FAIL,
                    name=DOCTOR_SUBCHECK_KANON_HASH,
                    reason=consistency_finding.message,
                ),
                quiet=quiet,
            )
            return 1

        if consistency_finding.code == "NO_SOURCES":
            # Zero-source .kanon: invalid workspace. Report the structured
            # finding and exit non-zero; subchecks 2-5/11 cannot run without
            # any source to inspect.
            _print_finding(consistency_finding)
            _print_structured_finding(
                Finding(
                    severity=FINDING_SEVERITY_FAIL,
                    name=DOCTOR_SUBCHECK_KANON_HASH,
                    reason=consistency_finding.message,
                ),
                quiet=quiet,
            )
            return 1

    # Subcheck 1 passed -- emit structured ok finding.
    _print_structured_finding(
        Finding(severity=FINDING_SEVERITY_OK, name=DOCTOR_SUBCHECK_KANON_HASH),
        quiet=quiet,
    )

    # Hash matched -- load the lockfile and run checks 3-5 and 6.
    from kanon_cli.core.lockfile import read_lockfile

    lockfile = read_lockfile(lock_file)

    has_errors = False

    # -- Check 3: orphan lock entries --
    orphan_findings = _check_orphan_locks(kanon_file, lockfile)
    if _emit_subcheck_result(DOCTOR_SUBCHECK_ORPHAN_LOCKS, orphan_findings, quiet):
        has_errors = True

    # -- Check 4: branch drift --
    drift_findings = _check_branch_drift(lockfile, strict_drift=strict_drift)
    if _emit_subcheck_result(DOCTOR_SUBCHECK_BRANCH_DRIFT, drift_findings, quiet):
        has_errors = True

    # -- Check 5: dangling SHA --
    dangling_findings = _check_dangling_shas(lockfile)
    for finding in dangling_findings:
        _print_finding(finding)
        if finding.kind == "error":
            has_errors = True

    # -- Check 11: remote reachability sanity check --
    remote_findings = _check_remote_reachability(
        lockfile,
        _run_ls_remote_exit_code,
        _read_retry_policy(),
    )
    for finding in remote_findings:
        _print_finding(finding)
        # Remote-reachability findings are always warnings -- they never set has_errors.

    # -- Check 6: effective catalog source --
    source_finding = _check_effective_catalog_source(args, dict(os.environ), lockfile)
    print(source_finding.message)

    # -- Checks 7 + 9: completion errors and script staleness --
    _run_completion_subchecks(completion_generator)

    return 1 if has_errors else 0


# ---------------------------------------------------------------------------
# register -- argparse subcommand registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'doctor' subcommand on the top-level argparse subparsers.

    Adds the 'doctor' subparser with flags consumed by subchecks 1-5, 8, 10:
    - ``--kanon-file``: path to .kanon (default KANON_KANON_FILE_DEFAULT).
    - ``--lock-file``: path to .kanon.lock (default derived from --kanon-file).
    - ``--strict-drift``: promote branch-drift findings to errors.
    - ``--no-color``: suppress ANSI color output.
    - ``--refresh-completion-cache``: subcheck 8 -- invalidate completion-cache subdir.
    - ``--prune-cache``: subcheck 10 -- remove stale cache files by atime.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "doctor",
        add_help=True,
        help="Workspace health checks and cache management.",
        description=(
            "Run workspace health checks against the current project directory.\n\n"
            "Subchecks:\n"
            "  1. .kanon / .kanon.lock consistency via kanon_hash\n"
            "  2. Hand-edit detection (kanon_hash mismatch)\n"
            "  3. Orphaned lock entries\n"
            "  4. Branch drift (use --strict-drift to promote to error)\n"
            "  5. Dangling SHA detection\n"
            "  8. Completion-cache invalidation (--refresh-completion-cache)\n"
            " 10. Stale cache pruning + stale-lock advisory (--prune-cache)\n"
            " 11. Remote reachability sanity check (warning only; exit 0)\n\n"
            "With --refresh-completion-cache, invalidates the completion-cache subdir\n"
            "under KANON_CACHE_DIR. With --prune-cache, removes cache files whose\n"
            "atime exceeds KANON_CACHE_PRUNE_AGE_DAYS days and reports stale\n"
            "install-lock files as an advisory (does not delete them).\n"
            "Both flags are independent and may be combined."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=None,
        metavar="<path>",
        help=(
            f"Path to the .kanon file that identifies the workspace root. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--lock-file",
        dest="lock_file",
        default=None,
        metavar="<path>",
        help=(
            "Path to the .kanon.lock lockfile. "
            "Defaults to '<kanon-file>.lock' (e.g. ./.kanon.lock). "
            f"Overridden by the {KANON_LOCK_FILE} environment variable."
        ),
    )

    parser.add_argument(
        "--strict-drift",
        dest="strict_drift",
        action="store_true",
        default=False,
        help=(
            "Promote branch-drift findings from info-level to error-level. "
            "With this flag, kanon doctor returns exit code 1 when any "
            "branch-pinned source's tip SHA differs from the locked SHA."
        ),
    )

    parser.add_argument(
        "--refresh-completion-cache",
        dest="refresh_completion_cache",
        action="store_true",
        default=False,
        help=(
            "Subcheck 8: invalidate the shell completion cache under "
            "${KANON_CACHE_DIR}/completion-cache/. "
            "Removes all files there and recreates the directory with mode 0700. "
            "Reports an info finding with the count of files removed."
        ),
    )

    parser.add_argument(
        "--prune-cache",
        dest="prune_cache",
        action="store_true",
        default=False,
        help=(
            f"Subcheck 10: remove cache files under ${{KANON_CACHE_DIR}} whose last-access "
            f"time is older than KANON_CACHE_PRUNE_AGE_DAYS days (default {KANON_CACHE_PRUNE_AGE_DAYS}). "
            "Reports an info finding with the count and total byte size pruned. "
            "Also reports stale .kanon-data/.kanon-install.lock files as advisory "
            "(does not delete them)."
        ),
    )

    # Delegate --catalog-source registration to the shared factory (DRY).
    # Then override the default to _UNSET so _check_effective_catalog_source
    # can distinguish a CLI-supplied value from the argparse-injected default.
    # The env-var fallback baked in by add_catalog_source_arg's default= would
    # conflate CLI-absent with env-var-present, breaking provenance tracking.
    add_catalog_source_arg(parser)
    parser.set_defaults(catalog_source=_UNSET)

    parser.set_defaults(func=run_doctor)


# ---------------------------------------------------------------------------
# run_doctor -- registered CLI entrypoint for 'kanon doctor'
# ---------------------------------------------------------------------------


def run_doctor(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon doctor' subcommand.

    Delegates to doctor_command, which handles all flags including
    --refresh-completion-cache (subcheck 8) and --prune-cache (subcheck 10).

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure.
    """
    return doctor_command(args)


# ---------------------------------------------------------------------------
# Subcheck 8: _refresh_completion_cache -- completion cache refresh helper
# ---------------------------------------------------------------------------


def _refresh_completion_cache(cache_dir: pathlib.Path) -> int:
    """Invalidate the completion-cache directory and return the count of files removed.

    Removes the entire ``cache_dir`` tree (including any subdirectories), then
    recreates the directory with mode ``0700``.

    When ``cache_dir`` does not exist, it is created with mode ``0700`` and 0
    is returned.

    Args:
        cache_dir: Path to the completion-cache directory to invalidate.
            Typically ``${KANON_CACHE_DIR}/completion-cache``.

    Returns:
        The number of files that were removed.
    """
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, mode=KANON_CACHE_DIR_MODE)
        return 0

    # Count all files recursively before removal.
    removed = sum(1 for child in cache_dir.rglob("*") if child.is_file())

    # Remove the entire directory tree and recreate it empty with mode 0700.
    shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, mode=KANON_CACHE_DIR_MODE)

    return removed


# ---------------------------------------------------------------------------
# Subcheck 10: _prune_cache -- age-based cache prune helper
# ---------------------------------------------------------------------------


def _prune_cache(
    cache_dir: pathlib.Path,
    age_days: int,
    now: Callable[[], datetime.datetime],
) -> tuple[int, int]:
    """Remove cache files whose atime is older than ``age_days`` days.

    Walks all files under ``cache_dir`` recursively and removes those whose
    atime falls before ``now() - timedelta(days=age_days)``.

    When ``cache_dir`` does not exist, returns (0, 0) immediately.

    Args:
        cache_dir: Top-level cache directory to prune.
        age_days: Files whose atime is older than this many days are removed.
        now: Zero-argument callable returning the current datetime (with
            timezone info). Injected so tests can pin time without relying on
            wall-clock behaviour.

    Returns:
        A tuple ``(count_pruned, total_bytes)`` where ``count_pruned`` is the
        number of files deleted and ``total_bytes`` is their combined size in
        bytes.
    """
    if not cache_dir.exists():
        return (0, 0)

    cutoff = now() - datetime.timedelta(days=age_days)
    count_pruned = 0
    total_bytes = 0

    for child in list(cache_dir.rglob("*")):
        if not child.is_file():
            continue
        try:
            file_stat = child.stat()
        except OSError as exc:
            print(f"WARN: Cannot stat {child}: {exc}", file=sys.stderr)
            continue
        atime = datetime.datetime.fromtimestamp(file_stat.st_atime, tz=datetime.timezone.utc)
        if atime < cutoff:
            try:
                child.unlink()
            except OSError as exc:
                print(f"WARN: Cannot remove {child}: {exc}", file=sys.stderr)
                continue
            total_bytes += file_stat.st_size
            count_pruned += 1

    return (count_pruned, total_bytes)


# ---------------------------------------------------------------------------
# Subcheck 10: _scan_stale_install_locks -- advisory stale-lock scanner
# ---------------------------------------------------------------------------


def _scan_stale_install_locks(
    root: pathlib.Path,
    max_depth: int,
    age_hours: int,
    now: Callable[[], datetime.datetime],
) -> Iterator[pathlib.Path]:
    """Yield paths of stale ``.kanon-data/.kanon-install.lock`` files.

    Walks ``root`` up to ``max_depth`` directory levels deep looking for
    ``<any-dir>/.kanon-data/.kanon-install.lock`` files whose mtime is older
    than ``age_hours`` hours. Stale lock files are reported as advisory
    findings; this function does NOT delete them.

    Args:
        root: Directory from which to start the scan. Typically the current
            working directory.
        max_depth: Maximum number of levels to descend below ``root``.
            A value of 4 means root itself (depth 0) plus four more levels.
        age_hours: Locks whose mtime is older than this many hours are stale.
        now: Zero-argument callable returning the current datetime (with
            timezone info). Injected so tests can pin time.

    Yields:
        Absolute Path of each stale lock file found.
    """
    cutoff = now() - datetime.timedelta(hours=age_hours)

    def _walk(directory: pathlib.Path, current_depth: int) -> Iterator[pathlib.Path]:
        """Recursively walk directory up to max_depth.

        Args:
            directory: Current directory being examined.
            current_depth: Depth level from root (root == 0).

        Yields:
            Stale lock file paths.
        """
        candidate = directory / ".kanon-data" / INSTALL_LOCK_FILENAME
        if candidate.is_file():
            try:
                mtime = datetime.datetime.fromtimestamp(candidate.stat().st_mtime, tz=datetime.timezone.utc)
                if mtime < cutoff:
                    yield candidate
            except OSError as exc:
                print(f"WARN: Cannot stat {candidate}: {exc}", file=sys.stderr)

        if current_depth >= max_depth:
            return

        try:
            children = list(directory.iterdir())
        except OSError as exc:
            print(f"WARN: Cannot list {directory}: {exc}", file=sys.stderr)
            return

        for child in children:
            if child.is_dir():
                yield from _walk(child, current_depth + 1)

    yield from _walk(root, 0)
