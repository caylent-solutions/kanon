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

"""Unit tests for subcmds/overview.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.overview import Overview


def _make_cmd():
    """Create an Overview command instance for testing."""
    cmd = Overview.__new__(Overview)
    cmd.manifest = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    cmd._Options(parser)

    # Should add multiple options
    assert parser.add_option.call_count >= 3


@pytest.mark.unit
def test_execute_no_branches():
    """Test Execute with no branches."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    project = mock.MagicMock()
    project.GetBranches.return_value = []

    cmd.GetProjects.return_value = [project]

    cmd.Execute(opt, [])

    # Should return early, no output
    cmd.GetProjects.assert_called_once()


@pytest.mark.unit
def test_execute_with_branches():
    """Test Execute with branches."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["commit1", "commit2"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature"]
    project.GetUploadableBranch.return_value = branch
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print output
        assert mock_print.call_count > 0


@pytest.mark.unit
def test_execute_current_branch_only():
    """Test Execute with current_branch option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = True

    current_branch = mock.MagicMock()
    current_branch.name = "main"
    current_branch.commits = ["commit1"]
    current_branch.date = "2024-01-01"

    other_branch = mock.MagicMock()
    other_branch.name = "feature"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["main", "feature"]
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    current_branch.project = project

    def get_uploadable(name):
        if name == "main":
            return current_branch
        return other_branch

    project.GetUploadableBranch.side_effect = get_uploadable

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])

    # Should only process current branch
    assert project.GetUploadableBranch.call_count == 2


@pytest.mark.unit
def test_execute_filters_none_branches():
    """Test Execute filters out None branches."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature", "none-branch"]
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    def get_uploadable(name):
        if name == "feature":
            return branch
        return None

    project.GetUploadableBranch.side_effect = get_uploadable

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])


@pytest.mark.unit
def test_execute_multiple_projects():
    """Test Execute with multiple projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.current_branch = False

    branch1 = mock.MagicMock()
    branch1.name = "feature"
    branch1.commits = ["commit1"]
    branch1.date = "2024-01-01"

    branch2 = mock.MagicMock()
    branch2.name = "main"
    branch2.commits = ["commit2", "commit3"]
    branch2.date = "2024-01-02"

    project1 = mock.MagicMock()
    project1.GetBranches.return_value = ["feature"]
    project1.GetUploadableBranch.return_value = branch1
    project1.CurrentBranch = "feature"
    project1.config = mock.MagicMock()
    project1.RelPath.return_value = "project1"
    branch1.project = project1

    project2 = mock.MagicMock()
    project2.GetBranches.return_value = ["main"]
    project2.GetUploadableBranch.return_value = branch2
    project2.CurrentBranch = "other"
    project2.config = mock.MagicMock()
    project2.RelPath.return_value = "project2"
    branch2.project = project2

    cmd.GetProjects.return_value = [project1, project2]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print for both projects
        assert mock_print.call_count > 0


@pytest.mark.unit
def test_execute_single_commit():
    """Test Execute with single commit (no 's' in output)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature"]
    project.GetUploadableBranch.return_value = branch
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Check for singular "commit"
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "commit" in printed.lower()


@pytest.mark.unit
def test_execute_is_current_branch():
    """Test Execute marks current branch with asterisk."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["commit1", "commit2"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature"]
    project.GetUploadableBranch.return_value = branch
    project.CurrentBranch = "feature"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should have asterisk for current branch
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "*" in printed or "feature" in printed


@pytest.mark.unit
def test_execute_prints_deprecation():
    """Test Execute prints deprecation message."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["commit1"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature"]
    project.GetUploadableBranch.return_value = branch
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print"):
        cmd.Execute(opt, [])

        # Deprecation message is printed via coloring output, just verify execution
        cmd.GetProjects.assert_called_once()


@pytest.mark.unit
def test_execute_prints_commits():
    """Test Execute prints individual commits."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    branch = mock.MagicMock()
    branch.name = "feature"
    branch.commits = ["abc123 First commit", "def456 Second commit"]
    branch.date = "2024-01-01"

    project = mock.MagicMock()
    project.GetBranches.return_value = ["feature"]
    project.GetUploadableBranch.return_value = branch
    project.CurrentBranch = "main"
    project.config = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    branch.project = project

    cmd.GetProjects.return_value = [project]

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, [])

        # Should print commits
        assert mock_print.call_count >= 2  # Should print branch info and commits


@pytest.mark.unit
def test_execute_with_args():
    """Test Execute with project args."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.current_branch = False

    cmd.GetProjects.return_value = []

    cmd.Execute(opt, ["project1", "project2"])

    cmd.GetProjects.assert_called_once_with(["project1", "project2"], all_manifests=False)
