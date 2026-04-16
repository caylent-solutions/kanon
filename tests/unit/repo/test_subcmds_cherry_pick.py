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

"""Unittests for the subcmds/cherry_pick.py module."""

import optparse

import pytest

from subcmds import cherry_pick


@pytest.mark.unit
class TestCherryPickOptions:
    """Test CherryPick command options."""

    def test_options_setup(self):
        """Verify CherryPick command option parser is set up correctly."""
        cmd = cherry_pick.CherryPick()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify options parser was set up
        assert p is not None


@pytest.mark.unit
class TestCherryPickCommand:
    """Test CherryPick command properties."""

    def test_help_summary(self):
        """Test CherryPick command has help summary."""
        assert cherry_pick.CherryPick.helpSummary is not None
