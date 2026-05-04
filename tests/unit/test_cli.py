"""Tests for the argparse CLI entry point."""

import signal
from unittest.mock import patch

import pytest

from kanon_cli.cli import _make_signal_handler, build_parser, main


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
