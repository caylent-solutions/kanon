"""Tests for E2-F3-S2-T3: install/uninstall must not crash on non-marketplace entries.

When a marketplace linkfile points at a subdirectory of a plugin repo
that does NOT itself contain `.claude-plugin/marketplace.json`,
`install_marketplace_plugins` and `uninstall_marketplace_plugins`
previously crashed with `FileNotFoundError` from
`read_marketplace_name`. The fix wraps each entry's marketplace.json
read in a `FileNotFoundError`-skipping try/except so the orchestrators
emit a warning and continue rather than fail-stop. MK-22 was the
canonical failure case (II-007).

These tests pin the new behaviour for both install and uninstall.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.marketplace import (
    install_marketplace_plugins,
    uninstall_marketplace_plugins,
)


def _make_real_marketplace(parent: pathlib.Path, name: str) -> pathlib.Path:
    mp = parent / name
    cp = mp / ".claude-plugin"
    cp.mkdir(parents=True)
    (cp / "marketplace.json").write_text(json.dumps({"name": name, "plugins": [{"name": name}]}))
    return mp


def _make_non_marketplace_dir(parent: pathlib.Path, name: str) -> pathlib.Path:
    """Create a directory that LOOKS like a marketplace entry (visible in
    discover_marketplace_entries) but lacks .claude-plugin/marketplace.json."""
    mp = parent / name
    mp.mkdir()
    (mp / "README.md").write_text("Not a marketplace; just a content dir.")
    return mp


@pytest.mark.unit
class TestInstallSkipsNonMarketplaceEntries:
    def test_install_skips_entry_without_marketplace_json(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marketplaces_root = tmp_path / "marketplaces"
        marketplaces_root.mkdir()
        _make_real_marketplace(marketplaces_root, "real-plugin")
        _make_non_marketplace_dir(marketplaces_root, "linkfile-non-mkt")

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True),
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            # Must not raise FileNotFoundError on the linkfile-non-mkt entry.
            install_marketplace_plugins(marketplaces_root)

        captured = capsys.readouterr()
        assert "Skipping non-marketplace entry" in captured.err
        assert "linkfile-non-mkt" in captured.err
        # Real plugin still gets registered + installed (summary reflects it).
        assert "1 registered, 1 plugins installed" in captured.out

    def test_install_does_not_register_skipped_entry(self, tmp_path: pathlib.Path) -> None:
        marketplaces_root = tmp_path / "marketplaces"
        marketplaces_root.mkdir()
        _make_real_marketplace(marketplaces_root, "real-plugin")
        _make_non_marketplace_dir(marketplaces_root, "linkfile-non-mkt")

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.register_marketplace", return_value=True) as mock_reg,
            patch("kanon_cli.core.marketplace.install_plugin", return_value=True),
        ):
            install_marketplace_plugins(marketplaces_root)
        # register_marketplace should be called exactly once (for real-plugin),
        # never for the non-marketplace entry.
        assert mock_reg.call_count == 1


@pytest.mark.unit
class TestUninstallSkipsNonMarketplaceEntries:
    def test_uninstall_skips_entry_without_marketplace_json(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marketplaces_root = tmp_path / "marketplaces"
        marketplaces_root.mkdir()
        _make_real_marketplace(marketplaces_root, "real-plugin")
        _make_non_marketplace_dir(marketplaces_root, "linkfile-non-mkt")

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=True),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True),
        ):
            # Must not raise FileNotFoundError on the linkfile-non-mkt entry.
            uninstall_marketplace_plugins(marketplaces_root)

        captured = capsys.readouterr()
        assert "Skipping non-marketplace entry" in captured.err
        assert "linkfile-non-mkt" in captured.err

    def test_uninstall_does_not_call_remove_for_skipped(self, tmp_path: pathlib.Path) -> None:
        marketplaces_root = tmp_path / "marketplaces"
        marketplaces_root.mkdir()
        _make_real_marketplace(marketplaces_root, "real-plugin")
        _make_non_marketplace_dir(marketplaces_root, "linkfile-non-mkt")

        with (
            patch("kanon_cli.core.marketplace.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.marketplace.uninstall_plugin", return_value=True),
            patch("kanon_cli.core.marketplace.remove_marketplace", return_value=True) as mock_remove,
        ):
            uninstall_marketplace_plugins(marketplaces_root)
        # remove_marketplace should be called exactly once (for real-plugin),
        # never for the non-marketplace entry.
        assert mock_remove.call_count == 1
