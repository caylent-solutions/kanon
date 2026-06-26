"""Unit tests for resolve_catalog_dir -- three-path parametrised coverage.

AC-TEST-001: Three cases:
  (a) resolve_catalog_dir(None) with no env var -> raises MissingCatalogSourceError
  (b) resolve_catalog_dir(None) with env var set -> returns path under tmp_path
  (c) resolve_catalog_dir("<url>@<ref>") -> returns path regardless of env var
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.catalog import MissingCatalogSourceError, resolve_catalog_dir


@pytest.mark.unit
class TestResolveCatalogDirParametrised:
    """Parametrised three-path coverage for resolve_catalog_dir."""

    def test_raises_missing_catalog_source_when_no_flag_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Case (a): no flag, no env var -- must raise MissingCatalogSourceError."""
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
        with pytest.raises(MissingCatalogSourceError):
            resolve_catalog_dir(None)

    def test_raises_missing_catalog_source_is_value_error_subclass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MissingCatalogSourceError must be a subclass of ValueError."""
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
        with pytest.raises(ValueError):
            resolve_catalog_dir(None)

    def test_env_var_set_returns_cloned_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        """Case (b): no flag but env var set -- resolves via env-var branch."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env-repo.git@env-branch")
        env_catalog = tmp_path / "repo" / "catalog"
        env_catalog.mkdir(parents=True)
        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = env_catalog
            result = resolve_catalog_dir(None)
        mock_clone.assert_called_once_with("https://env-repo.git@env-branch")
        assert result == env_catalog

    def test_flag_source_returns_cloned_path_regardless_of_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Case (c): flag set -- resolves via flag branch; env var is ignored."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env-repo.git@env-branch")
        flag_catalog = tmp_path / "repo" / "catalog"
        flag_catalog.mkdir(parents=True)
        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = flag_catalog
            result = resolve_catalog_dir("https://flag-repo.git@main")
        mock_clone.assert_called_once_with("https://flag-repo.git@main")
        assert result == flag_catalog

    def test_flag_wins_over_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        """Flag value is passed to _clone_remote_catalog; env var value is not used."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env-repo.git@env-branch")
        flag_catalog = tmp_path / "repo" / "catalog"
        flag_catalog.mkdir(parents=True)
        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = flag_catalog
            resolve_catalog_dir("https://flag-repo.git@main")

        call_arg = mock_clone.call_args[0][0]
        assert call_arg == "https://flag-repo.git@main"
        assert call_arg != "https://env-repo.git@env-branch"
