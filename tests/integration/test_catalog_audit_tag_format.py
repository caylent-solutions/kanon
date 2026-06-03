"""Integration tests for kanon catalog audit --check tag-format (soft-spot rule 5).

Drives the full CLI as a subprocess against a real fixture git repo
seeded with mixed PEP 440 and non-PEP-440 tags.

AC-TEST-002: Integration test running against a real fixture git server with mixed tags.
AC-CYCLE-001: End-to-end cycle:
  - Repo tagged with 1.0.0, v1.0.0, subpackage/2.0.0, release-2024.
  - Exit 0 (warnings only, no errors).
  - Exactly two WARN findings: for v1.0.0 and release-2024.
  - Zero findings for 1.0.0 (PEP 440) and subpackage/2.0.0 (monorepo PEP 440).

AC-TEST-001 (gap 4b): TestT001PeeledRefs exercises peeled-ref filtering.
  - Repo contains annotated tags (which produce ^{} peeled lines in git ls-remote output)
    plus lightweight malformed tags.
  - T001 fires for malformed tags and NOT for peeled refs.
  - Peeled refs do not duplicate or mask findings.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Git helper utilities
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _create_fixture_git_repo(base: pathlib.Path, tags: list[str]) -> pathlib.Path:
    """Create a local git repo with repo-specs/ and the given tags.

    Creates one marketplace XML file under repo-specs/ (so the audit target
    is a valid manifest repo), commits it, and then creates each tag listed
    in ``tags`` on that commit.

    Args:
        base: Parent directory under which the work dir is created.
        tags: Tag names to create on the initial commit.

    Returns:
        Absolute path to the created git repo directory.
    """
    repo_dir = base / "fixture-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(repo_dir)

    repo_specs = repo_dir / "repo-specs"
    repo_specs.mkdir()

    # Write a minimal marketplace XML so the directory is a valid audit target.
    xml_content = """\
<?xml version="1.0"?>
<manifest>
  <catalog-metadata>
    <name>fixture-tool</name>
    <display-name>Fixture Tool</display-name>
    <description>Fixture tool for tag-format integration test.</description>
    <version>1.0.0</version>
    <type>plugin</type>
    <owner-name>Test Author</owner-name>
    <owner-email>author@example.com</owner-email>
    <keywords>test,fixture</keywords>
  </catalog-metadata>
</manifest>
"""
    (repo_specs / "fixture-marketplace.xml").write_text(xml_content, encoding="utf-8")

    _git(["add", "."], cwd=repo_dir)
    _git(["commit", "-m", "initial commit"], cwd=repo_dir)

    for tag in tags:
        _git(["tag", tag], cwd=repo_dir)

    return repo_dir


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI as a subprocess and return the CompletedProcess result."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCatalogAuditTagFormatSubprocess:
    """End-to-end subprocess tests for --check tag-format against a real fixture git repo."""

    def test_exit_code_0_for_mixed_tag_repo(self, tmp_path: pathlib.Path) -> None:
        """kanon catalog audit --check tag-format exits 0 (warnings only, no errors).

        AC-CYCLE-001 and AC-FUNC-010.
        """
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_v1_0_0_warn_appears(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for v1.0.0 appears in output. AC-CYCLE-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "v1.0.0" in result.stdout, f"Expected 'v1.0.0' in stdout WARN finding.\nstdout: {result.stdout}"

    def test_release_2024_warn_appears(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for release-2024 appears in output. AC-CYCLE-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "release-2024" in result.stdout, (
            f"Expected 'release-2024' in stdout WARN finding.\nstdout: {result.stdout}"
        )

    def test_exactly_two_warn_findings_for_ac_cycle_001_fixture(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: exactly two WARN lines for the given fixture tags.

        Tags 1.0.0 and subpackage/2.0.0 are PEP 440 => zero findings.
        Tags v1.0.0 and release-2024 are non-PEP-440 canonical => two WARNs.
        """
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        assert len(warn_lines) == 2, (
            f"AC-CYCLE-001: expected exactly 2 WARN lines, got {len(warn_lines)}.\nstdout:\n{result.stdout}"
        )

    def test_no_error_prefix_in_output(self, tmp_path: pathlib.Path) -> None:
        """No ERROR: lines appear (tag-format check is warnings-only per spec 0.4)."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "ERROR:" not in result.stdout, f"Expected no ERROR: lines (only WARNs), got:\n{result.stdout}"

    def test_pep440_only_repo_produces_no_output(self, tmp_path: pathlib.Path) -> None:
        """A repo with only PEP 440 tags produces no findings and no stdout output."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "2.10.1", "2026.4.1"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 for PEP 440-only repo, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "", f"Expected empty stdout for PEP 440-only repo, got:\n{result.stdout}"

    def test_no_tag_repo_produces_no_output(self, tmp_path: pathlib.Path) -> None:
        """A repo with no tags produces no findings."""
        repo = _create_fixture_git_repo(tmp_path, tags=[])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 for no-tag repo, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "", f"Expected empty stdout for no-tag repo, got:\n{result.stdout}"

    def test_1_0_0_tag_produces_no_warn(self, tmp_path: pathlib.Path) -> None:
        """PEP 440 tag 1.0.0 does not appear in WARN findings. AC-FUNC-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        # 1.0.0 should NOT appear in a "WARN" line -- only WARN for non-PEP-440 tags.
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        for line in warn_lines:
            # Check that '1.0.0' is only referenced as part of 'v1.0.0' or
            # 'subpackage/2.0.0', not as the plain PEP 440 tag itself.
            assert "WARN:" not in line or "v1.0.0" in line or "release-2024" in line, (
                f"Unexpected WARN line content: {line!r}"
            )

    def test_subpackage_2_0_0_tag_produces_no_warn(self, tmp_path: pathlib.Path) -> None:
        """Monorepo-prefixed PEP 440 tag subpackage/2.0.0 produces no finding. AC-FUNC-004."""
        repo = _create_fixture_git_repo(tmp_path, tags=["subpackage/2.0.0"])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0
        assert result.stdout.strip() == "", f"Expected empty stdout for monorepo PEP 440 tag, got:\n{result.stdout}"

    def test_warn_prefix_present_for_non_pep440_tag(self, tmp_path: pathlib.Path) -> None:
        """At least one WARN: line appears for a repo with non-PEP-440 tags."""
        repo = _create_fixture_git_repo(tmp_path, tags=["v1.0.0"])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "WARN:" in result.stdout, (
            f"Expected at least one WARN: line.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_check_not_run_when_different_check_selected(self, tmp_path: pathlib.Path) -> None:
        """Running --check metadata does not run tag-format logic (no T001 codes)."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "metadata"])
        assert "T001" not in result.stdout, (
            f"Expected no T001 code when --check metadata is used.\nstdout: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# Annotated-tag fixture (produces peeled ^{} refs in git ls-remote output)
# ---------------------------------------------------------------------------


def _create_fixture_git_repo_with_annotated_tags(
    base: pathlib.Path,
    annotated_tags: list[str],
    lightweight_tags: list[str],
) -> pathlib.Path:
    """Create a fixture git repo containing both annotated and lightweight tags.

    Annotated tags produce a peeled ``^{}`` line in ``git ls-remote --tags``
    output in addition to the tag-object line.  Lightweight tags produce a
    single line.  The repo has a ``repo-specs/`` directory so it is a valid
    audit target.

    Args:
        base: Parent directory under which the repo directory is created.
        annotated_tags: Tag names to create as annotated tags (``git tag -a``).
        lightweight_tags: Tag names to create as lightweight tags (``git tag``).

    Returns:
        Absolute path to the created git repo directory.
    """
    repo_dir = base / "fixture-repo-annotated"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(repo_dir)

    repo_specs = repo_dir / "repo-specs"
    repo_specs.mkdir()

    xml_content = """\
<?xml version="1.0"?>
<manifest>
  <catalog-metadata>
    <name>fixture-tool</name>
    <display-name>Fixture Tool</display-name>
    <description>Fixture tool for peeled-ref integration test.</description>
    <version>1.0.0</version>
    <type>plugin</type>
    <owner-name>Test Author</owner-name>
    <owner-email>author@example.com</owner-email>
    <keywords>test,fixture</keywords>
  </catalog-metadata>
</manifest>
"""
    (repo_specs / "fixture-marketplace.xml").write_text(xml_content, encoding="utf-8")

    _git(["add", "."], cwd=repo_dir)
    _git(["-c", "core.hooksPath=/dev/null", "commit", "-m", "initial commit"], cwd=repo_dir)

    for tag in annotated_tags:
        _git(["tag", "-a", tag, "-m", f"annotated tag {tag}"], cwd=repo_dir)

    for tag in lightweight_tags:
        _git(["tag", tag], cwd=repo_dir)

    return repo_dir


# ---------------------------------------------------------------------------
# TestT001PeeledRefs (AC-TEST-001, gap 4b)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestT001PeeledRefs:
    """T001 filters peeled ^{} refs and fires on malformed tags (gap 4b).

    AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-TEST-001.
    """

    def test_t001_ignores_peeled_refs_and_fires_on_malformed(self, tmp_path: pathlib.Path) -> None:
        """T001 fires for malformed tags and ignores peeled ^{} ref lines.

        Tag set: v1.0.0 (annotated -- non-canonical, peeled ref produced),
                 1.0 (annotated -- canonical PEP 440, peeled ref produced),
                 badtag (lightweight -- malformed, no peeled ref).

        Expected: exactly two T001 WARN findings: one for 'v1.0.0' and one for
        'badtag'. The peeled refs for v1.0.0 and 1.0 must not produce extra
        findings. AC-FUNC-002, AC-FUNC-003, AC-TEST-001.
        """
        repo = _create_fixture_git_repo_with_annotated_tags(
            tmp_path,
            annotated_tags=["v1.0.0", "1.0"],
            lightweight_tags=["badtag"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        assert len(warn_lines) == 2, (
            f"Expected exactly 2 WARN findings (v1.0.0, badtag); peeled refs must not produce "
            f"extra findings. Got {len(warn_lines)} WARNs:\n{result.stdout}"
        )
        messages = " ".join(warn_lines)
        assert "v1.0.0" in messages, f"Expected T001 finding for 'v1.0.0' in WARN lines.\nstdout: {result.stdout}"
        assert "badtag" in messages, f"Expected T001 finding for 'badtag' in WARN lines.\nstdout: {result.stdout}"
        # Peeled ref suffix must NOT appear in any finding -- it was filtered before parsing.
        assert "^{}" not in result.stdout, (
            f"Peeled ref '^{{}}' must not appear in any T001 finding.\nstdout: {result.stdout}"
        )

    def test_t001_only_peeled_refs_no_malformed_yields_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """A tag set with only annotated PEP 440 tags yields 0 T001 findings.

        Annotated PEP 440 tags produce peeled ^{} lines in ls-remote output.
        Those peeled lines must be filtered and must not generate T001 findings.
        AC-FUNC-004, AC-FUNC-003.
        """
        repo = _create_fixture_git_repo_with_annotated_tags(
            tmp_path,
            annotated_tags=["1.0.0", "2.0.0"],
            lightweight_tags=[],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 for all-PEP-440 annotated tags, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "", (
            f"Expected empty stdout (0 findings) for annotated PEP 440 tags.\nstdout: {result.stdout}"
        )

    def test_t001_annotated_non_pep440_fires_once_not_twice(self, tmp_path: pathlib.Path) -> None:
        """An annotated non-PEP-440 tag produces exactly one T001 finding (not two).

        Without peeled-ref filtering, an annotated tag v1.0.0 would produce two
        T001 findings: one for 'v1.0.0' and one for 'v1.0.0^{}'. After the fix,
        only one finding appears. AC-FUNC-003.
        """
        repo = _create_fixture_git_repo_with_annotated_tags(
            tmp_path,
            annotated_tags=["v1.0.0"],
            lightweight_tags=[],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        assert len(warn_lines) == 1, (
            f"Annotated non-PEP-440 tag must produce exactly one T001 finding (not two via "
            f"duplicate peeled ref). Got {len(warn_lines)} WARNs:\n{result.stdout}"
        )
        assert "v1.0.0" in warn_lines[0], f"Expected 'v1.0.0' in the single T001 WARN finding.\nstdout: {result.stdout}"


# ---------------------------------------------------------------------------
# TestT001MalformedTagFixture (AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004)
# Spec Goal G2: fixture with {v1.0.0, 1.0, BADTAG, v1.0.0^{}} proves T001 fires
# on genuinely-malformed tags and ignores peeled refs.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestT001MalformedTagFixture:
    """T001 fires on genuinely-malformed tags and ignores peeled ^{} refs (spec Goal G2).

    Fixture tag set: v1.0.0 (annotated, non-canonical -- T001 fires),
                     1.0 (annotated, canonical PEP 440 -- no T001),
                     BADTAG (lightweight, non-PEP-440 -- T001 fires).
    The annotated tags produce peeled v1.0.0^{} and 1.0^{} lines in
    git ls-remote output; those peeled refs must be ignored by T001.

    AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, E52-F2, spec Goal G2.
    """

    def test_t001_fires_on_both_malformed_tags(self, tmp_path: pathlib.Path) -> None:
        """T001 fires for v1.0.0 and BADTAG from the spec Goal G2 fixture.

        Tag set mirrors spec Goal G2: {v1.0.0, 1.0, BADTAG, v1.0.0^{}}.
        The peeled ref v1.0.0^{} is produced automatically by git for the
        annotated v1.0.0 tag.

        Expected: exactly two T001 WARN findings: one for 'v1.0.0' and one for
        'BADTAG'. The PEP 440 tag '1.0' and the peeled refs produce no findings.

        AC-FUNC-001, AC-FUNC-002.
        """
        repo = _create_fixture_git_repo_with_annotated_tags(
            tmp_path,
            annotated_tags=["v1.0.0", "1.0"],
            lightweight_tags=["BADTAG"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        assert len(warn_lines) == 2, (
            f"AC-FUNC-001/G2: expected exactly 2 WARN findings (v1.0.0, BADTAG); "
            f"peeled refs and PEP 440 tags must produce no findings. "
            f"Got {len(warn_lines)} WARNs:\n{result.stdout}"
        )
        messages = " ".join(warn_lines)
        assert "v1.0.0" in messages, (
            f"AC-FUNC-002: expected T001 finding for 'v1.0.0' in WARN lines.\nstdout: {result.stdout}"
        )
        assert "BADTAG" in messages, (
            f"AC-FUNC-002: expected T001 finding for 'BADTAG' in WARN lines.\nstdout: {result.stdout}"
        )

    def test_t001_ignores_peeled_refs_in_goal_g2_fixture(self, tmp_path: pathlib.Path) -> None:
        """No T001 finding message contains '^{}' from the spec Goal G2 fixture.

        The annotated tag v1.0.0 produces a 'v1.0.0^{}' peeled line in
        git ls-remote output. That line must be filtered before T001 inspection
        so no finding message contains '^{}'.

        AC-FUNC-002: peeled-refs-ignored assertion.
        """
        repo = _create_fixture_git_repo_with_annotated_tags(
            tmp_path,
            annotated_tags=["v1.0.0", "1.0"],
            lightweight_tags=["BADTAG"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "^{}" not in result.stdout, (
            f"AC-FUNC-002: peeled ref '^{{}}' must not appear in any T001 finding "
            f"(peeled refs must be filtered before T001 inspection).\nstdout: {result.stdout}"
        )
