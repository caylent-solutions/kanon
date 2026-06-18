"""Shared git ls-remote runner for kanon-cli.

Provides a single, testable retry loop for all ``git ls-remote`` subprocess
calls issued by kanon doctor and kanon install.  Extracted from
``kanon_cli.commands.doctor._run_ls_remote_impl`` per spec Section 3 /
FR-27 (DRY consolidation) and issue #66.

Design decisions
----------------
- No ``time.sleep`` or any time-based delay between retries (spec Section 3.5,
  issue #64).  The retry loop is event-driven: each attempt either succeeds,
  fails with an auth-error (skips remaining retries), or times out -- and the
  next attempt starts immediately.
- Auth-error patterns from ``constants.GIT_AUTH_ERROR_PATTERNS`` bypass the
  retry loop so credential lockouts are not triggered.
- A ``subprocess.TimeoutExpired`` on any attempt returns exit code 124 (POSIX
  convention for timeout) with an informative stderr message.
- All configuration (auth-error patterns, default timeout) comes from
  ``kanon_cli.constants`` -- no inline literals.
"""

from __future__ import annotations

import subprocess

from kanon_cli.constants import GIT_AUTH_ERROR_PATTERNS


def run_git_ls_remote(
    cmd: list[str],
    timeout: int,
    retry_count: int,
) -> tuple[int, str, str]:
    """Execute a ``git ls-remote`` command with retry and per-attempt timeout.

    Retries up to ``retry_count`` times on transient non-zero exits.  Does NOT
    introduce any time-based delay between retries (event-driven loop, no
    ``time.sleep``).

    Retry semantics:
    - Returns immediately on exit code 0 (success).
    - Returns immediately when stderr contains an auth-error pattern from
      ``GIT_AUTH_ERROR_PATTERNS`` (to avoid credential lockouts).
    - Retries on all other non-zero exits until ``retry_count`` attempts are
      exhausted, then returns the last result.
    - Returns exit code 124 (POSIX timeout convention) when
      ``subprocess.TimeoutExpired`` is raised; retries apply.

    Args:
        cmd: Full command list, e.g. ``["git", "ls-remote", url, ref]``.
        timeout: Per-attempt timeout in seconds.
        retry_count: Maximum number of attempts (1 means no retries).

    Returns:
        A tuple ``(returncode, stdout, stderr)`` from the final attempt.
    """
    last_returncode: int = -1
    last_stdout: str = ""
    last_stderr: str = ""

    for _attempt in range(retry_count):
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

            if any(pat in result.stderr for pat in GIT_AUTH_ERROR_PATTERNS):
                return (result.returncode, result.stdout, result.stderr)

        except subprocess.TimeoutExpired:
            last_returncode = 124
            last_stdout = ""
            last_stderr = f"git ls-remote timed out after {timeout}s"

    return (last_returncode, last_stdout, last_stderr)
