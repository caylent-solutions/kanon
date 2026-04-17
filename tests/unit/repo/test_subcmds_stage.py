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

"""Unittests for the subcmds/stage.py module."""

import pytest

from kanon_cli.repo.subcmds import stage


@pytest.mark.unit
class TestStageOptions:
    """Test Stage command options."""

    def test_options_setup(self):
        """Verify Stage command option parser is set up correctly."""
        cmd = stage.Stage()
        opts, args = cmd.OptionParser.parse_args([])

        # Verify options parser was set up
        assert opts is not None


@pytest.mark.unit
class TestStageCommand:
    """Test Stage command properties."""

    def test_help_summary(self):
        """Test Stage command has help summary."""
        assert stage.Stage.helpSummary is not None
