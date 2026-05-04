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

"""Deep unit tests for ssh.py module."""

import multiprocessing
import subprocess
from unittest import mock

import pytest

from kanon_cli.repo.ssh import _get_git_protocol_version
from kanon_cli.repo.ssh import _parse_ssh_version
from kanon_cli.repo.ssh import _run_ssh_version
from kanon_cli.repo.ssh import ProxyManager
from kanon_cli.repo.ssh import URI_ALL
from kanon_cli.repo.ssh import URI_SCP
from kanon_cli.repo.ssh import version


@pytest.mark.unit
class TestParseSshVersion:
    """Tests for _parse_ssh_version function."""

    def test_parse_openssh_version(self):
        """Test parsing OpenSSH version string."""
        ver_str = "OpenSSH_8.2p1 Ubuntu-4ubuntu0.5, OpenSSL 1.1.1f  31 Mar 2020"
        result = _parse_ssh_version(ver_str)
        assert result == (8, 2)

    def test_parse_openssh_version_with_patch(self):
        """Test parsing OpenSSH version with patch."""
        ver_str = "OpenSSH_7.9p1, LibreSSL 2.7.3"
        result = _parse_ssh_version(ver_str)
        assert result == (7, 9)

    def test_parse_openssh_version_three_parts(self):
        """Test parsing OpenSSH version with three parts."""
        ver_str = "OpenSSH_6.7.1p1, OpenSSL 1.0.2k  26 Jan 2017"
        result = _parse_ssh_version(ver_str)
        assert result == (6, 7, 1)

    def test_parse_invalid_version(self):
        """Test parsing invalid version string."""
        ver_str = "Invalid SSH Version"
        result = _parse_ssh_version(ver_str)
        assert result == ()

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        ver_str = ""
        result = _parse_ssh_version(ver_str)
        assert result == ()


@pytest.mark.unit
class TestRunSshVersion:
    """Tests for _run_ssh_version function."""

    def test_run_ssh_version_success(self):
        """Test _run_ssh_version returns version output."""
        with mock.patch("subprocess.check_output") as mock_check_output:
            mock_check_output.return_value = b"OpenSSH_8.2p1 Ubuntu\n"
            result = _run_ssh_version()
            assert "OpenSSH_8.2p1" in result

    def test_run_ssh_version_calls_ssh(self):
        """Test _run_ssh_version calls ssh -V."""
        with mock.patch("subprocess.check_output") as mock_check_output:
            mock_check_output.return_value = b"OpenSSH_8.2p1\n"
            _run_ssh_version()
            mock_check_output.assert_called_once_with(["ssh", "-V"], stderr=subprocess.STDOUT)


@pytest.mark.unit
class TestVersion:
    """Tests for version function."""

    def test_version_file_not_found(self):
        """Test version exits when ssh not found."""
        with mock.patch("kanon_cli.repo.ssh._run_ssh_version", side_effect=FileNotFoundError()):
            version.cache_clear()
            with pytest.raises(SystemExit):
                version()

    def test_version_called_process_error(self):
        """Test version exits on CalledProcessError."""
        error = subprocess.CalledProcessError(1, "ssh", output=b"error")
        with mock.patch("kanon_cli.repo.ssh._run_ssh_version", side_effect=error):
            version.cache_clear()
            with pytest.raises(SystemExit):
                version()


@pytest.mark.unit
class TestURIPatterns:
    """Tests for URI regex patterns."""

    def test_uri_scp_matches(self):
        """Test URI_SCP matches SCP-style URLs."""
        assert URI_SCP.match("user@host:path/to/repo")
        assert URI_SCP.match("git@github.com:user/repo.git")
        assert URI_SCP.match("host:repo")

    def test_uri_all_matches(self):
        """Test URI_ALL matches standard URLs."""
        match = URI_ALL.match("https://user@host/path")
        assert match is not None
        assert match.group(1) == "https"

        match = URI_ALL.match("ssh://git@github.com/user/repo.git")
        assert match is not None
        assert match.group(1) == "ssh"

    def test_uri_all_no_match(self):
        """Test URI_ALL doesn't match non-standard URLs."""
        assert not URI_ALL.match("user@host:path")


@pytest.mark.unit
class TestProxyManagerInit:
    """Tests for ProxyManager initialization."""

    def test_proxy_manager_init(self):
        """Test ProxyManager initialization."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        assert pm._sock_path is None
        assert len(pm._masters) == 0
        assert len(pm._clients) == 0

    def test_proxy_manager_context_manager(self):
        """Test ProxyManager as context manager."""
        manager = multiprocessing.Manager()
        with ProxyManager(manager) as pm:
            assert pm is not None


@pytest.mark.unit
class TestProxyManagerClients:
    """Tests for ProxyManager client tracking."""

    def test_add_client(self):
        """Test adding a client."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        proc = mock.Mock()
        proc.pid = 12345

        pm.add_client(proc)
        assert 12345 in pm._clients

    def test_remove_client(self):
        """Test removing a client."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        proc = mock.Mock()
        proc.pid = 12345

        pm.add_client(proc)
        pm.remove_client(proc)
        assert 12345 not in pm._clients

    def test_remove_nonexistent_client(self):
        """Test removing a client that doesn't exist."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        proc = mock.Mock()
        proc.pid = 99999

        # Should not raise exception
        pm.remove_client(proc)


@pytest.mark.unit
class TestProxyManagerMasters:
    """Tests for ProxyManager master tracking."""

    def test_add_master(self):
        """Test adding a master."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        proc = mock.Mock()
        proc.pid = 54321

        pm.add_master(proc)
        assert 54321 in pm._masters


@pytest.mark.unit
class TestProxyManagerSock:
    """Tests for ProxyManager.sock method."""

    def test_sock_creates_path(self):
        """Test sock creates socket path."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 8)):
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-test"):
                sock = pm.sock(create=True)
                assert sock is not None
                assert "/tmp/ssh-test" in sock

    def test_sock_no_create(self):
        """Test sock returns None when not creating."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        sock = pm.sock(create=False)
        assert sock is None

    def test_sock_version_less_than_6_7(self):
        """Test sock uses old token format for old SSH."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 6)):
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-test"):
                sock = pm.sock(create=True)
                assert "%r@%h:%p" in sock

    def test_sock_version_6_7_or_later(self):
        """Test sock uses new token format for new SSH."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 7)):
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-test"):
                sock = pm.sock(create=True)
                assert "%C" in sock


@pytest.mark.unit
class TestProxyManagerPreconnect:
    """Tests for ProxyManager.preconnect method."""

    def test_preconnect_ssh_url(self):
        """Test preconnect with SSH URL."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._open = mock.Mock(return_value=True)

        result = pm.preconnect("ssh://git@github.com/user/repo.git")
        pm._open.assert_called_once_with("git@github.com", None)
        assert result is True

    def test_preconnect_ssh_url_with_port(self):
        """Test preconnect with SSH URL and port."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._open = mock.Mock(return_value=True)

        result = pm.preconnect("ssh://git@github.com:2222/user/repo.git")
        pm._open.assert_called_once_with("git@github.com", "2222")
        assert result is True

    def test_preconnect_scp_style(self):
        """Test preconnect with SCP-style URL."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._open = mock.Mock(return_value=True)

        result = pm.preconnect("git@github.com:user/repo.git")
        pm._open.assert_called_once_with("git@github.com")
        assert result is True

    def test_preconnect_https_url(self):
        """Test preconnect with HTTPS URL returns False."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        result = pm.preconnect("https://github.com/user/repo.git")
        assert result is False

    def test_preconnect_local_path(self):
        """Test preconnect with local path returns False."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        result = pm.preconnect("/local/path/to/repo")
        assert result is False


@pytest.mark.unit
class TestProxyManagerOpen:
    """Tests for ProxyManager._open method."""

    def test_open_windows_returns_false(self):
        """Test _open returns False on Windows."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch("sys.platform", "win32"):
            result = pm._open("host")
            assert result is False

    def test_open_cygwin_returns_false(self):
        """Test _open returns False on Cygwin."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch("sys.platform", "cygwin"):
            result = pm._open("host")
            assert result is False


@pytest.mark.unit
class TestProxyManagerOpenUnlocked:
    """Tests for ProxyManager._open_unlocked method."""

    def test_open_unlocked_already_exists(self):
        """Test _open_unlocked returns True if master exists."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._master_keys["host"] = True

        result = pm._open_unlocked("host")
        assert result is True

    def test_open_unlocked_master_broken(self):
        """Test _open_unlocked returns False if master is broken."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._master_broken.value = True

        result = pm._open_unlocked("host")
        assert result is False

    def test_open_unlocked_git_ssh_set(self):
        """Test _open_unlocked returns False if GIT_SSH is set."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)

        with mock.patch.dict("os.environ", {"GIT_SSH": "/usr/bin/ssh"}):
            result = pm._open_unlocked("host")
            assert result is False


@pytest.mark.unit
class TestGetGitProtocolVersion:
    """Tests for _get_git_protocol_version function."""

    def test_get_git_protocol_version_from_config(self):
        """Test getting protocol version from git config."""
        with mock.patch("subprocess.check_output", return_value="2\n"):
            _get_git_protocol_version.cache_clear()
            result = _get_git_protocol_version()
            assert result == "2"

    def test_get_git_protocol_version_not_found(self):
        """Test getting protocol version when config key not found."""
        error = subprocess.CalledProcessError(1, "git config", stderr=b"")
        with mock.patch("subprocess.check_output", side_effect=error):
            with mock.patch("kanon_cli.repo.git_command.git.version_tuple", return_value=(2, 26, 0)):
                _get_git_protocol_version.cache_clear()
                result = _get_git_protocol_version()
                assert result == "2"

    def test_get_git_protocol_version_old_git(self):
        """Test getting protocol version with old git."""
        error = subprocess.CalledProcessError(1, "git config", stderr=b"")
        with mock.patch("subprocess.check_output", side_effect=error):
            with mock.patch("kanon_cli.repo.git_command.git.version_tuple", return_value=(2, 25, 0)):
                _get_git_protocol_version.cache_clear()
                result = _get_git_protocol_version()
                assert result == "1"

    def test_get_git_protocol_version_config_error(self):
        """Test getting protocol version with config error."""
        error = subprocess.CalledProcessError(2, "git config", stderr=b"error")
        with mock.patch("subprocess.check_output", side_effect=error):
            _get_git_protocol_version.cache_clear()
            with pytest.raises(subprocess.CalledProcessError):
                _get_git_protocol_version()


@pytest.mark.unit
class TestProxyManagerClose:
    """Tests for ProxyManager.close method."""

    def test_close_terminates_clients_and_masters(self):
        """Test close terminates clients and masters."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._sock_path = "/tmp/ssh-test/master"

        with mock.patch("os.kill"):
            with mock.patch("os.waitpid"):
                with mock.patch("kanon_cli.repo.platform_utils.rmdir"):
                    with mock.patch("os.path.dirname", return_value="/tmp/ssh-test"):
                        pm.close()

    def test_close_handles_os_error(self):
        """Test close handles OSError."""
        manager = multiprocessing.Manager()
        pm = ProxyManager(manager)
        pm._sock_path = "/tmp/ssh-test/master"

        with mock.patch("os.kill", side_effect=OSError()):
            with mock.patch("os.waitpid"):
                with mock.patch("kanon_cli.repo.platform_utils.rmdir", side_effect=OSError()):
                    with mock.patch("os.path.dirname", return_value="/tmp/ssh-test"):
                        # Should not raise
                        pm.close()
