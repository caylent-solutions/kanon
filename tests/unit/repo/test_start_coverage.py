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

"""Unit tests for subcmds/start.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.start import Start, StartError, ExecuteOneResult


def _make_cmd():
    """Create a Start command instance for testing."""
    cmd = Start.__new__(Start)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.default = mock.MagicMock()
    cmd.manifest.default.revisionExpr = "refs/heads/main"
    cmd.git_event_log = mock.MagicMock()
    return cmd


class TestStartCommand:
    """Test Start command."""

    @pytest.mark.unit
    def test_execute_one_success(self):
        """Test _ExecuteOne with successful branch start."""
        mock_project = mock.MagicMock()
        mock_project.revisionExpr = "refs/heads/main"
        mock_project.dest_branch = None
        mock_project.StartBranch = mock.MagicMock()

        with mock.patch.object(
            Start,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Start._ExecuteOne("HEAD", "new-branch", "refs/heads/main", 0)
            assert result.project_idx == 0
            assert result.error is None
            mock_project.StartBranch.assert_called_once()

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.subcmds.start.IsImmutable")
    def test_execute_one_immutable_revision_with_dest_branch(self, mock_is_immutable):
        """Test _ExecuteOne with immutable revision and dest_branch."""
        mock_project = mock.MagicMock()
        mock_project.revisionExpr = "abc123"
        mock_project.dest_branch = "refs/heads/stable"
        mock_project.StartBranch = mock.MagicMock()
        mock_is_immutable.return_value = True

        with mock.patch.object(
            Start,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Start._ExecuteOne(None, "new-branch", "refs/heads/main", 0)
            assert result.project_idx == 0
            assert result.error is None

    @pytest.mark.unit
    @mock.patch("kanon_cli.repo.subcmds.start.IsImmutable")
    def test_execute_one_immutable_revision_without_dest_branch(self, mock_is_immutable):
        """Test _ExecuteOne with immutable revision without dest_branch."""
        mock_project = mock.MagicMock()
        mock_project.revisionExpr = "abc123"
        mock_project.dest_branch = None
        mock_project.StartBranch = mock.MagicMock()
        mock_is_immutable.return_value = True

        with mock.patch.object(
            Start,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Start._ExecuteOne(None, "new-branch", "refs/heads/main", 0)
            assert result.project_idx == 0
            assert result.error is None

    @pytest.mark.unit
    def test_execute_one_failure(self):
        """Test _ExecuteOne with branch start failure."""
        mock_project = mock.MagicMock()
        mock_project.name = "test-project"
        mock_project.revisionExpr = "refs/heads/main"
        mock_project.dest_branch = None
        mock_project.StartBranch = mock.MagicMock(side_effect=ValueError("test error"))

        with mock.patch.object(
            Start,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            result = Start._ExecuteOne("HEAD", "new-branch", "refs/heads/main", 0)
            assert result.project_idx == 0
            assert result.error is not None

    @pytest.mark.unit
    @mock.patch.object(Start, "GetProjects")
    @mock.patch.object(Start, "ExecuteInParallel")
    @mock.patch.object(Start, "ParallelContext")
    @mock.patch.object(Start, "get_parallel_context")
    def test_execute_with_all_flag(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with --all flag."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.all = True
        opt.revision = None
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = None

        cmd.Execute(opt, ["new-branch"])

    @pytest.mark.unit
    @mock.patch.object(Start, "GetProjects")
    @mock.patch.object(Start, "ExecuteInParallel")
    @mock.patch.object(Start, "ParallelContext")
    @mock.patch.object(Start, "get_parallel_context")
    def test_execute_with_specific_projects(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with specific project arguments."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.all = False
        opt.revision = None
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = None

        cmd.Execute(opt, ["new-branch", "project1", "project2"])

    @pytest.mark.unit
    @mock.patch.object(Start, "GetProjects")
    @mock.patch.object(Start, "ExecuteInParallel")
    @mock.patch.object(Start, "ParallelContext")
    @mock.patch.object(Start, "get_parallel_context")
    def test_execute_default_to_current_dir(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute defaults to current directory."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.all = False
        opt.revision = None
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = None

        cmd.Execute(opt, ["new-branch"])
        mock_get_projects.assert_called_once()
        assert mock_get_projects.call_args[0][0] == ["."]

    @pytest.mark.unit
    @mock.patch.object(Start, "GetProjects")
    @mock.patch.object(Start, "ExecuteInParallel")
    @mock.patch.object(Start, "ParallelContext")
    @mock.patch.object(Start, "get_parallel_context")
    def test_execute_with_errors(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with errors."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.all = False
        opt.revision = None
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "test/project"
        mock_get_projects.return_value = [mock_project]

        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}

        # Simulate callback that adds errors
        def mock_callback(pool, pm, results):
            for result in results:
                pass  # Process results would be done here

        mock_exec.return_value = None
        mock_exec.side_effect = lambda *args, **kwargs: kwargs["callback"](
            None,
            None,
            [ExecuteOneResult(0, ValueError("test error"))],
        )

        with pytest.raises(StartError):
            cmd.Execute(opt, ["new-branch"])

    @pytest.mark.unit
    @mock.patch.object(Start, "GetProjects")
    @mock.patch.object(Start, "ExecuteInParallel")
    @mock.patch.object(Start, "ParallelContext")
    @mock.patch.object(Start, "get_parallel_context")
    def test_execute_with_revision(self, mock_get_context, mock_par_context, mock_exec, mock_get_projects):
        """Test Execute with --revision option."""
        cmd = _make_cmd()
        opt = mock.MagicMock()
        opt.all = False
        opt.revision = "abc123"
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock()
        mock_par_context.return_value.__exit__ = mock.MagicMock()
        mock_get_context.return_value = {}
        mock_exec.return_value = None

        cmd.Execute(opt, ["new-branch"])


class TestExecuteOneResult:
    """Test ExecuteOneResult named tuple."""

    @pytest.mark.unit
    def test_execute_one_result_creation(self):
        """Test ExecuteOneResult creation."""
        result = ExecuteOneResult(project_idx=0, error=None)
        assert result.project_idx == 0
        assert result.error is None

    @pytest.mark.unit
    def test_execute_one_result_with_error(self):
        """Test ExecuteOneResult with error."""
        error = ValueError("test error")
        result = ExecuteOneResult(project_idx=1, error=error)
        assert result.project_idx == 1
        assert result.error == error


class TestStartError:
    """Test StartError exception."""

    @pytest.mark.unit
    def test_start_error_creation(self):
        """Test StartError creation."""
        error = StartError(exit_code=1)
        assert error.exit_code == 1

    @pytest.mark.unit
    def test_start_error_with_aggregate_errors(self):
        """Test StartError with aggregate errors."""
        errors = [ValueError("error1"), ValueError("error2")]
        error = StartError(exit_code=1, aggregate_errors=errors)
        assert error.exit_code == 1
        assert error.aggregate_errors == errors
