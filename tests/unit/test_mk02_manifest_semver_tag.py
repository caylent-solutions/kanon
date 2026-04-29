"""Regression guard for the MK-02 Manifest helper bash block.

AC-DOC-001: The Manifest helper bash block in docs/integration-testing.md must
contain the literal string 'git tag 1.0.0' so that the commit-time tag which
makes KANON_SOURCE_mp_REVISION=refs/tags/1.0.0 resolvable for MK-02 is always
present in the documentation.

AC-FUNC-001: This test is marked @pytest.mark.unit, is collected by the standard
`uv run pytest tests/unit` invocation, and fails (non-zero exit) when
'git tag 1.0.0' is absent from the Manifest helper section.
"""

import pathlib

import pytest

INTEGRATION_TESTING_DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "integration-testing.md"

MANIFEST_HELPER_HEADING = "### Manifest helper"
GIT_TAG_LINE = "git tag 1.0.0"


@pytest.mark.unit
class TestMkManifestSemverTag:
    """AC-DOC-001 / AC-FUNC-001: Manifest helper block must contain 'git tag 1.0.0'."""

    def test_doc_exists(self) -> None:
        assert INTEGRATION_TESTING_DOC.exists(), f"Expected {INTEGRATION_TESTING_DOC} to exist"

    def test_mk_manifest_helper_contains_semver_tag(self) -> None:
        """Reads docs/integration-testing.md, locates the Manifest helper code
        fence, and asserts 'git tag 1.0.0' is present within that section.

        Failing this test means the commit-time tag required by MK-02
        (KANON_SOURCE_mp_REVISION=refs/tags/1.0.0) has been removed from the
        Manifest helper bash block in docs/integration-testing.md.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")

        heading_index = content.find(MANIFEST_HELPER_HEADING)
        assert heading_index != -1, (
            f"Section '{MANIFEST_HELPER_HEADING}' not found in {INTEGRATION_TESTING_DOC}. "
            "The MK-02 Manifest helper section must be present."
        )

        # Extract text from the Manifest helper heading to the next top-level
        # or same-level heading, so the assertion is scoped to the right section.
        section_text = content[heading_index:]
        # Find the next heading at the same level (###) or higher to delimit scope.
        next_heading_index = section_text.find("\n### ", 1)
        if next_heading_index != -1:
            section_text = section_text[:next_heading_index]

        assert GIT_TAG_LINE in section_text, (
            f"'git tag 1.0.0' is missing from the '{MANIFEST_HELPER_HEADING}' section "
            f"in {INTEGRATION_TESTING_DOC}. "
            "This line creates the commit-time tag required for MK-02 scenario "
            "(KANON_SOURCE_mp_REVISION=refs/tags/1.0.0) to resolve correctly. "
            "Restore 'git tag 1.0.0' to the Manifest helper bash block to fix this failure."
        )
