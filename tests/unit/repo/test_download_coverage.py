"""Unit tests for subcmds/download.py coverage."""

import pytest

from kanon_cli.repo.subcmds.download import CHANGE_RE


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
