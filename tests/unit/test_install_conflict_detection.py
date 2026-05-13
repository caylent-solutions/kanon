"""Unit tests for canonical-URL conflict detection in kanon install.

Covers:
  AC-FUNC-001: benign diamond -- same canonical URL, same SHA -> no error
  AC-FUNC-002: two-row conflict -- same canonical URL, different SHA -> error
  AC-FUNC-003: three-plus-row conflict -- same canonical URL, multiple SHAs -> single error
  AC-FUNC-006: empty input -> empty list (consistent return type)
"""

from __future__ import annotations

import pytest

from kanon_cli.core.install import (
    CanonicalUrlConflictError,
    CanonicalUrlConflictReport,
    ResolvedProject,
    _detect_canonical_url_conflicts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANONICAL = "https://gitserver/org/example-package"
_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40


def _project(
    source_path: str,
    raw_url: str,
    canonical_url: str,
    resolved_sha: str,
) -> ResolvedProject:
    return ResolvedProject(
        source_path=source_path,
        raw_url=raw_url,
        canonical_url=canonical_url,
        resolved_sha=resolved_sha,
    )


# ---------------------------------------------------------------------------
# AC-FUNC-006: empty input -> empty list
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCanonicalUrlConflictsEmpty:
    def test_empty_input_returns_empty_list(self) -> None:
        result = _detect_canonical_url_conflicts([])
        assert result == []

    def test_returns_list_not_none(self) -> None:
        result = _detect_canonical_url_conflicts([])
        assert result is not None
        assert isinstance(result, list)

    def test_single_project_no_conflict(self) -> None:
        projects = [
            _project("src-a/path/manifest.xml", "git@gitserver:org/example-package.git", _CANONICAL, _SHA_A),
        ]
        result = _detect_canonical_url_conflicts(projects)
        assert result == []


# ---------------------------------------------------------------------------
# AC-FUNC-001: benign diamond -- same canonical URL, same SHA -> allowed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCanonicalUrlConflictsBenignDiamond:
    def test_two_rows_same_canonical_same_sha_no_conflict(self) -> None:
        """Two sources with different raw URLs but same canonical URL and same SHA -- allowed."""
        projects = [
            _project(
                "src-a/path/manifest.xml",
                "git@gitserver:org/example-package.git",
                _CANONICAL,
                _SHA_A,
            ),
            _project(
                "src-b/path/manifest.xml",
                "https://gitserver/org/example-package.git",
                _CANONICAL,
                _SHA_A,
            ),
        ]
        result = _detect_canonical_url_conflicts(projects)
        assert result == []

    def test_three_rows_same_canonical_same_sha_no_conflict(self) -> None:
        """Three sources with the same canonical URL and same SHA -- allowed."""
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-c/manifest.xml", "ssh://gitserver/org/pkg.git", _CANONICAL, _SHA_A),
        ]
        result = _detect_canonical_url_conflicts(projects)
        assert result == []

    def test_distinct_canonical_urls_no_conflict(self) -> None:
        """Two rows with entirely different canonical URLs -- no conflict."""
        projects = [
            _project(
                "src-a/manifest.xml",
                "git@gitserver:org/pkg-a.git",
                "https://gitserver/org/pkg-a",
                _SHA_A,
            ),
            _project(
                "src-b/manifest.xml",
                "https://gitserver/org/pkg-b.git",
                "https://gitserver/org/pkg-b",
                _SHA_B,
            ),
        ]
        result = _detect_canonical_url_conflicts(projects)
        assert result == []


# ---------------------------------------------------------------------------
# AC-FUNC-002: two-row conflict -- same canonical URL, different SHAs -> error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCanonicalUrlConflictsTwoRow:
    def test_two_rows_same_canonical_different_sha_is_conflict(self) -> None:
        """Two rows with same canonical URL but different SHAs produce one conflict report."""
        projects = [
            _project(
                "src-a/path/manifest.xml",
                "git@gitserver:org/example-package.git",
                _CANONICAL,
                _SHA_A,
            ),
            _project(
                "src-b/path/manifest.xml",
                "https://gitserver/org/example-package.git",
                _CANONICAL,
                _SHA_B,
            ),
        ]
        result = _detect_canonical_url_conflicts(projects)
        assert len(result) == 1

    def test_conflict_report_has_correct_canonical_url(self) -> None:
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        assert reports[0].canonical_url == _CANONICAL

    def test_conflict_report_entries_contain_both_rows(self) -> None:
        p_a = _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A)
        p_b = _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B)
        reports = _detect_canonical_url_conflicts([p_a, p_b])
        assert len(reports[0].entries) == 2
        entry_source_paths = {e.source_path for e in reports[0].entries}
        assert "src-a/manifest.xml" in entry_source_paths
        assert "src-b/manifest.xml" in entry_source_paths

    def test_conflict_report_entries_contain_raw_urls(self) -> None:
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        raw_urls = {e.raw_url for e in reports[0].entries}
        assert "git@gitserver:org/pkg.git" in raw_urls
        assert "https://gitserver/org/pkg.git" in raw_urls

    def test_conflict_report_entries_contain_shas(self) -> None:
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        shas = {e.resolved_sha for e in reports[0].entries}
        assert _SHA_A in shas
        assert _SHA_B in shas


# ---------------------------------------------------------------------------
# AC-FUNC-003: three-plus-row conflict
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCanonicalUrlConflictsMultiRow:
    def test_three_rows_two_distinct_shas_is_single_conflict(self) -> None:
        """Three rows with same canonical URL, two distinct SHAs -> one conflict report."""
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B),
            _project("src-c/manifest.xml", "ssh://git@gitserver/org/pkg.git", _CANONICAL, _SHA_A),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        assert len(reports) == 1

    def test_three_row_conflict_report_lists_all_three_entries(self) -> None:
        projects = [
            _project("src-a/manifest.xml", "git@gitserver:org/pkg.git", _CANONICAL, _SHA_A),
            _project("src-b/manifest.xml", "https://gitserver/org/pkg.git", _CANONICAL, _SHA_B),
            _project("src-c/manifest.xml", "ssh://gitserver/org/pkg.git", _CANONICAL, _SHA_C),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        assert len(reports[0].entries) == 3

    def test_two_canonical_groups_only_conflicting_group_reported(self) -> None:
        """Two canonical-URL groups: only the one with differing SHAs produces a report."""
        projects = [
            # Group 1: same SHA (benign)
            _project("src-a/m.xml", "git@gitserver:org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_A),
            _project("src-b/m.xml", "https://gitserver/org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_A),
            # Group 2: different SHAs (conflict)
            _project("src-c/m.xml", "git@gitserver:org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_A),
            _project("src-d/m.xml", "https://gitserver/org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_B),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        assert len(reports) == 1
        assert reports[0].canonical_url == "https://gitserver/org/pkg-b"

    def test_multiple_conflicting_groups_all_reported(self) -> None:
        """Two canonical-URL groups both with conflicting SHAs -- both reported."""
        projects = [
            _project("src-a/m.xml", "git@gitserver:org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_A),
            _project("src-b/m.xml", "https://gitserver/org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_B),
            _project("src-c/m.xml", "git@gitserver:org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_A),
            _project("src-d/m.xml", "https://gitserver/org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_C),
        ]
        reports = _detect_canonical_url_conflicts(projects)
        assert len(reports) == 2
        reported_canonicals = {r.canonical_url for r in reports}
        assert "https://gitserver/org/pkg-a" in reported_canonicals
        assert "https://gitserver/org/pkg-b" in reported_canonicals


# ---------------------------------------------------------------------------
# CanonicalUrlConflictError rendering (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCanonicalUrlConflictError:
    def _build_two_row_conflict(self) -> CanonicalUrlConflictReport:
        return CanonicalUrlConflictReport(
            canonical_url=_CANONICAL,
            entries=[
                ResolvedProject(
                    source_path="src-a/path/manifest.xml",
                    raw_url="git@gitserver:org/example-package.git",
                    canonical_url=_CANONICAL,
                    resolved_sha=_SHA_A,
                ),
                ResolvedProject(
                    source_path="src-b/path/manifest.xml",
                    raw_url="https://gitserver/org/example-package.git",
                    canonical_url=_CANONICAL,
                    resolved_sha=_SHA_B,
                ),
            ],
        )

    def test_is_install_error_subclass(self) -> None:
        from kanon_cli.core.install import InstallError

        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        assert isinstance(err, InstallError)

    def test_error_message_contains_source_paths(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert "src-a/path/manifest.xml" in msg
        assert "src-b/path/manifest.xml" in msg

    def test_error_message_contains_raw_urls(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert "git@gitserver:org/example-package.git" in msg
        assert "https://gitserver/org/example-package.git" in msg

    def test_error_message_contains_canonical_url(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert _CANONICAL in msg
        assert "both URLs canonicalize to:" in msg

    def test_error_message_contains_shas(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert _SHA_A in msg
        assert _SHA_B in msg

    def test_error_message_contains_remediation(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert "kanon why" in msg
        assert "resolve by removing one source" in msg.lower() or "removing one source" in msg

    def test_error_message_row_format(self) -> None:
        """Each conflicting row must appear as '  <source-path>: <raw-url> @ <sha>'."""
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert f"  src-a/path/manifest.xml: git@gitserver:org/example-package.git @ {_SHA_A}" in msg
        assert f"  src-b/path/manifest.xml: https://gitserver/org/example-package.git @ {_SHA_B}" in msg

    def test_error_message_starts_with_error(self) -> None:
        report = self._build_two_row_conflict()
        err = CanonicalUrlConflictError(reports=[report])
        msg = str(err)
        assert msg.startswith("ERROR:")

    def test_multiple_reports_all_rendered(self) -> None:
        """Two conflict reports in one error -- both canonical URLs rendered."""
        report1 = CanonicalUrlConflictReport(
            canonical_url="https://gitserver/org/pkg-a",
            entries=[
                ResolvedProject("src-a/m.xml", "git@gitserver:org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_A),
                ResolvedProject(
                    "src-b/m.xml", "https://gitserver/org/pkg-a.git", "https://gitserver/org/pkg-a", _SHA_B
                ),
            ],
        )
        report2 = CanonicalUrlConflictReport(
            canonical_url="https://gitserver/org/pkg-b",
            entries=[
                ResolvedProject("src-c/m.xml", "git@gitserver:org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_A),
                ResolvedProject(
                    "src-d/m.xml", "https://gitserver/org/pkg-b.git", "https://gitserver/org/pkg-b", _SHA_C
                ),
            ],
        )
        err = CanonicalUrlConflictError(reports=[report1, report2])
        msg = str(err)
        assert "https://gitserver/org/pkg-a" in msg
        assert "https://gitserver/org/pkg-b" in msg


# ---------------------------------------------------------------------------
# CanonicalUrlConflictReport NamedTuple shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCanonicalUrlConflictReport:
    def test_fields_accessible_by_name(self) -> None:
        report = CanonicalUrlConflictReport(
            canonical_url=_CANONICAL,
            entries=[],
        )
        assert report.canonical_url == _CANONICAL
        assert report.entries == []

    def test_entries_is_list_of_resolved_projects(self) -> None:
        entry = ResolvedProject(
            source_path="src/manifest.xml",
            raw_url="git@gitserver:org/pkg.git",
            canonical_url=_CANONICAL,
            resolved_sha=_SHA_A,
        )
        report = CanonicalUrlConflictReport(canonical_url=_CANONICAL, entries=[entry])
        assert len(report.entries) == 1
        assert report.entries[0].source_path == "src/manifest.xml"


# ---------------------------------------------------------------------------
# ResolvedProject NamedTuple shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvedProject:
    def test_fields_accessible_by_name(self) -> None:
        p = ResolvedProject(
            source_path="src-a/manifest.xml",
            raw_url="git@gitserver:org/pkg.git",
            canonical_url=_CANONICAL,
            resolved_sha=_SHA_A,
        )
        assert p.source_path == "src-a/manifest.xml"
        assert p.raw_url == "git@gitserver:org/pkg.git"
        assert p.canonical_url == _CANONICAL
        assert p.resolved_sha == _SHA_A
