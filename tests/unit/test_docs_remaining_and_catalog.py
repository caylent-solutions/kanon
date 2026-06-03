"""Tests that verify the remaining documentation files and the catalog template
reflect the embedded repo architecture.

AC-DOC-001: creating-manifest-repos.md has no standalone repo tool installation references
AC-DOC-002: creating-packages.md has no standalone repo tool references
AC-DOC-003: claude-marketplaces-guide.md repo tool references updated
AC-DOC-004: multi-source-guide.md repo tool references updated
AC-DOC-005: catalog/kanon/.kanon has no REPO_URL or REPO_REV references
AC-DOC-006: catalog/kanon/kanon-readme.md has no pipx/repo prerequisites
AC-DOC-007: catalog/kanon/kanon-readme.md install instructions updated
AC-LINT-001: No broken markdown links in modified files
"""

import pathlib
import re

import pytest

DOCS_DIR = pathlib.Path(__file__).parent.parent.parent / "docs"
CATALOG_KANON_DIR = pathlib.Path(__file__).parent.parent.parent / "src" / "kanon_cli" / "catalog" / "kanon"

CREATING_MANIFEST_REPOS = DOCS_DIR / "creating-manifest-repos.md"
CREATING_PACKAGES = DOCS_DIR / "creating-packages.md"
CLAUDE_MARKETPLACES_GUIDE = DOCS_DIR / "claude-marketplaces-guide.md"
MULTI_SOURCE_GUIDE = DOCS_DIR / "multi-source-guide.md"
KANON_DOT_KANON = CATALOG_KANON_DIR / ".kanon"
KANON_README = CATALOG_KANON_DIR / "kanon-readme.md"


@pytest.mark.unit
class TestCreatingManifestReposNoStandaloneRepo:
    """AC-DOC-001: creating-manifest-repos.md has no standalone repo tool installation references."""

    def test_doc_exists(self) -> None:
        assert CREATING_MANIFEST_REPOS.exists(), f"Expected {CREATING_MANIFEST_REPOS} to exist"

    def test_no_standalone_repo_tool_link(self) -> None:
        content = CREATING_MANIFEST_REPOS.read_text()
        assert "gerrit.googlesource.com/git-repo" not in content, (
            "creating-manifest-repos.md must not contain a link to the standalone repo tool at gerrit.googlesource.com"
        )

    def test_no_standalone_repo_tool_installation_reference(self) -> None:
        content = CREATING_MANIFEST_REPOS.read_text()
        lower = content.lower()
        assert "install the repo tool" not in lower and "install repo tool" not in lower, (
            "creating-manifest-repos.md must not describe installing the repo tool as a standalone package"
        )

    def test_no_pipx_install_reference(self) -> None:
        content = CREATING_MANIFEST_REPOS.read_text()
        assert "pipx install" not in content, "creating-manifest-repos.md must not reference pipx install"


@pytest.mark.unit
class TestCreatingPackagesNoStandaloneRepo:
    """AC-DOC-002: creating-packages.md has no standalone repo tool references."""

    def test_doc_exists(self) -> None:
        assert CREATING_PACKAGES.exists(), f"Expected {CREATING_PACKAGES} to exist"

    def test_no_gerrit_link(self) -> None:
        content = CREATING_PACKAGES.read_text()
        assert "gerrit.googlesource.com/git-repo" not in content, (
            "creating-packages.md must not contain a link to the standalone repo tool"
        )

    def test_no_standalone_install_reference(self) -> None:
        content = CREATING_PACKAGES.read_text()
        assert "pipx install" not in content, (
            "creating-packages.md must not reference pipx install for the standalone repo tool"
        )

    def test_no_repo_tool_install_reference(self) -> None:
        content = CREATING_PACKAGES.read_text()
        lower = content.lower()
        assert "install repo tool" not in lower, (
            "creating-packages.md must not describe installing the repo tool separately"
        )


@pytest.mark.unit
class TestClaudeMarketplacesGuideRepoToolUpdated:
    """AC-DOC-003: claude-marketplaces-guide.md repo tool references updated."""

    def test_doc_exists(self) -> None:
        assert CLAUDE_MARKETPLACES_GUIDE.exists(), f"Expected {CLAUDE_MARKETPLACES_GUIDE} to exist"

    def test_no_gerrit_standalone_link(self) -> None:
        content = CLAUDE_MARKETPLACES_GUIDE.read_text()
        assert "gerrit.googlesource.com/git-repo" not in content, (
            "claude-marketplaces-guide.md must not link to the standalone repo tool at gerrit.googlesource.com"
        )

    def test_no_standalone_repo_install_guidance(self) -> None:
        content = CLAUDE_MARKETPLACES_GUIDE.read_text()
        assert "pipx install" not in content, "claude-marketplaces-guide.md must not reference pipx install"


@pytest.mark.unit
class TestMultiSourceGuideRepoToolUpdated:
    """AC-DOC-004: multi-source-guide.md repo tool references updated."""

    def test_doc_exists(self) -> None:
        assert MULTI_SOURCE_GUIDE.exists(), f"Expected {MULTI_SOURCE_GUIDE} to exist"

    def test_no_gerrit_standalone_link(self) -> None:
        content = MULTI_SOURCE_GUIDE.read_text()
        assert "gerrit.googlesource.com/git-repo" not in content, (
            "multi-source-guide.md must not link to the standalone repo tool at gerrit.googlesource.com"
        )

    def test_no_standalone_repo_install_guidance(self) -> None:
        content = MULTI_SOURCE_GUIDE.read_text()
        assert "pipx install" not in content, (
            "multi-source-guide.md must not reference pipx install for the standalone repo tool"
        )


@pytest.mark.unit
class TestCatalogKanonFilesRemoved:
    """AC-DOC-005/006/007 (E6-F2-S1-T1): catalog/kanon/ was deleted.

    The catalog files (.kanon and kanon-readme.md) no longer exist.
    These tests assert the expected post-deletion state.
    """

    def test_kanon_dot_kanon_absent(self) -> None:
        assert not KANON_DOT_KANON.exists(), (
            f"catalog/kanon/.kanon at {KANON_DOT_KANON} must not exist after E6-F2-S1-T1 deletion. "
            "If this fails, the bundled catalog was accidentally re-added."
        )

    def test_kanon_readme_absent(self) -> None:
        assert not KANON_README.exists(), (
            f"catalog/kanon/kanon-readme.md at {KANON_README} must not exist after E6-F2-S1-T1 deletion. "
            "If this fails, the bundled catalog was accidentally re-added."
        )

    def test_catalog_dir_absent(self) -> None:
        assert not CATALOG_KANON_DIR.exists(), (
            f"catalog/kanon/ at {CATALOG_KANON_DIR} must not exist after E6-F2-S1-T1 deletion. "
            "If this fails, the bundled catalog was accidentally re-added."
        )


@pytest.mark.unit
class TestMarkdownLinksValid:
    """AC-LINT-001: No broken markdown links in modified files."""

    def _extract_internal_links(self, content: str) -> list[str]:
        """Extract all internal markdown links (relative paths) from content."""
        pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        links = []
        for match in pattern.finditer(content):
            href = match.group(2)
            if not href.startswith(("http://", "https://", "mailto:", "#")):
                links.append(href)
        return links

    @pytest.mark.parametrize(
        "doc_path,doc_name",
        [
            (CREATING_MANIFEST_REPOS, "creating-manifest-repos.md"),
            (CREATING_PACKAGES, "creating-packages.md"),
            (CLAUDE_MARKETPLACES_GUIDE, "claude-marketplaces-guide.md"),
            (MULTI_SOURCE_GUIDE, "multi-source-guide.md"),
        ],
    )
    def test_no_broken_internal_links_in_docs(self, doc_path: pathlib.Path, doc_name: str) -> None:
        content = doc_path.read_text()
        internal_links = self._extract_internal_links(content)
        for link in internal_links:
            path_part = link.split("#")[0]
            if path_part:
                resolved = (DOCS_DIR / path_part).resolve()
                assert resolved.exists(), f"Broken link in {doc_name}: '{link}' resolves to non-existent path"
