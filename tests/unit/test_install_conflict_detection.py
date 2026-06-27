"""Unit tests for package-destination conflict detection in kanon install.

The install conflict check is keyed on the package DESTINATION PATH
(``.packages/<name>``), not the repository URL.  The genuine invariant is that
no two installed ``<project>`` entries may occupy the same destination slot with
different content; the SAME repository installed at DIFFERENT commits for
DIFFERENT paths (independent packages from a mono-repo catalog) is allowed.

Covers:
  - benign diamond -- same path, same SHA -> no error
  - same repo, different paths, different SHAs -> no error (the mono-repo case)
  - two-row conflict -- same path, different SHA -> error
  - three-plus-row conflict -- same path, multiple SHAs -> single error
  - empty input -> empty list (consistent return type)
  - source manifests are excluded (never occupy a .packages/ slot)
"""

from __future__ import annotations

import pytest

from kanon_cli.core.install import (
    PackagePathConflictError,
    PackagePathConflictReport,
    PackagePin,
    _detect_package_path_conflicts,
    _gather_package_pins,
)
from kanon_cli.core.lockfile import ContentPinEntry, SourceEntry


_PATH = ".packages/example-package"
_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40


def _pin(source_alias: str, name: str, path: str, resolved_sha: str) -> PackagePin:
    return PackagePin(source_alias=source_alias, name=name, path=path, resolved_sha=resolved_sha)


@pytest.mark.unit
class TestDetectPackagePathConflictsEmpty:
    def test_empty_input_returns_empty_list(self) -> None:
        result = _detect_package_path_conflicts([])
        assert result == []

    def test_returns_list_not_none(self) -> None:
        result = _detect_package_path_conflicts([])
        assert result is not None
        assert isinstance(result, list)

    def test_single_pin_no_conflict(self) -> None:
        pins = [_pin("src_a", "example-package", _PATH, _SHA_A)]
        result = _detect_package_path_conflicts(pins)
        assert result == []


@pytest.mark.unit
class TestDetectPackagePathConflictsAllowed:
    def test_same_path_same_sha_no_conflict(self) -> None:
        """Two sources placing the same package at the same commit -- benign diamond."""
        pins = [
            _pin("src_a", "example-package", _PATH, _SHA_A),
            _pin("src_b", "example-package", _PATH, _SHA_A),
        ]
        result = _detect_package_path_conflicts(pins)
        assert result == []

    def test_same_repo_different_paths_different_sha_no_conflict(self) -> None:
        """The mono-repo case: one repo, two packages at different paths, different commits."""
        pins = [
            _pin("src_a", "control-tower", ".packages/control-tower", _SHA_A),
            _pin("src_b", "review-terraform", ".packages/review-terraform", _SHA_B),
        ]
        result = _detect_package_path_conflicts(pins)
        assert result == []

    def test_many_distinct_paths_distinct_shas_no_conflict(self) -> None:
        """Several packages from one mono-repo, each at its own path and commit."""
        pins = [
            _pin("s", "a", ".packages/a", _SHA_A),
            _pin("s", "b", ".packages/b", _SHA_B),
            _pin("s", "c", ".packages/c", _SHA_C),
        ]
        result = _detect_package_path_conflicts(pins)
        assert result == []


@pytest.mark.unit
class TestDetectPackagePathConflictsTwoRow:
    def test_same_path_different_sha_is_conflict(self) -> None:
        pins = [
            _pin("src_a", "example-package", _PATH, _SHA_A),
            _pin("src_b", "example-package", _PATH, _SHA_B),
        ]
        result = _detect_package_path_conflicts(pins)
        assert len(result) == 1

    def test_conflict_report_has_correct_path(self) -> None:
        pins = [
            _pin("src_a", "pkg", _PATH, _SHA_A),
            _pin("src_b", "pkg", _PATH, _SHA_B),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert reports[0].path == _PATH

    def test_conflict_report_entries_contain_both_rows(self) -> None:
        pins = [
            _pin("src_a", "pkg", _PATH, _SHA_A),
            _pin("src_b", "pkg", _PATH, _SHA_B),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert len(reports[0].entries) == 2
        aliases = {e.source_alias for e in reports[0].entries}
        assert aliases == {"src_a", "src_b"}

    def test_conflict_report_entries_contain_shas(self) -> None:
        pins = [
            _pin("src_a", "pkg", _PATH, _SHA_A),
            _pin("src_b", "pkg", _PATH, _SHA_B),
        ]
        reports = _detect_package_path_conflicts(pins)
        shas = {e.resolved_sha for e in reports[0].entries}
        assert shas == {_SHA_A, _SHA_B}

    def test_entries_sorted_deterministically(self) -> None:
        """Entries are sorted by (source_alias, sha) regardless of input order."""
        pins = [
            _pin("src_b", "pkg", _PATH, _SHA_B),
            _pin("src_a", "pkg", _PATH, _SHA_A),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert [e.source_alias for e in reports[0].entries] == ["src_a", "src_b"]


@pytest.mark.unit
class TestDetectPackagePathConflictsMultiRow:
    def test_three_rows_two_distinct_shas_is_single_conflict(self) -> None:
        pins = [
            _pin("src_a", "pkg", _PATH, _SHA_A),
            _pin("src_b", "pkg", _PATH, _SHA_B),
            _pin("src_c", "pkg", _PATH, _SHA_A),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert len(reports) == 1

    def test_three_row_conflict_report_lists_all_three_entries(self) -> None:
        pins = [
            _pin("src_a", "pkg", _PATH, _SHA_A),
            _pin("src_b", "pkg", _PATH, _SHA_B),
            _pin("src_c", "pkg", _PATH, _SHA_C),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert len(reports[0].entries) == 3

    def test_two_path_groups_only_conflicting_group_reported(self) -> None:
        pins = [
            _pin("src_a", "pkg-a", ".packages/pkg-a", _SHA_A),
            _pin("src_b", "pkg-a", ".packages/pkg-a", _SHA_A),
            _pin("src_c", "pkg-b", ".packages/pkg-b", _SHA_A),
            _pin("src_d", "pkg-b", ".packages/pkg-b", _SHA_B),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert len(reports) == 1
        assert reports[0].path == ".packages/pkg-b"

    def test_multiple_conflicting_groups_all_reported_sorted_by_path(self) -> None:
        pins = [
            _pin("src_c", "pkg-b", ".packages/pkg-b", _SHA_A),
            _pin("src_d", "pkg-b", ".packages/pkg-b", _SHA_C),
            _pin("src_a", "pkg-a", ".packages/pkg-a", _SHA_A),
            _pin("src_b", "pkg-a", ".packages/pkg-a", _SHA_B),
        ]
        reports = _detect_package_path_conflicts(pins)
        assert [r.path for r in reports] == [".packages/pkg-a", ".packages/pkg-b"]


@pytest.mark.unit
class TestGatherPackagePins:
    def _source(self, alias: str, sha: str, pins: list[ContentPinEntry]) -> SourceEntry:
        return SourceEntry(
            alias=alias,
            name=alias,
            url="https://gitserver/org/mono-repo.git",
            ref_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha=sha,
            path="repo-specs/entry-marketplace.xml",
            content_pins=pins,
        )

    def test_flattens_content_pins_across_sources(self) -> None:
        entries = [
            self._source("src_a", _SHA_A, [ContentPinEntry(name="a", path=".packages/a", resolved_sha=_SHA_A)]),
            self._source("src_b", _SHA_B, [ContentPinEntry(name="b", path=".packages/b", resolved_sha=_SHA_B)]),
        ]
        pins = _gather_package_pins(entries)
        assert {(p.source_alias, p.path, p.resolved_sha) for p in pins} == {
            ("src_a", ".packages/a", _SHA_A),
            ("src_b", ".packages/b", _SHA_B),
        }

    def test_excludes_source_manifest_itself(self) -> None:
        """A source's own manifest repo SHA is never a package pin (no .packages/ slot)."""
        entries = [self._source("src_a", _SHA_A, [])]
        pins = _gather_package_pins(entries)
        assert pins == []

    def test_same_repo_two_sources_different_sha_yields_no_conflict(self) -> None:
        """End-to-end gather+detect: same mono-repo under two aliases, different paths/commits."""
        entries = [
            self._source(
                "control_tower", _SHA_A, [ContentPinEntry("control-tower", ".packages/control-tower", _SHA_A)]
            ),
            self._source(
                "review_tf", _SHA_B, [ContentPinEntry("review-terraform", ".packages/review-terraform", _SHA_B)]
            ),
        ]
        reports = _detect_package_path_conflicts(_gather_package_pins(entries))
        assert reports == []


@pytest.mark.unit
class TestPackagePathConflictError:
    def _build_two_row_conflict(self) -> PackagePathConflictReport:
        return PackagePathConflictReport(
            path=_PATH,
            entries=[
                PackagePin(source_alias="src_a", name="example-package", path=_PATH, resolved_sha=_SHA_A),
                PackagePin(source_alias="src_b", name="example-package", path=_PATH, resolved_sha=_SHA_B),
            ],
        )

    def test_is_install_error_subclass(self) -> None:
        from kanon_cli.core.install import InstallError

        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        assert isinstance(err, InstallError)

    def test_error_message_contains_source_aliases(self) -> None:
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        msg = str(err)
        assert "src_a" in msg
        assert "src_b" in msg

    def test_error_message_contains_path(self) -> None:
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        msg = str(err)
        assert _PATH in msg
        assert "Conflict for package path:" in msg

    def test_error_message_contains_shas(self) -> None:
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        msg = str(err)
        assert _SHA_A in msg
        assert _SHA_B in msg

    def test_error_message_contains_remediation(self) -> None:
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        msg = str(err)
        assert "remove one source" in msg
        assert "align the project revisions" in msg

    def test_error_message_row_format(self) -> None:
        """Each conflicting row appears as '  <alias> (<name>): <path> @ <sha>'."""
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        msg = str(err)
        assert f"  src_a (example-package): {_PATH} @ {_SHA_A}" in msg
        assert f"  src_b (example-package): {_PATH} @ {_SHA_B}" in msg

    def test_error_message_starts_with_error(self) -> None:
        err = PackagePathConflictError(reports=[self._build_two_row_conflict()])
        assert str(err).startswith("ERROR:")

    def test_multiple_reports_all_rendered(self) -> None:
        report1 = PackagePathConflictReport(
            path=".packages/pkg-a",
            entries=[
                PackagePin("src_a", "pkg-a", ".packages/pkg-a", _SHA_A),
                PackagePin("src_b", "pkg-a", ".packages/pkg-a", _SHA_B),
            ],
        )
        report2 = PackagePathConflictReport(
            path=".packages/pkg-b",
            entries=[
                PackagePin("src_c", "pkg-b", ".packages/pkg-b", _SHA_A),
                PackagePin("src_d", "pkg-b", ".packages/pkg-b", _SHA_C),
            ],
        )
        err = PackagePathConflictError(reports=[report1, report2])
        msg = str(err)
        assert ".packages/pkg-a" in msg
        assert ".packages/pkg-b" in msg


@pytest.mark.unit
class TestPackagePathConflictReport:
    def test_fields_accessible_by_name(self) -> None:
        report = PackagePathConflictReport(path=_PATH, entries=[])
        assert report.path == _PATH
        assert report.entries == []

    def test_entries_is_list_of_package_pins(self) -> None:
        entry = PackagePin(source_alias="src_a", name="pkg", path=_PATH, resolved_sha=_SHA_A)
        report = PackagePathConflictReport(path=_PATH, entries=[entry])
        assert len(report.entries) == 1
        assert report.entries[0].source_alias == "src_a"


@pytest.mark.unit
class TestPackagePin:
    def test_fields_accessible_by_name(self) -> None:
        p = PackagePin(source_alias="src_a", name="pkg", path=_PATH, resolved_sha=_SHA_A)
        assert p.source_alias == "src_a"
        assert p.name == "pkg"
        assert p.path == _PATH
        assert p.resolved_sha == _SHA_A
