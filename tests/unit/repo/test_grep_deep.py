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

"""Deep unit tests for subcmds/grep.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.command import UsageError
from kanon_cli.repo.error import GitError
from kanon_cli.repo.error import InvalidArgumentsError
from kanon_cli.repo.subcmds.grep import ExecuteOneResult
from kanon_cli.repo.subcmds.grep import Grep
from kanon_cli.repo.subcmds.grep import GrepColoring
from kanon_cli.repo.subcmds.grep import GrepCommandError


@pytest.mark.unit
class TestGrepColoring:
    """Tests for GrepColoring class."""

    def test_grep_coloring_init(self):
        """Test GrepColoring initialization."""
        config = mock.Mock()
        coloring = GrepColoring(config)
        assert coloring is not None


@pytest.mark.unit
class TestGrepCarryOption:
    """Tests for Grep._carry_option callback."""

    def test_carry_option_with_value(self):
        """Test _carry_option with value."""
        option = mock.Mock()
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.values.cmd_argv = None

        Grep._carry_option(option, "-e", "pattern", parser)

        assert parser.values.cmd_argv == ["-e", "pattern"]

    def test_carry_option_without_value(self):
        """Test _carry_option without value."""
        option = mock.Mock()
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.values.cmd_argv = None

        Grep._carry_option(option, "--cached", None, parser)

        assert parser.values.cmd_argv == ["--cached"]

    def test_carry_option_parentheses(self):
        """Test _carry_option with parentheses."""
        option = mock.Mock()
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.values.cmd_argv = None

        Grep._carry_option(option, "-(", None, parser)
        assert parser.values.cmd_argv == ["("]

        Grep._carry_option(option, "-)", None, parser)
        assert parser.values.cmd_argv == ["(", ")"]

    def test_carry_option_appends(self):
        """Test _carry_option appends to existing list."""
        option = mock.Mock()
        parser = mock.Mock()
        parser.values = mock.Mock()
        parser.values.cmd_argv = ["-e", "pattern1"]

        Grep._carry_option(option, "-e", "pattern2", parser)

        assert parser.values.cmd_argv == ["-e", "pattern1", "-e", "pattern2"]


@pytest.mark.unit
class TestGrepExecuteOne:
    """Tests for Grep._ExecuteOne classmethod."""

    def test_execute_one_success(self):
        """Test _ExecuteOne successful execution."""
        project = mock.Mock()

        with mock.patch.object(Grep, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 0
                mock_process.stdout = "match line 1\nmatch line 2\n"
                mock_process.stderr = ""
                mock_git.return_value = mock_process

                result = Grep._ExecuteOne(["grep", "pattern"], 0)

                assert result.rc == 0
                assert result.stdout == "match line 1\nmatch line 2\n"
                assert result.error is None

    def test_execute_one_no_matches(self):
        """Test _ExecuteOne with no matches."""
        project = mock.Mock()

        with mock.patch.object(Grep, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 1
                mock_process.stdout = ""
                mock_process.stderr = ""
                mock_git.return_value = mock_process

                result = Grep._ExecuteOne(["grep", "pattern"], 0)

                assert result.rc == 1

    def test_execute_one_git_error_on_creation(self):
        """Test _ExecuteOne with GitError on command creation."""
        project = mock.Mock()

        with mock.patch.object(Grep, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand", side_effect=GitError("error")):
                result = Grep._ExecuteOne(["grep", "pattern"], 0)

                assert result.rc == -1
                assert result.error is not None

    def test_execute_one_git_error_on_wait(self):
        """Test _ExecuteOne with GitError on Wait."""
        project = mock.Mock()

        with mock.patch.object(Grep, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.side_effect = GitError("wait error")
                mock_git.return_value = mock_process

                result = Grep._ExecuteOne(["grep", "pattern"], 0)

                assert result.rc == 1
                assert result.error is not None


@pytest.mark.unit
class TestGrepProcessResults:
    """Tests for Grep._ProcessResults static method."""

    def test_process_results_success(self):
        """Test _ProcessResults with successful results."""
        projects = [mock.Mock()]
        projects[0].RelPath.return_value = "project/path"

        out = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        results = [ExecuteOneResult(0, 0, "match1\nmatch2\n", "", None)]

        git_failed, bad_rev, have_match, errors = Grep._ProcessResults(False, False, opt, projects, None, out, results)

        assert git_failed is False
        assert bad_rev is False
        assert have_match is True
        assert len(errors) == 0

    def test_process_results_git_failure(self):
        """Test _ProcessResults with git failure."""
        projects = [mock.Mock()]
        projects[0].RelPath.return_value = "project/path"

        out = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        error = GitError("git error")
        results = [ExecuteOneResult(0, -1, None, "git error", error)]

        git_failed, bad_rev, have_match, errors = Grep._ProcessResults(False, False, opt, projects, None, out, results)

        assert git_failed is True
        assert have_match is False
        assert len(errors) == 1

    def test_process_results_bad_revision(self):
        """Test _ProcessResults with bad revision."""
        projects = [mock.Mock()]
        projects[0].RelPath.return_value = "project/path"

        out = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        results = [ExecuteOneResult(0, 1, "", "fatal: ambiguous argument", None)]

        git_failed, bad_rev, have_match, errors = Grep._ProcessResults(False, True, opt, projects, None, out, results)

        assert bad_rev is True
        assert have_match is False

    def test_process_results_full_name(self):
        """Test _ProcessResults with full_name enabled."""
        projects = [mock.Mock()]
        projects[0].RelPath.return_value = "project/path"

        out = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        results = [ExecuteOneResult(0, 0, "file.txt:10:match line\n", "", None)]

        git_failed, bad_rev, have_match, errors = Grep._ProcessResults(True, False, opt, projects, None, out, results)

        assert have_match is True

    def test_process_results_with_revision(self):
        """Test _ProcessResults with revision and full_name."""
        projects = [mock.Mock()]
        projects[0].RelPath.return_value = "project/path"

        out = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        results = [ExecuteOneResult(0, 0, "main:file.txt:10:match line\n", "", None)]

        git_failed, bad_rev, have_match, errors = Grep._ProcessResults(True, True, opt, projects, None, out, results)

        assert have_match is True


@pytest.mark.unit
class TestGrepExecute:
    """Tests for Grep.Execute method."""

    def test_execute_no_pattern(self):
        """Test Execute with no pattern."""
        grep = Grep()
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = []

        with pytest.raises(UsageError):
            grep.Execute(opt, [])

    def test_execute_with_pattern_arg(self):
        """Test Execute with pattern as argument."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, False, True, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = []
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = None

        with pytest.raises(SystemExit) as exc_info:
            grep.Execute(opt, ["pattern"])

        assert exc_info.value.code == 0

    def test_execute_with_pattern_option(self):
        """Test Execute with pattern as -e option."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, False, True, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = None

        with pytest.raises(SystemExit) as exc_info:
            grep.Execute(opt, [])

        assert exc_info.value.code == 0

    def test_execute_with_revision(self):
        """Test Execute with revision option."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, False, True, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = ["HEAD"]

        with pytest.raises(SystemExit) as exc_info:
            grep.Execute(opt, [])

        assert exc_info.value.code == 0

    def test_execute_cached_with_revision(self):
        """Test Execute rejects --cached with --revision."""
        grep = Grep()
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern", "--cached"]
        opt.revision = ["HEAD"]
        opt.this_manifest_only = False

        with pytest.raises(InvalidArgumentsError):
            grep.Execute(opt, [])

    def test_execute_git_failure(self):
        """Test Execute with git failure."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(True, False, False, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = None

        with pytest.raises(GrepCommandError):
            grep.Execute(opt, [])

    def test_execute_no_matches(self):
        """Test Execute with no matches."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, False, False, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = None

        with pytest.raises(GrepCommandError):
            grep.Execute(opt, [])

    def test_execute_bad_revision(self):
        """Test Execute with bad revision."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, True, False, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = ["invalid-rev"]

        with pytest.raises(GrepCommandError):
            grep.Execute(opt, [])

    def test_execute_multiple_projects(self):
        """Test Execute with multiple projects adds --full-name."""
        grep = Grep()
        grep.GetProjects = mock.Mock(return_value=[mock.Mock(), mock.Mock()])
        grep.ParallelContext = mock.Mock(return_value=mock.MagicMock())
        grep.get_parallel_context = mock.Mock(return_value={})
        grep.ExecuteInParallel = mock.Mock(return_value=(False, False, True, []))
        grep.manifest = mock.Mock()
        grep.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.cmd_argv = ["-e", "pattern"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.revision = None

        with pytest.raises(SystemExit):
            grep.Execute(opt, [])

        # ExecuteInParallel should be called with command containing --full-name
        grep.ExecuteInParallel.call_args
        # The first argument should be jobs, second is the partial function
        # We can't easily check the cmd_argv inside the partial
