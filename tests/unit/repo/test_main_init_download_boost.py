# Copyright (C) 2024 The Android Open Source Project
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

"""Coverage boost tests for main.py, subcmds/init.py, subcmds/download.py."""

import os
import urllib.request
from unittest import mock

import pytest

from kanon_cli.repo import main
from kanon_cli.repo.error import (
    GitError,
    InvalidProjectGroupsError,
    ManifestInvalidRevisionError,
    NoManifestException,
    NoSuchProjectError,
    RepoError,
    RepoExitError,
    RepoUnhandledExceptionError,
)
from kanon_cli.repo.subcmds.download import Download, DownloadCommandError
from kanon_cli.repo.subcmds.init import Init


# ---------------------------------------------------------------------------
# main.py: _BasicAuthHandler.http_error_auth_reqed  (lines 641-660)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBasicAuthHandlerAuthReqed:
    """Tests for _BasicAuthHandler.http_error_auth_reqed."""

    def test_auth_reqed_strips_newlines(self):
        """Test that _add_header strips newlines from value."""
        handler = main._BasicAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        handler.passwd.add_password(None, "http://host/", "user", "pass")

        req = urllib.request.Request("http://host/path")
        with mock.patch.object(
            urllib.request.AbstractBasicAuthHandler,
            "http_error_auth_reqed",
            return_value=None,
        ):
            result = handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert result is None

    def test_auth_reqed_exception_with_reset_retry_count(self):
        """Test exception path calls reset_retry_count."""
        handler = main._BasicAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        handler.reset_retry_count = mock.Mock()

        req = mock.Mock()

        with mock.patch.object(
            urllib.request.AbstractBasicAuthHandler,
            "http_error_auth_reqed",
            side_effect=ValueError("test error"),
        ):
            with pytest.raises(ValueError, match="test error"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})
        handler.reset_retry_count.assert_called_once()

    def test_auth_reqed_exception_with_retried_attr(self):
        """Test exception path resets retried attribute."""
        handler = main._BasicAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        handler.retried = 5
        # Remove reset_retry_count if present
        if hasattr(handler, "reset_retry_count"):
            delattr(handler, "reset_retry_count")

        req = mock.Mock()

        with mock.patch.object(
            urllib.request.AbstractBasicAuthHandler,
            "http_error_auth_reqed",
            side_effect=ValueError("test error"),
        ):
            with pytest.raises(ValueError, match="test error"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})
        assert handler.retried == 0

    def test_auth_reqed_exception_no_reset(self):
        """Test exception path when neither reset_retry_count nor retried."""
        handler = main._BasicAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()

        # Ensure no reset mechanism exists
        for attr in ("reset_retry_count", "retried"):
            if hasattr(handler, attr):
                delattr(handler, attr)

        req = mock.Mock()

        with mock.patch.object(
            urllib.request.AbstractBasicAuthHandler,
            "http_error_auth_reqed",
            side_effect=ValueError("test error"),
        ):
            with pytest.raises(ValueError, match="test error"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})


# ---------------------------------------------------------------------------
# main.py: _DigestAuthHandler.http_error_auth_reqed  (lines 671-690)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDigestAuthHandlerAuthReqed:
    """Tests for _DigestAuthHandler.http_error_auth_reqed."""

    def test_auth_reqed_strips_newlines(self):
        """Test that _add_header strips newlines from value."""
        handler = main._DigestAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        handler.passwd.add_password(None, "http://host/", "user", "pass")

        req = urllib.request.Request("http://host/path")

        with mock.patch.object(
            urllib.request.AbstractDigestAuthHandler,
            "http_error_auth_reqed",
            return_value=None,
        ):
            result = handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert result is None

    def test_auth_reqed_exception_with_reset_retry_count(self):
        """Test exception path calls reset_retry_count."""
        handler = main._DigestAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        handler.reset_retry_count = mock.Mock()

        req = mock.Mock()

        with mock.patch.object(
            urllib.request.AbstractDigestAuthHandler,
            "http_error_auth_reqed",
            side_effect=ValueError("test error"),
        ):
            with pytest.raises(ValueError, match="test error"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})
        handler.reset_retry_count.assert_called_once()

    def test_auth_reqed_exception_calls_reset_retry(self):
        """Test exception path calls reset_retry_count on digest handler."""
        handler = main._DigestAuthHandler()
        handler.passwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        # Track that reset_retry_count gets called via the getattr path
        original_reset = handler.reset_retry_count
        call_tracker = mock.Mock(side_effect=original_reset)
        handler.reset_retry_count = call_tracker

        req = mock.Mock()

        with mock.patch.object(
            urllib.request.AbstractDigestAuthHandler,
            "http_error_auth_reqed",
            side_effect=ValueError("test error"),
        ):
            with pytest.raises(ValueError, match="test error"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})
        call_tracker.assert_called_once()


# ---------------------------------------------------------------------------
# main.py: _KerberosAuthHandler (lines 700-778)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestKerberosAuthHandlerMethods:
    """Tests for _KerberosAuthHandler methods."""

    def test_http_error_401_delegates(self):
        """Test http_error_401 delegates to http_error_auth_reqed."""
        handler = main._KerberosAuthHandler()
        handler.http_error_auth_reqed = mock.Mock(return_value="response")

        req = mock.Mock()
        req.get_host.return_value = "example.com"

        result = handler.http_error_401(req, None, 401, "Unauth", {})
        handler.http_error_auth_reqed.assert_called_once_with("www-authenticate", "example.com", req, {})
        assert result == "response"

    def test_http_error_auth_reqed_too_many_retries(self):
        """Test that too many retries raises HTTPError."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.GSSError = type("GSSError", (Exception,), {})
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.AUTH_GSS_CONTINUE = 0

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.retried = 4
            handler.context = None
            handler._negotiate_get_authdata = mock.Mock(return_value="authdata")
            req = mock.Mock()
            req.get_full_url.return_value = "http://host/path"

            with pytest.raises(urllib.request.HTTPError):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})

    def test_http_error_auth_reqed_success(self):
        """Test successful negotiation."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.GSSError = type("GSSError", (Exception,), {})
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.AUTH_GSS_CONTINUE = 0

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.retried = 0
            handler.context = None
            handler._negotiate_get_authdata = mock.Mock(return_value="authdata")
            handler._negotiate_get_svctk = mock.Mock(return_value="Negotiate token")
            handler._validate_response = mock.Mock(return_value=True)
            handler.parent = mock.Mock()
            mock_response = mock.Mock()
            mock_response.info.return_value = {}
            handler.parent.open.return_value = mock_response

            req = mock.Mock()
            result = handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert result == mock_response

    def test_http_error_auth_reqed_svctk_none(self):
        """Test negotiation returns None when svctk is None."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.GSSError = type("GSSError", (Exception,), {})
        mock_kerberos.AUTH_GSS_COMPLETE = 1

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.retried = 0
            handler.context = None
            handler._negotiate_get_authdata = mock.Mock(return_value="authdata")
            handler._negotiate_get_svctk = mock.Mock(return_value=None)
            handler._clean_context = mock.Mock()

            req = mock.Mock()
            result = handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert result is None

    def test_http_error_auth_reqed_gss_error(self):
        """Test GSSError returns None."""
        mock_kerberos = mock.MagicMock()
        GSSError = type("GSSError", (Exception,), {})
        mock_kerberos.GSSError = GSSError

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.retried = 0
            handler.context = None
            handler._negotiate_get_authdata = mock.Mock(side_effect=GSSError("gss fail"))
            handler._clean_context = mock.Mock()

            req = mock.Mock()
            result = handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert result is None

    def test_http_error_auth_reqed_generic_exception(self):
        """Test generic exception resets retry and re-raises."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.GSSError = type("GSSError", (Exception,), {})

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.retried = 2
            handler.context = None
            handler._negotiate_get_authdata = mock.Mock(side_effect=RuntimeError("unexpected"))
            handler._clean_context = mock.Mock()

            req = mock.Mock()
            with pytest.raises(RuntimeError, match="unexpected"):
                handler.http_error_auth_reqed("www-authenticate", "host", req, {})
            assert handler.retried == 0

    def test_negotiate_get_authdata_with_negotiate(self):
        """Test _negotiate_get_authdata finds Negotiate header."""
        handler = main._KerberosAuthHandler()
        headers = {"www-authenticate": "Negotiate dGVzdA=="}
        result = handler._negotiate_get_authdata("www-authenticate", headers)
        assert result == "dGVzdA=="

    def test_negotiate_get_authdata_no_header(self):
        """Test _negotiate_get_authdata returns None when no header."""
        handler = main._KerberosAuthHandler()
        headers = {}
        result = handler._negotiate_get_authdata("www-authenticate", headers)
        assert result is None

    def test_negotiate_get_authdata_no_negotiate(self):
        """Test _negotiate_get_authdata returns None without negotiate."""
        handler = main._KerberosAuthHandler()
        headers = {"www-authenticate": "Basic realm=test"}
        result = handler._negotiate_get_authdata("www-authenticate", headers)
        assert result is None

    def test_negotiate_get_authdata_multiple_schemes(self):
        """Test _negotiate_get_authdata with multiple schemes."""
        handler = main._KerberosAuthHandler()
        headers = {"www-authenticate": "Basic realm=test, Negotiate tokendata"}
        result = handler._negotiate_get_authdata("www-authenticate", headers)
        assert result == "tokendata"

    def test_negotiate_get_svctk_none_authdata(self):
        """Test _negotiate_get_svctk returns None when authdata is None."""
        handler = main._KerberosAuthHandler()
        result = handler._negotiate_get_svctk("HTTP@host", None)
        assert result is None

    def test_negotiate_get_svctk_success(self):
        """Test _negotiate_get_svctk successful negotiation."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.AUTH_GSS_CONTINUE = 0
        mock_kerberos.authGSSClientInit.return_value = (1, "ctx")
        mock_kerberos.authGSSClientStep.return_value = 0
        mock_kerberos.authGSSClientResponse.return_value = "response_token"

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            result = handler._negotiate_get_svctk("HTTP@host", "authdata")
            assert result == "Negotiate response_token"

    def test_negotiate_get_svctk_init_fail(self):
        """Test _negotiate_get_svctk fails on init."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.authGSSClientInit.return_value = (-1, "ctx")

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            result = handler._negotiate_get_svctk("HTTP@host", "authdata")
            assert result is None

    def test_negotiate_get_svctk_step_fail(self):
        """Test _negotiate_get_svctk fails on step."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.AUTH_GSS_CONTINUE = 0
        mock_kerberos.authGSSClientInit.return_value = (1, "ctx")
        mock_kerberos.authGSSClientStep.return_value = -1

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            result = handler._negotiate_get_svctk("HTTP@host", "authdata")
            assert result is None

    def test_validate_response_none(self):
        """Test _validate_response returns None for None authdata."""
        handler = main._KerberosAuthHandler()
        result = handler._validate_response(None)
        assert result is None

    def test_validate_response_complete(self):
        """Test _validate_response returns True on AUTH_GSS_COMPLETE."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.authGSSClientStep.return_value = 1

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.context = "ctx"
            result = handler._validate_response("authdata")
            assert result is True

    def test_validate_response_incomplete(self):
        """Test _validate_response returns None when not complete."""
        mock_kerberos = mock.MagicMock()
        mock_kerberos.AUTH_GSS_COMPLETE = 1
        mock_kerberos.authGSSClientStep.return_value = 0

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.context = "ctx"
            result = handler._validate_response("authdata")
            assert result is None

    def test_clean_context_with_context(self):
        """Test _clean_context cleans up when context exists."""
        mock_kerberos = mock.MagicMock()

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.context = "ctx"
            handler._clean_context()
            mock_kerberos.authGSSClientClean.assert_called_once_with("ctx")
            assert handler.context is None

    def test_clean_context_without_context(self):
        """Test _clean_context is a no-op when context is None."""
        mock_kerberos = mock.MagicMock()

        with mock.patch.object(main, "kerberos", mock_kerberos):
            handler = main._KerberosAuthHandler()
            handler.context = None
            handler._clean_context()
            mock_kerberos.authGSSClientClean.assert_not_called()


# ---------------------------------------------------------------------------
# main.py: _RunLong submanifest_path (line 306)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRunLongSubmanifestPath:
    """Tests for _RunLong with submanifest_path set."""

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_runlong_with_submanifest_path(self, mock_editor, mock_color, mock_client):
        """Test _RunLong creates submanifest repo client."""
        repo = main._Repo("/test/repodir")

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = "sub/manifest"

        mock_git_log = mock.MagicMock()
        # Unknown command so it returns 1 early
        result = repo._RunLong("unknowncmd", mock_gopts, [], mock_git_log)
        assert result == 1

        # Check RepoClient was called with submanifest_path
        assert mock_client.call_count >= 2


# ---------------------------------------------------------------------------
# main.py: _RunLong pager logic (lines 344-352)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRunLongPagerLogic:
    """Tests for _RunLong pager handling."""

    def _setup_cmd_and_repo(self):
        repo = main._Repo("/test/repodir")
        mock_cmd = mock.MagicMock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (
            mock.MagicMock(),
            [],
        )
        copts = mock_cmd.OptionParser.parse_args.return_value[0]
        copts.this_manifest_only = True
        copts.outer_manifest = False
        mock_cmd.ReadEnvironmentOptions.return_value = copts
        mock_cmd.Execute.return_value = 0
        mock_cmd.event_log.Add.return_value = "event"
        repo.commands = {"testcmd": lambda **kwargs: mock_cmd}
        return repo, mock_cmd, copts

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    @mock.patch("kanon_cli.repo.main.RunPager")
    @mock.patch("kanon_cli.repo.main.isinstance", return_value=False)
    def test_pager_explicit_true(
        self,
        mock_isinstance_fn,
        mock_run_pager,
        mock_time,
        mock_editor,
        mock_color,
        mock_client,
    ):
        """Test pager runs when gopts.pager is True."""
        repo, mock_cmd, copts = self._setup_cmd_and_repo()
        # Override isinstance to return False for InteractiveCommand
        mock_cmd.__class__ = type("NonInteractive", (), {})

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = True
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_pager_config_fallback(self, mock_time, mock_editor, mock_color, mock_client):
        """Test pager uses config when gopts.pager is None."""
        repo, mock_cmd, copts = self._setup_cmd_and_repo()

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = None
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_cmd.client.globalConfig.GetBoolean.return_value = False
        mock_git_log = mock.MagicMock()
        repo._RunLong("testcmd", mock_gopts, [], mock_git_log)


# ---------------------------------------------------------------------------
# main.py: execute_command_helper branches (lines 372-398)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRunLongMultiManifest:
    """Tests for _RunLong execute_command_helper multi-manifest."""

    def _make_repo_with_cmd(self, multi_manifest=False):
        repo = main._Repo("/test/repodir")
        mock_cmd = mock.MagicMock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.manifest.is_submanifest = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = multi_manifest
        copts = mock.MagicMock()
        copts.this_manifest_only = False
        copts.outer_manifest = False
        mock_cmd.OptionParser.parse_args.return_value = (copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = copts
        mock_cmd.Execute.return_value = 0
        mock_cmd.event_log.Add.return_value = "event"
        repo.commands = {"testcmd": lambda **kwargs: mock_cmd}
        return repo, mock_cmd, copts

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_non_multi_manifest_no_submanifests(self, mock_time, mock_editor, mock_color, mock_client):
        """Test non-multi-manifest command with no submanifests."""
        repo, mock_cmd, copts = self._make_repo_with_cmd(multi_manifest=False)
        mock_client.return_value.manifest.submanifests = {}
        mock_cmd.manifest.submanifests = {}

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result == 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_outer_manifest_is_submanifest(self, mock_time, mock_editor, mock_color, mock_client):
        """Test outer_manifest=True with submanifest re-runs at outer."""
        repo, mock_cmd, copts = self._make_repo_with_cmd(multi_manifest=False)
        copts.outer_manifest = True
        mock_client.return_value.manifest.is_submanifest = True

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        # This will call self._Run which we mock
        with mock.patch.object(repo, "_Run", return_value=0) as mock_run:
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
            mock_run.assert_called_once()

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_non_multi_with_submanifests(self, mock_time, mock_editor, mock_color, mock_client):
        """Test non-multi-manifest command iterates submanifests."""
        repo, mock_cmd, copts = self._make_repo_with_cmd(multi_manifest=False)
        # Add hasattr mocking so code thinks copts has manifest_url etc
        copts.manifest_url = "http://example.com"
        copts.manifest_name = "default.xml"
        copts.manifest_branch = "main"

        mock_sub = mock.MagicMock()
        mock_sub.ToSubmanifestSpec.return_value = mock.MagicMock(
            manifestUrl="http://example.com/sub",
            manifestName="sub.xml",
            revision="dev",
        )
        mock_sub.repo_client.path_prefix = "sub/path"

        # The _RunLong code uses repo_client.manifest.submanifests
        # repo_client is the RepoClient instance (mock_client.return_value)
        mock_client.return_value.manifest.submanifests = {"sub1": mock_sub}

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with mock.patch.object(repo, "_Run", return_value=0) as mock_run:
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# main.py: execute_command exception logging (lines 414-429)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRunLongExceptionLogging:
    """Tests for execute_command exception logging in _RunLong."""

    def _make_repo_setup(self):
        repo = main._Repo("/test/repodir")
        mock_cmd = mock.MagicMock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        copts = mock.MagicMock()
        copts.this_manifest_only = True
        copts.outer_manifest = False
        mock_cmd.OptionParser.parse_args.return_value = (copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = copts
        mock_cmd.event_log.Add.return_value = "event"
        repo.commands = {"testcmd": lambda **kwargs: mock_cmd}
        return repo, mock_cmd

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_repo_unhandled_exception_error(self, mock_time, mock_editor, mock_color, mock_client):
        """Test RepoUnhandledExceptionError logs inner error type."""
        repo, mock_cmd = self._make_repo_setup()
        inner = ValueError("inner error")
        mock_cmd.Execute.side_effect = RepoUnhandledExceptionError(inner)

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(RepoUnhandledExceptionError):
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_repo_exit_error_with_aggregate_errors(self, mock_time, mock_editor, mock_color, mock_client):
        """Test RepoExitError with aggregate_errors logs each error."""
        repo, mock_cmd = self._make_repo_setup()
        err1 = RepoError("err1", project="proj1")
        err2 = ValueError("err2")
        mock_cmd.Execute.side_effect = RepoExitError(aggregate_errors=[err1, err2])

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(RepoExitError):
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

        # Verify ErrorEvent was called for aggregate errors
        assert mock_git_log.ErrorEvent.call_count >= 2

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_system_exit_zero(self, mock_time, mock_editor, mock_color, mock_client):
        """Test SystemExit(0) is not treated as error."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = SystemExit(0)

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(SystemExit):
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_system_exit_nonzero(self, mock_time, mock_editor, mock_color, mock_client):
        """Test SystemExit with non-zero code is re-raised."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = SystemExit(42)

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert exc_info.value.code == 42

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_generic_exception_returns_1(self, mock_time, mock_editor, mock_color, mock_client):
        """Test generic Exception sets result=1 and re-raises."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = RuntimeError("unexpected")

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(RuntimeError, match="unexpected"):
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_no_such_project_no_name(self, mock_time, mock_editor, mock_color, mock_client):
        """Test NoSuchProjectError with no name."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = NoSuchProjectError()

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result != 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_invalid_project_groups_no_name(self, mock_time, mock_editor, mock_color, mock_client):
        """Test InvalidProjectGroupsError with no name."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = InvalidProjectGroupsError()

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result != 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_invalid_project_groups_with_name(self, mock_time, mock_editor, mock_color, mock_client):
        """Test InvalidProjectGroupsError with project name."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = InvalidProjectGroupsError(name="myproj")

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result != 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_no_manifest_in_execute(self, mock_time, mock_editor, mock_color, mock_client):
        """Test NoManifestException during Execute."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = NoManifestException(path="/path", reason="missing")

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result != 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_manifest_invalid_revision_error(self, mock_time, mock_editor, mock_color, mock_client):
        """Test ManifestInvalidRevisionError during Execute."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = ManifestInvalidRevisionError("bad revision")

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result != 0

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_event_log_write(self, mock_time, mock_editor, mock_color, mock_client):
        """Test event_log.Write is called when gopts.event_log is set."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.return_value = 0

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = "/tmp/event.log"
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

        mock_cmd.event_log.Write.assert_called_once()

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_repo_exit_error_in_runlong(self, mock_time, mock_editor, mock_color, mock_client):
        """Test RepoExitError is re-raised from _RunLong."""
        repo, mock_cmd = self._make_repo_setup()
        mock_cmd.Execute.side_effect = RepoExitError(exit_code=5)

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        with pytest.raises(RepoExitError):
            repo._RunLong("testcmd", mock_gopts, [], mock_git_log)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_mirror_safe_check(self, mock_time, mock_editor, mock_color, mock_client):
        """Test that non-MirrorSafe command with mirror repo returns 1."""
        repo = main._Repo("/test/repodir")
        mock_cmd = mock.MagicMock()
        mock_cmd.manifest.IsMirror = True
        # Make isinstance return False for MirrorSafeCommand
        mock_cmd.__class__ = type("NonMirrorSafe", (), {})
        repo.commands = {"testcmd": lambda **kwargs: mock_cmd}

        mock_gopts = mock.MagicMock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_time.time.return_value = 0.0

        mock_git_log = mock.MagicMock()
        result = repo._RunLong("testcmd", mock_gopts, [], mock_git_log)
        assert result == 1


# ---------------------------------------------------------------------------
# subcmds/download.py: _ParseChangeIds (lines 75-128)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestParseChangeIds:
    """Tests for Download._ParseChangeIds method."""

    def _make_download(self):
        cmd = Download()
        cmd.manifest = mock.MagicMock()
        return cmd

    def test_parse_change_ids_empty_args(self):
        """Test _ParseChangeIds with empty args calls Usage."""
        cmd = self._make_download()
        opt = mock.MagicMock()

        with mock.patch.object(cmd, "Usage", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                cmd._ParseChangeIds(opt, [])

    def test_parse_change_ids_with_patchset(self):
        """Test _ParseChangeIds with explicit patchset."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.name = "test-project"
        cmd.GetProjects = mock.Mock(return_value=[mock_project])

        result = cmd._ParseChangeIds(opt, ["12345/3"])

        assert len(result) == 1
        project, chg_id, ps_id = result[0]
        assert project == mock_project
        assert chg_id == 12345
        assert ps_id == 3

    def test_parse_change_ids_auto_patchset_with_ls_remote(self):
        """Test _ParseChangeIds resolves latest patchset from ls-remote."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.name = "test-project"
        mock_project._LsRemote.return_value = (
            "abc123\trefs/changes/45/12345/1\ndef456\trefs/changes/45/12345/5\nghi789\trefs/changes/45/12345/3\n"
        )
        cmd.GetProjects = mock.Mock(return_value=[mock_project])

        result = cmd._ParseChangeIds(opt, ["12345"])

        assert len(result) == 1
        _, chg_id, ps_id = result[0]
        assert chg_id == 12345
        assert ps_id == 5  # Should pick the max patchset

    def test_parse_change_ids_no_ls_remote_output(self):
        """Test _ParseChangeIds defaults to patchset 1 when ls-remote empty."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.name = "test-project"
        mock_project._LsRemote.return_value = ""
        cmd.GetProjects = mock.Mock(return_value=[mock_project])

        result = cmd._ParseChangeIds(opt, ["12345"])

        assert len(result) == 1
        _, chg_id, ps_id = result[0]
        assert chg_id == 12345
        assert ps_id == 1

    def test_parse_change_ids_project_then_change(self):
        """Test _ParseChangeIds with project arg then change number."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.name = "myproject"
        cmd.GetProjects = mock.Mock(return_value=[mock_project])

        result = cmd._ParseChangeIds(opt, ["myproject", "99/2"])

        assert len(result) == 1
        project, chg_id, ps_id = result[0]
        assert project == mock_project
        assert chg_id == 99
        assert ps_id == 2

    def test_parse_change_ids_too_many_projects(self):
        """Test _ParseChangeIds raises when project matches too many."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        proj1 = mock.MagicMock()
        proj1.name = "proj1"
        proj2 = mock.MagicMock()
        proj2.name = "proj2"

        # First call returns two projects for the ambiguous arg
        # GetProjects(".") raises NoSuchProjectError
        def get_projects_side_effect(arg, **kwargs):
            if arg == ".":
                raise NoSuchProjectError()
            return [proj1, proj2]

        cmd.GetProjects = mock.Mock(side_effect=get_projects_side_effect)

        with pytest.raises(NoSuchProjectError):
            cmd._ParseChangeIds(opt, ["ambiguous"])

    def test_parse_change_ids_too_many_projects_cwd_match(self):
        """Test _ParseChangeIds resolves when cwd matches one project."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        proj1 = mock.MagicMock()
        proj1.name = "proj1"
        proj2 = mock.MagicMock()
        proj2.name = "proj2"

        def get_projects_side_effect(arg, **kwargs):
            if arg == ".":
                return [proj1]
            return [proj1, proj2]

        cmd.GetProjects = mock.Mock(side_effect=get_projects_side_effect)

        # proj1 is in the list so it's accepted
        result = cmd._ParseChangeIds(opt, ["ambiguous"])
        assert result == []

    def test_parse_change_ids_single_project_match(self):
        """Test _ParseChangeIds with single project match."""
        cmd = self._make_download()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.name = "only-one"
        cmd.GetProjects = mock.Mock(return_value=[mock_project])

        result = cmd._ParseChangeIds(opt, ["only-one"])
        assert result == []


# ---------------------------------------------------------------------------
# subcmds/download.py: Execute & _ExecuteHelper (lines 143-212)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDownloadExecute:
    """Tests for Download.Execute and _ExecuteHelper."""

    def _make_download(self):
        cmd = Download()
        cmd.manifest = mock.MagicMock()
        return cmd

    def test_execute_wraps_non_repo_exception(self):
        """Test Execute wraps non-RepoExitError in DownloadCommandError."""
        cmd = self._make_download()
        cmd._ExecuteHelper = mock.Mock(side_effect=ValueError("unexpected"))

        with pytest.raises(DownloadCommandError):
            cmd.Execute(mock.MagicMock(), [])

    def test_execute_passes_repo_exit_error(self):
        """Test Execute re-raises RepoExitError directly."""
        cmd = self._make_download()
        cmd._ExecuteHelper = mock.Mock(side_effect=RepoExitError(exit_code=5))

        with pytest.raises(RepoExitError):
            cmd.Execute(mock.MagicMock(), [])

    def test_execute_helper_already_merged(self):
        """Test _ExecuteHelper skips already merged changes."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = []
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        # Should not call any checkout/cherrypick methods
        mock_project._CherryPick.assert_not_called()
        mock_project._Checkout.assert_not_called()

    def test_execute_helper_multiple_commits(self):
        """Test _ExecuteHelper logs warning for multiple commits."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1", "commit2", "commit3"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._Checkout.assert_called_once_with("commit1")

    def test_execute_helper_checkout_mode(self):
        """Test _ExecuteHelper in checkout mode."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._Checkout.assert_called_once_with("commit1")

    def test_execute_helper_checkout_with_branch(self):
        """Test _ExecuteHelper in checkout mode with branch."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = "my-branch"

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project.StartBranch.assert_called_once_with("my-branch", revision="commit1")

    def test_execute_helper_cherrypick_mode(self):
        """Test _ExecuteHelper in cherry-pick mode."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = True
        opt.ffonly = False
        opt.record_origin = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._CherryPick.assert_called_once_with("commit1", ffonly=False, record_origin=False)

    def test_execute_helper_cherrypick_with_branch(self):
        """Test _ExecuteHelper cherry-pick with branch starts branch first."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = True
        opt.ffonly = False
        opt.record_origin = False
        opt.branch = "feature"

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project.StartBranch.assert_called_once_with("feature")
        mock_project._CherryPick.assert_called_once()

    def test_execute_helper_revert_mode(self):
        """Test _ExecuteHelper in revert mode."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = True
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._Revert.assert_called_once_with("commit1")

    def test_execute_helper_revert_no_commits_still_proceeds(self):
        """Test _ExecuteHelper revert proceeds even with no commits."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = []
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = True
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._Revert.assert_called_once_with("commit1")

    def test_execute_helper_ffonly_mode(self):
        """Test _ExecuteHelper in fast-forward mode."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = True
        opt.branch = None

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project._FastForward.assert_called_once_with("commit1", ffonly=True)

    def test_execute_helper_git_error(self):
        """Test _ExecuteHelper raises GitError."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl
        mock_project._Checkout.side_effect = GitError("checkout failed")

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = False
        opt.branch = None

        with pytest.raises(GitError, match="checkout failed"):
            cmd._ExecuteHelper(opt, ["100/1"])

    def test_execute_helper_ffonly_with_branch(self):
        """Test _ExecuteHelper fast-forward with branch creates branch."""
        cmd = self._make_download()
        mock_project = mock.MagicMock()
        mock_project.name = "proj"
        dl = mock.MagicMock()
        dl.commits = ["commit1"]
        dl.commit = "commit1"
        mock_project.DownloadPatchSet.return_value = dl

        cmd._ParseChangeIds = mock.Mock(return_value=[(mock_project, 100, 1)])

        opt = mock.MagicMock()
        opt.revert = False
        opt.cherrypick = False
        opt.ffonly = True
        opt.branch = "ff-branch"

        cmd._ExecuteHelper(opt, ["100/1"])
        mock_project.StartBranch.assert_called_once_with("ff-branch")
        mock_project._FastForward.assert_called_once()


# ---------------------------------------------------------------------------
# subcmds/init.py: ValidateOptions (lines 298-341)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestInitValidateOptionsDetailed:
    """Tests for Init.ValidateOptions on specific branches."""

    def test_validate_reference_expansion(self):
        """Test ValidateOptions expands ~ in reference path."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = "~/my-reference"
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = "http://example.com"

        cmd.ValidateOptions(opt, [])
        assert opt.reference == os.path.expanduser("~/my-reference")

    def test_validate_mirror_and_archive_conflict(self):
        """Test ValidateOptions rejects mirror + archive."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = True
        opt.archive = True
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_mirror_and_superproject_conflict(self):
        """Test ValidateOptions rejects mirror + superproject."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = True
        opt.archive = False
        opt.use_superproject = True
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_archive_and_superproject_conflict(self):
        """Test ValidateOptions rejects archive + superproject."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = True
        opt.use_superproject = True
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_standalone_with_manifest_branch(self):
        """Test ValidateOptions rejects standalone + manifest-branch."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = True
        opt.manifest_branch = "main"
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_standalone_with_manifest_name(self):
        """Test ValidateOptions rejects standalone + manifest-name."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = True
        opt.manifest_branch = None
        opt.manifest_name = "custom.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_upstream_branch_without_branch(self):
        """Test ValidateOptions rejects upstream-branch without branch."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = "upstream/main"
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_url_from_positional_arg(self):
        """Test ValidateOptions takes URL from positional args."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        args = ["http://example.com/manifest.git"]
        cmd.ValidateOptions(opt, args)
        assert opt.manifest_url == "http://example.com/manifest.git"
        assert args == []

    def test_validate_url_arg_and_option_conflict(self):
        """Test ValidateOptions rejects URL arg when --manifest-url set."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = "http://existing.com"

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, ["http://another.com"])

    def test_validate_too_many_args(self):
        """Test ValidateOptions rejects too many positional args."""
        cmd = Init()
        opt = mock.MagicMock()
        opt.reference = None
        opt.mirror = False
        opt.archive = False
        opt.use_superproject = None
        opt.standalone_manifest = False
        opt.manifest_branch = None
        opt.manifest_name = "default.xml"
        opt.manifest_upstream_branch = None
        opt.manifest_url = None

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, ["url1", "url2"])


# ---------------------------------------------------------------------------
# subcmds/init.py: Execute (lines 344-410)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestInitExecuteMethod:
    """Tests for Init.Execute method."""

    def _make_init_cmd(self):
        cmd = Init()
        cmd.manifest = mock.MagicMock()
        cmd.client = mock.MagicMock()
        cmd.git_event_log = mock.MagicMock()
        return cmd

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    def test_execute_basic(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute basic path (non-interactive)."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False
        cmd.manifest.IsMirror = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = False
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()
        cmd._DisplayResult = mock.Mock()

        cmd.Execute(opt, [])

        cmd._SyncManifest.assert_called_once_with(opt)
        cmd._DisplayResult.assert_called_once()

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    def test_execute_with_repo_url(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute handles --repo-url."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False

        opt = mock.MagicMock()
        opt.repo_url = "http://new-repo.com"
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = True
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()

        cmd.Execute(opt, [])

        remote = cmd.manifest.repoProject.GetRemote.return_value
        assert remote.url == "http://new-repo.com"
        remote.Save.assert_called_once()

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    @mock.patch("os.path.isdir", return_value=True)
    def test_execute_with_repo_rev(
        self,
        mock_isdir,
        mock_isatty,
        mock_git_require,
        mock_wrapper_dir,
        mock_wrapper,
    ):
        """Test Execute handles --repo-rev."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        wrapper_instance = mock_wrapper.return_value
        wrapper_instance.Requirements.from_dir.return_value = mock.MagicMock()
        wrapper_instance.check_repo_rev.return_value = (
            "refs/heads/main",
            "abc123",
        )
        cmd.manifest.manifestProject.Exists = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = "v2.0"
        opt.repo_verify = True
        opt.worktree = False
        opt.quiet = True
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()

        cmd.Execute(opt, [])

        wrapper_instance.check_repo_rev.assert_called_once()

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    @mock.patch("os.path.isdir", return_value=True)
    def test_execute_repo_rev_clone_failure(
        self,
        mock_isdir,
        mock_isatty,
        mock_git_require,
        mock_wrapper_dir,
        mock_wrapper,
    ):
        """Test Execute handles CloneFailure from check_repo_rev."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        wrapper_instance = mock_wrapper.return_value
        wrapper_instance.Requirements.from_dir.return_value = mock.MagicMock()
        wrapper_instance.CloneFailure = type("CloneFailure", (Exception,), {})
        wrapper_instance.check_repo_rev.side_effect = wrapper_instance.CloneFailure("clone fail")
        cmd.manifest.manifestProject.Exists = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = "bad-rev"
        opt.repo_verify = True
        opt.worktree = False
        opt.quiet = True
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()

        with pytest.raises(RepoUnhandledExceptionError):
            cmd.Execute(opt, [])

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=True)
    def test_execute_interactive_configure_user(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute runs user configuration in interactive mode."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = True
        cmd.manifest.IsMirror = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = False
        opt.config_name = True

        cmd._SyncManifest = mock.Mock()
        cmd._ShouldConfigureUser = mock.Mock(return_value=False)
        cmd._ConfigureUser = mock.Mock()
        cmd._ConfigureColor = mock.Mock()
        cmd._DisplayResult = mock.Mock()

        cmd.Execute(opt, [])

        cmd._ConfigureUser.assert_called_once_with(opt)
        cmd._ConfigureColor.assert_called_once()

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    def test_execute_worktree_requires_git_2_15(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute calls git_require for worktree mode."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = True
        opt.quiet = True
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()

        cmd.Execute(opt, [])

        # Check git_require was called with (2, 15, 0)
        calls = mock_git_require.call_args_list
        worktree_call = [c for c in calls if len(c[0]) > 0 and c[0][0] == (2, 15, 0)]
        assert len(worktree_call) == 1

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    def test_execute_existing_checkout_prints_notice(
        self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper
    ):
        """Test Execute prints notice for existing checkout."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = True
        cmd.manifest.topdir = "/workspace/repo"

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = False
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()
        cmd._DisplayResult = mock.Mock()

        with mock.patch("builtins.print") as mock_print:
            cmd.Execute(opt, [])
            print_calls = [str(c) for c in mock_print.call_args_list]
            reuse_msg = any("reusing" in s for s in print_calls)
            assert reuse_msg

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=False)
    def test_execute_soft_git_version_warning(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute warns when git version is below soft minimum."""
        cmd = self._make_init_cmd()

        # First call (hard check): True, second call (soft check): False
        mock_git_require.side_effect = [True, False, True]
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = True
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()

        with mock.patch("kanon_cli.repo.subcmds.init.logger") as mock_logger:
            cmd.Execute(opt, [])
            mock_logger.warning.assert_called()

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=True)
    def test_execute_interactive_should_configure_user(
        self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper
    ):
        """Test Execute uses _ShouldConfigureUser when config_name=False."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False
        cmd.manifest.IsMirror = False

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = False
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()
        cmd._ShouldConfigureUser = mock.Mock(return_value=True)
        cmd._ConfigureUser = mock.Mock()
        cmd._ConfigureColor = mock.Mock()
        cmd._DisplayResult = mock.Mock()

        cmd.Execute(opt, [])

        cmd._ShouldConfigureUser.assert_called_once()
        cmd._ConfigureUser.assert_called_once_with(opt)

    @mock.patch("kanon_cli.repo.subcmds.init.Wrapper")
    @mock.patch("kanon_cli.repo.subcmds.init.WrapperDir")
    @mock.patch("kanon_cli.repo.subcmds.init.git_require")
    @mock.patch("os.isatty", return_value=True)
    def test_execute_mirror_skips_user_config(self, mock_isatty, mock_git_require, mock_wrapper_dir, mock_wrapper):
        """Test Execute skips user configuration for mirror repos."""
        cmd = self._make_init_cmd()
        mock_git_require.return_value = True
        mock_wrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False
        cmd.manifest.IsMirror = True

        opt = mock.MagicMock()
        opt.repo_url = None
        opt.repo_rev = None
        opt.worktree = False
        opt.quiet = False
        opt.config_name = False

        cmd._SyncManifest = mock.Mock()
        cmd._ShouldConfigureUser = mock.Mock()
        cmd._ConfigureUser = mock.Mock()
        cmd._ConfigureColor = mock.Mock()
        cmd._DisplayResult = mock.Mock()

        cmd.Execute(opt, [])

        cmd._ShouldConfigureUser.assert_not_called()
        cmd._ConfigureUser.assert_not_called()
        cmd._ConfigureColor.assert_not_called()


# ---------------------------------------------------------------------------
# download.py: ValidateOptions (lines 131-140)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDownloadValidateOptionsDetailed:
    """Tests for Download.ValidateOptions edge cases."""

    def test_validate_record_origin_without_cherrypick(self):
        """Test -x without -c raises error."""
        cmd = Download()
        opt = mock.MagicMock()
        opt.record_origin = True
        opt.cherrypick = False
        opt.ffonly = False

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_record_origin_with_ffonly(self):
        """Test -x and --ff conflict."""
        cmd = Download()
        opt = mock.MagicMock()
        opt.record_origin = True
        opt.cherrypick = True
        opt.ffonly = True

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    def test_validate_cherrypick_with_record_origin_ok(self):
        """Test -c -x is valid."""
        cmd = Download()
        opt = mock.MagicMock()
        opt.record_origin = True
        opt.cherrypick = True
        opt.ffonly = False

        # Should not raise
        cmd.ValidateOptions(opt, [])
