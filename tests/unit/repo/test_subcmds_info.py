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

"""Unittests for the subcmds/info.py module."""

import optparse
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import info


@pytest.mark.unit
class TestInfoOptions:
    """Test Info command options."""

    def test_options_setup(self):
        """Verify Info command option parser is set up correctly."""
        cmd = info.Info()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify default option values
        assert opts.all is None
        assert opts.overview is None
        assert opts.current_branch is None
        assert opts.local is None

    def test_options_diff(self):
        """Test parsing --diff option."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["-d"])
        assert opts.all is True

    def test_options_overview(self):
        """Test parsing --overview option."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["-o"])
        assert opts.overview is True

    def test_options_current_branch(self):
        """Test parsing --current-branch option."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["-c"])
        assert opts.current_branch is True

    def test_options_no_current_branch(self):
        """Test parsing --no-current-branch option."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["--no-current-branch"])
        assert opts.current_branch is False

    def test_options_local_only(self):
        """Test parsing --local-only option."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["-l"])
        assert opts.local is True

    def test_options_combined(self):
        """Test parsing combined options."""
        cmd = info.Info()
        opts, args = cmd.OptionParser.parse_args(["-d", "-o", "-c"])
        assert opts.all is True
        assert opts.overview is True
        assert opts.current_branch is True


@pytest.mark.unit
class TestInfoCommand:
    """Test Info command properties and methods."""

    def test_common_flag(self):
        """Test Info command is marked as COMMON."""
        assert info.Info.COMMON is True

    def test_help_summary(self):
        """Test Info command has help summary."""
        assert info.Info.helpSummary is not None
        assert len(info.Info.helpSummary) > 0

    def test_help_usage(self):
        """Test Info command has help usage."""
        assert info.Info.helpUsage is not None
        assert "[<project>...]" in info.Info.helpUsage

    def test_is_paged_command(self):
        """Test Info is a PagedCommand."""
        from kanon_cli.repo.command import PagedCommand

        assert issubclass(info.Info, PagedCommand)


@pytest.mark.unit
class TestInfoExecute:
    """Test Info command Execute method."""

    def test_execute_initializes_coloring(self):
        """Test Execute initializes coloring objects."""
        cmd = info.Info()
        cmd.client = mock.MagicMock()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.outer_client = mock.MagicMock()
        cmd.manifest.manifestProject.config.GetBranch.return_value.merge = "main"
        cmd.manifest.GetGroupsStr.return_value = "default"
        cmd.manifest.default.revisionExpr = "refs/heads/main"
        cmd.manifest.superproject = None

        opt = mock.MagicMock()
        opt.this_manifest_only = True
        opt.overview = False
        opt.all = False

        with mock.patch.object(cmd, "GetProjects", return_value=[]):
            with mock.patch("sys.stdout"):
                cmd.Execute(opt, [])

        assert hasattr(cmd, "out")
        assert hasattr(cmd, "heading")
        assert hasattr(cmd, "headtext")

    def test_execute_uses_outer_manifest(self):
        """Test Execute uses outer manifest when not this_manifest_only."""
        cmd = info.Info()
        cmd.client = mock.MagicMock()
        inner_manifest = mock.MagicMock()
        outer_manifest = mock.MagicMock()
        inner_manifest.outer_client = outer_manifest
        outer_manifest.manifestProject.config.GetBranch.return_value.merge = "main"
        outer_manifest.GetGroupsStr.return_value = "default"
        outer_manifest.default.revisionExpr = "refs/heads/main"
        outer_manifest.superproject = None

        cmd.manifest = inner_manifest

        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.overview = False
        opt.all = False

        with mock.patch.object(cmd, "GetProjects", return_value=[]):
            with mock.patch("sys.stdout"):
                cmd.Execute(opt, [])

        assert cmd.manifest == outer_manifest

    def test_execute_handles_no_merge_branch(self):
        """Test Execute handles missing merge branch gracefully."""
        cmd = info.Info()
        cmd.client = mock.MagicMock()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.outer_client = mock.MagicMock()
        cmd.manifest.manifestProject.config.GetBranch.return_value.merge = None
        cmd.manifest.GetGroupsStr.return_value = "default"
        cmd.manifest.default.revisionExpr = "refs/heads/main"
        cmd.manifest.superproject = None

        opt = mock.MagicMock()
        opt.this_manifest_only = True
        opt.overview = False
        opt.all = False

        with mock.patch.object(cmd, "GetProjects", return_value=[]):
            with mock.patch("sys.stdout"):
                # Should not raise
                cmd.Execute(opt, [])

    def test_execute_with_projects(self):
        """Test Execute processes projects."""
        cmd = info.Info()
        cmd.client = mock.MagicMock()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.outer_client = mock.MagicMock()
        cmd.manifest.manifestProject.config.GetBranch.return_value.merge = "main"
        cmd.manifest.GetGroupsStr.return_value = "default"
        cmd.manifest.default.revisionExpr = "refs/heads/main"
        cmd.manifest.superproject = None

        project = mock.MagicMock()
        project.name = "test-project"
        project.worktree = "/path/to/project"
        project.GetRevisionId.return_value = "abc123"
        project.CurrentBranch = "main"
        project.revisionExpr = "refs/heads/main"
        project.GetBranches.return_value = {}

        opt = mock.MagicMock()
        opt.this_manifest_only = True
        opt.overview = False
        opt.all = False

        with mock.patch.object(cmd, "GetProjects", return_value=[project]):
            with mock.patch("sys.stdout"):
                cmd.Execute(opt, [])


@pytest.mark.unit
class TestInfoColoring:
    """Test Info command coloring class."""

    def test_coloring_init(self):
        """Test _Coloring initializes correctly."""
        config = mock.MagicMock()
        coloring = info._Coloring(config)
        assert coloring is not None
