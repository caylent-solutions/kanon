"""Unittests for the subcmds/selfupdate.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import selfupdate


@pytest.mark.unit
class TestSelfupdateOptions:
    """Test Selfupdate command options."""

    def test_options_setup(self):
        """Verify Selfupdate command option parser is set up correctly."""
        cmd = selfupdate.Selfupdate()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestSelfupdateCommand:
    """Test Selfupdate command properties."""

    def test_help_summary(self):
        """Test Selfupdate command has help summary."""
        assert selfupdate.Selfupdate.helpSummary is not None
