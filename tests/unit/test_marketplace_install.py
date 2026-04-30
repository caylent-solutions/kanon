"""End-to-end install-path coverage for the marketplace plugins[] contract.

These tests exercise the full ``install_marketplace_plugins`` orchestration
against ``marketplace.json`` payloads that declare plugins via the
top-level ``plugins`` array (the contract introduced by E2-F3-S1-T5).

Each test mocks the external Claude CLI calls
(``register_marketplace`` / ``install_plugin``) and asserts that the
orchestration:
  - discovers plugin names from ``marketplace.json plugins[]``
  - registers each marketplace exactly once
  - calls ``install_plugin`` once per declared plugin
  - emits the install summary in the expected ``"<X> plugins installed"`` form
  - propagates failures via ``SystemExit`` rather than silently completing

Implements AC-TEST-001 of E2-F3-S1-T5.
"""

import json
import pathlib

import pytest
from unittest.mock import patch

from kanon_cli.core.marketplace import install_marketplace_plugins


def _write_marketplace(parent: pathlib.Path, name: str, plugin_names: list[str]) -> pathlib.Path:
    """Create a marketplace dir with marketplace.json declaring plugin_names."""
    mp_dir = parent / name
    (mp_dir / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": name, "plugins": [{"name": p} for p in plugin_names]}
    (mp_dir / ".claude-plugin" / "marketplace.json").write_text(json.dumps(manifest))
    return mp_dir


@pytest.mark.unit
class TestSinglePluginInstall:
    def test_install_plugin_called_once(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-one", ["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(mp_root)
        mock_install.assert_called_once_with("/usr/bin/claude", "plugin-a", "mp-one")

    def test_summary_reports_one_plugin(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-one", ["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            install_marketplace_plugins(mp_root)
        captured = capsys.readouterr()
        assert "1 marketplaces processed" in captured.out
        assert "1 registered" in captured.out
        assert "1 plugins installed" in captured.out


@pytest.mark.unit
class TestMultiPluginInstall:
    def test_install_plugin_called_per_array_entry(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-multi", ["plugin-a", "plugin-b", "plugin-c"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(mp_root)
        assert mock_install.call_count == 3
        installed_names = {call.args[1] for call in mock_install.call_args_list}
        assert installed_names == {"plugin-a", "plugin-b", "plugin-c"}

    def test_summary_reports_three_plugins(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-multi", ["plugin-a", "plugin-b", "plugin-c"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            install_marketplace_plugins(mp_root)
        captured = capsys.readouterr()
        assert "3 plugins installed" in captured.out


@pytest.mark.unit
class TestEmptyPluginsArrayInstall:
    def test_no_install_calls_when_array_empty(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-empty", [])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(mp_root)
        assert mock_install.call_count == 0

    def test_summary_reports_zero_plugins(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-empty", [])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            install_marketplace_plugins(mp_root)
        captured = capsys.readouterr()
        assert "0 plugins installed" in captured.out


@pytest.mark.unit
class TestInstallOrderingAndArguments:
    def test_register_called_before_install(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-one", ["plugin-a"])
        call_order: list[str] = []
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch(
                "kanon_cli.core.marketplace.register_marketplace",
                side_effect=lambda *_a, **_kw: call_order.append("register") or True,
            ),
            patch(
                "kanon_cli.core.marketplace.install_plugin",
                side_effect=lambda *_a, **_kw: call_order.append("install") or True,
            ),
        ):
            install_marketplace_plugins(mp_root)
        assert call_order == ["register", "install"]

    def test_install_uses_marketplace_name_from_manifest(self, tmp_path: pathlib.Path) -> None:
        """The marketplace_name passed to install_plugin comes from marketplace.json,
        not from the directory basename. Use a directory name that differs from
        the declared name to verify the source.
        """
        mp_root = tmp_path / "marketplaces"
        mp_dir = mp_root / "dir-basename"
        (mp_dir / ".claude-plugin").mkdir(parents=True)
        manifest = {"name": "declared-name", "plugins": [{"name": "plugin-a"}]}
        (mp_dir / ".claude-plugin" / "marketplace.json").write_text(json.dumps(manifest))
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(mp_root)
        mock_install.assert_called_once_with("/usr/bin/claude", "plugin-a", "declared-name")


@pytest.mark.unit
class TestInstallFailureExits:
    def test_register_failure_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-one", ["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=False),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install_marketplace_plugins(mp_root)
            assert exc_info.value.code == 1

    def test_plugin_install_failure_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        mp_root = tmp_path / "marketplaces"
        _write_marketplace(mp_root, "mp-one", ["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=False),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install_marketplace_plugins(mp_root)
            assert exc_info.value.code == 1
