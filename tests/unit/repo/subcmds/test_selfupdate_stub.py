"""Unit tests for the selfupdate disabled-stub code path.

Verifies that when EMBEDDED=True, Selfupdate.Execute():
- Returns exit code 1 (AC-FUNC-001 / AC-TEST-002).
- Emits the documented message to stderr (AC-FUNC-002 / AC-TEST-002).
- Does not call any network or sync operations.

These tests exercise the disabled-stub branch of Execute() directly via
unit-level instantiation and monkeypatching -- no subprocess invocation,
no real repo directory required.

Tests are decorated with @pytest.mark.unit.
"""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

import kanon_cli.repo.pager as repo_pager
from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from kanon_cli.repo.subcmds import selfupdate as selfupdate_mod

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_selfupdate_instance() -> selfupdate_mod.Selfupdate:
    """Return a minimal Selfupdate instance with all dependencies mocked."""
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
# AC-FUNC-001 / AC-TEST-002: Execute() returns 1 in embedded (disabled) mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelfupdateStubExitCode:
    """AC-FUNC-001 / AC-TEST-002: Execute() returns 1 when EMBEDDED=True.

    The disabled-stub must return exactly 1 so that CLI callers and
    scripting consumers receive a non-zero exit code.
    """

    def test_execute_returns_one_in_embedded_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must return 1 when pager.EMBEDDED is True."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt = _make_opt()

        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            result = instance.Execute(opt, [])

        assert result == 1, f"Execute() must return 1 in embedded mode, got {result!r}"

    def test_execute_returns_one_regardless_of_repo_verify_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() returns 1 in embedded mode regardless of opt.repo_verify value."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt_verify = _make_opt(repo_verify=True)
        opt_no_verify = _make_opt(repo_verify=False)

        for opt, flag_label in [
            (opt_verify, "repo_verify=True"),
            (opt_no_verify, "repo_verify=False"),
        ]:
            captured_stderr = StringIO()
            with patch.object(sys, "stderr", captured_stderr):
                result = instance.Execute(opt, [])

            assert result == 1, f"Execute() must return 1 in embedded mode with {flag_label}, got {result!r}"

    def test_execute_returns_one_regardless_of_repo_upgraded_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() returns 1 in embedded mode regardless of opt.repo_upgraded value."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt_not_upgraded = _make_opt(repo_upgraded=False)
        opt_upgraded = _make_opt(repo_upgraded=True)

        for opt, flag_label in [
            (opt_not_upgraded, "repo_upgraded=False"),
            (opt_upgraded, "repo_upgraded=True"),
        ]:
            captured_stderr = StringIO()
            with patch.object(sys, "stderr", captured_stderr):
                result = instance.Execute(opt, [])

            assert result == 1, f"Execute() must return 1 in embedded mode with {flag_label}, got {result!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-002: message emitted to stderr in embedded mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelfupdateStubMessageEmission:
    """AC-FUNC-002: disabled-stub emits the documented message to stderr.

    Verifies both that the message appears and that it is routed to stderr
    (not stdout).
    """

    def test_execute_emits_message_to_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must emit SELFUPDATE_EMBEDDED_MESSAGE to stderr in embedded mode."""
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

    def test_execute_message_not_on_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must not emit the disabled message to stdout."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt = _make_opt()

        captured_stdout = StringIO()
        with patch.object(sys, "stdout", captured_stdout):
            instance.Execute(opt, [])

        output = captured_stdout.getvalue()
        assert SELFUPDATE_EMBEDDED_MESSAGE not in output, (
            f"Disabled message must not appear on stdout, but stdout contains: {output!r}"
        )


# ---------------------------------------------------------------------------
# Guard: no network ops in embedded (disabled) mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelfupdateStubNoNetworkOps:
    """Disabled-stub must not invoke network or sync operations.

    These guards prevent the disabled path from accidentally calling
    Sync_NetworkHalf, PreSync, or the post-fetch/upgrade hooks.
    """

    def test_execute_does_not_call_presync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must not call rp.PreSync() in embedded mode."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt = _make_opt()

        presync_calls: list = []
        instance.manifest.repoProject.PreSync = lambda: presync_calls.append(True)

        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            instance.Execute(opt, [])

        assert presync_calls == [], (
            f"rp.PreSync() must not be called in embedded mode, got {len(presync_calls)} call(s)"
        )

    def test_execute_does_not_call_sync_network_half(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must not call Sync_NetworkHalf() in embedded mode."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        instance = _make_selfupdate_instance()
        opt = _make_opt()

        sync_calls: list = []
        instance.manifest.repoProject.Sync_NetworkHalf = lambda: sync_calls.append(True)

        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            instance.Execute(opt, [])

        assert sync_calls == [], (
            f"Sync_NetworkHalf() must not be called in embedded mode, got {len(sync_calls)} call(s)"
        )

    def test_execute_does_not_call_post_repo_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute() must not call _PostRepoFetch in embedded mode."""
        monkeypatch.setattr(repo_pager, "EMBEDDED", True)

        post_fetch_calls: list = []

        def _record(*args, **kwargs) -> None:
            post_fetch_calls.append((args, kwargs))

        monkeypatch.setattr(selfupdate_mod, "_PostRepoFetch", _record)

        instance = _make_selfupdate_instance()
        opt = _make_opt()

        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            instance.Execute(opt, [])

        assert post_fetch_calls == [], (
            f"_PostRepoFetch must not be called in embedded mode, got {len(post_fetch_calls)} call(s)"
        )
