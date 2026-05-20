"""Unit tests for src/kanon_cli/commands/completion.py.

Covers:
- The 'completion' subparser has add_help=True so '-h' is accepted.
- The subparser accepts 'bash' and 'zsh' as shell choices.
"""

import argparse

import pytest


@pytest.mark.unit
class TestCompletionSubparserHelp:
    """The 'completion' subparser has add_help=True and accepts '-h'."""

    def test_completion_short_dash_h_exits_0(self) -> None:
        """kanon completion -h exits 0 (add_help=True on the completion subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["completion", "-h"])
        assert exc_info.value.code == 0

    def test_completion_subparser_has_add_help_true(self) -> None:
        """The 'completion' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.completion import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        completion_parser = subparsers.choices["completion"]
        assert completion_parser.add_help is True, "completion subparser must have add_help=True so '-h' is accepted"

    def test_completion_long_help_still_works(self) -> None:
        """kanon completion --help still exits 0 (no regression in --help)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["completion", "--help"])
        assert exc_info.value.code == 0

    @pytest.mark.parametrize("shell", ["bash", "zsh"])
    def test_completion_accepts_shell_argument(self, shell: str) -> None:
        """The 'completion' subparser accepts 'bash' and 'zsh' as shell positional."""
        from kanon_cli.commands.completion import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        args = root_parser.parse_args(["completion", shell])
        assert args.shell == shell
