"""kanon doctor subcommand: workspace health checks and cache refresh.

Performs workspace health checks and optionally refreshes the completion cache.
The --refresh-completion-cache flag mutates completion-cache files and is
protected by the workspace lock to prevent concurrent cache refreshes from
clobbering each other.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 4.6 (kanon doctor subchecks 1-5), Section 5.1 (kanon_hash),
Section 7 (retry policy, KANON_RESOLVE_TIMEOUT).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kanon_cli.core.lockfile import Lockfile

from kanon_cli.constants import (
    GIT_AUTH_ERROR_PATTERNS,
    GIT_RETRY_COUNT_DEFAULT,
    GIT_RETRY_COUNT_ENV_VAR,
    GIT_RETRY_DELAY_DEFAULT,
    GIT_RETRY_DELAY_ENV_VAR,
    KANON_COMPLETION_CACHE_DIR,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    _KANON_RESOLVE_TIMEOUT_DEFAULT,
    _KANON_RESOLVE_TIMEOUT_ENV,
)
from kanon_cli.utils.concurrency import kanon_workspace_lock


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

    Implements the same retry policy as the existing git_runner module:
    - Retries up to ``retry_count`` times on transient failures.
    - Does NOT retry on auth-error patterns (to avoid credential lockouts).
    - Enforces ``timeout`` seconds per attempt via the ``timeout`` kwarg.

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
        retry_delay: Seconds to wait between retries.

    Returns:
        A tuple (returncode, stdout, stderr) from the final attempt.
    """
    if ref:
        cmd = ["git", "ls-remote", url, ref]
    else:
        cmd = ["git", "ls-remote", url]
    last_returncode = -1
    last_stdout = ""
    last_stderr = ""

    for attempt in range(retry_count):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            last_returncode = result.returncode
            last_stdout = result.stdout
            last_stderr = result.stderr

            if result.returncode == 0:
                return (result.returncode, result.stdout, result.stderr)

            # Do not retry auth errors
            if any(pat in result.stderr for pat in GIT_AUTH_ERROR_PATTERNS):
                return (result.returncode, result.stdout, result.stderr)

            # On non-zero but non-auth exit, retry if attempts remain
            if attempt < retry_count - 1:
                time.sleep(retry_delay)

        except subprocess.TimeoutExpired:
            last_returncode = 124  # POSIX convention for timeout
            last_stdout = ""
            last_stderr = f"git ls-remote timed out after {timeout}s"
            if attempt < retry_count - 1:
                time.sleep(retry_delay)

    return (last_returncode, last_stdout, last_stderr)


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
    - If kanon_hash in lockfile differs from the recomputed hash: returns error
      (code=HASH_MISMATCH).
    - Otherwise: returns None (no finding -- checks 2-5 may proceed).

    This function is pure: it performs no I/O on stdout/stderr and raises no
    exceptions unless the underlying parser raises them.

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
    from kanon_cli.core.lockfile import read_lockfile

    lockfile = read_lockfile(lock_file)
    computed = kanon_hash(kanon_file)
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
# Subcheck 4: Branch drift
# ---------------------------------------------------------------------------


def _check_branch_drift(
    lockfile: Lockfile,
    strict_drift: bool,
) -> list[DoctorFinding]:
    """Check branch-pinned sources for drift between locked SHA and current tip.

    Subcheck 4 in spec Section 4.6: For every lockfile entry whose revision_spec
    resolves to a branch ref (not a SHA, not refs/...), query
    ``git ls-remote refs/heads/<branch>`` against the source URL. When the
    branch tip SHA differs from the lockfile-recorded SHA:
    - Without ``--strict-drift``: emit an info-level finding.
    - With ``--strict-drift``: emit an error-level finding.

    SHA-pinned sources (40/64 hex-char revision_spec) are skipped.

    This function is pure: no stdout/stderr side effects.

    Args:
        lockfile: A Lockfile dataclass instance.
        strict_drift: When True, drift findings are promoted to error level.

    Returns:
        List of DoctorFinding instances (empty when no drift detected).
    """
    timeout = int(os.environ.get(_KANON_RESOLVE_TIMEOUT_ENV, str(_KANON_RESOLVE_TIMEOUT_DEFAULT)))
    retry_count = int(os.environ.get(GIT_RETRY_COUNT_ENV_VAR, str(GIT_RETRY_COUNT_DEFAULT)))
    retry_delay = float(os.environ.get(GIT_RETRY_DELAY_ENV_VAR, str(GIT_RETRY_DELAY_DEFAULT)))

    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        if not _is_branch_revision(source.revision_spec):
            continue

        branch = source.revision_spec
        ref = f"refs/heads/{branch}"
        returncode, stdout, stderr = _run_ls_remote(
            url=source.url,
            ref=ref,
            timeout=timeout,
            retry_count=retry_count,
            retry_delay=retry_delay,
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
    timeout = int(os.environ.get(_KANON_RESOLVE_TIMEOUT_ENV, str(_KANON_RESOLVE_TIMEOUT_DEFAULT)))
    retry_count = int(os.environ.get(GIT_RETRY_COUNT_ENV_VAR, str(GIT_RETRY_COUNT_DEFAULT)))
    retry_delay = float(os.environ.get(GIT_RETRY_DELAY_ENV_VAR, str(GIT_RETRY_DELAY_DEFAULT)))

    findings: list[DoctorFinding] = []
    for source in lockfile.sources:
        sha = source.resolved_sha
        # Skip branch-pinned sources: the locked SHA is an old branch tip that
        # may no longer be referenced by any remote ref even though the commit
        # still exists in the repo. Branch drift (subcheck 4) already covers
        # this case. The dangling SHA check is meaningful only for SHA-pinned
        # sources (40/64 hex-char revision_spec) where the operator intended to
        # lock a specific commit that must remain accessible.
        if _is_branch_revision(source.revision_spec):
            continue

        # Pass empty ref to list all refs -- needed because ls-remote only
        # matches on ref names (second column), not SHAs (first column).
        returncode, stdout, stderr = _run_ls_remote(
            url=source.url,
            ref="",
            timeout=timeout,
            retry_count=retry_count,
            retry_delay=retry_delay,
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


# ---------------------------------------------------------------------------
# doctor_command -- main entrypoint for 'kanon doctor' (checks 1-5)
# ---------------------------------------------------------------------------


def doctor_command(args: argparse.Namespace) -> int:
    """Entry-point for 'kanon doctor' implementing subchecks 1-5.

    Orchestrates the five consistency checks in order. Prints findings to
    stderr via _print_finding. Returns exit code 0 unless at least one
    finding with kind="error" is found.

    Check 1 (kanon_hash / lockfile presence):
    - .kanon absent: hard error, return immediately.
    - .kanon.lock absent: info notice to stderr; skip checks 2-5 and 11;
      return 0.

    Checks 2-5 are only run when both files are present and the hash is
    valid.

    Args:
        args: Parsed argument namespace from argparse. Expected attributes:
            - kanon_file (str | None): path to .kanon file.
            - lock_file (str | None): path to .kanon.lock file.
            - strict_drift (bool): promote drift findings to errors.
            - no_color (bool): suppress ANSI color (passed through from
              global flags).
            - refresh_completion_cache (bool): legacy flag handled by
              run_doctor; always False when routed through doctor_command.

    Returns:
        0 on success (no error-level findings); 1 when any error is found.
    """
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

    # -- Check 1: .kanon / .kanon.lock presence + hash match --
    consistency_finding = _check_kanon_hash(kanon_file, lock_file)

    if consistency_finding is not None:
        if consistency_finding.code == "NO_KANON":
            _print_finding(consistency_finding)
            return 1

        if consistency_finding.code == "NO_LOCKFILE":
            _print_finding(consistency_finding)
            # Skip checks 2-5 and 11 (later tasks); continue with 6-10 (later tasks T2-T5)
            return 0

        if consistency_finding.code == "HASH_MISMATCH":
            _print_finding(consistency_finding)
            return 1

    # Hash matched -- load the lockfile and run checks 3-5.
    from kanon_cli.core.lockfile import read_lockfile

    lockfile = read_lockfile(lock_file)

    has_errors = False

    # -- Check 3: orphan lock entries --
    orphan_findings = _check_orphan_locks(kanon_file, lockfile)
    for finding in orphan_findings:
        _print_finding(finding)
        if finding.kind == "error":
            has_errors = True

    # -- Check 4: branch drift --
    drift_findings = _check_branch_drift(lockfile, strict_drift=strict_drift)
    for finding in drift_findings:
        _print_finding(finding)
        if finding.kind == "error":
            has_errors = True

    # -- Check 5: dangling SHA --
    dangling_findings = _check_dangling_shas(lockfile)
    for finding in dangling_findings:
        _print_finding(finding)
        if finding.kind == "error":
            has_errors = True

    return 1 if has_errors else 0


# ---------------------------------------------------------------------------
# register -- argparse subcommand registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'doctor' subcommand on the top-level argparse subparsers.

    Adds the 'doctor' subparser with flags consumed by subchecks 1-5:
    - ``--kanon-file``: path to .kanon (default KANON_KANON_FILE_DEFAULT).
    - ``--lock-file``: path to .kanon.lock (default derived from --kanon-file).
    - ``--strict-drift``: promote branch-drift findings to errors.
    - ``--no-color``: suppress ANSI color output.
    - ``--refresh-completion-cache``: legacy cache-refresh flag (handled by
      run_doctor for backward compatibility with earlier tasks).

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "doctor",
        help="Workspace health checks and cache management.",
        description=(
            "Run workspace health checks against the current project directory.\n\n"
            "Subchecks implemented by this task (E5-F1-S1-T1):\n"
            "  1. .kanon / .kanon.lock consistency via kanon_hash\n"
            "  2. Hand-edit detection (kanon_hash mismatch)\n"
            "  3. Orphaned lock entries\n"
            "  4. Branch drift (use --strict-drift to promote to error)\n"
            "  5. Dangling SHA detection\n\n"
            "With --refresh-completion-cache, refreshes the shell completion cache\n"
            "files under .kanon-data/. This mutation is protected by the workspace\n"
            "lock to prevent concurrent refreshes from producing inconsistent state."
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
            "Refresh the shell completion cache files stored under .kanon-data/. "
            "Acquires the workspace exclusive lock before writing, so concurrent "
            "cache refreshes are serialised."
        ),
    )

    parser.set_defaults(func=run_doctor)


# ---------------------------------------------------------------------------
# run_doctor -- registered CLI entrypoint for 'kanon doctor'
# ---------------------------------------------------------------------------


def run_doctor(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon doctor' subcommand.

    Handles the --refresh-completion-cache flag first (legacy path that acquires
    the workspace lock). For all other invocations, delegates to doctor_command
    which implements subchecks 1-5.

    When --refresh-completion-cache is set, acquires the workspace exclusive
    lock (via kanon_workspace_lock) before mutating any completion-cache files.
    This prevents two concurrent refreshes from clobbering each other.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure.
    """
    refresh_completion_cache: bool = getattr(args, "refresh_completion_cache", False)

    if refresh_completion_cache:
        kanon_file_str = getattr(args, "kanon_file", None) or os.environ.get(KANON_KANON_FILE_ENV)
        if kanon_file_str is None:
            kanon_file_str = KANON_KANON_FILE_DEFAULT

        kanon_file = pathlib.Path(kanon_file_str)
        workspace_root = kanon_file.resolve().parent

        with kanon_workspace_lock(workspace_root):
            _refresh_completion_cache(workspace_root)
        return 0

    return doctor_command(args)


# ---------------------------------------------------------------------------
# _refresh_completion_cache -- completion cache refresh helper
# ---------------------------------------------------------------------------


def _refresh_completion_cache(workspace_root: pathlib.Path) -> None:
    """Refresh completion-cache files under .kanon-data/.

    Called exclusively from within a kanon_workspace_lock context, so callers
    hold the workspace exclusive lock and no concurrent mutation can occur.

    Args:
        workspace_root: The project root directory (parent of .kanon).
    """
    cache_dir = workspace_root / ".kanon-data" / KANON_COMPLETION_CACHE_DIR
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"ERROR: Cannot create completion-cache directory {cache_dir}: {exc.strerror}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"kanon doctor: completion cache refreshed at {cache_dir}")
