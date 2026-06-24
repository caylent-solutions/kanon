"""Integration tests for all CLI entry points.

Exercises the main() dispatcher and build_parser() for all kanon subcommands.
Tests verify correct argument parsing, dispatch to the right handler, and
that missing/invalid subcommands exit with the correct exit codes.

Covers the full 3.0.0 command set (search/add/remove/outdated/why/marketplace/
doctor/install/clean/validate) and asserts that the superseded ``list``
(renamed to ``search``) and removed ``bootstrap`` tokens are rejected by
argparse as unknown commands (exit 2).
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

    @pytest.mark.parametrize(
        "argv,expected_command",
        [
            pytest.param(["search"], "search", id="search"),
            pytest.param(["add", "widget"], "add", id="add"),
            pytest.param(["remove", "widget"], "remove", id="remove"),
            pytest.param(["outdated"], "outdated", id="outdated"),
            pytest.param(["why", "widget"], "why", id="why"),
            pytest.param(["marketplace", "status"], "marketplace", id="marketplace"),
            pytest.param(["doctor"], "doctor", id="doctor"),
        ],
    )
    def test_3_0_0_command_set_resolves(self, argv: list[str], expected_command: str) -> None:
        """Every 3.0.0 top-level command resolves to its handler via the parser.

        The search rename and the marketplace command are part of the 3.0.0
        surface; each must parse and set ``args.command`` to its own name so the
        dispatcher routes it correctly.
        """
        parser = build_parser()
        args = parser.parse_args(argv)
        assert args.command == expected_command

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

    def test_bootstrap_subcommand_not_registered(self) -> None:
        # 'bootstrap' was removed in a major release. It is no longer a
        # registered subcommand, so argparse rejects it as an invalid choice
        # and exits 2 (the argparse usage-error code).
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["bootstrap", "kanon"])
        assert exc_info.value.code == 2

    def test_list_subcommand_not_registered(self) -> None:
        # 'list' was renamed to 'search' in the 3.0.0 release. The old token is
        # no longer a registered subcommand, so argparse rejects it as an
        # invalid choice and exits 2 (the argparse usage-error code).
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["list"])
        assert exc_info.value.code == 2

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

    def test_bootstrap_invocation_exits_2_as_unknown_command(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`kanon bootstrap ...` exits 2 as an unknown command after removal.

        'bootstrap' was removed in a major release and is no longer registered
        or intercepted, so main() lets argparse reject it as an invalid choice
        and exit 2, just like any other unknown subcommand.
        """
        with pytest.raises(SystemExit) as exc:
            main(["bootstrap", "list"])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err
        assert "bootstrap" in captured.err

    def test_list_invocation_exits_2_as_unknown_command(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`kanon list ...` exits 2 as an unknown command after the search rename.

        'list' was renamed to 'search' in 3.0.0 and is no longer registered or
        intercepted, so main() lets argparse reject it as an invalid choice and
        exit 2, just like any other unknown subcommand. The new surface is
        reachable as `kanon search`.
        """
        with pytest.raises(SystemExit) as exc:
            main(["list"])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err
        assert "list" in captured.err

    def test_validate_xml_with_explicit_repo_root_exits_1_when_empty(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "xml", "--repo-root", str(tmp_path)])
        assert exc_info.value.code == 1
