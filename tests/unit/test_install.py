"""Tests for install core business logic."""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    aggregate_symlinks,
    create_source_dirs,
    install,
    prepare_marketplace_dir,
    run_repo_envsubst,
    run_repo_init,
    run_repo_sync,
    update_gitignore,
)


@pytest.mark.unit
class TestSourceDirectoryCreation:
    def test_creates_source_dirs(self, tmp_path: pathlib.Path) -> None:
        result = create_source_dirs(["build", "marketplaces"], tmp_path)
        for name in ["build", "marketplaces"]:
            assert (tmp_path / ".kanon-data" / "sources" / name).is_dir()
            assert name in result

    def test_idempotent(self, tmp_path: pathlib.Path) -> None:
        create_source_dirs(["build"], tmp_path)
        result = create_source_dirs(["build"], tmp_path)
        assert (tmp_path / ".kanon-data" / "sources" / "build").is_dir()
        assert result["build"] == tmp_path / ".kanon-data" / "sources" / "build"


@pytest.mark.unit
class TestRepoInit:
    def test_calls_repo_init(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml")
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "repo" in cmd
            assert "init" in cmd
            assert "--no-repo-verify" in cmd

    def test_includes_repo_rev(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml", "v2.0.0")
            cmd = mock_run.call_args[0][0]
            assert "--repo-rev" in cmd
            assert "v2.0.0" in cmd

    def test_failure_exits(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "failed"
            with pytest.raises(SystemExit):
                run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml")


@pytest.mark.unit
class TestRepoEnvsubst:
    def test_calls_envsubst(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            run_repo_envsubst(source_dir, {"GITBASE": "https://example.com/"})
            call_env = mock_run.call_args[1]["env"]
            assert call_env["GITBASE"] == "https://example.com/"

    def test_failure_exits(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "failed"
            with pytest.raises(SystemExit):
                run_repo_envsubst(source_dir, {})


@pytest.mark.unit
class TestRepoSync:
    def test_calls_sync(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            run_repo_sync(source_dir)
            assert mock_run.call_args[0][0] == ["repo", "sync"]

    def test_failure_exits(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.core.install.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "failed"
            with pytest.raises(SystemExit):
                run_repo_sync(source_dir)


@pytest.mark.unit
class TestSymlinkAggregation:
    def test_aggregates(self, tmp_path: pathlib.Path) -> None:
        build_pkg = tmp_path / ".kanon-data" / "sources" / "build" / ".packages"
        build_pkg.mkdir(parents=True)
        (build_pkg / "test-lint").mkdir()
        aggregate_symlinks(["build"], tmp_path)
        link = tmp_path / ".packages" / "test-lint"
        assert link.is_symlink()

    def test_collision_exits(self, tmp_path: pathlib.Path) -> None:
        for src in ["a", "b"]:
            pkg = tmp_path / ".kanon-data" / "sources" / src / ".packages"
            pkg.mkdir(parents=True)
            (pkg / "dup").mkdir()
        with pytest.raises(SystemExit):
            aggregate_symlinks(["a", "b"], tmp_path)


@pytest.mark.unit
class TestGitignore:
    def test_creates_gitignore(self, tmp_path: pathlib.Path) -> None:
        update_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert ".packages/" in content
        assert ".kanon-data/" in content

    def test_idempotent(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".gitignore").write_text(".packages/\n.kanon-data/\n")
        update_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".packages/") == 1


@pytest.mark.unit
class TestMarketplace:
    def test_prepare_creates_dir(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "mp"
        prepare_marketplace_dir(mp_dir)
        assert mp_dir.is_dir()

    def test_prepare_cleans_dir(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        (mp_dir / "stale").mkdir()
        prepare_marketplace_dir(mp_dir)
        assert list(mp_dir.iterdir()) == []


@pytest.mark.unit
class TestInstallLifecycle:
    def test_marketplace_true_missing_dir_exits(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        with pytest.raises(SystemExit):
            install(kanonenv)

    def test_full_lifecycle(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / ".claude-mp"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_REV=v2.0.0\n"
            "GITBASE=https://example.com/\n"
            f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        with (
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_install,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            install(kanonenv)

        assert mp_dir.is_dir()
        assert (tmp_path / ".kanon-data" / "sources" / "build").is_dir()
        mock_install.assert_called_once_with(mp_dir)

    def test_wildcard_revision_resolved_before_repo_init(self, tmp_path: pathlib.Path) -> None:
        """resolve_version must be called for source revisions with PEP 440 specifiers."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=*\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        with (
            patch("kanon_cli.core.install.subprocess.run") as mock_run,
            patch("kanon_cli.core.install.resolve_version", return_value="3.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            install(kanonenv)

        mock_resolve.assert_called_once_with("https://example.com/build.git", "*")
        # Confirm the resolved tag was used in the repo init command
        repo_init_call = mock_run.call_args_list[0]
        assert "3.0.0" in repo_init_call.kwargs.get("args", repo_init_call.args[0])
