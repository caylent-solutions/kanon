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

"""Unit tests for git_config.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.git_config import GetSchemeFromUrl, GetUrlCookieFile, GitConfig, Remote, Branch, RefSpec


class TestRemoteClass:
    """Test Remote class methods."""

    @pytest.mark.unit
    def test_remote_init(self):
        """Test Remote initialization."""
        mock_config = mock.MagicMock()
        mock_config._Get = mock.MagicMock(return_value=None)
        with mock.patch.object(Remote, "_Get", return_value=[]):
            remote = Remote(mock_config, "origin")
            assert remote.name == "origin"

    @pytest.mark.unit
    def test_remote_url_property(self):
        """Test Remote url property."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "https://example.com/repo.git",
                "pushurl": None,
                "review": None,
                "projectname": None,
                "fetch": [],
            }.get(key, None),
        ):
            remote = Remote(mock_config, "origin")
            assert remote.url == "https://example.com/repo.git"

    @pytest.mark.unit
    def test_remote_push_url(self):
        """Test Remote pushUrl property."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "https://example.com/repo.git",
                "pushurl": "ssh://example.com/repo.git",
                "review": None,
                "projectname": None,
                "fetch": [],
            }.get(key, None),
        ):
            remote = Remote(mock_config, "origin")
            assert remote.pushUrl == "ssh://example.com/repo.git"

    @pytest.mark.unit
    def test_remote_review(self):
        """Test Remote review property."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "https://example.com/repo.git",
                "pushurl": None,
                "review": "https://gerrit.example.com",
                "projectname": None,
                "fetch": [],
            }.get(key, None),
        ):
            remote = Remote(mock_config, "origin")
            assert remote.review == "https://gerrit.example.com"

    @pytest.mark.unit
    def test_remote_fetch_refspecs(self):
        """Test Remote fetch refspecs."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "https://example.com/repo.git",
                "pushurl": None,
                "review": None,
                "projectname": None,
                "fetch": ["+refs/heads/*:refs/remotes/origin/*"]
                if kwargs.get("all_keys")
                else "+refs/heads/*:refs/remotes/origin/*",
            }.get(key, []),
        ):
            remote = Remote(mock_config, "origin")
            assert len(remote.fetch) == 1
            assert isinstance(remote.fetch[0], RefSpec)

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser")
    def test_remote_instead_of(self, mock_for_user):
        """Test Remote _InsteadOf method."""
        mock_config = mock.MagicMock()
        mock_user_config = mock.MagicMock()
        mock_user_config.GetSubSections.return_value = ["https://github.com/"]
        mock_user_config.GetString.return_value = ["gh:"]
        mock_for_user.return_value = mock_user_config

        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "gh:user/repo",
                "pushurl": None,
                "review": None,
                "projectname": None,
                "fetch": [],
            }.get(key, None),
        ):
            remote = Remote(mock_config, "origin")
            result = remote._InsteadOf()
            # Should return URL after insteadOf replacement
            assert result is not None

    @pytest.mark.unit
    def test_remote_pre_connect_fetch(self):
        """Test Remote PreConnectFetch method."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Remote,
            "_Get",
            side_effect=lambda key, **kwargs: {
                "url": "https://example.com/repo.git",
                "pushurl": None,
                "review": None,
                "projectname": None,
                "fetch": [],
            }.get(key, None),
        ):
            remote = Remote(mock_config, "origin")
            ssh_proxy = mock.MagicMock()
            # Should not raise
            remote.PreConnectFetch(ssh_proxy)


class TestBranchClass:
    """Test Branch class methods."""

    @pytest.mark.unit
    def test_branch_init(self):
        """Test Branch initialization."""
        mock_config = mock.MagicMock()
        with mock.patch.object(Branch, "_Get", return_value=None):
            branch = Branch(mock_config, "main")
            assert branch.name == "main"

    @pytest.mark.unit
    def test_branch_merge(self):
        """Test Branch merge property."""
        mock_config = mock.MagicMock()
        with mock.patch.object(
            Branch,
            "_Get",
            side_effect=lambda key: {
                "merge": "refs/heads/main",
                "remote": "origin",
            }.get(key, None),
        ):
            branch = Branch(mock_config, "main")
            assert branch.merge == "refs/heads/main"

    @pytest.mark.unit
    def test_branch_remote(self):
        """Test Branch remote property."""
        mock_config = mock.MagicMock()
        mock_remote = mock.MagicMock()
        mock_remote.name = "origin"
        mock_config.GetRemote.return_value = mock_remote

        with mock.patch.object(
            Branch,
            "_Get",
            side_effect=lambda key: {
                "merge": "refs/heads/main",
                "remote": "origin",
            }.get(key, None),
        ):
            branch = Branch(mock_config, "main")
            assert branch.remote.name == "origin"


class TestGetSchemeFromUrl:
    """Test GetSchemeFromUrl function."""

    @pytest.mark.unit
    def test_get_scheme_https(self):
        """Test GetSchemeFromUrl with https URL."""
        result = GetSchemeFromUrl("https://example.com/repo.git")
        assert result == "https"

    @pytest.mark.unit
    def test_get_scheme_http(self):
        """Test GetSchemeFromUrl with http URL."""
        result = GetSchemeFromUrl("http://example.com/repo.git")
        assert result == "http"

    @pytest.mark.unit
    def test_get_scheme_ssh(self):
        """Test GetSchemeFromUrl with ssh URL."""
        result = GetSchemeFromUrl("ssh://user@example.com/repo.git")
        assert result == "ssh"

    @pytest.mark.unit
    def test_get_scheme_git(self):
        """Test GetSchemeFromUrl with git URL."""
        result = GetSchemeFromUrl("git://example.com/repo.git")
        assert result == "git"

    @pytest.mark.unit
    def test_get_scheme_file(self):
        """Test GetSchemeFromUrl with file URL."""
        result = GetSchemeFromUrl("file:///path/to/repo")
        assert result == "file"

    @pytest.mark.unit
    def test_get_scheme_none(self):
        """Test GetSchemeFromUrl with no scheme."""
        result = GetSchemeFromUrl("example.com/repo.git")
        assert result is None

    @pytest.mark.unit
    def test_get_scheme_persistent_https(self):
        """Test GetSchemeFromUrl with persistent-https scheme."""
        result = GetSchemeFromUrl("persistent-https://example.com/repo.git")
        assert result == "persistent-https"


class TestGetUrlCookieFile:
    """Test GetUrlCookieFile context manager."""

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser")
    def test_get_url_cookie_file_no_persistent(self, mock_for_user):
        """Test GetUrlCookieFile with non-persistent URL."""
        mock_user_config = mock.MagicMock()
        mock_user_config.GetString.return_value = None
        mock_for_user.return_value = mock_user_config

        with GetUrlCookieFile("https://example.com/repo", quiet=True) as (
            cookie,
            proxy,
        ):
            assert cookie is None
            assert proxy is None

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser")
    def test_get_url_cookie_file_with_cookie(self, mock_for_user):
        """Test GetUrlCookieFile with cookie file configured."""
        mock_user_config = mock.MagicMock()
        mock_user_config.GetString.return_value = "~/.gitcookies"
        mock_for_user.return_value = mock_user_config

        with GetUrlCookieFile("https://example.com/repo", quiet=True) as (
            cookie,
            proxy,
        ):
            assert cookie is not None
            assert proxy is None

    @pytest.mark.unit
    @mock.patch("subprocess.Popen")
    @mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser")
    def test_get_url_cookie_file_persistent_url_success(self, mock_for_user, mock_popen):
        """Test GetUrlCookieFile with persistent URL and successful subprocess."""
        mock_user_config = mock.MagicMock()
        mock_user_config.GetString.return_value = None
        mock_for_user.return_value = mock_user_config

        mock_proc = mock.MagicMock()
        mock_proc.stdout = [
            b"http.cookiefile=/tmp/cookies\n",
            b"http.proxy=http://proxy:8080\n",
        ]
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with GetUrlCookieFile("persistent-https://example.com/repo", quiet=True) as (cookie, proxy):
            assert cookie == "/tmp/cookies"
            assert proxy == "http://proxy:8080"

    @pytest.mark.unit
    @mock.patch("subprocess.Popen")
    @mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser")
    def test_get_url_cookie_file_persistent_url_failure(self, mock_for_user, mock_popen):
        """Test GetUrlCookieFile with persistent URL and subprocess failure."""
        mock_user_config = mock.MagicMock()
        mock_user_config.GetString.return_value = None
        mock_for_user.return_value = mock_user_config

        mock_proc = mock.MagicMock()
        mock_proc.stdout = []
        mock_proc.stderr.read.return_value = b"error: some error"
        mock_proc.wait.return_value = 1
        mock_popen.return_value = mock_proc

        with GetUrlCookieFile("persistent-https://example.com/repo", quiet=True) as (cookie, proxy):
            assert cookie is None
            assert proxy is None


class TestRefSpec:
    """Test RefSpec class."""

    @pytest.mark.unit
    def test_refspec_from_string_forced(self):
        """Test RefSpec.FromString with forced refspec."""
        rs = RefSpec.FromString("+refs/heads/*:refs/remotes/origin/*")
        assert rs.forced is True
        assert rs.src == "refs/heads/*"
        assert rs.dst == "refs/remotes/origin/*"

    @pytest.mark.unit
    def test_refspec_from_string_not_forced(self):
        """Test RefSpec.FromString with non-forced refspec."""
        rs = RefSpec.FromString("refs/heads/main:refs/remotes/origin/main")
        assert rs.forced is False
        assert rs.src == "refs/heads/main"
        assert rs.dst == "refs/remotes/origin/main"

    @pytest.mark.unit
    def test_refspec_source_matches_exact(self):
        """Test RefSpec.SourceMatches with exact match."""
        rs = RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        assert rs.SourceMatches("refs/heads/main") is True
        assert rs.SourceMatches("refs/heads/develop") is False

    @pytest.mark.unit
    def test_refspec_source_matches_wildcard(self):
        """Test RefSpec.SourceMatches with wildcard."""
        rs = RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        assert rs.SourceMatches("refs/heads/main") is True
        assert rs.SourceMatches("refs/heads/develop") is True
        assert rs.SourceMatches("refs/tags/v1.0") is False

    @pytest.mark.unit
    def test_refspec_dest_matches_exact(self):
        """Test RefSpec.DestMatches with exact match."""
        rs = RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        assert rs.DestMatches("refs/remotes/origin/main") is True
        assert rs.DestMatches("refs/remotes/origin/develop") is False

    @pytest.mark.unit
    def test_refspec_dest_matches_wildcard(self):
        """Test RefSpec.DestMatches with wildcard."""
        rs = RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        assert rs.DestMatches("refs/remotes/origin/main") is True
        assert rs.DestMatches("refs/remotes/origin/develop") is True
        assert rs.DestMatches("refs/remotes/upstream/main") is False

    @pytest.mark.unit
    def test_refspec_map_source(self):
        """Test RefSpec.MapSource."""
        rs = RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        result = rs.MapSource("refs/heads/main")
        assert result == "refs/remotes/origin/main"

    @pytest.mark.unit
    def test_refspec_str_forced(self):
        """Test RefSpec.__str__ with forced refspec."""
        rs = RefSpec(True, "refs/heads/*", "refs/remotes/origin/*")
        assert str(rs) == "+refs/heads/*:refs/remotes/origin/*"

    @pytest.mark.unit
    def test_refspec_str_not_forced(self):
        """Test RefSpec.__str__ with non-forced refspec."""
        rs = RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        assert str(rs) == "refs/heads/main:refs/remotes/origin/main"


class TestSyncAnalysisState:
    """Test SyncAnalysisState functionality."""

    @pytest.mark.unit
    def test_get_sync_analysis_state_data(self, tmp_path):
        """Test GetSyncAnalysisStateData method."""
        config_file = tmp_path / "config"
        config_file.write_text("[test]\n\tkey = value\n")

        config = GitConfig(configfile=str(config_file))
        config.SetString("repo.syncstate.test", "value")

        data = config.GetSyncAnalysisStateData()
        assert isinstance(data, dict)

    @pytest.mark.unit
    def test_update_sync_analysis_state(self, tmp_path):
        """Test UpdateSyncAnalysisState method."""
        config_file = tmp_path / "config"
        config_file.write_text("[test]\n\tkey = value\n")

        config = GitConfig(configfile=str(config_file))
        options = mock.MagicMock()
        superproject_data = {}

        result = config.UpdateSyncAnalysisState(options, superproject_data)
        assert result is not None
