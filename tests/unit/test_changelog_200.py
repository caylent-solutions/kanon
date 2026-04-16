"""Tests that verify CHANGELOG.md contains a comprehensive 2.0.0 version entry
documenting the embedded repo architecture migration.

AC-DOC-001: CHANGELOG.md has a 2.0.0 version entry
AC-DOC-002: CHANGELOG documents repo tool embedded as Python package
AC-DOC-003: CHANGELOG documents pipx no longer required
AC-DOC-004: CHANGELOG documents `kanon repo <subcommand>` availability
AC-DOC-005: CHANGELOG documents REPO_URL/REPO_REV deprecation
AC-DOC-006: CHANGELOG documents all 20 bug fixes
AC-DOC-007: CHANGELOG documents any breaking changes
AC-DOC-008: CHANGELOG follows the existing format and conventions in the file
AC-LINT-001: No broken markdown links in CHANGELOG.md
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _read_changelog() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def _extract_v200_section(content: str) -> str:
    """Extract the v2.0.0 section from the CHANGELOG content."""
    match = re.search(r"##\s+v2\.0\.0.*?(?=\n##\s+v|\Z)", content, re.DOTALL)
    assert match is not None, "CHANGELOG.md must contain a v2.0.0 section"
    return match.group(0)


@pytest.mark.unit
class TestChangelog200Exists:
    """AC-DOC-001: CHANGELOG.md has a 2.0.0 version entry."""

    def test_changelog_exists(self) -> None:
        assert CHANGELOG.exists(), f"Expected {CHANGELOG} to exist"

    def test_has_v200_entry(self) -> None:
        content = _read_changelog()
        assert re.search(r"##\s+v2\.0\.0", content), (
            "CHANGELOG.md must contain a v2.0.0 version entry header (e.g., '## v2.0.0')"
        )

    def test_v200_appears_before_v120(self) -> None:
        content = _read_changelog()
        v200_match = re.search(r"##\s+v2\.0\.0", content)
        v120_match = re.search(r"##\s+v1\.2\.0", content)
        assert v200_match is not None, "CHANGELOG.md must contain a v2.0.0 entry"
        assert v120_match is not None, "CHANGELOG.md must contain a v1.2.0 entry"
        assert v200_match.start() < v120_match.start(), "v2.0.0 entry must appear before v1.2.0 (newest versions first)"


@pytest.mark.unit
class TestChangelog200EmbeddedRepo:
    """AC-DOC-002: CHANGELOG documents repo tool embedded as Python package."""

    def test_mentions_embedded_repo(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "embedded" in lower or "kanon_cli.repo" in content, (
            "v2.0.0 entry must document that repo is embedded as a Python package inside kanon"
        )

    def test_mentions_python_package(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "python package" in lower or "kanon_cli.repo" in content or "python api" in lower, (
            "v2.0.0 entry must describe repo as an embedded Python package"
        )

    def test_no_external_rpm_git_repo_install(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "install rpm-git-repo" not in lower, (
            "v2.0.0 entry must not describe installing rpm-git-repo as an external tool"
        )


@pytest.mark.unit
class TestChangelog200PipxNotRequired:
    """AC-DOC-003: CHANGELOG documents pipx no longer required."""

    def test_mentions_pipx_no_longer_required(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "pipx" in lower, (
            "v2.0.0 entry must mention pipx (to document it is no longer required as a prerequisite)"
        )
        # pipx must appear in context of removal or no longer being required
        assert (
            "no longer" in lower
            or "removed" in lower
            or "not required" in lower
            or "prerequisite" in lower
            or "eliminated" in lower
        ), "v2.0.0 entry must document that pipx is no longer required as a prerequisite"


@pytest.mark.unit
class TestChangelog200KanonRepoSubcommand:
    """AC-DOC-004: CHANGELOG documents `kanon repo <subcommand>` availability."""

    def test_mentions_kanon_repo_subcommand(self) -> None:
        content = _extract_v200_section(_read_changelog())
        assert "kanon repo" in content, "v2.0.0 entry must document the `kanon repo` CLI subcommand"

    def test_kanon_repo_described_as_new_feature(self) -> None:
        content = _extract_v200_section(_read_changelog())
        # The kanon repo subcommand should be in a Feature or New section
        assert "kanon repo" in content, "v2.0.0 entry must reference `kanon repo` subcommand"
        # Verify it's in a feature/new context (not just a deprecation or bugfix)
        feature_section = re.search(r"###\s+(Feature|New|Added).*?(?=###|\Z)", content, re.DOTALL | re.IGNORECASE)
        assert feature_section is not None, "v2.0.0 entry must have a Feature/New/Added section documenting kanon repo"
        assert "kanon repo" in feature_section.group(0), (
            "kanon repo must appear in the Feature/New/Added section of the v2.0.0 entry"
        )


@pytest.mark.unit
class TestChangelog200RepoUrlRevDeprecation:
    """AC-DOC-005: CHANGELOG documents REPO_URL/REPO_REV deprecation."""

    def test_mentions_repo_url_deprecated(self) -> None:
        content = _extract_v200_section(_read_changelog())
        assert "REPO_URL" in content, "v2.0.0 entry must document REPO_URL deprecation"

    def test_mentions_repo_rev_deprecated(self) -> None:
        content = _extract_v200_section(_read_changelog())
        assert "REPO_REV" in content, "v2.0.0 entry must document REPO_REV deprecation"

    def test_repo_url_rev_described_as_deprecated(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "deprecated" in lower or "deprecat" in lower, (
            "v2.0.0 entry must describe REPO_URL/REPO_REV as deprecated"
        )

    def test_deprecation_section_exists(self) -> None:
        content = _extract_v200_section(_read_changelog())
        deprecation_section = re.search(
            r"###\s+(Deprecat|Breaking|Removed).*?(?=###|\Z)", content, re.DOTALL | re.IGNORECASE
        )
        assert deprecation_section is not None, "v2.0.0 entry must have a Deprecation or Breaking Changes section"


@pytest.mark.unit
class TestChangelog200BugFixes:
    """AC-DOC-006: CHANGELOG documents all 20 bug fixes."""

    BUG_KEYWORDS = [
        # Bug 1: Malformed XML in envsubst
        "envsubst",
        # Bug 2: LinkFile errors silently swallowed
        "linkfile",
        # Bug 3: os.execv RepoChangedException
        "execv",
        # Bug 4: Symlink overwrite silently removes user symlinks
        "symlink",
        # Bug 5: Empty file list in envsubst
        "empty",
        # Bug 6: Undefined environment variables silently preserved
        "undefined",
        # Bug 7: git ls-remote failures not retried
        "retry",
        # Bug 8: git ls-remote error messages don't include stderr
        "stderr",
        # Bug 9: Version constraint resolution called redundantly
        "constraint",
        # Bug 10: selfupdate subcommand incompatible
        "selfupdate",
        # Bug 11: Race condition tag deleted between ls-remote and fetch
        "race",
        # Bug 12: envsubst backup overwrites previous backup
        "backup",
        # Bug 13: Init reinitializes with different URL without warning
        "reinitializ",
        # Bug 14: Interactive prompts silently skipped
        "prompt",
        # Bug 15: Pre-release versions silently excluded
        "pre-release",
        # Bug 16: No nested variable reference support
        "nested",
        # Bug 17: Path operations assume Unix separators
        "pathlib",
        # Bug 18: envsubst XML save uses inefficient double-parse
        "double-parse",
        # Bug 19: Glob patterns with non-existent source
        "glob",
        # Bug 20: Glob linkfile skipped silently if dest is a file
        "destination",
    ]

    def test_fix_section_exists(self) -> None:
        content = _extract_v200_section(_read_changelog())
        fix_section = re.search(r"###\s+Fix.*?(?=###|\Z)", content, re.DOTALL | re.IGNORECASE)
        assert fix_section is not None, "v2.0.0 entry must have a Fix section documenting bug fixes"

    def test_documents_twenty_bug_fixes(self) -> None:
        content = _extract_v200_section(_read_changelog())
        fix_section = re.search(r"###\s+Fix.*?(?=###|\Z)", content, re.DOTALL | re.IGNORECASE)
        assert fix_section is not None, "v2.0.0 entry must have a Fix section"
        fix_text = fix_section.group(0)
        # Count bullet items (lines starting with *)
        bullets = [line.strip() for line in fix_text.splitlines() if line.strip().startswith("*")]
        assert len(bullets) >= 20, f"v2.0.0 Fix section must document at least 20 bug fixes, found {len(bullets)}"

    @pytest.mark.parametrize("keyword", BUG_KEYWORDS)
    def test_bug_keyword_present(self, keyword: str) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert keyword.lower() in lower, f"v2.0.0 entry must document the bug fix related to '{keyword}'"


@pytest.mark.unit
class TestChangelog200BreakingChanges:
    """AC-DOC-007: CHANGELOG documents any breaking changes."""

    def test_breaking_section_exists(self) -> None:
        content = _extract_v200_section(_read_changelog())
        breaking_section = re.search(
            r"###\s+(Breaking|Breaking Changes|Changed).*?(?=###|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert breaking_section is not None, (
            "v2.0.0 entry must have a Breaking Changes section (major version bump requires documenting breaking changes)"
        )

    def test_version_bump_rationale_documented(self) -> None:
        content = _extract_v200_section(_read_changelog())
        lower = content.lower()
        assert "2.0.0" in content or "major" in lower, "v2.0.0 section must indicate this is a major version release"


@pytest.mark.unit
class TestChangelog200Format:
    """AC-DOC-008: CHANGELOG follows the existing format and conventions."""

    def test_has_date_in_v200_header(self) -> None:
        content = _read_changelog()
        # Existing entries use format: ## v1.2.0 (2026-04-14)
        v200_header = re.search(r"##\s+v2\.0\.0\s+\(\d{4}-\d{2}-\d{2}\)", content)
        assert v200_header is not None, (
            "v2.0.0 header must include a date in parentheses, e.g. '## v2.0.0 (2026-04-16)'"
        )

    def test_subsections_use_heading_level_three(self) -> None:
        content = _extract_v200_section(_read_changelog())
        # All subsections should be ###
        subsections = re.findall(r"^#{1,6}\s+\w+", content, re.MULTILINE)
        for subsection in subsections[1:]:  # Skip the ## v2.0.0 header
            assert subsection.startswith("###"), f"Subsections in v2.0.0 must use ### (3 hashes), found: '{subsection}'"

    def test_v200_is_first_version_entry(self) -> None:
        content = _read_changelog()
        version_entries = re.findall(r"##\s+v\d+\.\d+\.\d+", content)
        assert len(version_entries) > 0, "CHANGELOG.md must have at least one version entry"
        assert version_entries[0] == "## v2.0.0", (
            f"v2.0.0 must be the first (newest) version entry, found: '{version_entries[0]}'"
        )


@pytest.mark.unit
class TestChangelogNobrokenLinks:
    """AC-LINT-001: No broken markdown links in CHANGELOG.md."""

    def test_no_relative_doc_links(self) -> None:
        content = _read_changelog()
        # CHANGELOG.md should not have relative links to docs/ that might break
        relative_links = re.findall(r"\[.*?\]\((?!https?://|#)(.*?)\)", content)
        assert len(relative_links) == 0, (
            f"CHANGELOG.md must not contain relative links that may break: {relative_links}"
        )

    def test_github_commit_links_are_absolute(self) -> None:
        content = _read_changelog()
        # All links should be absolute GitHub URLs or anchor links
        links = re.findall(r"\]\((.*?)\)", content)
        for link in links:
            assert link.startswith("https://") or link.startswith("#"), (
                f"CHANGELOG.md link must be absolute or anchor, found: '{link}'"
            )
