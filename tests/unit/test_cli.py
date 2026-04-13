"""Tests for the argparse CLI entry point."""

import pytest

from kanon_cli.cli import build_parser, main


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

    def test_install_missing_path_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["install"])
        assert exc_info.value.code == 2
