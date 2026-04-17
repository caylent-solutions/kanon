"""Tests for embedded mode (EMBEDDED flag) in the kanon_cli.repo package.

Verifies that:
- The EMBEDDED flag is present in the repo package.
- pager.py skips os.execvp() when EMBEDDED=True.
- forall.py saves and restores signal handlers before and after Execute().
- run_from_args() sets EMBEDDED=True before invoking repo commands.
"""

import os
import signal
from typing import NoReturn
from unittest.mock import MagicMock

import pytest

import kanon_cli.repo as repo_pkg
import kanon_cli.repo.main as repo_main
from kanon_cli.repo import pager as repo_pager
from kanon_cli.repo.subcmds import forall as forall_mod


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-TEST-001: EMBEDDED flag exists and defaults to False
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embedded_flag_exists_in_repo_package() -> None:
    """AC-FUNC-001: EMBEDDED flag must be accessible as kanon_cli.repo.EMBEDDED."""
    assert hasattr(repo_pkg, "EMBEDDED"), "kanon_cli.repo must expose an EMBEDDED attribute"


@pytest.mark.unit
def test_embedded_flag_defaults_to_false() -> None:
    """AC-FUNC-001: EMBEDDED must default to False so normal CLI usage is unaffected."""
    assert repo_pkg.EMBEDDED is False, f"EMBEDDED should default to False, got {repo_pkg.EMBEDDED!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-002 / AC-TEST-001 / AC-TEST-002: pager.py skips os.execvp when EMBEDDED
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pager_skips_execvp_when_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-002, AC-TEST-001: _BecomePager must not call os.execvp when EMBEDDED=True."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    execvp_calls: list[tuple[str, list[str]]] = []

    def _record_execvp(path: str, args: list[str]) -> NoReturn:
        execvp_calls.append((path, list(args)))
        raise AssertionError(f"os.execvp was called with EMBEDDED=True: path={path!r}")

    monkeypatch.setattr(os, "execvp", _record_execvp)

    # select.select would block waiting for input; patch it to return immediately.
    monkeypatch.setattr("select.select", lambda *_: ([0], [], []))

    repo_pager._BecomePager("less")

    assert execvp_calls == [], (
        f"os.execvp was called {len(execvp_calls)} time(s) even though EMBEDDED=True: {execvp_calls!r}"
    )


@pytest.mark.unit
def test_pager_calls_execvp_when_not_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-002: _BecomePager must call os.execvp when EMBEDDED=False (normal CLI mode)."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", False)

    execvp_calls: list[tuple[str, list[str]]] = []

    def _capture_execvp(path: str, args: list[str]) -> NoReturn:
        execvp_calls.append((path, list(args)))
        # Raise to prevent actual process replacement in the test.
        raise OSError("execvp intercepted for test")

    monkeypatch.setattr(os, "execvp", _capture_execvp)

    # Patch the fallback execv that _BecomePager uses on OSError.
    monkeypatch.setattr(os, "execv", lambda *_: None)

    # select.select would block waiting for input; patch it to return immediately.
    monkeypatch.setattr("select.select", lambda *_: ([0], [], []))

    repo_pager._BecomePager("less")

    assert len(execvp_calls) == 1, (
        f"os.execvp should be called exactly once when EMBEDDED=False, got {len(execvp_calls)} calls: {execvp_calls!r}"
    )
    assert execvp_calls[0][0] == "less", (
        f"os.execvp should be called with pager='less', got path={execvp_calls[0][0]!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-003 / AC-FUNC-004 / AC-FUNC-005 / AC-TEST-003 / AC-TEST-004:
# forall.py saves and restores signal handlers
# ---------------------------------------------------------------------------


def _make_mock_forall() -> "forall_mod.Forall":
    """Construct a minimal Forall instance with required attributes mocked."""
    instance = forall_mod.Forall.__new__(forall_mod.Forall)
    # Mock the manifest and related attributes that Execute() accesses.
    mock_manifest = MagicMock()
    mock_manifest.IsMirror = False
    mock_manifest.manifestProject.worktree = "/tmp/nonexistent-worktree"
    mock_manifest.submanifests = {}
    instance.manifest = mock_manifest
    instance.client = MagicMock()
    instance.client.globalConfig = MagicMock()
    instance.git_event_log = MagicMock()
    instance.event_log = MagicMock()
    instance.outer_client = MagicMock()
    instance.outer_manifest = MagicMock()
    return instance


def _build_opt_for_forall() -> MagicMock:
    """Return a minimal MagicMock simulating parsed forall options."""
    opt = MagicMock()
    opt.command = ["echo", "hello"]
    opt.jobs = 1
    opt.this_manifest_only = True
    opt.regex = False
    opt.inverse_regex = False
    opt.groups = None
    opt.project_header = False
    opt.verbose = False
    opt.abort_on_errors = False
    opt.ignore_missing = True
    opt.interactive = True
    opt.outer_manifest = False
    return opt


@pytest.mark.unit
def test_forall_saves_and_restores_signal_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-003, AC-FUNC-004, AC-TEST-003: Execute must save signal handlers before and restore after.

    Simulates an ExecuteInParallel that overwrites SIGINT with SIG_IGN, then
    verifies that Execute restores the original handler after returning.
    Without the save/restore logic, the sentinel handler would be lost.
    """
    sentinel_called: list[int] = []

    def _sentinel_handler(signum: int, frame: object) -> None:
        sentinel_called.append(signum)

    original = signal.signal(signal.SIGINT, _sentinel_handler)
    try:
        handler_before = signal.getsignal(signal.SIGINT)

        def _clobber_sigint_and_return(jobs, fn, rng, **kwargs):
            # Simulate internal code that alters the SIGINT handler.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            return 0

        opt = _build_opt_for_forall()
        forall_instance = _make_mock_forall()
        forall_instance.GetProjects = MagicMock(return_value=[])
        forall_instance.FindProjects = MagicMock(return_value=[])
        forall_instance.ParallelContext = MagicMock()
        forall_instance.ParallelContext.return_value.__enter__ = MagicMock(return_value=None)
        forall_instance.ParallelContext.return_value.__exit__ = MagicMock(return_value=False)
        forall_instance.get_parallel_context = MagicMock(return_value={})
        forall_instance.ExecuteInParallel = MagicMock(side_effect=_clobber_sigint_and_return)

        forall_instance.Execute(opt, [])

        handler_after = signal.getsignal(signal.SIGINT)
        assert handler_after is handler_before, (
            f"SIGINT handler was not restored after Execute altered it.\n"
            f"  Before: {handler_before!r}\n"
            f"  After:  {handler_after!r}"
        )
    finally:
        signal.signal(signal.SIGINT, original)


@pytest.mark.unit
def test_forall_restores_signal_handlers_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-005, AC-TEST-004: Signal handlers must be restored even when Execute raises.

    Simulates an ExecuteInParallel that overwrites SIGINT and then raises,
    then verifies the original SIGINT handler is restored.
    """
    sentinel_called: list[int] = []

    def _sentinel_handler(signum: int, frame: object) -> None:
        sentinel_called.append(signum)

    original = signal.signal(signal.SIGINT, _sentinel_handler)
    try:
        handler_before = signal.getsignal(signal.SIGINT)

        def _clobber_sigint_and_raise(jobs, fn, rng, **kwargs):
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise RuntimeError("forced failure for test")

        opt = _build_opt_for_forall()
        forall_instance = _make_mock_forall()
        forall_instance.GetProjects = MagicMock(return_value=["fake_project"])
        forall_instance.FindProjects = MagicMock(return_value=[])
        forall_instance.ParallelContext = MagicMock()
        forall_instance.ParallelContext.return_value.__enter__ = MagicMock(return_value=None)
        forall_instance.ParallelContext.return_value.__exit__ = MagicMock(return_value=False)
        forall_instance.get_parallel_context = MagicMock(return_value={})
        forall_instance.ExecuteInParallel = MagicMock(side_effect=_clobber_sigint_and_raise)

        # Execute catches exceptions internally and calls sys.exit on non-zero rc.
        try:
            forall_instance.Execute(opt, [])
        except SystemExit:
            pass

        handler_after = signal.getsignal(signal.SIGINT)
        assert handler_after is handler_before, (
            f"SIGINT handler was not restored after Execute raised an exception.\n"
            f"  Before: {handler_before!r}\n"
            f"  After:  {handler_after!r}"
        )
    finally:
        signal.signal(signal.SIGINT, original)


# ---------------------------------------------------------------------------
# AC-FUNC-006: run_from_args sets EMBEDDED=True before invoking repo commands
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_from_args_sets_embedded_true_during_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-006: run_from_args must set repo_pkg.EMBEDDED=True while _Main is executing.

    Patches _Main with a sentinel that records the value of EMBEDDED during
    the call and raises SystemExit(0) immediately to avoid running actual
    repo logic.
    """
    embedded_values_seen: list[bool] = []

    def _capture_embedded_main(argv: list[str]) -> None:
        embedded_values_seen.append(repo_pkg.EMBEDDED)
        raise SystemExit(0)

    monkeypatch.setattr(repo_main, "_Main", _capture_embedded_main)

    repo_pkg.run_from_args(["version"], repo_dir="/nonexistent/.repo")

    assert len(embedded_values_seen) == 1, (
        f"_Main should have been called exactly once, got {len(embedded_values_seen)} calls"
    )
    assert embedded_values_seen[0] is True, (
        f"EMBEDDED must be True during run_from_args execution, got {embedded_values_seen[0]!r}"
    )


@pytest.mark.unit
def test_run_from_args_restores_embedded_to_false_after_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-006: run_from_args must restore EMBEDDED to False after execution completes."""

    def _immediate_success(argv: list[str]) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(repo_main, "_Main", _immediate_success)

    assert repo_pkg.EMBEDDED is False, "EMBEDDED should be False before run_from_args"
    repo_pkg.run_from_args(["version"], repo_dir="/nonexistent/.repo")
    assert repo_pkg.EMBEDDED is False, (
        f"EMBEDDED should be restored to False after run_from_args, got {repo_pkg.EMBEDDED!r}"
    )


@pytest.mark.unit
def test_run_from_args_restores_embedded_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-006: run_from_args must restore EMBEDDED=False even when the command fails."""
    from kanon_cli.repo import RepoCommandError

    def _fail(argv: list[str]) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(repo_main, "_Main", _fail)

    assert repo_pkg.EMBEDDED is False, "EMBEDDED should be False before run_from_args"
    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["version"], repo_dir="/nonexistent/.repo")
    assert repo_pkg.EMBEDDED is False, (
        f"EMBEDDED should be restored to False after run_from_args fails, got {repo_pkg.EMBEDDED!r}"
    )
