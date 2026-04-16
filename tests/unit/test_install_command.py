"""Tests for the install command handler."""

import argparse
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
class TestDeprecationWarnings:
    """Tests for REPO_URL and REPO_REV deprecation warnings."""

    _BASE_CONFIG = (
        "GITBASE=https://example.com/\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
        "KANON_SOURCE_test_REVISION=main\n"
        "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
    )

    def test_repo_url_in_globals_emits_deprecation_warning_to_stderr(self, tmp_path, capsys) -> None:
        """When only REPO_URL is present, _run() emits a per-key deprecation warning mentioning REPO_URL."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_URL=https://example.com/repo.git\n" + self._BASE_CONFIG)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with patch("kanon_cli.commands.install.install"):
            _run(args)

        captured = capsys.readouterr()
        assert "REPO_URL" in captured.err, (
            f"Expected REPO_URL mentioned in deprecation warning to stderr, got: {captured.err!r}"
        )
        assert "deprecated" in captured.err.lower() or "deprecation" in captured.err.lower(), (
            f"Expected a deprecation warning in stderr when REPO_URL is set, got: {captured.err!r}"
        )
        assert "REPO_REV" not in captured.err, (
            f"Expected REPO_REV NOT mentioned when only REPO_URL is set, got: {captured.err!r}"
        )

    def test_repo_rev_in_globals_emits_deprecation_warning_to_stderr(self, tmp_path, capsys) -> None:
        """When only REPO_REV is present, _run() emits a per-key deprecation warning mentioning REPO_REV."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_REV=main\n" + self._BASE_CONFIG)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with patch("kanon_cli.commands.install.install"):
            _run(args)

        captured = capsys.readouterr()
        assert "REPO_REV" in captured.err, (
            f"Expected REPO_REV mentioned in deprecation warning to stderr, got: {captured.err!r}"
        )
        assert "deprecated" in captured.err.lower() or "deprecation" in captured.err.lower(), (
            f"Expected a deprecation warning in stderr when REPO_REV is set, got: {captured.err!r}"
        )
        assert "REPO_URL" not in captured.err, (
            f"Expected REPO_URL NOT mentioned when only REPO_REV is set, got: {captured.err!r}"
        )

    def test_both_keys_in_globals_emit_warnings_for_each(self, tmp_path, capsys) -> None:
        """When both REPO_URL and REPO_REV are present, a separate warning is emitted for each key."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_URL=https://example.com/repo.git\nREPO_REV=main\n" + self._BASE_CONFIG)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with patch("kanon_cli.commands.install.install"):
            _run(args)

        captured = capsys.readouterr()
        assert "REPO_URL" in captured.err, (
            f"Expected REPO_URL mentioned in deprecation warning to stderr, got: {captured.err!r}"
        )
        assert "REPO_REV" in captured.err, (
            f"Expected REPO_REV mentioned in deprecation warning to stderr, got: {captured.err!r}"
        )

    def test_neither_key_in_globals_emits_no_warning(self, tmp_path, capsys) -> None:
        """When neither REPO_URL nor REPO_REV are present in .kanon globals, no warning is emitted."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(self._BASE_CONFIG)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with patch("kanon_cli.commands.install.install"):
            _run(args)

        captured = capsys.readouterr()
        assert "deprecated" not in captured.err.lower(), (
            f"Expected no deprecation warning when REPO_URL and REPO_REV are absent, got: {captured.err!r}"
        )

    @pytest.mark.parametrize(
        "extra_config",
        [
            "REPO_URL=https://example.com/repo.git\n",
            "REPO_REV=main\n",
            "REPO_URL=https://example.com/repo.git\nREPO_REV=main\n",
        ],
    )
    def test_command_succeeds_when_deprecated_keys_present(self, tmp_path, extra_config) -> None:
        """The install command must not fail when REPO_URL or REPO_REV are present -- warn and continue."""
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(extra_config + self._BASE_CONFIG)
        args = MagicMock()
        args.kanonenv_path = kanonenv

        mock_install = MagicMock()
        with patch("kanon_cli.commands.install.install", mock_install):
            _run(args)

        mock_install.assert_called_once_with(kanonenv)


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
