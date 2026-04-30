"""Regression guards for the RX (Category 15) fixture preamble in docs/integration-testing.md.

AC-DOC-001: The Category 15 (RX) fixture setup section must document creation of a
bare git repo at the path that the RX manifest XML's fetch+name combination resolves
to, i.e. fixtures/cs-catalog/catalog.

AC-FUNC-001: The cs-catalog source git repository must carry all 7 semver tags
(1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0) so that RX scenarios exercising
PEP 440 constraints can resolve to the expected versions.

The RX manifest XML uses fetch="file://.../fixtures/cs-catalog" and name="catalog".
The repo tool resolves each project URL as fetch + "/" + name, so the bare git repo
must live at fixtures/cs-catalog/catalog -- a sub-path of the Category 13 fixture.

These tests are marked @pytest.mark.unit and are collected by `make test-unit`.
"""

import os
import pathlib
import subprocess

import pytest

INTEGRATION_TESTING_DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "integration-testing.md"

# Category 15 section and fixture headings.
RX_CATEGORY_HEADING = "## 16. Category 15:"
FIXTURE_HEADING = "### Fixture setup"

# Required semver tags that the cs-catalog source must carry so that all
# RX-01..RX-26 PEP 440 constraint scenarios resolve to the expected version.
REQUIRED_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")

# Key strings expected in the fixture setup block after T4's fix.
_BARE_CLONE_CMD = "git clone --bare"
_CATALOG_SUB_PATH = "fixtures/cs-catalog/catalog"
_TAG_VERIFY_CMD = "git -C"
# Post-T4 explanation strings: present only after the bare sub-repo fix is applied.
_FETCH_PLUS_NAME_RESOLUTION = 'fetch + "/" + name'
_SEPARATE_BARE_REPO_PHRASE = "separate bare git repo"
_PARENT_DIR_PHRASE = "_parent_ directory, not the project repo"


def _extract_category_block(content: str) -> str:
    """Return the text of the Category 15 section.

    Raises AssertionError with a descriptive message if the heading is absent.
    """
    cat_idx = content.find(RX_CATEGORY_HEADING)
    assert cat_idx != -1, (
        f"Category heading '{RX_CATEGORY_HEADING}' not found in {INTEGRATION_TESTING_DOC}. "
        "The Category 15 section is missing from the doc."
    )
    category_text = content[cat_idx:]
    next_cat_idx = category_text.find("\n## ", 1)
    if next_cat_idx != -1:
        category_text = category_text[:next_cat_idx]
    return category_text


def _extract_fixture_block(content: str) -> str:
    """Return the text of the '### Fixture setup' block inside the Category 15 section.

    Raises AssertionError with a descriptive message if either heading is absent.
    """
    category_text = _extract_category_block(content)
    # Find the fixture setup block within the category section.
    fix_idx = category_text.find(FIXTURE_HEADING)
    assert fix_idx != -1, (
        f"Fixture heading '{FIXTURE_HEADING}' not found inside '{RX_CATEGORY_HEADING}' "
        f"in {INTEGRATION_TESTING_DOC}. The fixture setup subsection is missing."
    )
    section = category_text[fix_idx:]
    # Delimit to the next ### heading so we stay within the fixture block.
    next_section_idx = section.find("\n### ", 1)
    if next_section_idx != -1:
        section = section[:next_section_idx]
    return section


@pytest.mark.unit
class TestRxCatalogSubRepoCreated:
    """AC-DOC-001: The RX fixture setup section must document bare sub-repo creation."""

    def test_bare_clone_command_present(self) -> None:
        """The fixture setup block must contain a 'git clone --bare' command.

        The RX manifest XML resolves project URLs to fetch+"/"+name, so the
        bare repo at fixtures/cs-catalog/catalog must be created via
        'git clone --bare'.  Without this command the sub-repo does not exist
        and every RX scenario will fail when repo tries to clone it.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        block = _extract_fixture_block(content)
        assert _BARE_CLONE_CMD in block, (
            f"'{_BARE_CLONE_CMD}' is missing from the '{FIXTURE_HEADING}' block "
            f"inside '{RX_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            "Add a 'git clone --bare' step to create fixtures/cs-catalog/catalog."
        )

    def test_catalog_sub_path_referenced(self) -> None:
        """The fixture setup block must explicitly reference 'fixtures/cs-catalog/catalog'.

        This path is the resolved URL that the repo tool derives from the RX XML's
        fetch='file://.../cs-catalog' and name='catalog' attributes.  Without an
        explicit reference a future editor cannot see which sub-path must exist.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        block = _extract_fixture_block(content)
        assert _CATALOG_SUB_PATH in block, (
            f"'{_CATALOG_SUB_PATH}' is missing from the '{FIXTURE_HEADING}' block "
            f"inside '{RX_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            "The fixture setup must name the sub-path that the bare repo occupies."
        )

    def test_fetch_plus_name_resolution_documented(self) -> None:
        """The Category 15 section must explain that the repo tool resolves fetch+"/"+name.

        The explanation 'fetch + "/" + name' makes the sub-repo requirement
        self-explanatory: readers learn exactly why fixtures/cs-catalog/catalog
        must be a separate bare repo rather than a symlink or directory of the
        parent fixture.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        category_text = _extract_category_block(content)
        assert _FETCH_PLUS_NAME_RESOLUTION in category_text, (
            f"'{_FETCH_PLUS_NAME_RESOLUTION}' not found in the Category 15 section of "
            f"{INTEGRATION_TESTING_DOC}. The fetch+name resolution explanation is missing; "
            'add a sentence explaining that the repo tool resolves URLs as fetch + "/" + name.'
        )

    def test_separate_bare_repo_requirement_documented(self) -> None:
        """The Category 15 section must state that a separate bare git repo is required.

        The phrase 'separate bare git repo' clarifies the requirement for a distinct
        bare repo at the sub-path, distinguishing it from the parent category fixture.
        This is only present after T4's fix adds the fetch+name resolution explanation.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        category_text = _extract_category_block(content)
        assert _SEPARATE_BARE_REPO_PHRASE in category_text, (
            f"'{_SEPARATE_BARE_REPO_PHRASE}' not found in the Category 15 section of "
            f"{INTEGRATION_TESTING_DOC}. Document that a separate bare git repo must exist "
            "at fixtures/cs-catalog/catalog (distinct from the parent Category 13 fixture)."
        )

    def test_parent_dir_not_project_repo_noted(self) -> None:
        """The Category 15 section must note that fixtures/cs-catalog is the parent, not the project.

        Without this clarification, operators may mistake the Category 13 fixture
        directory for the project repo that the RX XML points at, leading to
        'repository not found' errors during repo sync.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        category_text = _extract_category_block(content)
        assert _PARENT_DIR_PHRASE in category_text, (
            f"'{_PARENT_DIR_PHRASE}' not found in the Category 15 section of "
            f"{INTEGRATION_TESTING_DOC}. Add a note clarifying that fixtures/cs-catalog "
            "is the parent directory, not the project repo that the RX XML resolves to."
        )

    def test_tag_verification_command_present(self) -> None:
        """The fixture setup block must contain a tag-verification command.

        A 'git -C ... tag' invocation in the fixture setup documents the
        expected tag list and lets operators verify the sub-repo carries the
        required semver tags before running RX scenarios.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        block = _extract_fixture_block(content)
        assert _TAG_VERIFY_CMD in block, (
            f"'{_TAG_VERIFY_CMD}' is missing from the '{FIXTURE_HEADING}' block "
            f"inside '{RX_CATEGORY_HEADING}' in {INTEGRATION_TESTING_DOC}. "
            "Add a 'git -C ... tag | sort -V' verification step to the fixture setup."
        )

    @pytest.mark.skipif(
        not os.environ.get("KANON_TEST_ROOT"),
        reason="KANON_TEST_ROOT not set; skipping real-fixture filesystem assertion",
    )
    def test_catalog_bare_repo_head_file_exists(self) -> None:
        """The bare git repo at fixtures/cs-catalog/catalog must contain a HEAD file.

        A bare git repo always contains a HEAD file at its root; its presence
        confirms that the path is a genuine bare repository rather than an
        empty directory or a non-bare clone.  This test uses the KANON_TEST_ROOT
        environment variable to locate the fixture and runs
        'git rev-parse --is-bare-repository' to verify the repository type.
        """
        kanon_test_root = pathlib.Path(os.environ["KANON_TEST_ROOT"])
        catalog_path = kanon_test_root / "fixtures" / "cs-catalog" / "catalog"
        assert catalog_path.is_dir(), (
            f"Expected a bare git repository at {catalog_path} but the path does not exist. "
            "Run the Category 15 fixture setup to create it with 'git clone --bare'."
        )
        assert (catalog_path / "HEAD").exists(), (
            f"Expected a HEAD file inside {catalog_path} but it is absent. "
            "The directory exists but does not appear to be a bare git repository."
        )
        result = subprocess.run(
            ["git", "-C", str(catalog_path), "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and result.stdout.strip() == "true", (
            f"'git rev-parse --is-bare-repository' at {catalog_path} returned "
            f"returncode={result.returncode} stdout={result.stdout.strip()!r}. "
            "The repository at that path is not a bare git repository."
        )


@pytest.mark.unit
class TestRxCatalogSubRepoTags:
    """AC-FUNC-001: The cs-catalog sub-repo must carry all 7 required semver tags.

    The fixture setup verification block documents the expected output of
    'git -C .../cs-catalog/catalog tag | sort -V' as a comment starting with
    '# Expected:'.  These tests assert that every required tag appears in that
    comment so that an editor cannot silently drop a tag that RX constraint
    scenarios depend on.
    """

    @pytest.mark.parametrize("tag", REQUIRED_TAGS)
    def test_rx_fixture_setup_contains_expected_tag(self, tag: str) -> None:
        """The fixture setup verification comment must include every required semver tag.

        The doc instructs operators to verify the sub-repo tags with:
            git -C ".../cs-catalog/catalog" tag | sort -V
            # Expected: 1.0.0  1.0.1  1.1.0  1.2.0  2.0.0  2.1.0  3.0.0

        If a tag is absent from the '# Expected:' line, an operator checking
        the output would not notice the missing tag, and any RX scenario whose
        constraint resolves to that version would silently fail.
        """
        content = INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        block = _extract_fixture_block(content)
        # Each required tag must appear on a line beginning with '# Expected:'
        # so it is part of the documented verification output, not buried in prose.
        expected_comment_fragment = f"# Expected: {tag}"
        tag_on_expected_line = any(tag in line for line in block.splitlines() if line.strip().startswith("# Expected:"))
        assert tag_on_expected_line, (
            f"Semver tag '{tag}' is missing from the '# Expected:' verification "
            f"comment in the '{FIXTURE_HEADING}' block inside '{RX_CATEGORY_HEADING}' "
            f"in {INTEGRATION_TESTING_DOC}. "
            f"This tag is required for RX scenarios that resolve PEP 440 constraints "
            f"to version {tag}. Add '{tag}' to the '# Expected: ...' comment after "
            "the 'git -C .../cs-catalog/catalog tag | sort -V' command. "
            f"(Checked for: {expected_comment_fragment!r})"
        )
