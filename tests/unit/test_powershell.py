"""Unit tests for src/kanon_cli/completions/powershell.py.

Covers the PowerShell tab-completion generator (spec Section 4.6 / FR-31):

- The emitted script contains a ``Register-ArgumentCompleter`` block.
- The script references the ``kanon`` command (the root parser's prog name).
- The completer is produced from the injected root parser, so every public
  top-level subcommand (including ``search``) appears and hidden internal
  helper subcommands (``__complete_*``, ``__resolve_*``) are excluded.
- A root parser with no subparsers action fails loudly (no silent empty script).
"""

from __future__ import annotations

import argparse

import pytest

from kanon_cli.cli import build_parser
from kanon_cli.completions.powershell import generate


@pytest.mark.unit
def test_generate_emits_register_argument_completer() -> None:
    """generate() must emit a Register-ArgumentCompleter block."""
    script = generate(build_parser())
    assert "Register-ArgumentCompleter" in script


@pytest.mark.unit
def test_generate_references_program_name() -> None:
    """generate() must reference the root parser's program name (kanon)."""
    root_parser = build_parser()
    script = generate(root_parser)
    assert root_parser.prog == "kanon"
    assert "kanon" in script


@pytest.mark.unit
def test_generate_covers_search_subcommand() -> None:
    """The completer must list the 'search' subcommand introduced by E3."""
    script = generate(build_parser())
    assert "'search'" in script


@pytest.mark.unit
@pytest.mark.parametrize(
    "subcommand",
    ["add", "search", "install", "remove", "doctor", "completion"],
)
def test_generate_covers_public_subcommands(subcommand: str) -> None:
    """Every public top-level subcommand must appear in the completer list."""
    script = generate(build_parser())
    assert f"'{subcommand}'" in script


@pytest.mark.unit
def test_generate_excludes_hidden_internal_helpers() -> None:
    """Hidden internal helper subcommands must not leak into the user completer."""
    script = generate(build_parser())
    assert "__complete_catalog_entries" not in script
    assert "__resolve_entry_to_repo_url" not in script


@pytest.mark.unit
def test_generate_is_produced_from_injected_parser() -> None:
    """generate() must derive its subcommand list from the injected parser.

    A parser whose only subcommand is a custom name must produce a completer
    that lists exactly that name, proving the list is introspected (not
    hard-coded).
    """
    parser = argparse.ArgumentParser(prog="kanon")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("only-this-one")

    script = generate(parser)

    assert "'only-this-one'" in script
    assert "'add'" not in script


@pytest.mark.unit
def test_generate_uses_injected_program_name() -> None:
    """The completer must key on the injected parser's prog, not a constant."""
    parser = argparse.ArgumentParser(prog="kanon-fork")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("noop")

    script = generate(parser)

    assert "Register-ArgumentCompleter -Native -CommandName 'kanon-fork'" in script


@pytest.mark.unit
def test_generate_without_subparsers_raises() -> None:
    """A parser with no subparsers action must fail loudly, not emit empty output."""
    parser = argparse.ArgumentParser(prog="kanon")

    with pytest.raises(ValueError) as exc_info:
        generate(parser)

    assert "no subparsers action" in str(exc_info.value)


@pytest.mark.unit
def test_generate_escapes_single_quotes_in_subcommand_names() -> None:
    """A subcommand name containing a single quote must be PowerShell-escaped."""
    parser = argparse.ArgumentParser(prog="kanon")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("o'clock")

    script = generate(parser)

    # PowerShell escapes an embedded single quote by doubling it.
    assert "'o''clock'" in script
