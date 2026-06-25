"""Unit tests for kanon catalog audit --check tag-format covering <project revision> exactness.

These tests verify that '--check tag-format' validates every '<project revision>'
in the catalog against the SAME exact-only rule that 'kanon validate marketplace'
enforces (spec Section 4.5 / Section 6 / FR-22): a revision must be an exact tag
of the form 'refs/tags/<path>/<pep440>'. A branch, the '*' wildcard, and a single
or compound version-range constraint (e.g. '>=0.1.0,<1.0.0') are all rejected as
ERROR findings (code T002), so catalog audit and validate marketplace agree.

This is the alignment fix: previously '--check tag-format' inspected only the
manifest repo's git tag surface (T001 WARN about non-PEP-440 tag names) and never
validated the '<project revision>' attribute, so it silently ACCEPTED a range
revision that validate marketplace correctly REJECTED. The T002 check closes that
gap by reusing the shared '_is_exact_tag_revision' predicate (DRY).

The tests use a synthetic in-memory catalog fixture (an XML file written under
tmp_path/repo-specs/) with '<project revision="..."/>' elements, combined with an
injected ls_remote_callable stub that simulates git ls-remote --tags output for the
manifest repo. This approach avoids real network or git operations.
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.commands.catalog import AuditFinding, _check_tag_format
from tests.unit.conftest import _make_ls_remote_stub


def _build_catalog_fixture(
    tmp_path: pathlib.Path,
    entry_name: str,
    project_revisions: list[str],
    remote_name: str = "origin",
    remote_fetch: str = "https://example.com/repo",
) -> pathlib.Path:
    """Build a synthetic manifest repo fixture under tmp_path.

    Creates a repo-specs/ directory with a single '*-marketplace.xml' file
    whose '<project>' elements each use one of the provided 'revision' values.

    The XML is assembled with xml.etree so attribute values containing special
    characters (e.g. '<' in a version range like '>=0.1.0,<1.0.0') are escaped
    correctly and the manifest stays well-formed.

    Args:
        tmp_path: Temporary directory to use as the manifest repo root.
        entry_name: The '<catalog-metadata><name>' for the fixture entry.
        project_revisions: List of revision values to use as
            '<project revision="...">' attributes. One '<project>' element is
            created per revision.
        remote_name: The name attribute for the '<remote>' element.
        remote_fetch: The fetch URL for the '<remote>' element.

    Returns:
        Path to the tmp_path root (manifest repo root containing repo-specs/).
    """
    import xml.etree.ElementTree as ET

    repo_specs_dir = tmp_path / "repo-specs"
    repo_specs_dir.mkdir(parents=True, exist_ok=True)

    manifest = ET.Element("manifest")
    metadata = ET.SubElement(manifest, "catalog-metadata")
    for tag, text in (
        ("name", entry_name),
        ("display-name", "Test Tool"),
        ("description", "A test tool fixture."),
        ("version", "1.0.0"),
    ):
        ET.SubElement(metadata, tag).text = text

    ET.SubElement(manifest, "remote", {"name": remote_name, "fetch": remote_fetch})

    for i, rev in enumerate(project_revisions):
        ET.SubElement(
            manifest,
            "project",
            {
                "name": f"tool-{i}",
                "remote": remote_name,
                "path": f"tools/tool-{i}",
                "revision": rev,
            },
        )

    xml_file = repo_specs_dir / f"{entry_name}-marketplace.xml"
    ET.ElementTree(manifest).write(str(xml_file), encoding="utf-8", xml_declaration=True)

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


_VALID_EXACT_REVISION = "refs/tags/tools/tool/1.0.0"


@pytest.mark.unit
class TestProjectRevisionExactTagHappyPath:
    """An exact-tag '<project revision>' produces zero T002 findings."""

    @pytest.mark.parametrize(
        "revisions",
        [
            ["refs/tags/tools/tool/1.0.0"],
            ["refs/tags/tools/tool/1.0.0", "refs/tags/tools/tool/2.0.0"],
            ["refs/tags/tools/tool/1.0.0a1"],
            ["refs/tags/tools/tool/2026.4.1"],
            ["refs/tags/deep/nested/path/tool/3.4.5"],
        ],
    )
    def test_exact_tag_revisions_produce_zero_t002(
        self,
        tmp_path: pathlib.Path,
        revisions: list[str],
    ) -> None:
        """A catalog whose every '<project revision>' is an exact tag emits no T002 findings."""
        target_path = _build_catalog_fixture(tmp_path, "exact-tool", revisions)
        findings = _run_tag_format_check(target_path, ["1.0.0", "2.0.0"])

        t002 = [f for f in findings if f.code == "T002"]
        assert t002 == [], f"Expected zero T002 findings for exact-tag revisions {revisions!r}, got: {t002}"


@pytest.mark.unit
class TestProjectRevisionRangeRejected:
    """A non-exact '<project revision>' is rejected as a T002 ERROR (alignment with validate marketplace)."""

    @pytest.mark.parametrize(
        "revision",
        [
            ">=0.1.0,<1.0.0",
            "~=1.2.0",
            ">=1.0.0",
            "main",
            "*",
            "refs/tags/tools/tool/*",
            "refs/tags/tools/tool/1.2.x",
            "v1.0.0",
            "release-2024",
        ],
    )
    def test_non_exact_revision_produces_t002_error(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Every non-exact-tag revision shape produces exactly one T002 ERROR naming the revision."""
        target_path = _build_catalog_fixture(tmp_path, "bad-tool", [revision])
        findings = _run_tag_format_check(target_path, ["1.0.0"])

        t002 = [f for f in findings if f.code == "T002"]
        assert len(t002) == 1, f"Expected exactly one T002 ERROR for non-exact revision {revision!r}, got: {t002}"
        assert t002[0].kind == "error", f"Expected kind='error' for T002, got: {t002[0].kind!r}"
        assert revision in t002[0].message, f"Expected revision {revision!r} named in message, got: {t002[0].message!r}"

    def test_range_revision_rejected_identically_to_validate_marketplace(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A version-range revision is rejected by catalog audit just as validate marketplace rejects it.

        This is the core finding-#4 assertion: validate marketplace's
        validate_tag_format rejects '>=0.1.0,<1.0.0'; catalog audit's
        tag-format check must reject it identically (both reuse the shared
        '_is_exact_tag_revision' predicate, so the verdicts agree).
        """
        from pathlib import Path

        from kanon_cli.core.marketplace_validator import validate_tag_format

        range_revision = ">=0.1.0,<1.0.0"
        target_path = _build_catalog_fixture(tmp_path, "range-tool", [range_revision])

        audit_findings = _run_tag_format_check(target_path, ["1.0.0"])
        audit_t002 = [f for f in audit_findings if f.code == "T002"]

        xml_files = list((target_path / "repo-specs").glob("*-marketplace.xml"))
        marketplace_errors = validate_tag_format([Path(p) for p in xml_files], target_path)

        assert len(audit_t002) == 1, f"catalog audit must reject the range revision (one T002 ERROR), got: {audit_t002}"
        assert len(marketplace_errors) == 1, (
            f"validate marketplace must reject the range revision, got: {marketplace_errors}"
        )
        assert range_revision in audit_t002[0].message
        assert range_revision in marketplace_errors[0]

    def test_t002_remediation_points_at_validate_marketplace(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The T002 remediation names an exact-tag form and the validate marketplace cross-check."""
        target_path = _build_catalog_fixture(tmp_path, "bad-tool", [">=0.1.0,<1.0.0"])
        findings = _run_tag_format_check(target_path, ["1.0.0"])

        t002 = [f for f in findings if f.code == "T002"]
        assert len(t002) == 1
        assert "refs/tags/" in t002[0].remediation
        assert "validate marketplace" in t002[0].remediation


@pytest.mark.unit
class TestMixedProjectRevisions:
    """A mix of exact-tag and non-exact revisions yields T002 only for the non-exact ones."""

    def test_only_non_exact_revisions_produce_t002(self, tmp_path: pathlib.Path) -> None:
        """Exact-tag revisions are silent; only non-exact revisions produce T002 errors."""
        exact = ["refs/tags/tools/tool/1.0.0", "refs/tags/tools/tool/2.0.0"]
        non_exact = [">=0.1.0,<1.0.0", "main"]
        target_path = _build_catalog_fixture(tmp_path, "mixed-tool", exact + non_exact)

        findings = _run_tag_format_check(target_path, ["1.0.0", "2.0.0"])
        t002 = [f for f in findings if f.code == "T002"]

        assert len(t002) == len(non_exact), (
            f"Expected {len(non_exact)} T002 errors for non-exact revisions {non_exact!r}, got {len(t002)}: {t002}"
        )
        messages = " ".join(f.message for f in t002)
        for rev in non_exact:
            assert rev in messages, f"Expected non-exact revision {rev!r} named in a T002 message: {messages!r}"
        for rev in exact:
            assert rev not in messages, f"Exact-tag revision {rev!r} must not be flagged: {messages!r}"


@pytest.mark.unit
class TestInheritedDefaultRevision:
    """A project that inherits a non-exact '<default revision>' is rejected via T002."""

    def test_inherited_branch_default_revision_produces_t002(self, tmp_path: pathlib.Path) -> None:
        """A '<project>' inheriting a branch '<default revision>' produces a T002 ERROR.

        The project omits its own 'revision'; the inherited default 'main' is a
        branch, so the exact-tag rule rejects it and the T002 finding flags the
        inherited source.
        """
        import xml.etree.ElementTree as ET

        repo_specs_dir = tmp_path / "repo-specs"
        repo_specs_dir.mkdir(parents=True, exist_ok=True)

        manifest = ET.Element("manifest")
        metadata = ET.SubElement(manifest, "catalog-metadata")
        for tag, text in (
            ("name", "inherit-tool"),
            ("display-name", "Inherit Tool"),
            ("description", "Inherited default revision fixture."),
            ("version", "1.0.0"),
        ):
            ET.SubElement(metadata, tag).text = text
        ET.SubElement(manifest, "default", {"revision": "main", "remote": "origin"})
        ET.SubElement(manifest, "remote", {"name": "origin", "fetch": "https://example.com/repo"})
        ET.SubElement(manifest, "project", {"name": "tool-0", "remote": "origin", "path": "tools/tool-0"})

        xml_file = repo_specs_dir / "inherit-tool-marketplace.xml"
        ET.ElementTree(manifest).write(str(xml_file), encoding="utf-8", xml_declaration=True)

        findings = _run_tag_format_check(tmp_path, ["1.0.0"])
        t002 = [f for f in findings if f.code == "T002"]

        assert len(t002) == 1, f"Expected one T002 for inherited branch default, got: {t002}"
        assert "inherited <default revision>" in t002[0].message, (
            f"Expected the inherited-default source named, got: {t002[0].message!r}"
        )


@pytest.mark.unit
class TestT001AndT002Coexist:
    """T001 (repo tag PEP 440 WARN) and T002 (project revision exactness ERROR) are independent."""

    def test_non_pep440_repo_tag_and_non_exact_revision_both_fire(self, tmp_path: pathlib.Path) -> None:
        """A non-PEP-440 repo tag yields a T001 WARN while a non-exact revision yields a T002 ERROR."""
        target_path = _build_catalog_fixture(tmp_path, "both-tool", [">=0.1.0,<1.0.0"])

        findings = _run_tag_format_check(target_path, ["release-2024"])

        t001 = [f for f in findings if f.code == "T001"]
        t002 = [f for f in findings if f.code == "T002"]

        assert len(t001) == 1, f"Expected one T001 WARN for the non-PEP-440 repo tag, got: {t001}"
        assert t001[0].kind == "warn"
        assert len(t002) == 1, f"Expected one T002 ERROR for the non-exact revision, got: {t002}"
        assert t002[0].kind == "error"

    def test_clean_catalog_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """PEP-440 repo tags plus an exact-tag revision produce zero findings."""
        target_path = _build_catalog_fixture(tmp_path, "clean-tool", [_VALID_EXACT_REVISION])
        findings = _run_tag_format_check(target_path, ["1.0.0", "2.0.0"])
        assert findings == [], f"Expected zero findings for a clean catalog, got: {findings}"
