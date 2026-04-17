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

"""Deep unit tests for subcmds/info.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.info import _Coloring
from kanon_cli.repo.subcmds.info import Info


@pytest.mark.unit
class TestColoringInit:
    """Tests for _Coloring initialization."""

    def test_coloring_init(self):
        """Test _Coloring initialization."""
        config = mock.Mock()
        coloring = _Coloring(config)
        assert coloring is not None


@pytest.mark.unit
class TestInfoPrintSeparator:
    """Tests for Info.printSeparator method."""

    def test_print_separator(self):
        """Test printSeparator prints separator."""
        info = Info()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.text = mock.Mock()

        info.printSeparator()

        info.text.assert_called_once()
        info.out.nl.assert_called_once()


@pytest.mark.unit
class TestInfoPrintDiffInfo:
    """Tests for Info._printDiffInfo method."""

    def test_print_diff_info_basic(self):
        """Test _printDiffInfo with basic project."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.redtext = mock.Mock()
        info.text = mock.Mock()
        info.printSeparator = mock.Mock()
        info.opt = mock.Mock()
        info.opt.all = False

        project = mock.Mock()
        project.name = "test-project"
        project.worktree = "/path/to/project"
        project.GetRevisionId.return_value = "abc123"
        project.CurrentBranch = "main"
        project.revisionExpr = "refs/heads/main"
        project.GetBranches.return_value = {
            "main": mock.Mock(),
            "develop": mock.Mock(),
        }

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printDiffInfo(opt, [])

        info.heading.assert_called()
        info.headtext.assert_called()

    def test_print_diff_info_no_current_branch(self):
        """Test _printDiffInfo with no current branch."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.redtext = mock.Mock()
        info.printSeparator = mock.Mock()
        info.opt = mock.Mock()
        info.opt.all = False

        project = mock.Mock()
        project.name = "test-project"
        project.worktree = "/path/to/project"
        project.GetRevisionId.return_value = "abc123"
        project.CurrentBranch = None
        project.revisionExpr = "refs/heads/main"
        project.GetBranches.return_value = {}

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printDiffInfo(opt, [])

        info.heading.assert_called()

    def test_print_diff_info_with_all(self):
        """Test _printDiffInfo with --all option."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.redtext = mock.Mock()
        info.text = mock.Mock()
        info.printSeparator = mock.Mock()
        info.findRemoteLocalDiff = mock.Mock()
        info.opt = mock.Mock()
        info.opt.all = True

        project = mock.Mock()
        project.name = "test-project"
        project.worktree = "/path/to/project"
        project.GetRevisionId.return_value = "abc123"
        project.CurrentBranch = "main"
        project.revisionExpr = "refs/heads/main"
        project.GetBranches.return_value = {"main": mock.Mock()}

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printDiffInfo(opt, [])

        info.findRemoteLocalDiff.assert_called_once_with(project)


@pytest.mark.unit
class TestInfoFindRemoteLocalDiff:
    """Tests for Info.findRemoteLocalDiff method."""

    def test_find_remote_local_diff_with_sync(self):
        """Test findRemoteLocalDiff with network sync."""
        info = Info()
        info.opt = mock.Mock()
        info.opt.local = False
        info.manifest = mock.Mock()
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.redtext = mock.Mock()
        info.dimtext = mock.Mock()
        info.sha = mock.Mock()
        info.text = mock.Mock()
        info.printSeparator = mock.Mock()

        project = mock.Mock()
        project.Sync_NetworkHalf = mock.Mock()
        project.bare_git._bare = True
        project.bare_git.rev_list = mock.Mock(side_effect=[["commit1", "commit2"], ["commit3"]])

        info.findRemoteLocalDiff(project)

        project.Sync_NetworkHalf.assert_called_once()
        assert project.bare_git.rev_list.call_count == 2

    def test_find_remote_local_diff_local_only(self):
        """Test findRemoteLocalDiff with --local option."""
        info = Info()
        info.opt = mock.Mock()
        info.opt.local = True
        info.manifest = mock.Mock()
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.redtext = mock.Mock()
        info.dimtext = mock.Mock()
        info.sha = mock.Mock()
        info.text = mock.Mock()
        info.printSeparator = mock.Mock()

        project = mock.Mock()
        project.Sync_NetworkHalf = mock.Mock()
        project.bare_git._bare = True
        project.bare_git.rev_list = mock.Mock(side_effect=[[], []])

        info.findRemoteLocalDiff(project)

        project.Sync_NetworkHalf.assert_not_called()

    def test_find_remote_local_diff_with_commits(self):
        """Test findRemoteLocalDiff displays commits."""
        info = Info()
        info.opt = mock.Mock()
        info.opt.local = True
        info.manifest = mock.Mock()
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.redtext = mock.Mock()
        info.dimtext = mock.Mock()
        info.sha = mock.Mock()
        info.text = mock.Mock()
        info.printSeparator = mock.Mock()

        project = mock.Mock()
        project.bare_git._bare = False
        project.bare_git.rev_list = mock.Mock(
            side_effect=[
                ["abc1234 local commit 1", "def5678 local commit 2"],
                ["ghi9012 remote commit 1"],
            ]
        )

        info.findRemoteLocalDiff(project)

        # Should print local and remote commits
        assert info.sha.call_count >= 3


@pytest.mark.unit
class TestInfoPrintCommitOverview:
    """Tests for Info._printCommitOverview method."""

    def test_print_commit_overview_basic(self):
        """Test _printCommitOverview with basic branches."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.text = mock.Mock()
        info.sha = mock.Mock()
        info.opt = mock.Mock()
        info.opt.current_branch = False

        project = mock.Mock()
        project.GetBranches.return_value = ["main", "develop"]
        project.RelPath.return_value = "project/path"
        project.CurrentBranch = "main"

        branch1 = mock.Mock()
        branch1.name = "main"
        branch1.project = project
        branch1.commits = ["abc1234 commit 1", "def5678 commit 2"]
        branch1.date = "2024-01-01"

        branch2 = mock.Mock()
        branch2.name = "develop"
        branch2.project = project
        branch2.commits = ["ghi9012 commit 3"]
        branch2.date = "2024-01-02"

        project.GetUploadableBranch.side_effect = [branch1, branch2]

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printCommitOverview(opt, [])

        info.heading.assert_called()
        info.headtext.assert_called()

    def test_print_commit_overview_current_branch_only(self):
        """Test _printCommitOverview with current_branch option."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.out.nl = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.text = mock.Mock()
        info.sha = mock.Mock()
        info.opt = mock.Mock()
        info.opt.current_branch = True

        project = mock.Mock()
        project.GetBranches.return_value = ["main", "develop"]
        project.RelPath.return_value = "project/path"
        project.CurrentBranch = "main"

        branch1 = mock.Mock()
        branch1.name = "main"
        branch1.project = project
        branch1.commits = ["abc1234 commit 1"]
        branch1.date = "2024-01-01"

        branch2 = mock.Mock()
        branch2.name = "develop"
        branch2.project = project
        branch2.commits = []
        branch2.date = "2024-01-02"

        project.GetUploadableBranch.side_effect = [branch1, branch2]

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printCommitOverview(opt, [])

        # Should only show main branch
        assert info.text.call_count >= 1

    def test_print_commit_overview_no_branches(self):
        """Test _printCommitOverview with no branches."""
        info = Info()
        info.GetProjects = mock.Mock()
        info.out = mock.Mock()
        info.heading = mock.Mock()
        info.opt = mock.Mock()
        info.opt.current_branch = False

        project = mock.Mock()
        project.GetBranches.return_value = []

        info.GetProjects.return_value = [project]

        opt = mock.Mock()
        opt.this_manifest_only = False

        info._printCommitOverview(opt, [])

        # Should not call heading since no branches
        info.heading.assert_not_called()


@pytest.mark.unit
class TestInfoExecute:
    """Tests for Info.Execute method."""

    def test_execute_basic_info(self):
        """Test Execute displays basic info."""
        info = Info()
        info.client = mock.Mock()
        info.client.globalConfig = mock.Mock()
        info.manifest = mock.Mock()
        info.manifest.outer_client = info.manifest
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.manifest.default.revisionExpr = "main"
        info.manifest.GetGroupsStr.return_value = "default"
        info.manifest.superproject = None
        info._printDiffInfo = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = True
        opt.overview = False

        info.Execute(opt, [])

        info._printDiffInfo.assert_called_once()

    def test_execute_with_superproject(self):
        """Test Execute displays superproject info."""
        info = Info()
        info.client = mock.Mock()
        info.client.globalConfig = mock.Mock()
        info.manifest = mock.Mock()
        info.manifest.outer_client = info.manifest
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.manifest.default.revisionExpr = "main"
        info.manifest.GetGroupsStr.return_value = "default"

        superproject = mock.Mock()
        superproject.commit_id = "sp123456"
        info.manifest.superproject = superproject

        info._printDiffInfo = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = True
        opt.overview = False

        info.Execute(opt, [])

        # Just verify Execute completes without error
        info._printDiffInfo.assert_called_once()

    def test_execute_overview_mode(self):
        """Test Execute in overview mode."""
        info = Info()
        info.client = mock.Mock()
        info.client.globalConfig = mock.Mock()
        info.manifest = mock.Mock()
        info.manifest.outer_client = info.manifest
        info.manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        info.manifest.default.revisionExpr = "main"
        info.manifest.GetGroupsStr.return_value = "default"
        info.manifest.superproject = None
        info.out = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.printSeparator = mock.Mock()
        info._printCommitOverview = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = True
        opt.overview = True

        info.Execute(opt, [])

        info._printCommitOverview.assert_called_once()

    def test_execute_outer_manifest(self):
        """Test Execute with outer manifest."""
        outer_manifest = mock.Mock()
        outer_manifest.manifestProject.config.GetBranch.return_value.merge = "refs/heads/main"
        outer_manifest.default.revisionExpr = "main"
        outer_manifest.GetGroupsStr.return_value = "default"
        outer_manifest.superproject = None

        info = Info()
        info.client = mock.Mock()
        info.client.globalConfig = mock.Mock()
        info.manifest = mock.Mock()
        info.manifest.outer_client = outer_manifest
        info.out = mock.Mock()
        info.heading = mock.Mock()
        info.headtext = mock.Mock()
        info.printSeparator = mock.Mock()
        info._printDiffInfo = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = False
        opt.overview = False

        info.Execute(opt, [])

        # Should use outer_client
        assert info.manifest == outer_manifest

    def test_execute_no_merge_branch(self):
        """Test Execute handles missing merge branch."""
        info = Info()
        info.client = mock.Mock()
        info.client.globalConfig = mock.Mock()
        info.manifest = mock.Mock()
        info.manifest.outer_client = info.manifest
        info.manifest.manifestProject.config.GetBranch.return_value.merge = None
        info.manifest.default.revisionExpr = "main"
        info.manifest.GetGroupsStr.return_value = "default"
        info.manifest.superproject = None
        info._printDiffInfo = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = True
        opt.overview = False

        info.Execute(opt, [])

        # Should handle None merge branch
        info._printDiffInfo.assert_called_once()
