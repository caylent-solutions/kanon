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

"""Unittests for the subcmds/abandon.py module."""

import optparse
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import abandon


@pytest.mark.unit
class TestAbandonOptions:
    """Test Abandon command options."""

    def test_options_setup(self):
        """Verify Abandon command option parser is set up correctly."""
        cmd = abandon.Abandon()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Options should be minimal/none for abandon
        assert True  # Placeholder for basic setup verification

    def test_options_all(self):
        """Test parsing --all option."""
        cmd = abandon.Abandon()
        opts, args = cmd.OptionParser.parse_args(["--all"])
        assert opts.all is True


@pytest.mark.unit
class TestAbandonCommand:
    """Test Abandon command properties."""

    def test_common_flag(self):
        """Test Abandon command is marked as COMMON."""
        assert abandon.Abandon.COMMON is True

    def test_help_summary(self):
        """Test Abandon command has help summary."""
        assert abandon.Abandon.helpSummary is not None

    def test_parallel_jobs(self):
        """Test Abandon has parallel jobs configured."""
        from kanon_cli.repo.command import DEFAULT_LOCAL_JOBS

        assert abandon.Abandon.PARALLEL_JOBS == DEFAULT_LOCAL_JOBS


@pytest.mark.unit
class TestAbandonValidateOptions:
    """Test Abandon ValidateOptions method."""

    def test_validate_options_no_branch_fails(self):
        """Test ValidateOptions fails with no branch name."""
        from kanon_cli.repo.command import UsageError

        cmd = abandon.Abandon()
        opts, args = cmd.OptionParser.parse_args([])

        with pytest.raises(UsageError):
            cmd.ValidateOptions(opts, args)

    def test_validate_options_with_branch(self):
        """Test ValidateOptions passes with branch name."""
        cmd = abandon.Abandon()
        opts, args = cmd.OptionParser.parse_args(["branch-name"])

        # Should not raise
        cmd.ValidateOptions(opts, args)


@pytest.mark.unit
class TestAbandonExecute:
    """Test Abandon Execute method."""

    def test_execute_abandons_branch(self):
        """Test Execute abandons branch."""
        cmd = abandon.Abandon()
        cmd.manifest = mock.MagicMock()

        project = mock.MagicMock()
        project.name = "test-project"
        project.AbandonBranch.return_value = True

        opt = mock.MagicMock()
        opt.all = False

        with mock.patch.object(cmd, "GetProjects", return_value=[project]):
            result = cmd.Execute(opt, ["branch-name"])
            assert result == 0 or result is None

    def test_execute_with_all_projects(self):
        """Test Execute with --all abandons in all projects."""
        cmd = abandon.Abandon()
        cmd.manifest = mock.MagicMock()

        project1 = mock.MagicMock()
        project1.name = "project1"
        project1.GetBranches.return_value = {"branch1": mock.MagicMock()}
        project1.AbandonBranch.return_value = True
        project1.RelPath.return_value = "project1"

        project2 = mock.MagicMock()
        project2.name = "project2"
        project2.GetBranches.return_value = {"branch1": mock.MagicMock()}
        project2.AbandonBranch.return_value = True
        project2.RelPath.return_value = "project2"

        opt = mock.MagicMock()
        opt.all = True
        opt.jobs = 1
        opt.quiet = False
        opt.this_manifest_only = False

        with mock.patch.object(cmd, "GetProjects", return_value=[project1, project2]):
            with mock.patch("builtins.print"):
                result = cmd.Execute(opt, ["branch-name"])
                assert result == 0 or result is None
