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

"""Unit tests for Bug 3: os.execv replaces process on RepoChangedException.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 3 -- main.py RepoChangedException
handler calls os.execv() which would replace the entire calling process when
repo is embedded in kanon. When kanon calls run_from_args() and the underlying
repo sync triggers a self-update (RepoChangedException), os.execv() would kill
the kanon process instead of returning control to the caller.

Root cause: main.py _Main() lines 808-817 -- the except RepoChangedException
block calls os.execv(sys.executable, ...) unconditionally. When embedded in
a library context, this terminates the host process instead of propagating
the error back to the caller.

Fix: run_from_args() in main.py intercepts os.execv by temporarily replacing
it with a sentinel (_intercepting_execv) that raises _ExecvIntercepted. The
retry loop in run_from_args() catches _ExecvIntercepted, handles the repo
restart internally (up to KANON_MAX_REPO_RESTART_RETRIES times), and raises
RepoCommandError with an actionable message if the retry limit is exceeded.
This ensures os.execv never reaches the real os module during embedded execution.

These tests verify the fix from Bug 3's perspective:
- AC-TEST-001: os.execv is not called when RepoChangedException is raised
- AC-TEST-002: RepoCommandError is raised to the caller instead of process replacement
- AC-TEST-003: The error message includes actionable information about the failure
"""

import os
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
import kanon_cli.repo.main as repo_main
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# AC-TEST-001: os.execv is not called when RepoChangedException is raised
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_os_execv_not_called_when_repo_changed_exception_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001: os.execv must not reach the real os module when RepoChangedException fires.

    Arrange: Patch _Main to raise _ExecvIntercepted (the exception raised when
    os.execv is intercepted inside run_from_args). Patch the real os.execv with
    a sentinel that raises AssertionError if invoked. Set retry limit to 0 so
    the loop exits after one attempt.
    Act: Call run_from_args() with an arbitrary subcommand.
    Assert: The sentinel os.execv is never called -- the retry loop handles the
    restart internally, never delegating to the real os.execv.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(
            f"os.execv reached the real os module after RepoChangedException: path={path!r}, argv={argv!r}"
        )

    monkeypatch.setattr(os, "execv", _record_execv)

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert real_execv_calls == [], (
        f"os.execv was called {len(real_execv_calls)} time(s) on the real os module "
        f"after RepoChangedException was raised. Bug 3 regression: the embedded process "
        f"would have been replaced. Calls: {real_execv_calls!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "extra_args",
    [
        [],
        ["--some-flag"],
        ["--jobs=4", "--network-only"],
    ],
    ids=["no_extra_args", "one_extra_arg", "multiple_extra_args"],
)
def test_os_execv_not_called_regardless_of_extra_args_in_repo_changed_exception(
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
) -> None:
    """AC-TEST-001 (parametrized): os.execv must not fire for any extra_args on RepoChangedException.

    RepoChangedException carries an extra_args list that would be appended to
    the os.execv restart argv in the original code. This test confirms that no
    matter what extra_args are present, os.execv never reaches the real os
    module through run_from_args().
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    real_execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        real_execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv must not be called: path={path!r}")

    monkeypatch.setattr(os, "execv", _record_execv)

    captured_extra_args = list(extra_args)

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv) + captured_extra_args)

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert real_execv_calls == [], (
        f"os.execv was called with extra_args={extra_args!r}. "
        f"Bug 3 regression: the embedded process would have been replaced."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: RepoCommandError is raised to the caller (not process replacement)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_command_error_raised_instead_of_process_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: run_from_args() must raise RepoCommandError, not replace the process.

    Arrange: Patch _Main to raise _ExecvIntercepted (simulating RepoChangedException
    triggering os.execv inside _Main). Set retry limit to 0 to exhaust immediately.
    Act: Call run_from_args().
    Assert: RepoCommandError is raised to the caller -- the process is not replaced.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    process_survived = False
    try:
        with pytest.raises(RepoCommandError):
            repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")
        process_survived = True
    except SystemExit as exc:
        pytest.fail(
            f"run_from_args() raised SystemExit({exc.code!r}) instead of RepoCommandError. "
            f"Bug 3: library code must not terminate the host process."
        )

    assert process_survived, (
        "run_from_args() did not raise RepoCommandError after RepoChangedException. "
        "Bug 3: the caller must receive a typed exception, not a process replacement."
    )


@pytest.mark.unit
def test_repo_command_error_has_non_zero_exit_code_for_repo_changed_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002 (exit code): RepoCommandError must carry a non-zero exit_code.

    When the retry limit is exhausted after a RepoChangedException path,
    run_from_args() must raise RepoCommandError with a non-zero exit_code so
    that callers can detect and respond to the failure programmatically.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    error = exc_info.value
    assert isinstance(error.exit_code, int), (
        f"RepoCommandError.exit_code must be an int, got {type(error.exit_code).__name__!r}"
    )
    assert error.exit_code != 0, (
        f"RepoCommandError.exit_code must be non-zero when the retry limit is exhausted "
        f"after RepoChangedException. Got exit_code={error.exit_code!r}"
    )


@pytest.mark.unit
def test_embedded_flag_is_false_after_repo_changed_exception_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002 (state cleanup): EMBEDDED flag must be False after run_from_args() raises.

    After RepoChangedException triggers the retry path and run_from_args()
    raises RepoCommandError, the EMBEDDED flag must be restored to False so
    that subsequent calls to run_from_args() begin in a clean state.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError):
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    assert repo_pkg.EMBEDDED is False, (
        f"EMBEDDED must be restored to False after run_from_args() raises on "
        f"RepoChangedException retry exhaustion. Got: {repo_pkg.EMBEDDED!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: Error message includes actionable information
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_message_mentions_retry_limit_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003: RepoCommandError message must mention the retry limit env var.

    When the retry limit is exhausted after repeated RepoChangedException
    triggers, the error message must include 'KANON_MAX_REPO_RESTART_RETRIES'
    so the operator knows how to increase the limit and unblock the workflow.
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", "0")

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    message = str(exc_info.value)
    assert "KANON_MAX_REPO_RESTART_RETRIES" in message, (
        f"RepoCommandError message must mention 'KANON_MAX_REPO_RESTART_RETRIES' so the "
        f"operator knows how to adjust the retry limit. Got message: {message!r}"
    )


@pytest.mark.unit
def test_error_message_includes_retry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003 (retry count): Error message must include the retry count that was exhausted.

    The operator needs to know the configured limit to understand whether to
    increase it. The message must embed the numeric limit so the error is
    self-contained and actionable without consulting documentation.
    """
    retry_limit = 2
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", str(retry_limit))

    def _raise_intercepted(argv: list[str]) -> None:
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    message = str(exc_info.value)
    assert str(retry_limit) in message, (
        f"RepoCommandError message must include the retry count ({retry_limit}) so the "
        f"operator can see the configured limit. Got message: {message!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "retry_limit",
    [0, 1, 3],
    ids=["zero_retries", "one_retry", "three_retries"],
)
def test_error_message_is_actionable_for_various_retry_limits(
    monkeypatch: pytest.MonkeyPatch,
    retry_limit: int,
) -> None:
    """AC-TEST-003 (parametrized): Error message is actionable for any retry limit value.

    For each retry limit, the error message must contain both the env var name
    (so the operator knows what to set) and the exhausted count (so the operator
    knows the current value they need to increase beyond).
    """
    monkeypatch.setenv("KANON_MAX_REPO_RESTART_RETRIES", str(retry_limit))

    invocation_count = [0]

    def _raise_intercepted(argv: list[str]) -> None:
        invocation_count[0] += 1
        raise repo_main._ExecvIntercepted("/fake/python", list(argv))

    monkeypatch.setattr(repo_main, "_Main", _raise_intercepted)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.run_from_args(["sync"], repo_dir="/nonexistent/.repo")

    message = str(exc_info.value)
    assert "KANON_MAX_REPO_RESTART_RETRIES" in message, (
        f"retry_limit={retry_limit}: message must mention KANON_MAX_REPO_RESTART_RETRIES. Got: {message!r}"
    )
    assert str(retry_limit) in message, (
        f"retry_limit={retry_limit}: message must include the limit value. Got: {message!r}"
    )
    # _Main is invoked once per attempt: initial + retries = retry_limit + 1
    expected_invocations = retry_limit + 1
    assert invocation_count[0] == expected_invocations, (
        f"retry_limit={retry_limit}: expected {expected_invocations} _Main invocations "
        f"(1 initial + {retry_limit} retries), got {invocation_count[0]}"
    )
