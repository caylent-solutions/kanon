"""Tests for marketplace shared module (core/marketplace.py).

Validates marketplace operations used by both install and clean:
  - Claude binary location
  - Marketplace entry discovery
  - Marketplace name reading from JSON
  - Plugin discovery from JSON
  - Marketplace registration, plugin install/uninstall, marketplace removal
  - Full install/uninstall orchestration
  - Bug fix: remove_marketplace passes name, not path
"""

import json
import pathlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.marketplace import (
    _get_timeout,
    discover_marketplace_entries,
    discover_plugins,
    install_marketplace_plugins,
    install_plugin,
    locate_claude_binary,
    read_marketplace_name,
    register_marketplace,
    remove_marketplace,
    uninstall_marketplace_plugins,
    uninstall_plugin,
)


def _create_marketplace(parent_dir: pathlib.Path, name: str, plugins: list[str] | None = None) -> pathlib.Path:
    """Helper to create a marketplace directory structure with marketplace.json and optional plugins.

    Creates parent_dir/name/.claude-plugin/marketplace.json and returns parent_dir/name.
    """
    mp_dir = parent_dir / name
    mp_dir.mkdir(parents=True, exist_ok=True)
    claude_plugin = mp_dir / ".claude-plugin"
    claude_plugin.mkdir(exist_ok=True)
    (claude_plugin / "marketplace.json").write_text(json.dumps({"name": name}))
    for plugin_name in plugins or []:
        plugin_dir = mp_dir / plugin_name / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": plugin_name}))
    return mp_dir


@pytest.mark.unit
class TestLocateClaudeBinary:
    def test_found(self) -> None:
        with patch("kanon_cli.core.marketplace.shutil.which", return_value="/usr/bin/claude"):
            result = locate_claude_binary()
            assert "claude" in result

    def test_not_found_exits(self) -> None:
        with patch("kanon_cli.core.marketplace.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                locate_claude_binary()
            assert exc_info.value.code == 1


@pytest.mark.unit
class TestDiscoverMarketplaceEntries:
    def test_discovers_directories(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "marketplace-a").mkdir()
        (tmp_path / "marketplace-b").mkdir()
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 2
        assert entries[0].name == "marketplace-a"

    def test_skips_hidden(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0].name == "visible"

    def test_skips_broken_symlinks(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "good").mkdir()
        (tmp_path / "broken-link").symlink_to(tmp_path / "nonexistent")
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0].name == "good"

    def test_empty_directory(self, tmp_path: pathlib.Path) -> None:
        entries = discover_marketplace_entries(tmp_path)
        assert entries == []


@pytest.mark.unit
class TestReadMarketplaceName:
    def test_reads_name(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "test-marketplace")
        assert read_marketplace_name(mp) == "test-marketplace"

    def test_missing_file_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_marketplace_name(tmp_path)

    def test_missing_name_field_raises(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "bad"
        claude_plugin = mp_dir / ".claude-plugin"
        claude_plugin.mkdir(parents=True)
        (claude_plugin / "marketplace.json").write_text(json.dumps({"version": "1.0"}))
        with pytest.raises(KeyError):
            read_marketplace_name(mp_dir)

    def test_invalid_json_raises(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "corrupt"
        claude_plugin = mp_dir / ".claude-plugin"
        claude_plugin.mkdir(parents=True)
        (claude_plugin / "marketplace.json").write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            read_marketplace_name(mp_dir)


@pytest.mark.unit
class TestDiscoverPlugins:
    def test_discovers_plugins(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp", plugins=["plugin-a", "plugin-b"])
        plugins = discover_plugins(mp)
        assert len(plugins) == 2
        names = [name for name, _ in plugins]
        assert "plugin-a" in names
        assert "plugin-b" in names

    def test_skips_non_plugin_dirs(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp", plugins=["real-plugin"])
        (mp / "not-a-plugin").mkdir()
        plugins = discover_plugins(mp)
        assert len(plugins) == 1
        assert plugins[0][0] == "real-plugin"

    def test_empty_marketplace(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp")
        plugins = discover_plugins(mp)
        assert plugins == []


@pytest.mark.unit
class TestGetTimeout:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_TIMEOUT_VAR", raising=False)
        result = _get_timeout("TEST_TIMEOUT_VAR", default=42)
        assert result == 42

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TIMEOUT_VAR", "60")
        result = _get_timeout("TEST_TIMEOUT_VAR")
        assert result == 60

    def test_invalid_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TIMEOUT_VAR", "not-a-number")
        with pytest.raises(SystemExit):
            _get_timeout("TEST_TIMEOUT_VAR")

    def test_zero_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TIMEOUT_VAR", "0")
        with pytest.raises(SystemExit):
            _get_timeout("TEST_TIMEOUT_VAR")

    def test_negative_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TIMEOUT_VAR", "-5")
        with pytest.raises(SystemExit):
            _get_timeout("TEST_TIMEOUT_VAR")


@pytest.mark.unit
class TestRegisterMarketplace:
    def test_success(self, tmp_path: pathlib.Path) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = register_marketplace("/usr/bin/claude", tmp_path / "mp")
            assert result is True
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/usr/bin/claude", "plugin", "marketplace", "add", str(tmp_path / "mp")]

    def test_failure(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = register_marketplace("/usr/bin/claude", pathlib.Path("/mp"))
            assert result is False

    def test_timeout(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            result = register_marketplace("/usr/bin/claude", pathlib.Path("/mp"))
            assert result is False


@pytest.mark.unit
class TestInstallPlugin:
    def test_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = install_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is True
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/usr/bin/claude", "plugin", "install", "my-plugin@my-marketplace", "--scope", "user"]

    def test_failure(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = install_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is False

    def test_timeout(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            result = install_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is False


@pytest.mark.unit
class TestUninstallPlugin:
    def test_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is True
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/usr/bin/claude", "plugin", "uninstall", "my-plugin@my-marketplace", "--scope", "user"]

    def test_not_found_is_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Plugin not found")
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is True

    def test_not_installed_is_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Plugin not installed")
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is True

    def test_failure(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="some other error")
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is False

    def test_timeout(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
            assert result is False


@pytest.mark.unit
class TestRemoveMarketplace:
    def test_passes_name_not_path(self) -> None:
        """Bug fix verification: remove_marketplace must pass the marketplace name, not path."""
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = remove_marketplace("/usr/bin/claude", "my-marketplace-name")
            assert result is True
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/usr/bin/claude", "plugin", "marketplace", "remove", "my-marketplace-name"]

    def test_not_found_is_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Marketplace not found")
            result = remove_marketplace("/usr/bin/claude", "my-marketplace")
            assert result is True

    def test_failure(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="some error")
            result = remove_marketplace("/usr/bin/claude", "my-marketplace")
            assert result is False

    def test_timeout(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            result = remove_marketplace("/usr/bin/claude", "my-marketplace")
            assert result is False


@pytest.mark.unit
class TestInstallMarketplacePlugins:
    def test_full_orchestration(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp-one", plugins=["plugin-a"])

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True) as mock_reg,
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(tmp_path / "marketplaces")

        mock_reg.assert_called_once()
        mock_install.assert_called_once_with("/usr/bin/claude", "plugin-a", "mp-one")

    def test_missing_dir_no_error(self, tmp_path: pathlib.Path) -> None:
        with patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"):
            install_marketplace_plugins(tmp_path / "nonexistent")

    def test_failure_exits(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["p"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=False),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            with pytest.raises(SystemExit):
                install_marketplace_plugins(tmp_path / "marketplaces")


@pytest.mark.unit
class TestUninstallMarketplacePlugins:
    def test_full_orchestration(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp-one", plugins=["plugin-a"])

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=True) as mock_uninstall,
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True) as mock_remove,
        ):
            uninstall_marketplace_plugins(tmp_path / "marketplaces")

        mock_uninstall.assert_called_once_with("/usr/bin/claude", "plugin-a", "mp-one")
        mock_remove.assert_called_once_with("/usr/bin/claude", "mp-one")

    def test_remove_uses_name_not_path(self, tmp_path: pathlib.Path) -> None:
        """Bug fix verification: uninstall orchestration passes marketplace name to remove."""
        # Directory name differs from marketplace.json name to verify the name is used
        mp_dir = tmp_path / "marketplaces" / "dir-name-differs"
        mp_dir.mkdir(parents=True)
        claude_plugin = mp_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "marketplace.json").write_text(json.dumps({"name": "the-marketplace-name"}))

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True) as mock_remove,
        ):
            uninstall_marketplace_plugins(tmp_path / "marketplaces")

        mock_remove.assert_called_once_with("/usr/bin/claude", "the-marketplace-name")

    def test_missing_dir_no_error(self, tmp_path: pathlib.Path) -> None:
        with patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"):
            uninstall_marketplace_plugins(tmp_path / "nonexistent")

    def test_failure_exits(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["p"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=False),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True),
        ):
            with pytest.raises(SystemExit):
                uninstall_marketplace_plugins(tmp_path / "marketplaces")
