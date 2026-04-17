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

"""Unit tests for subcmds/status.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.status import Status


def _make_cmd():
    """Create a Status command instance for testing."""
    cmd = Status.__new__(Status)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.topdir = "/tmp/test"
    cmd.client = mock.MagicMock()
    cmd.client.globalConfig = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    cmd.ExecuteInParallel = mock.MagicMock()
    cmd.ParallelContext = mock.MagicMock()
    cmd.get_parallel_context = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    cmd._Options(parser)
    parser.add_option.assert_called_once()


@pytest.mark.unit
def test_status_helper():
    """Test _StatusHelper class method."""
    project = mock.MagicMock()
    project.PrintWorkTreeStatus = mock.MagicMock(return_value="CLEAN")

    Status.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    ret, output = Status._StatusHelper(quiet=False, local=False, project_idx=0)

    assert ret == "CLEAN"
    project.PrintWorkTreeStatus.assert_called_once()


@pytest.mark.unit
def test_status_helper_with_output():
    """Test _StatusHelper with status output."""
    project = mock.MagicMock()
    project.PrintWorkTreeStatus = mock.MagicMock(return_value="DIRTY")

    Status.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    ret, output = Status._StatusHelper(quiet=True, local=True, project_idx=0)

    assert ret == "DIRTY"
    assert isinstance(output, str)
    project.PrintWorkTreeStatus.assert_called_once_with(quiet=True, output_redir=mock.ANY, local=True)


@pytest.mark.unit
def test_find_orphans_file():
    """Test _FindOrphans with a file."""
    cmd = _make_cmd()
    outstring = []

    with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=False):
        cmd._FindOrphans(["file.txt"], set(), set(), outstring)

    assert len(outstring) == 1
    assert "file.txt" in outstring[0]


@pytest.mark.unit
def test_find_orphans_in_proj_dirs():
    """Test _FindOrphans with directory in proj_dirs."""
    cmd = _make_cmd()
    outstring = []

    with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
        cmd._FindOrphans(["project1"], {"project1"}, set(), outstring)

    assert len(outstring) == 0


@pytest.mark.unit
def test_find_orphans_recursive():
    """Test _FindOrphans with recursive directory search."""
    cmd = _make_cmd()
    outstring = []

    with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
        with mock.patch("glob.glob", return_value=["subdir/file.txt"]):
            cmd._FindOrphans(["orphan"], set(), {"orphan"}, outstring)

    # Should recursively search
    assert len(outstring) >= 1


@pytest.mark.unit
def test_find_orphans_directory_marker():
    """Test _FindOrphans adds trailing slash for directories."""
    cmd = _make_cmd()
    outstring = []

    with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
        with mock.patch("glob.glob", return_value=[]):
            cmd._FindOrphans(["orphan_dir"], set(), set(), outstring)

    assert len(outstring) == 1
    assert outstring[0].endswith("/")


@pytest.mark.unit
def test_execute_no_projects():
    """Test Execute with no projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.quiet = False
    opt.orphans = False
    opt.jobs = 1

    cmd.GetProjects.return_value = []
    cmd.ExecuteInParallel.return_value = 0

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])
        # Should print "nothing to commit"
        mock_print.assert_called()


@pytest.mark.unit
def test_execute_with_clean_projects(capsys):
    """Test Execute with all clean projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = False
    opt.orphans = False
    opt.jobs = 2

    mock_project = mock.MagicMock()
    mock_project.name = "test_project"
    cmd.GetProjects.return_value = [mock_project]
    cmd.ExecuteInParallel.return_value = 1

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    cmd.Execute(opt, [])

    cmd.GetProjects.assert_called_once_with([], all_manifests=True)


@pytest.mark.unit
def test_execute_with_orphans():
    """Test Execute with orphans option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.quiet = False
    opt.orphans = True
    opt.jobs = 1

    mock_project = mock.MagicMock()
    mock_project.RelPath = mock.MagicMock(return_value="project1")
    cmd.GetProjects.return_value = [mock_project]
    cmd.ExecuteInParallel.return_value = 1

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("os.getcwd", return_value="/tmp/test"):
        with mock.patch("os.chdir"):
            with mock.patch("glob.glob", return_value=[".git", "file.txt"]):
                with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=False):
                    with mock.patch("builtins.print"):
                        cmd.Execute(opt, [])


@pytest.mark.unit
def test_execute_orphans_no_orphans_found():
    """Test Execute with orphans option when no orphans exist."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = False
    opt.orphans = True
    opt.jobs = 1

    mock_project = mock.MagicMock()
    mock_project.RelPath = mock.MagicMock(return_value="project1")
    cmd.GetProjects.return_value = [mock_project]
    cmd.ExecuteInParallel.return_value = 0

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("os.getcwd", return_value="/tmp/test"):
        with mock.patch("os.chdir"):
            with mock.patch("glob.glob", return_value=[]):
                with mock.patch("builtins.print") as mock_print:
                    cmd.Execute(opt, [])
                    # Should print "No orphan files"
                    assert any("orphan" in str(call).lower() for call in mock_print.call_args_list)


@pytest.mark.unit
def test_execute_restores_cwd():
    """Test Execute restores current working directory after orphans check."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.quiet = True
    opt.orphans = True
    opt.jobs = 1

    cmd.GetProjects.return_value = []
    cmd.ExecuteInParallel.return_value = 0

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    original_cwd = "/original/path"

    with mock.patch("os.getcwd", return_value=original_cwd):
        with mock.patch("os.chdir") as mock_chdir:
            with mock.patch("glob.glob", return_value=[]):
                with mock.patch("builtins.print"):
                    cmd.Execute(opt, [])

                    # Should chdir to topdir and then back
                    calls = mock_chdir.call_args_list
                    assert len(calls) == 2
                    assert calls[0][0][0] == cmd.manifest.topdir
                    assert calls[1][0][0] == original_cwd
