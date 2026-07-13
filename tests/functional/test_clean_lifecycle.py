"""Full clean lifecycle with mocked uninstall.

3.0.0 store model (spec Section 7.1 / FR-15): ``clean`` removes the install
artifacts (``.packages/`` and ``.kanon-data/``) from the shared ``KANON_HOME``
store at ``<KANON_HOME>/store``, the same location ``install`` writes them, not
from the project directory. Each test sets ``KANON_HOME`` to an isolated temp
dir and resolves the store base via ``resolve_workspace_base_dir``.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import resolve_workspace_base_dir


def _write_kanonenv(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _isolated_store(monkeypatch: pytest.MonkeyPatch, kanon_home: Path) -> Path:
    """Point KANON_HOME at ``kanon_home`` and return the resolved store base.

    The store base is ``<KANON_HOME>/store`` -- the single location shared by
    install and clean for the ``.packages/`` and ``.kanon-data/`` artifacts.
    """
    kanon_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KANON_HOME", str(kanon_home))
    return resolve_workspace_base_dir()


@pytest.mark.functional
class TestCleanLifecycle:
    def test_clean_removes_packages_and_kanon(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
            ),
        )
        (store / ".packages" / "pkg").mkdir(parents=True)
        (store / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        clean(kanonenv)

        assert not (store / ".packages").exists()

    def test_clean_purge_removes_config_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """kanon clean --purge deletes the project .kanon and .kanon.lock after the normal teardown."""
        store = _isolated_store(monkeypatch, tmp_path / "home")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
            ),
        )
        (store / ".packages" / "pkg").mkdir(parents=True)

        clean(kanonenv, purge=True)

        assert not (store / ".packages").exists()
        assert not kanonenv.exists(), "--purge must delete the .kanon file"

    def test_clean_purge_all_removes_home_store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """kanon clean --purge-all deletes the config files and removes the whole KANON_HOME store dir."""
        home = tmp_path / "home"
        store = _isolated_store(monkeypatch, home)
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
            ),
        )
        assert store.exists()

        clean(kanonenv, purge=True, purge_home=True)

        assert not kanonenv.exists(), "--purge-all must delete the .kanon file"
        assert not home.exists(), "--purge-all must remove the entire KANON_HOME store directory"

    def test_clean_with_marketplace_runs_uninstall(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")
        mp_dir = tmp_path / "marketplaces"
        mp_dir.mkdir()
        (mp_dir / "some-file.txt").write_text("data")

        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
                "KANON_SOURCE_build_MARKETPLACE=true\n"
                f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            ),
        )

        packages_dir = store / ".packages"
        packages_dir.mkdir(parents=True)
        (store / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_called_once_with(mp_dir)

        assert not mp_dir.exists()
        assert not packages_dir.exists()

    def test_clean_without_marketplace_skips_uninstall(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
            ),
        )
        (store / ".packages" / "pkg").mkdir(parents=True)
        (store / ".kanon-data" / "sources" / "build").mkdir(parents=True, exist_ok=True)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()

        assert not (store / ".packages").exists()

    def test_clean_idempotent_on_already_clean(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REF=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
                "KANON_SOURCE_build_NAME=build\n"
                "KANON_SOURCE_build_GITBASE=https://example.com\n"
            ),
        )

        clean(kanonenv)

        assert not (store / ".packages").exists()
