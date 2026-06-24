"""Unittests for the subcmds/status.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import status


@pytest.mark.unit
class TestStatusOptions:
    """Test Status command options."""

    def test_options_setup(self):
        """Verify Status command option parser is set up correctly."""
        cmd = status.Status()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestStatusCommand:
    """Test Status command properties."""

    def test_help_summary(self):
        """Test Status command has help summary."""
        assert status.Status.helpSummary is not None
