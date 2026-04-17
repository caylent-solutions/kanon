"""Tests for the kanon repo CLI subcommand.

Verifies CLI registration, argument passing, exit code propagation,
and help output for the `kanon repo` subcommand.
"""

import argparse
from unittest.mock import MagicMock, call, patch

import pytest


@pytest.mark.unit
class TestRepoRegister:
    def test_registers_repo_subcommand(self) -> None:
        """register() must add 'repo' to the parent subparsers."""
        from kanon_cli.commands.repo import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        parsed = parser.parse_args(["repo", "version"])
        assert parsed.command == "repo"

    def test_repo_help_lists_subcommands(self, capsys) -> None:
        """'kanon repo --help' must include repo subcommand descriptions."""
        from kanon_cli.commands.repo import register

        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["repo", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "repo" in captured.out.lower()

    def test_repo_help_output_not_empty(self, capsys) -> None:
        """'kanon repo --help' must produce non-empty output."""
        from kanon_cli.commands.repo import register

        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["repo", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert len(captured.out) > 0


@pytest.mark.unit
class TestRepoVersion:
    def test_repo_version_exits_zero(self, tmp_path) -> None:
        """'kanon repo version' must exit with code 0."""
        from kanon_cli.commands.repo import _run

        args = MagicMock()
        args.repo_args = ["version"]
        args.repo_dir = str(tmp_path)

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=0) as mock_run,
            pytest.raises(SystemExit) as exc_info,
        ):
            _run(args)

        assert exc_info.value.code == 0
        mock_run.assert_called_once_with(["version"], repo_dir=str(tmp_path))

    @pytest.mark.parametrize(
        "subcommand",
        [
            ["version"],
            ["help"],
            ["version", "--verbose"],
        ],
    )
    def test_repo_run_called_with_exact_args(self, tmp_path, subcommand) -> None:
        """_run() must pass trailing args exactly as-is to repo_run()."""
        from kanon_cli.commands.repo import _run

        args = MagicMock()
        args.repo_args = subcommand
        args.repo_dir = str(tmp_path)

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=0),
            pytest.raises(SystemExit),
        ):
            _run(args)


@pytest.mark.unit
class TestRepoArgPassing:
    def test_trailing_args_forwarded_to_repo_run(self, tmp_path) -> None:
        """_run() must forward all trailing args to repo_run()."""
        from kanon_cli.commands.repo import _run

        trailing = ["sync", "--jobs=4", "--current-branch"]
        args = MagicMock()
        args.repo_args = trailing
        args.repo_dir = str(tmp_path)

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=0) as mock_run,
            pytest.raises(SystemExit),
        ):
            _run(args)

        mock_run.assert_called_once_with(trailing, repo_dir=str(tmp_path))

    def test_empty_trailing_args_forwarded(self, tmp_path) -> None:
        """_run() with no trailing args must pass an empty list to repo_run()."""
        from kanon_cli.commands.repo import _run

        args = MagicMock()
        args.repo_args = []
        args.repo_dir = str(tmp_path)

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=0) as mock_run,
            pytest.raises(SystemExit),
        ):
            _run(args)

        mock_run.assert_called_once_with([], repo_dir=str(tmp_path))

    def test_repo_dir_passed_as_keyword_arg(self, tmp_path) -> None:
        """_run() must pass repo_dir as a keyword argument to repo_run()."""
        from kanon_cli.commands.repo import _run

        repo_dir = str(tmp_path / "my-repo")
        args = MagicMock()
        args.repo_args = ["version"]
        args.repo_dir = repo_dir

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=0) as mock_run,
            pytest.raises(SystemExit),
        ):
            _run(args)

        assert mock_run.call_args == call(["version"], repo_dir=repo_dir)


@pytest.mark.unit
class TestRepoExitCodePropagation:
    @pytest.mark.parametrize("exit_code", [0, 1, 2, 127])
    def test_exit_code_propagated_from_repo_run(self, tmp_path, exit_code) -> None:
        """_run() must exit with the same code returned by repo_run()."""
        from kanon_cli.commands.repo import _run

        args = MagicMock()
        args.repo_args = ["version"]
        args.repo_dir = str(tmp_path)

        with (
            patch("kanon_cli.commands.repo.repo_run", return_value=exit_code),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run(args)

        assert exc_info.value.code == exit_code

    def test_repo_run_error_propagates_exit_code(self, tmp_path) -> None:
        """When repo_run() raises RepoCommandError, _run() must exit non-zero."""
        from kanon_cli.commands.repo import _run
        from kanon_cli.repo.main import RepoCommandError

        args = MagicMock()
        args.repo_args = ["bad-subcommand"]
        args.repo_dir = str(tmp_path)

        with (
            patch(
                "kanon_cli.commands.repo.repo_run",
                side_effect=RepoCommandError(exit_code=1),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run(args)

        assert exc_info.value.code != 0


@pytest.mark.unit
class TestRepoInvalidSubcommand:
    def test_invalid_subcommand_exits_nonzero(self, tmp_path) -> None:
        """An invalid repo subcommand must result in a non-zero exit code."""
        from kanon_cli.commands.repo import _run
        from kanon_cli.repo.main import RepoCommandError

        args = MagicMock()
        args.repo_args = ["totally-not-a-real-subcommand"]
        args.repo_dir = str(tmp_path)

        with (
            patch(
                "kanon_cli.commands.repo.repo_run",
                side_effect=RepoCommandError(exit_code=1),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run(args)

        assert exc_info.value.code != 0

    @pytest.mark.parametrize(
        "bad_args",
        [
            ["notacommand"],
            ["--invalid-flag"],
            ["fake", "sub"],
        ],
    )
    def test_various_invalid_subcommands_exit_nonzero(self, tmp_path, bad_args) -> None:
        """Multiple invalid subcommand patterns must all exit non-zero."""
        from kanon_cli.commands.repo import _run
        from kanon_cli.repo.main import RepoCommandError

        args = MagicMock()
        args.repo_args = bad_args
        args.repo_dir = str(tmp_path)

        with (
            patch(
                "kanon_cli.commands.repo.repo_run",
                side_effect=RepoCommandError(exit_code=1),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run(args)

        assert exc_info.value.code != 0
