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

"""Unit tests for subcmds/download.py coverage."""

import pytest

from subcmds.download import CHANGE_RE


class TestDownloadCommand:
    """Test Download command."""

    @pytest.mark.unit
    def test_change_re_matches_change_only(self):
        """Test CHANGE_RE matches change number only."""
        match = CHANGE_RE.match("12345")
        assert match is not None
        assert match.group(1) == "12345"
        assert match.group(2) is None

    @pytest.mark.unit
    def test_change_re_matches_change_with_patchset(self):
        """Test CHANGE_RE matches change/patchset."""
        match = CHANGE_RE.match("12345/3")
        assert match is not None
        assert match.group(1) == "12345"
        assert match.group(2) == "3"

    @pytest.mark.unit
    def test_change_re_matches_change_with_dash(self):
        """Test CHANGE_RE matches change-patchset."""
        match = CHANGE_RE.match("12345-2")
        assert match is not None
        assert match.group(1) == "12345"
        assert match.group(2) == "2"

    @pytest.mark.unit
    def test_change_re_matches_change_with_dot(self):
        """Test CHANGE_RE matches change.patchset."""
        match = CHANGE_RE.match("12345.4")
        assert match is not None
        assert match.group(1) == "12345"
        assert match.group(2) == "4"

    @pytest.mark.unit
    def test_change_re_no_match_invalid(self):
        """Test CHANGE_RE doesn't match invalid input."""
        assert CHANGE_RE.match("invalid") is None
        assert CHANGE_RE.match("0") is None
        assert CHANGE_RE.match("012345") is None
