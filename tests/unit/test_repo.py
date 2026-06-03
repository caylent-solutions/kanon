"""Unit tests for src/kanon_cli/commands/repo.py.

Covers:
- The 'repo' subparser has add_help=True so '-h' is accepted.
- The subparser accepts '--repo-dir' flag.
"""

import argparse

import pytest


@pytest.mark.unit
class TestRepoSubparserHelp:
    """The 'repo' subparser has add_help=True and accepts '-h'."""

    def test_repo_short_dash_h_exits_0(self) -> None:
        """kanon repo -h exits 0 (add_help=True on the repo subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["repo", "-h"])
        assert exc_info.value.code == 0

    def test_repo_subparser_has_add_help_true(self) -> None:
        """The 'repo' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.repo import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        repo_parser = subparsers.choices["repo"]
        assert repo_parser.add_help is True, "repo subparser must have add_help=True so '-h' is accepted"

    def test_repo_long_help_still_works(self) -> None:
        """kanon repo --help still exits 0 (no regression in --help)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["repo", "--help"])
        assert exc_info.value.code == 0

    def test_repo_subparser_registered_in_build_parser(self) -> None:
        """build_parser() includes 'repo' as a registered subcommand."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices and "repo" in action.choices:
                return
        raise AssertionError("'repo' not registered as a subcommand in build_parser()")
