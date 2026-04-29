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

"""Regression guard for E0-F6-S2-T6: selfupdate incompatible with embedded mode.

Bug reference: E0-F6-S2-T6 / Bug 10 -- selfupdate subcommand incompatible
with embedding. When kanon-cli runs in embedded mode (EMBEDDED=True), the
selfupdate subcommand attempted to call PreSync() and Sync_NetworkHalf() on
the "repo project", which does not exist in that context. This caused an
AttributeError or network failure crash.

Root cause: subcmds/selfupdate.py Execute() had no guard for the embedded
mode flag. The call to self.manifest.repoProject.PreSync() failed because
repoProject is not meaningful when running embedded.

Fix (landed in E0-F4-S1-T3): Added an early return in Execute() that checks
_pager_module.EMBEDDED before any repoProject access. When embedded, a
descriptive informational message is printed to stderr and the function
returns 0 immediately, skipping all sync/update operations.

This regression guard asserts that:
1. The informational message is printed to stderr when embedded.
2. No sync or update operation is attempted when embedded.
3. The exit status is zero when embedded.
4. The embedded-mode guard branch is structurally present in the source code.
"""

import inspect
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.repo.pager as repo_pager
from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod
from kanon_cli.repo.subcmds.selfupdate import Selfupdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_selfupdate_instance() -> Selfupdate:
    """Return a Selfupdate instance with all required attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest and remote setup.
    All attributes accessed by Execute() are provided as MagicMock objects.

    Returns:
        A Selfupdate instance ready for Execute() invocation.
    """
    instance = Selfupdate.__new__(Selfupdate)
    mock_manifest = MagicMock()
    mock_manifest.repoProject = MagicMock()
    instance.manifest = mock_manifest
    instance.client = MagicMock()
    instance.git_event_log = MagicMock()
    instance.event_log = MagicMock()
    instance.outer_client = MagicMock()
    instance.outer_manifest = MagicMock()
    return instance


def _make_opt(repo_upgraded: bool = False, repo_verify: bool = True) -> MagicMock:
    """Return a minimal MagicMock simulating parsed selfupdate CLI options.

    Args:
        repo_upgraded: Simulates the --repo-upgraded flag being set.
        repo_verify: Simulates the --no-repo-verify flag (True = verify).

    Returns:
        MagicMock with repo_upgraded and repo_verify attributes set.
    """
    opt = MagicMock()
    opt.repo_upgraded = repo_upgraded
    opt.repo_verify = repo_verify
    return opt


# ---------------------------------------------------------------------------
# AC-TEST-001 -- selfupdate prints embedded mode informational message
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_selfupdate_embedded_prints_informational_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001: selfupdate prints the informational message when EMBEDDED=True.

    This test reproduces the exact bug condition from E0-F6-S2-T6: the selfupdate
    subcommand is invoked while EMBEDDED=True. Before the fix, Execute() called
    self.manifest.repoProject.PreSync() unconditionally, which fails in embedded
    mode. After the fix, a descriptive message is printed to stderr and the
    function returns immediately without any repoProject access.

    If this test fails with a missing SELFUPDATE_EMBEDDED_MESSAGE in stderr,
    the E0-F6-S2-T6 bug has regressed.

    Arrange: Set EMBEDDED=True to simulate embedded execution context.
    Act: Call Execute() on a Selfupdate instance.
    Assert: SELFUPDATE_EMBEDDED_MESSAGE appears in stderr output.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    output = captured_stderr.getvalue()
    assert SELFUPDATE_EMBEDDED_MESSAGE in output, (
        f"E0-F6-S2-T6 regression: expected stderr to contain "
        f"{SELFUPDATE_EMBEDDED_MESSAGE!r} when EMBEDDED=True, "
        f"but stderr was: {output!r}. "
        "The embedded-mode message guard in selfupdate.py Execute() is missing or broken."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- selfupdate triggers the exact bug condition (no sync calls)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sync_attr,description",
    [
        ("PreSync", "PreSync() -- first repoProject call that fails in embedded mode"),
        (
            "Sync_NetworkHalf",
            "Sync_NetworkHalf() -- network operation that requires a real repoProject",
        ),
    ],
)
def test_regression_selfupdate_embedded_does_not_call_repo_project_methods(
    monkeypatch: pytest.MonkeyPatch,
    sync_attr: str,
    description: str,
) -> None:
    """AC-TEST-002: selfupdate does not call repoProject sync methods when EMBEDDED=True.

    This test reproduces the exact bug condition from E0-F6-S2-T6: the bug
    manifested because Execute() called PreSync() and Sync_NetworkHalf() on
    self.manifest.repoProject regardless of the EMBEDDED flag. In embedded mode
    that repoProject does not exist, so these calls crash.

    If any parametrized case detects a call that should be skipped, the regression
    is confirmed and the embedded guard must be restored in selfupdate.py.

    Arrange: Set EMBEDDED=True. Track calls to each repoProject method.
    Act: Call Execute().
    Assert: The tracked method was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    call_log: list[tuple] = []
    setattr(instance.manifest.repoProject, sync_attr, lambda *a, **kw: call_log.append((a, kw)))

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert call_log == [], (
        f"E0-F6-S2-T6 regression: {sync_attr}() ({description}) was called "
        f"{len(call_log)} time(s) when EMBEDDED=True -- must not be called "
        "in embedded mode. The early-return guard in selfupdate.py Execute() "
        "is missing or placed after the repoProject access."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "post_fn_attr,flag_kwargs,description",
    [
        (
            "_PostRepoFetch",
            {"repo_upgraded": False},
            "_PostRepoFetch -- called in normal update path",
        ),
        (
            "_PostRepoUpgrade",
            {"repo_upgraded": True},
            "_PostRepoUpgrade -- called in --repo-upgraded path",
        ),
    ],
)
def test_regression_selfupdate_embedded_does_not_call_post_sync_functions(
    monkeypatch: pytest.MonkeyPatch,
    post_fn_attr: str,
    flag_kwargs: dict,
    description: str,
) -> None:
    """AC-TEST-002: selfupdate does not call post-sync functions when EMBEDDED=True.

    The _PostRepoFetch and _PostRepoUpgrade functions are part of the sync/update
    path that the embedded-mode guard must skip entirely. If either is called,
    the early-return is placed too late in Execute() or has been removed.

    Arrange: Set EMBEDDED=True. Patch the post-sync function to track calls.
    Act: Call Execute() with the relevant opt flag.
    Assert: The post-sync function was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    call_log: list[tuple] = []

    def _record(*args, **kwargs) -> None:
        call_log.append((args, kwargs))

    monkeypatch.setattr(selfupdate_mod, post_fn_attr, _record)

    instance = _make_selfupdate_instance()
    opt = _make_opt(**flag_kwargs)

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert call_log == [], (
        f"E0-F6-S2-T6 regression: {post_fn_attr}() ({description}) was called "
        f"{len(call_log)} time(s) when EMBEDDED=True -- must not be called "
        "in embedded mode. Restore the early-return guard at the top of "
        "selfupdate.py Execute()."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- selfupdate exits with non-zero status in embedded mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_selfupdate_embedded_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003: selfupdate returns exit status 1 when EMBEDDED=True.

    The embedded-mode early return must yield exactly 1 so callers receive a
    non-zero exit code signalling that selfupdate is unavailable (disabled).
    Updated per E2-F2-S2-T2: selfupdate.py Execute() now returns 1 instead
    of 0 in the embedded branch.

    Arrange: Set EMBEDDED=True.
    Act: Call Execute() and capture the return value.
    Assert: Return value is exactly 1 (non-zero, signals disabled state).
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        result = instance.Execute(opt, [])

    assert result == 1, (
        f"E0-F6-S2-T6 regression: Execute() must return 1 in embedded mode, "
        f"got {result!r}. The early-return guard in selfupdate.py must explicitly "
        "return 1 after printing the informational message."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: embedded-mode branch present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_embedded_guard_present_in_selfupdate_source() -> None:
    """AC-FUNC-001: The embedded-mode guard branch is present in selfupdate.py.

    Inspects the source of Selfupdate.Execute() to confirm:
    - The EMBEDDED flag is checked before any repoProject access.
    - The SELFUPDATE_EMBEDDED_MESSAGE is used inside Execute().

    If either check fails the guard has been structurally removed and the
    E0-F6-S2-T6 bug would regress for any selfupdate call in embedded mode.
    """
    source = inspect.getsource(Selfupdate.Execute)

    assert "EMBEDDED" in source, (
        "E0-F6-S2-T6 regression guard: the EMBEDDED flag check is no longer present "
        "in Selfupdate.Execute(). The early-return guard that prevents selfupdate "
        "from calling repoProject in embedded mode has been removed. "
        "Restore the guard in src/kanon_cli/repo/subcmds/selfupdate.py."
    )

    assert "SELFUPDATE_EMBEDDED_MESSAGE" in source, (
        "E0-F6-S2-T6 regression guard: SELFUPDATE_EMBEDDED_MESSAGE is no longer "
        "referenced inside Selfupdate.Execute(). The informational message that "
        "replaces the sync/update operations in embedded mode is missing. "
        "Restore the print(SELFUPDATE_EMBEDDED_MESSAGE, file=sys.stderr) call "
        "in src/kanon_cli/repo/subcmds/selfupdate.py."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_selfupdate_embedded_message_goes_to_stderr_not_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-CHANNEL-001: The embedded-mode message is written to stderr, not stdout.

    stdout is reserved for machine-consumable output. Informational/diagnostic
    messages must go to stderr. Verifies that the embedded-mode message does not
    leak to stdout.

    Arrange: Set EMBEDDED=True. Capture both stdout and stderr independently.
    Act: Call Execute().
    Assert: Message appears in stderr; stdout remains empty.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stdout = StringIO()
    captured_stderr = StringIO()

    with patch.object(sys, "stdout", captured_stdout):
        with patch.object(sys, "stderr", captured_stderr):
            instance.Execute(opt, [])

    stdout_content = captured_stdout.getvalue()
    stderr_content = captured_stderr.getvalue()

    assert SELFUPDATE_EMBEDDED_MESSAGE in stderr_content, (
        f"E0-F6-S2-T6 regression: SELFUPDATE_EMBEDDED_MESSAGE must appear in stderr "
        f"but was not found. stderr={stderr_content!r}"
    )

    assert SELFUPDATE_EMBEDDED_MESSAGE not in stdout_content, (
        f"E0-F6-S2-T6 regression: SELFUPDATE_EMBEDDED_MESSAGE must NOT appear in "
        f"stdout (channel discipline violation). stdout={stdout_content!r}"
    )
