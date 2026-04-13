"""Shared fixtures for kanon-cli tests."""

import pathlib

import pytest


@pytest.fixture()
def sample_kanonenv(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a sample two-source .kanon file."""
    kanonenv = tmp_path / ".kanon"
    kanonenv.write_text(
        "REPO_URL=https://example.com/org/repo-tool.git\n"
        "REPO_REV=v2.0.0\n"
        "GITBASE=https://example.com/org/\n"
        "CLAUDE_MARKETPLACES_DIR=.claude-marketplaces\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        "KANON_SOURCE_build_URL=https://example.com/org/build-repo.git\n"
        "KANON_SOURCE_build_REVISION=main\n"
        "KANON_SOURCE_build_PATH=repo-specs/common/meta.xml\n"
        "KANON_SOURCE_marketplaces_URL=https://example.com/org/mp-repo.git\n"
        "KANON_SOURCE_marketplaces_REVISION=main\n"
        "KANON_SOURCE_marketplaces_PATH=repo-specs/common/marketplaces.xml\n"
    )
    return kanonenv


@pytest.fixture()
def mock_git_ls_remote_output() -> str:
    """Sample git ls-remote --tags output."""
    return (
        "abc123\trefs/tags/1.0.0\n"
        "def456\trefs/tags/1.0.1\n"
        "ghi789\trefs/tags/1.1.0\n"
        "jkl012\trefs/tags/2.0.0\n"
        "mno345\trefs/tags/2.0.0^{}\n"
    )
