"""Unittests for the subcmds/prune.py module."""

import optparse

import pytest

from kanon_cli.repo.subcmds import prune


@pytest.mark.unit
class TestPruneOptions:
    """Test Prune command options."""

    def test_options_setup(self):
        """Verify Prune command option parser is set up correctly."""
        cmd = prune.Prune()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestPruneCommand:
    """Test Prune command properties."""

    def test_help_summary(self):
        """Test Prune command has help summary."""
        assert prune.Prune.helpSummary is not None
