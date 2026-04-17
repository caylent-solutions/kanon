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

"""Unit tests for subcmds/rebase.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.rebase import Rebase, RebaseColoring


def _make_cmd():
    """Create a Rebase command instance for testing."""
    cmd = Rebase.__new__(Rebase)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.manifestProject = mock.MagicMock()
    cmd.manifest.manifestProject.config = mock.MagicMock()
    cmd.manifest.projects = []
    cmd.outer_client = mock.MagicMock()
    cmd.outer_manifest = mock.MagicMock()
    cmd.git_event_log = mock.MagicMock()
    return cmd


class TestRebaseColoring:
    """Test RebaseColoring class."""

    @pytest.mark.unit
    def test_rebase_coloring_init(self):
        """Test RebaseColoring initialization."""
        config = mock.MagicMock()
        coloring = RebaseColoring(config)
        assert coloring is not None
        assert hasattr(coloring, "project")
        assert hasattr(coloring, "fail")


class TestRebaseCommand:
    """Test Rebase command."""

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    def test_execute_interactive_multiple_projects(self, mock_get_projects):
        """Test Execute with interactive flag and multiple projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = True
        opt.this_manifest_only = False

        mock_project1 = mock.MagicMock()
        mock_project2 = mock.MagicMock()
        mock_get_projects.return_value = [mock_project1, mock_project2]

        result = cmd.Execute(opt, ["arg"])
        assert result == 1

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_single_project_success(self, mock_git_command, mock_get_projects):
        """Test Execute with single project success."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    def test_execute_detached_head_single_project(self, mock_get_projects):
        """Test Execute with detached HEAD on single project."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = None
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        result = cmd.Execute(opt, [])
        assert result == 1

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    def test_execute_no_remote_branch_single_project(self, mock_get_projects):
        """Test Execute with no remote branch on single project."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = None
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        result = cmd.Execute(opt, [])
        assert result == 1

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_whitespace_option(self, mock_git_command, mock_get_projects):
        """Test Execute with whitespace option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = "fix"
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_force_rebase(self, mock_git_command, mock_get_projects):
        """Test Execute with force-rebase option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = True
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_no_ff(self, mock_git_command, mock_get_projects):
        """Test Execute with no-ff option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = False
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_autosquash(self, mock_git_command, mock_get_projects):
        """Test Execute with autosquash option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = True
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_onto_manifest(self, mock_git_command, mock_get_projects):
        """Test Execute with onto-manifest option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = True
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_project.revisionExpr = "refs/heads/main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_auto_stash_clean(self, mock_git_command, mock_get_projects):
        """Test Execute with auto-stash on clean working directory."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = True
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_with_auto_stash_dirty(self, mock_git_command, mock_get_projects):
        """Test Execute with auto-stash on dirty working directory."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = True
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        # First call (update-index) returns 1 (dirty)
        # Second call (stash) returns 0
        # Third call (rebase) returns 0
        # Fourth call (stash pop) returns 0
        mock_git_cmd.Wait.side_effect = [1, 0, 0, 0]
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 0

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_rebase_failure(self, mock_git_command, mock_get_projects):
        """Test Execute with rebase failure."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.CurrentBranch = "main"
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_project.GetBranch.return_value = mock_branch
        mock_project.RelPath.return_value = "test/project"

        mock_get_projects.return_value = [mock_project]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 1
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 1

    @pytest.mark.unit
    @mock.patch.object(Rebase, "GetProjects")
    @mock.patch("kanon_cli.repo.subcmds.rebase.GitCommand")
    def test_execute_fail_fast(self, mock_git_command, mock_get_projects):
        """Test Execute with fail-fast on multiple projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.interactive = False
        opt.whitespace = None
        opt.quiet = False
        opt.force_rebase = False
        opt.ff = True
        opt.autosquash = False
        opt.onto_manifest = False
        opt.auto_stash = False
        opt.fail_fast = True
        opt.this_manifest_only = False

        mock_project1 = mock.MagicMock()
        mock_project1.CurrentBranch = "main"
        mock_branch1 = mock.MagicMock()
        mock_branch1.LocalMerge = "refs/remotes/origin/main"
        mock_project1.GetBranch.return_value = mock_branch1
        mock_project1.RelPath.return_value = "test/project1"

        mock_project2 = mock.MagicMock()
        mock_project2.CurrentBranch = "main"
        mock_branch2 = mock.MagicMock()
        mock_branch2.LocalMerge = "refs/remotes/origin/main"
        mock_project2.GetBranch.return_value = mock_branch2
        mock_project2.RelPath.return_value = "test/project2"

        mock_get_projects.return_value = [mock_project1, mock_project2]

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 1
        mock_git_command.return_value = mock_git_cmd

        result = cmd.Execute(opt, [])
        assert result == 1
        # Should stop after first failure with fail_fast
