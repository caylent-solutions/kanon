"""Tests that verify docs/configuration.md and docs/version-resolution.md
reflect the deprecated REPO_URL/REPO_REV variables, embedded repo architecture,
and consolidated version constraint implementation.

AC-DOC-001: configuration.md marks REPO_URL as deprecated
AC-DOC-002: configuration.md marks REPO_REV as deprecated
AC-DOC-003: configuration.md has deprecation notice explaining embedded repo
AC-DOC-004: configuration.md has ``kanon repo`` section
AC-DOC-005: configuration.md has no standalone repo tool configuration guidance
AC-DOC-006: version-resolution.md notes consolidated version constraint in kanon_cli.version
AC-DOC-007: version-resolution.md has no references to separate repo version_constraints.py implementation
AC-DOC-008: version-resolution.md documents delegation from repo/version_constraints.py to kanon_cli.version
AC-LINT-001: No broken markdown links in modified files
"""

import pathlib
import re

import pytest

DOCS_DIR = pathlib.Path(__file__).parent.parent.parent / "docs"
CONFIGURATION = DOCS_DIR / "configuration.md"
VERSION_RESOLUTION = DOCS_DIR / "version-resolution.md"


@pytest.mark.unit
class TestConfigurationRepoUrlDeprecated:
    """AC-DOC-001: configuration.md marks REPO_URL as deprecated."""

    def test_doc_exists(self) -> None:
        assert CONFIGURATION.exists(), f"Expected {CONFIGURATION} to exist"

    def test_repo_url_marked_deprecated(self) -> None:
        content = CONFIGURATION.read_text()
        assert "REPO_URL" in content, "configuration.md must reference REPO_URL"
        assert "deprecated" in content.lower(), "configuration.md must contain a deprecation notice for REPO_URL"
        # Verify REPO_URL and deprecated appear in proximity (same section)
        repo_url_idx = content.find("REPO_URL")
        deprecated_idx = content.lower().find("deprecated")
        assert abs(repo_url_idx - deprecated_idx) < 500, (
            "REPO_URL and the deprecation notice must appear in the same section"
        )


@pytest.mark.unit
class TestConfigurationRepoRevDeprecated:
    """AC-DOC-002: configuration.md marks REPO_REV as deprecated."""

    def test_repo_rev_marked_deprecated(self) -> None:
        content = CONFIGURATION.read_text()
        assert "REPO_REV" in content, "configuration.md must reference REPO_REV"
        # Verify REPO_REV and deprecated appear in proximity (same section)
        repo_rev_idx = content.find("REPO_REV")
        deprecated_idx = content.lower().find("deprecated")
        assert abs(repo_rev_idx - deprecated_idx) < 500, (
            "REPO_REV and the deprecation notice must appear in the same section"
        )


@pytest.mark.unit
class TestConfigurationDeprecationNoticeEmbeddedRepo:
    """AC-DOC-003: configuration.md has deprecation notice explaining embedded repo."""

    def test_deprecation_notice_mentions_embedded(self) -> None:
        content = CONFIGURATION.read_text()
        assert "embedded" in content.lower(), (
            "configuration.md must explain that REPO_URL/REPO_REV are deprecated because the repo tool is now embedded"
        )

    def test_deprecation_notice_present(self) -> None:
        content = CONFIGURATION.read_text()
        assert "deprecated" in content.lower(), "configuration.md must contain a deprecation notice"


@pytest.mark.unit
class TestConfigurationKanonRepoSection:
    """AC-DOC-004: configuration.md has a ``kanon repo`` section."""

    def test_kanon_repo_section_present(self) -> None:
        content = CONFIGURATION.read_text()
        assert "kanon repo" in content, (
            "configuration.md must contain a 'kanon repo' section documenting the subcommand"
        )

    def test_kanon_repo_section_is_heading(self) -> None:
        content = CONFIGURATION.read_text()
        lines = content.splitlines()
        heading_lines = [line for line in lines if line.startswith("#") and "kanon repo" in line.lower()]
        assert heading_lines, "configuration.md must have a markdown heading for the 'kanon repo' section"

    def test_kanon_repo_section_documents_configuration(self) -> None:
        content = CONFIGURATION.read_text()
        # The section should describe configuration for kanon repo (e.g. env var or flag)
        assert "KANON_REPO_DIR" in content or "--repo-dir" in content, (
            "configuration.md 'kanon repo' section must document KANON_REPO_DIR or --repo-dir"
        )


@pytest.mark.unit
class TestConfigurationNoStandaloneRepoGuidance:
    """AC-DOC-005: configuration.md has no standalone repo tool configuration guidance."""

    def test_no_pipx_install_guidance(self) -> None:
        content = CONFIGURATION.read_text()
        assert "pipx install" not in content, (
            "configuration.md must not contain pipx install guidance for the standalone repo tool"
        )

    def test_no_standalone_repo_tool_install_guidance(self) -> None:
        content = CONFIGURATION.read_text()
        assert "install repo tool" not in content.lower(), (
            "configuration.md must not describe installing the repo tool as a standalone package"
        )


@pytest.mark.unit
class TestVersionResolutionConsolidatedImplementation:
    """AC-DOC-006: version-resolution.md notes consolidated version constraint in kanon_cli.version."""

    def test_doc_exists(self) -> None:
        assert VERSION_RESOLUTION.exists(), f"Expected {VERSION_RESOLUTION} to exist"

    def test_mentions_kanon_cli_version(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        assert "kanon_cli.version" in content, (
            "version-resolution.md must note that version constraint logic is consolidated in kanon_cli.version"
        )

    def test_mentions_consolidated_implementation(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        assert "consolidated" in content.lower() or "canonical" in content.lower(), (
            "version-resolution.md must indicate that the implementation is consolidated/canonical in kanon_cli.version"
        )


@pytest.mark.unit
class TestVersionResolutionNoSeparateImplementationReference:
    """AC-DOC-007: version-resolution.md has no references to separate repo version_constraints.py
    as an independent implementation.
    """

    def test_no_independent_implementation_claim(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        # Must not describe version_constraints.py as a separate/independent implementation
        assert "separate" not in content.lower() or "delegates" in content.lower(), (
            "version-resolution.md must not describe version_constraints.py as a "
            "separate independent implementation -- it must note that it delegates"
        )

    def test_no_dual_implementation_description(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        lower = content.lower()
        assert "dual" not in lower, "version-resolution.md must not describe a dual-implementation architecture"


@pytest.mark.unit
class TestVersionResolutionDelegationDocumented:
    """AC-DOC-008: version-resolution.md documents delegation from
    repo/version_constraints.py to kanon_cli.version.
    """

    def test_delegation_documented(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        assert "delegate" in content.lower() or "delegates" in content.lower(), (
            "version-resolution.md must document that repo/version_constraints.py delegates to kanon_cli.version"
        )

    def test_repo_version_constraints_referenced(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        assert "version_constraints" in content, (
            "version-resolution.md must reference version_constraints.py and its delegation to kanon_cli.version"
        )


@pytest.mark.unit
class TestNoRepoRevInVersionResolution:
    """AC-DOC related: REPO_REV section in version-resolution.md should reflect deprecation."""

    def test_repo_rev_section_reflects_current_state(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        # If REPO_REV is still mentioned, it must be in the context of deprecation
        # or historical note, not as an active configuration option
        if "REPO_REV" in content:
            lower = content.lower()
            assert "deprecated" in lower or "no longer" in lower or "delegate" in lower, (
                "If REPO_REV appears in version-resolution.md, it must be in the "
                "context of deprecation or delegation, not as an active option"
            )


@pytest.mark.unit
class TestMarkdownLinksValid:
    """AC-LINT-001: No broken markdown links in modified files."""

    def _extract_internal_links(self, content: str) -> list[str]:
        """Extract all internal markdown links (relative paths) from content."""
        # Match [text](link) patterns that are not external URLs
        pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        links = []
        for match in pattern.finditer(content):
            href = match.group(2)
            # Only internal links (not http/https/mailto/anchors)
            if not href.startswith(("http://", "https://", "mailto:", "#")):
                links.append(href)
        return links

    def test_configuration_no_broken_internal_links(self) -> None:
        content = CONFIGURATION.read_text()
        internal_links = self._extract_internal_links(content)
        for link in internal_links:
            # Strip anchor fragments
            path_part = link.split("#")[0]
            if path_part:
                resolved = (DOCS_DIR / path_part).resolve()
                assert resolved.exists(), f"Broken link in configuration.md: '{link}' resolves to non-existent path"

    def test_version_resolution_no_broken_internal_links(self) -> None:
        content = VERSION_RESOLUTION.read_text()
        internal_links = self._extract_internal_links(content)
        for link in internal_links:
            path_part = link.split("#")[0]
            if path_part:
                resolved = (DOCS_DIR / path_part).resolve()
                assert resolved.exists(), (
                    f"Broken link in version-resolution.md: '{link}' resolves to non-existent path"
                )
