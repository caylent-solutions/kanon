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

"""Unit tests for subcmds/abandon.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.error import RepoError
from kanon_cli.repo.subcmds.abandon import Abandon, AbandonError


def _make_cmd():
    """Create an Abandon command instance for testing."""
    cmd = Abandon.__new__(Abandon)
    cmd.manifest = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    cmd.ExecuteInParallel = mock.MagicMock()
    cmd.ParallelContext = mock.MagicMock()
    cmd.get_parallel_context = mock.MagicMock()
    cmd.Usage = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    cmd._Options(parser)

    parser.add_option.assert_called_once()


@pytest.mark.unit
def test_validate_options_with_all():
    """Test ValidateOptions with --all flag."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = True
    args = []

    cmd.ValidateOptions(opt, args)

    # Should not call Usage and should insert placeholder
    cmd.Usage.assert_not_called()
    assert args[0] == "'All local branches'"


@pytest.mark.unit
def test_validate_options_valid_branch():
    """Test ValidateOptions with valid branch name."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False

    with mock.patch("kanon_cli.repo.subcmds.abandon.git") as mock_git:
        mock_git.check_ref_format.return_value = True

        cmd.ValidateOptions(opt, ["feature-branch"])

        cmd.Usage.assert_not_called()


@pytest.mark.unit
def test_execute_one_single_branch():
    """Test _ExecuteOne with single branch."""
    project = mock.MagicMock()
    project.AbandonBranch.return_value = True

    Abandon.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result, idx, errors = Abandon._ExecuteOne(False, ["feature"], 0)

    assert result == {"feature": True}
    assert idx == 0
    assert errors == []
    project.AbandonBranch.assert_called_once_with("feature")


@pytest.mark.unit
def test_execute_one_all_branches():
    """Test _ExecuteOne with all_branches=True."""
    project = mock.MagicMock()
    project.GetBranches.return_value = ["branch1", "branch2"]
    project.AbandonBranch.return_value = True

    Abandon.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result, idx, errors = Abandon._ExecuteOne(True, [], 0)

    assert "branch1" in result
    assert "branch2" in result
    assert project.AbandonBranch.call_count == 2


@pytest.mark.unit
def test_execute_one_with_error():
    """Test _ExecuteOne when AbandonBranch raises RepoError."""
    project = mock.MagicMock()
    repo_error = RepoError("abandon failed")
    project.AbandonBranch.side_effect = repo_error

    Abandon.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result, idx, errors = Abandon._ExecuteOne(False, ["feature"], 0)

    assert result == {"feature": False}
    assert len(errors) == 1
    assert errors[0] == repo_error


@pytest.mark.unit
def test_execute_success_quiet():
    """Test Execute with successful abandon in quiet mode."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = True

    project = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [({"feature": True}, 0, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, ["feature"])

        # Should not print in quiet mode
        assert mock_print.call_count == 0


@pytest.mark.unit
def test_execute_success_verbose():
    """Test Execute with successful abandon in verbose mode."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [({"feature": True}, 0, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, ["feature"])

        # Should print "Abandoned branches:"
        assert mock_print.call_count > 0


@pytest.mark.unit
def test_execute_with_errors():
    """Test Execute when abandon fails."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [({"feature": False}, 0, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with pytest.raises(AbandonError):
        cmd.Execute(opt, ["feature"])


@pytest.mark.unit
def test_execute_no_local_branches():
    """Test Execute when no project has the branch."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.RelPath.return_value = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [({}, 0, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with pytest.raises(AbandonError):
        cmd.Execute(opt, ["nonexistent"])


@pytest.mark.unit
def test_execute_all_projects_success():
    """Test Execute shows 'all project' when all projects abandoned."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 2
    opt.quiet = False

    project1 = mock.MagicMock()
    project1.RelPath.return_value = "project1"
    project2 = mock.MagicMock()
    project2.RelPath.return_value = "project2"
    cmd.GetProjects.return_value = [project1, project2]

    results = [({"feature": True}, 0, []), ({"feature": True}, 1, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with mock.patch("builtins.print") as mock_print:
        cmd.Execute(opt, ["feature"])

        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "all project" in printed.lower()


@pytest.mark.unit
def test_execute_mixed_success():
    """Test Execute with some projects succeeding."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.all = False
    opt.this_manifest_only = True
    opt.jobs = 2
    opt.quiet = False

    project1 = mock.MagicMock()
    project1.RelPath.return_value = "project1"
    project2 = mock.MagicMock()
    project2.RelPath.return_value = "project2"
    cmd.GetProjects.return_value = [project1, project2]

    results = [({"feature": True}, 0, []), ({"feature": False}, 1, [])]

    def mock_execute(*args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            mock_pm = mock.MagicMock()
            callback(None, mock_pm, results)
        return None

    cmd.ExecuteInParallel.side_effect = mock_execute

    context_mock = mock.MagicMock()
    context_mock.__enter__ = mock.MagicMock(return_value=context_mock)
    context_mock.__exit__ = mock.MagicMock(return_value=False)
    cmd.ParallelContext.return_value = context_mock
    cmd.get_parallel_context.return_value = {}

    with pytest.raises(AbandonError):
        cmd.Execute(opt, ["feature"])


@pytest.mark.unit
def test_abandon_error():
    """Test AbandonError exception."""
    error = AbandonError("abandon failed")
    assert isinstance(error, Exception)
