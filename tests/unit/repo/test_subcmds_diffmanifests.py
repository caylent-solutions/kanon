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

"""Unittests for the subcmds/diffmanifests.py module."""

import pytest

from kanon_cli.repo.subcmds import diffmanifests


@pytest.mark.unit
class TestDiffManifestsOptions:
    """Test DiffManifests command options."""

    def test_options_setup(self):
        """Verify DiffManifests command option parser is set up correctly."""
        cmd = diffmanifests.Diffmanifests()
        opts, args = cmd.OptionParser.parse_args([])

        # Verify default option values
        assert opts.raw is None or opts.raw is False
        assert not hasattr(opts, "pretty_format") or opts.pretty_format is None

    def test_options_raw(self):
        """Test parsing --raw option."""
        cmd = diffmanifests.Diffmanifests()
        opts, args = cmd.OptionParser.parse_args(["--raw"])
        assert opts.raw is True

    def test_options_pretty_format(self):
        """Test parsing --pretty-format option."""
        cmd = diffmanifests.Diffmanifests()
        opts, args = cmd.OptionParser.parse_args(["--pretty-format=%h %s"])
        assert opts.pretty_format == "%h %s"


@pytest.mark.unit
class TestDiffManifestsCommand:
    """Test DiffManifests command properties."""

    def test_common_flag(self):
        """Test DiffManifests command is marked as COMMON."""
        assert diffmanifests.Diffmanifests.COMMON is True

    def test_help_summary(self):
        """Test DiffManifests command has help summary."""
        assert diffmanifests.Diffmanifests.helpSummary is not None


@pytest.mark.unit
class TestDiffManifestsValidateOptions:
    """Test DiffManifests ValidateOptions method."""

    def test_validate_options_requires_two_manifests(self):
        """Test ValidateOptions requires at least one manifest argument."""
        cmd = diffmanifests.Diffmanifests()
        opts, args = cmd.OptionParser.parse_args([])

        # Should raise because no manifests provided
        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opts, args)

    def test_validate_options_with_two_manifests(self):
        """Test ValidateOptions passes with two manifests."""
        cmd = diffmanifests.Diffmanifests()
        opts, args = cmd.OptionParser.parse_args(["manifest1.xml", "manifest2.xml"])

        # Should not raise
        cmd.ValidateOptions(opts, args)
