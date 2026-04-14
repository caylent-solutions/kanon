"""Tests for the clean command handler."""

import argparse
import pathlib
import types
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.clean import _run, register


@pytest.mark.unit
class TestCleanCommand:
    def test_delegates_to_core(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
        )
        args = types.SimpleNamespace(kanonenv_path=kanonenv)
        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            _run(args)
            mock_clean.assert_called_once_with(kanonenv)


@pytest.mark.unit
class TestCleanRegister:
    def test_kanonenv_path_is_optional(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        parsed = parser.parse_args(["clean"])
        assert parsed.kanonenv_path is None

    def test_explicit_path_accepted(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        parsed = parser.parse_args(["clean", "/tmp/test-kanonenv"])
        assert str(parsed.kanonenv_path) == "/tmp/test-kanonenv"


@pytest.mark.unit
class TestCleanAutoDiscovery:
    def test_no_arg_calls_find_kanonenv(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = None

        with (
            patch("kanon_cli.commands.clean.find_kanonenv", return_value=kanonenv) as mock_find,
            patch("kanon_cli.commands.clean.clean"),
        ):
            _run(args)
            mock_find.assert_called_once()

    def test_explicit_path_skips_discovery(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.clean.find_kanonenv") as mock_find,
            patch("kanon_cli.commands.clean.clean"),
        ):
            _run(args)
            mock_find.assert_not_called()

    def test_auto_discover_not_found_exits(self) -> None:
        args = MagicMock()
        args.kanonenv_path = None

        with (
            patch(
                "kanon_cli.commands.clean.find_kanonenv",
                side_effect=FileNotFoundError("No .kanon file found"),
            ),
            pytest.raises(SystemExit),
        ):
            _run(args)

    def test_clean_error_exits(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("NO_SOURCES=true\n")
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with pytest.raises(SystemExit):
            _run(args)
