"""Unittests for the subcmds/list.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import list


@pytest.mark.unit
class TestListOptions:
    """Test List command options."""

    def test_options_setup(self):
        """Verify List command option parser is set up correctly."""
        cmd = list.List()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestListCommand:
    """Test List command properties."""

    def test_help_summary(self):
        """Test List command has help summary."""
        assert list.List.helpSummary is not None
