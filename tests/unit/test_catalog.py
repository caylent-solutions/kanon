"""Tests for the catalog resolution module."""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.catalog import (
    _clone_remote_catalog,
    _get_bundled_catalog_dir,
    _parse_catalog_source,
    resolve_catalog_dir,
)


@pytest.mark.unit
class TestGetBundledCatalogDir:
    """Verify bundled catalog directory resolution."""

    def test_bundled_catalog_exists(self) -> None:
        catalog = _get_bundled_catalog_dir()
        assert catalog.is_dir()

    def test_bundled_catalog_contains_kanon(self) -> None:
        catalog = _get_bundled_catalog_dir()
        assert (catalog / "kanon").is_dir()


@pytest.mark.unit
class TestParseCatalogSource:
    """Verify catalog source string parsing."""

    def test_parses_https_url_with_tag(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@v1.0.0")
        assert url == "https://github.com/org/repo.git"
        assert ref == "v1.0.0"

    def test_parses_ssh_url_with_branch(self) -> None:
        url, ref = _parse_catalog_source("git@github.com:org/repo.git@main")
        assert url == "git@github.com:org/repo.git"
        assert ref == "main"

    def test_parses_latest(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@latest")
        assert url == "https://github.com/org/repo.git"
        assert ref == "latest"

    def test_missing_at_sign_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("https://github.com/org/repo.git")

    def test_empty_ref_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty ref"):
            _parse_catalog_source("https://github.com/org/repo.git@")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty URL"):
            _parse_catalog_source("@main")


@pytest.mark.unit
class TestResolveCatalogDir:
    """Verify catalog directory resolution priority."""

    def test_returns_bundled_when_no_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        result = resolve_catalog_dir(None)
        assert result == _get_bundled_catalog_dir()

    def test_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://env-repo.git@env-branch")
        flag_catalog = tmp_path / "repo" / "catalog"
        flag_catalog.mkdir(parents=True)

        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = flag_catalog
            result = resolve_catalog_dir("https://flag-repo.git@flag-branch")

        mock_clone.assert_called_once_with("https://flag-repo.git@flag-branch")
        assert result == flag_catalog

    def test_env_var_used_when_no_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://env-repo.git@env-branch")
        env_catalog = tmp_path / "repo" / "catalog"
        env_catalog.mkdir(parents=True)

        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = env_catalog
            result = resolve_catalog_dir(None)

        mock_clone.assert_called_once_with("https://env-repo.git@env-branch")
        assert result == env_catalog


@pytest.mark.unit
class TestCloneRemoteCatalog:
    """Verify remote catalog cloning."""

    def test_clones_repo_and_returns_catalog_path(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            mock_run.return_value.returncode = 0
            result = _clone_remote_catalog("https://github.com/org/repo.git@main")

        assert result == catalog_dir
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert "--branch" in cmd
        assert "main" in cmd

    def test_latest_resolves_via_version_module(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="v2.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@latest")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "*")
        cmd = mock_run.call_args[0][0]
        assert "v2.0.0" in cmd

    def test_clone_failure_exits(self) -> None:
        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "clone failed"
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")

    def test_missing_catalog_dir_in_clone_exits(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True)
        # No catalog/ directory inside repo

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            mock_run.return_value.returncode = 0
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")
