"""Full install lifecycle with mocked repo tool."""

from pathlib import Path
from unittest.mock import MagicMock, patch

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

        def fake_repo_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", tmp_path)
            if "sync" in cmd:
                packages = cwd / ".packages" / "pkg-a"
                packages.mkdir(parents=True, exist_ok=True)
                (packages / "file.txt").write_text("content")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("kanon_cli.core.install.subprocess.run", side_effect=fake_repo_run):
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

        call_count = {"init": 0, "sync": 0}

        def fake_repo_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", tmp_path)
            if "init" in cmd:
                call_count["init"] += 1
            if "sync" in cmd:
                call_count["sync"] += 1
                source_name = cwd.name
                packages = cwd / ".packages" / f"pkg-{source_name}"
                packages.mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("kanon_cli.core.install.subprocess.run", side_effect=fake_repo_run):
            install(kanonenv)

        assert call_count["init"] == 2
        assert call_count["sync"] == 2
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

        def fake_repo_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", tmp_path)
            if "sync" in cmd:
                packages = cwd / ".packages" / "collider"
                packages.mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("kanon_cli.core.install.subprocess.run", side_effect=fake_repo_run):
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

        with patch("kanon_cli.core.install.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            install(kanonenv)

        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".packages/") == 1
        assert ".kanon-data/" in content
