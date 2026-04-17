"""Tests for install core business logic."""

import pathlib
from unittest.mock import MagicMock, patch

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
from kanon_cli.repo import RepoCommandError


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
        with patch("kanon_cli.repo.repo_init") as mock_init:
            run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml")
            mock_init.assert_called_once()
            args, kwargs = mock_init.call_args
            all_args = args + tuple(kwargs.values())
            assert "https://example.com/r.git" in all_args
            assert "main" in all_args
            assert "meta.xml" in all_args

    def test_passes_correct_source_dir(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_init") as mock_init:
            run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml")
            args, kwargs = mock_init.call_args
            all_args = args + tuple(kwargs.values())
            assert str(source_dir) in all_args

    def test_includes_repo_rev(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_init") as mock_init:
            run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml", "v2.0.0")
            args, kwargs = mock_init.call_args
            all_args = args + tuple(kwargs.values())
            assert "v2.0.0" in all_args

    def test_failure_raises_system_exit(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_init") as mock_init:
            mock_init.side_effect = RepoCommandError(
                exit_code=1,
                message="repo init failed: connection refused",
            )
            with pytest.raises(SystemExit):
                run_repo_init(source_dir, "https://example.com/r.git", "main", "meta.xml")
            mock_init.assert_called_once()


@pytest.mark.unit
class TestRepoEnvsubst:
    def test_calls_envsubst(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_envsubst") as mock_envsubst:
            run_repo_envsubst(source_dir, {"GITBASE": "https://example.com/"})
            mock_envsubst.assert_called_once()
            args, kwargs = mock_envsubst.call_args
            all_args = args + tuple(kwargs.values())
            assert {"GITBASE": "https://example.com/"} in all_args

    def test_passes_correct_source_dir(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_envsubst") as mock_envsubst:
            run_repo_envsubst(source_dir, {})
            mock_envsubst.assert_called_once()
            args, kwargs = mock_envsubst.call_args
            all_args = args + tuple(kwargs.values())
            assert str(source_dir) in all_args

    def test_failure_raises_system_exit(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_envsubst") as mock_envsubst:
            mock_envsubst.side_effect = RepoCommandError(
                exit_code=1,
                message="repo envsubst failed: manifest not found",
            )
            with pytest.raises(SystemExit):
                run_repo_envsubst(source_dir, {})
            mock_envsubst.assert_called_once()


@pytest.mark.unit
class TestRepoSync:
    def test_calls_sync(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            run_repo_sync(source_dir)
            mock_sync.assert_called_once()
            args, kwargs = mock_sync.call_args
            all_args = args + tuple(kwargs.values())
            assert str(source_dir) in all_args

    def test_failure_raises_system_exit(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            mock_sync.side_effect = RepoCommandError(
                exit_code=1,
                message="repo sync failed: network timeout",
            )
            with pytest.raises(SystemExit):
                run_repo_sync(source_dir)
            mock_sync.assert_called_once()


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
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync") as mock_sync,
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_install,
        ):
            install(kanonenv)

        assert mp_dir.is_dir()
        assert (tmp_path / ".kanon-data" / "sources" / "build").is_dir()
        mock_init.assert_called_once()
        mock_envsubst.assert_called_once()
        mock_sync.assert_called_once()
        mock_install.assert_called_once_with(mp_dir)

    def test_api_calls_in_correct_sequence(self, tmp_path: pathlib.Path) -> None:
        """init, envsubst, and sync must be called in order for each source."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        manager = MagicMock()
        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync") as mock_sync,
        ):
            manager.attach_mock(mock_init, "repo_init")
            manager.attach_mock(mock_envsubst, "repo_envsubst")
            manager.attach_mock(mock_sync, "repo_sync")
            install(kanonenv)

        call_names = [c[0] for c in manager.mock_calls]
        assert call_names == ["repo_init", "repo_envsubst", "repo_sync"], (
            f"Expected API calls in sequence [repo_init, repo_envsubst, repo_sync], got {call_names!r}"
        )

    def test_wildcard_revision_resolved_before_repo_init(self, tmp_path: pathlib.Path) -> None:
        """resolve_version must be called for source revisions with PEP 440 specifiers."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=*\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.resolve_version", return_value="3.0.0") as mock_resolve,
        ):
            install(kanonenv)

        mock_resolve.assert_called_once_with("https://example.com/build.git", "*")
        args, kwargs = mock_init.call_args
        all_args = args + tuple(kwargs.values())
        assert "3.0.0" in all_args, (
            f"repo_init must be called with the resolved revision '3.0.0', but call args were: {mock_init.call_args!r}"
        )
