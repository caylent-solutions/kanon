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

"""Unittests for the pager.py module."""

import os
import sys
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import pager


@pytest.mark.unit
class RunPagerTests(unittest.TestCase):
    """Tests for RunPager function."""

    def test_run_pager_returns_early_if_not_tty_stdin(self):
        """RunPager should return early if stdin is not a TTY."""
        with mock.patch("os.isatty", side_effect=lambda fd: fd != 0):
            with mock.patch("kanon_cli.repo.pager._SelectPager") as mock_select:
                pager.RunPager(mock.Mock())
                mock_select.assert_not_called()

    def test_run_pager_returns_early_if_not_tty_stdout(self):
        """RunPager should return early if stdout is not a TTY."""
        with mock.patch("os.isatty", side_effect=lambda fd: fd != 1):
            with mock.patch("kanon_cli.repo.pager._SelectPager") as mock_select:
                pager.RunPager(mock.Mock())
                mock_select.assert_not_called()

    def test_run_pager_returns_early_for_empty_pager(self):
        """RunPager should return early if pager is empty string."""
        with mock.patch("os.isatty", return_value=True):
            with mock.patch("kanon_cli.repo.pager._SelectPager", return_value=""):
                with mock.patch("kanon_cli.repo.pager._ForkPager") as mock_fork:
                    pager.RunPager(mock.Mock())
                    mock_fork.assert_not_called()

    def test_run_pager_returns_early_for_cat_pager(self):
        """RunPager should return early if pager is 'cat'."""
        with mock.patch("os.isatty", return_value=True):
            with mock.patch("kanon_cli.repo.pager._SelectPager", return_value="cat"):
                with mock.patch("kanon_cli.repo.pager._ForkPager") as mock_fork:
                    pager.RunPager(mock.Mock())
                    mock_fork.assert_not_called()

    def test_run_pager_uses_pipe_pager_on_windows(self):
        """RunPager should use _PipePager on Windows."""
        with mock.patch("os.isatty", return_value=True):
            with mock.patch("kanon_cli.repo.pager._SelectPager", return_value="less"):
                with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
                    with mock.patch("kanon_cli.repo.pager._PipePager") as mock_pipe:
                        pager.RunPager(mock.Mock())
                        mock_pipe.assert_called_once_with("less")

    def test_run_pager_uses_fork_pager_on_unix(self):
        """RunPager should use _ForkPager on Unix."""
        with mock.patch("os.isatty", return_value=True):
            with mock.patch("kanon_cli.repo.pager._SelectPager", return_value="less"):
                with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
                    with mock.patch("kanon_cli.repo.pager._ForkPager") as mock_fork:
                        pager.RunPager(mock.Mock())
                        mock_fork.assert_called_once_with("less")


@pytest.mark.unit
class SelectPagerTests(unittest.TestCase):
    """Tests for _SelectPager function."""

    def test_select_pager_prefers_git_pager(self):
        """_SelectPager should prefer GIT_PAGER environment variable."""
        config = mock.Mock()
        with mock.patch.dict(os.environ, {"GIT_PAGER": "git-pager"}):
            result = pager._SelectPager(config)
            self.assertEqual(result, "git-pager")

    def test_select_pager_uses_config_pager(self):
        """_SelectPager should use core.pager from config."""
        config = mock.Mock()
        config.GetString.return_value = "config-pager"
        with mock.patch.dict(os.environ, {}, clear=True):
            result = pager._SelectPager(config)
            self.assertEqual(result, "config-pager")

    def test_select_pager_uses_pager_env(self):
        """_SelectPager should use PAGER environment variable."""
        config = mock.Mock()
        config.GetString.return_value = None
        with mock.patch.dict(os.environ, {"PAGER": "env-pager"}, clear=True):
            result = pager._SelectPager(config)
            self.assertEqual(result, "env-pager")

    def test_select_pager_defaults_to_less(self):
        """_SelectPager should default to 'less'."""
        config = mock.Mock()
        config.GetString.return_value = None
        with mock.patch.dict(os.environ, {}, clear=True):
            result = pager._SelectPager(config)
            self.assertEqual(result, "less")


@pytest.mark.unit
class PipePagerTests(unittest.TestCase):
    """Tests for _PipePager function."""

    def setUp(self):
        """Reset pager state before each test."""
        pager.pager_process = None
        pager.old_stdout = None
        pager.old_stderr = None

    def tearDown(self):
        """Clean up pager state after each test."""
        pager.pager_process = None
        pager.old_stdout = None
        pager.old_stderr = None

    def test_pipe_pager_creates_subprocess(self):
        """_PipePager should create a pager subprocess."""
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.Mock()
            mock_process.stdin = mock.Mock()
            mock_popen.return_value = mock_process
            pager._PipePager("less")
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            self.assertEqual(call_args, ["less"])

    def test_pipe_pager_redirects_stdout(self):
        """_PipePager should redirect stdout to pager stdin."""
        original_stdout = sys.stdout
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.Mock()
            mock_process.stdin = mock.Mock()
            mock_popen.return_value = mock_process
            pager._PipePager("less")
            self.assertIs(sys.stdout, mock_process.stdin)
        sys.stdout = original_stdout

    def test_pipe_pager_redirects_stderr(self):
        """_PipePager should redirect stderr to pager stdin."""
        original_stderr = sys.stderr
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.Mock()
            mock_process.stdin = mock.Mock()
            mock_popen.return_value = mock_process
            pager._PipePager("less")
            self.assertIs(sys.stderr, mock_process.stdin)
        sys.stderr = original_stderr

    def test_pipe_pager_saves_old_stdout(self):
        """_PipePager should save original stdout."""
        original_stdout = sys.stdout
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.Mock()
            mock_process.stdin = mock.Mock()
            mock_popen.return_value = mock_process
            pager._PipePager("less")
            self.assertIs(pager.old_stdout, original_stdout)
        sys.stdout = original_stdout

    def test_pipe_pager_saves_old_stderr(self):
        """_PipePager should save original stderr."""
        original_stderr = sys.stderr
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.Mock()
            mock_process.stdin = mock.Mock()
            mock_popen.return_value = mock_process
            pager._PipePager("less")
            self.assertIs(pager.old_stderr, original_stderr)
        sys.stderr = original_stderr

    def test_pipe_pager_exits_on_file_not_found(self):
        """_PipePager should exit if pager command not found."""
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(SystemExit):
                pager._PipePager("nonexistent")

    def test_pipe_pager_asserts_no_existing_process(self):
        """_PipePager should assert no existing pager process."""
        pager.pager_process = mock.Mock()
        with self.assertRaises(AssertionError):
            pager._PipePager("less")
        pager.pager_process = None


@pytest.mark.unit
class TerminatePagerTests(unittest.TestCase):
    """Tests for TerminatePager function."""

    def setUp(self):
        """Reset pager state before each test."""
        pager.pager_process = None
        pager.old_stdout = sys.stdout
        pager.old_stderr = sys.stderr

    def tearDown(self):
        """Clean up pager state after each test."""
        pager.pager_process = None
        sys.stdout = pager.old_stdout
        sys.stderr = pager.old_stderr

    def test_terminate_pager_does_nothing_if_no_process(self):
        """TerminatePager should do nothing if no pager process."""
        pager.pager_process = None
        # Should not raise
        pager.TerminatePager()

    def test_terminate_pager_flushes_stdout(self):
        """TerminatePager should flush stdout."""
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        with mock.patch.object(sys.stdout, "flush") as mock_flush:
            pager.TerminatePager()
            mock_flush.assert_called_once()

    def test_terminate_pager_flushes_stderr(self):
        """TerminatePager should flush stderr."""
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        with mock.patch.object(sys.stderr, "flush") as mock_flush:
            pager.TerminatePager()
            mock_flush.assert_called_once()

    def test_terminate_pager_closes_stdin(self):
        """TerminatePager should close pager stdin."""
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        pager.TerminatePager()
        mock_process.stdin.close.assert_called_once()

    def test_terminate_pager_waits_for_process(self):
        """TerminatePager should wait for pager process."""
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        pager.TerminatePager()
        mock_process.wait.assert_called_once()

    def test_terminate_pager_restores_stdout(self):
        """TerminatePager should restore original stdout."""
        original_stdout = sys.stdout
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        sys.stdout = mock.Mock()
        pager.old_stdout = original_stdout
        pager.TerminatePager()
        self.assertIs(sys.stdout, original_stdout)

    def test_terminate_pager_restores_stderr(self):
        """TerminatePager should restore original stderr."""
        original_stderr = sys.stderr
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        sys.stderr = mock.Mock()
        pager.old_stderr = original_stderr
        pager.TerminatePager()
        self.assertIs(sys.stderr, original_stderr)

    def test_terminate_pager_clears_process_reference(self):
        """TerminatePager should clear pager_process reference."""
        mock_process = mock.Mock()
        mock_process.stdin = mock.Mock()
        pager.pager_process = mock_process
        pager.TerminatePager()
        self.assertIsNone(pager.pager_process)


@pytest.mark.unit
class BecomePagerTests(unittest.TestCase):
    """Tests for _BecomePager function."""

    def test_become_pager_waits_for_input(self):
        """_BecomePager should wait for input using select."""
        with mock.patch("select.select", return_value=([], [], [])) as mock_select:
            with mock.patch("os.execvp", side_effect=Exception("stop")):
                try:
                    pager._BecomePager("less")
                except Exception:
                    pass
                mock_select.assert_called_once()

    def test_become_pager_sets_less_env(self):
        """_BecomePager should set LESS environment variable if not set."""
        with mock.patch("select.select", return_value=([], [], [])):
            with mock.patch("os.execvp", side_effect=Exception("stop")):
                with mock.patch.dict(os.environ, {}, clear=True):
                    try:
                        pager._BecomePager("less")
                    except Exception:
                        pass
                    self.assertEqual(os.environ.get("LESS"), "FRX")

    def test_become_pager_preserves_existing_less_env(self):
        """_BecomePager should not override existing LESS variable."""
        with mock.patch("select.select", return_value=([], [], [])):
            with mock.patch("os.execvp", side_effect=Exception("stop")):
                with mock.patch.dict(os.environ, {"LESS": "custom"}):
                    try:
                        pager._BecomePager("less")
                    except Exception:
                        pass
                    self.assertEqual(os.environ.get("LESS"), "custom")

    def test_become_pager_calls_execvp(self):
        """_BecomePager should call os.execvp with pager."""
        with mock.patch("select.select", return_value=([], [], [])):
            with mock.patch("os.execvp") as mock_exec:
                pager._BecomePager("less")
                mock_exec.assert_called_once_with("less", ["less"])

    def test_become_pager_falls_back_to_sh(self):
        """_BecomePager should fall back to /bin/sh on OSError."""
        with mock.patch("select.select", return_value=([], [], [])):
            with mock.patch("os.execvp", side_effect=OSError):
                with mock.patch("os.execv") as mock_execv:
                    pager._BecomePager("less")
                    mock_execv.assert_called_once_with("/bin/sh", ["sh", "-c", "less"])


@pytest.mark.unit
class ForkPagerTests(unittest.TestCase):
    """Tests for _ForkPager function."""

    def test_fork_pager_sets_active_in_child(self):
        """_ForkPager should set active=True in child process."""
        with mock.patch("os.pipe", return_value=(3, 4)):
            with mock.patch("os.fork", return_value=0):  # Child process
                with mock.patch("os.dup2"):
                    with mock.patch("os.close"):
                        # Should return (not call _BecomePager)
                        pager._ForkPager("less")
                        # active should be set
                        self.assertTrue(pager.active)
        # Reset
        pager.active = False

    def test_fork_pager_redirects_output_in_child(self):
        """_ForkPager should redirect stdout/stderr in child."""
        with mock.patch("os.pipe", return_value=(3, 4)):
            with mock.patch("os.fork", return_value=0):
                with mock.patch("os.dup2") as mock_dup2:
                    with mock.patch("os.close"):
                        pager._ForkPager("less")
                        # Should dup2 write fd to stdout and stderr
                        calls = mock_dup2.call_args_list
                        self.assertEqual(len(calls), 2)
        pager.active = False

    def test_fork_pager_closes_fds_in_child(self):
        """_ForkPager should close pipe fds in child."""
        with mock.patch("os.pipe", return_value=(3, 4)):
            with mock.patch("os.fork", return_value=0):
                with mock.patch("os.dup2"):
                    with mock.patch("os.close") as mock_close:
                        pager._ForkPager("less")
                        # Should close both pipe fds
                        self.assertEqual(mock_close.call_count, 2)
        pager.active = False

    def test_fork_pager_becomes_pager_in_parent(self):
        """_ForkPager should call _BecomePager in parent."""
        with mock.patch("os.pipe", return_value=(3, 4)):
            with mock.patch("os.fork", return_value=12345):  # Parent process
                with mock.patch("os.dup2"):
                    with mock.patch("os.close"):
                        with mock.patch("kanon_cli.repo.pager._BecomePager") as mock_become:
                            pager._ForkPager("less")
                            mock_become.assert_called_once_with("less")

    def test_fork_pager_handles_exceptions(self):
        """_ForkPager should handle exceptions and exit."""
        with mock.patch("os.pipe", side_effect=Exception("test error")):
            with mock.patch("builtins.print"):
                with mock.patch("sys.exit") as mock_exit:
                    pager._ForkPager("less")
                    mock_exit.assert_called_once_with(255)
