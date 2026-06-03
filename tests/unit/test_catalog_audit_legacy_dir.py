"""Unit tests for the _check_legacy_catalog_dir helper in catalog.py.

AC-TEST-001: Parametrized unit tests covering:
  - catalog/ absent (zero findings)
  - catalog/ present but empty (zero findings)
  - catalog/ with one subdirectory (one WARN finding)
  - catalog/ with multiple subdirectories (one WARN finding)
  - version string interpolated into the warning message

Spec source: spec Section 4.8.
"""

from __future__ import annotations

import argparse
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.commands.catalog import (
    AUDIT_CHECK_REGISTRY,
    AuditFinding,
    _check_legacy_catalog_dir,
    audit_command,
)
from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE


@pytest.mark.unit
class TestCheckLegacyCatalogDir:
    """Parametrized unit tests for _check_legacy_catalog_dir."""

    @pytest.mark.parametrize(
        "subdirs,expected_finding_count",
        [
            pytest.param(
                [],
                0,
                id="catalog_dir_absent",
            ),
            pytest.param(
                ["__empty__"],
                0,
                id="catalog_dir_present_but_empty",
            ),
            pytest.param(
                ["foo"],
                1,
                id="catalog_dir_with_one_child",
            ),
            pytest.param(
                ["foo", "bar"],
                1,
                id="catalog_dir_with_multiple_children",
            ),
        ],
    )
    def test_finding_count(
        self,
        tmp_path: pathlib.Path,
        subdirs: list[str],
        expected_finding_count: int,
    ) -> None:
        """Correct number of findings for each catalog/ directory scenario."""
        target = tmp_path / "target"
        target.mkdir()

        if subdirs == ["__empty__"]:
            # catalog/ present but contains no subdirectories
            (target / "catalog").mkdir()
        elif subdirs:
            catalog_dir = target / "catalog"
            for name in subdirs:
                (catalog_dir / name).mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.2.3")
        assert len(findings) == expected_finding_count, (
            f"Expected {expected_finding_count} findings for subdirs={subdirs!r}, got {len(findings)}: {findings!r}"
        )

    def test_finding_is_warn_severity(self, tmp_path: pathlib.Path) -> None:
        """The single finding for catalog/ with children is severity 'warn'."""
        target = tmp_path / "target"
        catalog_child = target / "catalog" / "sample-entry"
        catalog_child.mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert len(findings) == 1
        assert findings[0].kind == "warn"

    def test_finding_is_audit_finding_instance(self, tmp_path: pathlib.Path) -> None:
        """The returned finding is an AuditFinding dataclass instance."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert isinstance(findings[0], AuditFinding)

    @pytest.mark.parametrize(
        "version",
        ["1.0.0", "2.3.4", "0.1.0a1", "99.0.0"],
    )
    def test_version_string_interpolated_into_message(
        self,
        tmp_path: pathlib.Path,
        version: str,
    ) -> None:
        """The version string is interpolated into the warning message. AC-FUNC-004."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, version)
        assert len(findings) == 1
        expected_message = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=version)
        assert findings[0].message == expected_message, (
            f"Message mismatch for version={version!r}.\n"
            f"Expected: {expected_message!r}\n"
            f"Got:      {findings[0].message!r}"
        )

    def test_message_contains_migration_doc_reference(self, tmp_path: pathlib.Path) -> None:
        """The finding message references docs/migration-bootstrap-to-add.md. AC-FUNC-004."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert "docs/migration-bootstrap-to-add.md" in findings[0].message

    def test_message_contains_catalog_dir_name(self, tmp_path: pathlib.Path) -> None:
        """The finding message mentions the 'catalog/' directory. AC-FUNC-004."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert "catalog/" in findings[0].message

    def test_exact_message_text_matches_spec(self, tmp_path: pathlib.Path) -> None:
        """The warning message matches the spec Section 4.8 wording verbatim. AC-FUNC-004."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)
        version = "1.3.1"

        findings = _check_legacy_catalog_dir(target, version)
        expected = (
            f"Legacy catalog/ directory detected; this directory is unused by "
            f"kanon >= {version} and should be deleted; "
            "see docs/migration-bootstrap-to-add.md"
        )
        assert findings[0].message == expected, (
            f"Spec message mismatch.\nExpected: {expected!r}\nGot: {findings[0].message!r}"
        )

    def test_catalog_files_only_not_dirs_produce_no_finding(self, tmp_path: pathlib.Path) -> None:
        """catalog/ with only files (no subdirs) produces zero findings. AC-FUNC-002."""
        target = tmp_path / "target"
        catalog_dir = target / "catalog"
        catalog_dir.mkdir(parents=True)
        # Write files (not subdirectories) inside catalog/
        (catalog_dir / "README.md").write_text("content", encoding="utf-8")
        (catalog_dir / ".gitkeep").write_text("", encoding="utf-8")

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert findings == [], f"Expected zero findings when catalog/ has only files, got: {findings!r}"

    def test_returns_empty_list_when_no_catalog_dir(self, tmp_path: pathlib.Path) -> None:
        """Returns [] (not None) when catalog/ is absent. AC-FUNC-001."""
        target = tmp_path / "target"
        target.mkdir()

        result = _check_legacy_catalog_dir(target, "1.0.0")
        assert result == []
        assert isinstance(result, list)

    def test_one_finding_for_many_children(self, tmp_path: pathlib.Path) -> None:
        """catalog/ with many children still produces exactly ONE finding. AC-FUNC-003."""
        target = tmp_path / "target"
        catalog_dir = target / "catalog"
        for i in range(10):
            (catalog_dir / f"entry-{i}").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert len(findings) == 1, f"Expected exactly 1 finding for 10 children, got {len(findings)}: {findings!r}"

    def test_finding_code_is_legacy_dir(self, tmp_path: pathlib.Path) -> None:
        """The AuditFinding has a stable code identifier for the legacy-dir check."""
        target = tmp_path / "target"
        (target / "catalog" / "entry").mkdir(parents=True)

        findings = _check_legacy_catalog_dir(target, "1.0.0")
        assert findings[0].code == "L001"


@pytest.mark.unit
class TestLegacyDirConstant:
    """Verify the warning template constant is defined correctly in constants.py."""

    def test_template_is_string(self) -> None:
        """KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE is a non-empty string."""
        assert isinstance(KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE, str)
        assert len(KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE) > 0

    def test_template_contains_version_placeholder(self) -> None:
        """The template contains the {version} format placeholder."""
        assert "{version}" in KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

    def test_template_formats_correctly(self) -> None:
        """The template .format(version=...) produces the expected message."""
        result = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version="1.2.3")
        assert "1.2.3" in result
        assert "catalog/" in result
        assert "docs/migration-bootstrap-to-add.md" in result

    def test_template_matches_spec_verbatim(self) -> None:
        """Template matches the spec Section 4.8 wording with {version} as the only placeholder."""
        version = "1.3.1"
        result = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=version)
        expected = (
            f"Legacy catalog/ directory detected; this directory is unused by "
            f"kanon >= {version} and should be deleted; "
            "see docs/migration-bootstrap-to-add.md"
        )
        assert result == expected, f"Template format output mismatch.\nExpected: {expected!r}\nGot: {result!r}"


def _make_audit_args(
    target: str,
    check: str = "metadata",
    fmt: str = "text",
    strict: bool = False,
) -> argparse.Namespace:
    """Build a minimal argparse Namespace for audit_command unit tests."""
    from kanon_cli.commands.catalog import _parse_check_subset

    return argparse.Namespace(
        target=target,
        check=check,
        check_subset=_parse_check_subset(check),
        format=fmt,
        no_color=False,
        strict=strict,
        quiet=False,
        verbose=False,
    )


@pytest.mark.unit
class TestAuditCommandLegacyDirIntegration:
    """Unit tests verifying audit_command invokes _check_legacy_catalog_dir unconditionally."""

    def test_audit_command_calls_legacy_check_unconditionally(self, tmp_path: pathlib.Path) -> None:
        """audit_command emits legacy-dir WARN even when --check metadata is specified. AC-FUNC-005."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        # Create the legacy catalog/ directory tree to trigger the WARN.
        (tmp_path / "catalog" / "entry").mkdir(parents=True)

        args = _make_audit_args(target=str(tmp_path), check="metadata")
        captured_output: list[str] = []

        def _mock_print(msg: str = "", **_kwargs: object) -> None:
            captured_output.append(msg)

        with (
            patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True),
            patch("kanon_cli.commands.catalog.print", side_effect=_mock_print),
        ):
            result = audit_command(args)

        assert result == 0, f"Expected exit 0 (WARN only), got {result}"
        all_output = "\n".join(captured_output)
        assert "catalog/" in all_output, f"Expected 'catalog/' in audit_command output.\nGot: {all_output!r}"

    def test_audit_command_no_legacy_warn_when_no_catalog_dir(self, tmp_path: pathlib.Path) -> None:
        """audit_command emits no WARN when catalog/ is absent. AC-FUNC-001."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        # No catalog/ directory created.

        args = _make_audit_args(target=str(tmp_path), check="metadata")
        captured_output: list[str] = []

        def _mock_print(msg: str = "", **_kwargs: object) -> None:
            captured_output.append(msg)

        with (
            patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True),
            patch("kanon_cli.commands.catalog.print", side_effect=_mock_print),
        ):
            result = audit_command(args)

        assert result == 0
        all_output = "\n".join(captured_output)
        assert "catalog/" not in all_output, (
            f"Expected no 'catalog/' mention when catalog/ is absent.\nGot: {all_output!r}"
        )

    def test_audit_command_exit_0_with_warn_only(self, tmp_path: pathlib.Path) -> None:
        """audit_command exits 0 when only the legacy-dir WARN is present. AC-FUNC-007."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (tmp_path / "catalog" / "entry").mkdir(parents=True)

        args = _make_audit_args(target=str(tmp_path), check="metadata")
        with (
            patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True),
            patch("kanon_cli.commands.catalog.print"),
        ):
            result = audit_command(args)

        assert result == 0, f"Expected exit 0 for WARN-only run, got {result}"
