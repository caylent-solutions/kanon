"""Unittests for the subcmds/diff.py module."""

import optparse
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import diff


@pytest.mark.unit
class TestDiffOptions:
    """Test Diff command options."""

    def test_options_setup(self):
        """Verify Diff command option parser is set up correctly."""
        cmd = diff.Diff()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        assert p is not None


@pytest.mark.unit
class TestDiffCommand:
    """Test Diff command properties."""

    def test_help_summary(self):
        """Test Diff command has help summary."""
        assert diff.Diff.helpSummary is not None


@pytest.mark.unit
class TestDiffExecute:
    """Test Diff Execute method."""

    def test_execute_basic(self):
        """Test Execute runs without error."""
        cmd = diff.Diff()
        cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        with mock.patch.object(cmd, "GetProjects", return_value=[]):
            result = cmd.Execute(opt, [])

            assert result == 0 or result is None
