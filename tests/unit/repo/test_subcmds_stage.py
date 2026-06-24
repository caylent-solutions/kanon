"""Unittests for the subcmds/stage.py module."""

import pytest

from kanon_cli.repo.subcmds import stage


@pytest.mark.unit
class TestStageOptions:
    """Test Stage command options."""

    def test_options_setup(self):
        """Verify Stage command option parser is set up correctly."""
        cmd = stage.Stage()
        opts, args = cmd.OptionParser.parse_args([])

        assert opts is not None


@pytest.mark.unit
class TestStageCommand:
    """Test Stage command properties."""

    def test_help_summary(self):
        """Test Stage command has help summary."""
        assert stage.Stage.helpSummary is not None
