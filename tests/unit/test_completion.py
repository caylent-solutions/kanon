"""Unit tests for src/kanon_cli/commands/completion.py.

Covers:
- The 'completion' subparser has add_help=True so '-h' is accepted.
- The subparser accepts 'bash', 'zsh', and 'powershell' as shell choices.
- SUPPORTED_SHELLS includes 'powershell' (FR-31).
- The 'powershell' choice dispatches to the powershell generator.
- An unsupported shell (e.g. 'cmd') raises the argparse choice error whose
  message names the supported set including 'powershell' (FR-39).
"""

import argparse
from io import StringIO
from unittest.mock import patch

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

    @pytest.mark.parametrize("shell", ["bash", "zsh", "powershell"])
    def test_completion_accepts_shell_argument(self, shell: str) -> None:
        """The 'completion' subparser accepts bash, zsh, and powershell positionals."""
        from kanon_cli.commands.completion import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        args = root_parser.parse_args(["completion", shell])
        assert args.shell == shell


@pytest.mark.unit
class TestSupportedShells:
    """SUPPORTED_SHELLS includes powershell and feeds the subparser choices."""

    def test_supported_shells_includes_powershell(self) -> None:
        """SUPPORTED_SHELLS must include 'powershell' (FR-31)."""
        from kanon_cli.commands.completion import SUPPORTED_SHELLS

        assert "powershell" in SUPPORTED_SHELLS

    def test_supported_shells_is_bash_zsh_powershell(self) -> None:
        """SUPPORTED_SHELLS must be exactly ['bash', 'zsh', 'powershell']."""
        from kanon_cli.commands.completion import SUPPORTED_SHELLS

        assert SUPPORTED_SHELLS == ["bash", "zsh", "powershell"]

    def test_subparser_choices_follow_supported_shells(self) -> None:
        """The shell positional's choices must equal SUPPORTED_SHELLS."""
        from kanon_cli.commands.completion import SUPPORTED_SHELLS, register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        completion_parser = subparsers.choices["completion"]
        shell_action = next(a for a in completion_parser._actions if a.dest == "shell")
        assert list(shell_action.choices) == SUPPORTED_SHELLS


@pytest.mark.unit
class TestPowershellDispatch:
    """The 'powershell' choice routes through the powershell generator."""

    def test_handle_dispatches_powershell_to_generator(self) -> None:
        """handle() must call the powershell generator for the powershell shell."""
        from kanon_cli.cli import build_parser
        from kanon_cli.commands.completion import handle

        root_parser = build_parser()
        args = argparse.Namespace(shell="powershell", func=handle, parser=root_parser)

        sentinel_script = "# generated-powershell-script\n"
        with patch(
            "kanon_cli.commands.completion.powershell.generate",
            return_value=sentinel_script,
        ) as mock_generate:
            captured = StringIO()
            with patch("sys.stdout", captured):
                handle(args)

        mock_generate.assert_called_once_with(root_parser)
        assert captured.getvalue() == sentinel_script

    def test_handle_powershell_emits_register_argument_completer(self) -> None:
        """The powershell script written to stdout contains Register-ArgumentCompleter."""
        from kanon_cli.cli import build_parser
        from kanon_cli.commands.completion import handle

        root_parser = build_parser()
        args = argparse.Namespace(shell="powershell", func=handle, parser=root_parser)

        captured = StringIO()
        with patch("sys.stdout", captured):
            handle(args)

        assert "Register-ArgumentCompleter" in captured.getvalue()

    def test_handle_powershell_does_not_call_shtab(self) -> None:
        """The powershell path must not route through shtab (which lacks PowerShell)."""
        from kanon_cli.cli import build_parser
        from kanon_cli.commands.completion import handle

        root_parser = build_parser()
        args = argparse.Namespace(shell="powershell", func=handle, parser=root_parser)

        with patch("kanon_cli.commands.completion.shtab") as mock_shtab:
            captured = StringIO()
            with patch("sys.stdout", captured):
                handle(args)

        mock_shtab.complete.assert_not_called()


@pytest.mark.unit
class TestUnsupportedShellChoiceError:
    """An unsupported shell raises the argparse choice error naming the set."""

    def test_cmd_choice_raises_systemexit(self) -> None:
        """kanon completion cmd must exit non-zero (cmd is not a valid choice)."""
        from kanon_cli.commands.completion import register

        root_parser = argparse.ArgumentParser(prog="kanon")
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        with pytest.raises(SystemExit) as exc_info:
            root_parser.parse_args(["completion", "cmd"])
        assert exc_info.value.code != 0

    def test_cmd_choice_error_names_powershell(self) -> None:
        """The cmd choice error must name the supported set including powershell."""
        from kanon_cli.commands.completion import register

        root_parser = argparse.ArgumentParser(prog="kanon")
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)

        captured_err = StringIO()
        with patch("sys.stderr", captured_err), pytest.raises(SystemExit):
            root_parser.parse_args(["completion", "cmd"])

        assert "powershell" in captured_err.getvalue()
