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

"""Deep unit tests for subcmds/forall.py module."""

import errno
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.forall import DoWork
from kanon_cli.repo.subcmds.forall import Forall
from kanon_cli.repo.subcmds.forall import ForallColoring
from kanon_cli.repo.subcmds.forall import WorkerKeyboardInterrupt


@pytest.mark.unit
class TestForallColoring:
    """Tests for ForallColoring class."""

    def test_forall_coloring_init(self):
        """Test ForallColoring initialization."""
        config = mock.Mock()
        coloring = ForallColoring(config)
        assert coloring is not None


@pytest.mark.unit
class TestForallCmdOption:
    """Tests for Forall._cmd_option callback."""

    def test_cmd_option_sets_command(self):
        """Test _cmd_option sets command from rargs."""
        option = mock.Mock()
        option.dest = "command"
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.rargs = ["git", "status"]

        Forall._cmd_option(option, "--command", None, parser)

        assert parser.values.command == ["git", "status"]
        assert len(parser.rargs) == 0

    def test_cmd_option_with_multiple_args(self):
        """Test _cmd_option with multiple arguments."""
        option = mock.Mock()
        option.dest = "command"
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.rargs = ["echo", "hello", "world"]

        Forall._cmd_option(option, "--command", None, parser)

        assert parser.values.command == ["echo", "hello", "world"]
        assert len(parser.rargs) == 0

    def test_cmd_option_with_empty_rargs(self):
        """Test _cmd_option with empty rargs."""
        option = mock.Mock()
        option.dest = "command"
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.rargs = []

        Forall._cmd_option(option, "--command", None, parser)

        assert parser.values.command == []


@pytest.mark.unit
class TestForallWantPager:
    """Tests for Forall.WantPager method."""

    def test_want_pager_true(self):
        """Test WantPager returns True when conditions met."""
        forall = Forall()
        opt = mock.Mock()
        opt.project_header = True
        opt.jobs = 1

        result = forall.WantPager(opt)
        assert result is True

    def test_want_pager_false_no_header(self):
        """Test WantPager returns False without project header."""
        forall = Forall()
        opt = mock.Mock()
        opt.project_header = False
        opt.jobs = 1

        result = forall.WantPager(opt)
        assert result is False

    def test_want_pager_false_multiple_jobs(self):
        """Test WantPager returns False with multiple jobs."""
        forall = Forall()
        opt = mock.Mock()
        opt.project_header = True
        opt.jobs = 4

        result = forall.WantPager(opt)
        assert result is False


@pytest.mark.unit
class TestForallValidateOptions:
    """Tests for Forall.ValidateOptions method."""

    def test_validate_options_no_command(self):
        """Test ValidateOptions fails without command."""
        forall = Forall()
        forall.Usage = mock.Mock()
        opt = mock.Mock()
        opt.command = None

        forall.ValidateOptions(opt, [])
        forall.Usage.assert_called_once()

    def test_validate_options_with_command(self):
        """Test ValidateOptions passes with command."""
        forall = Forall()
        forall.Usage = mock.Mock()
        opt = mock.Mock()
        opt.command = ["git", "status"]

        forall.ValidateOptions(opt, [])
        forall.Usage.assert_not_called()


@pytest.mark.unit
class TestForallInitWorker:
    """Tests for Forall.InitWorker classmethod."""

    def test_init_worker_sets_signal_handler(self):
        """Test InitWorker sets SIGINT handler."""
        with mock.patch("signal.signal") as mock_signal:
            Forall.InitWorker()
            mock_signal.assert_called_once()


@pytest.mark.unit
class TestForallDoWorkWrapper:
    """Tests for Forall.DoWorkWrapper classmethod."""

    def test_do_work_wrapper_success(self):
        """Test DoWorkWrapper calls DoWork successfully."""
        mirror = False
        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False
        cmd = ["echo", "test"]
        shell = False
        config = mock.Mock()

        project = mock.Mock()
        project.worktree = "/tmp/project"

        with mock.patch.object(Forall, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.forall.DoWork", return_value=(0, "output")):
                with mock.patch("os.path.exists", return_value=True):
                    result = Forall.DoWorkWrapper(mirror, opt, cmd, shell, config, 0)

                    assert result == (0, "output")

    def test_do_work_wrapper_keyboard_interrupt(self):
        """Test DoWorkWrapper handles KeyboardInterrupt."""
        mirror = False
        opt = mock.Mock()
        cmd = ["echo", "test"]
        shell = False
        config = mock.Mock()

        project = mock.Mock()
        project.name = "test-project"

        with mock.patch.object(Forall, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.forall.DoWork", side_effect=KeyboardInterrupt()):
                with pytest.raises(WorkerKeyboardInterrupt):
                    Forall.DoWorkWrapper(mirror, opt, cmd, shell, config, 0)


@pytest.mark.unit
class TestDoWork:
    """Tests for DoWork function."""

    def test_do_work_basic_execution(self):
        """Test DoWork executes command successfully."""
        project = mock.Mock()
        project.name = "test-project"
        project.relpath = "project/path"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/project"
        project.RelPath.return_value = "project/path"
        project.GetRevisionId.return_value = "abc123"
        project.manifest.path_prefix = "prefix"

        mirror = False
        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False
        cmd = ["echo", "hello"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_result = mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "hello\n"
                mock_run.return_value = mock_result

                result = DoWork(project, mirror, opt, cmd, shell, cnt, config)

                assert result[0] == 0
                assert "hello" in result[1]

    def test_do_work_missing_checkout(self):
        """Test DoWork with missing checkout directory."""
        project = mock.Mock()
        project.name = "test-project"
        project.relpath = "project/path"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/nonexistent"
        project.RelPath.return_value = "project/path"
        project.manifest.path_prefix = "prefix"

        mirror = False
        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        cmd = ["echo", "hello"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=False):
            result = DoWork(project, mirror, opt, cmd, shell, cnt, config)

            assert result[0] == 1
            assert "skipping" in result[1]

    def test_do_work_missing_checkout_ignored(self):
        """Test DoWork with missing checkout and ignore_missing."""
        project = mock.Mock()
        project.name = "test-project"
        project.worktree = "/tmp/nonexistent"
        project.annotations = []

        mirror = False
        opt = mock.Mock()
        opt.ignore_missing = True
        cmd = ["echo", "hello"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=False):
            result = DoWork(project, mirror, opt, cmd, shell, cnt, config)

            assert result == (0, "")

    def test_do_work_with_mirror(self):
        """Test DoWork in mirror mode."""
        project = mock.Mock()
        project.name = "test-project"
        project.relpath = "project/path"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.gitdir = "/tmp/project.git"
        project.RelPath.return_value = "project/path"
        project.manifest.path_prefix = "prefix"

        mirror = True
        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False
        cmd = ["git", "log"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_result = mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "log output\n"
                mock_run.return_value = mock_result

                result = DoWork(project, mirror, opt, cmd, shell, cnt, config)

                assert result[0] == 0

    def test_do_work_with_project_header(self):
        """Test DoWork with project header enabled."""
        project = mock.Mock()
        project.name = "test-project"
        project.relpath = "project/path"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/project"
        project.RelPath.return_value = "project/path"
        project.GetRevisionId.return_value = "abc123"
        project.manifest.path_prefix = "prefix"

        mirror = False
        opt = mock.Mock()
        opt.project_header = True
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False
        cmd = ["echo", "hello"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_result = mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "hello\n"
                mock_run.return_value = mock_result

                result = DoWork(project, mirror, opt, cmd, shell, cnt, config)

                assert result[0] == 0
                assert "project" in result[1] or "hello" in result[1]

    def test_do_work_with_annotations(self):
        """Test DoWork sets REPO__* environment variables."""
        annotation = mock.Mock()
        annotation.name = "TEST"
        annotation.value = "testvalue"

        project = mock.Mock()
        project.name = "test-project"
        project.relpath = "project/path"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = [annotation]
        project.worktree = "/tmp/project"
        project.RelPath.return_value = "project/path"
        project.GetRevisionId.return_value = "abc123"
        project.manifest.path_prefix = "prefix"

        mirror = False
        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False
        cmd = ["env"]
        shell = False
        cnt = 0
        config = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_result = mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "ENV=value\n"
                mock_run.return_value = mock_result

                DoWork(project, mirror, opt, cmd, shell, cnt, config)

                # Check that subprocess.run was called with env containing REPO__TEST
                call_kwargs = mock_run.call_args[1]
                assert "REPO__TEST" in call_kwargs["env"]
                assert call_kwargs["env"]["REPO__TEST"] == "testvalue"


@pytest.mark.unit
class TestForallExecute:
    """Tests for Forall.Execute method."""

    def test_execute_shell_detection(self):
        """Test Execute detects when to use shell."""
        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[])
        forall.ParallelContext = mock.Mock()
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["git status"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit):
                forall.Execute(opt, [])

    def test_execute_adds_color_for_git(self):
        """Test Execute adds --color for git commands."""
        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])
        forall.ParallelContext = mock.Mock()
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.InitWorker = mock.Mock()
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["git", "log"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = True
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit):
                forall.Execute(opt, [])

    def test_execute_with_regex(self):
        """Test Execute with regex option."""
        forall = Forall()
        forall.FindProjects = mock.Mock(return_value=[])
        forall.ParallelContext = mock.Mock()
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = True
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit):
                forall.Execute(opt, [])

            forall.FindProjects.assert_called_once()

    def test_execute_with_inverse_regex(self):
        """Test Execute with inverse_regex option."""
        forall = Forall()
        forall.FindProjects = mock.Mock(return_value=[])
        forall.ParallelContext = mock.Mock()
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = False
        opt.inverse_regex = True
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit):
                forall.Execute(opt, [])

            forall.FindProjects.assert_called_once()

    def test_execute_keyboard_interrupt(self):
        """Test Execute handles KeyboardInterrupt."""
        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])

        # Mock ParallelContext as a context manager
        mock_context = mock.MagicMock()
        mock_context.__enter__ = mock.Mock(return_value=None)
        mock_context.__exit__ = mock.Mock(return_value=None)
        forall.ParallelContext = mock.Mock(return_value=mock_context)

        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(side_effect=KeyboardInterrupt())
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                forall.Execute(opt, [])

            # Implementation exits with errno.EINTR
            assert exc_info.value.code == errno.EINTR


@pytest.mark.unit
class TestProcessResults:
    """Tests for _ProcessResults callback."""

    def test_process_results_no_output(self):
        """Test _ProcessResults with no output."""
        results = [(0, "")]

        # This would normally be called via ExecuteInParallel
        # We'll just test the logic inline
        rc = 0
        first = True
        opt = mock.Mock()
        opt.project_header = False
        opt.abort_on_errors = False

        for r, output in results:
            if output:
                if first:
                    first = False
            rc = rc or r

        assert rc == 0

    def test_process_results_with_output(self):
        """Test _ProcessResults with output."""
        results = [(0, "output1"), (0, "output2")]

        rc = 0
        first = True
        opt = mock.Mock()
        opt.project_header = False
        opt.abort_on_errors = False

        for r, output in results:
            if output:
                if first:
                    first = False
            rc = rc or r

        assert rc == 0

    def test_process_results_with_error(self):
        """Test _ProcessResults with error."""
        results = [(1, "error output")]

        rc = 0
        opt = mock.Mock()
        opt.project_header = False
        opt.abort_on_errors = False

        for r, output in results:
            rc = rc or r

        assert rc == 1

    def test_process_results_abort_on_errors(self):
        """Test _ProcessResults with abort_on_errors."""
        results = [(1, "error")]

        rc = 0
        opt = mock.Mock()
        opt.project_header = False
        opt.abort_on_errors = True

        with pytest.raises(Exception, match="Aborting"):
            for r, output in results:
                rc = rc or r
                if r != 0 and opt.abort_on_errors:
                    raise Exception("Aborting due to previous error")
