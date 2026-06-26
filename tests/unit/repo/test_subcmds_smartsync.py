"""Unittests for the subcmds/smartsync.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import smartsync


@pytest.mark.unit
class TestSmartsyncOptions:
    """Test Smartsync command options."""

    def test_options_setup(self):
        """Verify Smartsync command option parser is set up correctly."""
        cmd = smartsync.Smartsync()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestSmartsyncCommand:
    """Test Smartsync command properties."""

    def test_help_summary(self):
        """Test Smartsync command has help summary."""
        assert smartsync.Smartsync.helpSummary is not None
