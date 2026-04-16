"""Tests for selfupdate subcommand embedded mode behavior.

Verifies that:
- selfupdate.Execute() prints the informational message to stderr in embedded mode.
- selfupdate.Execute() returns exit code 0 in embedded mode.
- selfupdate.Execute() does not call sync, download, or update operations in embedded mode.
- Normal (non-embedded) selfupdate behavior is not affected.
"""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.repo.pager as repo_pager
from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod


def _make_selfupdate_instance() -> selfupdate_mod.Selfupdate:
    """Construct a minimal Selfupdate instance with required attributes mocked."""
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
    """Return a minimal MagicMock simulating parsed selfupdate options."""
    opt = MagicMock()
    opt.repo_upgraded = repo_upgraded
    opt.repo_verify = repo_verify
    return opt


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-TEST-001: embedded mode prints informational message to stderr
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_selfupdate_embedded_prints_message_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-001, AC-TEST-001: Execute must print the informational message to stderr in embedded mode."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    output = captured_stderr.getvalue()
    assert SELFUPDATE_EMBEDDED_MESSAGE in output, (
        f"Expected stderr to contain {SELFUPDATE_EMBEDDED_MESSAGE!r}, got {output!r}"
    )


@pytest.mark.unit
def test_selfupdate_embedded_message_exact_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-002: The message text must exactly match the required string."""
    expected = "selfupdate is not available -- upgrade kanon-cli instead: pipx upgrade kanon-cli"
    assert SELFUPDATE_EMBEDDED_MESSAGE == expected, (
        f"SELFUPDATE_EMBEDDED_MESSAGE must be exactly {expected!r}, got {SELFUPDATE_EMBEDDED_MESSAGE!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-003 / AC-TEST-002: embedded mode returns exit code 0
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_selfupdate_embedded_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-003, AC-TEST-002: Execute must return exit code 0 in embedded mode."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        result = instance.Execute(opt, [])

    assert result == 0, f"Execute must return 0 in embedded mode, got {result!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-004 / AC-TEST-003: embedded mode does not call sync or download ops
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_selfupdate_embedded_does_not_call_presync(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-004, AC-TEST-003: Execute must not call rp.PreSync() in embedded mode."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    presync_calls: list[tuple] = []
    instance.manifest.repoProject.PreSync = lambda: presync_calls.append(())

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert presync_calls == [], (
        f"rp.PreSync() was called {len(presync_calls)} time(s) in embedded mode -- should not be called"
    )


@pytest.mark.unit
def test_selfupdate_embedded_does_not_call_sync_network_half(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-004, AC-TEST-003: Execute must not call Sync_NetworkHalf() in embedded mode."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", True)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    sync_calls: list[tuple] = []
    instance.manifest.repoProject.Sync_NetworkHalf = lambda: sync_calls.append(())

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        instance.Execute(opt, [])

    assert sync_calls == [], (
        f"Sync_NetworkHalf() was called {len(sync_calls)} time(s) in embedded mode -- should not be called"
    )


@pytest.mark.unit
def test_selfupdate_embedded_does_not_call_post_repo_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-004, AC-TEST-003: Execute must not call _PostRepoFetch in embedded mode."""
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
        f"_PostRepoFetch was called {len(post_fetch_calls)} time(s) in embedded mode -- should not be called"
    )


@pytest.mark.unit
def test_selfupdate_embedded_does_not_call_post_repo_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-004, AC-TEST-003: Execute must not call _PostRepoUpgrade in embedded mode."""
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
        f"_PostRepoUpgrade was called {len(post_upgrade_calls)} time(s) in embedded mode -- should not be called"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-005: Normal (non-embedded) selfupdate behavior is not affected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_selfupdate_non_embedded_calls_presync(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-005: Normal mode must still call rp.PreSync()."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", False)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    presync_calls: list[tuple] = []
    instance.manifest.repoProject.PreSync = lambda: presync_calls.append(())

    mock_result = MagicMock()
    mock_result.error = None
    instance.manifest.repoProject.Sync_NetworkHalf = lambda: mock_result
    instance.manifest.repoProject.bare_git = MagicMock()

    with patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch"):
        instance.Execute(opt, [])

    assert len(presync_calls) == 1, (
        f"PreSync() must be called exactly once in non-embedded mode, got {len(presync_calls)} calls"
    )


@pytest.mark.unit
def test_selfupdate_non_embedded_does_not_print_embedded_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-FUNC-005: Normal mode must not print the embedded informational message to stderr."""
    monkeypatch.setattr(repo_pager, "EMBEDDED", False)

    instance = _make_selfupdate_instance()
    opt = _make_opt()

    mock_result = MagicMock()
    mock_result.error = None
    instance.manifest.repoProject.Sync_NetworkHalf = lambda: mock_result
    instance.manifest.repoProject.bare_git = MagicMock()

    captured_stderr = StringIO()
    with patch.object(sys, "stderr", captured_stderr):
        with patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch"):
            instance.Execute(opt, [])

    output = captured_stderr.getvalue()
    assert SELFUPDATE_EMBEDDED_MESSAGE not in output, (
        f"Embedded message must not appear in non-embedded mode, but stderr contains: {output!r}"
    )
