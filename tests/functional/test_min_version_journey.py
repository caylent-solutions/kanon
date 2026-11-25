"""Functional journey: a .kanon's KANON_MIN_VERSION stops an older kanon at the CLI.

Runs the real ``kanon`` CLI in a subprocess against a ``.kanon`` that demands a
newer kanon than the one under test, and asserts the operator sees exit 1, an
``ERROR:`` line naming both versions, and the upgrade command, with the
``.kanon`` left untouched. A second case shows that setting
``KANON_MIN_VERSION`` in the shell cannot lower the file's minimum.
"""

import pathlib

import pytest
from packaging.version import Version

from kanon_cli import __version__
from kanon_cli.constants import KANON_MIN_VERSION_KEY, KANON_SKIP_UPDATE_CHECK_ENV, KANON_UPDATE_UPGRADE_COMMAND
from tests.functional.conftest import _run_kanon

_SOURCE_BLOCK = (
    "KANON_SOURCE_primary_URL=https://example.com/primary.git\n"
    "KANON_SOURCE_primary_REF=main\n"
    "KANON_SOURCE_primary_PATH=repo-specs/manifest.xml\n"
    "KANON_SOURCE_primary_NAME=primary\n"
)


def _write_kanon_requiring_next_major(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    required = f"{Version(__version__).major + 1}.0.0"
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(f"{KANON_MIN_VERSION_KEY}={required}\n\n{_SOURCE_BLOCK}", encoding="utf-8")
    return kanon_file, required


@pytest.mark.functional
class TestMinVersionJourney:
    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["install"], id="install"),
            pytest.param(["clean"], id="clean"),
            pytest.param(["remove", "primary"], id="remove"),
            pytest.param(["add", "--catalog-source", "https://example.com/catalog.git@main", "primary"], id="add"),
        ],
    )
    def test_older_kanon_is_refused_with_upgrade_command(self, tmp_path: pathlib.Path, argv: list[str]) -> None:
        kanon_file, required = _write_kanon_requiring_next_major(tmp_path)
        before = kanon_file.read_bytes()

        result = _run_kanon(*argv, cwd=tmp_path, extra_env={KANON_SKIP_UPDATE_CHECK_ENV: "1"})

        assert result.returncode == 1, result.stderr
        assert result.stderr.startswith("ERROR: ")
        assert f"requires kanon {required} or later; this is kanon {__version__}" in result.stderr
        assert KANON_UPDATE_UPGRADE_COMMAND in result.stderr
        assert kanon_file.read_bytes() == before

    def test_shell_value_cannot_lower_the_file_minimum(self, tmp_path: pathlib.Path) -> None:
        kanon_file, required = _write_kanon_requiring_next_major(tmp_path)

        result = _run_kanon(
            "install",
            cwd=tmp_path,
            extra_env={KANON_SKIP_UPDATE_CHECK_ENV: "1", KANON_MIN_VERSION_KEY: "0.0.0"},
        )

        assert result.returncode == 1, result.stderr
        assert f"requires kanon {required} or later" in result.stderr
