"""Unit tests for src/kanon_cli/commands/bootstrap.py.

Covers:
- The 'bootstrap' parser has add_help=True so '-h' is accepted.
- The deprecated notice appears before 'usage:' in help output.
- The parser accepts 'package' positional and '--output-dir' flag.
"""

import argparse
import io

import pytest


@pytest.mark.unit
class TestBootstrapSubparserHelp:
    """The 'bootstrap' parser has add_help=True and accepts '-h'."""

    def _get_bootstrap_parser(self) -> argparse.ArgumentParser:
        """Register bootstrap and return the resulting parser object."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices and "bootstrap" in action.choices:
                return action.choices["bootstrap"]
        raise AssertionError("No 'bootstrap' subparser found in build_parser()")

    def test_bootstrap_short_dash_h_exits_0(self) -> None:
        """kanon bootstrap -h exits 0 (add_help=True on the bootstrap parser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["bootstrap", "-h"])
        assert exc_info.value.code == 0

    def test_bootstrap_parser_has_add_help_true(self) -> None:
        """The 'bootstrap' parser has add_help=True set explicitly."""
        bootstrap_parser = self._get_bootstrap_parser()
        assert bootstrap_parser.add_help is True, "bootstrap parser must have add_help=True so '-h' is accepted"

    def test_bootstrap_long_help_still_works(self) -> None:
        """kanon bootstrap --help still exits 0 (no regression in --help)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["bootstrap", "--help"])
        assert exc_info.value.code == 0

    def test_bootstrap_help_contains_deprecated_notice(self) -> None:
        """'bootstrap' help output contains the DEPRECATED notice before 'usage:'."""
        bootstrap_parser = self._get_bootstrap_parser()
        buf = io.StringIO()
        bootstrap_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "DEPRECATED" in help_text, "bootstrap help must contain the DEPRECATED notice"
        deprecated_pos = help_text.index("DEPRECATED")
        usage_pos = help_text.lower().index("usage:")
        assert deprecated_pos < usage_pos, "DEPRECATED notice must appear before 'usage:' in bootstrap help output"
