"""Integration tests for all CLI entry points (14 tests).

Exercises the main() dispatcher and build_parser() for all kanon subcommands.
Tests verify correct argument parsing, dispatch to the right handler, and
that missing/invalid subcommands exit with the correct exit codes.
"""

import pathlib

import pytest

from kanon_cli.cli import build_parser, main


# ---------------------------------------------------------------------------
# AC-FUNC-009: CLI entry points integration tests (14 tests)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestParserConstruction:
    """Verify the argument parser registers all expected subcommands."""

    def test_parser_prog_is_kanon(self) -> None:
        parser = build_parser()
        assert parser.prog == "kanon"

    def test_install_subcommand_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "/tmp/.kanon"])
        assert args.command == "install"

    def test_clean_subcommand_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "/tmp/.kanon"])
        assert args.command == "clean"

    def test_validate_xml_subcommand_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "xml"])
        assert args.command == "validate"
        assert args.validate_command == "xml"

    def test_validate_marketplace_subcommand_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "marketplace"])
        assert args.command == "validate"
        assert args.validate_command == "marketplace"

    def test_bootstrap_subcommand_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["bootstrap", "kanon"])
        assert args.command == "bootstrap"

    def test_validate_repo_root_option(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "xml", "--repo-root", "/some/path"])
        assert str(args.repo_root) == "/some/path"


@pytest.mark.integration
class TestMainDispatch:
    """Verify main() dispatch exits correctly for valid and invalid inputs."""

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

    def test_install_no_arg_no_kanonenv_exits_1(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["install"])
        assert exc_info.value.code == 1

    def test_bootstrap_list_exits_0(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        main(["bootstrap", "list"])

    def test_bootstrap_kanon_with_output_dir(self, tmp_path: pathlib.Path) -> None:
        output = tmp_path / "project"
        main(["bootstrap", "kanon", "--output-dir", str(output)])
        assert (output / ".kanon").is_file()

    def test_validate_xml_with_explicit_repo_root_exits_1_when_empty(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "xml", "--repo-root", str(tmp_path)])
        assert exc_info.value.code == 1
