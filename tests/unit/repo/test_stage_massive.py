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
    cmd.GetProjects = mock.MagicMock()
    cmd.Usage = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_project_list_init():
    """Test _ProjectList initialization."""
    gc = mock.MagicMock()
    pl = _ProjectList(gc)
    assert pl is not None
    assert hasattr(pl, "prompt")
    assert hasattr(pl, "header")
    assert hasattr(pl, "help")


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    option_group = mock.MagicMock()
    parser.get_option_group.return_value = option_group

    cmd._Options(parser)

    option_group.add_option.assert_called_once()


@pytest.mark.unit
def test_execute_without_interactive():
    """Test Execute without interactive flag calls Usage."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = False

    cmd.Execute(opt, [])

    cmd.Usage.assert_called_once()


@pytest.mark.unit
def test_execute_with_interactive():
    """Test Execute with interactive flag."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["q\n"]):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])

    cmd.GetProjects.assert_called_once()


@pytest.mark.unit
def test_interactive_no_dirty_projects():
    """Test _Interactive with no dirty projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True

    clean_project = mock.MagicMock()
    clean_project.IsDirty.return_value = False

    cmd.GetProjects.return_value = [clean_project]

    with mock.patch("kanon_cli.repo.repo_logging.RepoLogger"):
        cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_quit_lowercase():
    """Test _Interactive with 'q' input."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = False

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", return_value="q\n"):
        with mock.patch("builtins.print") as mock_print:
            cmd.Execute(opt, [])
            # Should print "Bye."
            assert any("Bye" in str(call) for call in mock_print.call_args_list)


@pytest.mark.unit
def test_interactive_quit_word():
    """Test _Interactive with 'quit' input."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", return_value="quit\n"):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_exit_word():
    """Test _Interactive with 'exit' input."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", return_value="exit\n"):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_eof():
    """Test _Interactive with EOF (empty string)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", return_value=""):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_keyboard_interrupt():
    """Test _Interactive with KeyboardInterrupt."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=KeyboardInterrupt):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_empty_input():
    """Test _Interactive with empty input (just whitespace)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["  \n", "q\n"]):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_select_by_index():
    """Test _Interactive selecting project by index."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["1\n", "q\n"]):
        with mock.patch("builtins.print"):
            with mock.patch("kanon_cli.repo.subcmds.stage._AddI") as mock_add:
                cmd.Execute(opt, [])
                mock_add.assert_called_once_with(dirty_project)


@pytest.mark.unit
def test_interactive_select_zero_exits():
    """Test _Interactive selecting 0 exits."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", return_value="0\n"):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_select_by_name():
    """Test _Interactive selecting project by name."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"
    dirty_project.name = "myproject"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["myproject\n", "q\n"]):
        with mock.patch("builtins.print"):
            with mock.patch("kanon_cli.repo.subcmds.stage._AddI") as mock_add:
                cmd.Execute(opt, [])
                mock_add.assert_called_once_with(dirty_project)


@pytest.mark.unit
def test_interactive_invalid_index():
    """Test _Interactive with invalid index."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["999\n", "q\n"]):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_interactive_non_numeric_input():
    """Test _Interactive with non-numeric non-project input."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.interactive = True
    opt.this_manifest_only = True

    dirty_project = mock.MagicMock()
    dirty_project.IsDirty.return_value = True
    dirty_project.RelPath.return_value = "project1"
    dirty_project.name = "myproject"

    cmd.GetProjects.return_value = [dirty_project]

    with mock.patch("sys.stdin.readline", side_effect=["invalid\n", "q\n"]):
        with mock.patch("builtins.print"):
            cmd.Execute(opt, [])


@pytest.mark.unit
def test_addi():
    """Test _AddI function."""
    project = mock.MagicMock()
    project.name = "test_project"

    with mock.patch("kanon_cli.repo.subcmds.stage.GitCommand") as mock_git:
        mock_cmd = mock.MagicMock()
        mock_git.return_value = mock_cmd

        _AddI(project)

        mock_git.assert_called_once_with(project, ["add", "--interactive"], bare=False)
        mock_cmd.Wait.assert_called_once()
