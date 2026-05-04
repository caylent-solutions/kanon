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

"""Unittests for the git_command.py module."""

import io
import os
import re
import subprocess
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import git_command
from kanon_cli.repo import wrapper


class GitCommandTest(unittest.TestCase):
    """Tests the GitCommand class (via git_command.git)."""

    def setUp(self):
        def realpath_mock(val, **kwargs):
            return val

        mock.patch.object(os.path, "realpath", side_effect=realpath_mock).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_alternative_setting_when_matching(self):
        r = git_command._build_env(objdir=os.path.join("zap", "objects"), gitdir="zap")

        self.assertIsNone(r.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"))
        self.assertEqual(r.get("GIT_OBJECT_DIRECTORY"), os.path.join("zap", "objects"))

    def test_alternative_setting_when_different(self):
        r = git_command._build_env(objdir=os.path.join("wow", "objects"), gitdir="zap")

        self.assertEqual(
            r.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"),
            os.path.join("zap", "objects"),
        )
        self.assertEqual(r.get("GIT_OBJECT_DIRECTORY"), os.path.join("wow", "objects"))


class GitCommandWaitTest(unittest.TestCase):
    """Tests the GitCommand class .Wait()"""

    def setUp(self):
        class MockPopen:
            rc = 0

            def __init__(self):
                self.stdout = io.BufferedReader(io.BytesIO())
                self.stderr = io.BufferedReader(io.BytesIO())

            def communicate(self, input: str = None, timeout: float = None) -> [str, str]:
                """Mock communicate fn."""
                return ["", ""]

            def wait(self, timeout=None):
                return self.rc

        self.popen = popen = MockPopen()

        def popen_mock(*args, **kwargs):
            return popen

        def realpath_mock(val, **kwargs):
            return val

        mock.patch.object(subprocess, "Popen", side_effect=popen_mock).start()

        mock.patch.object(os.path, "realpath", side_effect=realpath_mock).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_raises_when_verify_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"], verify_command=True)
        with self.assertRaises(git_command.GitCommandError):
            r.Wait()

    def test_returns_when_no_verify_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"], verify_command=False)
        self.assertEqual(1, r.Wait())

    def test_default_returns_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"])
        self.assertEqual(1, r.Wait())


class GitCommandStreamLogsTest(unittest.TestCase):
    """Tests the GitCommand class stderr log streaming cases."""

    def setUp(self):
        self.mock_process = mock.MagicMock()
        self.mock_process.communicate.return_value = (None, None)
        self.mock_process.wait.return_value = 0

        self.mock_popen = mock.MagicMock()
        self.mock_popen.return_value = self.mock_process
        mock.patch("subprocess.Popen", self.mock_popen).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_does_not_stream_logs_when_input_is_set(self):
        git_command.GitCommand(None, ["status"], input="foo")

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
        )
        self.mock_process.communicate.assert_called_once_with(input="foo")
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_stdout_is_set(self):
        git_command.GitCommand(None, ["status"], capture_stdout=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_stderr_is_set(self):
        git_command.GitCommand(None, ["status"], capture_stderr=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=None,
            stderr=subprocess.PIPE,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_merge_output_is_set(self):
        git_command.GitCommand(None, ["status"], merge_output=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=None,
            stderr=subprocess.STDOUT,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    @mock.patch("sys.stderr")
    def test_streams_stderr_when_no_stream_is_set(self, mock_stderr):
        logs = "\n".join(
            [
                "Enumerating objects: 5, done.",
                "Counting objects: 100% (5/5), done.",
                "Writing objects: 100% (3/3), 330 bytes | 330 KiB/s, done.",
                "remote: Processing changes: refs: 1, new: 1, done ",
                "remote: SUCCESS",
            ]
        )
        self.mock_process.stderr = io.BufferedReader(io.BytesIO(bytes(logs, "utf-8")))

        cmd = git_command.GitCommand(None, ["push"])

        self.mock_popen.assert_called_once_with(
            ["git", "push"],
            cwd=None,
            env=mock.ANY,
            stdin=None,
            stdout=None,
            stderr=subprocess.PIPE,
        )
        self.mock_process.communicate.assert_not_called()
        mock_stderr.write.assert_called_once_with(logs)
        self.assertEqual(cmd.stderr, logs)


class GitCallUnitTest(unittest.TestCase):
    """Tests the _GitCall class (via git_command.git)."""

    def test_version_tuple(self):
        """Check git.version_tuple() handling."""
        ver = git_command.git.version_tuple()
        self.assertIsNotNone(ver)

        # We don't dive too deep into the values here to avoid having to update
        # whenever git versions change.  We do check relative to this min
        # version as this is what `repo` itself requires via MIN_GIT_VERSION.
        MIN_GIT_VERSION = (2, 10, 2)
        self.assertTrue(isinstance(ver.major, int))
        self.assertTrue(isinstance(ver.minor, int))
        self.assertTrue(isinstance(ver.micro, int))

        self.assertGreater(ver.major, MIN_GIT_VERSION[0] - 1)
        self.assertGreaterEqual(ver.micro, 0)
        self.assertGreaterEqual(ver.major, 0)

        self.assertGreaterEqual(ver, MIN_GIT_VERSION)
        self.assertLess(ver, (9999, 9999, 9999))

        self.assertNotEqual("", ver.full)


class UserAgentUnitTest(unittest.TestCase):
    """Tests the UserAgent function."""

    def test_smoke_os(self):
        """Make sure UA OS setting returns something useful."""
        os_name = git_command.user_agent.os
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^[^ ]+$", os_name)
        self.assertIsNotNone(m)

    def test_smoke_repo(self):
        """Make sure repo UA returns something useful."""
        ua = git_command.user_agent.repo
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^git-repo/[^ ]+ ([^ ]+) git/[^ ]+ Python/[0-9.]+", ua)
        self.assertIsNotNone(m)

    def test_smoke_git(self):
        """Make sure git UA returns something useful."""
        ua = git_command.user_agent.git
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^git/[^ ]+ ([^ ]+) git-repo/[^ ]+", ua)
        self.assertIsNotNone(m)


class GitRequireTests(unittest.TestCase):
    """Test the git_require helper."""

    def setUp(self):
        self.wrapper = wrapper.Wrapper()
        ver = self.wrapper.GitVersion(1, 2, 3, 4)
        mock.patch.object(git_command.git, "version_tuple", return_value=ver).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_older_nonfatal(self):
        """Test non-fatal require calls with old versions."""
        self.assertFalse(git_command.git_require((2,)))
        self.assertFalse(git_command.git_require((1, 3)))
        self.assertFalse(git_command.git_require((1, 2, 4)))
        self.assertFalse(git_command.git_require((1, 2, 3, 5)))

    def test_newer_nonfatal(self):
        """Test non-fatal require calls with newer versions."""
        self.assertTrue(git_command.git_require((0,)))
        self.assertTrue(git_command.git_require((1, 0)))
        self.assertTrue(git_command.git_require((1, 2, 0)))
        self.assertTrue(git_command.git_require((1, 2, 3, 0)))

    def test_equal_nonfatal(self):
        """Test require calls with equal values."""
        self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=False))
        self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=True))

    def test_older_fatal(self):
        """Test fatal require calls with old versions."""
        with self.assertRaises(git_command.GitRequireError) as e:
            git_command.git_require((2,), fail=True)
            self.assertNotEqual(0, e.code)

    def test_older_fatal_msg(self):
        """Test fatal require calls with old versions and message."""
        with self.assertRaises(git_command.GitRequireError) as e:
            git_command.git_require((2,), fail=True, msg="so sad")
            self.assertNotEqual(0, e.code)


class GitCommandErrorTest(unittest.TestCase):
    """Test for the GitCommandError class."""

    def test_augument_stderr(self):
        self.assertEqual(
            git_command.GitCommandError(git_stderr="couldn't find remote ref refs/heads/foo").suggestion,
            "Check if the provided ref exists in the remote.",
        )

        self.assertEqual(
            git_command.GitCommandError(git_stderr="'foobar' does not appear to be a git repository").suggestion,
            "Are you running this repo command outside of a repo workspace?",
        )


# Additional comprehensive tests below


@pytest.mark.unit
class TestGitCommandExtended(unittest.TestCase):
    """Extended tests for GitCommand class."""

    def setUp(self):
        self.mock_process = mock.MagicMock()
        self.mock_process.communicate.return_value = ("stdout", "stderr")
        self.mock_process.wait.return_value = 0
        self.mock_process.stdout = "stdout"
        self.mock_process.stderr = "stderr"

        self.mock_popen = mock.MagicMock()
        self.mock_popen.return_value = self.mock_process
        mock.patch("subprocess.Popen", self.mock_popen).start()
        mock.patch.object(os.path, "realpath", side_effect=lambda x: x).start()

        # Mock git version_tuple to avoid git command execution
        mock_version = wrapper.Wrapper().GitVersion(2, 28, 0, 0)
        mock.patch.object(git_command.git, "version_tuple", return_value=mock_version).start()

    def tearDown(self):
        mock.patch.stopall()


@pytest.mark.unit
class TestBuildEnv(unittest.TestCase):
    """Tests for _build_env function."""

    def test_build_env_basic(self):
        """Test _build_env returns basic environment."""
        env = git_command._build_env()
        self.assertIn("GIT_HTTP_USER_AGENT", env)
        self.assertIn("GIT_ALLOW_PROTOCOL", env)

    def test_build_env_disable_editor(self):
        """Test _build_env with disable_editor=True."""
        env = git_command._build_env(disable_editor=True)
        self.assertEqual(env["GIT_EDITOR"], ":")

    def test_build_env_with_ssh_proxy(self):
        """Test _build_env with ssh_proxy."""
        ssh_proxy = mock.MagicMock()
        ssh_proxy.sock.return_value = "/tmp/sock"
        ssh_proxy.proxy = "/usr/bin/ssh"

        env = git_command._build_env(ssh_proxy=ssh_proxy)
        self.assertEqual(env["REPO_SSH_SOCK"], "/tmp/sock")
        self.assertEqual(env["GIT_SSH"], "/usr/bin/ssh")
        self.assertEqual(env["GIT_SSH_VARIANT"], "ssh")

    def test_build_env_with_objdir(self):
        """Test _build_env with objdir."""
        env = git_command._build_env(objdir="/path/to/objects")
        self.assertEqual(env["GIT_OBJECT_DIRECTORY"], "/path/to/objects")

    def test_build_env_with_objdir_and_gitdir(self):
        """Test _build_env with both objdir and gitdir."""
        with mock.patch.object(os.path, "realpath", side_effect=lambda x: x):
            env = git_command._build_env(objdir="/path/to/objects", gitdir="/path/to/gitdir")
        self.assertEqual(env["GIT_OBJECT_DIRECTORY"], "/path/to/objects")

    def test_build_env_with_bare_and_gitdir(self):
        """Test _build_env with bare=True and gitdir."""
        env = git_command._build_env(bare=True, gitdir="/path/to/gitdir")
        self.assertEqual(env["GIT_DIR"], "/path/to/gitdir")

    def test_build_env_http_proxy_darwin(self):
        """Test _build_env handles http_proxy on darwin."""
        with mock.patch("sys.platform", "darwin"):
            with mock.patch.dict(os.environ, {"http_proxy": "http://proxy:8080"}):
                env = git_command._build_env()
                self.assertIn("GIT_CONFIG_PARAMETERS", env)


@pytest.mark.unit
class TestRepoSourceVersion(unittest.TestCase):
    """Tests for RepoSourceVersion function."""

    def test_RepoSourceVersion_returns_string(self):
        """Test RepoSourceVersion() returns a string."""
        version = git_command.RepoSourceVersion()
        self.assertIsInstance(version, str)

    def test_RepoSourceVersion_cached(self):
        """Test RepoSourceVersion() is cached."""
        version1 = git_command.RepoSourceVersion()
        version2 = git_command.RepoSourceVersion()
        self.assertEqual(version1, version2)


@pytest.mark.unit
class TestGitRequireExtended(unittest.TestCase):
    """Extended tests for git_require function."""

    def setUp(self):
        self.wrapper = wrapper.Wrapper()
        ver = self.wrapper.GitVersion(2, 28, 0, 0)
        mock.patch.object(git_command.git, "version_tuple", return_value=ver).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_git_require_exact_match(self):
        """Test git_require with exact version match."""
        self.assertTrue(git_command.git_require((2, 28, 0)))

    def test_git_require_newer_required(self):
        """Test git_require with newer version required."""
        self.assertFalse(git_command.git_require((3, 0, 0)))

    def test_git_require_older_required(self):
        """Test git_require with older version required."""
        self.assertTrue(git_command.git_require((2, 27, 0)))

    def test_git_require_with_message(self):
        """Test git_require with custom message."""
        with self.assertRaises(git_command.GitRequireError):
            git_command.git_require((3, 0, 0), fail=True, msg="custom message")


@pytest.mark.unit
class TestUserAgentExtended(unittest.TestCase):
    """Extended tests for UserAgent class."""

    def test_user_agent_os_linux(self):
        """Test UserAgent.os on Linux."""
        with mock.patch("sys.platform", "linux"):
            ua = git_command.UserAgent()
            self.assertEqual(ua.os, "Linux")

    def test_user_agent_os_win32(self):
        """Test UserAgent.os on Windows."""
        with mock.patch("sys.platform", "win32"):
            ua = git_command.UserAgent()
            self.assertEqual(ua.os, "Win32")

    def test_user_agent_os_darwin(self):
        """Test UserAgent.os on macOS."""
        with mock.patch("sys.platform", "darwin"):
            ua = git_command.UserAgent()
            self.assertEqual(ua.os, "Darwin")

    def test_user_agent_os_cygwin(self):
        """Test UserAgent.os on Cygwin."""
        with mock.patch("sys.platform", "cygwin"):
            ua = git_command.UserAgent()
            self.assertEqual(ua.os, "Cygwin")


@pytest.mark.unit
class TestGitCommandError(unittest.TestCase):
    """Extended tests for GitCommandError class."""

    def test_GitCommandError_with_project(self):
        """Test GitCommandError with project."""
        err = git_command.GitCommandError(project="myproject", command_args=["status"], git_rc=1)
        self.assertIn("myproject", str(err))

    def test_GitCommandError_with_stdout(self):
        """Test GitCommandError with stdout."""
        err = git_command.GitCommandError(git_stdout="stdout content", command_args=["status"])
        self.assertIn("stdout: stdout content", str(err))

    def test_GitCommandError_with_stderr(self):
        """Test GitCommandError with stderr."""
        err = git_command.GitCommandError(git_stderr="stderr content", command_args=["status"])
        self.assertIn("stderr: stderr content", str(err))

    def test_GitCommandError_suggestion_unable_to_access(self):
        """Test GitCommandError suggestion for access errors."""
        err = git_command.GitCommandError(git_stderr="unable to access 'https://example.com': Connection refused")
        self.assertIsNotNone(err.suggestion)
        self.assertIn("access rights", err.suggestion)

    def test_GitCommandError_suggestion_not_git_repository(self):
        """Test GitCommandError suggestion for not a git repository."""
        err = git_command.GitCommandError(git_stderr="not a git repository")
        self.assertIsNotNone(err.suggestion)
        self.assertIn("outside of a repo workspace", err.suggestion)

    def test_GitCommandError_no_suggestion(self):
        """Test GitCommandError with no matching suggestion."""
        err = git_command.GitCommandError(git_stderr="some other error")
        self.assertIsNone(err.suggestion)

    def test_GitCommandError_custom_message(self):
        """Test GitCommandError with custom message."""
        err = git_command.GitCommandError(message="custom error message", command_args=["status"])
        self.assertIn("custom error message", str(err))

    def test_GitCommandError_str_format(self):
        """Test GitCommandError string format."""
        err = git_command.GitCommandError(project="myproject", command_args=["status", "--short"], git_rc=128)
        error_str = str(err)
        self.assertIn("GitCommandError", error_str)
        self.assertIn("status --short", error_str)
        self.assertIn("myproject", error_str)


@pytest.mark.unit
class TestGitRequireError(unittest.TestCase):
    """Tests for GitRequireError class."""

    def test_GitRequireError_default_exit_code(self):
        """Test GitRequireError has default exit code."""
        err = git_command.GitRequireError("test message")
        self.assertEqual(err.exit_code, git_command.INVALID_GIT_EXIT_CODE)

    def test_GitRequireError_custom_exit_code(self):
        """Test GitRequireError with custom exit code."""
        err = git_command.GitRequireError("test message", exit_code=42)
        self.assertEqual(err.exit_code, 42)

    def test_GitRequireError_message(self):
        """Test GitRequireError message."""
        err = git_command.GitRequireError("custom error")
        self.assertIn("custom error", str(err))


@pytest.mark.unit
class TestGetEventTargetPath(unittest.TestCase):
    """Tests for GetEventTargetPath function."""

    def test_GetEventTargetPath_returns_none_when_not_set(self):
        """Test GetEventTargetPath returns None when config not set."""
        with mock.patch("kanon_cli.repo.git_command.GitCommand") as mock_git_cmd:
            mock_instance = mock.MagicMock()
            mock_instance.Wait.return_value = 1
            mock_git_cmd.return_value = mock_instance

            # Clear cache
            git_command.GetEventTargetPath.cache_clear()
            result = git_command.GetEventTargetPath()
            self.assertIsNone(result)

    def test_GetEventTargetPath_returns_path_when_set(self):
        """Test GetEventTargetPath returns path when config is set."""
        with mock.patch("kanon_cli.repo.git_command.GitCommand") as mock_git_cmd:
            mock_instance = mock.MagicMock()
            mock_instance.Wait.return_value = 0
            mock_instance.stdout = "/path/to/trace\n"
            mock_git_cmd.return_value = mock_instance

            # Clear cache
            git_command.GetEventTargetPath.cache_clear()
            result = git_command.GetEventTargetPath()
            self.assertEqual(result, "/path/to/trace")


@pytest.mark.unit
class TestGitPopenCommandError(unittest.TestCase):
    """Tests for GitPopenCommandError class."""

    def test_GitPopenCommandError_creation(self):
        """Test GitPopenCommandError can be created."""
        err = git_command.GitPopenCommandError(message="popen failed", project="myproject", command_args=["status"])
        self.assertIn("popen failed", str(err))


@pytest.mark.unit
class TestGitCallExtended(unittest.TestCase):
    """Extended tests for _GitCall class."""

    def test_git_call_attribute_conversion(self):
        """Test _GitCall converts underscores to dashes."""
        with mock.patch("kanon_cli.repo.git_command.GitCommand") as mock_git_cmd:
            mock_instance = mock.MagicMock()
            mock_instance.Wait.return_value = 0
            mock_git_cmd.return_value = mock_instance

            git_command.git.symbolic_ref("HEAD")

            call_args = mock_git_cmd.call_args[0]
            self.assertEqual(call_args[1][0], "symbolic-ref")
