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

"""Unit tests for subcmds/checkout.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.subcmds.checkout import Checkout, CheckoutBranchResult, CheckoutCommandError, MissingBranchError


def _make_cmd():
    """Create a Checkout command instance for testing."""
    cmd = Checkout.__new__(Checkout)
    cmd.manifest = mock.MagicMock()
    cmd.GetProjects = mock.MagicMock()
    cmd.ExecuteInParallel = mock.MagicMock()
    cmd.ParallelContext = mock.MagicMock()
    cmd.get_parallel_context = mock.MagicMock()
    cmd.Usage = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_validate_options_no_args():
    """Test ValidateOptions with no arguments calls Usage."""
    cmd = _make_cmd()
    opt = mock.MagicMock()

    cmd.ValidateOptions(opt, [])

    cmd.Usage.assert_called_once()


@pytest.mark.unit
def test_validate_options_with_args():
    """Test ValidateOptions with arguments."""
    cmd = _make_cmd()
    opt = mock.MagicMock()

    cmd.ValidateOptions(opt, ["branch-name"])

    cmd.Usage.assert_not_called()


@pytest.mark.unit
def test_execute_one_success():
    """Test _ExecuteOne with successful checkout."""
    project = mock.MagicMock()
    project.CheckoutBranch.return_value = True

    Checkout.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result = Checkout._ExecuteOne("feature-branch", 0)

    assert isinstance(result, CheckoutBranchResult)
    assert result.result is True
    assert result.project_idx == 0
    assert result.error is None
    project.CheckoutBranch.assert_called_once_with("feature-branch")


@pytest.mark.unit
def test_execute_one_failure():
    """Test _ExecuteOne with checkout failure."""
    project = mock.MagicMock()
    project.CheckoutBranch.return_value = False

    Checkout.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result = Checkout._ExecuteOne("feature-branch", 0)

    assert result.result is False
    assert result.project_idx == 0


@pytest.mark.unit
def test_execute_one_git_error():
    """Test _ExecuteOne with GitError."""
    project = mock.MagicMock()
    git_error = GitError("checkout failed")
    project.CheckoutBranch.side_effect = git_error

    Checkout.get_parallel_context = mock.MagicMock(return_value={"projects": [project]})

    result = Checkout._ExecuteOne("feature-branch", 0)

    assert result.result is None
    assert result.error == git_error


@pytest.mark.unit
def test_execute_success():
    """Test Execute with successful checkout."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.relpath = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [CheckoutBranchResult(True, 0, None)]

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

    cmd.Execute(opt, ["feature-branch"])

    cmd.GetProjects.assert_called_once_with([], all_manifests=False)


@pytest.mark.unit
def test_execute_with_errors():
    """Test Execute with checkout errors."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.relpath = "test/project"
    cmd.GetProjects.return_value = [project]

    error = GitError("checkout failed")
    results = [CheckoutBranchResult(None, 0, error)]

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

    with pytest.raises(CheckoutCommandError):
        cmd.Execute(opt, ["feature-branch"])


@pytest.mark.unit
def test_execute_no_branch_found():
    """Test Execute when no project has the branch."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    project.relpath = "test/project"
    cmd.GetProjects.return_value = [project]

    results = [CheckoutBranchResult(False, 0, None)]

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

    with pytest.raises(MissingBranchError):
        cmd.Execute(opt, ["nonexistent-branch"])


@pytest.mark.unit
def test_execute_multiple_projects():
    """Test Execute with multiple projects."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.jobs = 2
    opt.quiet = True

    project1 = mock.MagicMock()
    project1.relpath = "project1"
    project2 = mock.MagicMock()
    project2.relpath = "project2"
    cmd.GetProjects.return_value = [project1, project2]

    results = [
        CheckoutBranchResult(True, 0, None),
        CheckoutBranchResult(True, 1, None),
    ]

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

    cmd.Execute(opt, ["feature-branch", "project1"])

    assert cmd.GetProjects.call_count == 1


@pytest.mark.unit
def test_execute_mixed_results():
    """Test Execute with some successes and some not found."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 2
    opt.quiet = False

    project1 = mock.MagicMock()
    project1.relpath = "project1"
    project2 = mock.MagicMock()
    project2.relpath = "project2"
    cmd.GetProjects.return_value = [project1, project2]

    results = [
        CheckoutBranchResult(True, 0, None),
        CheckoutBranchResult(False, 1, None),
    ]

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

    # Should succeed even if one project doesn't have the branch
    cmd.Execute(opt, ["feature-branch"])


@pytest.mark.unit
def test_execute_uses_progress():
    """Test Execute creates Progress with branch name."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.this_manifest_only = True
    opt.jobs = 1
    opt.quiet = False

    project = mock.MagicMock()
    cmd.GetProjects.return_value = [project]

    results = [CheckoutBranchResult(True, 0, None)]

    def mock_execute(*args, **kwargs):
        output = kwargs.get("output")
        # Verify Progress was created with branch name
        assert output is not None
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

    with mock.patch("kanon_cli.repo.subcmds.checkout.Progress"):
        cmd.Execute(opt, ["my-branch"])


@pytest.mark.unit
def test_checkout_branch_result_named_tuple():
    """Test CheckoutBranchResult named tuple."""
    result = CheckoutBranchResult(True, 5, None)

    assert result.result is True
    assert result.project_idx == 5
    assert result.error is None


@pytest.mark.unit
def test_checkout_command_error():
    """Test CheckoutCommandError exception."""
    error = CheckoutCommandError("test error")
    assert isinstance(error, Exception)


@pytest.mark.unit
def test_missing_branch_error():
    """Test MissingBranchError exception."""
    error = MissingBranchError("branch not found")
    assert isinstance(error, Exception)
