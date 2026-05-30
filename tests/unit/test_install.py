"""Tests for install core business logic."""

import argparse
import pathlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.install import _run
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
    # Catalog source used across all TestInstallLifecycle tests.
    _CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
    _FAKE_SHA = "a" * 40
    # _resolve_ref_to_sha now returns a _RefResolution named tuple; patch
    # with a consistent fake result so tests do not require network access.
    _FAKE_REF_RESOLUTION = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")

    def test_create_source_dirs_oserror_causes_system_exit(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install() exits 1 when create_source_dirs raises OSError."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        monkeypatch.setenv("KANON_CATALOG_SOURCE", self._CATALOG_SOURCE)
        args = argparse.Namespace(
            kanonenv_path=kanonenv,
            lock_file=None,
            catalog_source=None,
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
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            pytest.raises(ValueError),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

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
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

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
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            manager.attach_mock(mock_init, "repo_init")
            manager.attach_mock(mock_envsubst, "repo_envsubst")
            manager.attach_mock(mock_sync, "repo_sync")
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

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
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=self._FAKE_REF_RESOLUTION),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

        mock_resolve.assert_called_once_with("https://example.com/build.git", "*")
        args, kwargs = mock_init.call_args
        all_args = args + tuple(kwargs.values())
        assert "3.0.0" in all_args, (
            f"repo_init must be called with the resolved revision '3.0.0', but call args were: {mock_init.call_args!r}"
        )


# ---------------------------------------------------------------------------
# Tests for workspace lock integration in install()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallWorkspaceLock:
    """install() acquires kanon_workspace_lock, creating .kanon-data/ eagerly."""

    _CATALOG_SOURCE = "https://example.com/catalog.git@main"
    _FAKE_REF_RESOLUTION = MagicMock(
        ref="refs/tags/1.0.0",
        sha="abc123",
    )

    def test_install_creates_kanon_data_dir(self, tmp_path: pathlib.Path) -> None:
        """install() creates .kanon-data/ via kanon_workspace_lock eager-create.

        A fresh workspace with no prior .kanon-data/ must end up with the
        directory after install() runs (even if the install fails later).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.core.install import _RefResolution

        fake_resolution = _RefResolution(sha="abc123", resolved_ref="refs/tags/1.0.0")

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        assert not (tmp_path / ".kanon-data").exists()

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

        assert (tmp_path / ".kanon-data").is_dir(), (
            "install() must create .kanon-data/ as a side effect of kanon_workspace_lock eager-create"
        )

    def test_install_lock_file_created_in_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """install() creates the workspace lock file inside .kanon-data/.

        After install() completes, the lock file must persist at
        .kanon-data/INSTALL_LOCK_FILENAME so subsequent invocations can
        lock on the same file.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.constants import INSTALL_LOCK_FILENAME
        from kanon_cli.core.install import _RefResolution

        fake_resolution = _RefResolution(sha="abc123", resolved_ref="refs/tags/1.0.0")

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock", catalog_source=self._CATALOG_SOURCE)

        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME
        assert lock_path.exists(), f"Workspace lock file must exist at {lock_path} after install() completes"


# ---------------------------------------------------------------------------
# Tests for add_help=True on the 'install' subparser
# ---------------------------------------------------------------------------


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
        # Should not raise even though .repo/manifests is absent.
        _reset_manifests_working_tree(source_dir)

    def test_restores_modified_tracked_file(self, tmp_path: pathlib.Path) -> None:
        """Modified tracked files are restored to their HEAD state.

        Simulates the envsubst step that rewrites manifest.xml: after reset,
        manifest.xml is back to its committed content.
        """
        manifests_dir = tmp_path / ".repo" / "manifests"
        self._init_git_repo(manifests_dir)

        # Simulate envsubst rewriting manifest.xml.
        (manifests_dir / "manifest.xml").write_text("<manifest><!-- envsubst was here --></manifest>\n")
        status_before = subprocess.run(
            ["git", "status", "--short"], cwd=manifests_dir, capture_output=True, text=True
        ).stdout.strip()
        assert "manifest.xml" in status_before, "manifest.xml should be dirty before reset"

        source_dir = tmp_path
        _reset_manifests_working_tree(source_dir)

        # manifest.xml should be restored to its committed content.
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

    def test_raises_oserror_when_git_checkout_fails(self, tmp_path: pathlib.Path) -> None:
        """OSError is raised when git checkout -- . fails.

        Uses a non-git directory to simulate the failure so the assertion is
        deterministic without requiring a mock.
        """
        # Create a .repo/manifests dir that is NOT a git repo so git checkout fails.
        manifests_dir = tmp_path / ".repo" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "manifest.xml").write_text("<manifest/>\n")
        # No git init -- git checkout will exit non-zero.

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
