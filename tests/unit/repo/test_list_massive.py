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

"""Unit tests for subcmds/list.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.list import List


def _make_cmd():
    """Create a List command instance for testing."""
    cmd = List.__new__(List)
    cmd.manifest = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    cmd.FindProjects = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    cmd._Options(parser)

    # Should add multiple options
    assert parser.add_option.call_count >= 7


@pytest.mark.unit
def test_validate_options_fullpath_and_name_only():
    """Test ValidateOptions rejects -f and -n together."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.fullpath = True
    opt.name_only = True
    opt.relative_to = None

    # Mock the OptionParser property
    mock_parser = mock.MagicMock()
    with mock.patch.object(type(cmd), "OptionParser", new_callable=mock.PropertyMock) as mock_optparser:
        mock_optparser.return_value = mock_parser
        cmd.ValidateOptions(opt, [])
        mock_parser.error.assert_called_once()


@pytest.mark.unit
def test_validate_options_relative_to_resolved():
    """Test ValidateOptions resolves relative_to path."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.fullpath = False
    opt.name_only = False
    opt.relative_to = "/tmp/test"

    with mock.patch("os.path.realpath", return_value="/resolved/path"):
        cmd.ValidateOptions(opt, [])

    assert opt.relative_to == "/resolved/path"


@pytest.mark.unit
def test_execute_default_output():
    """Test Execute with default output format."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/abs/path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print path : name
        mock_print.assert_called_once()
        output = str(mock_print.call_args[0][0])
        assert "myproject" in output
        assert ":" in output


@pytest.mark.unit
def test_execute_name_only():
    """Test Execute with --name-only."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = True
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/abs/path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        mock_print.assert_called_once_with("myproject")


@pytest.mark.unit
def test_execute_path_only():
    """Test Execute with --path-only."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = True
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/abs/path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        mock_print.assert_called_once_with("path/to/project")


@pytest.mark.unit
def test_execute_fullpath():
    """Test Execute with --fullpath."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = True
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/abs/path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        output = str(mock_print.call_args[0][0])
        assert "/abs/path/to/project" in output


@pytest.mark.unit
def test_execute_relative_to():
    """Test Execute with --relative-to."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = "/base/path"
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/base/path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("os.path.relpath", return_value="to/project"):
        with mock.patch("builtins.print") as mock_print:
            cmd.Execute(opt, [])

            output = str(mock_print.call_args[0][0])
            assert "to/project" in output


@pytest.mark.unit
def test_execute_regex_mode():
    """Test Execute with --regex flag."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = True
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = False
    opt.groups = None
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"
    project.worktree = "/abs/path/to/project"

    cmd.FindProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, ["my.*"])

        cmd.FindProjects.assert_called_once_with(["my.*"], all_manifests=True)


@pytest.mark.unit
def test_execute_sorted_output():
    """Test Execute sorts output."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = True
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    project1 = mock.MagicMock()
    project1.name = "zebra"

    project2 = mock.MagicMock()
    project2.name = "alpha"

    cmd.GetProjects.return_value = [project1, project2]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print sorted
        output = mock_print.call_args[0][0]
        assert "alpha" in output
        assert output.index("alpha") < output.index("zebra")


@pytest.mark.unit
def test_execute_no_projects():
    """Test Execute with no projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = False

    cmd.GetProjects.return_value = []

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        mock_print.assert_not_called()


@pytest.mark.unit
def test_execute_with_groups():
    """Test Execute with --groups option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = "default,test"
    opt.all = False

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])

        cmd.GetProjects.assert_called_once_with([], groups="default,test", missing_ok=False, all_manifests=False)


@pytest.mark.unit
def test_execute_with_all():
    """Test Execute with --all option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = True
    opt.groups = None
    opt.all = True

    project = mock.MagicMock()
    project.name = "myproject"
    project.RelPath.return_value = "path/to/project"

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])

        cmd.GetProjects.assert_called_once_with([], groups=None, missing_ok=True, all_manifests=False)


@pytest.mark.unit
def test_execute_multiple_projects():
    """Test Execute with multiple projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.regex = False
    opt.name_only = False
    opt.path_only = False
    opt.fullpath = False
    opt.relative_to = None
    opt.this_manifest_only = False
    opt.groups = None
    opt.all = False

    project1 = mock.MagicMock()
    project1.name = "project1"
    project1.RelPath.return_value = "path/to/project1"

    project2 = mock.MagicMock()
    project2.name = "project2"
    project2.RelPath.return_value = "path/to/project2"

    cmd.GetProjects.return_value = [project1, project2]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        output = mock_print.call_args[0][0]
        assert "project1" in output
        assert "project2" in output
