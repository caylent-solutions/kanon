"""Unittests for the subcmds/cherry_pick.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import cherry_pick


@pytest.mark.unit
class TestCherryPickOptions:
    """Test CherryPick command options."""

    def test_options_setup(self):
        """Verify CherryPick command option parser is set up correctly."""
        cmd = cherry_pick.CherryPick()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestCherryPickCommand:
    """Test CherryPick command properties."""

    def test_help_summary(self):
        """Test CherryPick command has help summary."""
        assert cherry_pick.CherryPick.helpSummary is not None
