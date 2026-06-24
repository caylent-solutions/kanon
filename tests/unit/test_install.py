"""Tests for install core business logic.

Covers:
- Source directory creation
- Repo init/sync/envsubst lifecycle
- .gitignore management
- Manifest working-tree reset
- aggregate_symlinks
- create_dirsymlink
- utf-8 encoding sweep (AC-12): read_text/write_text callsites specify encoding="utf-8"
"""

import argparse
import pathlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.install import _run
from tests.conftest import bare_text_io_calls
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    _RefResolution,
    _reset_manifests_working_tree,
    aggregate_symlinks,
    create_source_dirs,
    install,
    prepare_marketplace_dir,
    RefreshRepoInitError,
    run_repo_envsubst,
    run_repo_init,
    run_repo_sync,
    update_gitignore,
)
from kanon_cli.core.marketplace import create_dirsymlink
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

    def test_oserror_propagates_with_path_context(self, tmp_path: pathlib.Path) -> None:
        """create_source_dirs raises OSError with path context when mkdir fails."""
        with patch("pathlib.Path.mkdir", side_effect=OSError(13, "Permission denied")):
            with pytest.raises(OSError) as exc_info:
                create_source_dirs(["src"], tmp_path)
        assert "Cannot create source directory" in str(exc_info.value)

    def test_oserror_message_contains_strerror(self, tmp_path: pathlib.Path) -> None:
        """OSError raised by create_source_dirs includes the OS error message."""
        with patch("pathlib.Path.mkdir", side_effect=OSError(13, "Permission denied")):
            with pytest.raises(OSError) as exc_info:
                create_source_dirs(["src"], tmp_path)
        assert "Permission denied" in str(exc_info.value)


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

    def test_failure_raises_repo_command_error(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_init") as mock_init:
            mock_init.side_effect = RepoCommandError(
                exit_code=1,
                message="repo init failed: connection refused",
            )
            with pytest.raises(RepoCommandError):
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

    def test_failure_raises_repo_command_error(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_envsubst") as mock_envsubst:
            mock_envsubst.side_effect = RepoCommandError(
                exit_code=1,
                message="repo envsubst failed: manifest not found",
            )
            with pytest.raises(RepoCommandError):
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

    def test_failure_raises_repo_command_error(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            mock_sync.side_effect = RepoCommandError(
                exit_code=1,
                message="repo sync failed: network timeout",
            )
            with pytest.raises(RepoCommandError):
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

    def test_collision_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        for src in ["a", "b"]:
            pkg = tmp_path / ".kanon-data" / "sources" / src / ".packages"
            pkg.mkdir(parents=True)
            (pkg / "dup").mkdir()
        with pytest.raises(ValueError):
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
    _CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
    _FAKE_SHA = "a" * 40

    _FAKE_REF_RESOLUTION = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")

    def test_create_source_dirs_oserror_causes_system_exit(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install() exits 1 when create_source_dirs raises OSError."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
        args = argparse.Namespace(
            kanonenv_path=kanonenv,
            lock_file=None,
            refresh_lock=False,
            refresh_lock_source=None,
            strict_lock=False,
            strict_drift=False,
        )
        with (
            patch(
                "kanon_cli.core.install.create_source_dirs",
                side_effect=OSError("Cannot create source directory /x: Permission denied"),
            ),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _run(args)
        assert exc_info.value.code == 1

    def test_marketplace_true_missing_dir_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
            "KANON_SOURCE_build_MARKETPLACE=true\n"
        )
        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            pytest.raises(ValueError),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

    def test_full_lifecycle(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mp_dir = tmp_path / ".claude-mp"
        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_REV=v2.0.0\n"
            "GITBASE=https://example.com/\n"
            f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
            "KANON_SOURCE_build_MARKETPLACE=true\n"
        )

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync") as mock_sync,
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_install,
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert mp_dir.is_dir()
        assert (store / ".kanon-data" / "sources" / "build").is_dir()
        mock_init.assert_called_once()
        mock_envsubst.assert_called_once()
        mock_sync.assert_called_once()
        mock_install.assert_called_once_with(mp_dir)

    def test_register_direct_checkout_marketplaces_called_when_marketplace_install(
        self, tmp_path: pathlib.Path
    ) -> None:
        """BUG-3 fix: install() calls register_direct_checkout_marketplaces for each
        source whose KANON_SOURCE_<alias>_MARKETPLACE=true, so that direct-checkout
        entries carrying .claude-plugin/marketplace.json are registered even when no
        <linkfile> element is present in the manifest XML.
        """
        mp_dir = tmp_path / ".claude-mp"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_REV=v2.0.0\n"
            "GITBASE=https://example.com/\n"
            f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
            "KANON_SOURCE_build_MARKETPLACE=true\n"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins"),
            patch("kanon_cli.core.install.register_direct_checkout_marketplaces") as mock_reg,
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert mock_reg.called, (
            "register_direct_checkout_marketplaces must be called when KANON_SOURCE_<alias>_MARKETPLACE=true"
        )
        call_args = mock_reg.call_args
        assert call_args is not None

        passed_marketplace_dir = call_args[0][2]
        assert str(passed_marketplace_dir) == str(mp_dir), (
            f"register_direct_checkout_marketplaces must be called with marketplace_dir={mp_dir!r}, "
            f"got {passed_marketplace_dir!r}"
        )

    def test_register_direct_checkout_marketplaces_not_called_without_flag(self, tmp_path: pathlib.Path) -> None:
        """Without any KANON_SOURCE_<alias>_MARKETPLACE=true flag,
        register_direct_checkout_marketplaces must NOT be called (AC-FUNC-003:
        default false registers nothing).
        """
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.register_direct_checkout_marketplaces") as mock_reg,
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert not mock_reg.called, (
            "register_direct_checkout_marketplaces must NOT be called when no "
            "KANON_SOURCE_<alias>_MARKETPLACE flag is true/present"
        )

    def test_api_calls_in_correct_sequence(self, tmp_path: pathlib.Path) -> None:
        """init, envsubst, and sync must be called in order for each source."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        manager = MagicMock()
        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync") as mock_sync,
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            manager.attach_mock(mock_init, "repo_init")
            manager.attach_mock(mock_envsubst, "repo_envsubst")
            manager.attach_mock(mock_sync, "repo_sync")
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        call_names = [c[0] for c in manager.mock_calls]
        assert call_names == ["repo_init", "repo_envsubst", "repo_sync"], (
            f"Expected API calls in sequence [repo_init, repo_envsubst, repo_sync], got {call_names!r}"
        )

    def test_wildcard_revision_resolved_before_repo_init(self, tmp_path: pathlib.Path) -> None:
        """resolve_version must be called for source revisions with PEP 440 specifiers."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=*\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.resolve_version", return_value="3.0.0") as mock_resolve,
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        mock_resolve.assert_called_once_with("https://example.com/build.git", "*")
        args, kwargs = mock_init.call_args
        all_args = args + tuple(kwargs.values())
        assert "3.0.0" in all_args, (
            f"repo_init must be called with the resolved revision '3.0.0', but call args were: {mock_init.call_args!r}"
        )


@pytest.mark.unit
class TestInstallWorkspaceLock:
    """install() acquires kanon_workspace_lock, creating .kanon-data/ eagerly."""

    _CATALOG_SOURCE = "https://example.com/catalog.git@main"
    _FAKE_REF_RESOLUTION = MagicMock(
        ref="refs/tags/1.0.0",
        sha="abc123",
    )

    def test_install_creates_kanon_data_dir(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """install() creates .kanon-data/ under the KANON_HOME store via eager-create.

        A fresh store with no prior .kanon-data/ must end up with the directory
        under <KANON_HOME>/store after install() runs (even if the install fails
        later).

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.core.install import _RefResolution

        fake_resolution = _RefResolution(sha="abc123", resolved_ref="refs/tags/1.0.0")

        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        assert not (store / ".kanon-data").exists()

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert (store / ".kanon-data").is_dir(), (
            "install() must create .kanon-data/ under <KANON_HOME>/store as a side effect "
            "of kanon_workspace_lock eager-create"
        )

    def test_install_lock_file_created_in_kanon_data(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install() creates the workspace lock file inside the store .kanon-data/.

        After install() completes, the lock file must persist at
        <KANON_HOME>/store/.kanon-data/INSTALL_LOCK_FILENAME so subsequent
        invocations can lock on the same file.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.constants import INSTALL_LOCK_FILENAME
        from kanon_cli.core.install import _RefResolution

        fake_resolution = _RefResolution(sha="abc123", resolved_ref="refs/tags/1.0.0")

        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        lock_path = store / ".kanon-data" / INSTALL_LOCK_FILENAME
        assert lock_path.exists(), f"Workspace lock file must exist at {lock_path} after install() completes"


@pytest.mark.unit
class TestInstallSubparserHelp:
    """The 'install' subparser has add_help=True and accepts '-h'."""

    def test_install_short_dash_h_exits_0(self) -> None:
        """kanon install -h exits 0 (add_help=True on the install subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["install", "-h"])
        assert exc_info.value.code == 0

    def test_install_subparser_has_add_help_true(self) -> None:
        """The 'install' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.install import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        install_parser = subparsers.choices["install"]
        assert install_parser.add_help is True, "install subparser must have add_help=True so '-h' is accepted"


@pytest.mark.unit
class TestResetManifestsWorkingTree:
    """Unit tests for _reset_manifests_working_tree (BUG-1 fix helper).

    Covers the helper that restores the .repo/manifests working tree to a
    clean state before repo re-init on the --refresh-lock[-source] path.
    AC-TEST-003.
    """

    def _init_git_repo(self, path: pathlib.Path) -> None:
        """Initialise a bare-minimum git repo at path with a tracked file."""
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
        (path / "manifest.xml").write_text("<manifest/>\n")
        subprocess.run(["git", "add", "manifest.xml"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)

    def test_noop_when_manifests_dir_absent(self, tmp_path: pathlib.Path) -> None:
        """_reset_manifests_working_tree is a no-op when .repo/manifests does not exist.

        This covers the first-install path where no prior envsubst has run.
        """
        source_dir = tmp_path / ".kanon-data" / "sources" / "SRC"
        source_dir.mkdir(parents=True)

        _reset_manifests_working_tree(source_dir)

    def test_restores_modified_tracked_file(self, tmp_path: pathlib.Path) -> None:
        """Modified tracked files are restored to their HEAD state.

        Simulates the envsubst step that rewrites manifest.xml: after reset,
        manifest.xml is back to its committed content.
        """
        manifests_dir = tmp_path / ".repo" / "manifests"
        self._init_git_repo(manifests_dir)

        (manifests_dir / "manifest.xml").write_text("<manifest><!-- envsubst was here --></manifest>\n")
        status_before = subprocess.run(
            ["git", "status", "--short"], cwd=manifests_dir, capture_output=True, text=True
        ).stdout.strip()
        assert "manifest.xml" in status_before, "manifest.xml should be dirty before reset"

        source_dir = tmp_path
        _reset_manifests_working_tree(source_dir)

        restored = (manifests_dir / "manifest.xml").read_text()
        assert restored == "<manifest/>\n", (
            f"Expected manifest.xml to be restored to '<manifest/>\\n', got {restored!r}"
        )
        status_after = subprocess.run(
            ["git", "status", "--short"], cwd=manifests_dir, capture_output=True, text=True
        ).stdout.strip()
        assert "manifest.xml" not in status_after, (
            f"manifest.xml should be clean after reset, got git status: {status_after!r}"
        )

    def test_removes_bak_files(self, tmp_path: pathlib.Path) -> None:
        """Untracked .bak files created by envsubst are removed.

        envsubst creates <manifest>.bak sibling files on the first substitution
        run.  These files are untracked in the git working tree; git checkout --
        leaves them untouched, so _reset_manifests_working_tree must remove them
        explicitly.
        """
        manifests_dir = tmp_path / ".repo" / "manifests"
        self._init_git_repo(manifests_dir)

        bak = manifests_dir / "manifest.xml.bak"
        bak.write_text("<manifest/>\n")
        assert bak.exists(), "manifest.xml.bak should exist before reset"

        source_dir = tmp_path
        _reset_manifests_working_tree(source_dir)

        assert not bak.exists(), ".bak file should be removed by _reset_manifests_working_tree"

    def test_noop_when_manifests_dir_not_a_git_repo(self, tmp_path: pathlib.Path) -> None:
        """_reset_manifests_working_tree is a no-op when .repo/manifests exists but is not a git repo.

        Integration tests create a plain directory in place of a real repo; the function
        must return without raising and must not alter the directory contents.
        AC-1, AC-3 (non-git no-op guard).
        """
        manifests_dir = tmp_path / ".repo" / "manifests"
        manifests_dir.mkdir(parents=True)
        sentinel = manifests_dir / "manifest.xml"
        sentinel.write_text("<manifest/>\n")

        source_dir = tmp_path

        _reset_manifests_working_tree(source_dir)

        assert sentinel.exists(), "manifest.xml should be untouched when directory is not a git repo"
        assert sentinel.read_text() == "<manifest/>\n", (
            "manifest.xml should be unmodified when directory is not a git repo"
        )

    def test_raises_oserror_when_git_checkout_fails_on_valid_git_repo(self, tmp_path: pathlib.Path) -> None:
        """OSError is raised when git checkout fails on a valid git working tree.

        Verifies the no-op guard does not swallow a real reset failure on a real git repo.
        AC-4.
        """
        manifests_dir = tmp_path / ".repo" / "manifests"
        self._init_git_repo(manifests_dir)

        failed_result = MagicMock()
        failed_result.returncode = 1
        failed_result.stderr = "simulated git checkout failure"

        with patch("kanon_cli.core.install.subprocess.run", return_value=failed_result):
            source_dir = tmp_path
            with pytest.raises(OSError, match="_reset_manifests_working_tree"):
                _reset_manifests_working_tree(source_dir)


@pytest.mark.unit
class TestRefreshRepoInitError:
    """Unit tests for RefreshRepoInitError (BUG-1 fix handled error class).

    Covers the error's string representation: source name included, cause
    string included, remediation line present.  AC-TEST-003.
    """

    def test_str_contains_source_name(self) -> None:
        """The error string includes the offending source name."""
        cause = RuntimeError("bad revision '^HEAD'")
        err = RefreshRepoInitError(source_name="MY_SOURCE", cause=cause)
        assert "MY_SOURCE" in str(err), f"Expected source name in error string, got: {str(err)!r}"

    def test_str_contains_cause(self) -> None:
        """The error string includes the cause's text."""
        cause = RuntimeError("bad revision '^HEAD'")
        err = RefreshRepoInitError(source_name="SRC", cause=cause)
        assert "bad revision" in str(err), f"Expected cause text in error string, got: {str(err)!r}"

    def test_str_starts_with_error_prefix(self) -> None:
        """The error string starts with 'ERROR:' per the kanon error shape."""
        cause = ValueError("something went wrong")
        err = RefreshRepoInitError(source_name="SRC", cause=cause)
        assert str(err).startswith("ERROR:"), f"Expected 'ERROR:' prefix in error string, got: {str(err)!r}"

    def test_str_contains_remediation(self) -> None:
        """The error string contains a remediation hint."""
        cause = ValueError("something went wrong")
        err = RefreshRepoInitError(source_name="SRC", cause=cause)
        assert "Remediation" in str(err) or "remediation" in str(err).lower(), (
            f"Expected remediation hint in error string, got: {str(err)!r}"
        )

    def test_is_install_error_subclass(self) -> None:
        """RefreshRepoInitError is a subclass of InstallError for unified CLI handling."""
        from kanon_cli.core.install import InstallError

        cause = ValueError("x")
        err = RefreshRepoInitError(source_name="SRC", cause=cause)
        assert isinstance(err, InstallError), (
            "RefreshRepoInitError must be an InstallError subclass so the CLI "
            "catches it and prints a structured ERROR: message"
        )


@pytest.mark.unit
class TestInstallMarketplaceLockfileState:
    """AC-7: install records marketplace_registered in the lockfile."""

    _CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
    _FAKE_REF_RESOLUTION = None

    def setup_method(self):
        from kanon_cli.core.install import _RefResolution

        self._FAKE_REF_RESOLUTION = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")

    def test_install_with_marketplace_writes_registered_true_to_lockfile(self, tmp_path: pathlib.Path) -> None:
        """AC-7: install with a KANON_SOURCE_<alias>_MARKETPLACE=true dependency writes
        marketplace_registered=true.
        """
        from kanon_cli.core.lockfile import read_lockfile

        mp_dir = tmp_path / ".claude-mp"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n"
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
            "KANON_SOURCE_build_MARKETPLACE=true\n"
        )
        lock_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins"),
            patch("kanon_cli.core.install.register_direct_checkout_marketplaces"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch(
                "kanon_cli.core.install._walk_includes",
                return_value=IncludeTree(path=pathlib.Path("meta.xml")),
            ),
        ):
            install(kanonenv, lock_file_path=lock_path)

        lf = read_lockfile(lock_path)
        assert lf.marketplace_registered is True, (
            "install with a KANON_SOURCE_<alias>_MARKETPLACE=true dependency must write marketplace_registered=true"
        )
        assert lf.marketplace_dir == str(mp_dir), (
            "install must record marketplace_dir in the lockfile when marketplace is registered"
        )

    def test_install_without_marketplace_writes_registered_false_to_lockfile(self, tmp_path: pathlib.Path) -> None:
        """AC-7: install with no KANON_SOURCE_<alias>_MARKETPLACE=true dependency writes
        marketplace_registered=false.
        """
        from kanon_cli.core.lockfile import read_lockfile

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )
        lock_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch(
                "kanon_cli.core.install._walk_includes",
                return_value=IncludeTree(path=pathlib.Path("meta.xml")),
            ),
        ):
            install(kanonenv, lock_file_path=lock_path)

        lf = read_lockfile(lock_path)
        assert lf.marketplace_registered is False, (
            "install with no KANON_SOURCE_<alias>_MARKETPLACE=true dependency must write marketplace_registered=false"
        )
        assert lf.marketplace_dir == "", "install must write empty marketplace_dir when no marketplace is registered"


@pytest.mark.unit
class TestInstallKanonHomeStore:
    """install() places .packages/ and .kanon-data/ under <KANON_HOME>/store.

    The artifact base resolves to the shared KANON_HOME store (spec Section 7.1 /
    Section 8 / FR-15), replacing the removed KANON_WORKSPACE_DIR override. The
    .kanon / .kanon.lock files stay in the project directory; only fetched
    artifacts move into the store.
    """

    _CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
    _FAKE_REF_RESOLUTION = None

    def setup_method(self):
        from kanon_cli.core.install import _RefResolution

        self._FAKE_REF_RESOLUTION = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")

    def _write_kanonenv(self, path: pathlib.Path) -> None:
        path.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_NAME=build\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )

    def _patched_install(self, kanonenv: pathlib.Path, lock_path: pathlib.Path) -> None:
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch(
                "kanon_cli.core.install._walk_includes",
                return_value=IncludeTree(path=pathlib.Path("meta.xml")),
            ),
        ):
            install(kanonenv, lock_file_path=lock_path)

    def test_install_creates_artifacts_under_kanon_home_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-23: .kanon-data/ lands under <KANON_HOME>/store, never in cwd."""
        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        cwd_dir = tmp_path / "cwd_dir"
        cwd_dir.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = cwd_dir / ".kanon"
        self._write_kanonenv(kanonenv)
        lock_path = cwd_dir / ".kanon.lock"

        self._patched_install(kanonenv, lock_path)

        assert (store / ".kanon-data").exists(), ".kanon-data/ must be created under <KANON_HOME>/store"
        assert not (cwd_dir / ".kanon-data").exists(), ".kanon-data/ must NOT be created in cwd"
        assert not (cwd_dir / ".packages").exists(), ".packages/ must NOT be created in cwd"

    def test_install_creates_packages_under_kanon_home_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-23: .packages/ lands under <KANON_HOME>/store."""
        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = cwd_dir / ".kanon"
        self._write_kanonenv(kanonenv)
        lock_path = cwd_dir / ".kanon.lock"

        self._patched_install(kanonenv, lock_path)

        assert (store / ".packages").exists(), ".packages/ must be created under <KANON_HOME>/store"

    def test_install_store_created_if_absent(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-23: the KANON_HOME store is created automatically when it does not exist."""
        kanon_home = tmp_path / "new_dir" / "deeply_nested"
        store = kanon_home / "store"
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        assert not store.exists(), "pre-condition: the store must not exist before install"

        kanonenv = cwd_dir / ".kanon"
        self._write_kanonenv(kanonenv)
        lock_path = cwd_dir / ".kanon.lock"

        self._patched_install(kanonenv, lock_path)

        assert store.exists(), "install must create the <KANON_HOME>/store directory if it does not exist"

    def test_install_unwritable_kanon_home_exits_nonzero(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-23: an unwritable KANON_HOME causes a non-zero exit with no cwd fallback."""
        import stat

        locked_parent = tmp_path / "locked"
        locked_parent.mkdir()
        unwritable_home = locked_parent / "home"
        locked_parent.chmod(stat.S_IRUSR | stat.S_IXUSR)

        monkeypatch.setenv("KANON_HOME", str(unwritable_home))
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir(parents=True, exist_ok=True)

        kanonenv = cwd_dir / ".kanon"
        self._write_kanonenv(kanonenv)
        lock_path = cwd_dir / ".kanon.lock"

        try:
            with pytest.raises(SystemExit) as exc_info:
                self._patched_install(kanonenv, lock_path)
            assert exc_info.value.code != 0, "unwritable KANON_HOME must exit non-zero"
            assert not (cwd_dir / ".kanon-data").exists(), (
                "on unwritable KANON_HOME, no artifacts must be written to cwd (no fallback)"
            )
            assert not (cwd_dir / ".packages").exists(), (
                "on unwritable KANON_HOME, no .packages/ must appear in cwd (no fallback)"
            )
        finally:
            locked_parent.chmod(stat.S_IRWXU)


@pytest.mark.unit
class TestInstallImportsGitRunner:
    """install.py imports run_git_ls_remote from kanon_cli.core.git_runner (AC-4)."""

    def test_run_git_ls_remote_importable_from_install_module(self) -> None:
        """run_git_ls_remote is accessible in the install module namespace."""
        import kanon_cli.core.install as install_mod

        assert hasattr(install_mod, "run_git_ls_remote")

    def test_install_uses_kanon_git_ls_remote_timeout_constant(self) -> None:
        """install.py references KANON_GIT_LS_REMOTE_TIMEOUT from constants (not inline literal)."""
        import inspect

        import kanon_cli.core.install as install_mod

        source = inspect.getsource(install_mod)
        assert "KANON_GIT_LS_REMOTE_TIMEOUT" in source, (
            "install.py must reference KANON_GIT_LS_REMOTE_TIMEOUT from constants"
        )

        assert 'os.environ.get("KANON_GIT_LS_REMOTE_TIMEOUT"' not in source, (
            "install.py must not contain inline os.environ.get KANON_GIT_LS_REMOTE_TIMEOUT literal"
        )


@pytest.mark.unit
class TestAggregateSymlinksUsesJunctionHelper:
    """aggregate_symlinks must route its directory link through create_dirsymlink (AC-10)."""

    def test_aggregate_symlinks_calls_create_dirsymlink(self, tmp_path: pathlib.Path) -> None:
        """aggregate_symlinks calls create_dirsymlink for each package link."""
        build_pkg = tmp_path / ".kanon-data" / "sources" / "build" / ".packages"
        build_pkg.mkdir(parents=True)
        (build_pkg / "test-lint").mkdir()

        with patch("kanon_cli.core.install.create_dirsymlink") as mock_helper:
            aggregate_symlinks(["build"], tmp_path)

        mock_helper.assert_called_once()
        call_args = mock_helper.call_args

        assert call_args[0][0].name == "test-lint", (
            "create_dirsymlink must be called with link_path named after the package"
        )

    def test_aggregate_symlinks_produces_directory_link_on_posix(self, tmp_path: pathlib.Path) -> None:
        """aggregate_symlinks produces a working directory link on POSIX (not a mock)."""
        build_pkg = tmp_path / ".kanon-data" / "sources" / "build" / ".packages"
        build_pkg.mkdir(parents=True)
        pkg_dir = build_pkg / "my-tool"
        pkg_dir.mkdir()
        (pkg_dir / "tool.sh").write_text("#!/bin/sh\necho hi\n")

        aggregate_symlinks(["build"], tmp_path)

        link = tmp_path / ".packages" / "my-tool"
        assert link.is_symlink(), f"Expected symlink at {link}"
        assert link.is_dir(), f"Expected symlink to resolve to a directory at {link}"
        assert (link / "tool.sh").is_file(), "Expected tool.sh accessible through the link"

    def test_create_dirsymlink_fails_fast_on_error(self, tmp_path: pathlib.Path) -> None:
        """create_dirsymlink raises OSError with an actionable message when link creation fails."""
        target = tmp_path / "real-dir"
        target.mkdir()
        link = tmp_path / "the-link"

        link.mkdir()

        with pytest.raises(OSError):
            create_dirsymlink(link, target)


_INSTALL_PY = pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "core" / "install.py"


@pytest.mark.unit
class TestInstallPyUtf8EncodingSweep:
    """AC-12: all read_text/write_text calls in core/install.py specify encoding."""

    def test_no_bare_read_text_calls(self) -> None:
        """core/install.py must not contain bare .read_text() calls (no encoding arg)."""
        bare = bare_text_io_calls(_INSTALL_PY)
        read_bare = [b for b in bare if "read_text" in b[1]]
        assert read_bare == [], (
            f"core/install.py has bare read_text() calls: {read_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )

    def test_no_bare_write_text_calls(self) -> None:
        """core/install.py must not contain bare .write_text() calls (no encoding arg)."""
        bare = bare_text_io_calls(_INSTALL_PY)
        write_bare = [b for b in bare if "write_text" in b[1]]
        assert write_bare == [], (
            f"core/install.py has bare write_text() calls: {write_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )


@pytest.mark.unit
class TestComputeStoreEntryAddress:
    """compute_store_entry_address derives a deterministic content address."""

    def test_deterministic_for_same_url_and_sha(self) -> None:
        """The same (url, sha) yields the same address across calls (dedup key)."""
        from kanon_cli.core.install import compute_store_entry_address

        sha = "a" * 40
        first = compute_store_entry_address("https://example.com/repo.git", sha)
        second = compute_store_entry_address("https://example.com/repo.git", sha)
        assert first == second
        assert len(first) == 64
        assert all(c in "0123456789abcdef" for c in first)

    def test_canonical_url_variants_collapse_to_one_address(self) -> None:
        """SSH and HTTPS forms of the same remote produce one address (canonicalized)."""
        from kanon_cli.core.install import compute_store_entry_address

        sha = "b" * 40
        https = compute_store_entry_address("https://example.com/org/repo.git", sha)
        ssh = compute_store_entry_address("git@example.com:org/repo.git", sha)
        assert https == ssh

    def test_distinct_sha_yields_distinct_address(self) -> None:
        """A different SHA produces a different content address (immutability)."""
        from kanon_cli.core.install import compute_store_entry_address

        url = "https://example.com/repo.git"
        assert compute_store_entry_address(url, "a" * 40) != compute_store_entry_address(url, "c" * 40)

    @pytest.mark.parametrize(
        "url,sha",
        [
            ("", "a" * 40),
            ("https://example.com/repo.git", ""),
        ],
    )
    def test_empty_argument_fails_fast(self, url: str, sha: str) -> None:
        """An empty url or sha raises ValueError (no silent unidentified address)."""
        from kanon_cli.core.install import compute_store_entry_address

        with pytest.raises(ValueError):
            compute_store_entry_address(url, sha)


@pytest.mark.unit
class TestPublishStoreEntry:
    """publish_store_entry publishes via atomic rename, dedups, and locks per entry."""

    def test_publishes_into_final_content_addressed_path(self, tmp_path: pathlib.Path) -> None:
        """A fresh publish materializes content under store/entries/<address>."""
        from kanon_cli.core.install import publish_store_entry, store_entries_dir

        store = tmp_path / "store"
        store.mkdir()
        address = "f" * 64

        def materialize(dest: pathlib.Path) -> None:
            (dest / "marker.txt").write_text("payload", encoding="utf-8")

        final = publish_store_entry(store, address, materialize)

        assert final == store_entries_dir(store) / address
        assert final.is_dir()
        assert (final / "marker.txt").read_text(encoding="utf-8") == "payload"

    def test_dedup_skips_rematerialize_when_final_path_exists(self, tmp_path: pathlib.Path) -> None:
        """A second publish of the same address is a dedup no-op (readiness via existence)."""
        from kanon_cli.core.install import publish_store_entry

        store = tmp_path / "store"
        store.mkdir()
        address = "1" * 64
        call_count = {"n": 0}

        def materialize(dest: pathlib.Path) -> None:
            call_count["n"] += 1
            (dest / "data").write_text("x", encoding="utf-8")

        first = publish_store_entry(store, address, materialize)
        second = publish_store_entry(store, address, materialize)

        assert first == second
        assert call_count["n"] == 1, "the second publish must not re-materialize an existing entry"

    def test_no_sleep_call_in_install_core(self) -> None:
        """AC-24: no time.sleep() call is introduced under src/kanon_cli/core (no poll-sleep).

        The check matches the call syntax ``time.sleep(`` (a real sleep call),
        not the bare token that appears in prose. ``core/git_runner.py`` documents
        the ABSENCE of a sleep with the literal token inside its docstring; that
        prose is not a sleep call and must not be flagged. The store-publish path
        added by this work unit blocks on a kernel lock and detects readiness via
        final-path existence, never a poll-sleep.
        """
        import re

        core_dir = pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "core"
        call_pattern = re.compile(r"\btime\.sleep\s*\(")
        offenders = []
        for py in core_dir.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if call_pattern.search(text):
                offenders.append(str(py))
        assert offenders == [], f"time.sleep() call must not appear under core/: {offenders}"

    def test_atomic_rename_used_in_publish(self) -> None:
        """AC-24: the publish path uses an atomic rename (Path.replace) into the store."""
        install_py = pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "core" / "install.py"
        text = install_py.read_text(encoding="utf-8")
        assert ".replace(final_path)" in text, "publish must atomically rename the temp dir into the final path"

    def test_partial_materialize_leaves_no_final_entry(self, tmp_path: pathlib.Path) -> None:
        """A failing materialize callback removes the temp dir and never creates the final entry."""
        from kanon_cli.core.install import publish_store_entry, store_entries_dir

        store = tmp_path / "store"
        store.mkdir()
        address = "2" * 64

        def materialize(dest: pathlib.Path) -> None:
            (dest / "half").write_text("partial", encoding="utf-8")
            raise RuntimeError("materialize blew up")

        with pytest.raises(RuntimeError, match="materialize blew up"):
            publish_store_entry(store, address, materialize)

        assert not (store_entries_dir(store) / address).exists(), "no final entry on materialize failure"

    @pytest.mark.parametrize("bad_address", ["", "with/slash", "a" + __import__("os").sep + "b"])
    def test_non_single_component_address_fails_fast(self, tmp_path: pathlib.Path, bad_address: str) -> None:
        """An address that is not a single path component raises ValueError (fail fast)."""
        from kanon_cli.core.install import publish_store_entry

        store = tmp_path / "store"
        store.mkdir()
        with pytest.raises(ValueError):
            publish_store_entry(store, bad_address, lambda dest: None)

    def test_contended_publish_fails_fast_on_timeout(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A held per-entry lock makes a second in-process publish fail fast with diagnostics.

        The E2 ``kanon_workspace_lock`` re-entrance guard raises immediately when
        the same process already holds the per-entry lock, so a nested publish of
        the same address fails fast (no deadlock, no sleep). This proves the
        publish guards each entry with the per-entry lock rather than racing.
        """
        from kanon_cli.core.install import compute_store_entry_address, publish_store_entry
        from kanon_cli.utils.concurrency import WorkspaceLockReentranceError

        store = tmp_path / "store"
        store.mkdir()
        address = compute_store_entry_address("https://example.com/repo.git", "d" * 40)

        captured: dict[str, Exception] = {}

        def nested_materialize(dest: pathlib.Path) -> None:

            try:
                publish_store_entry(store, address, lambda d: None)
            except WorkspaceLockReentranceError as exc:
                captured["err"] = exc
            (dest / "ok").write_text("done", encoding="utf-8")

        publish_store_entry(store, address, nested_materialize)

        assert "err" in captured, "nested publish of a held entry must hit the per-entry lock guard"
        message = str(captured["err"])
        assert "already held by this process" in message


@pytest.mark.unit
class TestStoreGitignoreSafetyNet:
    """write_store_gitignore_if_in_git_repo writes .gitignore only inside a git repo."""

    def test_no_gitignore_when_store_not_in_git_repo(self, tmp_path: pathlib.Path) -> None:
        """Outside a git working tree nothing is written (conditional safety net)."""
        from kanon_cli.core.install import write_store_gitignore_if_in_git_repo

        store = tmp_path / "home" / "store"
        store.mkdir(parents=True)
        wrote = write_store_gitignore_if_in_git_repo(store)
        assert wrote is False
        assert not (store / ".gitignore").exists()

    def test_gitignore_written_when_store_inside_git_repo(self, tmp_path: pathlib.Path) -> None:
        """Inside a git working tree the store .gitignore gains the whole-store ignore entry."""
        from kanon_cli.constants import KANON_HOME_STORE_GITIGNORE_ENTRY
        from kanon_cli.core.install import write_store_gitignore_if_in_git_repo

        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        store = repo / "nested" / "store"
        store.mkdir(parents=True)

        wrote = write_store_gitignore_if_in_git_repo(store)

        assert wrote is True
        lines = (store / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert KANON_HOME_STORE_GITIGNORE_ENTRY in lines

    def test_gitignore_safety_net_preserves_existing_entries(self, tmp_path: pathlib.Path) -> None:
        """The safety net appends the ignore entry without clobbering existing lines."""
        from kanon_cli.constants import KANON_HOME_STORE_GITIGNORE_ENTRY
        from kanon_cli.core.install import write_store_gitignore_if_in_git_repo

        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        store = repo / "store"
        store.mkdir(parents=True)
        (store / ".gitignore").write_text(".packages/\n.kanon-data/\n", encoding="utf-8")

        write_store_gitignore_if_in_git_repo(store)

        lines = (store / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert ".packages/" in lines, "existing entries must be preserved"
        assert ".kanon-data/" in lines, "existing entries must be preserved"
        assert KANON_HOME_STORE_GITIGNORE_ENTRY in lines, "the whole-store ignore entry must be appended"

    def test_gitignore_safety_net_is_idempotent(self, tmp_path: pathlib.Path) -> None:
        """Calling the safety net twice does not duplicate the ignore entry."""
        from kanon_cli.constants import KANON_HOME_STORE_GITIGNORE_ENTRY
        from kanon_cli.core.install import write_store_gitignore_if_in_git_repo

        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        store = repo / "store"
        store.mkdir(parents=True)

        write_store_gitignore_if_in_git_repo(store)
        write_store_gitignore_if_in_git_repo(store)

        lines = (store / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert lines.count(KANON_HOME_STORE_GITIGNORE_ENTRY) == 1

    def test_kanon_home_inside_git_repo_detects_worktree_dotgit_file(self, tmp_path: pathlib.Path) -> None:
        """A .git FILE (worktree/submodule) is detected as inside a git repo too."""
        from kanon_cli.core.install import kanon_home_inside_git_repo

        repo = tmp_path / "wt"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        store = repo / "store"
        store.mkdir()
        assert kanon_home_inside_git_repo(store) is True


@pytest.mark.unit
class TestPruneStore:
    """prune_store removes content-addressed entries but keeps the store base."""

    def test_prunes_entries_and_keeps_store_base(self, tmp_path: pathlib.Path) -> None:
        """prune_store removes entries/.locks/.tmp, preserving the store base dir."""
        from kanon_cli.constants import (
            KANON_HOME_STORE_LOCKS_SUBDIR,
            KANON_HOME_STORE_TMP_SUBDIR,
        )
        from kanon_cli.core.install import prune_store, store_entries_dir

        store = tmp_path / "store"
        entries = store_entries_dir(store)
        (entries / "abc").mkdir(parents=True)
        (store / KANON_HOME_STORE_LOCKS_SUBDIR / "abc").mkdir(parents=True)
        (store / KANON_HOME_STORE_TMP_SUBDIR).mkdir(parents=True)

        prune_store(store)

        assert not entries.exists()
        assert not (store / KANON_HOME_STORE_LOCKS_SUBDIR).exists()
        assert not (store / KANON_HOME_STORE_TMP_SUBDIR).exists()
        assert store.exists(), "the store base directory must survive a prune"

    def test_prune_on_absent_store_is_noop(self, tmp_path: pathlib.Path) -> None:
        """Pruning a store that was never populated is a no-op (clean before install)."""
        from kanon_cli.core.install import prune_store

        store = tmp_path / "store"
        store.mkdir()
        prune_store(store)
        assert store.exists()
