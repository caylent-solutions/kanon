"""Integration tests that scan kanon source files for hard-coded org-specific values.

These tests enforce that no Caylent-specific identifiers are embedded in the
kanon source tree under src/kanon_cli/.  Each test scans specific files or
directories and asserts the absence of the targeted pattern.

Covered acceptance criteria:
  - AC-FUNC-001: ALLOWED_BRANCHES does not contain 'review/caylent-claude'
  - AC-FUNC-003: catalog .kanon has no REPO_URL or REPO_REV lines
  - AC-FUNC-004: kanon-readme.md has no reference to rpm-git-repo as external tool
  - AC-TEST-001: Automated scan of src/ for hard-coded org-specific values passes
"""

from pathlib import Path

import pytest

# Root of the kanon source package relative to this test file's location.
_SRC_ROOT = Path(__file__).parent.parent.parent / "src" / "kanon_cli"


def _collect_matching_lines(directory: Path, pattern: str, glob: str = "**/*") -> list[str]:
    """Return lines matching *pattern* in text files found under *directory*.

    Only regular files that can be decoded as UTF-8 are examined.  Binary files
    are silently skipped.  Each returned string has the form
    ``<relative_path>:<line_no>: <content>``.
    """
    hits: list[str] = []
    for file_path in sorted(directory.glob(glob)):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                rel = file_path.relative_to(directory)
                hits.append(f"{rel}:{line_no}: {line.strip()}")
    return hits


@pytest.mark.integration
class TestAllowedBranchesNoOrgValue:
    """AC-FUNC-001: ALLOWED_BRANCHES must not contain org-specific branch names."""

    def test_constants_does_not_contain_caylent_claude_branch(self) -> None:
        """'review/caylent-claude' must not appear in constants.py."""
        constants_file = _SRC_ROOT / "constants.py"
        assert constants_file.is_file(), f"constants.py not found at {constants_file}"

        text = constants_file.read_text(encoding="utf-8")
        assert "review/caylent-claude" not in text, (
            f"Found org-specific branch 'review/caylent-claude' in {constants_file}. "
            "Remove it from ALLOWED_BRANCHES -- only universally valid branches belong there."
        )


@pytest.mark.integration
class TestCatalogKanonFileNoRepoUrl:
    """AC-FUNC-003: catalog .kanon must have no REPO_URL or REPO_REV lines."""

    _KANONENV = _SRC_ROOT / "catalog" / "kanon" / ".kanon"

    @pytest.mark.parametrize("keyword", ["REPO_URL", "REPO_REV"])
    def test_kanonenv_has_no_repo_override_lines(self, keyword: str) -> None:
        """Neither active nor commented REPO_URL / REPO_REV lines should be present."""
        assert self._KANONENV.is_file(), f".kanon not found at {self._KANONENV}"

        lines = self._KANONENV.read_text(encoding="utf-8").splitlines()
        matching = [f"line {i + 1}: {line.strip()}" for i, line in enumerate(lines) if keyword in line]
        assert not matching, (
            f"Found {keyword} references in {self._KANONENV} (even commented lines are prohibited):\n"
            + "\n".join(matching)
        )


@pytest.mark.integration
class TestKanonReadmeNoExternalRepoTool:
    """AC-FUNC-004: kanon-readme.md must not reference rpm-git-repo as an external tool."""

    _README = _SRC_ROOT / "catalog" / "kanon" / "kanon-readme.md"

    def test_readme_has_no_rpm_git_repo_link(self) -> None:
        """rpm-git-repo GitHub URL must not appear in kanon-readme.md."""
        assert self._README.is_file(), f"kanon-readme.md not found at {self._README}"

        text = self._README.read_text(encoding="utf-8")
        assert "caylent-solutions/rpm-git-repo" not in text, (
            f"Found reference to 'caylent-solutions/rpm-git-repo' in {self._README}. "
            "The repo tool is now embedded -- replace the external link with generic text."
        )


@pytest.mark.integration
class TestSrcNoHardcodedOrgValues:
    """AC-TEST-001: src/kanon_cli/ must contain no hard-coded org-specific identifiers.

    The scan excludes the embedded 'repo' subdirectory, which is a vendored
    third-party tool and is maintained separately.
    """

    # Patterns that must not appear in first-party kanon source files.
    _PROHIBITED_PATTERNS = [
        "review/caylent-claude",
        "caylent-private",
    ]

    # Subdirectories of src/kanon_cli/ that are first-party kanon code.
    # The embedded 'repo' directory is vendored and excluded from this scan.
    _FIRST_PARTY_DIRS = [
        _SRC_ROOT / "catalog",
        _SRC_ROOT / "core",
    ]
    # First-party individual files (top-level in src/kanon_cli/).
    _FIRST_PARTY_FILES = list((_SRC_ROOT).glob("*.py"))

    @pytest.mark.parametrize("pattern", _PROHIBITED_PATTERNS)
    def test_no_org_pattern_in_first_party_source(self, pattern: str) -> None:
        """Pattern must not appear in any first-party kanon source file."""
        hits: list[str] = []

        for directory in self._FIRST_PARTY_DIRS:
            if directory.is_dir():
                hits.extend(_collect_matching_lines(directory, pattern))

        for file_path in self._FIRST_PARTY_FILES:
            if file_path.is_file():
                try:
                    text = file_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError):
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if pattern in line:
                        rel = file_path.relative_to(_SRC_ROOT)
                        hits.append(f"{rel}:{line_no}: {line.strip()}")

        assert not hits, (
            f"Hard-coded org-specific value {pattern!r} found in first-party source files:\n"
            + "\n".join(hits)
            + "\nRemove or make these values configurable."
        )
