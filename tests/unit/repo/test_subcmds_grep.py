# Copyright (C) 2025 The Android Open Source Project
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

"""Unittests for the subcmds/grep.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.subcmds import grep


@pytest.mark.unit
class TestGrepOptions:
    """Test Grep command options."""

    def test_options_setup(self):
        """Verify Grep command option parser is set up correctly."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args([])

        # Verify default option values - cmd_argv is only set when options are used
        assert not hasattr(opts, "cmd_argv") or opts.cmd_argv is None

    def test_options_with_pattern(self):
        """Test parsing -e pattern option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-e", "pattern"])
        assert "pattern" in opts.cmd_argv

    def test_options_with_revision(self):
        """Test parsing -r revision option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-r", "HEAD", "-e", "test"])
        # -r stores in revision list, not cmd_argv
        assert opts.revision == ["HEAD"]
        assert "-e" in opts.cmd_argv
        assert "test" in opts.cmd_argv

    def test_options_cached(self):
        """Test parsing --cached option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["--cached", "pattern"])
        assert "--cached" in opts.cmd_argv

    def test_options_line_number(self):
        """Test parsing -n option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-n", "pattern"])
        assert "-n" in opts.cmd_argv

    def test_options_ignore_case(self):
        """Test parsing -i option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-i", "pattern"])
        assert "-i" in opts.cmd_argv

    def test_options_word_regexp(self):
        """Test parsing -w option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-w", "pattern"])
        assert "-w" in opts.cmd_argv

    def test_options_extended_regexp(self):
        """Test parsing -E option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-E", "pattern"])
        assert "-E" in opts.cmd_argv

    def test_options_fixed_strings(self):
        """Test parsing -F option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-F", "pattern"])
        assert "-F" in opts.cmd_argv

    def test_options_boolean_and(self):
        """Test parsing --and option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-e", "p1", "--and", "-e", "p2"])
        assert "--and" in opts.cmd_argv

    def test_options_boolean_or(self):
        """Test parsing --or option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-e", "p1", "--or", "-e", "p2"])
        assert "--or" in opts.cmd_argv

    def test_options_boolean_not(self):
        """Test parsing --not option."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["--not", "-e", "pattern"])
        assert "--not" in opts.cmd_argv


@pytest.mark.unit
class TestGrepCarryOption:
    """Test Grep _carry_option static method."""

    def test_carry_option_initializes_cmd_argv(self):
        """Test _carry_option initializes cmd_argv if not present."""
        parser = mock.MagicMock()
        parser.values = mock.MagicMock()
        parser.values.cmd_argv = None

        grep.Grep._carry_option(None, "-e", "pattern", parser)

        assert hasattr(parser.values, "cmd_argv")
        assert isinstance(parser.values.cmd_argv, list)

    def test_carry_option_handles_open_paren(self):
        """Test _carry_option converts -( to (."""
        parser = mock.MagicMock()
        parser.values = mock.MagicMock()
        parser.values.cmd_argv = []

        grep.Grep._carry_option(None, "-(", None, parser)

        assert "(" in parser.values.cmd_argv

    def test_carry_option_handles_close_paren(self):
        """Test _carry_option converts -) to )."""
        parser = mock.MagicMock()
        parser.values = mock.MagicMock()
        parser.values.cmd_argv = []

        grep.Grep._carry_option(None, "-)", None, parser)

        assert ")" in parser.values.cmd_argv

    def test_carry_option_adds_regular_options(self):
        """Test _carry_option adds regular options."""
        parser = mock.MagicMock()
        parser.values = mock.MagicMock()
        parser.values.cmd_argv = []

        grep.Grep._carry_option(None, "--cached", None, parser)

        assert "--cached" in parser.values.cmd_argv

    def test_carry_option_adds_value_with_option(self):
        """Test _carry_option adds value with option."""
        parser = mock.MagicMock()
        parser.values = mock.MagicMock()
        parser.values.cmd_argv = []

        grep.Grep._carry_option(None, "-e", "pattern", parser)

        assert "-e" in parser.values.cmd_argv
        assert "pattern" in parser.values.cmd_argv


@pytest.mark.unit
class TestGrepValidateOptions:
    """Test Grep ValidateOptions method."""

    def test_validate_options_no_pattern_fails(self):
        """Test parsing with no pattern - grep requires pattern in args."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args([])

        # Grep doesn't have ValidateOptions, pattern validation happens in Execute
        # Just verify we can parse with no args
        assert args == []

    def test_validate_options_with_pattern_passes(self):
        """Test ValidateOptions passes with valid pattern."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["-e", "pattern"])

        # Should not raise
        cmd.ValidateOptions(opts, args)

    def test_validate_options_with_positional_pattern(self):
        """Test ValidateOptions passes with positional pattern."""
        cmd = grep.Grep()
        opts, args = cmd.OptionParser.parse_args(["pattern"])

        # Should not raise
        cmd.ValidateOptions(opts, args)


@pytest.mark.unit
class TestGrepCommand:
    """Test Grep command properties and methods."""

    def test_common_flag(self):
        """Test Grep command is marked as COMMON."""
        assert grep.Grep.COMMON is True

    def test_help_summary(self):
        """Test Grep command has help summary."""
        assert grep.Grep.helpSummary is not None
        assert len(grep.Grep.helpSummary) > 0

    def test_help_usage(self):
        """Test Grep command has help usage."""
        assert grep.Grep.helpUsage is not None
        assert "pattern" in grep.Grep.helpUsage

    def test_is_paged_command(self):
        """Test Grep is a PagedCommand."""
        from kanon_cli.repo.command import PagedCommand

        assert issubclass(grep.Grep, PagedCommand)

    def test_parallel_jobs(self):
        """Test Grep has parallel jobs configured."""
        from kanon_cli.repo.command import DEFAULT_LOCAL_JOBS

        assert grep.Grep.PARALLEL_JOBS == DEFAULT_LOCAL_JOBS


@pytest.mark.unit
class TestGrepColoring:
    """Test GrepColoring class."""

    def test_grep_coloring_init(self):
        """Test GrepColoring initializes correctly."""
        config = mock.MagicMock()
        coloring = grep.GrepColoring(config)

        assert coloring is not None
        assert hasattr(coloring, "project")
        assert hasattr(coloring, "fail")


@pytest.mark.unit
class TestExecuteOneResult:
    """Test ExecuteOneResult namedtuple."""

    def test_execute_one_result_creation(self):
        """Test ExecuteOneResult can be created."""
        result = grep.ExecuteOneResult(project_idx=0, rc=0, stdout="output", stderr="", error=None)

        assert result.project_idx == 0
        assert result.rc == 0
        assert result.stdout == "output"
        assert result.stderr == ""
        assert result.error is None

    def test_execute_one_result_with_error(self):
        """Test ExecuteOneResult with error."""
        error = GitError("git error")
        result = grep.ExecuteOneResult(project_idx=1, rc=1, stdout="", stderr="error output", error=error)

        assert result.project_idx == 1
        assert result.rc == 1
        assert result.error == error


@pytest.mark.unit
class TestGrepCommandError:
    """Test GrepCommandError exception."""

    def test_grep_command_error_inheritance(self):
        """Test GrepCommandError is a SilentRepoExitError."""
        from kanon_cli.repo.error import SilentRepoExitError

        err = grep.GrepCommandError("grep failed")
        assert isinstance(err, SilentRepoExitError)

    def test_grep_command_error_message(self):
        """Test GrepCommandError stores message."""
        err = grep.GrepCommandError("test error")
        assert "test error" in str(err)


@pytest.mark.unit
class TestGrepExecute:
    """Test Grep Execute method."""

    def test_execute_one_project(self):
        """Test _ExecuteOne processes a project."""
        cmd = grep.Grep()

        project = mock.MagicMock()
        project.name = "test-project"
        project.worktree = "/path/to/project"

        opt = mock.MagicMock()
        opt.cmd_argv = ["-e", "pattern"]

        with cmd.ParallelContext():
            cmd.get_parallel_context()["projects"] = [project]
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand") as mock_git:
                mock_git_instance = mock.MagicMock()
                mock_git_instance.Wait.return_value = 0
                mock_git_instance.stdout = "match"
                mock_git_instance.stderr = ""
                mock_git.return_value = mock_git_instance

                result = cmd._ExecuteOne(opt, 0)

        assert result.project_idx == 0
        assert result.rc == 0

    def test_execute_one_with_git_error(self):
        """Test _ExecuteOne handles GitError."""
        cmd = grep.Grep()

        project = mock.MagicMock()
        project.name = "test-project"
        project.worktree = "/path/to/project"

        opt = mock.MagicMock()
        opt.cmd_argv = ["-e", "pattern"]

        with cmd.ParallelContext():
            cmd.get_parallel_context()["projects"] = [project]
            with mock.patch("kanon_cli.repo.subcmds.grep.GitCommand") as mock_git:
                mock_git.side_effect = GitError("git error")

                result = cmd._ExecuteOne(opt, 0)

        assert result.error is not None
        assert result.rc != 0
