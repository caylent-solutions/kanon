"""Unit tests for src/kanon_cli/commands/validate.py.

Covers:
- The 'validate' subparser has add_help=True so '-h' is accepted.
- Nested sub-subparsers ('xml', 'marketplace', 'metadata') also accept '-h'.
"""

import argparse

import pytest


@pytest.mark.unit
class TestValidateSubparserHelp:
    """The 'validate' subparser and its nested sub-subparsers accept '-h'."""

    def test_validate_short_dash_h_exits_0(self) -> None:
        """kanon validate -h exits 0 (add_help=True on the validate subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "-h"])
        assert exc_info.value.code == 0

    def test_validate_subparser_has_add_help_true(self) -> None:
        """The 'validate' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.validate import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        validate_parser = subparsers.choices["validate"]
        assert validate_parser.add_help is True, "validate subparser must have add_help=True so '-h' is accepted"

    @pytest.mark.parametrize("sub_sub", ["xml", "marketplace", "metadata"])
    def test_validate_sub_subparser_has_add_help_true(self, sub_sub: str) -> None:
        """Each validate sub-subparser ('xml', 'marketplace', 'metadata') has add_help=True."""
        from kanon_cli.commands.validate import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        validate_parser = subparsers.choices["validate"]
        for action in validate_parser._actions:
            if hasattr(action, "choices") and action.choices and sub_sub in action.choices:
                sub_parser = action.choices[sub_sub]
                assert sub_parser.add_help is True, (
                    f"validate {sub_sub} sub-subparser must have add_help=True so '-h' is accepted"
                )
                return
        raise AssertionError(f"No '{sub_sub}' sub-subparser found under 'validate'")

    @pytest.mark.parametrize("sub_sub", ["xml", "marketplace", "metadata"])
    def test_validate_sub_subcommand_dash_h_exits_0(self, sub_sub: str) -> None:
        """'kanon validate <sub_sub> -h' exits 0 for each nested subcommand."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["validate", sub_sub, "-h"])
        assert exc_info.value.code == 0

    def test_validate_long_help_still_works(self) -> None:
        """kanon validate --help still exits 0 (no regression in --help)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "--help"])
        assert exc_info.value.code == 0
