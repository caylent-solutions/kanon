"""Unit tests for the kanon completion subcommand.

Tests the register() and handle() functions in commands/completion.py.
Covers: bash, zsh (success), fish (rejected by argparse choices),
missing shell (rejected by argparse required argument).

AC-TEST-001: Parametrized cases for bash, zsh, fish, and missing shell.
"""

from __future__ import annotations

import argparse
from io import StringIO
from unittest.mock import patch

import pytest

from kanon_cli.cli import build_parser
from kanon_cli.commands.completion import handle, register


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subparsers() -> "argparse._SubParsersAction[argparse.ArgumentParser]":
    """Return a fresh subparsers action on a minimal ArgumentParser."""
    parent = argparse.ArgumentParser(prog="kanon")
    return parent.add_subparsers(dest="command")


# ---------------------------------------------------------------------------
# register() -- structural tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_register_adds_completion_subcommand() -> None:
    """register() should add a 'completion' subparser with a shell positional."""
    subparsers = _make_subparsers()
    register(subparsers)
    parser = subparsers.choices["completion"]
    assert parser is not None


@pytest.mark.unit
def test_register_sets_func() -> None:
    """register() must set func=handle on the completion subparser."""
    subparsers = _make_subparsers()
    register(subparsers)
    parser = subparsers.choices["completion"]
    args = parser.parse_args(["bash"])
    assert args.func is handle


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_register_accepts_valid_shells(shell: str) -> None:
    """register() must accept 'bash' and 'zsh' as valid shell choices."""
    subparsers = _make_subparsers()
    register(subparsers)
    parser = subparsers.choices["completion"]
    args = parser.parse_args([shell])
    assert args.shell == shell


@pytest.mark.unit
def test_register_rejects_fish_shell() -> None:
    """register() must reject 'fish' via argparse choices -- exits non-zero."""
    subparsers = _make_subparsers()
    register(subparsers)
    parser = subparsers.choices["completion"]
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["fish"])
    assert exc_info.value.code != 0


@pytest.mark.unit
def test_register_rejects_missing_shell() -> None:
    """register() must require the shell argument -- missing shell exits non-zero."""
    subparsers = _make_subparsers()
    register(subparsers)
    parser = subparsers.choices["completion"]
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# handle() -- output contract tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_handle_writes_non_empty_script_to_stdout(shell: str) -> None:
    """handle() must write a non-empty completion script to stdout for bash and zsh."""
    root_parser = build_parser()
    args = argparse.Namespace(shell=shell, func=handle, parser=root_parser)

    captured = StringIO()
    with patch("sys.stdout", captured):
        result = handle(args)

    # Returns None on success (consistent with other command handlers)
    assert result is None
    output = captured.getvalue()
    assert len(output) > 0, f"Expected non-empty output for shell={shell!r}"


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_handle_produces_no_stderr_on_success(shell: str) -> None:
    """handle() must not write to stderr on a successful completion generation."""
    root_parser = build_parser()
    args = argparse.Namespace(shell=shell, func=handle, parser=root_parser)

    captured_out = StringIO()
    captured_err = StringIO()
    with patch("sys.stdout", captured_out), patch("sys.stderr", captured_err):
        handle(args)

    assert captured_err.getvalue() == "", "stderr must be empty on success"


@pytest.mark.unit
def test_handle_calls_shtab_with_preamble() -> None:
    """handle() must call shtab.complete with the PREAMBLE dict from completions.preamble."""
    from kanon_cli.completions.preamble import PREAMBLE

    root_parser = build_parser()
    args = argparse.Namespace(shell="bash", func=handle, parser=root_parser)

    with patch("kanon_cli.commands.completion.shtab") as mock_shtab:
        mock_shtab.complete.return_value = "# completion script"
        handle(args)

    mock_shtab.complete.assert_called_once_with(root_parser, "bash", preamble=PREAMBLE)


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_handle_output_contains_shell_keyword(shell: str) -> None:
    """handle() output must reference the target shell (shtab embeds shell name in output)."""
    root_parser = build_parser()
    args = argparse.Namespace(shell=shell, func=handle, parser=root_parser)

    captured = StringIO()
    with patch("sys.stdout", captured):
        handle(args)

    output = captured.getvalue()
    # shtab-generated scripts include the shell name in the header/function names
    assert shell in output.lower(), f"Expected shell={shell!r} to appear in output"
