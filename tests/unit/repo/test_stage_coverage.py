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

"""Unit tests for subcmds/stage.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.stage import Stage, _AddI, _ProjectList


def _make_cmd():
    """Create a Stage command instance for testing."""
    cmd = Stage.__new__(Stage)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.manifestProject = mock.MagicMock()
    cmd.manifest.manifestProject.config = mock.MagicMock()
    return cmd


class TestProjectList:
    """Test _ProjectList class."""

    @pytest.mark.unit
    def test_project_list_init(self):
        """Test _ProjectList initialization."""
        gc = mock.MagicMock()
        pl = _ProjectList(gc)
        assert pl is not None
        assert hasattr(pl, "prompt")
        assert hasattr(pl, "header")
        assert hasattr(pl, "help")


class TestStageCommand:
    """Test Stage command."""

    @pytest.mark.unit
    def test_execute_without_interactive(self):
        """Test Execute without interactive flag."""
        cmd = _make_cmd()
        cmd.Usage = mock.MagicMock()
        opt = mock.MagicMock()
        opt.interactive = False

        cmd.Execute(opt, [])
        cmd.Usage.assert_called_once()

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    def test_execute_interactive_no_dirty_projects(self, mock_get_projects):
        """Test Execute with interactive flag but no dirty projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = True
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = False
        mock_get_projects.return_value = [mock_project]

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_quit_command(self, mock_readline, mock_get_projects):
        """Test _Interactive with quit command."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.return_value = "q\n"

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_quit_uppercase(self, mock_readline, mock_get_projects):
        """Test _Interactive with QUIT command."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.return_value = "QUIT\n"

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_exit_command(self, mock_readline, mock_get_projects):
        """Test _Interactive with exit command."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.return_value = "exit\n"

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_eof(self, mock_readline, mock_get_projects):
        """Test _Interactive with EOF."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.return_value = ""

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    @mock.patch("kanon_cli.repo.subcmds.stage._AddI")
    def test_interactive_select_by_index(self, mock_addi, mock_readline, mock_get_projects):
        """Test _Interactive with project selection by index."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = ["1\n", "q\n"]

        cmd._Interactive(opt, [])
        mock_addi.assert_called_once()

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_select_zero_index(self, mock_readline, mock_get_projects):
        """Test _Interactive with zero index (quit)."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.return_value = "0\n"

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    @mock.patch("kanon_cli.repo.subcmds.stage._AddI")
    def test_interactive_select_by_name(self, mock_addi, mock_readline, mock_get_projects):
        """Test _Interactive with project selection by name."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.name = "test-project"
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = ["test-project\n", "q\n"]

        cmd._Interactive(opt, [])
        mock_addi.assert_called_once()

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    @mock.patch("kanon_cli.repo.subcmds.stage._AddI")
    def test_interactive_select_by_path(self, mock_addi, mock_readline, mock_get_projects):
        """Test _Interactive with project selection by path."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.name = "test-project"
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = ["test/project\n", "q\n"]

        cmd._Interactive(opt, [])
        mock_addi.assert_called_once()

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_invalid_index(self, mock_readline, mock_get_projects):
        """Test _Interactive with invalid index."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = ["999\n", "q\n"]

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_empty_input(self, mock_readline, mock_get_projects):
        """Test _Interactive with empty input."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = ["\n", "q\n"]

        cmd._Interactive(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Stage, "GetProjects")
    @mock.patch("sys.stdin.readline")
    def test_interactive_keyboard_interrupt(self, mock_readline, mock_get_projects):
        """Test _Interactive with keyboard interrupt."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.IsDirty.return_value = True
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_readline.side_effect = KeyboardInterrupt()

        cmd._Interactive(opt, [])


class TestAddI:
    """Test _AddI function."""

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.subcmds.stage.GitCommand")
    def test_addi_success(self, mock_git_command):
        """Test _AddI with successful git command."""
        mock_project = mock.MagicMock()
        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_cmd

        _AddI(mock_project)
        mock_git_command.assert_called_once_with(mock_project, ["add", "--interactive"], bare=False)

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.subcmds.stage.GitCommand")
    def test_addi_failure(self, mock_git_command):
        """Test _AddI with failed git command."""
        mock_project = mock.MagicMock()
        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 1
        mock_git_command.return_value = mock_cmd

        _AddI(mock_project)
        mock_git_command.assert_called_once()
