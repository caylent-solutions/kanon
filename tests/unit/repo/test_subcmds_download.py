"""Unittests for the subcmds/download.py module."""

import pytest

from kanon_cli.repo.subcmds import download


@pytest.mark.unit
class TestDownloadOptions:
    """Test Download command options."""

    def test_options_setup(self):
        """Verify Download command option parser is set up correctly."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args([])

        assert opts.cherrypick is None or opts.cherrypick is False
        assert opts.revert is None or opts.revert is False
        assert opts.ffonly is None or opts.ffonly is False

    def test_options_cherrypick(self):
        """Test parsing -c option."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args(["-c"])
        assert opts.cherrypick is True

    def test_options_revert(self):
        """Test parsing -r option."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args(["-r"])
        assert opts.revert is True

    def test_options_ffonly(self):
        """Test parsing -f option."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args(["-f"])
        assert opts.ffonly is True


@pytest.mark.unit
class TestDownloadCommand:
    """Test Download command properties."""

    def test_common_flag(self):
        """Test Download command is marked as COMMON."""
        assert download.Download.COMMON is True

    def test_help_summary(self):
        """Test Download command has help summary."""
        assert download.Download.helpSummary is not None


@pytest.mark.unit
class TestDownloadValidateOptions:
    """Test Download ValidateOptions method."""

    def test_validate_options_with_change_id(self):
        """Test ValidateOptions passes with change ID."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args(["project", "12345/1"])

        cmd.ValidateOptions(opts, args)

    def test_validate_options_conflicting_options(self):
        """Test ValidateOptions rejects conflicting -x and --ff options."""
        cmd = download.Download()
        opts, args = cmd.OptionParser.parse_args(["-c", "-x", "--ff", "project", "12345/1"])

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opts, args)
