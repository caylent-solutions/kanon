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

"""Unit tests for main.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo import main
from kanon_cli.repo.error import (
    DownloadError,
    InvalidProjectGroupsError,
    ManifestParseError,
    NoManifestException,
    NoSuchProjectError,
)


class TestCheckRepoDir:
    """Test _CheckRepoDir function."""

    @pytest.mark.unit
    def test_check_repo_dir_none(self):
        """Test _CheckRepoDir with None raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main._CheckRepoDir(None)
        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_check_repo_dir_empty_string(self):
        """Test _CheckRepoDir with empty string raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main._CheckRepoDir("")
        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_check_repo_dir_valid(self):
        """Test _CheckRepoDir with valid path does not raise."""
        main._CheckRepoDir("/valid/path")


class TestRepoClass:
    """Test _Repo class."""

    @pytest.mark.unit
    def test_repo_init(self):
        """Test _Repo initialization."""
        repo = main._Repo("/test/repo")
        assert repo.repodir == "/test/repo"
        assert repo.commands is not None

    @pytest.mark.unit
    def test_parse_args_no_command(self):
        """Test _ParseArgs with no command."""
        repo = main._Repo("/test/repo")
        name, gopts, argv = repo._ParseArgs([])
        assert name is None
        assert argv == []

    @pytest.mark.unit
    def test_parse_args_with_command(self):
        """Test _ParseArgs with command."""
        repo = main._Repo("/test/repo")
        name, gopts, argv = repo._ParseArgs(["init", "arg1"])
        assert name == "init"
        assert argv == ["arg1"]

    @pytest.mark.unit
    def test_parse_args_with_global_opts(self):
        """Test _ParseArgs with global options."""
        repo = main._Repo("/test/repo")
        name, gopts, argv = repo._ParseArgs(["--trace", "sync"])
        assert name == "sync"
        assert gopts.trace is True

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_no_alias(self, mock_config):
        """Test _ExpandAlias with no alias configured."""
        mock_config.ForRepository.return_value.GetString.return_value = None
        mock_config.ForUser.return_value.GetString.return_value = None
        repo = main._Repo("/test/repo")
        name, args = repo._ExpandAlias("unknown")
        assert name == "unknown"
        assert args == []

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_existing_command(self, mock_config):
        """Test _ExpandAlias with existing command doesn't resolve alias."""
        repo = main._Repo("/test/repo")
        name, args = repo._ExpandAlias("sync")
        assert name == "sync"
        assert args == []

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoConfig")
    def test_expand_alias_with_alias(self, mock_config):
        """Test _ExpandAlias with configured alias."""
        mock_config.ForRepository.return_value.GetString.return_value = "status --verbose"
        repo = main._Repo("/test/repo")
        name, args = repo._ExpandAlias("st")
        assert name == "status"
        assert args == ["--verbose"]

    @pytest.mark.unit
    def test_print_help_short(self, capsys):
        """Test _PrintHelp with short format."""
        repo = main._Repo("/test/repo")
        repo._PrintHelp(short=True)
        captured = capsys.readouterr()
        assert "Available commands:" in captured.out

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main._Repo._PrintHelp")
    def test_run_help_option(self, mock_help):
        """Test _Run with --help option."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.help = True
        gopts.help_all = False
        result = repo._Run("test", gopts, [])
        assert result == 0
        mock_help.assert_called_once()

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main._Repo._PrintHelp")
    def test_run_help_all_option(self, mock_help):
        """Test _Run with --help-all option."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.help = False
        gopts.help_all = True
        result = repo._Run("test", gopts, [])
        assert result == 0
        mock_help.assert_called_once()

    @pytest.mark.unit
    def test_run_show_toplevel(self, tmp_path, capsys):
        """Test _Run with --show-toplevel option."""
        repo = main._Repo(str(tmp_path / ".repo"))
        gopts = mock.MagicMock()
        gopts.help = False
        gopts.help_all = False
        gopts.show_version = False
        gopts.show_toplevel = True
        result = repo._Run("test", gopts, [])
        assert result == 0
        captured = capsys.readouterr()
        assert str(tmp_path) in captured.out

    @pytest.mark.unit
    def test_run_no_command(self):
        """Test _Run with no command shows help."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.help = False
        gopts.help_all = False
        gopts.show_version = False
        gopts.show_toplevel = False
        result = repo._Run(None, gopts, [])
        assert result == 1


class TestRunLongErrors:
    """Test _RunLong error handling."""

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    def test_run_long_unknown_command(self, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with unknown command."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        git_event_log = mock.MagicMock()
        result = repo._RunLong("nonexistent", gopts, [], git_event_log)
        assert result == 1

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_run_long_no_manifest_exception(self, mock_editor, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with NoManifestException during option parsing."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        mock_cmd = mock.MagicMock()
        mock_cmd.OptionParser.parse_args.side_effect = NoManifestException(
            path="/test/path", reason="No manifest found"
        )
        repo.commands = {"test": lambda **kwargs: mock_cmd}

        git_event_log = mock.MagicMock()
        result = repo._RunLong("test", gopts, [], git_event_log)
        assert result == 1

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_run_long_download_error(self, mock_editor, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with DownloadError during execution."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        mock_cmd = mock.MagicMock()
        mock_cmd.Execute.side_effect = DownloadError(reason="Download failed")
        mock_cmd.MULTI_MANIFEST_SUPPORT = False
        repo.commands = {"test": lambda **kwargs: mock_cmd}

        git_event_log = mock.MagicMock()
        result = repo._RunLong("test", gopts, [], git_event_log)
        assert result != 0

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_run_long_no_such_project_error(self, mock_editor, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with NoSuchProjectError during execution."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        mock_cmd = mock.MagicMock()
        mock_cmd.Execute.side_effect = NoSuchProjectError(name="test-proj")
        mock_cmd.MULTI_MANIFEST_SUPPORT = False
        repo.commands = {"test": lambda **kwargs: mock_cmd}

        git_event_log = mock.MagicMock()
        result = repo._RunLong("test", gopts, [], git_event_log)
        assert result != 0

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_run_long_invalid_project_groups_error(self, mock_editor, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with InvalidProjectGroupsError."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        mock_cmd = mock.MagicMock()
        mock_cmd.Execute.side_effect = InvalidProjectGroupsError(name="test-proj")
        mock_cmd.MULTI_MANIFEST_SUPPORT = False
        repo.commands = {"test": lambda **kwargs: mock_cmd}

        git_event_log = mock.MagicMock()
        result = repo._RunLong("test", gopts, [], git_event_log)
        assert result != 0

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.main.RepoClient")
    @mock.patch("kanon_cli.repo.main.SetDefaultColoring")
    @mock.patch("kanon_cli.repo.main.EventLog")
    @mock.patch("kanon_cli.repo.main.Editor")
    def test_run_long_manifest_parse_error(self, mock_editor, mock_event_log, mock_coloring, mock_client):
        """Test _RunLong with ManifestParseError."""
        repo = main._Repo("/test/repo")
        gopts = mock.MagicMock()
        gopts.color = None
        gopts.submanifest_path = None
        gopts.pager = False
        gopts.time = False
        gopts.event_log = None
        gopts.git_trace2_event_log = None

        mock_cmd = mock.MagicMock()
        mock_cmd.Execute.side_effect = ManifestParseError("parse error")
        mock_cmd.MULTI_MANIFEST_SUPPORT = False
        repo.commands = {"test": lambda **kwargs: mock_cmd}

        git_event_log = mock.MagicMock()
        result = repo._RunLong("test", gopts, [], git_event_log)
        assert result != 0


class TestPruneOptions:
    """Test _PruneOptions function."""

    @pytest.mark.unit
    def test_prune_options_basic(self):
        """Test _PruneOptions with basic options."""
        argv = ["--version", "1.0"]
        opt = mock.MagicMock()
        opt.has_option.return_value = True
        main._PruneOptions(argv, opt)
        assert argv == ["--version", "1.0"]

    @pytest.mark.unit
    def test_prune_options_no_match(self):
        """Test _PruneOptions with no matching option."""
        argv = ["--other", "value"]
        opt = mock.MagicMock()
        opt.has_option.return_value = False
        main._PruneOptions(argv, opt)
        assert argv == []

    @pytest.mark.unit
    def test_prune_options_double_dash(self):
        """Test _PruneOptions stops at double dash."""
        argv = ["--version", "1.0", "--", "--version", "2.0"]
        opt = mock.MagicMock()
        opt.has_option.return_value = True
        main._PruneOptions(argv, opt)
        assert argv == ["--version", "1.0", "--", "--version", "2.0"]
