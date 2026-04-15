"""Global process state isolation tests for kanon_cli.repo.

These tests assert that calling into the repo package from Python code leaves
the calling process in the same state it was in before the call. The contract
is: sys.argv, os.execv, sys.path, os.getcwd(), and os.environ must all be
unchanged (or restored) after any API entry point into the repo package.

The isolation tests expect RepoCommandError (not SystemExit) to be raised
because run_from_args() is library code -- it must never propagate SystemExit
to callers.
"""

import copy
import os
import sys
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
import kanon_cli.repo.main as repo_main
from kanon_cli.repo import RepoCommandError

_SENTINEL_REPO_DIR = "/nonexistent/.repo"
# Use an unknown subcommand so _Main raises SystemExit(1) immediately after
# printing "not a repo command", without attempting any git operations that
# would fail with GitCommandError on a nonexistent repo directory.
_SENTINEL_ARGS = ["kanon-nonexistent-subcommand-sentinel"]


def _invoke_api() -> None:
    """Invoke the repo API with sentinel arguments.

    Uses an unknown subcommand name so _Main raises SystemExit(1) immediately
    (printing "not a repo command") without reaching any git operations that
    would fail with GitCommandError on the nonexistent sentinel repo dir.
    Expected to raise RepoCommandError wrapping that SystemExit.
    """
    repo_pkg.run_from_args(_SENTINEL_ARGS, repo_dir=_SENTINEL_REPO_DIR)


@pytest.mark.unit
def test_sys_argv_unchanged_after_api_call() -> None:
    """AC-TEST-001: sys.argv must not be mutated by a repo API call.

    Snapshot sys.argv before calling run_from_args, then assert the list
    contents are identical after the call returns.
    """
    argv_before = list(sys.argv)
    with pytest.raises(RepoCommandError):
        _invoke_api()
    argv_after = list(sys.argv)
    assert argv_after == argv_before, (
        f"sys.argv was mutated by repo API call.\n  Before: {argv_before!r}\n  After:  {argv_after!r}"
    )


@pytest.mark.unit
def test_os_execv_never_called_during_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-002: os.execv must never be invoked during a repo API call.

    Monkeypatch os.execv with a sentinel that raises AssertionError if called.
    Any invocation of os.execv during run_from_args means the caller's process
    would be replaced -- a critical isolation violation.
    """
    execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv was called during repo API call: path={path!r}, argv={argv!r}")

    monkeypatch.setattr(os, "execv", _record_execv)
    with pytest.raises(RepoCommandError):
        _invoke_api()
    assert execv_calls == [], f"os.execv was called {len(execv_calls)} time(s) during repo API call: {execv_calls!r}"


@pytest.mark.unit
def test_sys_path_unchanged_after_api_call() -> None:
    """AC-TEST-003: sys.path must not be mutated by a repo API call.

    Snapshot the list contents before, compare after. The repo tool must not
    insert, remove, or reorder entries in the interpreter path.
    """
    path_before = list(sys.path)
    with pytest.raises(RepoCommandError):
        _invoke_api()
    path_after = list(sys.path)
    assert path_after == path_before, (
        f"sys.path was mutated by repo API call.\n  Before: {path_before!r}\n  After:  {path_after!r}"
    )


@pytest.mark.unit
def test_cwd_unchanged_after_api_call() -> None:
    """AC-TEST-004: The current working directory must not be changed by a repo API call.

    Record os.getcwd() before and after run_from_args and assert they are equal.
    """
    cwd_before = os.getcwd()
    with pytest.raises(RepoCommandError):
        _invoke_api()
    cwd_after = os.getcwd()
    assert cwd_after == cwd_before, (
        f"os.getcwd() changed during repo API call.\n  Before: {cwd_before!r}\n  After:  {cwd_after!r}"
    )


@pytest.mark.unit
def test_os_environ_restored_after_api_call() -> None:
    """AC-TEST-005: os.environ must be restored to its original state after a repo API call.

    Deep-copy the environment mapping before the call and compare after. Any
    key added, removed, or changed by the repo package is an isolation
    violation.
    """
    env_before = copy.deepcopy(dict(os.environ))
    with pytest.raises(RepoCommandError):
        _invoke_api()
    env_after = dict(os.environ)

    added = {k: env_after[k] for k in env_after if k not in env_before}
    removed = {k: env_before[k] for k in env_before if k not in env_after}
    changed = {k: (env_before[k], env_after[k]) for k in env_before if k in env_after and env_before[k] != env_after[k]}

    violations: list[str] = []
    if added:
        violations.append(f"Keys added to os.environ: {added!r}")
    if removed:
        violations.append(f"Keys removed from os.environ: {removed!r}")
    if changed:
        violations.append(f"Keys changed in os.environ: {changed!r}")

    assert not violations, "os.environ was mutated by repo API call:\n" + "\n".join(f"  {v}" for v in violations)


@pytest.mark.unit
def test_system_exit_converted_to_repo_command_error() -> None:
    """AC-TEST-002 (exception contract): SystemExit from _Main must be converted to RepoCommandError.

    run_from_args() is library code and must never propagate SystemExit to
    callers. Instead, it must catch SystemExit and raise RepoCommandError
    carrying the original exit code. An unknown subcommand reliably triggers
    SystemExit(1) from _Main without reaching git operations.
    """
    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(_SENTINEL_ARGS, repo_dir=_SENTINEL_REPO_DIR)
    assert exc_info.value.exit_code is not None, (
        "RepoCommandError must carry the exit_code from the underlying SystemExit"
    )


@pytest.mark.unit
def test_repo_command_error_carries_exit_code() -> None:
    """AC-TEST-002 (exit code propagation): RepoCommandError.exit_code reflects _Main's exit code.

    When _Main raises SystemExit with a specific exit code, run_from_args must
    wrap it in a RepoCommandError that exposes the same exit code so callers
    can act on it. An unknown subcommand reliably produces SystemExit(1).
    """
    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(_SENTINEL_ARGS, repo_dir=_SENTINEL_REPO_DIR)
    error = exc_info.value
    assert isinstance(error.exit_code, int), f"RepoCommandError.exit_code must be an int, got {type(error.exit_code)}"
    assert error.exit_code != 0, f"Expected a non-zero exit code for an unknown subcommand, got {error.exit_code}"


@pytest.mark.unit
def test_repo_changed_retries_without_execv_and_raises_on_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003: RepoChangedException retry path must never call os.execv.

    Simulate the RepoChangedException path by patching _Main to always raise
    _ExecvIntercepted (the exception raised when os.execv is intercepted inside
    run_from_args). Verify:
    (a) os.execv is never called on the real os module -- the retry loop handles
        the restart internally without replacing the process.
    (b) After the retry limit is exhausted, RepoCommandError is raised with a
        descriptive message mentioning the retry limit env var.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "1")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv reached the real os module during retry loop: path={path!r}")

    monkeypatch.setattr(os, "execv", _record_execv)

    # Patch _Main to always raise _ExecvIntercepted, simulating a scenario
    # where every invocation triggers a RepoChangedException -> os.execv path.
    def _always_intercept(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _always_intercept)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(_SENTINEL_ARGS, repo_dir=_SENTINEL_REPO_DIR)

    error = exc_info.value
    assert real_execv_calls == [], (
        f"os.execv was invoked on the real os module {len(real_execv_calls)} time(s): {real_execv_calls!r}"
    )
    assert "KANON_MAX_REPO_RESTART_RETRIES" in str(error), (
        f"RepoCommandError message must mention KANON_MAX_REPO_RESTART_RETRIES so the "
        f"caller knows how to adjust the retry limit; got: {error!r}"
    )
