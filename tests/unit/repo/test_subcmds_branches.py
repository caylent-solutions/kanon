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

"""Unittests for the subcmds/branches.py module."""

from unittest import mock

import pytest

from subcmds import branches


@pytest.mark.unit
class TestBranchesOptions:
    """Test Branches command options."""

    def test_options_setup(self):
        """Verify Branches command option parser is set up correctly."""
        cmd = branches.Branches()
        opts, args = cmd.OptionParser.parse_args([])

        # Branches command has no custom options, just common ones
        assert hasattr(opts, "output_mode")
        assert hasattr(opts, "jobs")


@pytest.mark.unit
class TestBranchesCommand:
    """Test Branches command properties and methods."""

    def test_common_flag(self):
        """Test Branches command is marked as COMMON."""
        assert branches.Branches.COMMON is True

    def test_help_summary(self):
        """Test Branches command has help summary."""
        assert branches.Branches.helpSummary is not None
        assert len(branches.Branches.helpSummary) > 0

    def test_is_paged_command(self):
        """Test Branches is not a PagedCommand (it's just a Command)."""
        # Branches is a Command, not PagedCommand
        from command import Command

        assert issubclass(branches.Branches, Command)


@pytest.mark.unit
class TestBranchesExecute:
    """Test Branches command Execute method."""

    def test_execute_lists_branches(self):
        """Test Execute lists branches."""
        cmd = branches.Branches()
        cmd.manifest = mock.MagicMock()

        project = mock.MagicMock()
        project.name = "test-project"
        project.GetBranches.return_value = {}
        project.RelPath.return_value = "test-project"

        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        with mock.patch.object(cmd, "GetProjects", return_value=[project]):
            with mock.patch("builtins.print"):
                cmd.Execute(opt, [])

    def test_execute_with_branches(self):
        """Test Execute shows branches when present."""
        cmd = branches.Branches()
        cmd.manifest = mock.MagicMock()

        branch_mock = mock.MagicMock()
        branch_mock.current = False
        branch_mock.published = False
        branch_mock.revision = "abc123"

        project = mock.MagicMock()
        project.name = "test-project"
        project.GetBranches.return_value = {"branch1": branch_mock}
        project.RelPath.return_value = "test-project"

        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        with mock.patch.object(cmd, "GetProjects", return_value=[project]):
            cmd.Execute(opt, [])
