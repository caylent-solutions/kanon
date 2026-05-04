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


_VALID_KANONENV = (
    "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
)


@pytest.mark.unit
class TestCleanResolvesExplicitPath:
    """``_run`` must resolve an explicit ``kanonenv_path`` to an absolute path.

    ``kanon clean .kanon`` (relative) previously passed ``PosixPath('.kanon')``
    straight through to ``clean()``, which in turn propagates into the repo
    manifest parser where ``manifest_file`` must be absolute. The CLI handler
    must normalize at the boundary to match ``find_kanonenv()``'s contract.
    """

    def test_relative_kanonenv_path_is_resolved_to_abspath(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        """``_run`` must resolve ``PosixPath('.kanon')`` to an absolute path before clean()."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_VALID_KANONENV)
        monkeypatch.chdir(tmp_path)

        args = MagicMock()
        args.kanonenv_path = pathlib.Path(".kanon")

        received: list[pathlib.Path] = []

        def _capture_clean(path):
            received.append(path)

        with patch("kanon_cli.commands.clean.clean", side_effect=_capture_clean):
            _run(args)

        assert len(received) == 1, f"clean() must be called exactly once, got {len(received)} calls"
        resolved = received[0]
        assert resolved.is_absolute(), f"clean() must receive an absolute path, got {resolved!r}"
        assert resolved == kanonenv.resolve(), (
            f"clean() must receive the resolved .kanon path {kanonenv.resolve()!r}, got {resolved!r}"
        )

    def test_absolute_kanonenv_path_is_unchanged(self, tmp_path: pathlib.Path) -> None:
        """``_run`` must pass an already-absolute path through to clean() unchanged."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_VALID_KANONENV)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        received: list[pathlib.Path] = []

        def _capture_clean(path):
            received.append(path)

        with patch("kanon_cli.commands.clean.clean", side_effect=_capture_clean):
            _run(args)

        assert received == [kanonenv.resolve()], f"clean() must receive the resolved absolute path, got {received!r}"

    def test_missing_relative_kanonenv_fails_fast_with_clear_message(
        self, tmp_path: pathlib.Path, monkeypatch, capsys
    ) -> None:
        """``_run`` must fail-fast with an actionable message when the .kanon file does not exist."""
        monkeypatch.chdir(tmp_path)
        args = MagicMock()
        args.kanonenv_path = pathlib.Path(".kanon")

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            with pytest.raises(SystemExit) as exc_info:
                _run(args)

        assert exc_info.value.code == 1, f"missing .kanon must exit 1, got {exc_info.value.code!r}"
        mock_clean.assert_not_called()
        captured = capsys.readouterr()
        assert ".kanon file not found" in captured.err, (
            f"stderr must mention '.kanon file not found', got {captured.err!r}"
        )
