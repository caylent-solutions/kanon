"""Integration tests for marketplace lifecycle (28 tests).

Exercises marketplace plugin discovery, registration, install, and uninstall
workflows.  All subprocess calls to the claude binary are mocked so tests
run without the claude CLI being installed.
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


# ---------------------------------------------------------------------------
# AC-FUNC-006: Marketplace lifecycle integration tests (28 tests)
# ---------------------------------------------------------------------------


def _create_marketplace(
    parent: pathlib.Path,
    name: str,
    plugins: list[str] | None = None,
) -> pathlib.Path:
    """Create a marketplace directory whose marketplace.json declares plugins.

    Writes ``.claude-plugin/marketplace.json`` containing the marketplace
    ``name`` and a ``plugins`` array with one entry per name in ``plugins``.
    Returns ``parent/name``. The plugin discovery contract reads names
    from the array, not from per-plugin subdirectories.
    """
    mp_dir = parent / name
    mp_dir.mkdir(parents=True, exist_ok=True)
    claude_plugin = mp_dir / ".claude-plugin"
    claude_plugin.mkdir(exist_ok=True)
    manifest = {"name": name, "plugins": [{"name": p} for p in (plugins or [])]}
    (claude_plugin / "marketplace.json").write_text(json.dumps(manifest))
    return mp_dir


@pytest.mark.integration
class TestLocateClaudeBinary:
    """Verify claude binary location."""

    def test_returns_path_when_found(self) -> None:
        with patch("kanon_cli.core.marketplace.shutil.which", return_value="/usr/bin/claude"):
            result = locate_claude_binary()
            assert "claude" in result

    def test_exits_when_not_found(self) -> None:
        with patch("kanon_cli.core.marketplace.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                locate_claude_binary()
            assert exc_info.value.code == 1


@pytest.mark.integration
class TestDiscoverMarketplaceEntries:
    """Verify marketplace entry discovery."""

    def test_discovers_all_directories(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "mp-a").mkdir()
        (tmp_path / "mp-b").mkdir()
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 2

    def test_sorts_entries_alphabetically(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "zzz").mkdir()
        (tmp_path / "aaa").mkdir()
        entries = discover_marketplace_entries(tmp_path)
        assert entries[0].name == "aaa"
        assert entries[1].name == "zzz"

    def test_skips_hidden_directories(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0].name == "visible"

    def test_skips_broken_symlinks(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "good").mkdir()
        (tmp_path / "broken").symlink_to(tmp_path / "nonexistent")
        entries = discover_marketplace_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0].name == "good"

    def test_empty_directory_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        entries = discover_marketplace_entries(tmp_path)
        assert entries == []


@pytest.mark.integration
class TestReadMarketplaceName:
    """Verify marketplace name reading from JSON."""

    def test_reads_name_correctly(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "my-marketplace")
        assert read_marketplace_name(mp) == "my-marketplace"

    def test_raises_file_not_found_when_missing(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_marketplace_name(tmp_path)

    def test_raises_key_error_when_name_missing(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "mp"
        plugin_dir = mp_dir / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "marketplace.json").write_text(json.dumps({"version": "1.0"}))
        with pytest.raises(KeyError):
            read_marketplace_name(mp_dir)


@pytest.mark.integration
class TestDiscoverPlugins:
    """Verify plugin discovery within a marketplace."""

    def test_discovers_plugins(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp", plugins=["plugin-a", "plugin-b"])
        plugins = discover_plugins(mp)
        names = [name for name, _ in plugins]
        assert "plugin-a" in names
        assert "plugin-b" in names

    def test_only_named_plugins_in_array_are_returned(self, tmp_path: pathlib.Path) -> None:
        """Discovery only returns entries declared in marketplace.json's plugins[]
        array. Sibling directories without a corresponding array entry are NOT
        discovered (the previous plugin.json-subdirectory pattern is gone)."""
        mp = _create_marketplace(tmp_path, "mp", plugins=["real"])
        # A bare directory next to the manifest must NOT be picked up by
        # discover_plugins now that the contract is array-driven.
        (mp / "not-a-plugin").mkdir()
        plugins = discover_plugins(mp)
        assert len(plugins) == 1
        assert plugins[0][0] == "real"

    def test_empty_marketplace_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp")
        assert discover_plugins(mp) == []


@pytest.mark.integration
class TestGetTimeout:
    """Verify timeout configuration from environment variables."""

    def test_returns_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KANON_TEST_TIMEOUT_VAR_XYZ", raising=False)
        result = _get_timeout("KANON_TEST_TIMEOUT_VAR_XYZ", default=42)
        assert result == 42

    def test_reads_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_TEST_TIMEOUT_VAR_XYZ", "99")
        result = _get_timeout("KANON_TEST_TIMEOUT_VAR_XYZ")
        assert result == 99

    def test_exits_on_invalid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_TEST_TIMEOUT_VAR_XYZ", "notanumber")
        with pytest.raises(SystemExit):
            _get_timeout("KANON_TEST_TIMEOUT_VAR_XYZ")

    def test_exits_on_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_TEST_TIMEOUT_VAR_XYZ", "0")
        with pytest.raises(SystemExit):
            _get_timeout("KANON_TEST_TIMEOUT_VAR_XYZ")


@pytest.mark.integration
class TestRegisterMarketplace:
    """Verify marketplace registration calls."""

    def test_success_returns_true(self, tmp_path: pathlib.Path) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = register_marketplace("/usr/bin/claude", tmp_path / "mp")
        assert result is True

    def test_failure_returns_false(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = register_marketplace("/usr/bin/claude", pathlib.Path("/mp"))
        assert result is False

    def test_timeout_returns_false(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            result = register_marketplace("/usr/bin/claude", pathlib.Path("/mp"))
        assert result is False

    def test_passes_correct_path_to_cli(self, tmp_path: pathlib.Path) -> None:
        mp_path = tmp_path / "my-marketplace"
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            register_marketplace("/usr/bin/claude", mp_path)
        cmd = mock_run.call_args[0][0]
        assert str(mp_path) in cmd


@pytest.mark.integration
class TestInstallAndUninstallPlugin:
    """Verify plugin install and uninstall calls."""

    def test_install_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = install_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
        assert result is True

    def test_install_failure_returns_false(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = install_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
        assert result is False

    def test_uninstall_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
        assert result is True

    def test_uninstall_not_found_is_success(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Plugin not found")
            result = uninstall_plugin("/usr/bin/claude", "my-plugin", "my-marketplace")
        assert result is True

    def test_remove_marketplace_passes_name(self) -> None:
        with patch("kanon_cli.core.marketplace.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = remove_marketplace("/usr/bin/claude", "the-marketplace-name")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "the-marketplace-name" in cmd


@pytest.mark.integration
class TestInstallUninstallOrchestration:
    """Verify full install and uninstall orchestration flows."""

    def test_install_orchestration_calls_register_and_install(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True) as mock_reg,
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True) as mock_install,
        ):
            install_marketplace_plugins(tmp_path / "marketplaces")
        mock_reg.assert_called_once()
        mock_install.assert_called_once_with("/usr/bin/claude", "plugin-a", "mp")

    def test_install_nonexistent_dir_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        with patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"):
            install_marketplace_plugins(tmp_path / "nonexistent")

    def test_install_failure_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["p"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=False),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            with pytest.raises(SystemExit):
                install_marketplace_plugins(tmp_path / "marketplaces")

    def test_uninstall_orchestration_calls_uninstall_and_remove(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["plugin-a"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=True) as mock_uninstall,
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True) as mock_remove,
        ):
            uninstall_marketplace_plugins(tmp_path / "marketplaces")
        mock_uninstall.assert_called_once_with("/usr/bin/claude", "plugin-a", "mp")
        mock_remove.assert_called_once_with("/usr/bin/claude", "mp")

    def test_uninstall_uses_name_from_json_not_dir(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "marketplaces" / "dir-name"
        mp_dir.mkdir(parents=True)
        plugin_dir = mp_dir / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "marketplace.json").write_text(json.dumps({"name": "json-name"}))
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True) as mock_remove,
        ):
            uninstall_marketplace_plugins(tmp_path / "marketplaces")
        mock_remove.assert_called_once_with("/usr/bin/claude", "json-name")

    def test_uninstall_failure_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        _create_marketplace(tmp_path / "marketplaces", "mp", plugins=["p"])
        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=False),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True),
        ):
            with pytest.raises(SystemExit):
                uninstall_marketplace_plugins(tmp_path / "marketplaces")
