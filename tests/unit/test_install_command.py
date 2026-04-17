"""Tests for the install command handler."""

import argparse
import pathlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestRunNoPipx:
    def test_run_does_not_invoke_pipx(self, tmp_path) -> None:
        """_run() must never invoke pipx at any point during execution."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "GITBASE=https://example.com/\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install.install"),
            patch("subprocess.run") as mock_subprocess,
        ):
            _run(args)
            for actual_call in mock_subprocess.call_args_list:
                cmd = actual_call[0][0] if actual_call[0] else actual_call[1].get("args", [])
                assert "pipx" not in cmd, f"_run() invoked pipx unexpectedly: {actual_call}"


@pytest.mark.unit
class TestRunPartialConfig:
    def test_missing_kanonenv_file_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        args = MagicMock()
        args.kanonenv_path = tmp_path / "nonexistent"

        with pytest.raises(SystemExit):
            _run(args)

    def test_invalid_kanonenv_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("NO_SOURCES_DEFINED=true\n")
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with pytest.raises(SystemExit):
            _run(args)


_VALID_KANONENV = (
    "GITBASE=https://example.com/\n"
    "KANON_MARKETPLACE_INSTALL=false\n"
    "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
    "KANON_SOURCE_test_REVISION=main\n"
    "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
)


@pytest.mark.unit
class TestRunResolvesExplicitPath:
    """``_run`` must resolve an explicit ``kanonenv_path`` to an absolute path.

    The downstream repo manifest parser at
    ``src/kanon_cli/repo/manifest_xml.py:410`` enforces
    ``manifest_file == os.path.abspath(manifest_file)``. When a user invokes
    ``kanon install .kanon`` from the containing directory, argparse stores
    ``pathlib.Path('.kanon')`` as-is (relative) and the repo parser later
    raises ``ManifestParseError: manifest_file must be abspath``. ``_run`` must
    normalize the argument at the CLI boundary -- matching the resolution
    behavior of ``find_kanonenv()`` used by auto-discovery -- and fail-fast
    with a clear message if the file does not exist.
    """

    def test_relative_kanonenv_path_is_resolved_to_abspath(self, tmp_path, monkeypatch) -> None:
        """``_run`` must resolve ``PosixPath('.kanon')`` to an absolute path before install()."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_VALID_KANONENV)
        monkeypatch.chdir(tmp_path)

        args = MagicMock()
        args.kanonenv_path = pathlib.Path(".kanon")

        received: list[pathlib.Path] = []

        def _capture_install(path):
            received.append(path)

        with patch("kanon_cli.commands.install.install", side_effect=_capture_install):
            _run(args)

        assert len(received) == 1, f"install() must be called exactly once, got {len(received)} calls"
        resolved = received[0]
        assert resolved.is_absolute(), f"install() must receive an absolute path, got {resolved!r}"
        assert resolved == kanonenv.resolve(), (
            f"install() must receive the resolved .kanon path {kanonenv.resolve()!r}, got {resolved!r}"
        )

    def test_absolute_kanonenv_path_is_unchanged(self, tmp_path) -> None:
        """``_run`` must pass an already-absolute path through to install() unchanged."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_VALID_KANONENV)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        received: list[pathlib.Path] = []

        def _capture_install(path):
            received.append(path)

        with patch("kanon_cli.commands.install.install", side_effect=_capture_install):
            _run(args)

        assert received == [kanonenv.resolve()], f"install() must receive the resolved absolute path, got {received!r}"

    def test_missing_relative_kanonenv_fails_fast_with_clear_message(self, tmp_path, monkeypatch, capsys) -> None:
        """``_run`` must fail-fast with an actionable message when the .kanon file does not exist."""
        from kanon_cli.commands.install import _run

        monkeypatch.chdir(tmp_path)
        args = MagicMock()
        args.kanonenv_path = pathlib.Path(".kanon")

        with patch("kanon_cli.commands.install.install") as mock_install:
            with pytest.raises(SystemExit) as exc_info:
                _run(args)

        assert exc_info.value.code == 1, f"missing .kanon must exit 1, got {exc_info.value.code!r}"
        mock_install.assert_not_called()
        captured = capsys.readouterr()
        assert ".kanon file not found" in captured.err, (
            f"stderr must mention '.kanon file not found', got {captured.err!r}"
        )


@pytest.mark.unit
class TestRegister:
    def test_registers_install_subcommand(self) -> None:
        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        parsed = parser.parse_args(["install", "/tmp/test-kanonenv"])
        assert hasattr(parsed, "func")
        assert str(parsed.kanonenv_path) == "/tmp/test-kanonenv"

    def test_kanonenv_path_is_optional(self) -> None:
        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        parsed = parser.parse_args(["install"])
        assert parsed.kanonenv_path is None


@pytest.mark.unit
class TestAutoDiscovery:
    def test_no_arg_calls_find_kanonenv(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "GITBASE=https://example.com/\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = None

        with (
            patch("kanon_cli.commands.install.find_kanonenv", return_value=kanonenv) as mock_find,
            patch("kanon_cli.commands.install.install"),
        ):
            _run(args)
            mock_find.assert_called_once()

    def test_explicit_path_skips_discovery(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "GITBASE=https://example.com/\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install.find_kanonenv") as mock_find,
            patch("kanon_cli.commands.install.install"),
        ):
            _run(args)
            mock_find.assert_not_called()

    def test_auto_discover_not_found_exits(self) -> None:
        from kanon_cli.commands.install import _run

        args = MagicMock()
        args.kanonenv_path = None

        with (
            patch(
                "kanon_cli.commands.install.find_kanonenv",
                side_effect=FileNotFoundError("No .kanon file found"),
            ),
            pytest.raises(SystemExit),
        ):
            _run(args)
