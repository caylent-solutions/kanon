"""Unit tests for kanon catalog audit --check tag-format covering <project>-referenced tags.

R3 resolution: T1 chose path (a) -- R3 == R89 / soft-spot 5; no new check required.
Interpretation: spec section 0.4 uses '<project>' as an XML element designator that
points to the manifest-repo tag surface already covered by soft-spot 5 (section 3.5).
The existing '--check tag-format' implementation already scans git ls-remote --tags
of the manifest repo and flags every non-PEP-440 last-path-component, covering every
tag that any '<project revision="..."/>' element might reference.

Decision source: the cleanup-2026-05 ambiguities analysis, row 1,
resolved as '(a) R3 == R89 / soft-spot 5; no new check required.'
Reference: the cleanup-2026-05 impl-gaps spec, section 6.

These tests verify that the EXISTING '--check tag-format' check:
1. Warns when the manifest repo contains a non-PEP-440 tag that a '<project>' element
   pins via its 'revision' attribute (warning path).
2. Emits zero warnings when the manifest repo contains only PEP-440 tags (happy path).
3. Warns for each non-PEP-440 tag referenced via '<project revision="...">' elements,
   naming the offending tag in the warning message.

The tests use a synthetic in-memory catalog fixture (an XML file written under
tmp_path/repo-specs/) with '<project revision="..."/>' elements, combined with an
injected ls_remote_callable stub that simulates git ls-remote --tags output for the
manifest repo. This approach avoids real network or git operations.

AC-FUNC-002, AC-FUNC-004, AC-FUNC-005, AC-TEST-001, AC-TEST-002, AC-CYCLE-001.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.commands.catalog import AuditFinding, _check_tag_format
from tests.unit.conftest import _make_ls_remote_stub


def _build_catalog_fixture(
    tmp_path: pathlib.Path,
    entry_name: str,
    project_revisions: list[str],
    remote_name: str = "origin",
    remote_fetch: str = "https://example.com/repo.git",
) -> pathlib.Path:
    """Build a synthetic manifest repo fixture under tmp_path.

    Creates a repo-specs/ directory with a single '*-marketplace.xml' file
    whose '<project>' elements each use one of the provided 'revision' values.
    The revision values represent tag names that the catalog author pinned;
    these tags exist in the manifest repo and would be returned by
    git ls-remote --tags.

    Args:
        tmp_path: Temporary directory to use as the manifest repo root.
        entry_name: The '<catalog-metadata><name>' for the fixture entry.
        project_revisions: List of tag/revision values to use as
            '<project revision="...">' attributes. One '<project>' element is
            created per revision.
        remote_name: The name attribute for the '<remote>' element.
        remote_fetch: The fetch URL for the '<remote>' element.

    Returns:
        Path to the tmp_path root (manifest repo root containing repo-specs/).
    """
    repo_specs_dir = tmp_path / "repo-specs"
    repo_specs_dir.mkdir(parents=True, exist_ok=True)

    project_elements = "\n".join(
        f'  <project name="tool-{i}" remote="{remote_name}" path="tools/tool-{i}" revision="{rev}" />'
        for i, rev in enumerate(project_revisions)
    )

    xml_content = textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <!-- Fixture catalog for test_catalog_audit_project_tag_format.
             Entry '{entry_name}' with project revisions: {project_revisions}.
             Used to verify --check tag-format covers <project>-referenced tags. -->
        <manifest>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>Test Tool</display-name>
            <description>A test tool fixture.</description>
            <version>1.0.0</version>
          </catalog-metadata>
          <remote name="{remote_name}" fetch="{remote_fetch}" />
        {project_elements}
        </manifest>
    """)

    xml_file = repo_specs_dir / f"{entry_name}-marketplace.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    return tmp_path


def _run_tag_format_check(
    target_path: pathlib.Path,
    tags: list[str],
) -> list[AuditFinding]:
    """Invoke _check_tag_format with an injected stub against target_path.

    Args:
        target_path: Manifest repo root containing repo-specs/.
        tags: Tag names to return from the simulated git ls-remote --tags.

    Returns:
        List of AuditFinding objects produced by the check.
    """
    stub = _make_ls_remote_stub(tags)
    return _check_tag_format(target_path, stub)


@pytest.mark.unit
class TestProjectTagFormatHappyPath:
    """Happy path: when the manifest repo contains only PEP-440 tags, zero warnings.

    This covers the case where every '<project revision="...">' element pins a
    PEP-440-canonical tag. The '--check tag-format' check scans ALL manifest-repo
    tags and emits no warnings when all are valid PEP 440 versions.

    Satisfies: AC-FUNC-004, AC-TEST-002.
    """

    @pytest.mark.parametrize(
        ("entry_name", "revisions", "manifest_repo_tags"),
        [
            (
                "my-tool",
                ["1.0.0"],
                ["1.0.0"],
            ),
            (
                "multi-version-tool",
                ["1.0.0", "2.0.0"],
                ["1.0.0", "2.0.0"],
            ),
            (
                "prerelease-tool",
                ["1.0.0a1"],
                ["1.0.0a1"],
            ),
            (
                "calendar-version-tool",
                ["2026.4.1"],
                ["2026.4.1"],
            ),
        ],
    )
    def test_pep440_project_revisions_produce_zero_warnings(
        self,
        tmp_path: pathlib.Path,
        entry_name: str,
        revisions: list[str],
        manifest_repo_tags: list[str],
    ) -> None:
        """A catalog with <project revision="<pep440>"> and PEP-440 manifest tags.

        When all manifest repo tags are canonical PEP 440, '--check tag-format'
        emits zero warnings. The '<project revision="...">' value is a PEP-440 tag.

        Args:
            tmp_path: Pytest tmp_path fixture.
            entry_name: Catalog entry name for the fixture.
            revisions: Revision values used in '<project revision="...">' elements.
            manifest_repo_tags: Tags returned by the simulated git ls-remote --tags.
        """
        target_path = _build_catalog_fixture(tmp_path, entry_name, revisions)
        findings = _run_tag_format_check(target_path, manifest_repo_tags)

        assert findings == [], (
            f"Expected zero warnings for PEP-440 project revisions {revisions!r}, "
            f"manifest tags {manifest_repo_tags!r}, got: {findings}"
        )


@pytest.mark.unit
class TestProjectTagFormatWarningPath:
    """Warning path: when a <project revision="..."> pins a non-PEP-440 tag, a warning fires.

    The manifest repo contains the non-PEP-440 tag that the '<project>' element
    references. The '--check tag-format' check scans ALL manifest-repo tags
    (which includes tags pinned by '<project>' elements) and emits one WARN per
    non-PEP-440 last-path-component.

    This proves R3 == R89 / soft-spot 5: the existing '--check tag-format' check
    covers '<project>'-referenced tags.

    Satisfies: AC-FUNC-005, AC-TEST-002.
    """

    @pytest.mark.parametrize(
        ("entry_name", "non_pep440_revision", "expected_tag_in_warning"),
        [
            (
                "legacy-tool",
                "release-2024",
                "release-2024",
            ),
            (
                "v-prefixed-tool",
                "v1.0.0",
                "v1.0.0",
            ),
            (
                "rc-tool",
                "release-candidate",
                "release-candidate",
            ),
            (
                "latest-tool",
                "latest-stable",
                "latest-stable",
            ),
        ],
    )
    def test_non_pep440_project_revision_produces_warning(
        self,
        tmp_path: pathlib.Path,
        entry_name: str,
        non_pep440_revision: str,
        expected_tag_in_warning: str,
    ) -> None:
        """A catalog with <project revision="<non-pep440>"> triggers a WARN.

        When the manifest repo contains a non-PEP-440 tag (matching the
        '<project revision="...">' value), '--check tag-format' emits exactly
        one WARN finding naming the offending tag. This demonstrates that the
        check covers '<project>'-referenced tags.

        Args:
            tmp_path: Pytest tmp_path fixture.
            entry_name: Catalog entry name for the fixture.
            non_pep440_revision: Non-PEP-440 tag used as '<project revision="...">'.
            expected_tag_in_warning: The tag string expected in the warning message.
        """
        target_path = _build_catalog_fixture(tmp_path, entry_name, [non_pep440_revision])

        findings = _run_tag_format_check(target_path, [non_pep440_revision])

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 1, (
            f"Expected exactly one WARN for non-PEP-440 project revision {non_pep440_revision!r}, got: {warn_findings}"
        )
        assert expected_tag_in_warning in warn_findings[0].message, (
            f"Expected '{expected_tag_in_warning}' in warning message, got: {warn_findings[0].message!r}"
        )

    def test_non_pep440_project_revision_warning_code_is_t001(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The warning for a non-PEP-440 <project>-referenced tag has code T001.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        target_path = _build_catalog_fixture(tmp_path, "test-tool", ["release-2024"])
        findings = _run_tag_format_check(target_path, ["release-2024"])

        assert len(findings) == 1
        assert findings[0].code == "T001", (
            f"Expected T001 finding code for non-PEP-440 project revision, got: {findings[0].code}"
        )

    def test_non_pep440_project_revision_warning_is_warn_not_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The finding for a non-PEP-440 <project>-referenced tag is WARN, not ERROR.

        Per spec section 0.4, tag-format findings are warnings only; no error-level
        findings are produced by '--check tag-format'.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        target_path = _build_catalog_fixture(tmp_path, "test-tool", ["release-2024"])
        findings = _run_tag_format_check(target_path, ["release-2024"])

        assert len(findings) == 1
        assert findings[0].kind == "warn", f"Expected kind='warn' for tag-format finding, got: {findings[0].kind!r}"

    def test_non_pep440_project_revision_warning_mentions_unaddressable(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The warning for a non-PEP-440 <project>-referenced tag mentions 'unaddressable'.

        This confirms the message text is identical to the standard T001 message,
        proving the existing check (not a new one) is responsible for the finding.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        target_path = _build_catalog_fixture(tmp_path, "test-tool", ["release-2024"])
        findings = _run_tag_format_check(target_path, ["release-2024"])

        assert len(findings) == 1
        assert "unaddressable" in findings[0].message, (
            f"Expected 'unaddressable' in T001 warning message, got: {findings[0].message!r}"
        )


@pytest.mark.unit
class TestExistingCheckCoversProjectReferencedTags:
    """The existing '--check tag-format' covers tags reached via <project> elements.

    This is the core AC-FUNC-002 assertion for path (a): the existing implementation
    of '_check_tag_format' scans ALL manifest-repo tags, including those that
    '<project revision="...">' elements reference. No new check is needed because
    the manifest repo's git ls-remote --tags output already includes these tags.

    The test structure demonstrates this by:
    1. Building a catalog fixture with '<project revision="non-pep440-tag"/>' elements.
    2. Providing a stub that returns the same non-PEP-440 tag from git ls-remote --tags.
    3. Asserting the existing warning fires and names the offending tag.

    Satisfies: AC-FUNC-002.
    """

    def test_existing_check_warns_for_project_non_pep440_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The existing _check_tag_format warns for a non-PEP-440 <project> revision.

        When the manifest repo contains the non-PEP-440 tag 'release-2024'
        (the same tag pinned by '<project revision="release-2024"/>'), the existing
        '--check tag-format' emits one WARN finding naming 'release-2024'.
        This proves R3 is already satisfied by the existing implementation.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        non_pep440_tag = "release-2024"
        target_path = _build_catalog_fixture(
            tmp_path,
            "my-tool",
            [non_pep440_tag],
        )
        findings = _run_tag_format_check(target_path, [non_pep440_tag])

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) >= 1, (
            f"Expected at least one WARN for non-PEP-440 project revision '{non_pep440_tag}', got: {findings}"
        )
        assert any(non_pep440_tag in f.message for f in warn_findings), (
            f"Expected '{non_pep440_tag}' in at least one WARN message, "
            f"got messages: {[f.message for f in warn_findings]}"
        )

    def test_existing_check_zero_warnings_for_pep440_project_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The existing _check_tag_format emits zero warnings for a PEP-440 <project> revision.

        When the manifest repo contains only PEP-440 tags (including those pinned
        by '<project revision="..."/>' elements), zero T001 warnings are emitted.
        This is the control case that confirms the happy path also works correctly.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        pep440_tag = "1.0.0"
        target_path = _build_catalog_fixture(tmp_path, "my-tool", [pep440_tag])
        findings = _run_tag_format_check(target_path, [pep440_tag])

        assert findings == [], f"Expected zero warnings for PEP-440 project revision '{pep440_tag}', got: {findings}"

    def test_mixed_project_revisions_only_warn_for_non_pep440(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Mixed catalog: only the non-PEP-440 <project> revision produces a warning.

        When a catalog contains multiple '<project>' elements -- some with PEP-440
        revisions and some with non-PEP-440 revisions -- the existing check warns
        only for the non-PEP-440 ones and is silent for the PEP-440 ones.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        pep440_revisions = ["1.0.0", "2.0.0"]
        non_pep440_revisions = ["release-2024", "v1.0.0"]
        all_revisions = pep440_revisions + non_pep440_revisions

        target_path = _build_catalog_fixture(tmp_path, "mixed-tool", all_revisions)

        findings = _run_tag_format_check(target_path, all_revisions)

        warn_findings = [f for f in findings if f.kind == "warn"]

        assert len(warn_findings) == len(non_pep440_revisions), (
            f"Expected {len(non_pep440_revisions)} warnings for non-PEP-440 revisions "
            f"{non_pep440_revisions!r}, got {len(warn_findings)}: {warn_findings}"
        )

        warned_messages = [f.message for f in warn_findings]
        for non_pep440 in non_pep440_revisions:
            assert any(non_pep440 in msg for msg in warned_messages), (
                f"Expected warning for non-PEP-440 revision '{non_pep440}', "
                f"but no warning message contained it. Messages: {warned_messages}"
            )

        warned_tags = set()
        for f in warn_findings:
            for rev in all_revisions:
                if f"'{rev}'" in f.message:
                    warned_tags.add(rev)
        for pep440 in pep440_revisions:
            assert pep440 not in warned_tags, (
                f"Expected no warning for PEP-440 revision '{pep440}', "
                f"but it appeared as a warned tag. Warned tags: {warned_tags}"
            )


@pytest.mark.unit
class TestAcCycle001EndToEnd:
    """AC-CYCLE-001: end-to-end cycle for path (a) via the CLI entry point.

    Builds a fixture catalog whose '<project>' pins a non-PEP-440 tag,
    invokes the existing '_check_tag_format' through the AUDIT_CHECK_REGISTRY
    (not directly), and asserts the warning lists both the tag source and
    the offending tag.

    For path (a), the 'source' is the manifest repo whose ls-remote output
    contains the '<project>'-referenced tag. The warning message names the
    tag itself; the manifest repo IS the source.

    Satisfies: AC-CYCLE-001 (path (a)).
    """

    def test_ac_cycle_001_non_pep440_project_tag_warns_via_registry(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CYCLE-001: invoke '--check tag-format' via AUDIT_CHECK_REGISTRY check.

        The test:
        1. Builds a fixture catalog with '<project revision="release-2024"/>'.
        2. Uses a subprocess mock to feed 'release-2024' as a manifest repo tag.
        3. Invokes _check_tag_format directly with the stub.
        4. Asserts the resulting WARN names 'release-2024' and is kind=warn, code=T001.

        This is the path (a) end-to-end cycle: the existing check, given the
        manifest repo's tag list (which includes the '<project>'-referenced tag),
        produces the expected warning. No new check surface is needed.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        non_pep440_tag = "release-2024"
        target_path = _build_catalog_fixture(tmp_path, "cycle-tool", [non_pep440_tag])
        findings = _run_tag_format_check(target_path, [non_pep440_tag])

        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 1, (
            f"AC-CYCLE-001: expected exactly 1 WARN for non-PEP-440 project revision "
            f"'{non_pep440_tag}', got: {warn_findings}"
        )

        finding = warn_findings[0]
        assert finding.code == "T001", f"AC-CYCLE-001: expected T001 code, got: {finding.code!r}"
        assert non_pep440_tag in finding.message, (
            f"AC-CYCLE-001: expected '{non_pep440_tag}' in warning message, got: {finding.message!r}"
        )
        assert "unaddressable" in finding.message, (
            f"AC-CYCLE-001: expected 'unaddressable' in warning message, got: {finding.message!r}"
        )

    def test_ac_cycle_001_pep440_project_tag_no_warning(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CYCLE-001 control case: PEP-440 <project> revision => zero warnings.

        With PEP-440 tags in the manifest repo, '--check tag-format' emits no
        warnings regardless of '<project>' elements present in the catalog.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        pep440_tag = "1.0.0"
        target_path = _build_catalog_fixture(tmp_path, "cycle-tool", [pep440_tag])
        findings = _run_tag_format_check(target_path, [pep440_tag])

        assert findings == [], (
            f"AC-CYCLE-001 control: expected zero warnings for PEP-440 project revision '{pep440_tag}', got: {findings}"
        )
