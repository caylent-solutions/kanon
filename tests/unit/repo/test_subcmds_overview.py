"""Unittests for the subcmds/overview.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import overview


@pytest.mark.unit
class TestOverviewOptions:
    """Test Overview command options."""

    def test_options_setup(self):
        """Verify Overview command option parser is set up correctly."""
        cmd = overview.Overview()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestOverviewCommand:
    """Test Overview command properties."""

    def test_help_summary(self):
        """Test Overview command has help summary."""
        assert overview.Overview.helpSummary is not None
