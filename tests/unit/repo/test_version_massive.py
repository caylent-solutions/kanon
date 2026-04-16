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

"""Unit tests for subcmds/version.py coverage."""

from unittest import mock

import pytest

from subcmds.version import Version


def _make_cmd():
    """Create a Version command instance for testing."""
    cmd = Version.__new__(Version)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_execute_basic():
    """Test Execute method basic functionality."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        # Should print version info
                        assert mock_print.call_count >= 5


@pytest.mark.unit
def test_execute_with_wrapper_version():
    """Test Execute with wrapper version set."""
    cmd = _make_cmd()
    cmd.wrapper_version = "1.0.0"
    cmd.wrapper_path = "/usr/bin/repo"
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        # Should print wrapper version
                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "1.0.0" in printed


@pytest.mark.unit
def test_execute_version_mismatch():
    """Test Execute when source version differs from repo version."""
    cmd = _make_cmd()
    cmd.wrapper_version = "1.0.0"
    cmd.wrapper_path = "/usr/bin/repo"
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.0.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        # Should print "currently at"
                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "currently" in printed.lower() or "v2.0.0" in printed


@pytest.mark.unit
def test_execute_prints_remote_url():
    """Test Execute prints remote URL."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "example.com/repo.git" in printed


@pytest.mark.unit
def test_execute_prints_tracking_branch():
    """Test Execute prints tracking branch."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/stable"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "stable" in printed


@pytest.mark.unit
def test_execute_prints_user_agents():
    """Test Execute prints user agent strings."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0 custom"
            mock_ua.git = "git/2.40.0 custom"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "User-Agent" in printed


@pytest.mark.unit
def test_execute_prints_python_version():
    """Test Execute prints Python version."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "Python" in printed


@pytest.mark.unit
def test_execute_prints_os_info():
    """Test Execute prints OS information."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        # Should print OS info
                        assert "OS" in printed or "CPU" in printed or len(mock_print.call_args_list) >= 8


@pytest.mark.unit
def test_execute_prints_bug_url():
    """Test Execute prints bug reporting URL."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print") as mock_print:
                        cmd.Execute(opt, args)

                        printed = " ".join(str(call) for call in mock_print.call_args_list)
                        assert "Bug" in printed or "bugs.example.com" in printed


@pytest.mark.unit
def test_execute_calls_describe():
    """Test Execute calls git describe."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0-5-gabc1234"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print"):
                        cmd.Execute(opt, args)

                        # Should call describe with HEAD
                        from git_refs import HEAD

                        rp.bare_git.describe.assert_called_once_with(HEAD)


@pytest.mark.unit
def test_execute_calls_log():
    """Test Execute calls git log for date."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    rp = cmd.manifest.repoProject
    remote = mock.MagicMock()
    remote.url = "https://example.com/repo.git"
    rp.GetRemote.return_value = remote

    branch = mock.MagicMock()
    branch.merge = "refs/heads/main"
    rp.GetBranch.return_value = branch

    rp.bare_git.describe.return_value = "v2.1.0"
    rp.bare_git.log.return_value = "Mon, 01 Jan 2024 12:00:00 +0000"

    with mock.patch("subcmds.version.RepoSourceVersion", return_value="v2.1.0"):
        with mock.patch("subcmds.version.user_agent") as mock_ua:
            mock_ua.repo = "repo/2.1.0"
            mock_ua.git = "git/2.40.0"
            with mock.patch("subcmds.version.git") as mock_git:
                version_tuple = mock.MagicMock()
                version_tuple.full = "2.40.0"
                mock_git.version_tuple.return_value = version_tuple
                with mock.patch("subcmds.version.Wrapper") as mock_wrapper:
                    wrapper_instance = mock.MagicMock()
                    wrapper_instance.BUG_URL = "https://bugs.example.com"
                    mock_wrapper.return_value = wrapper_instance
                    with mock.patch("builtins.print"):
                        cmd.Execute(opt, args)

                        # Should call log
                        from git_refs import HEAD

                        rp.bare_git.log.assert_called_once_with("-1", "--format=%cD", HEAD)
