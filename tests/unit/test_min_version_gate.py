"""Tests that install, add, remove and clean enforce KANON_MIN_VERSION before any work."""

import pathlib
from unittest.mock import patch

import pytest
from packaging.version import Version

from kanon_cli import __version__
from kanon_cli.cli import main
from kanon_cli.constants import KANON_MIN_VERSION_KEY, KANON_SKIP_UPDATE_CHECK_ENV, KANON_UPDATE_UPGRADE_COMMAND

_SOURCE_BLOCK = (
    "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
    "KANON_SOURCE_test_REF=main\n"
    "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
    "KANON_SOURCE_test_NAME=test\n"
)


def _next_major() -> str:
    return f"{Version(__version__).major + 1}.0.0"


_GATED_COMMANDS = [
    pytest.param(["install", "{kanon}"], "kanon_cli.commands.install.install", id="install"),
    pytest.param(["clean", "{kanon}"], "kanon_cli.commands.clean.clean", id="clean"),
    pytest.param(["clean", "--purge-all", "{kanon}"], "kanon_cli.commands.clean.clean", id="clean-purge-all"),
    pytest.param(
        ["add", "--catalog-source", "https://example.com/catalog.git@main", "--kanon-file", "{kanon}", "test"],
        "kanon_cli.commands.add._resolve_manifest_repo_for_add",
        id="add",
    ),
    pytest.param(
        ["remove", "--kanon-file", "{kanon}", "test"],
        "kanon_cli.commands.remove._collect_removal_lines",
        id="remove",
    ),
]


@pytest.fixture(autouse=True)
def _skip_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KANON_SKIP_UPDATE_CHECK_ENV, "1")


def _run_cli(argv_template: list[str], kanon_file: pathlib.Path) -> int:
    argv = [arg.format(kanon=kanon_file) for arg in argv_template]
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    return exc_info.value.code


@pytest.mark.unit
class TestGatedCommandsRefuseOldKanon:
    """Each gated command exits 1 before doing work when kanon is below the minimum."""

    @pytest.mark.parametrize(("argv_template", "downstream"), _GATED_COMMANDS)
    def test_below_minimum_exits_before_work(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        argv_template: list[str],
        downstream: str,
    ) -> None:
        required = _next_major()
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}={required}\n" + _SOURCE_BLOCK, encoding="utf-8")
        before = kanon_file.read_bytes()

        with patch(downstream) as downstream_mock:
            exit_code = _run_cli(argv_template, kanon_file)

        assert exit_code == 1
        downstream_mock.assert_not_called()
        assert kanon_file.read_bytes() == before
        stderr = capsys.readouterr().err
        assert f"requires kanon {required} or later" in stderr
        assert KANON_UPDATE_UPGRADE_COMMAND in stderr

    @pytest.mark.parametrize(("argv_template", "downstream"), _GATED_COMMANDS)
    def test_malformed_minimum_exits_before_work(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        argv_template: list[str],
        downstream: str,
    ) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}=latest\n" + _SOURCE_BLOCK, encoding="utf-8")

        with patch(downstream) as downstream_mock:
            exit_code = _run_cli(argv_template, kanon_file)

        assert exit_code == 1
        downstream_mock.assert_not_called()
        assert f"Invalid {KANON_MIN_VERSION_KEY}='latest'" in capsys.readouterr().err


@pytest.mark.unit
class TestGatedCommandsAllowCurrentKanon:
    """A minimum at the running version lets each command reach its work."""

    def test_install_reaches_core_install(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}={__version__}\n" + _SOURCE_BLOCK, encoding="utf-8")

        with patch("kanon_cli.commands.install.install") as install_mock:
            main(["install", str(kanon_file)])

        install_mock.assert_called_once()

    def test_clean_reaches_core_clean(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}={__version__}\n" + _SOURCE_BLOCK, encoding="utf-8")

        with patch("kanon_cli.commands.clean.clean") as clean_mock:
            main(["clean", str(kanon_file)])

        clean_mock.assert_called_once()

    def test_remove_drops_block_and_keeps_minimum(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}={__version__}\n\n" + _SOURCE_BLOCK, encoding="utf-8")

        main(["remove", "--kanon-file", str(kanon_file), "test"])

        remaining = kanon_file.read_text(encoding="utf-8")
        assert f"{KANON_MIN_VERSION_KEY}={__version__}" in remaining
        assert "KANON_SOURCE_test_URL" not in remaining

    def test_clean_purge_all_without_kanon_is_not_gated(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--purge-all with no .kanon never reads a file, so there is nothing to enforce."""
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.clean._purge_home_only") as purge_mock:
            main(["clean", "--purge-all", str(tmp_path / ".kanon")])

        purge_mock.assert_called_once()
