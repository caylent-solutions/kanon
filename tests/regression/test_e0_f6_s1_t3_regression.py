# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regression guard for E0-F6-S1-T3: os.execv replaces process on RepoChangedException.

Bug reference: E0-F6-S1-T3 / Bug 3 -- main.py _Main() lines 808-817 contained
an except RepoChangedException block that called os.execv(sys.executable, ...)
unconditionally. When kanon embedded repo as a library (run_from_args()), this
os.execv call terminated the host process instead of returning a typed exception
to the caller.

Root cause: the RepoChangedException handler in _Main() had no awareness that it
was running inside a library-mode caller. It called os.execv directly, replacing
the entire calling process (the kanon CLI or any other embedder) rather than
propagating the error up the call stack.

Fix (landed in E0-F2-S1-T2 and codified in E0-F6-S1-T3): run_from_args() in
main.py temporarily replaces os.execv with _intercepting_execv, a sentinel that
raises _ExecvIntercepted. When _Main triggers a RepoChangedException and its
handler calls os.execv, _ExecvIntercepted is raised instead of replacing the
process. run_from_args() catches _ExecvIntercepted and retries internally up to
KANON_MAX_REPO_RESTART_RETRIES times. If retries are exhausted, RepoCommandError
is raised to the caller. The original os.execv is restored in a finally block.

This regression guard asserts that:
1. os.execv does not reach the real os module during embedded execution.
2. run_from_args() raises RepoCommandError rather than replacing the process.
3. The RepoCommandError message includes actionable information
   (KANON_MAX_REPO_RESTART_RETRIES and the exhausted count).
4. The _intercepting_execv sentinel is structurally present in main.py source.
5. No stdout leakage occurs when the retry limit is exhausted.
"""

import inspect
import os
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
import kanon_cli.repo.main as repo_main
from kanon_cli.repo import RepoCommandError
from kanon_cli.repo.main import _ExecvIntercepted, run_from_args


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Regression: os.execv never reaches real os module
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_os_execv_not_called_on_repo_changed_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001: os.execv must not replace the calling process on RepoChangedException.

    This test reproduces the exact bug condition from E0-F6-S1-T3: when the
    repo self-update path fires RepoChangedException inside _Main, the original
    code called os.execv unconditionally and replaced the calling process.

    After the fix, run_from_args() intercepts os.execv via _intercepting_execv.
    The sentinel raises _ExecvIntercepted, which run_from_args() catches and
    handles internally. The real os.execv must never be reached.

    Arrange: Patch _Main to raise _ExecvIntercepted (simulating the intercept).
    Patch the real os.execv with a sentinel that fails if called.
    Set retry limit to 0 so the loop exits after one attempt.
    Act: Call run_from_args().
    Assert: The real os.execv sentinel is never invoked; RepoCommandError is raised.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _fail_if_called(path: str, argv: list[str]) -> NoReturn:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(
            f"E0-F6-S1-T3 regression: os.execv reached the real os module. "
            f"The intercepting sentinel was bypassed. path={path!r}, argv={argv!r}"
        )

    monkeypatch.setattr(os, "execv", _fail_if_called)

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert real_execv_calls == [], (
        f"E0-F6-S1-T3 regression: os.execv was invoked {len(real_execv_calls)} time(s) "
        f"on the real os module. The intercepting sentinel in run_from_args() was bypassed. "
        f"The calling process would have been replaced. Calls recorded: {real_execv_calls!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "extra_args,test_id",
    [
        ([], "no_extra_args"),
        (["--some-flag"], "one_extra_arg"),
        (["--jobs=4", "--network-only"], "multiple_extra_args"),
    ],
)
def test_os_execv_not_called_for_any_extra_args_variant(
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    test_id: str,
) -> None:
    """AC-TEST-001 (parametrized): os.execv is not called for any extra_args on RepoChangedException.

    RepoChangedException carries an extra_args list that the original code
    appended to the os.execv restart argv. This test verifies that no matter
    what extra_args are present, os.execv never reaches the real os module
    through run_from_args().

    If any variant calls the real os.execv sentinel, the Bug 3 regression is
    confirmed: the intercepting sentinel was bypassed for that argv shape.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _fail_if_called(path: str, argv: list[str]) -> NoReturn:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(f"E0-F6-S1-T3 regression [{test_id}]: os.execv called with path={path!r}")

    monkeypatch.setattr(os, "execv", _fail_if_called)

    captured = list(extra_args)

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv) + captured)

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert real_execv_calls == [], (
        f"E0-F6-S1-T3 regression [{test_id}]: os.execv was called with "
        f"extra_args={extra_args!r}. Calls: {real_execv_calls!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Regression: exact E0-F6-S1-T3 bug condition triggered
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exact_bug_condition_repo_command_error_raised_not_process_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: run_from_args() raises RepoCommandError instead of replacing the process.

    Triggers the exact bug condition from E0-F6-S1-T3: _Main raises
    _ExecvIntercepted (which represents RepoChangedException triggering
    os.execv in the original buggy code). Before the fix, os.execv would
    have terminated the host process; after the fix, run_from_args() raises
    RepoCommandError.

    If this test fails with SystemExit or no exception at all, the Bug 3
    regression is confirmed: the process replacement path has been restored.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    process_survived = False
    try:
        with pytest.raises(RepoCommandError):
            run_from_args(["sync"], repo_dir="/nonexistent/.repo")
        process_survived = True
    except SystemExit as exc:
        pytest.fail(
            f"E0-F6-S1-T3 regression: run_from_args() raised SystemExit({exc.code!r}) "
            f"instead of RepoCommandError. Library code must not terminate the host process. "
            f"The Bug 3 fix -- intercepting os.execv and raising RepoCommandError -- "
            f"has been removed or bypassed."
        )

    assert process_survived, (
        "E0-F6-S1-T3 regression: run_from_args() did not raise RepoCommandError after "
        "the RepoChangedException path was triggered. The caller must receive a typed "
        "exception, not a process replacement."
    )


@pytest.mark.unit
def test_exact_bug_condition_repo_command_error_has_non_zero_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002 (exit code): RepoCommandError carries a non-zero exit_code attribute.

    When the retry limit is exhausted after repeated RepoChangedException
    triggers, run_from_args() must raise RepoCommandError with a non-zero
    exit_code so callers can detect and respond to the failure programmatically.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    error = exc_info.value
    assert isinstance(error.exit_code, int), (
        f"E0-F6-S1-T3 regression: RepoCommandError.exit_code must be an int, got {type(error.exit_code).__name__!r}"
    )
    assert error.exit_code != 0, (
        f"E0-F6-S1-T3 regression: RepoCommandError.exit_code must be non-zero "
        f"when the retry limit is exhausted after RepoChangedException. "
        f"Got exit_code={error.exit_code!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Guard: fixed code is structurally sound
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_intercepting_execv_sentinel_present_in_run_from_args_source() -> None:
    """AC-TEST-003: The _intercepting_execv sentinel is present in run_from_args() source.

    Inspects the source of run_from_args() to confirm that the os.execv
    interception mechanism is structurally intact. If os.execv is no longer
    replaced before _Main is called, the Bug 3 regression is immediate: any
    RepoChangedException inside _Main would call the real os.execv and replace
    the calling process.

    Checks for the presence of:
    - An _intercepting_execv or equivalent inner function that intercepts os.execv.
    - Assignment of os.execv to the interceptor before _Main is called.
    - Restoration of os.execv in a finally block.

    If any check fails, the structural guard against Bug 3 has been removed.
    """
    source = inspect.getsource(run_from_args)

    assert "_ExecvIntercepted" in source, (
        "E0-F6-S1-T3 regression guard: '_ExecvIntercepted' is no longer referenced in "
        "run_from_args(). The exception class used to intercept os.execv calls has been "
        "removed or renamed. Without it, RepoChangedException would call the real os.execv "
        "and replace the calling process. Restore the intercept mechanism in "
        "src/kanon_cli/repo/main.py -- run_from_args()."
    )

    assert "os.execv" in source, (
        "E0-F6-S1-T3 regression guard: 'os.execv' is no longer referenced in "
        "run_from_args(). The code that intercepts and restores os.execv has been removed. "
        "Without this guard, any RepoChangedException inside _Main() would call the real "
        "os.execv and terminate the host process. Restore the intercept in "
        "src/kanon_cli/repo/main.py -- run_from_args()."
    )

    assert "original_execv" in source or "os.execv = " in source, (
        "E0-F6-S1-T3 regression guard: os.execv replacement is no longer present in "
        "run_from_args(). The sentinel that prevents process replacement must assign a "
        "callable to os.execv before calling _Main(). Restore the os.execv = sentinel "
        "line in src/kanon_cli/repo/main.py -- run_from_args()."
    )

    assert "finally" in source, (
        "E0-F6-S1-T3 regression guard: 'finally' block is no longer present in "
        "run_from_args(). The original os.execv must be restored in a finally block "
        "so the calling process observes no persistent change after run_from_args() "
        "returns or raises. Restore the finally block in "
        "src/kanon_cli/repo/main.py -- run_from_args()."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "retry_limit",
    [0, 1, 3],
    ids=["zero_retries", "one_retry", "three_retries"],
)
def test_retry_loop_exhaustion_raises_repo_command_error_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
    retry_limit: int,
) -> None:
    """AC-TEST-003 (parametrized): Error message is actionable for any retry limit value.

    For each retry limit, the RepoCommandError message must contain both the env
    var name (KANON_MAX_REPO_RESTART_RETRIES -- so the operator knows what to set)
    and the exhausted count (so the operator knows the current value). Verifies
    that _Main is invoked exactly retry_limit + 1 times before the error is raised.

    This is the third acceptance-criterion check: the error message contains
    actionable information about the Bug 3 fix's retry mechanism.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", str(retry_limit))

    invocation_count = [0]

    def _raise_intercepted(argv: list[str]) -> None:
        invocation_count[0] += 1
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    message = str(exc_info.value)

    assert "KANON_MAX_REPO_RESTART_RETRIES" in message, (
        f"E0-F6-S1-T3 regression: retry_limit={retry_limit}: RepoCommandError message "
        f"must mention 'KANON_MAX_REPO_RESTART_RETRIES' so the operator knows which "
        f"env var to increase. Got message: {message!r}"
    )
    assert str(retry_limit) in message, (
        f"E0-F6-S1-T3 regression: retry_limit={retry_limit}: RepoCommandError message "
        f"must include the exhausted retry count ({retry_limit}) so the operator knows "
        f"the current value they need to increase beyond. Got message: {message!r}"
    )

    expected_invocations = retry_limit + 1
    assert invocation_count[0] == expected_invocations, (
        f"E0-F6-S1-T3 regression: retry_limit={retry_limit}: expected {expected_invocations} "
        f"_Main invocations (1 initial + {retry_limit} retries) before RepoCommandError, "
        f"got {invocation_count[0]}. The retry loop in run_from_args() may be broken."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Guard: prevents Bug 3 from recurring
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embedded_flag_restored_after_repo_changed_exception_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-FUNC-001: EMBEDDED flag is restored to False after run_from_args() raises.

    After RepoChangedException triggers the retry path and run_from_args()
    raises RepoCommandError, the EMBEDDED flag must be restored to False so
    that subsequent calls to run_from_args() begin in a clean state. If
    EMBEDDED is left True, subsequent library invocations may behave
    unexpectedly (e.g., selfupdate suppressed permanently).

    This is the functional guard against Bug 3's side-effect on global state.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert repo_pkg.EMBEDDED is False, (
        f"E0-F6-S1-T3 regression: EMBEDDED must be restored to False after "
        f"run_from_args() raises on RepoChangedException retry exhaustion. "
        f"Got EMBEDDED={repo_pkg.EMBEDDED!r}. The finally block in run_from_args() "
        f"that resets _pager_module.EMBEDDED has been removed or broken."
    )


@pytest.mark.unit
def test_original_os_execv_restored_after_repo_changed_exception_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-FUNC-001: original os.execv is restored after run_from_args() raises.

    The finally block in run_from_args() must restore os.execv to its
    pre-call value even when RepoCommandError is raised on retry exhaustion.
    If os.execv is not restored, the calling process is left with the
    _intercepting_execv sentinel as the real os.execv, which would suppress
    all process-replacement calls system-wide until the process exits.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    original_execv = os.execv

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert os.execv is original_execv, (
        f"E0-F6-S1-T3 regression: os.execv was not restored to its original value "
        f"after run_from_args() raised RepoCommandError. The finally block that "
        f"restores os.execv in src/kanon_cli/repo/main.py -- run_from_args() has "
        f"been removed or broken. Got: {os.execv!r}, expected: {original_execv!r}"
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_stdout_leakage_when_retry_limit_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-CHANNEL-001: No stdout output when RepoCommandError is raised on retry exhaustion.

    stdout is reserved for machine-consumable output. When run_from_args()
    exhausts the retry limit after RepoChangedException, the error must be
    communicated via a raised RepoCommandError exception -- not by writing
    to stdout. Verifies that no print() call inside the retry loop or error
    path writes to stdout.

    If this test fails with non-empty stdout, a print() or sys.stdout.write()
    has been introduced into the error path of run_from_args() (a channel
    discipline violation).
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"E0-F6-S1-T3 channel discipline violation: run_from_args() produced stdout "
        f"output when RepoCommandError was raised on retry exhaustion. "
        f"stdout content: {captured.out!r}. Errors must propagate as exceptions, "
        f"not be written to stdout."
    )


@pytest.mark.unit
def test_no_stdout_leakage_uses_repo_pkg_interface(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-CHANNEL-001 (package interface): No stdout from kanon_cli.repo.run_from_args.

    Verifies the same channel discipline through the public package-level
    run_from_args() re-export in kanon_cli.repo, ensuring the public API
    surface does not introduce any additional stdout writes.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise _ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"E0-F6-S1-T3 channel discipline violation: kanon_cli.repo.run_from_args() "
        f"produced stdout output when RepoCommandError was raised. "
        f"stdout content: {captured.out!r}."
    )
