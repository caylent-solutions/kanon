"""Tests for uncovered lines in subcmds/status.py.

Covers:
- Lines 134-140: _ProcessResults nested callback in Execute
- Lines 164-165: while head != "" parent directory loop in Execute with orphans
"""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.status import Status


def _make_cmd(topdir):
    """Create a Status command instance for testing.

    Args:
        topdir: Path to use as the manifest topdir. Pass a tmp_path-derived
            value from the calling test to avoid hard-coded path literals.
    """
    cmd = Status.__new__(Status)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.topdir = topdir
    cmd.client = mock.MagicMock()
    cmd.client.globalConfig = mock.MagicMock()
    return cmd


@pytest.mark.unit
class TestStatusProcessResultsCallback:
    """Tests that _ProcessResults callback inside Execute is exercised."""

    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch.object(Status, "ExecuteInParallel")
    def test_process_results_counts_clean_states(
        self, mock_exec, mock_get_context, mock_par_context, mock_get_projects, tmp_path
    ):
        """Lines 134-140: _ProcessResults iterates results and counts CLEAN states.

        Uses side_effect on ExecuteInParallel to invoke the callback with real
        result data, exercising lines 134-140 that are otherwise unreachable
        when ExecuteInParallel is mocked to return directly.
        """
        cmd = _make_cmd(str(tmp_path))
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock(return_value=None)
        mock_par_context.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_get_context.return_value = {"projects": [mock_project]}

        def invoke_callback(_jobs, _func, _inputs, callback, **kwargs):
            results = [("CLEAN", ""), ("DIRTY", "some output")]
            return callback(None, None, iter(results))

        mock_exec.side_effect = invoke_callback

        cmd.Execute(opt, [])

        mock_exec.assert_called_once()

    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch.object(Status, "ExecuteInParallel")
    def test_process_results_prints_output_when_present(
        self, mock_exec, mock_get_context, mock_par_context, mock_get_projects, capsys, tmp_path
    ):
        """Lines 135-137: _ProcessResults prints output when it is non-empty."""
        cmd = _make_cmd(str(tmp_path))
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock(return_value=None)
        mock_par_context.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_get_context.return_value = {"projects": [mock_project]}

        def invoke_callback(_jobs, _func, _inputs, callback, **kwargs):
            results = [("DIRTY", "project has changes\n")]
            return callback(None, None, iter(results))

        mock_exec.side_effect = invoke_callback

        cmd.Execute(opt, [])
        captured = capsys.readouterr()
        assert "project has changes" in captured.out

    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch.object(Status, "ExecuteInParallel")
    def test_process_results_returns_clean_count(
        self, mock_exec, mock_get_context, mock_par_context, mock_get_projects, capsys, tmp_path
    ):
        """Lines 138-139: CLEAN state increments counter; prints all-clean message."""
        cmd = _make_cmd(str(tmp_path))
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = False
        opt.orphans = False
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock(return_value=None)
        mock_par_context.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_get_context.return_value = {"projects": [mock_project]}

        def invoke_callback(_jobs, _func, _inputs, callback, **kwargs):
            results = [("CLEAN", "")]
            return callback(None, None, iter(results))

        mock_exec.side_effect = invoke_callback

        cmd.Execute(opt, [])
        captured = capsys.readouterr()
        assert "nothing to commit" in captured.out


@pytest.mark.unit
class TestStatusOrphanNestedPath:
    """Tests for lines 163-165: while head != '' loop for nested project paths."""

    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch("os.chdir")
    @mock.patch("os.getcwd")
    @mock.patch("glob.glob")
    def test_orphans_nested_path_populates_parent_dirs(
        self,
        mock_glob,
        mock_getcwd,
        mock_chdir,
        mock_get_context,
        mock_par_context,
        mock_exec,
        mock_get_projects,
        tmp_path,
    ):
        """Lines 163-165: relpath with directory separators causes parent path loop.

        A project at 'dir/subdir/project' causes the while loop to add
        'dir/subdir' and 'dir' to proj_dirs_parents.
        """
        cmd = _make_cmd(str(tmp_path / "topdir"))
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = True
        opt.orphans = True
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "dir/subdir/project"
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock(return_value=None)
        mock_par_context.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_get_context.return_value = {}
        mock_exec.return_value = 0
        mock_getcwd.return_value = str(tmp_path / "cwd")
        mock_glob.return_value = []

        cmd.Execute(opt, [])

        mock_chdir.assert_called()

    @mock.patch.object(Status, "GetProjects")
    @mock.patch.object(Status, "ExecuteInParallel")
    @mock.patch.object(Status, "ParallelContext")
    @mock.patch.object(Status, "get_parallel_context")
    @mock.patch("os.chdir")
    @mock.patch("os.getcwd")
    @mock.patch("glob.glob")
    def test_orphans_triple_nested_path(
        self,
        mock_glob,
        mock_getcwd,
        mock_chdir,
        mock_get_context,
        mock_par_context,
        mock_exec,
        mock_get_projects,
        tmp_path,
    ):
        """Lines 163-165: deeper nested path traverses multiple parent components."""
        cmd = _make_cmd(str(tmp_path / "topdir"))
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = True
        opt.orphans = True
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "a/b/c/d"
        mock_get_projects.return_value = [mock_project]
        mock_par_context.return_value.__enter__ = mock.MagicMock(return_value=None)
        mock_par_context.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_get_context.return_value = {}
        mock_exec.return_value = 0
        mock_getcwd.return_value = str(tmp_path / "cwd")
        mock_glob.return_value = []

        cmd.Execute(opt, [])

        mock_chdir.assert_called()
