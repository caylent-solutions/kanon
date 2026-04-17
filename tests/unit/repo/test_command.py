# Copyright (C) 2008 The Android Open Source Project
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

"""Unittests for the command.py module."""

import optparse
import os
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import command
from kanon_cli.repo import progress
from kanon_cli.repo.error import NoSuchProjectError


@pytest.mark.unit
class TestConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_worker_batch_size(self):
        """Test WORKER_BATCH_SIZE constant."""
        self.assertEqual(command.WORKER_BATCH_SIZE, 32)
        self.assertIsInstance(command.WORKER_BATCH_SIZE, int)

    def test_default_local_jobs(self):
        """Test DEFAULT_LOCAL_JOBS constant."""
        self.assertIsInstance(command.DEFAULT_LOCAL_JOBS, int)
        self.assertGreater(command.DEFAULT_LOCAL_JOBS, 0)
        self.assertLessEqual(command.DEFAULT_LOCAL_JOBS, 8)

    def test_generate_manpages_flag(self):
        """Test GENERATE_MANPAGES flag."""
        self.assertIsInstance(command.GENERATE_MANPAGES, bool)


@pytest.mark.unit
class TestUsageError(unittest.TestCase):
    """Tests for UsageError exception."""

    def test_usage_error_is_repo_exit_error(self):
        """Test that UsageError inherits from RepoExitError."""
        from kanon_cli.repo.error import RepoExitError

        err = command.UsageError()
        self.assertIsInstance(err, RepoExitError)


@pytest.mark.unit
class TestCommandInit(unittest.TestCase):
    """Tests for Command.__init__ method."""

    def test_init_with_defaults(self):
        """Test Command initialization with default values."""
        cmd = command.Command()

        self.assertIsNone(cmd.repodir)
        self.assertIsNone(cmd.client)
        self.assertIsNone(cmd.manifest)
        self.assertIsNone(cmd.git_event_log)
        self.assertIsNone(cmd._optparse)

    def test_init_with_all_params(self):
        """Test Command initialization with all parameters."""
        mock_client = mock.Mock()
        mock_manifest = mock.Mock()
        mock_outer_client = mock.Mock()
        mock_outer_manifest = mock.Mock()
        mock_git_log = mock.Mock()

        cmd = command.Command(
            repodir="/test/repo",
            client=mock_client,
            manifest=mock_manifest,
            git_event_log=mock_git_log,
            outer_client=mock_outer_client,
            outer_manifest=mock_outer_manifest,
        )

        self.assertEqual(cmd.repodir, "/test/repo")
        self.assertEqual(cmd.client, mock_client)
        self.assertEqual(cmd.manifest, mock_manifest)
        self.assertEqual(cmd.git_event_log, mock_git_log)
        self.assertEqual(cmd.outer_client, mock_outer_client)
        self.assertEqual(cmd.outer_manifest, mock_outer_manifest)

    def test_init_outer_client_defaults_to_client(self):
        """Test that outer_client defaults to client."""
        mock_client = mock.Mock()

        cmd = command.Command(client=mock_client)

        self.assertEqual(cmd.outer_client, mock_client)


@pytest.mark.unit
class TestCommandConstants(unittest.TestCase):
    """Tests for Command class constants."""

    def test_common_default(self):
        """Test COMMON constant default value."""
        self.assertFalse(command.Command.COMMON)

    def test_parallel_jobs_default(self):
        """Test PARALLEL_JOBS constant default value."""
        self.assertIsNone(command.Command.PARALLEL_JOBS)

    def test_multi_manifest_support_default(self):
        """Test MULTI_MANIFEST_SUPPORT constant default value."""
        self.assertTrue(command.Command.MULTI_MANIFEST_SUPPORT)

    def test_event_log_exists(self):
        """Test that event_log class variable exists."""
        self.assertIsNotNone(command.Command.event_log)


@pytest.mark.unit
class TestCommandWantPager(unittest.TestCase):
    """Tests for Command.WantPager method."""

    def test_want_pager_default(self):
        """Test WantPager returns False by default."""
        cmd = command.Command()
        self.assertFalse(cmd.WantPager(None))

    def test_want_pager_with_options(self):
        """Test WantPager with options object."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        self.assertFalse(cmd.WantPager(mock_opt))


@pytest.mark.unit
class TestCommandOptionParser(unittest.TestCase):
    """Tests for Command.OptionParser property."""

    def test_option_parser_cached(self):
        """Test that OptionParser is cached."""
        cmd = command.Command()
        cmd.NAME = "test"

        parser1 = cmd.OptionParser
        parser2 = cmd.OptionParser

        self.assertIs(parser1, parser2)

    def test_option_parser_with_help_usage(self):
        """Test OptionParser with helpUsage attribute."""
        cmd = command.Command()
        cmd.NAME = "test"
        cmd.helpUsage = "usage: test [options]"

        parser = cmd.OptionParser

        self.assertIsInstance(parser, optparse.OptionParser)

    def test_option_parser_without_help_usage(self):
        """Test OptionParser without helpUsage attribute."""
        cmd = command.Command()
        cmd.NAME = "test"

        parser = cmd.OptionParser

        self.assertIsInstance(parser, optparse.OptionParser)

    def test_option_parser_calls_common_options(self):
        """Test that OptionParser calls _CommonOptions."""
        cmd = command.Command()
        cmd.NAME = "test"

        with mock.patch.object(cmd, "_CommonOptions") as mock_common:
            with mock.patch.object(cmd, "_Options"):
                cmd.OptionParser

        mock_common.assert_called_once()

    def test_option_parser_calls_options(self):
        """Test that OptionParser calls _Options."""
        cmd = command.Command()
        cmd.NAME = "test"

        with mock.patch.object(cmd, "_Options") as mock_options:
            cmd.OptionParser

        mock_options.assert_called_once()


@pytest.mark.unit
class TestCommandCommonOptions(unittest.TestCase):
    """Tests for Command._CommonOptions method."""

    def test_common_options_verbose(self):
        """Test that verbose option is added."""
        cmd = command.Command()
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser)

        self.assertTrue(parser.has_option("--verbose"))
        self.assertTrue(parser.has_option("-v"))

    def test_common_options_quiet(self):
        """Test that quiet option is added."""
        cmd = command.Command()
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser)

        self.assertTrue(parser.has_option("--quiet"))
        self.assertTrue(parser.has_option("-q"))

    def test_common_options_without_v(self):
        """Test common options without -v flag."""
        cmd = command.Command()
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser, opt_v=False)

        self.assertTrue(parser.has_option("--verbose"))
        self.assertFalse(parser.has_option("-v"))

    def test_common_options_with_parallel_jobs(self):
        """Test that jobs option is added when PARALLEL_JOBS is set."""
        cmd = command.Command()
        cmd.PARALLEL_JOBS = 4
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser)

        self.assertTrue(parser.has_option("--jobs"))
        self.assertTrue(parser.has_option("-j"))

    def test_common_options_without_parallel_jobs(self):
        """Test that jobs option is not added when PARALLEL_JOBS is None."""
        cmd = command.Command()
        cmd.PARALLEL_JOBS = None
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser)

        self.assertFalse(parser.has_option("--jobs"))

    def test_common_options_multi_manifest(self):
        """Test that multi-manifest options are added."""
        cmd = command.Command()
        parser = optparse.OptionParser()

        cmd._CommonOptions(parser)

        self.assertTrue(parser.has_option("--outer-manifest"))
        self.assertTrue(parser.has_option("--no-outer-manifest"))
        self.assertTrue(parser.has_option("--this-manifest-only"))
        self.assertTrue(parser.has_option("--all-manifests"))


@pytest.mark.unit
class TestCommandOptions(unittest.TestCase):
    """Tests for Command._Options method."""

    def test_options_default_implementation(self):
        """Test that _Options default implementation does nothing."""
        cmd = command.Command()
        parser = optparse.OptionParser()

        # Should not raise
        cmd._Options(parser)


@pytest.mark.unit
class TestCommandRegisteredEnvironmentOptions(unittest.TestCase):
    """Tests for Command._RegisteredEnvironmentOptions method."""

    def test_registered_environment_options_default(self):
        """Test that default returns empty dict."""
        cmd = command.Command()
        result = cmd._RegisteredEnvironmentOptions()

        self.assertEqual(result, {})
        self.assertIsInstance(result, dict)


@pytest.mark.unit
class TestCommandReadEnvironmentOptions(unittest.TestCase):
    """Tests for Command.ReadEnvironmentOptions method."""

    def test_read_environment_options_no_env(self):
        """Test ReadEnvironmentOptions with no environment variables."""
        cmd = command.Command()
        mock_opts = mock.Mock()
        mock_opts.test_option = None

        with mock.patch.dict(os.environ, {}, clear=True):
            result = cmd.ReadEnvironmentOptions(mock_opts)

        self.assertEqual(result, mock_opts)

    def test_read_environment_options_with_env(self):
        """Test ReadEnvironmentOptions with environment variable."""
        cmd = command.Command()

        def mock_registered():
            return {"REPO_TEST_OPTION": "test_option"}

        cmd._RegisteredEnvironmentOptions = mock_registered

        mock_opts = mock.Mock()
        mock_opts.test_option = None

        with mock.patch.dict(os.environ, {"REPO_TEST_OPTION": "test_value"}):
            result = cmd.ReadEnvironmentOptions(mock_opts)

        self.assertEqual(result.test_option, "test_value")

    def test_read_environment_options_user_value_takes_precedence(self):
        """Test that user-provided value takes precedence over environment."""
        cmd = command.Command()

        def mock_registered():
            return {"REPO_TEST_OPTION": "test_option"}

        cmd._RegisteredEnvironmentOptions = mock_registered

        mock_opts = mock.Mock()
        mock_opts.test_option = "user_value"

        with mock.patch.dict(os.environ, {"REPO_TEST_OPTION": "env_value"}):
            result = cmd.ReadEnvironmentOptions(mock_opts)

        self.assertEqual(result.test_option, "user_value")


@pytest.mark.unit
class TestCommandUsage(unittest.TestCase):
    """Tests for Command.Usage method."""

    def test_usage_raises_usage_error(self):
        """Test that Usage raises UsageError."""
        cmd = command.Command()
        cmd.NAME = "test"

        with self.assertRaises(command.UsageError):
            cmd.Usage()

    def test_usage_prints_usage(self):
        """Test that Usage prints usage information."""
        cmd = command.Command()
        cmd.NAME = "test"

        with mock.patch.object(cmd.OptionParser, "print_usage") as mock_print:
            try:
                cmd.Usage()
            except command.UsageError:
                pass

        mock_print.assert_called_once()


@pytest.mark.unit
class TestCommandCommonValidateOptions(unittest.TestCase):
    """Tests for Command.CommonValidateOptions method."""

    def test_validate_options_quiet_false(self):
        """Test CommonValidateOptions with output_mode False."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        mock_opt.output_mode = False
        mock_opt.outer_manifest = None

        cmd.CommonValidateOptions(mock_opt, [])

        self.assertTrue(mock_opt.quiet)
        self.assertFalse(mock_opt.verbose)

    def test_validate_options_quiet_true(self):
        """Test CommonValidateOptions with output_mode True."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        mock_opt.output_mode = True
        mock_opt.outer_manifest = None

        cmd.CommonValidateOptions(mock_opt, [])

        self.assertFalse(mock_opt.quiet)
        self.assertTrue(mock_opt.verbose)

    def test_validate_options_quiet_none(self):
        """Test CommonValidateOptions with output_mode None."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        mock_opt.output_mode = None
        mock_opt.outer_manifest = None

        cmd.CommonValidateOptions(mock_opt, [])

        self.assertFalse(mock_opt.quiet)
        self.assertFalse(mock_opt.verbose)

    def test_validate_options_outer_manifest_default(self):
        """Test that outer_manifest defaults to True."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        mock_opt.output_mode = None
        mock_opt.outer_manifest = None

        cmd.CommonValidateOptions(mock_opt, [])

        self.assertTrue(mock_opt.outer_manifest)

    def test_validate_options_outer_manifest_preserved(self):
        """Test that outer_manifest is preserved if set."""
        cmd = command.Command()
        mock_opt = mock.Mock()
        mock_opt.output_mode = None
        mock_opt.outer_manifest = False

        cmd.CommonValidateOptions(mock_opt, [])

        self.assertFalse(mock_opt.outer_manifest)


@pytest.mark.unit
class TestCommandValidateOptions(unittest.TestCase):
    """Tests for Command.ValidateOptions method."""

    def test_validate_options_default(self):
        """Test that ValidateOptions default implementation does nothing."""
        cmd = command.Command()
        mock_opt = mock.Mock()

        # Should not raise
        cmd.ValidateOptions(mock_opt, [])


@pytest.mark.unit
class TestCommandExecute(unittest.TestCase):
    """Tests for Command.Execute method."""

    def test_execute_not_implemented(self):
        """Test that Execute raises NotImplementedError."""
        cmd = command.Command()

        with self.assertRaises(NotImplementedError):
            cmd.Execute(None, [])


@pytest.mark.unit
class TestCommandParallelContext(unittest.TestCase):
    """Tests for Command.ParallelContext context manager."""

    def test_parallel_context_sets_context(self):
        """Test that ParallelContext sets _parallel_context."""
        self.assertIsNone(command.Command._parallel_context)

        with command.Command.ParallelContext():
            self.assertIsNotNone(command.Command._parallel_context)
            self.assertIsInstance(command.Command._parallel_context, dict)

        self.assertIsNone(command.Command._parallel_context)

    def test_parallel_context_allows_data_storage(self):
        """Test that data can be stored in parallel context."""
        with command.Command.ParallelContext():
            ctx = command.Command.get_parallel_context()
            ctx["test_key"] = "test_value"

            self.assertEqual(ctx["test_key"], "test_value")

    def test_parallel_context_clears_on_exit(self):
        """Test that context is cleared on exit."""
        with command.Command.ParallelContext():
            ctx = command.Command.get_parallel_context()
            ctx["test_key"] = "test_value"

        self.assertIsNone(command.Command._parallel_context)

    def test_get_parallel_context_asserts_without_context(self):
        """Test that get_parallel_context asserts when no context."""
        command.Command._parallel_context = None

        with self.assertRaises(AssertionError):
            command.Command.get_parallel_context()


@pytest.mark.unit
class TestCommandInitParallelWorker(unittest.TestCase):
    """Tests for Command._InitParallelWorker method."""

    def test_init_parallel_worker_sets_context(self):
        """Test that _InitParallelWorker sets context."""
        test_context = {"key": "value"}

        command.Command._InitParallelWorker(test_context, None)

        self.assertEqual(command.Command._parallel_context, test_context)

    def test_init_parallel_worker_calls_initializer(self):
        """Test that _InitParallelWorker calls initializer."""
        mock_initializer = mock.Mock()
        test_context = {}

        command.Command._InitParallelWorker(test_context, mock_initializer)

        mock_initializer.assert_called_once()

    def test_init_parallel_worker_without_initializer(self):
        """Test _InitParallelWorker without initializer."""
        test_context = {}

        # Should not raise
        command.Command._InitParallelWorker(test_context, None)


@pytest.mark.unit
class TestCommandExecuteInParallel(unittest.TestCase):
    """Tests for Command.ExecuteInParallel method."""

    def setUp(self):
        """Reset parallel context before each test."""
        command.Command._parallel_context = None

    def tearDown(self):
        """Clean up parallel context after each test."""
        command.Command._parallel_context = None

    def test_execute_in_parallel_single_job(self):
        """Test ExecuteInParallel with single job."""

        def test_func(x):
            return x * 2

        def callback(pool, output, results):
            return list(results)

        result = command.Command.ExecuteInParallel(jobs=1, func=test_func, inputs=[1, 2, 3], callback=callback)

        self.assertEqual(result, [2, 4, 6])

    def test_execute_in_parallel_single_input(self):
        """Test ExecuteInParallel with single input."""

        def test_func(x):
            return x * 2

        def callback(pool, output, results):
            return list(results)

        result = command.Command.ExecuteInParallel(jobs=2, func=test_func, inputs=[5], callback=callback)

        self.assertEqual(result, [10])

    def test_execute_in_parallel_with_output(self):
        """Test ExecuteInParallel with output object."""

        def test_func(x):
            return x * 2

        def callback(pool, output, results):
            return (list(results), output)

        mock_output = mock.Mock()

        result_list, output = command.Command.ExecuteInParallel(
            jobs=1,
            func=test_func,
            inputs=[1, 2],
            callback=callback,
            output=mock_output,
        )

        self.assertEqual(result_list, [2, 4])
        self.assertEqual(output, mock_output)

    def test_execute_in_parallel_with_progress_output(self):
        """Test ExecuteInParallel with Progress output."""

        def test_func(x):
            return x * 2

        def callback(pool, output, results):
            return list(results)

        mock_progress = mock.Mock(spec=progress.Progress)

        command.Command.ExecuteInParallel(
            jobs=1,
            func=test_func,
            inputs=[1, 2],
            callback=callback,
            output=mock_progress,
        )

        mock_progress.end.assert_called_once()


@pytest.mark.unit
class TestCommandResetPathToProjectMap(unittest.TestCase):
    """Tests for Command._ResetPathToProjectMap method."""

    def test_reset_path_to_project_map(self):
        """Test _ResetPathToProjectMap creates mapping."""
        cmd = command.Command()
        mock_project1 = mock.Mock()
        mock_project1.worktree = "/path/to/project1"
        mock_project2 = mock.Mock()
        mock_project2.worktree = "/path/to/project2"

        cmd._ResetPathToProjectMap([mock_project1, mock_project2])

        self.assertEqual(len(cmd._by_path), 2)
        self.assertEqual(cmd._by_path["/path/to/project1"], mock_project1)
        self.assertEqual(cmd._by_path["/path/to/project2"], mock_project2)

    def test_reset_path_to_project_map_empty(self):
        """Test _ResetPathToProjectMap with empty list."""
        cmd = command.Command()

        cmd._ResetPathToProjectMap([])

        self.assertEqual(len(cmd._by_path), 0)


@pytest.mark.unit
class TestCommandUpdatePathToProjectMap(unittest.TestCase):
    """Tests for Command._UpdatePathToProjectMap method."""

    def test_update_path_to_project_map(self):
        """Test _UpdatePathToProjectMap updates mapping."""
        cmd = command.Command()
        cmd._by_path = {}

        mock_project = mock.Mock()
        mock_project.worktree = "/path/to/project"

        cmd._UpdatePathToProjectMap(mock_project)

        self.assertEqual(cmd._by_path["/path/to/project"], mock_project)


@pytest.mark.unit
class TestCommandGetProjectByPath(unittest.TestCase):
    """Tests for Command._GetProjectByPath method."""

    def test_get_project_by_path_exact_match(self):
        """Test _GetProjectByPath with exact path match."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"

        mock_project = mock.Mock()
        mock_project.worktree = "/repo/project"
        cmd._by_path = {"/repo/project": mock_project}

        with mock.patch("os.path.exists", return_value=True):
            result = cmd._GetProjectByPath(mock_manifest, "/repo/project")

        self.assertEqual(result, mock_project)

    def test_get_project_by_path_parent_directory(self):
        """Test _GetProjectByPath with parent directory."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"

        mock_project = mock.Mock()
        mock_project.worktree = "/repo/project"
        cmd._by_path = {"/repo/project": mock_project}

        with mock.patch("os.path.exists", return_value=True):
            result = cmd._GetProjectByPath(mock_manifest, "/repo/project/subdir")

        self.assertEqual(result, mock_project)

    def test_get_project_by_path_topdir(self):
        """Test _GetProjectByPath with topdir."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"

        mock_project = mock.Mock()
        mock_project.worktree = "/repo"
        cmd._by_path = {"/repo": mock_project}

        with mock.patch("os.path.exists", return_value=True):
            result = cmd._GetProjectByPath(mock_manifest, "/repo/unknown")

        self.assertEqual(result, mock_project)

    def test_get_project_by_path_not_found(self):
        """Test _GetProjectByPath when project not found."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"
        cmd._by_path = {}

        with mock.patch("os.path.exists", return_value=True):
            result = cmd._GetProjectByPath(mock_manifest, "/repo/unknown")

        self.assertIsNone(result)

    def test_get_project_by_path_nonexistent(self):
        """Test _GetProjectByPath with non-existent path."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"

        mock_project = mock.Mock()
        mock_project.worktree = "/repo/project"
        cmd._by_path = {"/repo/project": mock_project}

        with mock.patch("os.path.exists", return_value=False):
            result = cmd._GetProjectByPath(mock_manifest, "/repo/project")

        self.assertEqual(result, mock_project)


@pytest.mark.unit
class TestCommandGetProjects(unittest.TestCase):
    """Tests for Command.GetProjects method."""

    def test_get_projects_no_args_no_filter(self):
        """Test GetProjects with no arguments returns all projects."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.projects = []

        mock_project1 = mock.Mock()
        mock_project1.Exists = True
        mock_project1.sync_s = False
        mock_project1.MatchesGroups.return_value = True
        mock_project1.GetDerivedSubprojects.return_value = []
        mock_project1.relpath = "project1"

        mock_project2 = mock.Mock()
        mock_project2.Exists = True
        mock_project2.sync_s = False
        mock_project2.MatchesGroups.return_value = True
        mock_project2.GetDerivedSubprojects.return_value = []
        mock_project2.relpath = "project2"

        mock_manifest.projects = [mock_project1, mock_project2]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.GetProjects([])

        self.assertEqual(len(result), 2)
        self.assertIn(mock_project1, result)
        self.assertIn(mock_project2, result)

    def test_get_projects_with_groups_filter(self):
        """Test GetProjects filters by groups."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project1 = mock.Mock()
        mock_project1.Exists = True
        mock_project1.sync_s = False
        mock_project1.MatchesGroups.return_value = True
        mock_project1.GetDerivedSubprojects.return_value = []
        mock_project1.relpath = "project1"

        mock_project2 = mock.Mock()
        mock_project2.Exists = True
        mock_project2.sync_s = False
        mock_project2.MatchesGroups.return_value = False
        mock_project2.GetDerivedSubprojects.return_value = []
        mock_project2.relpath = "project2"

        mock_manifest.projects = [mock_project1, mock_project2]
        mock_manifest.GetGroupsStr.return_value = "test-group"
        cmd.manifest = mock_manifest

        result = cmd.GetProjects([])

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project1, result)

    def test_get_projects_with_missing_ok(self):
        """Test GetProjects with missing_ok=True."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project = mock.Mock()
        mock_project.Exists = False
        mock_project.sync_s = False
        mock_project.MatchesGroups.return_value = True
        mock_project.GetDerivedSubprojects.return_value = []
        mock_project.relpath = "project1"

        mock_manifest.projects = [mock_project]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.GetProjects([], missing_ok=True)

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project, result)

    def test_get_projects_with_submodules_ok(self):
        """Test GetProjects with submodules_ok=True."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_subproject = mock.Mock()
        mock_subproject.Exists = True
        mock_subproject.MatchesGroups.return_value = True
        mock_subproject.relpath = "subproject"
        mock_subproject.name = "subproject"

        mock_project = mock.Mock()
        mock_project.Exists = True
        mock_project.sync_s = True
        mock_project.MatchesGroups.return_value = True
        mock_project.GetDerivedSubprojects.return_value = [mock_subproject]
        mock_project.relpath = "project1"

        mock_manifest.projects = [mock_project]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.GetProjects([], submodules_ok=True)

        self.assertGreater(len(result), 0)

    def test_get_projects_by_name(self):
        """Test GetProjects with project name argument."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project = mock.Mock()
        mock_project.Exists = True
        mock_project.MatchesGroups.return_value = True
        mock_project.relpath = "project1"
        mock_project.name = "project1"

        mock_manifest.projects = [mock_project]
        mock_manifest.GetProjectsWithName.return_value = [mock_project]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.GetProjects(["project1"])

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project, result)

    def test_get_projects_by_path(self):
        """Test GetProjects with path argument."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.topdir = "/repo"

        mock_project = mock.Mock()
        mock_project.Exists = True
        mock_project.MatchesGroups.return_value = True
        mock_project.worktree = "/repo/project1"
        mock_project.relpath = "project1"
        mock_project.Derived = False
        mock_project.sync_s = False
        mock_project.GetDerivedSubprojects.return_value = []

        mock_manifest.projects = [mock_project]
        mock_manifest.GetProjectsWithName.return_value = []
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest
        cmd._by_path = {"/repo/project1": mock_project}

        with mock.patch("os.path.abspath", return_value="/repo/project1"):
            result = cmd.GetProjects(["/repo/project1"])

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project, result)

    def test_get_projects_not_found(self):
        """Test GetProjects raises NoSuchProjectError."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_manifest.projects = []
        mock_manifest.GetProjectsWithName.return_value = []
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest
        cmd._by_path = {}

        with mock.patch("os.path.abspath", return_value="/repo/unknown"):
            with self.assertRaises(NoSuchProjectError):
                cmd.GetProjects(["unknown"])

    def test_get_projects_missing_not_ok(self):
        """Test GetProjects raises when project doesn't exist."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project = mock.Mock()
        mock_project.Exists = False
        mock_project.MatchesGroups.return_value = True
        mock_project.RelPath.return_value = "project1"

        mock_manifest.projects = []
        mock_manifest.GetProjectsWithName.return_value = [mock_project]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        with self.assertRaises(NoSuchProjectError):
            cmd.GetProjects(["project1"], missing_ok=False)

    def test_get_projects_group_mismatch(self):
        """Test GetProjects raises error when project doesn't match groups."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project = mock.Mock()
        mock_project.Exists = True
        mock_project.MatchesGroups.return_value = False

        mock_manifest.projects = []
        mock_manifest.GetProjectsWithName.return_value = [mock_project]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        # When MatchesGroups returns False, the project is filtered out in the
        # list comprehension, so NoSuchProjectError is raised (not InvalidProjectGroupsError)
        with self.assertRaises(NoSuchProjectError):
            cmd.GetProjects(["project1"])


@pytest.mark.unit
class TestCommandFindProjects(unittest.TestCase):
    """Tests for Command.FindProjects method."""

    def test_find_projects_by_name_pattern(self):
        """Test FindProjects with name pattern."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project1 = mock.Mock()
        mock_project1.name = "test-project"
        mock_project1.relpath = "test/project"
        mock_project1.RelPath.return_value = "test/project"
        mock_project1.Exists = True
        mock_project1.sync_s = False
        mock_project1.MatchesGroups.return_value = True
        mock_project1.GetDerivedSubprojects.return_value = []
        mock_project1.manifest.path_prefix = ""

        mock_project2 = mock.Mock()
        mock_project2.name = "other-project"
        mock_project2.relpath = "other/project"
        mock_project2.RelPath.return_value = "other/project"
        mock_project2.Exists = True
        mock_project2.sync_s = False
        mock_project2.MatchesGroups.return_value = True
        mock_project2.GetDerivedSubprojects.return_value = []
        mock_project2.manifest.path_prefix = ""

        mock_manifest.projects = [mock_project1, mock_project2]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.FindProjects(["test"])

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project1, result)

    def test_find_projects_inverse(self):
        """Test FindProjects with inverse=True."""
        cmd = command.Command()
        mock_manifest = mock.Mock()

        mock_project1 = mock.Mock()
        mock_project1.name = "test-project"
        mock_project1.relpath = "test/project"
        mock_project1.RelPath.return_value = "test/project"
        mock_project1.Exists = True
        mock_project1.sync_s = False
        mock_project1.MatchesGroups.return_value = True
        mock_project1.GetDerivedSubprojects.return_value = []
        mock_project1.manifest.path_prefix = ""

        mock_project2 = mock.Mock()
        mock_project2.name = "other-project"
        mock_project2.relpath = "other/project"
        mock_project2.RelPath.return_value = "other/project"
        mock_project2.Exists = True
        mock_project2.sync_s = False
        mock_project2.MatchesGroups.return_value = True
        mock_project2.GetDerivedSubprojects.return_value = []
        mock_project2.manifest.path_prefix = ""

        mock_manifest.projects = [mock_project1, mock_project2]
        mock_manifest.GetGroupsStr.return_value = "default"
        cmd.manifest = mock_manifest

        result = cmd.FindProjects(["test"], inverse=True)

        self.assertEqual(len(result), 1)
        self.assertIn(mock_project2, result)


@pytest.mark.unit
class TestCommandManifestList(unittest.TestCase):
    """Tests for Command.ManifestList method."""

    def test_manifest_list_default(self):
        """Test ManifestList with default options."""
        cmd = command.Command()
        mock_outer_manifest = mock.Mock()
        mock_outer_manifest.all_children = []
        cmd.outer_manifest = mock_outer_manifest
        cmd.manifest = mock.Mock()

        mock_opt = mock.Mock()
        mock_opt.outer_manifest = True
        mock_opt.this_manifest_only = False

        result = list(cmd.ManifestList(mock_opt))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], mock_outer_manifest)

    def test_manifest_list_this_manifest_only(self):
        """Test ManifestList with this_manifest_only=True."""
        cmd = command.Command()
        mock_manifest = mock.Mock()
        mock_manifest.all_children = []
        cmd.manifest = mock_manifest
        cmd.outer_manifest = mock.Mock()

        mock_opt = mock.Mock()
        mock_opt.outer_manifest = True
        mock_opt.this_manifest_only = True

        result = list(cmd.ManifestList(mock_opt))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], mock_manifest)

    def test_manifest_list_with_children(self):
        """Test ManifestList includes children."""
        cmd = command.Command()
        mock_child1 = mock.Mock()
        mock_child2 = mock.Mock()
        mock_outer_manifest = mock.Mock()
        mock_outer_manifest.all_children = [mock_child1, mock_child2]
        cmd.outer_manifest = mock_outer_manifest
        cmd.manifest = mock.Mock()

        mock_opt = mock.Mock()
        mock_opt.outer_manifest = True
        mock_opt.this_manifest_only = False

        result = list(cmd.ManifestList(mock_opt))

        self.assertEqual(len(result), 3)
        self.assertIn(mock_outer_manifest, result)
        self.assertIn(mock_child1, result)
        self.assertIn(mock_child2, result)


@pytest.mark.unit
class TestInteractiveCommand(unittest.TestCase):
    """Tests for InteractiveCommand class."""

    def test_interactive_command_want_pager(self):
        """Test that InteractiveCommand.WantPager returns False."""
        cmd = command.InteractiveCommand()
        self.assertFalse(cmd.WantPager(None))

    def test_interactive_command_inherits_from_command(self):
        """Test that InteractiveCommand inherits from Command."""
        cmd = command.InteractiveCommand()
        self.assertIsInstance(cmd, command.Command)


@pytest.mark.unit
class TestPagedCommand(unittest.TestCase):
    """Tests for PagedCommand class."""

    def test_paged_command_want_pager(self):
        """Test that PagedCommand.WantPager returns True."""
        from kanon_cli.repo.command import PagedCommand

        cmd = PagedCommand()
        self.assertTrue(cmd.WantPager(None))

    def test_paged_command_inherits_from_command(self):
        """Test that PagedCommand inherits from Command."""
        from kanon_cli.repo.command import PagedCommand

        cmd = PagedCommand()
        self.assertIsInstance(cmd, command.Command)


@pytest.mark.unit
class TestMirrorSafeCommand(unittest.TestCase):
    """Tests for MirrorSafeCommand class."""

    def test_mirror_safe_command_exists(self):
        """Test that MirrorSafeCommand class exists."""
        self.assertTrue(hasattr(command, "MirrorSafeCommand"))

    def test_mirror_safe_command_is_class(self):
        """Test that MirrorSafeCommand is a class."""
        self.assertTrue(isinstance(command.MirrorSafeCommand, type))
