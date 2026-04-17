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

"""Unit tests for subcmds/prune.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.prune import Prune


def _make_cmd():
    """Create a Prune command instance for testing."""
    cmd = Prune.__new__(Prune)
    cmd.manifest = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    cmd.ExecuteInParallel = mock.MagicMock()
    cmd.ParallelContext = mock.MagicMock()
    cmd.get_parallel_context = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_execute_one():
    """Test _ExecuteOne class method."""
    project = mock.MagicMock()
    branch1 = mock.MagicMock()
    branch1.name = "feature1"
    branch2 = mock.MagicMock()
    branch2.name = "feature2"
    project.PruneHeads.return_value = [branch1, branch2]

    Prune.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result = Prune._ExecuteOne(0)

    assert result == [branch1, branch2]
    project.PruneHeads.assert_called_once()


@pytest.mark.unit
def test_execute_no_branches():
    """Test Execute with no branches to prune."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    project = mock.MagicMock()
    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = []

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    cmd.Execute(opt, [])

    cmd.GetProjects.assert_called_once()


@pytest.mark.unit
def test_execute_with_branches():
    """Test Execute with branches to prune."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.jobs = 2

    branch = mock.MagicMock()
    branch.name = "old-feature"
    branch.base_exists = True
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])


@pytest.mark.unit
def test_execute_branch_without_base():
    """Test Execute with branch where base doesn't exist."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    branch = mock.MagicMock()
    branch.name = "orphan-feature"
    branch.base_exists = False
    branch.base = "refs/remotes/origin/deleted"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print message about missing tracking branch
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "ignoring" in printed.lower() or "gone" in printed.lower()


@pytest.mark.unit
def test_execute_current_branch_marked():
    """Test Execute marks current branch with asterisk."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    branch = mock.MagicMock()
    branch.name = "main"
    branch.base_exists = True
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "*" in printed


@pytest.mark.unit
def test_execute_not_current_branch():
    """Test Execute with non-current branch (space instead of asterisk)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    branch = mock.MagicMock()
    branch.name = "old-feature"
    branch.base_exists = True
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])


@pytest.mark.unit
def test_execute_single_commit():
    """Test Execute with single commit (no 's' in commits)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.base_exists = True
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Check singular form
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "commit" in printed.lower()


@pytest.mark.unit
def test_execute_multiple_commits():
    """Test Execute with multiple commits."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.base_exists = True
    branch.commits = ["commit1", "commit2"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]
    cmd.ExecuteInParallel.return_value = [branch]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Check plural form
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "commit" in printed.lower()


@pytest.mark.unit
def test_execute_multiple_projects():
    """Test Execute with multiple projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.jobs = 2

    branch1 = mock.MagicMock()
    branch1.name = "feature"
    branch1.base_exists = True
    branch1.commits = ["commit1"]
    branch1.date = "2024-01-01"

    branch2 = mock.MagicMock()
    branch2.name = "bugfix"
    branch2.base_exists = True
    branch2.commits = ["commit2"]
    branch2.date = "2024-01-02"

    project1 = mock.MagicMock()
    project1.CurrentBranch = "main"
    project1.config = mock.MagicMock()
    project1.RelPath.return_value = "project1"
    branch1.project = project1

    project2 = mock.MagicMock()
    project2.CurrentBranch = "main"
    project2.config = mock.MagicMock()
    project2.RelPath.return_value = "project2"
    branch2.project = project2

    cmd.GetProjects.return_value = [project1, project2]
    cmd.ExecuteInParallel.return_value = [branch1, branch2]

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])


@pytest.mark.unit
def test_execute_with_args():
    """Test Execute with project args."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1

    cmd.GetProjects.return_value = []
    cmd.ExecuteInParallel.return_value = []

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    cmd.Execute(opt, ["project1"])

    cmd.GetProjects.assert_called_once_with(["project1"], all_manifests=False)
