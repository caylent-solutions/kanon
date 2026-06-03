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

    def test_bootstrap_list_exits_3_with_deprecation(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`kanon bootstrap list` exits 3 with the deprecation message; list arm."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            main(["bootstrap", "list"])
        assert exc.value.code == 3
        captured = capsys.readouterr()
        assert "DEPRECATED" in captured.err
        assert "major release" in captured.err
        assert "breaking change" in captured.err
        assert "docs/migration-bootstrap-to-add.md" in captured.err
        # The list-arm closest-replacement line points at `kanon list`.
        assert "kanon list --catalog-source <git-url>@<ref>" in captured.err

    def test_bootstrap_entry_exits_3_with_deprecation(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`kanon bootstrap kanon` exits 3 with the deprecation message; add arm."""
        with pytest.raises(SystemExit) as exc:
            main(["bootstrap", "kanon", "--output-dir", str(tmp_path / "project")])
        assert exc.value.code == 3
        captured = capsys.readouterr()
        assert "DEPRECATED" in captured.err
        assert "docs/migration-bootstrap-to-add.md" in captured.err
        # The entry-arm closest-replacement line names the entry.
        assert "kanon add kanon --catalog-source <git-url>@<ref>" in captured.err
        # The shim performs no work: --output-dir is never created.
        assert not (tmp_path / "project").exists()

    def test_bootstrap_unknown_flag_exits_3_not_argparse_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`kanon bootstrap history --marketplace-install` exits 3 (intercept before argparse)."""
        with pytest.raises(SystemExit) as exc:
            main(["bootstrap", "history", "--marketplace-install"])
        assert exc.value.code == 3
        captured = capsys.readouterr()
        assert "DEPRECATED" in captured.err
        assert "kanon add history --catalog-source <git-url>@<ref>" in captured.err
        assert "unrecognized arguments" not in captured.err

    def test_validate_xml_with_explicit_repo_root_exits_1_when_empty(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "xml", "--repo-root", str(tmp_path)])
        assert exc_info.value.code == 1
