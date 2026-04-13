"""Full clean lifecycle with mocked uninstall."""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean


def _write_kanonenv(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


@pytest.mark.functional
class TestCleanLifecycle:
    def test_clean_removes_packages_and_kanon(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
            ),
        )
        (tmp_path / ".packages" / "pkg").mkdir(parents=True)
        (tmp_path / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists()

    def test_clean_with_marketplace_runs_uninstall(self, tmp_path: Path) -> None:
        mp_dir = tmp_path / "marketplaces"
        mp_dir.mkdir()
        (mp_dir / "some-file.txt").write_text("data")

        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_MARKETPLACE_INSTALL=true\n"
                f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            ),
        )

        packages_dir = tmp_path / ".packages"
        packages_dir.mkdir(parents=True)
        (tmp_path / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not mp_dir.exists()
        assert not packages_dir.exists()

    def test_clean_without_marketplace_skips_uninstall(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
            ),
        )
        (tmp_path / ".packages" / "pkg").mkdir(parents=True)
        (tmp_path / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()

        assert not (tmp_path / ".packages").exists()

    def test_clean_idempotent_on_already_clean(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
            ),
        )

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists()
