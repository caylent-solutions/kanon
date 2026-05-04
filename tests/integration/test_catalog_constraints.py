"""Integration tests for catalog-level version constraints and filtering (10 tests).

Exercises _parse_catalog_source(), _clone_remote_catalog(), and
resolve_catalog_dir() covering format validation, constraint resolution,
and the bundled-catalog fallback path.
"""

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.catalog import (
    _clone_remote_catalog,
    _get_bundled_catalog_dir,
    _parse_catalog_source,
    resolve_catalog_dir,
)


# ---------------------------------------------------------------------------
# AC-FUNC-008: Catalog constraints integration tests (10 tests)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestParseCatalogSource:
    """Verify catalog source string parsing into URL and ref."""

    def test_parses_https_url_with_tag(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@v1.0.0")
        assert url == "https://github.com/org/repo.git"
        assert ref == "v1.0.0"

    def test_parses_ssh_url(self) -> None:
        url, ref = _parse_catalog_source("git@github.com:org/repo.git@main")
        assert url == "git@github.com:org/repo.git"
        assert ref == "main"

    def test_parses_latest_ref(self) -> None:
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


@pytest.mark.integration
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


@pytest.mark.integration
class TestCloneRemoteCatalogConstraints:
    """Verify constraint resolution is applied before git clone."""

    def test_latest_resolves_via_version_module(self, tmp_path: pathlib.Path) -> None:
        catalog_dir = tmp_path / "repo" / "catalog"
        catalog_dir.mkdir(parents=True)
        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="v2.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@latest")
        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "*")

    def test_clone_failure_exits(self) -> None:
        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="clone failed")
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")

    def test_missing_catalog_dir_exits(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "repo").mkdir()
        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            mock_run.return_value.returncode = 0
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")
