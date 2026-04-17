"""Full install lifecycle with mocked repo Python API."""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install


def _write_kanonenv(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


@pytest.mark.functional
class TestInstallLifecycle:
    def test_single_source_creates_dirs_and_symlinks(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
            ),
        )

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            packages = Path(repo_dir) / ".packages" / "pkg-a"
            packages.mkdir(parents=True, exist_ok=True)
            (packages / "file.txt").write_text("content")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv)

        assert (tmp_path / ".kanon-data" / "sources" / "build").is_dir()
        assert (tmp_path / ".packages" / "pkg-a").is_symlink()
        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".packages/" in gitignore
        assert ".kanon-data/" in gitignore

    def test_two_sources_aggregate_without_collision(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
                "KANON_SOURCE_alpha_REVISION=main\n"
                "KANON_SOURCE_alpha_PATH=meta.xml\n"
                "KANON_SOURCE_bravo_URL=https://example.com/bravo.git\n"
                "KANON_SOURCE_bravo_REVISION=main\n"
                "KANON_SOURCE_bravo_PATH=meta.xml\n"
            ),
        )

        init_calls: list[str] = []
        sync_calls: list[str] = []

        def fake_repo_init(repo_dir: str, url: str, revision: str, manifest_path: str, repo_rev: str = "") -> None:
            init_calls.append(repo_dir)

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
            install(kanonenv)

        assert len(init_calls) == 2
        assert len(sync_calls) == 2
        assert (tmp_path / ".packages" / "pkg-alpha").is_symlink()
        assert (tmp_path / ".packages" / "pkg-bravo").is_symlink()

    def test_collision_detection_exits(self, tmp_path: Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
                "KANON_SOURCE_alpha_REVISION=main\n"
                "KANON_SOURCE_alpha_PATH=meta.xml\n"
                "KANON_SOURCE_bravo_URL=https://example.com/bravo.git\n"
                "KANON_SOURCE_bravo_REVISION=main\n"
                "KANON_SOURCE_bravo_PATH=meta.xml\n"
            ),
        )

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            packages = Path(repo_dir) / ".packages" / "collider"
            packages.mkdir(parents=True, exist_ok=True)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install(kanonenv)
            assert exc_info.value.code == 1

    def test_gitignore_appended_not_duplicated(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text(".packages/\n")
        kanonenv = _write_kanonenv(
            tmp_path / ".kanon",
            (
                "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_build_REVISION=main\n"
                "KANON_SOURCE_build_PATH=meta.xml\n"
            ),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".packages/") == 1
        assert ".kanon-data/" in content
