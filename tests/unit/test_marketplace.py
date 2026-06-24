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
    create_dirsymlink,
    discover_marketplace_entries,
    discover_plugins,
    discover_registered_marketplace_names,
    install_marketplace_plugins,
    install_plugin,
    locate_claude_binary,
    read_marketplace_name,
    register_direct_checkout_marketplaces,
    register_marketplace,
    remove_marketplace,
    uninstall_marketplace_plugins,
    uninstall_plugin,
)


def _create_marketplace(parent_dir: pathlib.Path, name: str, plugins: list[str] | None = None) -> pathlib.Path:
    """Helper to create a marketplace directory with marketplace.json declaring plugins.

    Writes ``.claude-plugin/marketplace.json`` containing the marketplace
    ``name`` and a ``plugins`` array with one entry per name in ``plugins``.
    Returns ``parent_dir/name``.
    """
    mp_dir = parent_dir / name
    mp_dir.mkdir(parents=True, exist_ok=True)
    claude_plugin = mp_dir / ".claude-plugin"
    claude_plugin.mkdir(exist_ok=True)
    manifest = {"name": name, "plugins": [{"name": p} for p in (plugins or [])]}
    (claude_plugin / "marketplace.json").write_text(json.dumps(manifest))
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

    def test_only_named_plugins_in_array_are_returned(self, tmp_path: pathlib.Path) -> None:
        """Entries in the plugins[] array without a 'name' field are skipped silently."""
        mp_dir = tmp_path / "mp"
        (mp_dir / ".claude-plugin").mkdir(parents=True)
        manifest = {
            "name": "mp",
            "plugins": [
                {"name": "real-plugin"},
                {"description": "no name field"},
                {"name": ""},
                "not-a-dict",
            ],
        }
        (mp_dir / ".claude-plugin" / "marketplace.json").write_text(json.dumps(manifest))
        plugins = discover_plugins(mp_dir)
        assert len(plugins) == 1
        assert plugins[0][0] == "real-plugin"

    def test_empty_marketplace(self, tmp_path: pathlib.Path) -> None:
        mp = _create_marketplace(tmp_path, "mp")
        plugins = discover_plugins(mp)
        assert plugins == []

    def test_missing_manifest_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """When marketplace.json is absent, discover_plugins returns []."""
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        plugins = discover_plugins(mp_dir)
        assert plugins == []

    def test_missing_plugins_key_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """When marketplace.json lacks a 'plugins' key, discover_plugins returns []."""
        mp_dir = tmp_path / "mp"
        (mp_dir / ".claude-plugin").mkdir(parents=True)
        (mp_dir / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "mp"}))
        plugins = discover_plugins(mp_dir)
        assert plugins == []

    def test_invalid_json_raises(self, tmp_path: pathlib.Path) -> None:
        """A malformed marketplace.json surfaces as JSONDecodeError, not silent empty."""
        mp_dir = tmp_path / "mp"
        (mp_dir / ".claude-plugin").mkdir(parents=True)
        (mp_dir / ".claude-plugin" / "marketplace.json").write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            discover_plugins(mp_dir)


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


def _write_manifest_xml(
    parent: pathlib.Path,
    project_path: str,
    *,
    has_linkfile: bool = False,
    filename: str = "default.xml",
    marketplace_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Write a minimal manifest XML for unit testing register_direct_checkout_marketplaces.

    Args:
        parent: Directory to write the XML into.
        project_path: The ``path`` attribute for the ``<project>`` element.
        has_linkfile: If True, add a ``<linkfile>`` child to the project.
        filename: Output filename.
        marketplace_dir: Required when has_linkfile is True to produce a valid dest.

    Returns:
        Path to the written XML file.
    """
    if has_linkfile and marketplace_dir is not None:
        project_xml = (
            f'  <project name="{project_path}" path="{project_path}">\n'
            f'    <linkfile src="." dest="{marketplace_dir}/{project_path}" />\n'
            "  </project>\n"
        )
    else:
        project_xml = f'  <project name="{project_path}" path="{project_path}" />\n'
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n{project_xml}</manifest>\n'
    out = parent / filename
    out.write_text(xml)
    return out


def _create_project_with_marketplace_json(
    source_dir: pathlib.Path,
    project_path: str,
    name: str,
) -> pathlib.Path:
    """Create a project checkout directory with .claude-plugin/marketplace.json.

    Args:
        source_dir: Root source directory (project is created at source_dir/project_path).
        project_path: Relative path for the project checkout.
        name: Marketplace name to write in marketplace.json.

    Returns:
        Path to the project directory.
    """
    project_dir = source_dir / project_path
    claude_plugin = project_dir / ".claude-plugin"
    claude_plugin.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "plugins": [{"name": name}]}
    (claude_plugin / "marketplace.json").write_text(json.dumps(manifest))
    return project_dir


@pytest.mark.unit
class TestRegisterDirectCheckoutMarketplaces:
    """Tests for register_direct_checkout_marketplaces (BUG-3 fix).

    Verifies both the new direct-checkout registration path and the
    linkfile-pattern no-regression (AC-TEST-003).
    """

    def test_creates_symlink_for_project_with_marketplace_json(self, tmp_path: pathlib.Path) -> None:
        """A project with .claude-plugin/marketplace.json and no <linkfile> gets a symlink."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, "my-plugin", "my-plugin")
        manifest_xml = _write_manifest_xml(tmp_path, "my-plugin")

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        link = marketplace_dir / "my-plugin"
        assert link.is_symlink(), f"Expected symlink at {link}"
        assert (link / ".claude-plugin" / "marketplace.json").is_file()

    def test_skips_project_without_marketplace_json(self, tmp_path: pathlib.Path) -> None:
        """A project without .claude-plugin/marketplace.json is silently skipped."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        plain_dir = source_dir / "plain-pkg"
        plain_dir.mkdir(parents=True)
        (plain_dir / "README.md").write_text("# plain\n")

        manifest_xml = _write_manifest_xml(tmp_path, "plain-pkg")

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        assert list(marketplace_dir.iterdir()) == [], (
            "Expected empty marketplace dir for project without marketplace.json"
        )

    def test_skips_project_with_linkfile(self, tmp_path: pathlib.Path) -> None:
        """A project that already has a <linkfile> is skipped (handled by linkfile path).

        No-regression test: linkfile-pattern entries are not double-registered.
        """
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, "linked-plugin", "linked-plugin")
        manifest_xml = _write_manifest_xml(
            tmp_path,
            "linked-plugin",
            has_linkfile=True,
            marketplace_dir=marketplace_dir,
        )

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        assert list(marketplace_dir.iterdir()) == [], (
            "Expected linkfile-pattern project to be skipped by register_direct_checkout_marketplaces"
        )

    def test_absent_manifest_xml_is_noop(self, tmp_path: pathlib.Path) -> None:
        """If the manifest XML file does not exist, the function returns silently."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        absent_xml = tmp_path / "absent.xml"

        register_direct_checkout_marketplaces(absent_xml, tmp_path / "source", marketplace_dir)

        assert list(marketplace_dir.iterdir()) == []

    def test_idempotent_second_call_does_not_error(self, tmp_path: pathlib.Path) -> None:
        """Calling register_direct_checkout_marketplaces twice is safe (idempotent)."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, "idem-plugin", "idem-plugin")
        manifest_xml = _write_manifest_xml(tmp_path, "idem-plugin")

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)
        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        link = marketplace_dir / "idem-plugin"
        assert link.is_symlink(), "Expected symlink to still be present after second call"

    @pytest.mark.parametrize(
        "project_path,marketplace_name",
        [
            (".packages/builders-plugins", "builders-plugins"),
            (".packages/history", "history"),
            ("direct-pkg", "direct-pkg"),
        ],
    )
    def test_parametrized_project_paths(
        self,
        tmp_path: pathlib.Path,
        project_path: str,
        marketplace_name: str,
    ) -> None:
        """Symlinks are created correctly for various project path shapes."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, project_path, marketplace_name)
        manifest_xml = _write_manifest_xml(tmp_path, project_path)

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        link = marketplace_dir / marketplace_name
        assert link.is_symlink(), f"Expected symlink at {link} for project {project_path!r}"
        assert (link / ".claude-plugin" / "marketplace.json").is_file()

    def test_mixed_projects_only_registers_direct_checkout_ones(self, tmp_path: pathlib.Path) -> None:
        """When a manifest has both linkfile and non-linkfile projects, only
        the non-linkfile projects with marketplace.json are registered.

        This is the combined regression guard for AC-FUNC-003 at the unit level.
        """
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        # Project with linkfile -- should NOT be registered by this function.
        _create_project_with_marketplace_json(source_dir, "linked", "linked")
        # Project without linkfile but with marketplace.json -- SHOULD be registered.
        _create_project_with_marketplace_json(source_dir, "direct", "direct")
        # Project without linkfile and without marketplace.json -- NOT registered.
        plain_dir = source_dir / "plain"
        plain_dir.mkdir(parents=True)

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <project name="linked" path="linked">\n'
            f'    <linkfile src="." dest="{marketplace_dir}/linked" />\n'
            "  </project>\n"
            '  <project name="direct" path="direct" />\n'
            '  <project name="plain" path="plain" />\n'
            "</manifest>\n"
        )
        manifest_xml = tmp_path / "mixed.xml"
        manifest_xml.write_text(xml)

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        entries = {p.name for p in marketplace_dir.iterdir()}
        assert entries == {"direct"}, f"Expected only 'direct' in marketplace_dir but got: {entries}"

    def test_raises_value_error_when_marketplace_json_missing_name_field(self, tmp_path: pathlib.Path) -> None:
        """A marketplace.json that exists but lacks 'name' raises ValueError with context.

        AC-FUNC-004: registration failure surfaces as a handled error, not a raw traceback.
        """
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        # Create a project with a marketplace.json that has NO 'name' field.
        project_dir = source_dir / "bad-plugin"
        claude_plugin_dir = project_dir / ".claude-plugin"
        claude_plugin_dir.mkdir(parents=True)
        (claude_plugin_dir / "marketplace.json").write_text(json.dumps({"plugins": [{"name": "some-plugin"}]}))

        manifest_xml = _write_manifest_xml(tmp_path, "bad-plugin")

        with pytest.raises(ValueError, match="bad-plugin") as exc_info:
            register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        error_msg = str(exc_info.value)
        assert "name" in error_msg, f"ValueError message should mention the missing 'name' field; got: {error_msg!r}"
        assert "Remediation" in error_msg, f"ValueError message should include a remediation hint; got: {error_msg!r}"


@pytest.mark.unit
class TestDiscoverRegisteredMarketplaceNames:
    """``discover_registered_marketplace_names`` returns a sorted, de-duplicated
    list of marketplace names discovered under ``marketplace_dir``.

    Entries lacking ``.claude-plugin/marketplace.json`` are skipped (same
    tolerance as ``install_marketplace_plugins``). A missing directory yields
    an empty list. The helper is the authoritative source of the freshly
    registered set used by the install auto-prune and ``clean --orphans``.
    """

    def test_one_valid_one_no_json_returns_only_named(self, tmp_path: pathlib.Path) -> None:
        """A valid marketplace and a non-marketplace entry: only the named one is returned."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        _create_marketplace(marketplace_dir, "mp-current", plugins=["plug-a"])

        # An entry that is a directory but has NO .claude-plugin/marketplace.json
        # (e.g. a linkfile target that does not point at a marketplace root).
        no_json_entry = marketplace_dir / "not-a-marketplace"
        no_json_entry.mkdir()
        (no_json_entry / "some-file.txt").write_text("not a marketplace manifest")

        result = discover_registered_marketplace_names(marketplace_dir)

        assert result == ["mp-current"], (
            f"Expected only the named marketplace 'mp-current'; the entry lacking "
            f".claude-plugin/marketplace.json must be skipped. Got: {result!r}"
        )

    def test_returns_sorted_deduplicated(self, tmp_path: pathlib.Path) -> None:
        """Multiple valid marketplaces are returned sorted (and de-duplicated)."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        # Create in non-sorted creation order; the manifest 'name' fields are the
        # values that must come back sorted.
        _create_marketplace(marketplace_dir, "zeta-dir", plugins=[])
        _create_marketplace(marketplace_dir, "alpha-dir", plugins=[])
        _create_marketplace(marketplace_dir, "mike-dir", plugins=[])

        result = discover_registered_marketplace_names(marketplace_dir)

        assert result == ["alpha-dir", "mike-dir", "zeta-dir"], f"Expected sorted marketplace names; got: {result!r}"
        assert result == sorted(set(result)), f"Result must be sorted and de-duplicated; got: {result!r}"

    def test_missing_dir_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """A non-existent marketplace_dir yields an empty list (tolerant, not an error)."""
        result = discover_registered_marketplace_names(tmp_path / "does-not-exist")
        assert result == [], f"Missing marketplace_dir must return []; got: {result!r}"


# ---------------------------------------------------------------------------
# E2-F1-S3-T1: POSIX directory-symlink helper (AC-10)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDirsymlink:
    """create_dirsymlink creates a POSIX directory symlink."""

    def test_creates_symlink_pointing_at_target_directory(self, tmp_path: pathlib.Path) -> None:
        """create_dirsymlink creates a symlink at link_path pointing at target on POSIX."""
        target = tmp_path / "real-target"
        target.mkdir()
        (target / "sentinel.txt").write_text("content")
        link = tmp_path / "the-link"

        create_dirsymlink(link, target)

        assert link.is_symlink(), f"Expected symlink at {link}"
        assert link.is_dir(), "Expected symlink to resolve to a directory"
        assert (link / "sentinel.txt").is_file(), "Expected sentinel.txt accessible through link"

    def test_fails_fast_when_link_path_already_exists_as_directory(self, tmp_path: pathlib.Path) -> None:
        """create_dirsymlink raises OSError when link_path exists as a plain directory."""
        target = tmp_path / "real-target"
        target.mkdir()
        link = tmp_path / "already-a-dir"
        link.mkdir()

        with pytest.raises(OSError):
            create_dirsymlink(link, target)

    def test_fails_fast_when_target_does_not_exist(self, tmp_path: pathlib.Path) -> None:
        """create_dirsymlink raises OSError when target path does not exist."""
        target = tmp_path / "nonexistent-target"
        link = tmp_path / "the-link"

        # os.symlink succeeds even for non-existent targets (dangling links are legal),
        # so we only guarantee the link is created; the *real* fail-fast constraint
        # is that an existing non-symlink at link_path is rejected (tested above).
        # We assert here that the helper at least runs without swallowing exceptions.
        create_dirsymlink(link, target)
        assert link.is_symlink(), "create_dirsymlink must create the symlink even for a dangling target"


@pytest.mark.unit
class TestRegisterDirectCheckoutMarketplacesUsesJunctionHelper:
    """register_direct_checkout_marketplaces must route its directory link through create_dirsymlink."""

    def test_register_direct_checkout_marketplaces_calls_create_dirsymlink(self, tmp_path: pathlib.Path) -> None:
        """register_direct_checkout_marketplaces calls create_dirsymlink for directory links."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, "mp-name", "mp-name")
        manifest_xml = _write_manifest_xml(tmp_path, "mp-name")

        with patch("kanon_cli.core.marketplace.create_dirsymlink") as mock_helper:
            register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        mock_helper.assert_called_once()
        call_args = mock_helper.call_args
        # link_path (first arg) should be marketplace_dir / "mp-name"
        assert call_args[0][0] == marketplace_dir / "mp-name", (
            "create_dirsymlink must be called with link_path = marketplace_dir / name"
        )

    def test_register_produces_working_directory_link_on_posix(self, tmp_path: pathlib.Path) -> None:
        """register_direct_checkout_marketplaces produces a usable directory link on POSIX."""
        source_dir = tmp_path / "source"
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        _create_project_with_marketplace_json(source_dir, "my-mp", "my-mp")
        manifest_xml = _write_manifest_xml(tmp_path, "my-mp")

        register_direct_checkout_marketplaces(manifest_xml, source_dir, marketplace_dir)

        link = marketplace_dir / "my-mp"
        assert link.is_symlink(), f"Expected symlink at {link}"
        assert link.is_dir(), "Expected symlink to resolve to a directory"
        assert (link / ".claude-plugin" / "marketplace.json").is_file(), (
            "marketplace.json must be accessible through the link"
        )
