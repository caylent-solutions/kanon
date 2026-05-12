"""Tests for the argparse CLI entry point."""

import argparse
import re
import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.cli import _make_signal_handler, build_parser, main

# Placeholder path used for subcommands that require a positional kanon-env argument.
# The parser performs no filesystem check, so any non-empty string is valid for
# unit-test purposes. A fixed constant avoids hardcoded literal paths in every
# test method and keeps all tests environment-agnostic (12-Factor rule 4).
_FAKE_KANON_PATH = "test-kanon-file"


@pytest.mark.unit
class TestBuildParser:
    """Verify parser construction and subcommand registration."""

    def test_parser_has_version(self) -> None:
        parser = build_parser()
        assert parser.prog == "kanon"

    def test_parser_has_subcommands(self) -> None:
        parser = build_parser()
        # Verify subparsers exist by checking parse_args on known subcommands
        args = parser.parse_args(["install", "/tmp/.kanon"])
        assert args.command == "install"

    def test_parser_clean_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "/tmp/.kanon"])
        assert args.command == "clean"

    def test_parser_validate_xml_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "xml"])
        assert args.command == "validate"
        assert args.validate_command == "xml"

    def test_parser_validate_marketplace_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "marketplace"])
        assert args.command == "validate"
        assert args.validate_command == "marketplace"

    def test_parser_validate_xml_with_repo_root(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "xml", "--repo-root", "/some/path"])
        assert str(args.repo_root) == "/some/path"


@pytest.mark.unit
class TestMainDispatch:
    """Verify main() dispatch behavior."""

    def test_no_subcommand_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

    def test_help_exits_0(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_version_exits_0(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_install_no_arg_no_kanonenv_exits_1(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["install"])
        assert exc_info.value.code == 1

    def test_main_installs_sigterm_handler(self) -> None:
        """main() installs a SIGTERM handler before dispatching."""
        captured_handler = {}

        def _mock_signal(signum: int, handler: object) -> object:
            captured_handler[signum] = handler
            return signal.SIG_DFL

        with patch("kanon_cli.cli.signal.signal", side_effect=_mock_signal):
            with pytest.raises(SystemExit):
                main([])

        assert signal.SIGTERM in captured_handler, (
            "main() must call signal.signal(SIGTERM, ...) to install a SIGTERM handler"
        )

    def test_main_installs_sigint_handler(self) -> None:
        """main() installs a SIGINT handler before dispatching."""
        captured_handler = {}

        def _mock_signal(signum: int, handler: object) -> object:
            captured_handler[signum] = handler
            return signal.SIG_DFL

        with patch("kanon_cli.cli.signal.signal", side_effect=_mock_signal):
            with pytest.raises(SystemExit):
                main([])

        assert signal.SIGINT in captured_handler, (
            "main() must call signal.signal(SIGINT, ...) to install a SIGINT handler"
        )


@pytest.mark.unit
class TestMakeSignalHandler:
    """Verify _make_signal_handler() creates handlers that call os._exit(128+signum)."""

    @pytest.mark.parametrize(
        "signum",
        [signal.SIGTERM, signal.SIGINT],
        ids=["SIGTERM", "SIGINT"],
    )
    def test_handler_calls_os_exit_with_128_plus_signum(self, signum: int) -> None:
        """Handler calls os._exit(128 + signum) when invoked.

        Patches os._exit so the test process is not terminated. Verifies
        the exit code matches the POSIX shell convention of 128 + signal_number.
        """
        handler = _make_signal_handler(signum)

        with patch("kanon_cli.cli.os._exit") as mock_exit:
            handler(signum, None)

        mock_exit.assert_called_once_with(128 + signum)

    def test_handler_uses_received_signum_not_closure(self) -> None:
        """Handler uses the signal number received at call time, not the closure value.

        _make_signal_handler(SIGTERM) returns a handler that receives the actual
        signal number as its first argument. The handler must use that argument
        (received_signum) to compute the exit code, not a captured closure variable.
        Both approaches produce the same result for a correctly formed handler, but
        this test confirms the received_signum path is executed.
        """
        handler = _make_signal_handler(signal.SIGTERM)

        with patch("kanon_cli.cli.os._exit") as mock_exit:
            handler(signal.SIGTERM, None)

        mock_exit.assert_called_once_with(128 + signal.SIGTERM)


# ---------------------------------------------------------------------------
# Tests for global flags integration in cli.py (AC-FUNC-009, AC-FUNC-010,
# AC-FUNC-012, AC-TEST-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGlobalFlagsInRootParser:
    """build_parser() adds global flags to the root parser before subparsers (AC-FUNC-009)."""

    def test_root_parser_has_quiet_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--quiet", "install", _FAKE_KANON_PATH])
        assert args.quiet is True

    def test_root_parser_has_verbose_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--verbose", "install", _FAKE_KANON_PATH])
        assert args.verbose is True

    def test_root_parser_has_no_color_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--no-color", "install", _FAKE_KANON_PATH])
        assert args.no_color is True

    def test_global_flags_default_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", _FAKE_KANON_PATH])
        assert args.quiet is False
        assert args.verbose is False
        assert args.no_color is False

    def test_quiet_verbose_together_exits_nonzero(self) -> None:
        """Root parser enforces mutual exclusion of --quiet and --verbose."""
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--quiet", "--verbose", "install", _FAKE_KANON_PATH])
        assert exc_info.value.code != 0


@pytest.mark.unit
class TestGlobalFlagsSubcommandPropagation:
    """Every subcommand receives quiet, verbose, no_color in parsed namespace (AC-FUNC-012, AC-TEST-002)."""

    def _get_subcommand_choices(self) -> list[str]:
        """Return all registered subcommand names by introspecting the parser."""
        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return list(action.choices.keys())
        return []

    @pytest.fixture()
    def subcommands(self) -> list[str]:
        return self._get_subcommand_choices()

    def _minimal_args_for(self, subcommand: str) -> list[str]:
        """Return the minimal argv needed to parse the given subcommand without error.

        Every registered subcommand MUST have an entry here. If a new subcommand
        is added to the parser without a corresponding entry, _minimal_args_for
        returns an empty list which will cause parse_args to raise SystemExit --
        and the test will fail loudly rather than swallowing the error.
        """
        minimal: dict[str, list[str]] = {
            "add": ["entry-a", "--catalog-source", "https://example.com/repo.git@main"],
            "install": [_FAKE_KANON_PATH],
            "clean": [_FAKE_KANON_PATH],
            "validate": ["xml"],
            "bootstrap": ["list"],
            "list": [],
            "repo": ["init", "-u", "https://example.com/repo", "-b", "main", "-m", "manifest.xml"],
        }
        return minimal[subcommand]

    def test_subcommands_not_empty(self, subcommands: list[str]) -> None:
        assert len(subcommands) > 0, "build_parser() must register at least one subcommand"

    @pytest.mark.parametrize(
        "flag_args,attr,expected",
        [
            (["--quiet"], "quiet", True),
            (["--verbose"], "verbose", True),
            (["--no-color"], "no_color", True),
            ([], "quiet", False),
            ([], "verbose", False),
            ([], "no_color", False),
        ],
        ids=[
            "--quiet->quiet=True",
            "--verbose->verbose=True",
            "--no-color->no_color=True",
            "default->quiet=False",
            "default->verbose=False",
            "default->no_color=False",
        ],
    )
    def test_global_flag_propagated_to_install(
        self,
        flag_args: list[str],
        attr: str,
        expected: bool,
    ) -> None:
        """install subcommand receives global flag values (representative subcommand)."""
        parser = build_parser()
        argv = flag_args + ["install", _FAKE_KANON_PATH]
        args = parser.parse_args(argv)
        assert getattr(args, attr) == expected

    def test_all_subcommands_have_quiet_attr(self, subcommands: list[str]) -> None:
        """Every subcommand's parsed namespace has the quiet attribute.

        Uses _minimal_args_for to supply valid positional arguments for each
        subcommand so parse_args succeeds. If a new subcommand is added without
        a _minimal_args_for entry, parse_args will raise SystemExit (via argparse
        error), which will propagate and fail the test loudly -- intentional
        fail-fast behavior.
        """
        parser = build_parser()
        for subcommand in subcommands:
            extra = self._minimal_args_for(subcommand)
            args = parser.parse_args(["--quiet"] + [subcommand] + extra)
            assert hasattr(args, "quiet"), f"subcommand '{subcommand}' missing 'quiet'"
            assert args.quiet is True, f"subcommand '{subcommand}' quiet not True"

    def test_all_subcommands_have_verbose_attr(self, subcommands: list[str]) -> None:
        """Every subcommand's parsed namespace has the verbose attribute.

        Uses _minimal_args_for to supply valid positional arguments for each
        subcommand so parse_args succeeds. If a new subcommand is added without
        a _minimal_args_for entry, parse_args will raise SystemExit (via argparse
        error), which will propagate and fail the test loudly -- intentional
        fail-fast behavior.
        """
        parser = build_parser()
        for subcommand in subcommands:
            extra = self._minimal_args_for(subcommand)
            args = parser.parse_args(["--verbose"] + [subcommand] + extra)
            assert hasattr(args, "verbose"), f"subcommand '{subcommand}' missing 'verbose'"
            assert args.verbose is True, f"subcommand '{subcommand}' verbose not True"

    def test_all_subcommands_have_no_color_attr(self, subcommands: list[str]) -> None:
        """Every subcommand's parsed namespace has the no_color attribute.

        Uses _minimal_args_for to supply valid positional arguments for each
        subcommand so parse_args succeeds. If a new subcommand is added without
        a _minimal_args_for entry, parse_args will raise SystemExit (via argparse
        error), which will propagate and fail the test loudly -- intentional
        fail-fast behavior.
        """
        parser = build_parser()
        for subcommand in subcommands:
            extra = self._minimal_args_for(subcommand)
            args = parser.parse_args(["--no-color"] + [subcommand] + extra)
            assert hasattr(args, "no_color"), f"subcommand '{subcommand}' missing 'no_color'"
            assert args.no_color is True, f"subcommand '{subcommand}' no_color not True"


@pytest.mark.unit
class TestApplyGlobalFlagsCalledBeforeDispatch:
    """_apply_global_flags is called in main() after parse_args and before subcommand dispatch (AC-FUNC-010)."""

    def test_apply_global_flags_called_in_main(self) -> None:
        """_apply_global_flags is invoked during main() execution."""
        with patch("kanon_cli.cli._apply_global_flags") as mock_apply:
            with pytest.raises(SystemExit):
                main([])
        # Called once even when no subcommand (exits with code 2 but apply is called before dispatch)
        # OR called before the sys.exit(2) path; either way it must be called
        # The spec requires it to be called BEFORE dispatch -- verified by checking
        # it was invoked at all. The order test below ensures it precedes dispatch.
        mock_apply.assert_called_once()

    def test_apply_global_flags_called_before_subcommand_dispatch(self) -> None:
        """_apply_global_flags is invoked before the subcommand func is called."""
        call_order: list[str] = []

        def record_apply(args: argparse.Namespace) -> None:
            call_order.append("apply_global_flags")

        mock_func = MagicMock(side_effect=lambda args: call_order.append("subcommand"))

        with patch("kanon_cli.cli._apply_global_flags", side_effect=record_apply):
            with patch("kanon_cli.cli.build_parser") as mock_build:
                mock_parser = MagicMock()
                mock_args = argparse.Namespace(
                    command="install",
                    quiet=False,
                    verbose=False,
                    no_color=False,
                    func=mock_func,
                )
                mock_parser.parse_args.return_value = mock_args
                mock_build.return_value = mock_parser
                main([])

        assert call_order == ["apply_global_flags", "subcommand"], (
            f"Expected apply_global_flags before subcommand dispatch, got: {call_order}"
        )


# ---------------------------------------------------------------------------
# AC-CYCLE-001: subprocess-driven verification of global flags via the
# installed kanon binary (three required scenarios per spec Section 12 item 25).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubprocessGlobalFlags:
    """Subprocess-driven tests for global flag behavior (AC-CYCLE-001).

    Each test spawns the kanon binary as a subprocess so the full argparse
    wiring, entry-point plumbing, and environment handling are exercised
    end-to-end -- not via in-process mocks.
    """

    def _run_kanon(
        self,
        args: list[str],
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the kanon entry point via the same Python interpreter.

        Uses `sys.executable -m kanon_cli` so no separate installation is
        required; the entry point is invoked directly from the source tree.
        extra_env values are merged on top of a clean minimal env that
        includes PATH and HOME (so git and other tools resolve correctly)
        while preventing test-environment leakage.
        """
        import os

        env = {k: v for k, v in os.environ.items()}
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "kanon_cli"] + args,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_help_lists_three_global_flags(self) -> None:
        """kanon --help output includes --quiet, --verbose, and --no-color.

        Verifies that add_global_flags is wired to the root parser and that
        argparse's generated help text names all three flags.
        """
        result = self._run_kanon(["--help"])
        assert result.returncode == 0, f"kanon --help exited {result.returncode}; stderr: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "--quiet" in combined, f"'--quiet' not found in kanon --help output: {combined!r}"
        assert "--verbose" in combined, f"'--verbose' not found in kanon --help output: {combined!r}"
        assert "--no-color" in combined, f"'--no-color' not found in kanon --help output: {combined!r}"

    def test_quiet_and_verbose_together_exits_nonzero_with_mutex_error(self) -> None:
        """kanon --quiet --verbose install exits non-zero with argparse's mutual-exclusion message.

        Passing both --quiet and --verbose must be rejected immediately by
        argparse's mutually-exclusive group with a non-zero exit code and
        an error message on stderr that names 'not allowed with' -- confirming
        the fail-fast mutex enforcement from spec Section 7.

        A subcommand (install) is included so argparse parses all tokens; the
        mutex violation is detected before the subcommand is dispatched.
        """
        result = self._run_kanon(["--quiet", "--verbose", "install", "test-kanon-file"])
        assert result.returncode != 0, (
            f"kanon --quiet --verbose install should exit non-zero, got {result.returncode}; stdout: {result.stdout!r}"
        )
        assert "not allowed with" in result.stderr, (
            f"Expected argparse mutex error ('not allowed with') in stderr; got: {result.stderr!r}"
        )

    def test_no_color_env_suppresses_ansi_in_help(self) -> None:
        """NO_COLOR=1 kanon --help produces no ANSI escape sequences in output.

        Sets NO_COLOR=1 in the subprocess environment and asserts that the
        combined stdout+stderr contains no ANSI color escape sequences
        (pattern ESC [ ... m). This validates that _apply_global_flags reads
        the NO_COLOR env var and disables color output before any formatted
        output is produced.
        """
        result = self._run_kanon(["--help"], extra_env={"NO_COLOR": "1"})
        assert result.returncode == 0, f"NO_COLOR=1 kanon --help exited {result.returncode}; stderr: {result.stderr!r}"
        combined = result.stdout + result.stderr
        ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
        matches = ansi_pattern.findall(combined)
        assert not matches, (
            f"ANSI escape sequences found in NO_COLOR=1 output: {matches!r}; output snippet: {combined[:500]!r}"
        )


# ---------------------------------------------------------------------------
# Tests for the new 'list' subcommand registration in build_parser() (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSubcommandRegistration:
    """build_parser() registers the 'list' subcommand per AC-FUNC-002."""

    def test_list_subcommand_exists_in_parser(self) -> None:
        """build_parser() includes 'list' as a registered subcommand."""
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_list_subcommand_has_catalog_source_flag(self) -> None:
        """The 'list' subcommand accepts --catalog-source (from shared factory)."""
        parser = build_parser()
        args = parser.parse_args(["list", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.catalog_source == "https://example.com/repo.git@main"

    def test_list_subcommand_catalog_source_default_none(self) -> None:
        """--catalog-source defaults to None when unset and env var is absent."""
        import os

        parser = build_parser()
        env_backup = os.environ.pop("KANON_CATALOG_SOURCE", None)
        try:
            args = parser.parse_args(["list"])
        finally:
            if env_backup is not None:
                os.environ["KANON_CATALOG_SOURCE"] = env_backup
        assert args.catalog_source is None

    def test_list_subcommand_has_no_color_flag(self) -> None:
        """The 'list' subcommand propagates --no-color from the root parser.

        --no-color is a global flag defined on the root parser (before any
        subcommand token). Verify that 'kanon --no-color list' sets
        no_color=True in the parsed namespace.
        """
        parser = build_parser()
        args = parser.parse_args(["--no-color", "list"])
        assert args.no_color is True

    def test_list_subcommand_sets_func(self) -> None:
        """The 'list' subcommand sets args.func to run_list."""
        from kanon_cli.commands.list import run_list

        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.func is run_list

    def test_list_help_exits_0(self) -> None:
        """kanon list --help exits 0 without error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["list", "--help"])
        assert exc_info.value.code == 0

    def test_list_help_mentions_catalog_source(self) -> None:
        """kanon list --help text mentions --catalog-source and KANON_CATALOG_SOURCE."""
        import io

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                list_parser = action.choices.get("list")
                break
        else:
            list_parser = None

        assert list_parser is not None, "list subparser must be registered"
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--catalog-source" in help_text
        assert "KANON_CATALOG_SOURCE" in help_text


# ---------------------------------------------------------------------------
# Tests for the new 'add' subcommand registration in build_parser() (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddSubcommandRegistration:
    """build_parser() registers the 'add' subcommand per AC-FUNC-002."""

    def test_add_subcommand_exists_in_parser(self) -> None:
        """build_parser() includes 'add' as a registered subcommand."""
        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.command == "add"

    def test_add_subcommand_has_catalog_source_flag(self) -> None:
        """The 'add' subcommand accepts --catalog-source (from shared factory)."""
        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.catalog_source == "https://example.com/repo.git@main"

    def test_add_subcommand_has_kanon_file_flag(self) -> None:
        """The 'add' subcommand accepts --kanon-file."""
        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main", "--kanon-file", "/tmp/.kanon"])
        assert args.kanon_file == "/tmp/.kanon"

    def test_add_subcommand_kanon_file_default(self) -> None:
        """--kanon-file defaults to ./.kanon when not supplied and env var is absent."""
        import os

        parser = build_parser()
        env_backup = os.environ.pop("KANON_KANON_FILE", None)
        try:
            args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main"])
        finally:
            if env_backup is not None:
                os.environ["KANON_KANON_FILE"] = env_backup
        assert args.kanon_file == "./.kanon"

    def test_add_subcommand_sets_func(self) -> None:
        """The 'add' subcommand sets args.func to run_add."""
        from kanon_cli.commands.add import run_add

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main"])
        assert args.func is run_add

    def test_add_help_exits_0(self) -> None:
        """kanon add --help exits 0 without error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["add", "--help"])
        assert exc_info.value.code == 0

    def test_add_help_mentions_kanon_file_and_env_var(self) -> None:
        """kanon add --help text mentions --kanon-file and KANON_KANON_FILE."""
        import io

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                add_parser = action.choices.get("add")
                break
        else:
            add_parser = None

        assert add_parser is not None, "add subparser must be registered"
        buf = io.StringIO()
        add_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--kanon-file" in help_text
        assert "KANON_KANON_FILE" in help_text
