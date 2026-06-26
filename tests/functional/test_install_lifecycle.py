"""Full install lifecycle with mocked repo Python API.

3.0.0 store model (spec Section 7.1 / FR-15): the install artifacts
(``.kanon-data/sources/<name>/``, the aggregated ``.packages/`` symlinks, and
the artifact ``.gitignore``) live under the shared ``KANON_HOME`` store at
``<KANON_HOME>/store``, not under the project directory. Each test sets
``KANON_HOME`` to an isolated temp dir and resolves the store base via
``resolve_workspace_base_dir`` so the assertions point at the real artifact
location.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.install import _run as _install_run
from kanon_cli.core.install import install, resolve_workspace_base_dir
from tests.conftest import write_manifest_for_sync


def _write_kanonenv(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _isolated_store(monkeypatch: pytest.MonkeyPatch, kanon_home: Path) -> Path:
    """Point KANON_HOME at ``kanon_home`` and return the resolved store base.

    The store base is ``<KANON_HOME>/store`` (the single location shared by
    install and clean), where the ``.kanon-data/`` source workspaces, the
    aggregated ``.packages/`` symlinks, and the artifact ``.gitignore`` are
    written.
    """
    kanon_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KANON_HOME", str(kanon_home))
    return resolve_workspace_base_dir()


@pytest.mark.functional
class TestInstallLifecycle:
    def test_single_source_creates_dirs_and_symlinks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

        def fake_repo_init(repo_dir: str, url: str, revision: str, manifest_path: str, repo_rev: str = "") -> None:
            write_manifest_for_sync(Path(repo_dir), sub_path=manifest_path)

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            packages = Path(repo_dir) / ".packages" / "pkg-a"
            packages.mkdir(parents=True, exist_ok=True)
            (packages / "file.txt").write_text("content")

        with (
            patch("kanon_cli.repo.repo_init", side_effect=fake_repo_init),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert (store / ".kanon-data" / "sources" / "build").is_dir()
        assert (store / ".packages" / "pkg-a").is_symlink()
        gitignore = (store / ".gitignore").read_text()
        assert ".packages/" in gitignore
        assert ".kanon-data/" in gitignore

    def test_two_sources_aggregate_without_collision(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
                "KANON_SOURCE_alpha_REF=main\n"
                "KANON_SOURCE_alpha_PATH=meta.xml\n"
                "KANON_SOURCE_alpha_NAME=alpha\n"
                "KANON_SOURCE_alpha_GITBASE=https://example.com\n"
                "KANON_SOURCE_bravo_URL=https://example.com/bravo.git\n"
                "KANON_SOURCE_bravo_REF=main\n"
                "KANON_SOURCE_bravo_PATH=meta.xml\n"
                "KANON_SOURCE_bravo_NAME=bravo\n"
                "KANON_SOURCE_bravo_GITBASE=https://example.com\n"
            ),
        )

        init_calls: list[str] = []
        sync_calls: list[str] = []

        def fake_repo_init(repo_dir: str, url: str, revision: str, manifest_path: str, repo_rev: str = "") -> None:
            init_calls.append(repo_dir)
            write_manifest_for_sync(Path(repo_dir), sub_path=manifest_path)

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            sync_calls.append(repo_dir)
            source_name = Path(repo_dir).name
            packages = Path(repo_dir) / ".packages" / f"pkg-{source_name}"
            packages.mkdir(parents=True, exist_ok=True)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=fake_repo_init),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert len(init_calls) == 2
        assert len(sync_calls) == 2
        assert (store / ".packages" / "pkg-alpha").is_symlink()
        assert (store / ".packages" / "pkg-bravo").is_symlink()

    def test_collision_detection_exits(self, tmp_path: Path, make_install_args) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
                "KANON_SOURCE_alpha_REF=main\n"
                "KANON_SOURCE_alpha_PATH=meta.xml\n"
                "KANON_SOURCE_alpha_NAME=alpha\n"
                "KANON_SOURCE_alpha_GITBASE=https://example.com\n"
                "KANON_SOURCE_bravo_URL=https://example.com/bravo.git\n"
                "KANON_SOURCE_bravo_REF=main\n"
                "KANON_SOURCE_bravo_PATH=meta.xml\n"
                "KANON_SOURCE_bravo_NAME=bravo\n"
                "KANON_SOURCE_bravo_GITBASE=https://example.com\n"
            ),
        )

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            packages = Path(repo_dir) / ".packages" / "collider"
            packages.mkdir(parents=True, exist_ok=True)

        args = make_install_args(kanonenv.resolve())
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _install_run(args)
        assert exc_info.value.code == 1

    def test_gitignore_appended_not_duplicated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _isolated_store(monkeypatch, tmp_path / "home")

        (store / ".gitignore").write_text(".packages/\n")
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

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        content = (store / ".gitignore").read_text()
        assert content.count(".packages/") == 1
        assert ".kanon-data/" in content
