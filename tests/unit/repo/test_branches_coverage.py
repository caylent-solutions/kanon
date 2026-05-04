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

"""Unit tests for subcmds/branches.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.branches import Branches, BranchColoring, BranchInfo


def _make_cmd():
    """Create a Branches command instance for testing."""
    cmd = Branches.__new__(Branches)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.manifestProject = mock.MagicMock()
    cmd.manifest.manifestProject.config = mock.MagicMock()
    return cmd


class TestBranchColoring:
    """Test BranchColoring class."""

    @pytest.mark.unit
    def test_branch_coloring_init(self):
        """Test BranchColoring initialization."""
        config = mock.MagicMock()
        coloring = BranchColoring(config)
        assert coloring is not None
        assert hasattr(coloring, "current")
        assert hasattr(coloring, "local")
        assert hasattr(coloring, "notinproject")


class TestBranchInfo:
    """Test BranchInfo class."""

    @pytest.mark.unit
    def test_branch_info_init(self):
        """Test BranchInfo initialization."""
        info = BranchInfo("feature-branch")
        assert info.name == "feature-branch"
        assert info.current == 0
        assert info.published == 0
        assert info.published_equal == 0
        assert info.projects == []

    @pytest.mark.unit
    def test_branch_info_add_current(self):
        """Test BranchInfo.add with current branch."""
        info = BranchInfo("feature-branch")
        branch = mock.MagicMock()
        branch.current = True
        branch.published = False
        branch.revision = "abc123"

        info.add(branch)
        assert info.current == 1
        assert info.published == 0
        assert len(info.projects) == 1

    @pytest.mark.unit
    def test_branch_info_add_published(self):
        """Test BranchInfo.add with published branch."""
        info = BranchInfo("feature-branch")
        branch = mock.MagicMock()
        branch.current = False
        branch.published = "def456"
        branch.revision = "abc123"

        info.add(branch)
        assert info.current == 0
        assert info.published == 1
        assert len(info.projects) == 1

    @pytest.mark.unit
    def test_branch_info_add_published_equal(self):
        """Test BranchInfo.add with published equal to revision."""
        info = BranchInfo("feature-branch")
        branch = mock.MagicMock()
        branch.current = False
        branch.published = "abc123"
        branch.revision = "abc123"

        info.add(branch)
        assert info.published_equal == 1

    @pytest.mark.unit
    def test_branch_info_is_current(self):
        """Test BranchInfo.IsCurrent property."""
        info = BranchInfo("feature-branch")
        assert info.IsCurrent is False

        branch = mock.MagicMock()
        branch.current = True
        branch.published = False
        branch.revision = "abc123"
        info.add(branch)

        assert info.IsCurrent is True

    @pytest.mark.unit
    def test_branch_info_is_split_current(self):
        """Test BranchInfo.IsSplitCurrent property."""
        info = BranchInfo("feature-branch")

        # Add two branches, one current, one not
        branch1 = mock.MagicMock()
        branch1.current = True
        branch1.published = False
        branch1.revision = "abc123"

        branch2 = mock.MagicMock()
        branch2.current = False
        branch2.published = False
        branch2.revision = "def456"

        info.add(branch1)
        info.add(branch2)

        assert info.IsSplitCurrent is True

    @pytest.mark.unit
    def test_branch_info_is_published(self):
        """Test BranchInfo.IsPublished property."""
        info = BranchInfo("feature-branch")
        assert info.IsPublished is False

        branch = mock.MagicMock()
        branch.current = False
        branch.published = "abc123"
        branch.revision = "abc123"
        info.add(branch)

        assert info.IsPublished is True

    @pytest.mark.unit
    def test_branch_info_is_published_equal(self):
        """Test BranchInfo.IsPublishedEqual property."""
        info = BranchInfo("feature-branch")

        # Add two branches, both published equal
        branch1 = mock.MagicMock()
        branch1.current = False
        branch1.published = "abc123"
        branch1.revision = "abc123"

        branch2 = mock.MagicMock()
        branch2.current = False
        branch2.published = "def456"
        branch2.revision = "def456"

        info.add(branch1)
        info.add(branch2)

        assert info.IsPublishedEqual is True


class TestBranchesCommand:
    """Test Branches command."""

    @pytest.mark.unit
    def test_expand_project_to_branches(self):
        """Test _ExpandProjectToBranches."""
        mock_project = mock.MagicMock()
        mock_branch1 = mock.MagicMock()
        mock_branch2 = mock.MagicMock()
        mock_project.GetBranches.return_value = {
            "main": mock_branch1,
            "feature": mock_branch2,
        }

        with mock.patch.object(
            Branches,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Branches._ExpandProjectToBranches(0)
            assert len(result) == 2
            assert result[0][0] == "main"
            assert result[0][1] == mock_branch1
            assert result[0][2] == 0
            assert result[1][0] == "feature"
            assert result[1][1] == mock_branch2
            assert result[1][2] == 0

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_no_branches(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with no branches."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = None

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_with_branches(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with branches."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_branch = mock.MagicMock()
        mock_branch.current = True
        mock_branch.published = "abc123"
        mock_branch.revision = "abc123"

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        # Simulate callback that adds branches
        def mock_callback(pool, output, results):
            # Simulate processing results
            pass

        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [[("main", mock_branch, 0)]],
        )

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_branch_in_subset_projects(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with branch in subset of projects."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project1 = mock.MagicMock()
        mock_project1.RelPath.return_value = "test/project1"
        mock_project2 = mock.MagicMock()
        mock_project2.RelPath.return_value = "test/project2"
        mock_get_projects.return_value = [mock_project1, mock_project2]

        mock_branch = mock.MagicMock()
        mock_branch.current = False
        mock_branch.published = None
        mock_branch.revision = "abc123"
        mock_branch.project = mock_project1

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [[("feature", mock_branch, 0)]],
        )

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_split_current_branch(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with split current branch."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project1 = mock.MagicMock()
        mock_project1.RelPath.return_value = "test/project1"
        mock_project2 = mock.MagicMock()
        mock_project2.RelPath.return_value = "test/project2"
        mock_get_projects.return_value = [mock_project1, mock_project2]

        mock_branch1 = mock.MagicMock()
        mock_branch1.current = True
        mock_branch1.published = None
        mock_branch1.revision = "abc123"
        mock_branch1.project = mock_project1

        mock_branch2 = mock.MagicMock()
        mock_branch2.current = False
        mock_branch2.published = None
        mock_branch2.revision = "abc123"
        mock_branch2.project = mock_project2

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [[("feature", mock_branch1, 0), ("feature", mock_branch2, 1)]],
        )

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_long_branch_name(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with long branch name."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_branch = mock.MagicMock()
        mock_branch.current = True
        mock_branch.published = None
        mock_branch.revision = "abc123"
        mock_branch.project = mock_project

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        long_name = "a" * 50
        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [[(long_name, mock_branch, 0)]],
        )

        cmd.Execute(opt, [])

    @pytest.mark.unit
    @mock.patch.object(Branches, "GetProjects")
    @mock.patch.object(Branches, "ExecuteInParallel")
    @mock.patch.object(Branches, "ParallelContext")
    @mock.patch.object(Branches, "get_parallel_context")
    def test_execute_branch_with_percent_sign(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with branch name containing percent sign."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_branch = mock.MagicMock()
        mock_branch.current = True
        mock_branch.published = None
        mock_branch.revision = "abc123"
        mock_branch.project = mock_project

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [[("feature%branch", mock_branch, 0)]],
        )

        cmd.Execute(opt, [])
