# Copyright 2019 The Android Open Source Project
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

"""Unittests for the ssh.py module."""

import multiprocessing
import os
import subprocess
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import ssh


class SshTests(unittest.TestCase):
    """Tests the ssh functions."""

    def test_parse_ssh_version(self):
        """Check _parse_ssh_version() handling."""
        ver = ssh._parse_ssh_version("Unknown\n")
        self.assertEqual(ver, ())
        ver = ssh._parse_ssh_version("OpenSSH_1.0\n")
        self.assertEqual(ver, (1, 0))
        ver = ssh._parse_ssh_version("OpenSSH_6.6.1p1 Ubuntu-2ubuntu2.13, OpenSSL 1.0.1f 6 Jan 2014\n")
        self.assertEqual(ver, (6, 6, 1))
        ver = ssh._parse_ssh_version("OpenSSH_7.6p1 Ubuntu-4ubuntu0.3, OpenSSL 1.0.2n  7 Dec 2017\n")
        self.assertEqual(ver, (7, 6))
        ver = ssh._parse_ssh_version("OpenSSH_9.0p1, LibreSSL 3.3.6\n")
        self.assertEqual(ver, (9, 0))

    def test_version(self):
        """Check version() handling."""
        ssh.version.cache_clear()
        with mock.patch("kanon_cli.repo.ssh._run_ssh_version", return_value="OpenSSH_1.2\n"):
            self.assertEqual(ssh.version(), (1, 2))
        ssh.version.cache_clear()

    def test_context_manager_empty(self):
        """Verify context manager with no clients works correctly."""
        with multiprocessing.Manager() as manager:
            with ssh.ProxyManager(manager):
                pass

    def test_context_manager_child_cleanup(self):
        """Verify orphaned clients & masters get cleaned up."""
        with multiprocessing.Manager() as manager:
            with ssh.ProxyManager(manager) as ssh_proxy:
                client = subprocess.Popen(["sleep", "964853320"])
                ssh_proxy.add_client(client)
                master = subprocess.Popen(["sleep", "964853321"])
                ssh_proxy.add_master(master)
        # If the process still exists, these will throw timeout errors.
        client.wait(0)
        master.wait(0)

    def test_ssh_sock(self):
        """Check sock() function."""
        manager = multiprocessing.Manager()
        proxy = ssh.ProxyManager(manager)
        with mock.patch("tempfile.mkdtemp", return_value="/tmp/foo"):
            # Old ssh version uses port.
            with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 6)):
                self.assertTrue(proxy.sock().endswith("%p"))

            proxy._sock_path = None
            # New ssh version uses hash.
            with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 7)):
                self.assertTrue(proxy.sock().endswith("%C"))


@pytest.mark.unit
class ProxyPathTests(unittest.TestCase):
    """Tests that the git_ssh proxy script is present and executable."""

    def test_proxy_path_exists(self):
        """git_ssh must exist alongside ssh.py for GIT_SSH to work."""
        self.assertTrue(
            os.path.isfile(ssh.PROXY_PATH),
            f"git_ssh proxy script missing: {ssh.PROXY_PATH}",
        )

    def test_proxy_path_is_executable(self):
        """git_ssh must be executable so git can invoke it via GIT_SSH."""
        self.assertTrue(
            os.access(ssh.PROXY_PATH, os.X_OK),
            f"git_ssh proxy script is not executable: {ssh.PROXY_PATH}",
        )


@pytest.mark.unit
class SshMandatoryTests(unittest.TestCase):
    """Tests for mandatory SSH behavior (fork feature)."""

    def test_ssh_not_installed_exits_with_error(self):
        """FileNotFoundError from ssh -V should cause sys.exit(1)."""
        ssh.version.cache_clear()
        with mock.patch(
            "kanon_cli.repo.ssh._run_ssh_version",
            side_effect=FileNotFoundError("ssh not found"),
        ):
            with mock.patch("sys.exit") as mock_exit:
                with mock.patch("builtins.print") as mock_print:
                    ssh.version()
                    mock_exit.assert_called_once_with(1)
                    mock_print.assert_called_once()
                    self.assertIn(
                        "fatal: ssh not installed",
                        mock_print.call_args[0][0],
                    )
        ssh.version.cache_clear()

    def test_ssh_called_process_error_exits(self):
        """CalledProcessError from ssh -V should cause sys.exit(1)."""
        ssh.version.cache_clear()
        with mock.patch(
            "kanon_cli.repo.ssh._run_ssh_version",
            side_effect=subprocess.CalledProcessError(1, "ssh", output=b"error"),
        ):
            with mock.patch("sys.exit") as mock_exit:
                with mock.patch("builtins.print"):
                    ssh.version()
                    mock_exit.assert_called_once_with(1)
        ssh.version.cache_clear()

    def test_ssh_version_success_returns_tuple(self):
        """Normal ssh version parsing should return a tuple."""
        ssh.version.cache_clear()
        with mock.patch(
            "kanon_cli.repo.ssh._run_ssh_version",
            return_value="OpenSSH_8.9p1 Ubuntu-3, OpenSSL 3.0.2\n",
        ):
            result = ssh.version()
            self.assertEqual(result, (8, 9))
        ssh.version.cache_clear()


@pytest.mark.unit
class ProxyManagerTests(unittest.TestCase):
    """Tests for ProxyManager class."""

    def test_init_creates_all_attributes(self):
        """ProxyManager.__init__ should initialize all required attributes."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            self.assertIsNotNone(proxy._lock)
            self.assertIsNotNone(proxy._masters)
            self.assertIsNotNone(proxy._master_keys)
            self.assertIsNotNone(proxy._master_broken)
            self.assertIsNotNone(proxy._clients)
            self.assertIsNone(proxy._sock_path)

    def test_add_client_adds_pid_to_list(self):
        """add_client should add process PID to clients list."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            mock_proc = mock.Mock()
            mock_proc.pid = 12345
            proxy.add_client(mock_proc)
            self.assertIn(12345, proxy._clients)

    def test_remove_client_removes_pid(self):
        """remove_client should remove process PID from clients list."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            mock_proc = mock.Mock()
            mock_proc.pid = 12345
            proxy.add_client(mock_proc)
            proxy.remove_client(mock_proc)
            self.assertNotIn(12345, proxy._clients)

    def test_remove_client_ignores_missing_pid(self):
        """remove_client should not raise if PID not in list."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            mock_proc = mock.Mock()
            mock_proc.pid = 99999
            # Should not raise ValueError
            proxy.remove_client(mock_proc)

    def test_add_master_adds_pid_to_list(self):
        """add_master should add process PID to masters list."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            mock_proc = mock.Mock()
            mock_proc.pid = 54321
            proxy.add_master(mock_proc)
            self.assertIn(54321, proxy._masters)

    def test_sock_returns_path_with_tokens(self):
        """sock() should return path with SSH control socket tokens."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-test"):
                with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 6)):
                    path = proxy.sock()
                    self.assertIn("/tmp/ssh-test", path)
                    self.assertTrue(path.endswith("%r@%h:%p"))

    def test_sock_uses_hash_for_new_ssh(self):
        """sock() should use %C hash for SSH >= 6.7."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-test"):
                with mock.patch("kanon_cli.repo.ssh.version", return_value=(6, 7)):
                    path = proxy.sock()
                    self.assertTrue(path.endswith("%C"))

    def test_sock_returns_none_when_create_false(self):
        """sock(create=False) should return None if path not set."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            result = proxy.sock(create=False)
            self.assertIsNone(result)

    def test_sock_caches_path(self):
        """sock() should cache and reuse the same path."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-cache"):
                with mock.patch("kanon_cli.repo.ssh.version", return_value=(7, 0)):
                    path1 = proxy.sock()
                    path2 = proxy.sock()
                    self.assertEqual(path1, path2)

    def test_close_terminates_clients(self):
        """close() should terminate all client processes."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("os.kill") as mock_kill:
                with mock.patch("os.waitpid"):
                    proxy._clients.append(111)
                    proxy._clients.append(222)
                    proxy.close()
                    self.assertEqual(mock_kill.call_count, 2)

    def test_close_terminates_masters(self):
        """close() should terminate all master processes."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("os.kill") as mock_kill:
                with mock.patch("os.waitpid"):
                    proxy._masters.append(333)
                    proxy._masters.append(444)
                    proxy.close()
                    self.assertEqual(mock_kill.call_count, 2)

    def test_close_removes_socket_directory(self):
        """close() should remove the socket directory."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("tempfile.mkdtemp", return_value="/tmp/ssh-remove"):
                with mock.patch("kanon_cli.repo.ssh.version", return_value=(7, 0)):
                    with mock.patch("kanon_cli.repo.platform_utils.rmdir") as mock_rmdir:
                        proxy.sock()
                        proxy.close()
                        mock_rmdir.assert_called_once()

    def test_close_handles_oserror_gracefully(self):
        """close() should handle OSError when killing processes."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("os.kill", side_effect=OSError):
                with mock.patch("os.waitpid"):
                    proxy._clients.append(999)
                    # Should not raise
                    proxy.close()

    def test_context_manager_enter_returns_self(self):
        """__enter__ should return the ProxyManager instance."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            result = proxy.__enter__()
            self.assertIs(result, proxy)

    def test_context_manager_exit_calls_close(self):
        """__exit__ should call close()."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch.object(proxy, "close") as mock_close:
                proxy.__exit__(None, None, None)
                mock_close.assert_called_once()

    def test_preconnect_with_ssh_scheme(self):
        """preconnect() should handle ssh:// URLs."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch.object(proxy, "_open", return_value=True) as mock_open:
                result = proxy.preconnect("ssh://user@host.com/path")
                mock_open.assert_called_once_with("user@host.com", None)
                self.assertTrue(result)

    def test_preconnect_with_ssh_and_port(self):
        """preconnect() should handle ssh:// URLs with port."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch.object(proxy, "_open", return_value=True) as mock_open:
                result = proxy.preconnect("ssh://user@host.com:2222/path")
                mock_open.assert_called_once_with("user@host.com", "2222")
                self.assertTrue(result)

    def test_preconnect_with_scp_syntax(self):
        """preconnect() should handle SCP-style URLs."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch.object(proxy, "_open", return_value=True) as mock_open:
                result = proxy.preconnect("user@host.com:path/to/repo")
                mock_open.assert_called_once_with("user@host.com")
                self.assertTrue(result)

    def test_preconnect_with_git_ssh_scheme(self):
        """preconnect() should handle git+ssh:// URLs."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch.object(proxy, "_open", return_value=True):
                result = proxy.preconnect("git+ssh://host.com/path")
                self.assertTrue(result)

    def test_preconnect_returns_false_for_non_ssh(self):
        """preconnect() should return False for non-SSH URLs."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            result = proxy.preconnect("https://host.com/path")
            self.assertFalse(result)

    def test_open_returns_false_on_windows(self):
        """_open() should return False on Windows platform."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("sys.platform", "win32"):
                result = proxy._open("host.com")
                self.assertFalse(result)

    def test_open_returns_false_on_cygwin(self):
        """_open() should return False on Cygwin platform."""
        with multiprocessing.Manager() as manager:
            proxy = ssh.ProxyManager(manager)
            with mock.patch("sys.platform", "cygwin"):
                result = proxy._open("host.com")
                self.assertFalse(result)


@pytest.mark.unit
class RunSshVersionTests(unittest.TestCase):
    """Tests for _run_ssh_version function."""

    def test_run_ssh_version_calls_subprocess(self):
        """_run_ssh_version should call subprocess.check_output."""
        with mock.patch("subprocess.check_output", return_value=b"OpenSSH_8.0\n"):
            result = ssh._run_ssh_version()
            self.assertEqual(result, "OpenSSH_8.0\n")

    def test_run_ssh_version_uses_stderr_stdout(self):
        """_run_ssh_version should redirect stderr to stdout."""
        with mock.patch("subprocess.check_output") as mock_check:
            mock_check.return_value = b"version"
            ssh._run_ssh_version()
            mock_check.assert_called_once_with(["ssh", "-V"], stderr=subprocess.STDOUT)


@pytest.mark.unit
class ParseSshVersionTests(unittest.TestCase):
    """Additional tests for _parse_ssh_version."""

    def test_parse_with_patch_version(self):
        """Should parse version with patch number."""
        result = ssh._parse_ssh_version("OpenSSH_7.4p1\n")
        self.assertEqual(result, (7, 4))

    def test_parse_without_newline(self):
        """Should parse version string with space after version."""
        result = ssh._parse_ssh_version("OpenSSH_8.2 ")
        self.assertEqual(result, (8, 2))

    def test_parse_with_extra_info(self):
        """Should parse version with extra build info."""
        result = ssh._parse_ssh_version("OpenSSH_9.1p1, OpenSSL 1.1.1\n")
        self.assertEqual(result, (9, 1))

    def test_parse_calls_run_when_no_arg(self):
        """Should call _run_ssh_version when ver_str is None."""
        with mock.patch("kanon_cli.repo.ssh._run_ssh_version", return_value="OpenSSH_7.8\n"):
            result = ssh._parse_ssh_version()
            self.assertEqual(result, (7, 8))

    def test_parse_multipart_version(self):
        """Should handle version with multiple parts."""
        result = ssh._parse_ssh_version("OpenSSH_8.9.1p1 Ubuntu\n")
        self.assertEqual(result, (8, 9, 1))
