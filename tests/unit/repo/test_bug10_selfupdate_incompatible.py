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

"""Unit tests for Bug 10: selfupdate subcommand incompatible with embedded mode.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 10 -- selfupdate subcommand
incompatible with embedding. Tries to sync the "repo project" which does not
exist when running embedded. Fix: print an informational message, skip the
sync/update operations, and exit with zero status.

These tests verify the fix from the Bug 10 perspective:
- selfupdate prints an informational message when running embedded
- selfupdate does not attempt any sync or update operations when embedded
- selfupdate exits with zero status when running embedded
"""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.repo.pager as repo_pager
from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_selfupdate_instance() -> selfupdate_mod.Selfupdate:
    """Construct a minimal Selfupdate instance with required attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest and remote setup.
    All attributes accessed by Execute() are provided as MagicMock objects.

    Returns:
        A Selfupdate instance ready for Execute() invocation.
    """
    instance = selfupdate_mod.Selfupdate.__new__(selfupdate_mod.Selfupdate)
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
    """Return a minimal MagicMock simulating parsed selfupdate options.

    Args:
        repo_upgraded: Simulates the --repo-upgraded flag being set.
        repo_verify: Simulates the --no-repo-verify flag (True by default).

    Returns:
        MagicMock with repo_upgraded and repo_verify attributes set.
    """
    opt = MagicMock()
    opt.repo_upgraded = repo_upgraded
    opt.repo_verify = repo_verify
    return opt


# ---------------------------------------------------------------------------
# AC-TEST-001: selfupdate prints embedded mode informational message
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bug10_selfupdate_embedded_prints_informational_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001: selfupdate prints the embedded mode informational message.

    Bug 10 root cause: selfupdate tried to sync the repo project, which does
    not exist in embedded mode. Fix: print an informational message to stderr
    instead of attempting the sync.

    Arrange: Set EMBEDDED=True to simulate embedded execution context.
    Act: Call Execute() on a Selfupdate instance.
    Assert: The SELFUPDATE_EMBEDDED_MESSAGE appears in stderr output.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    output = captured_stderr.getvalue()
    assert SELFUPDATE_EMBEDDED_MESSAGE in output, (
        f"Bug 10 fix: expected stderr to contain {SELFUPDATE_EMBEDDED_MESSAGE!r} "
        f"in embedded mode, but stderr was: {output!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: selfupdate does not attempt any sync or update operation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bug10_selfupdate_embedded_does_not_call_presync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: selfupdate does not call PreSync() in embedded mode.

    Bug 10 root cause: PreSync() assumes a real repo project exists. When
    embedded, rp.PreSync() must never be called.

    Arrange: Set EMBEDDED=True. Track calls to repoProject.PreSync.
    Act: Call Execute().
    Assert: PreSync() was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    presync_calls: list[tuple] = []
    instance.manifest.repoProject.PreSync = lambda: presync_calls.append(())

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert presync_calls == [], (
        f"Bug 10 fix: PreSync() was called {len(presync_calls)} time(s) in embedded mode -- "
        "must not be called when embedded"
    )


@pytest.mark.unit
def test_bug10_selfupdate_embedded_does_not_call_sync_network_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: selfupdate does not call Sync_NetworkHalf() in embedded mode.

    Bug 10 root cause: Sync_NetworkHalf() requires network access and a real
    repo project. When embedded, it must never be called.

    Arrange: Set EMBEDDED=True. Track calls to repoProject.Sync_NetworkHalf.
    Act: Call Execute().
    Assert: Sync_NetworkHalf() was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    sync_calls: list[tuple] = []
    instance.manifest.repoProject.Sync_NetworkHalf = lambda: sync_calls.append(())

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert sync_calls == [], (
        f"Bug 10 fix: Sync_NetworkHalf() was called {len(sync_calls)} time(s) in embedded mode -- "
        "must not be called when embedded"
    )


@pytest.mark.unit
def test_bug10_selfupdate_embedded_does_not_call_post_repo_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: selfupdate does not call _PostRepoFetch() in embedded mode.

    Bug 10 root cause: _PostRepoFetch() performs repo verification that
    requires the repo project to be synced. It must not run when embedded.

    Arrange: Set EMBEDDED=True. Patch _PostRepoFetch to track calls.
    Act: Call Execute().
    Assert: _PostRepoFetch was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    post_fetch_calls: list[tuple] = []

    def _record_post_fetch(*args, **kwargs) -> None:
        post_fetch_calls.append((args, kwargs))

    monkeypatch.setattr(selfupdate_mod, "_PostRepoFetch", _record_post_fetch)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert post_fetch_calls == [], (
        f"Bug 10 fix: _PostRepoFetch was called {len(post_fetch_calls)} time(s) in embedded mode -- "
        "must not be called when embedded"
    )


@pytest.mark.unit
def test_bug10_selfupdate_embedded_does_not_call_post_repo_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: selfupdate does not call _PostRepoUpgrade() in embedded mode.

    Bug 10 root cause: _PostRepoUpgrade() is also part of the sync/update
    path and requires a real repo project. It must not run when embedded.

    Arrange: Set EMBEDDED=True and repo_upgraded=True. Patch _PostRepoUpgrade.
    Act: Call Execute().
    Assert: _PostRepoUpgrade was never called.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    post_upgrade_calls: list[tuple] = []

    def _record_post_upgrade(*args, **kwargs) -> None:
        post_upgrade_calls.append((args, kwargs))

    monkeypatch.setattr(selfupdate_mod, "_PostRepoUpgrade", _record_post_upgrade)

    instance = _make_selfupdate_instance()
    opt = _make_opt(repo_upgraded=True)

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert post_upgrade_calls == [], (
        f"Bug 10 fix: _PostRepoUpgrade was called {len(post_upgrade_calls)} time(s) in embedded mode -- "
        "must not be called when embedded"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: selfupdate exits with zero status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bug10_selfupdate_embedded_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003: selfupdate exits with zero status in embedded mode.

    Bug 10 root cause: If selfupdate attempted to sync and failed, it would
    raise an exception or exit non-zero. The fix must return 0 so that
    callers treating selfupdate as informational do not see an error.

    Arrange: Set EMBEDDED=True.
    Act: Call Execute() and capture the return value.
    Assert: Return value is exactly 0.
    """
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        result = instance.Execute(opt, [])

    assert result == 0, f"Bug 10 fix: Execute() must return 0 in embedded mode, got {result!r}"
