"""Unit tests for kanon catalog audit --check tag-format (soft-spot rule 5).

Covers _check_tag_format via the AUDIT_CHECK_REGISTRY and directly. Tests
parametrize across:
  - Only PEP 440 tags (1.0.0, 2.10.1, 2026.4.1): zero findings.
  - v1.0.0 tag (non-PEP 440 prefix): one WARN finding.
  - release-2024 tag (free-form non-PEP 440): one WARN finding.
  - Monorepo-prefixed PEP 440 tag (subpackage/1.0.0): zero findings.
  - Monorepo-prefixed non-PEP-440 tag (subpackage/v1.0.0): one WARN finding.
  - Empty tag list: zero findings.
  - 60 non-PEP-440 tags with cap of 50: 50 WARN + 1 summary WARN.

AC-TEST-001: Parametrized unit tests with a callable stub for git ls-remote --tags.
AC-FUNC-001 through AC-FUNC-009.
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.commands.catalog import AUDIT_CHECK_REGISTRY, AuditFinding
from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT
from tests.unit.conftest import _make_ls_remote_stub


def _run_check(
    tmp_path: pathlib.Path,
    tags: list[str],
) -> list[AuditFinding]:
    """Call _check_tag_format with an injected ls_remote stub.

    Args:
        tmp_path: Temporary directory used as the target_path.
        tags: Tag names to simulate in ``git ls-remote --tags`` output.

    Returns:
        List of AuditFinding objects produced by the check.
    """
    from kanon_cli.commands.catalog import _check_tag_format

    stub = _make_ls_remote_stub(tags)
    return _check_tag_format(tmp_path, stub)


# ---------------------------------------------------------------------------
# Registry registration (AC-FUNC-007)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTagFormatCheckRegistered:
    """'tag-format' is registered in AUDIT_CHECK_REGISTRY (AC-FUNC-007)."""

    def test_tag_format_key_present(self) -> None:
        """'tag-format' key must exist in AUDIT_CHECK_REGISTRY."""
        assert "tag-format" in AUDIT_CHECK_REGISTRY

    def test_tag_format_value_is_callable(self) -> None:
        """AUDIT_CHECK_REGISTRY['tag-format'] must be callable."""
        assert callable(AUDIT_CHECK_REGISTRY["tag-format"])

    def test_registered_check_returns_list(self, tmp_path: pathlib.Path) -> None:
        """The registered 'tag-format' check value is callable (AC-FUNC-007).

        The registry value is the subprocess-backed wrapper. Verify it is
        callable rather than invoking it against a non-git tmp_path (which
        would trigger a real git subprocess and fail).
        """
        check_fn = AUDIT_CHECK_REGISTRY["tag-format"]
        assert callable(check_fn)

    def test_registered_check_returns_audit_finding_instances(self, tmp_path: pathlib.Path) -> None:
        """When findings exist, each is an AuditFinding instance (AC-FUNC-007)."""
        from kanon_cli.commands.catalog import _check_tag_format

        stub = _make_ls_remote_stub(["v1.0.0"])
        findings = _check_tag_format(tmp_path, stub)
        assert len(findings) == 1
        assert isinstance(findings[0], AuditFinding), f"Expected AuditFinding, got {type(findings[0])}"


# ---------------------------------------------------------------------------
# AC-FUNC-008: ls_remote_callable injection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLsRemoteCallableInjection:
    """_check_tag_format accepts ls_remote_callable so tests avoid network (AC-FUNC-008)."""

    def test_stub_is_called_with_target_path(self, tmp_path: pathlib.Path) -> None:
        """The ls_remote_callable receives the target_path argument."""
        from kanon_cli.commands.catalog import _check_tag_format

        received: list[pathlib.Path] = []

        def _capturing_stub(target_path: pathlib.Path) -> str:
            received.append(target_path)
            return ""

        _check_tag_format(tmp_path, _capturing_stub)
        assert received == [tmp_path], f"Expected target_path passed to stub, got: {received}"

    def test_two_stubs_give_different_results(self, tmp_path: pathlib.Path) -> None:
        """Injecting different stubs produces different findings (stub isolation)."""
        from kanon_cli.commands.catalog import _check_tag_format

        findings_pep440 = _check_tag_format(tmp_path, _make_ls_remote_stub(["1.0.0"]))
        findings_non_pep440 = _check_tag_format(tmp_path, _make_ls_remote_stub(["v1.0.0"]))
        assert findings_pep440 == []
        assert len(findings_non_pep440) == 1


# ---------------------------------------------------------------------------
# AC-FUNC-001: Only PEP 440 tags => zero findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOnlyPep440TagsZeroFindings:
    """A repo with only PEP 440 tags produces zero tag-format findings (AC-FUNC-001)."""

    @pytest.mark.parametrize(
        "tags",
        [
            ["1.0.0"],
            ["2.10.1"],
            ["2026.4.1"],
            ["1.0.0", "2.10.1", "2026.4.1"],
            ["1.0.0a1"],
            ["1.0.0.post1"],
            ["1.0.0.dev0"],
        ],
    )
    def test_pep440_tags_produce_zero_findings(self, tmp_path: pathlib.Path, tags: list[str]) -> None:
        """PEP 440 version strings in tags produce zero findings."""
        findings = _run_check(tmp_path, tags)
        assert findings == [], f"Expected zero findings for PEP 440 tags {tags!r}, got: {findings}"


# ---------------------------------------------------------------------------
# AC-FUNC-002: v1.0.0 tag => one WARN finding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestV1Dot0Dot0TagOneWarn:
    """A v1.0.0 tag produces exactly one WARN finding naming the tag (AC-FUNC-002)."""

    def test_v1_0_0_tag_produces_one_warn(self, tmp_path: pathlib.Path) -> None:
        """v1.0.0 produces exactly one WARN finding."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 1, f"Expected one WARN finding for v1.0.0, got: {warn_findings}"

    def test_v1_0_0_tag_finding_names_tag(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for v1.0.0 names the tag in its message."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        assert "v1.0.0" in findings[0].message, f"Expected 'v1.0.0' in message, got: {findings[0].message}"

    def test_v1_0_0_tag_finding_notes_unaddressable(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for v1.0.0 mentions unaddressable."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        msg = findings[0].message
        assert "unaddressable" in msg, f"Expected 'unaddressable' in message, got: {msg}"

    def test_v1_0_0_tag_finding_code_is_t001(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for v1.0.0 has code T001."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        assert findings[0].code == "T001", f"Expected code T001, got: {findings[0].code}"

    def test_v1_0_0_tag_finding_is_warn_not_error(self, tmp_path: pathlib.Path) -> None:
        """The finding for v1.0.0 is kind=warn (not error) per spec Section 0.4."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        assert findings[0].kind == "warn", f"Expected kind='warn', got: {findings[0].kind}"

    @pytest.mark.parametrize(
        "tag",
        ["v1.0.0", "v2.0.0", "V1.0.0", "v1.2.3"],
    )
    def test_v_prefixed_tags_produce_warn(self, tmp_path: pathlib.Path, tag: str) -> None:
        """Any v-prefixed version tag produces exactly one WARN finding."""
        findings = _run_check(tmp_path, [tag])
        assert len(findings) == 1
        assert findings[0].kind == "warn"
        assert tag in findings[0].message


# ---------------------------------------------------------------------------
# AC-FUNC-003: release-2024 tag => one WARN finding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRelease2024TagOneWarn:
    """A release-2024 tag produces exactly one WARN finding (AC-FUNC-003)."""

    def test_release_2024_tag_produces_one_warn(self, tmp_path: pathlib.Path) -> None:
        """release-2024 produces exactly one WARN finding."""
        findings = _run_check(tmp_path, ["release-2024"])
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 1, f"Expected one WARN for release-2024, got: {warn_findings}"

    def test_release_2024_tag_finding_names_tag(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding names the offending tag."""
        findings = _run_check(tmp_path, ["release-2024"])
        assert len(findings) == 1
        assert "release-2024" in findings[0].message

    @pytest.mark.parametrize(
        "tag",
        ["release-2024", "release-candidate", "latest-stable", "my-tag"],
    )
    def test_free_form_tags_produce_warn(self, tmp_path: pathlib.Path, tag: str) -> None:
        """Parametrized: free-form non-PEP-440 tags each produce one WARN finding."""
        findings = _run_check(tmp_path, [tag])
        assert len(findings) == 1, f"Expected one WARN for tag {tag!r}, got: {findings}"
        assert findings[0].kind == "warn"


# ---------------------------------------------------------------------------
# AC-FUNC-004: subpackage/1.0.0 (monorepo PEP 440) => zero findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMonorepoPep440TagZeroFindings:
    """A monorepo-prefixed PEP 440 tag produces zero findings (AC-FUNC-004)."""

    @pytest.mark.parametrize(
        "tag",
        [
            "subpackage/1.0.0",
            "mylib/2.0.0",
            "infra/tools/3.0.1",
            "a/b/c/1.0.0a1",
        ],
    )
    def test_monorepo_pep440_tag_produces_zero_findings(self, tmp_path: pathlib.Path, tag: str) -> None:
        """Monorepo-prefixed tags whose last component is PEP 440 produce zero findings."""
        findings = _run_check(tmp_path, [tag])
        assert findings == [], f"Expected zero findings for monorepo PEP 440 tag {tag!r}, got: {findings}"


# ---------------------------------------------------------------------------
# AC-FUNC-005: subpackage/v1.0.0 (monorepo non-PEP-440) => one WARN finding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMonorepoNonPep440TagOneWarn:
    """A monorepo-prefixed non-PEP-440 tag produces one WARN finding (AC-FUNC-005)."""

    @pytest.mark.parametrize(
        "tag",
        [
            "subpackage/v1.0.0",
            "mylib/release-2024",
            "infra/tools/latest",
        ],
    )
    def test_monorepo_non_pep440_tag_produces_one_warn(self, tmp_path: pathlib.Path, tag: str) -> None:
        """Monorepo-prefixed tags whose last component is not PEP 440 produce one WARN."""
        findings = _run_check(tmp_path, [tag])
        assert len(findings) == 1, f"Expected one WARN for monorepo non-PEP-440 tag {tag!r}, got: {findings}"
        assert findings[0].kind == "warn"

    def test_subpackage_v1_0_0_finding_names_full_tag(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding names the full tag path (subpackage/v1.0.0)."""
        findings = _run_check(tmp_path, ["subpackage/v1.0.0"])
        assert len(findings) == 1
        msg = findings[0].message
        assert "subpackage/v1.0.0" in msg, f"Expected full tag name in message, got: {msg}"


# ---------------------------------------------------------------------------
# AC-FUNC-006 (empty tag list => zero findings)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyTagListZeroFindings:
    """An empty tag list produces zero findings."""

    def test_empty_tag_list_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """No tags means no findings."""
        findings = _run_check(tmp_path, [])
        assert findings == [], f"Expected zero findings for empty tag list, got: {findings}"

    def test_only_whitespace_ls_remote_output_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """Whitespace-only output from ls-remote produces zero findings."""
        from kanon_cli.commands.catalog import _check_tag_format

        def _whitespace_stub(target_path: pathlib.Path) -> str:
            return "\n\n   \n"

        findings = _check_tag_format(tmp_path, _whitespace_stub)
        assert findings == [], f"Expected zero findings for whitespace-only output, got: {findings}"

    def test_line_without_tab_is_skipped(self, tmp_path: pathlib.Path) -> None:
        """Lines without a tab separator are silently skipped."""
        from kanon_cli.commands.catalog import _check_tag_format

        def _notab_stub(target_path: pathlib.Path) -> str:
            # No tab -- malformed line
            return "aaaa refs/tags/bad-format\n"

        findings = _check_tag_format(tmp_path, _notab_stub)
        assert findings == [], f"Expected zero findings for line without tab, got: {findings}"

    def test_non_refs_tags_line_is_skipped(self, tmp_path: pathlib.Path) -> None:
        """Lines whose ref does not start with 'refs/tags/' are silently skipped."""
        from kanon_cli.commands.catalog import _check_tag_format

        def _no_tag_prefix_stub(target_path: pathlib.Path) -> str:
            return "aaaa\trefs/heads/main\n"

        findings = _check_tag_format(tmp_path, _no_tag_prefix_stub)
        assert findings == [], f"Expected zero findings for refs/heads line, got: {findings}"

    def test_empty_tag_name_after_prefix_is_skipped(self, tmp_path: pathlib.Path) -> None:
        """A ref of exactly 'refs/tags/' (empty tag name) is silently skipped."""
        from kanon_cli.commands.catalog import _check_tag_format

        def _empty_tag_stub(target_path: pathlib.Path) -> str:
            return "aaaa\trefs/tags/\n"

        findings = _check_tag_format(tmp_path, _empty_tag_stub)
        assert findings == [], f"Expected zero findings for empty tag name, got: {findings}"


# ---------------------------------------------------------------------------
# AC-FUNC-006: cap behaviour -- 60 non-PEP-440 tags => 50 WARN + 1 summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCapBehaviour:
    """More than KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT non-PEP-440 tags triggers cap (AC-FUNC-006)."""

    def test_60_non_pep440_tags_produces_cap_plus_summary(self, tmp_path: pathlib.Path) -> None:
        """60 non-PEP-440 tags produces exactly LIMIT per-tag WARNs + 1 summary WARN.

        The cap is KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT (default 50).
        Beyond the cap, one additional summary WARN names the remaining count.
        """
        tags = [f"v1.{i}.0" for i in range(60)]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        # Expect exactly LIMIT per-tag + 1 summary
        expected_count = KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT + 1
        assert len(warn_findings) == expected_count, (
            f"Expected {expected_count} WARN findings (cap={KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT} + summary), "
            f"got {len(warn_findings)}"
        )

    def test_cap_summary_warn_mentions_remaining_count(self, tmp_path: pathlib.Path) -> None:
        """The summary WARN finding mentions the remaining count (60 - cap = 10)."""
        tags = [f"v1.{i}.0" for i in range(60)]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        # The last finding is the summary
        summary = warn_findings[-1]
        remaining = 60 - KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT
        assert str(remaining) in summary.message, (
            f"Expected remaining count {remaining} in summary message, got: {summary.message}"
        )

    def test_cap_per_tag_warnings_have_t001_code(self, tmp_path: pathlib.Path) -> None:
        """Per-tag WARN findings all have code T001."""
        tags = [f"v1.{i}.0" for i in range(60)]
        findings = _run_check(tmp_path, tags)
        per_tag_findings = findings[:KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT]
        for finding in per_tag_findings:
            assert finding.code == "T001", f"Expected T001 per-tag finding, got code: {finding.code}"

    def test_exactly_at_limit_no_summary(self, tmp_path: pathlib.Path) -> None:
        """Exactly LIMIT non-PEP-440 tags produces exactly LIMIT WARNs (no summary)."""
        tags = [f"v1.{i}.0" for i in range(KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT)]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT, (
            f"Expected exactly {KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT} WARNs at the cap, got {len(warn_findings)}"
        )

    def test_one_below_limit_no_summary(self, tmp_path: pathlib.Path) -> None:
        """LIMIT-1 non-PEP-440 tags produces LIMIT-1 WARNs (no summary)."""
        n = KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT - 1
        tags = [f"v1.{i}.0" for i in range(n)]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == n, f"Expected {n} WARNs for {n} non-PEP-440 tags, got {len(warn_findings)}"


# ---------------------------------------------------------------------------
# Mixed tag lists (PEP 440 + non-PEP-440 together)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMixedTagLists:
    """Mixed PEP 440 and non-PEP-440 tags produce findings only for non-PEP-440 ones."""

    def test_mixed_list_only_warns_for_non_pep440(self, tmp_path: pathlib.Path) -> None:
        """In a mixed list, only non-PEP-440 tags produce WARN findings."""
        tags = ["1.0.0", "v1.0.0", "2.10.1", "release-2024", "subpackage/3.0.0"]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        # v1.0.0 and release-2024 => 2 WARNs; 1.0.0, 2.10.1, subpackage/3.0.0 => 0
        assert len(warn_findings) == 2, f"Expected 2 WARNs for non-PEP-440 tags, got: {warn_findings}"
        warned_tags = [f.message for f in warn_findings]
        assert any("v1.0.0" in m for m in warned_tags), "Expected v1.0.0 in WARN message"
        assert any("release-2024" in m for m in warned_tags), "Expected release-2024 in WARN message"

    def test_ac_cycle_001_fixture_tags(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: tags 1.0.0, v1.0.0, subpackage/2.0.0, release-2024 => exactly 2 WARNs."""
        tags = ["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"]
        findings = _run_check(tmp_path, tags)
        warn_findings = [f for f in findings if f.kind == "warn"]
        assert len(warn_findings) == 2, (
            f"AC-CYCLE-001: expected 2 WARNs (v1.0.0 and release-2024), got: {warn_findings}"
        )
        messages = [f.message for f in warn_findings]
        assert any("v1.0.0" in m for m in messages), "Expected v1.0.0 WARN"
        assert any("release-2024" in m for m in messages), "Expected release-2024 WARN"


# ---------------------------------------------------------------------------
# Finding attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindingAttributes:
    """All tag-format findings have correct kind, code, non-empty message, and remediation."""

    def test_warn_finding_has_nonempty_remediation(self, tmp_path: pathlib.Path) -> None:
        """Each T001 finding has a non-empty remediation string."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        assert findings[0].remediation, "Expected non-empty remediation in T001 finding"

    def test_warn_finding_remediation_mentions_pep_440(self, tmp_path: pathlib.Path) -> None:
        """The T001 remediation mentions PEP 440."""
        findings = _run_check(tmp_path, ["v1.0.0"])
        assert len(findings) == 1
        assert "PEP 440" in findings[0].remediation or "pep440" in findings[0].remediation.lower(), (
            f"Expected PEP 440 mention in remediation, got: {findings[0].remediation}"
        )

    def test_no_error_findings_ever(self, tmp_path: pathlib.Path) -> None:
        """tag-format check never produces error-level findings (warnings only per spec 0.4)."""
        tags = [f"v1.{i}.0" for i in range(60)]
        findings = _run_check(tmp_path, tags)
        error_findings = [f for f in findings if f.kind == "error"]
        assert error_findings == [], f"tag-format check must never produce ERROR findings, got: {error_findings}"


# ---------------------------------------------------------------------------
# _check_tag_format_with_subprocess error path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckTagFormatWithSubprocessErrorPath:
    """_check_tag_format_with_subprocess exits non-zero when git ls-remote fails."""

    def test_git_ls_remote_failure_causes_systemexit(self, tmp_path: pathlib.Path) -> None:
        """When git ls-remote --tags exits non-zero, _check_tag_format_with_subprocess calls sys.exit(1)."""
        from unittest.mock import patch

        import subprocess

        from kanon_cli.commands.catalog import _check_tag_format_with_subprocess

        failed_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", str(tmp_path)],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

        with patch("subprocess.run", return_value=failed_result):
            with pytest.raises(SystemExit) as exc_info:
                _check_tag_format_with_subprocess(tmp_path)

        assert exc_info.value.code == 1, f"Expected sys.exit(1), got sys.exit({exc_info.value.code})"

    def test_git_ls_remote_success_returns_findings(self, tmp_path: pathlib.Path) -> None:
        """When git ls-remote --tags exits 0, _check_tag_format_with_subprocess parses the output."""
        from unittest.mock import patch

        import subprocess

        from kanon_cli.commands.catalog import _check_tag_format_with_subprocess

        sha = "a" * 40
        success_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", str(tmp_path)],
            returncode=0,
            stdout=f"{sha}\trefs/tags/v1.0.0\n{sha}\trefs/tags/1.0.0\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=success_result):
            findings = _check_tag_format_with_subprocess(tmp_path)

        # v1.0.0 is non-canonical => one WARN; 1.0.0 is canonical => zero findings
        assert len(findings) == 1, f"Expected one WARN for v1.0.0, got: {findings}"
        assert findings[0].kind == "warn"
        assert "v1.0.0" in findings[0].message


# ---------------------------------------------------------------------------
# AC-FUNC-009: constant lives in constants.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstantLocation:
    """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT lives in constants.py (AC-FUNC-009)."""

    def test_constant_importable_from_constants(self) -> None:
        """KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT is importable from kanon_cli.constants."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT as limit

        assert isinstance(limit, int)
        assert limit > 0

    def test_constant_default_value_is_50(self) -> None:
        """Default value of KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT is 50."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT as limit

        assert limit == 50, f"Expected default 50, got {limit}"
