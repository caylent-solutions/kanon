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
    cmd.manifest.topdir = "/test/topdir"
    cmd.client = mock.MagicMock()
    cmd.client.globalConfig = mock.MagicMock()
    return cmd


class TestStatusCommand:
    """Test Status command."""

    @pytest.mark.unit
    def test_status_helper_clean_project(self):
        """Test _StatusHelper with clean project."""
        mock_project = mock.MagicMock()
        mock_project.PrintWorkTreeStatus.return_value = "CLEAN"

        with mock.patch.object(
            Status,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Status._StatusHelper(quiet=False, local=False, project_idx=0)
            assert result[0] == "CLEAN"
            assert isinstance(result[1], str)

    @pytest.mark.unit
    def test_status_helper_dirty_project(self):
        """Test _StatusHelper with dirty project."""
        mock_project = mock.MagicMock()
        mock_project.PrintWorkTreeStatus.return_value = "DIRTY"

        with mock.patch.object(
            Status,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Status._StatusHelper(quiet=False, local=False, project_idx=0)
            assert result[0] == "DIRTY"

    @pytest.mark.unit
    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    def test_execute_all_clean(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with all clean projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = 1  # All clean

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    def test_execute_some_dirty(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with some dirty projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project1 = mock.MagicMock()
        mock_project2 = mock.MagicMock()
        mock_get_projects.return_value = [mock_project1, mock_project2]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = 0  # Some dirty

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch("glob.glob")
    @mock.patch("kanon_cli.repo.platform_utils.isdir")
    def test_find_orphans_file(self, mock_isdir, mock_glob):
        """Test _FindOrphans with file."""
        cmd = _make_cmd()
        mock_isdir.return_value = False
        outstring = []

        cmd._FindOrphans(["file.txt"], set(), set(), outstring)
        assert len(outstring) == 1
        assert "file.txt" in outstring[0]

    @pytest.mark.unit
    @mock.patch("glob.glob")
    @mock.patch("kanon_cli.repo.platform_utils.isdir")
    def test_find_orphans_project_dir(self, mock_isdir, mock_glob):
        """Test _FindOrphans with project directory."""
        cmd = _make_cmd()
        mock_isdir.return_value = True
        outstring = []

        cmd._FindOrphans(["proj_dir"], {"proj_dir"}, set(), outstring)
        assert len(outstring) == 0

    @pytest.mark.unit
    @mock.patch("glob.glob")
    @mock.patch("kanon_cli.repo.platform_utils.isdir")
    def test_find_orphans_parent_dir(self, mock_isdir, mock_glob):
        """Test _FindOrphans with parent directory."""
        cmd = _make_cmd()
        mock_isdir.return_value = True
        mock_glob.return_value = []
        outstring = []

        cmd._FindOrphans(["parent"], set(), {"parent"}, outstring)

    @pytest.mark.unit
    @mock.patch("glob.glob")
    @mock.patch("kanon_cli.repo.platform_utils.isdir")
    def test_find_orphans_orphan_dir(self, mock_isdir, mock_glob):
        """Test _FindOrphans with orphan directory."""
        cmd = _make_cmd()
        mock_isdir.return_value = True
        outstring = []

        cmd._FindOrphans(["orphan_dir"], set(), set(), outstring)
        assert len(outstring) == 1
        assert "orphan_dir/" in outstring[0]

    @pytest.mark.unit
    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch("os.chdir")
    @mock.patch("os.getcwd")
    @mock.patch("glob.glob")
    def test_execute_with_orphans_none(
        self,
        mock_glob,
        mock_getcwd,
        mock_chdir,
        mock_get_context,
        mock_par_context,
        mock_exec,
        mock_get_projects,
    ):
        """Test Execute with orphans option but no orphans."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = True
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "project"
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = 0
        mock_getcwd.return_value = "/test/cwd"
        mock_glob.return_value = []

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch("os.chdir")
    @mock.patch("os.getcwd")
    @mock.patch("glob.glob")
    @mock.patch("kanon_cli.repo.platform_utils.isdir")
    def test_execute_with_orphans_found(
        self,
        mock_isdir,
        mock_glob,
        mock_getcwd,
        mock_chdir,
        mock_get_context,
        mock_par_context,
        mock_exec,
        mock_get_projects,
    ):
        """Test Execute with orphans option and orphans found."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = True
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "project"
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = 0
        mock_getcwd.return_value = "/test/cwd"
        mock_glob.return_value = ["orphan.txt"]
        mock_isdir.return_value = False

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    def test_execute_quiet_mode(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with quiet mode."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = True
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = 0

        cmd.Execute(opt, [])
