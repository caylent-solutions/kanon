"""Catalog source parsing retains literal branch, tag, and constraint refs."""

import pytest

from kanon_cli.core.catalog import (
    _parse_catalog_source,
)


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
