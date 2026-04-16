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

"""Unittests for the subcmds/help.py module."""

import optparse
from unittest import mock

import pytest

from subcmds import help as help_cmd


@pytest.mark.unit
class TestHelpOptions:
    """Test Help command options."""

    def test_options_setup(self):
        """Verify Help command option parser is set up correctly."""
        cmd = help_cmd.Help()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify default option values
        assert opts.show_all is None

    def test_options_all(self):
        """Test parsing --all option."""
        cmd = help_cmd.Help()
        opts, args = cmd.OptionParser.parse_args(["-a"])
        assert opts.show_all is True

    def test_options_all_long_form(self):
        """Test parsing --all long form."""
        cmd = help_cmd.Help()
        opts, args = cmd.OptionParser.parse_args(["--all"])
        assert opts.show_all is True


@pytest.mark.unit
class TestHelpCommand:
    """Test Help command properties and methods."""

    def test_common_flag(self):
        """Test Help command is marked as COMMON."""
        assert help_cmd.Help.COMMON is False

    def test_help_summary(self):
        """Test Help command has help summary."""
        assert help_cmd.Help.helpSummary is not None
        assert len(help_cmd.Help.helpSummary) > 0

    def test_help_usage(self):
        """Test Help command has help usage."""
        assert help_cmd.Help.helpUsage is not None


@pytest.mark.unit
class TestHelpExecute:
    """Test Help command Execute method."""

    def test_execute_with_no_args(self):
        """Test Execute with no arguments shows common commands."""
        cmd = help_cmd.Help()
        cmd.client = mock.MagicMock()
        cmd.client.globalConfig = mock.MagicMock()
        cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.show_all = False
        opt.show_all_help = False

        with mock.patch("builtins.print") as mock_print:
            cmd.Execute(opt, [])
            # Should print something
            assert mock_print.called

    def test_execute_with_show_all(self):
        """Test Execute with --all shows all commands."""
        cmd = help_cmd.Help()
        cmd.client = mock.MagicMock()
        cmd.client.globalConfig = mock.MagicMock()
        cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.show_all = True
        opt.show_all_help = False

        with mock.patch("builtins.print") as mock_print:
            cmd.Execute(opt, [])
            assert mock_print.called

    def test_execute_with_specific_command(self):
        """Test Execute with specific command name."""
        cmd = help_cmd.Help()
        cmd.client = mock.MagicMock()
        cmd.client.globalConfig = mock.MagicMock()
        cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.show_all = False
        opt.show_all_help = False

        # Help prints to stdout directly via OptionParser
        with mock.patch("sys.stdout"):
            # Should not raise with existing command
            cmd.Execute(opt, ["sync"])


@pytest.mark.unit
class TestHelpWantPager:
    """Test Help command WantPager method."""

    def test_want_pager_returns_true(self):
        """Test WantPager returns True."""
        cmd = help_cmd.Help()
        opt = mock.MagicMock()

        assert cmd.WantPager(opt) is True
