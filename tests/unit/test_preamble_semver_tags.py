"""Regression guards for KS (Category 16), MK (Category 17), and PK (Category 18)
fixture preamble semver git tag commands in docs/integration-testing.md.

AC-DOC-001: The preamble for Category 16 (KS), Category 17 (MK), and
non-marketplace PK tests must include `git tag` commands that create at
least the version tags required by the affected test constraints.

The full set required to satisfy the constraint matrix across KS-01..24,
MK-04, MK-05, MK-08, MK-10, MK-11, MK-18, PK-03, PK-04, PK-07 is:
  1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0

These tests are marked @pytest.mark.unit and are collected by `make test-unit`.
"""

import pathlib

import pytest

INTEGRATION_TESTING_DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "integration-testing.md"

# Semver tags required by KS-01..24, MK-04/05/08/10/11/18, PK-03/04/07.
REQUIRED_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")

# Section headings that delimit each fixture block.
KS_FIXTURE_HEADING = "### Fixture"
KS_CATEGORY_HEADING = "## 17. Category 16:"

MK_MANIFEST_HELPER_HEADING = "### Manifest helper"
MK_CATEGORY_HEADING = "## 18. Category 17:"

PK_FIXTURE_HEADING = "### Fixture setup"
PK_CATEGORY_HEADING = "## 19. Category 18:"


def _extract_category_fixture_block(content: str, category_heading: str, fixture_heading: str) -> str:
    """Return the fixture block inside a category section."""
    cat_idx = content.find(category_heading)
    assert cat_idx != -1, f"Category heading '{category_heading}' not found in {INTEGRATION_TESTING_DOC}."
    # Narrow to the category section first.
    category_text = content[cat_idx:]
    # Find the next top-level heading (##) to bound the category.
    next_cat_idx = category_text.find("\n## ", 1)
    if next_cat_idx != -1:
        category_text = category_text[:next_cat_idx]
    # Now find the fixture heading inside the category.
    fix_idx = category_text.find(fixture_heading)
    assert fix_idx != -1, (
        f"Fixture heading '{fixture_heading}' not found inside '{category_heading}' in {INTEGRATION_TESTING_DOC}."
    )
    section = category_text[fix_idx:]
    # Delimit to next ### heading.
    next_section_idx = section.find("\n### ", 1)
    if next_section_idx != -1:
        section = section[:next_section_idx]
    return section


@pytest.mark.unit
class TestKsFixtureSemverTags:
    """AC-DOC-001 / AC-FUNC-001 (KS): Category 16 KS fixture must tag all required versions."""

    def test_doc_exists(self) -> None:
        assert INTEGRATION_TESTING_DOC.exists(), f"Expected {INTEGRATION_TESTING_DOC} to exist"

    @pytest.mark.parametrize("tag", REQUIRED_TAGS)
    def test_ks_fixture_contains_git_tag(self, tag: str) -> None:
        """The KS fixture bash block must contain 'git tag <version>' for every
        version required by the KS-01..24 constraint matrix.

        Without these tags, KS scenarios that resolve PEP 440 constraints against
        the ks-manifest repo (e.g. KS-06 ~=1.0.0, KS-08 ~=2.0, KS-10 <2.0.0)
        will fail because the required tag does not exist on the fixture repo.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        section = _extract_category_fixture_block(content, KS_CATEGORY_HEADING, KS_FIXTURE_HEADING)
        git_tag_line = f"git tag {tag}"
        assert git_tag_line in section, (
            f"'git tag {tag}' is missing from the '{KS_FIXTURE_HEADING}' block "
            f"inside '{KS_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            f"This tag is required to satisfy KS scenario constraints that resolve "
            f"to version {tag}. Add 'git tag {tag}' after the fixture commit."
        )


@pytest.mark.unit
class TestMkManifestHelperSemverTags:
    """AC-DOC-001 / AC-FUNC-002 (MK): Category 17 Manifest helper must tag all required versions."""

    def test_doc_exists(self) -> None:
        assert INTEGRATION_TESTING_DOC.exists(), f"Expected {INTEGRATION_TESTING_DOC} to exist"

    @pytest.mark.parametrize("tag", REQUIRED_TAGS)
    def test_mk_manifest_helper_contains_git_tag(self, tag: str) -> None:
        """The MK Manifest helper bash block must contain 'git tag <version>' for
        every version required by the MK-04, MK-05, MK-08, MK-10, MK-11, MK-18
        constraint matrix.

        The MK_MFST repo is used as the kanon source whose REVISION is constrained
        by those scenarios. Without the required tags, the PEP 440 constraints
        cannot resolve to the expected versions.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        section = _extract_category_fixture_block(content, MK_CATEGORY_HEADING, MK_MANIFEST_HELPER_HEADING)
        git_tag_line = f"git tag {tag}"
        assert git_tag_line in section, (
            f"'git tag {tag}' is missing from the '{MK_MANIFEST_HELPER_HEADING}' "
            f"block inside '{MK_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            f"This tag is required so that MK scenarios using PEP 440 REVISION "
            f"constraints on MK_MFST can resolve to version {tag}. "
            f"Add 'git tag {tag}' after 'git commit -q -m \"init mk manifests\"'."
        )


@pytest.mark.unit
class TestPkManifestFixtureSemverTags:
    """AC-DOC-001 / AC-FUNC-003 (PK): Category 18 fixture must tag all required versions."""

    def test_doc_exists(self) -> None:
        assert INTEGRATION_TESTING_DOC.exists(), f"Expected {INTEGRATION_TESTING_DOC} to exist"

    @pytest.mark.parametrize("tag", REQUIRED_TAGS)
    def test_pk_manifest_fixture_contains_git_tag(self, tag: str) -> None:
        """The PK Manifest fixture bash block must contain 'git tag <version>' for
        every version required by the PK-03, PK-04, PK-07 constraint matrix.

        The PK_MFST repo is used as the kanon source whose REVISION is constrained
        by those scenarios. Without the required tags, PEP 440 constraints such as
        refs/tags/~=1.0.0 and refs/tags/>=1.0.0,<2.0.0 cannot resolve correctly.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        section = _extract_category_fixture_block(content, PK_CATEGORY_HEADING, PK_FIXTURE_HEADING)
        git_tag_line = f"git tag {tag}"
        assert git_tag_line in section, (
            f"'git tag {tag}' is missing from the '{PK_FIXTURE_HEADING}' block "
            f"inside '{PK_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            f"This tag is required to satisfy PK scenario constraints that resolve "
            f"to version {tag}. Add 'git tag {tag}' after the fixture commit."
        )
