"""Unittests for the subcmds/rebase.py module."""

import pytest

from kanon_cli.repo.subcmds import rebase


@pytest.mark.unit
class TestRebaseOptions:
    """Test Rebase command options."""

    def test_options_interactive(self):
        """Test parsing -i option."""
        cmd = rebase.Rebase()
        opts, args = cmd.OptionParser.parse_args(["-i"])
        assert opts.interactive is True

    def test_options_whitespace(self):
        """Test parsing --whitespace option."""
        cmd = rebase.Rebase()
        opts, args = cmd.OptionParser.parse_args(["--whitespace=fix"])
        assert opts.whitespace == "fix"


@pytest.mark.unit
class TestRebaseCommand:
    """Test Rebase command properties."""

    def test_common_flag(self):
        """Test Rebase command is marked as COMMON."""
        assert rebase.Rebase.COMMON is True

    def test_help_summary(self):
        """Test Rebase command has help summary."""
        assert rebase.Rebase.helpSummary is not None

    def test_parallel_jobs(self):
        """Test Rebase has parallel jobs configured."""

        assert rebase.Rebase.PARALLEL_JOBS is None or rebase.Rebase.PARALLEL_JOBS > 0
