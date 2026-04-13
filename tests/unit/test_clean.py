"""Tests for clean core business logic."""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import (
    clean,
    remove_kanon_dir,
    remove_marketplace_dir,
    remove_packages_dir,
)


@pytest.mark.unit
class TestDirectoryRemoval:
    def test_removes_marketplace(self, tmp_path: pathlib.Path) -> None:
        mp = tmp_path / "mp"
        mp.mkdir()
        (mp / "file.txt").write_text("content")
        remove_marketplace_dir(mp)
        assert not mp.exists()

    def test_marketplace_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_marketplace_dir(tmp_path / "nonexistent")

    def test_removes_packages(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".packages").mkdir()
        remove_packages_dir(tmp_path)
        assert not (tmp_path / ".packages").exists()

    def test_packages_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_packages_dir(tmp_path)

    def test_removes_kanon(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon-data").mkdir()
        remove_kanon_dir(tmp_path)
        assert not (tmp_path / ".kanon-data").exists()

    def test_kanon_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_kanon_dir(tmp_path)


@pytest.mark.unit
class TestCleanLifecycle:
    def test_marketplace_false_skips_uninstall(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir(exist_ok=True)
        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()
        assert not (tmp_path / ".packages").exists()

    def test_marketplace_true_missing_dir_exits(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        with pytest.raises(SystemExit):
            clean(kanonenv)

    def test_order_of_operations(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / ".mp"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        mp_dir.mkdir()
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir(exist_ok=True)

        ops: list[str] = []

        def track_uninstall(marketplace_dir):
            ops.append("uninstall")

        orig_rmtree = __import__("shutil").rmtree

        def track_rm(path, ignore_errors=False):
            p = str(path)
            if ".mp" in p:
                ops.append("rm_mp")
            elif ".packages" in p:
                ops.append("rm_packages")
            elif ".kanon-data" in p:
                ops.append("rm_kanon")
            orig_rmtree(path, ignore_errors=ignore_errors)

        with (
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=track_uninstall),
            patch("kanon_cli.core.clean.shutil.rmtree", side_effect=track_rm),
        ):
            clean(kanonenv)

        assert ops == ["uninstall", "rm_mp", "rm_packages", "rm_kanon"]
