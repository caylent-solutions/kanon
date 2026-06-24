"""Unittests for the subcmds/start.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import start


@pytest.mark.unit
class TestStartOptions:
    """Test Start command options."""

    def test_options_setup(self):
        """Verify Start command option parser is set up correctly."""
        cmd = start.Start()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestStartCommand:
    """Test Start command properties."""

    def test_help_summary(self):
        """Test Start command has help summary."""
        assert start.Start.helpSummary is not None
