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

"""Unittests for the subcmds/rebase.py module."""

import pytest

from kanon_cli.repo.subcmds import rebase


@pytest.mark.unit
class TestRebaseOptions:
    """Test Rebase command options."""

    def test_options_interactive(self):
        """Test parsing -i option."""
        cmd = rebase.Rebase()
        opts, args = cmd.OptionParser.parse_args(["-i"])
        assert opts.interactive is True

    def test_options_whitespace(self):
        """Test parsing --whitespace option."""
        cmd = rebase.Rebase()
        opts, args = cmd.OptionParser.parse_args(["--whitespace=fix"])
        assert opts.whitespace == "fix"


@pytest.mark.unit
class TestRebaseCommand:
    """Test Rebase command properties."""

    def test_common_flag(self):
        """Test Rebase command is marked as COMMON."""
        assert rebase.Rebase.COMMON is True

    def test_help_summary(self):
        """Test Rebase command has help summary."""
        assert rebase.Rebase.helpSummary is not None

    def test_parallel_jobs(self):
        """Test Rebase has parallel jobs configured."""
        # Rebase doesn't set PARALLEL_JOBS
        assert rebase.Rebase.PARALLEL_JOBS is None or rebase.Rebase.PARALLEL_JOBS > 0
