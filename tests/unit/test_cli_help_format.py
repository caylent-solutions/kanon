"""Unit tests for _TopLevelHelpAction and _TOP_LEVEL_HELP in cli.py.

Verifies that:
- _TOP_LEVEL_HELP is defined as a module-level string constant.
- _TopLevelHelpAction subclasses argparse.Action.
- _TopLevelHelpAction.__call__ prints _TOP_LEVEL_HELP to stdout and raises
  SystemExit(0).
- build_parser() registers --help via _TopLevelHelpAction (add_help=False).
- Invoking parse_args(['--help']) prints _TOP_LEVEL_HELP and exits with code 0.
"""

import argparse
import io
from unittest.mock import patch

import pytest

from kanon_cli.cli import (
    _TOP_LEVEL_HELP,
    _TopLevelHelpAction,
    build_parser,
)


@pytest.mark.unit
class TestEveryGlobalFlagIsDocumented:
    """Every global option argparse accepts must appear in the hand-written help.

    ``kanon --help`` prints ``_TOP_LEVEL_HELP``, a hand-maintained block, not
    argparse's generated output. A flag added to the parser without a matching
    line there is invisible to anyone reading the help, while still appearing in
    the usage line argparse prints on an error, which is a confusing place to
    discover a feature.

    The help snapshot fixture does not catch this. Adding a flag and not touching
    the help block leaves the snapshot byte-identical, so it passes. That is
    exactly how ``--allow-abs-root`` shipped undocumented in this help block.
    """

    def _global_option_strings(self) -> list[str]:
        """Return every long option declared on the top-level parser.

        Returns:
            The ``--flag`` strings, excluding argparse's own ``--help``.
        """
        parser = build_parser()
        flags: list[str] = []
        for action in parser._actions:
            for option in action.option_strings:
                if option.startswith("--") and option != "--help":
                    flags.append(option)
        return flags

    def test_parser_declares_global_options(self) -> None:
        """Guard the guard: an empty flag list would make the check vacuous."""
        assert len(self._global_option_strings()) > 0

    def test_every_global_flag_appears_in_the_help_text(self) -> None:
        """A global flag missing from the help block is undiscoverable."""
        missing = [flag for flag in self._global_option_strings() if flag not in _TOP_LEVEL_HELP]
        assert not missing, f"global flags absent from the hand-written help block: {missing}"


@pytest.mark.unit
class TestTopLevelHelpConstant:
    """Verify the _TOP_LEVEL_HELP module-level constant."""

    def test_top_level_help_is_string(self) -> None:
        """_TOP_LEVEL_HELP must be a non-empty string."""
        assert isinstance(_TOP_LEVEL_HELP, str)
        assert len(_TOP_LEVEL_HELP) > 0

    @pytest.mark.parametrize(
        "heading",
        [
            "Discovery & management:",
            "Lifecycle:",
            "Manifest repo (catalog author):",
            "Shell integration:",
            "Global options (always available):",
            "Catalog source",
        ],
    )
    def test_top_level_help_contains_group_heading(self, heading: str) -> None:
        """_TOP_LEVEL_HELP must contain each required group heading."""
        assert heading in _TOP_LEVEL_HELP

    def test_top_level_help_no_em_dash(self) -> None:
        """_TOP_LEVEL_HELP must not contain em-dash characters (U+2014)."""
        assert "\u2014" not in _TOP_LEVEL_HELP

    def test_top_level_help_ends_with_newline(self) -> None:
        """_TOP_LEVEL_HELP must end with a LF newline (as argparse emits)."""
        assert _TOP_LEVEL_HELP.endswith("\n")

    def test_top_level_help_no_trailing_whitespace_on_non_empty_lines(self) -> None:
        """Non-empty lines in _TOP_LEVEL_HELP must not have trailing whitespace."""
        for line in _TOP_LEVEL_HELP.splitlines():
            if line.strip():
                assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"


@pytest.mark.unit
class TestTopLevelHelpAction:
    """Verify _TopLevelHelpAction subclasses argparse.Action and exits correctly."""

    def test_is_subclass_of_argparse_action(self) -> None:
        """_TopLevelHelpAction must be a subclass of argparse.Action."""
        assert issubclass(_TopLevelHelpAction, argparse.Action)

    def test_call_prints_top_level_help_to_stdout(self) -> None:
        """__call__ must print _TOP_LEVEL_HELP to stdout."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            with pytest.raises(SystemExit):
                parser = argparse.ArgumentParser(add_help=False)
                parser.add_argument(
                    "--help",
                    nargs=0,
                    action=_TopLevelHelpAction,
                    default=argparse.SUPPRESS,
                )
                parser.parse_args(["--help"])

        assert captured.getvalue() == _TOP_LEVEL_HELP

    def test_call_raises_system_exit_0(self) -> None:
        """__call__ must raise SystemExit with code 0."""
        with patch("sys.stdout", io.StringIO()):
            with pytest.raises(SystemExit) as exc_info:
                parser = argparse.ArgumentParser(add_help=False)
                parser.add_argument(
                    "--help",
                    nargs=0,
                    action=_TopLevelHelpAction,
                    default=argparse.SUPPRESS,
                )
                parser.parse_args(["--help"])

        assert exc_info.value.code == 0


@pytest.mark.unit
class TestBuildParserHelp:
    """Verify build_parser() wires --help via _TopLevelHelpAction."""

    def test_help_flag_prints_top_level_help(self) -> None:
        """build_parser() --help must print _TOP_LEVEL_HELP to stdout."""
        parser = build_parser()
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(["--help"])

        assert exc_info.value.code == 0
        assert captured.getvalue() == _TOP_LEVEL_HELP

    def test_help_flag_exits_with_zero(self) -> None:
        """build_parser() --help must exit with code 0."""
        parser = build_parser()
        with patch("sys.stdout", io.StringIO()):
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(["--help"])

        assert exc_info.value.code == 0

    def test_help_output_contains_no_em_dash(self) -> None:
        """Help output captured from build_parser() must contain no em-dash (U+2014)."""
        parser = build_parser()
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            with pytest.raises(SystemExit):
                parser.parse_args(["--help"])

        assert "\u2014" not in captured.getvalue()
