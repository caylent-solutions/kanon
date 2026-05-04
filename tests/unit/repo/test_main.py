# Copyright (C) 2008 The Android Open Source Project
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

"""Unittests for the main.py module."""

import optparse
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import main
from kanon_cli.repo.error import DownloadError, NoManifestException, NoSuchProjectError


@pytest.mark.unit
class TestCheckRepoDir(unittest.TestCase):
    """Tests for _CheckRepoDir function."""

    @mock.patch("kanon_cli.repo.main.sys.exit")
    def test_missing_repo_dir(self, mock_exit):
        """Test that missing repo_dir causes exit."""
        main._CheckRepoDir(None)
        mock_exit.assert_called_once_with(1)

    @mock.patch("kanon_cli.repo.main.sys.exit")
    def test_empty_repo_dir(self, mock_exit):
        """Test that empty repo_dir causes exit."""
        main._CheckRepoDir("")
        mock_exit.assert_called_once_with(1)

    def test_valid_repo_dir(self):
        """Test that valid repo_dir passes."""
        # Should not raise or exit
        main._CheckRepoDir("/valid/repo/dir")


@pytest.mark.unit
class TestPruneOptions(unittest.TestCase):
    """Tests for _PruneOptions function."""

    def test_prune_unknown_options(self):
        """Test that unknown options are removed."""
        opt = optparse.OptionParser()
        opt.add_option("--known", dest="known")

        argv = ["--known", "value", "--unknown", "value2", "arg"]
        main._PruneOptions(argv, opt)

        # _PruneOptions removes anything that's not a known option
        self.assertEqual(argv, ["--known"])

    def test_prune_with_equals(self):
        """Test pruning options with = syntax."""
        opt = optparse.OptionParser()
        opt.add_option("--known", dest="known")

        argv = ["--known=value", "--unknown=value2"]
        main._PruneOptions(argv, opt)

        self.assertEqual(argv, ["--known=value"])

    def test_prune_stops_at_double_dash(self):
        """Test that pruning stops at -- separator."""
        opt = optparse.OptionParser()
        opt.add_option("--known", dest="known")

        argv = ["--known", "value", "--", "--unknown", "value2"]
        main._PruneOptions(argv, opt)

        # _PruneOptions removes non-options before --, then stops
        self.assertEqual(argv, ["--known", "--", "--unknown", "value2"])

    def test_prune_empty_list(self):
        """Test pruning empty argv."""
        opt = optparse.OptionParser()
        argv = []
        main._PruneOptions(argv, opt)
        self.assertEqual(argv, [])


@pytest.mark.unit
class TestUserAgentHandler(unittest.TestCase):
    """Tests for _UserAgentHandler class."""

    @mock.patch("kanon_cli.repo.main.user_agent")
    def test_http_request_adds_user_agent(self, mock_user_agent):
        """Test that HTTP request gets user agent header."""
        mock_user_agent.repo = "test-user-agent/1.0"
        handler = main._UserAgentHandler()

        mock_req = mock.Mock()
        result = handler.http_request(mock_req)

        mock_req.add_header.assert_called_once_with("User-Agent", "test-user-agent/1.0")
        self.assertEqual(result, mock_req)

    @mock.patch("kanon_cli.repo.main.user_agent")
    def test_https_request_adds_user_agent(self, mock_user_agent):
        """Test that HTTPS request gets user agent header."""
        mock_user_agent.repo = "test-user-agent/1.0"
        handler = main._UserAgentHandler()

        mock_req = mock.Mock()
        result = handler.https_request(mock_req)

        mock_req.add_header.assert_called_once_with("User-Agent", "test-user-agent/1.0")
        self.assertEqual(result, mock_req)


@pytest.mark.unit
class TestAddPasswordFromUserInput(unittest.TestCase):
    """Tests for _AddPasswordFromUserInput function."""

    @mock.patch("builtins.input", return_value="testuser")
    @mock.patch("getpass.getpass", return_value="testpass")
    def test_add_password_success(self, mock_getpass, mock_input):
        """Test adding password from user input."""
        mock_handler = mock.Mock()
        mock_handler.passwd.find_user_password.return_value = (None, None)
        mock_req = mock.Mock()
        mock_req.get_full_url.return_value = "http://example.com"

        main._AddPasswordFromUserInput(mock_handler, "Auth required", mock_req)

        mock_handler.passwd.add_password.assert_called_once_with(None, "http://example.com", "testuser", "testpass")

    @mock.patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_input(self, mock_input):
        """Test that keyboard interrupt is handled."""
        mock_handler = mock.Mock()
        mock_handler.passwd.find_user_password.return_value = (None, None)
        mock_req = mock.Mock()
        mock_req.get_full_url.return_value = "http://example.com"

        # Should not raise
        main._AddPasswordFromUserInput(mock_handler, "Auth required", mock_req)

        # Should not add password
        mock_handler.passwd.add_password.assert_not_called()

    def test_existing_user_skips_input(self):
        """Test that existing user skips password input."""
        mock_handler = mock.Mock()
        mock_handler.passwd.find_user_password.return_value = (
            "existinguser",
            "existingpass",
        )
        mock_req = mock.Mock()
        mock_req.get_full_url.return_value = "http://example.com"

        with mock.patch("builtins.input") as mock_input:
            main._AddPasswordFromUserInput(mock_handler, "Auth required", mock_req)
            mock_input.assert_not_called()


@pytest.mark.unit
class TestInitHttp(unittest.TestCase):
    """Tests for init_http function."""

    @mock.patch("urllib.request.install_opener")
    @mock.patch("urllib.request.build_opener")
    @mock.patch("netrc.netrc")
    def test_init_http_with_netrc(self, mock_netrc, mock_build_opener, mock_install):
        """Test HTTP initialization with netrc credentials."""
        mock_netrc_instance = mock.Mock()
        mock_netrc_instance.hosts = {"example.com": ("user1", "account1", "pass1")}
        mock_netrc.return_value = mock_netrc_instance

        main.init_http()

        mock_build_opener.assert_called_once()
        mock_install.assert_called_once()

    @mock.patch("urllib.request.install_opener")
    @mock.patch("urllib.request.build_opener")
    @mock.patch("netrc.netrc", side_effect=OSError)
    def test_init_http_without_netrc(self, mock_netrc, mock_build_opener, mock_install):
        """Test HTTP initialization when netrc is missing."""
        main.init_http()

        mock_build_opener.assert_called_once()
        mock_install.assert_called_once()

    @mock.patch("urllib.request.install_opener")
    @mock.patch("urllib.request.build_opener")
    @mock.patch("os.environ", {"http_proxy": "http://proxy.example.com:8080"})
    def test_init_http_with_proxy(self, mock_build_opener, mock_install):
        """Test HTTP initialization with proxy settings."""
        with mock.patch("netrc.netrc", side_effect=OSError):
            main.init_http()

        mock_build_opener.assert_called_once()
        mock_install.assert_called_once()

    @mock.patch("urllib.request.install_opener")
    @mock.patch("urllib.request.build_opener")
    @mock.patch("os.environ", {"REPO_CURL_VERBOSE": "1"})
    def test_init_http_with_verbose(self, mock_build_opener, mock_install):
        """Test HTTP initialization with verbose debugging."""
        with mock.patch("netrc.netrc", side_effect=OSError):
            main.init_http()

        mock_build_opener.assert_called_once()
        mock_install.assert_called_once()


@pytest.mark.unit
class TestRepoClass(unittest.TestCase):
    """Tests for _Repo class."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = main._Repo("/test/repodir")

    def test_init(self):
        """Test _Repo initialization."""
        self.assertEqual(self.repo.repodir, "/test/repodir")
        self.assertIsNotNone(self.repo.commands)

    @mock.patch("kanon_cli.repo.main.global_options")
    @mock.patch("kanon_cli.repo.main.Wrapper")
    def test_print_help_short(self, mock_wrapper, mock_global_options):
        """Test short help output."""
        mock_wrapper.return_value.BUG_URL = "http://bugs.example.com"
        self.repo.commands = {"help": mock.Mock(), "sync": mock.Mock()}

        with mock.patch("builtins.print") as mock_print:
            self.repo._PrintHelp(short=True)

        mock_global_options.print_help.assert_called_once()
        mock_print.assert_called()

    @mock.patch("kanon_cli.repo.main.global_options")
    def test_print_help_full(self, mock_global_options):
        """Test full help output."""
        mock_help_cmd = mock.Mock()
        self.repo.commands = {"help": lambda: mock_help_cmd}

        self.repo._PrintHelp(short=False, all_commands=False)

        mock_global_options.print_help.assert_called_once()
        mock_help_cmd.PrintCommonCommandsBody.assert_called_once()

    @mock.patch("kanon_cli.repo.main.global_options")
    def test_print_help_all_commands(self, mock_global_options):
        """Test help with all commands."""
        mock_help_cmd = mock.Mock()
        self.repo.commands = {"help": lambda: mock_help_cmd}

        self.repo._PrintHelp(short=False, all_commands=True)

        mock_global_options.print_help.assert_called_once()
        mock_help_cmd.PrintAllCommandsBody.assert_called_once()

    def test_parse_args_no_command(self):
        """Test parsing args without a command."""
        name, gopts, argv = self.repo._ParseArgs(["-h"])

        self.assertIsNone(name)
        self.assertEqual(argv, [])

    def test_parse_args_with_command(self):
        """Test parsing args with a command."""
        name, gopts, argv = self.repo._ParseArgs(["sync", "-j4"])

        self.assertEqual(name, "sync")
        self.assertEqual(argv, ["-j4"])

    def test_parse_args_with_global_options(self):
        """Test parsing args with global options before command."""
        name, gopts, argv = self.repo._ParseArgs(["--trace", "sync", "-j4"])

        self.assertEqual(name, "sync")
        self.assertEqual(argv, ["-j4"])

    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_no_alias(self, mock_repo_config):
        """Test expanding non-existent alias."""
        mock_config = mock.Mock()
        mock_config.GetString.return_value = None
        mock_repo_config.ForRepository.return_value = mock_config
        mock_repo_config.ForUser.return_value = mock_config

        self.repo.commands = {"sync": mock.Mock()}
        name, args = self.repo._ExpandAlias("sync")

        self.assertEqual(name, "sync")
        self.assertEqual(args, [])

    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_existing_command(self, mock_repo_config):
        """Test that existing commands are not aliased."""
        mock_config = mock.Mock()
        mock_config.GetString.return_value = "other-command"
        mock_repo_config.ForRepository.return_value = mock_config

        self.repo.commands = {"sync": mock.Mock()}
        name, args = self.repo._ExpandAlias("sync")

        self.assertEqual(name, "sync")
        self.assertEqual(args, [])

    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_with_args(self, mock_repo_config):
        """Test expanding alias with arguments."""
        mock_config = mock.Mock()
        mock_config.GetString.return_value = "sync -j4"
        mock_repo_config.ForRepository.return_value = mock_config

        name, args = self.repo._ExpandAlias("mysync")

        self.assertEqual(name, "sync")
        self.assertEqual(args, ["-j4"])

    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_from_user_config(self, mock_repo_config):
        """Test expanding alias from user config."""
        mock_repo_conf = mock.Mock()
        mock_repo_conf.GetString.return_value = None
        mock_user_conf = mock.Mock()
        mock_user_conf.GetString.return_value = "sync"
        mock_repo_config.ForRepository.return_value = mock_repo_conf
        mock_repo_config.ForUser.return_value = mock_user_conf

        name, args = self.repo._ExpandAlias("mysync")

        self.assertEqual(name, "sync")
        self.assertEqual(args, [])


@pytest.mark.unit
class TestRepoRun(unittest.TestCase):
    """Tests for _Repo._Run method."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = main._Repo("/test/repodir")

    @mock.patch("kanon_cli.repo.main.global_options")
    def test_run_help_flag(self, mock_global_options):
        """Test running with --help flag."""
        mock_gopts = mock.Mock()
        mock_gopts.help = True
        mock_gopts.help_all = False

        with mock.patch.object(self.repo, "_PrintHelp") as mock_print_help:
            result = self.repo._Run(None, mock_gopts, [])

        mock_print_help.assert_called_once_with(short=False, all_commands=False)
        self.assertEqual(result, 0)

    @mock.patch("kanon_cli.repo.main.global_options")
    def test_run_help_all_flag(self, mock_global_options):
        """Test running with --help-all flag."""
        mock_gopts = mock.Mock()
        mock_gopts.help = False
        mock_gopts.help_all = True

        with mock.patch.object(self.repo, "_PrintHelp") as mock_print_help:
            result = self.repo._Run(None, mock_gopts, [])

        mock_print_help.assert_called_once_with(short=False, all_commands=True)
        self.assertEqual(result, 0)

    @mock.patch("kanon_cli.repo.main.global_options")
    def test_run_show_version(self, mock_global_options):
        """Test running with --version flag."""
        mock_gopts = mock.Mock()
        mock_gopts.help = False
        mock_gopts.help_all = False
        mock_gopts.show_version = True
        mock_gopts.trace_python = False

        with mock.patch.object(self.repo, "_RunLong", return_value=0):
            result = self.repo._Run(None, mock_gopts, [])

        self.assertEqual(result, 0)

    def test_run_show_toplevel(self):
        """Test running with --show-toplevel flag."""
        mock_gopts = mock.Mock()
        mock_gopts.help = False
        mock_gopts.help_all = False
        mock_gopts.show_version = False
        mock_gopts.show_toplevel = True

        with mock.patch("builtins.print") as mock_print:
            result = self.repo._Run(None, mock_gopts, [])

        mock_print.assert_called_once()
        self.assertEqual(result, 0)

    def test_run_no_subcommand(self):
        """Test running without a subcommand."""
        mock_gopts = mock.Mock()
        mock_gopts.help = False
        mock_gopts.help_all = False
        mock_gopts.show_version = False
        mock_gopts.show_toplevel = False

        with mock.patch.object(self.repo, "_PrintHelp") as mock_print_help:
            result = self.repo._Run(None, mock_gopts, [])

        mock_print_help.assert_called_once_with(short=True)
        self.assertEqual(result, 1)

    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Trace")
    def test_run_with_trace_python(self, mock_trace, mock_event_log):
        """Test running with --trace-python flag."""
        mock_gopts = mock.Mock()
        mock_gopts.help = False
        mock_gopts.help_all = False
        mock_gopts.show_version = False
        mock_gopts.show_toplevel = False
        mock_gopts.trace_python = True

        with mock.patch.object(self.repo, "_RunLong", return_value=0):
            result = self.repo._Run("sync", mock_gopts, [])

        self.assertEqual(result, 0)


@pytest.mark.unit
class TestRepoRunLong(unittest.TestCase):
    """Tests for _Repo._RunLong method."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = main._Repo("/test/repodir")

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_runlong_unknown_command(self, mock_editor, mock_color, mock_client):
        """Test running unknown command."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None

        mock_git_log = mock.Mock()
        result = self.repo._RunLong("unknowncmd", mock_gopts, [], mock_git_log)

        self.assertEqual(result, 1)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_runlong_no_manifest_exception(self, mock_time, mock_editor, mock_color, mock_client):
        """Test handling NoManifestException."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False

        mock_cmd = mock.Mock()
        mock_cmd.OptionParser.parse_args.side_effect = NoManifestException(
            path="/path/to/manifest", reason="Manifest not found"
        )

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.return_value = 0.0

        result = self.repo._RunLong("sync", mock_gopts, [], mock_git_log)

        self.assertEqual(result, 1)


@pytest.mark.unit
class TestRepoExceptionHandling(unittest.TestCase):
    """Tests for exception handling in _Repo._RunLong."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = main._Repo("/test/repodir")

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_download_error_handling(self, mock_time, mock_editor, mock_color, mock_client):
        """Test handling DownloadError."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None

        mock_copts = mock.Mock()
        mock_copts.this_manifest_only = False
        mock_copts.outer_manifest = False

        mock_cmd = mock.Mock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (mock_copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = mock_copts
        mock_cmd.Execute.side_effect = DownloadError("Download failed")
        mock_cmd.event_log.Add.return_value = "event"

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.return_value = 0.0

        result = self.repo._RunLong("sync", mock_gopts, [], mock_git_log)

        self.assertNotEqual(result, 0)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_no_such_project_error(self, mock_time, mock_editor, mock_color, mock_client):
        """Test handling NoSuchProjectError."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None

        mock_copts = mock.Mock()
        mock_copts.this_manifest_only = False
        mock_copts.outer_manifest = False

        mock_cmd = mock.Mock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (mock_copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = mock_copts
        mock_cmd.Execute.side_effect = NoSuchProjectError("project1")
        mock_cmd.event_log.Add.return_value = "event"

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.return_value = 0.0

        result = self.repo._RunLong("sync", mock_gopts, [], mock_git_log)

        self.assertNotEqual(result, 0)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_keyboard_interrupt(self, mock_time, mock_editor, mock_color, mock_client):
        """Test handling KeyboardInterrupt."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = False
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None

        mock_copts = mock.Mock()
        mock_copts.this_manifest_only = False
        mock_copts.outer_manifest = False

        mock_cmd = mock.Mock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (mock_copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = mock_copts
        mock_cmd.Execute.side_effect = KeyboardInterrupt()
        mock_cmd.event_log.Add.return_value = "event"

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.return_value = 0.0

        with self.assertRaises(KeyboardInterrupt):
            self.repo._RunLong("sync", mock_gopts, [], mock_git_log)


@pytest.mark.unit
class TestBasicAuthHandler(unittest.TestCase):
    """Tests for _BasicAuthHandler class."""

    @mock.patch("kanon_cli.repo.main._AddPasswordFromUserInput")
    @mock.patch("urllib.request.HTTPBasicAuthHandler.http_error_401")
    def test_http_error_401(self, mock_parent_handler, mock_add_password):
        """Test handling 401 error."""
        handler = main._BasicAuthHandler()
        mock_req = mock.Mock()
        mock_fp = mock.Mock()

        handler.http_error_401(mock_req, mock_fp, 401, "Unauthorized", {})

        mock_add_password.assert_called_once()


@pytest.mark.unit
class TestDigestAuthHandler(unittest.TestCase):
    """Tests for _DigestAuthHandler class."""

    @mock.patch("kanon_cli.repo.main._AddPasswordFromUserInput")
    @mock.patch("urllib.request.HTTPDigestAuthHandler.http_error_401")
    def test_http_error_401(self, mock_parent_handler, mock_add_password):
        """Test handling 401 error."""
        handler = main._DigestAuthHandler()
        mock_req = mock.Mock()
        mock_fp = mock.Mock()

        handler.http_error_401(mock_req, mock_fp, 401, "Unauthorized", {})

        mock_add_password.assert_called_once()


@pytest.mark.unit
class TestKerberosAuthHandler(unittest.TestCase):
    """Tests for _KerberosAuthHandler class."""

    def test_init(self):
        """Test initialization of KerberosAuthHandler."""
        handler = main._KerberosAuthHandler()

        self.assertEqual(handler.retried, 0)
        self.assertIsNone(handler.context)

    def test_reset_retry_count(self):
        """Test reset_retry_count method."""
        handler = main._KerberosAuthHandler()
        handler.retried = 5

        handler.reset_retry_count()

        self.assertEqual(handler.retried, 0)


@pytest.mark.unit
class TestConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_keyboard_interrupt_exit_code(self):
        """Test KEYBOARD_INTERRUPT_EXIT constant."""
        import signal

        self.assertEqual(main.KEYBOARD_INTERRUPT_EXIT, 128 + signal.SIGINT)

    def test_max_print_errors(self):
        """Test MAX_PRINT_ERRORS constant."""
        self.assertGreater(main.MAX_PRINT_ERRORS, 0)

    def test_min_python_version_soft(self):
        """Test MIN_PYTHON_VERSION_SOFT constant."""
        self.assertIsInstance(main.MIN_PYTHON_VERSION_SOFT, tuple)
        self.assertEqual(len(main.MIN_PYTHON_VERSION_SOFT), 2)

    def test_min_python_version_hard(self):
        """Test MIN_PYTHON_VERSION_HARD constant."""
        self.assertIsInstance(main.MIN_PYTHON_VERSION_HARD, tuple)
        self.assertEqual(len(main.MIN_PYTHON_VERSION_HARD), 2)


@pytest.mark.unit
class TestGlobalOptions(unittest.TestCase):
    """Tests for global_options OptionParser."""

    def test_global_options_exists(self):
        """Test that global_options parser exists."""
        self.assertIsInstance(main.global_options, optparse.OptionParser)

    def test_help_option_exists(self):
        """Test that --help option exists."""
        self.assertTrue(main.global_options.has_option("--help"))

    def test_version_option_exists(self):
        """Test that --version option exists."""
        self.assertTrue(main.global_options.has_option("--version"))

    def test_trace_option_exists(self):
        """Test that --trace option exists."""
        self.assertTrue(main.global_options.has_option("--trace"))

    def test_color_option_exists(self):
        """Test that --color option exists."""
        self.assertTrue(main.global_options.has_option("--color"))

    def test_pager_options_exist(self):
        """Test that pager options exist."""
        self.assertTrue(main.global_options.has_option("--paginate"))
        self.assertTrue(main.global_options.has_option("--no-pager"))


@pytest.mark.unit
class TestTimeFormatting(unittest.TestCase):
    """Tests for time formatting in _RunLong."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = main._Repo("/test/repodir")

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    @mock.patch("sys.stderr")
    def test_time_formatting_minutes_only(self, mock_stderr, mock_time, mock_editor, mock_color, mock_client):
        """Test time formatting with minutes only."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = True
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None

        mock_copts = mock.Mock()
        mock_copts.this_manifest_only = False
        mock_copts.outer_manifest = False

        mock_cmd = mock.Mock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (mock_copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = mock_copts
        mock_cmd.Execute.return_value = 0
        mock_cmd.event_log.Add.return_value = "event"

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.side_effect = [0.0, 90.5]

        with mock.patch("builtins.print") as mock_print:
            self.repo._RunLong("sync", mock_gopts, [], mock_git_log)

        # Verify time was printed
        calls = [str(call) for call in mock_print.call_args_list]
        time_printed = any("real" in str(call) for call in calls)
        self.assertTrue(time_printed)

    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.Editor")
    @mock.patch("kanon_cli.repo.main.time")
    def test_time_formatting_with_hours(self, mock_time, mock_editor, mock_color, mock_client):
        """Test time formatting with hours."""
        mock_gopts = mock.Mock()
        mock_gopts.color = None
        mock_gopts.submanifest_path = None
        mock_gopts.pager = False
        mock_gopts.time = True
        mock_gopts.event_log = None
        mock_gopts.git_trace2_event_log = None

        mock_copts = mock.Mock()
        mock_copts.this_manifest_only = False
        mock_copts.outer_manifest = False

        mock_cmd = mock.Mock()
        mock_cmd.manifest.IsMirror = False
        mock_cmd.MULTI_MANIFEST_SUPPORT = True
        mock_cmd.OptionParser.parse_args.return_value = (mock_copts, [])
        mock_cmd.ReadEnvironmentOptions.return_value = mock_copts
        mock_cmd.Execute.return_value = 0
        mock_cmd.event_log.Add.return_value = "event"

        self.repo.commands = {"sync": lambda **kwargs: mock_cmd}

        mock_git_log = mock.Mock()
        mock_time.time.side_effect = [0.0, 3661.5]

        with mock.patch("builtins.print") as mock_print:
            self.repo._RunLong("sync", mock_gopts, [], mock_git_log)

        # Verify time was printed with hours
        calls = [str(call) for call in mock_print.call_args_list]
        time_printed = any("real" in str(call) and "h" in str(call) for call in calls)
        self.assertTrue(time_printed)
