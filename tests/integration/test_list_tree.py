"""Integration tests for 'kanon list --tree'.

Builds temporary local file:// manifest-repo fixtures (committed git repos
with *-marketplace.xml files) and invokes 'kanon list --tree --catalog-source
<file>@<ref>' via subprocess.run.

Covers three threshold scenarios per AC-TEST-002:
1. Smaller-than-threshold (3 entries): no filter needed -- exits 0.
2. Exactly-threshold (20 entries): no filter needed -- exits 0.
3. Larger-than-threshold (25 entries): filter required -- exits non-zero.

Also covers AC-CYCLE-001:
- 25-entry repo + 'kanon list --tree' -> non-zero with guardrail message.
- 25-entry repo + KANON_TREE_NO_FILTER_THRESHOLD=30 -> exits 0.
- 25-entry repo + --no-filter-required -> exits 0.
- 25-entry repo + --max-depth 0 -> exits 0, one root-only line per entry.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from kanon_cli.constants import KANON_TREE_NO_FILTER_THRESHOLD


# ---------------------------------------------------------------------------
# Git helper constants and utilities (independent copies, not shared)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


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


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_manifest_repo(
    base: pathlib.Path,
    entry_names: list[str],
    dir_suffix: str = "manifest",
) -> pathlib.Path:
    """Create a bare manifest repo with *-marketplace.xml files under repo-specs/.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_names: Catalog entry names. Each gets a marketplace XML.
        dir_suffix: Suffix to make unique work/bare dir names in the same base.

    Returns:
        The absolute path to the bare repo.
    """
    work_dir = base / f"{dir_suffix}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{dir_suffix}-bare.git")
    return bare_dir


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after 'kanon' (e.g. ["list", "--tree", ...]).
        extra_env: Extra environment variables to set (merged onto os.environ).

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Helper: generate N distinct entry names
# ---------------------------------------------------------------------------


def _entry_names(count: int) -> list[str]:
    """Return ``count`` distinct entry names formatted as 'entry-NNN'."""
    return [f"entry-{i:03d}" for i in range(count)]


# ---------------------------------------------------------------------------
# Scenario 1: smaller-than-threshold (3 entries)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListTreeBelowThreshold:
    """kanon list --tree with a 3-entry catalog (below threshold): exits 0."""

    def test_exits_0_with_max_depth_0(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree --max-depth 0 exits 0 for a 3-entry catalog."""
        bare = _create_manifest_repo(tmp_path, _entry_names(3), dir_suffix="small")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for 3-entry catalog with --max-depth 0; "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_stdout_has_three_entry_lines_with_max_depth_0(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree --max-depth 0 produces three root-only lines for 3 entries."""
        names = _entry_names(3)
        bare = _create_manifest_repo(tmp_path, names, dir_suffix="small-out")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        # Each entry produces one root line (max-depth 0 = root only)
        entry_lines = [ln for ln in lines if ln.startswith("entry ")]
        assert len(entry_lines) == 3, (
            f"Expected 3 'entry ...' root lines for 3-entry catalog; got {len(entry_lines)}: {lines!r}"
        )

    def test_no_filter_needed_below_threshold(self, tmp_path: pathlib.Path) -> None:
        """3-entry catalog does not require a filter; exits 0 without --no-filter-required."""
        bare = _create_manifest_repo(tmp_path, _entry_names(3), dir_suffix="small-no-filter")
        catalog_source = f"file://{bare}@main"

        # No filter flags passed; catalog size is below threshold so guardrail must not fire
        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, f"Guardrail fired unexpectedly for 3-entry catalog.\n  stderr: {result.stderr!r}"
        assert "ERROR:" not in result.stderr, f"No ERROR: expected for 3-entry catalog; got: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Scenario 2: exactly-threshold entries
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListTreeAtThreshold:
    """kanon list --tree with exactly KANON_TREE_NO_FILTER_THRESHOLD entries: exits 0."""

    def test_exits_0_at_threshold(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree exits 0 when catalog has exactly threshold entries."""
        count = KANON_TREE_NO_FILTER_THRESHOLD
        bare = _create_manifest_repo(tmp_path, _entry_names(count), dir_suffix="at-threshold")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for exactly {count} entries; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_no_error_at_threshold(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree writes no ERROR: to stderr at exactly threshold entries."""
        count = KANON_TREE_NO_FILTER_THRESHOLD
        bare = _create_manifest_repo(tmp_path, _entry_names(count), dir_suffix="at-threshold-err")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "ERROR:" not in result.stderr, f"No ERROR: expected at exactly {count} entries; got: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Scenario 3: larger-than-threshold (AC-TEST-002, AC-CYCLE-001)
# ---------------------------------------------------------------------------

_OVER_THRESHOLD = KANON_TREE_NO_FILTER_THRESHOLD + 5  # 25 when threshold is 20


@pytest.mark.integration
class TestListTreeOverThreshold:
    """kanon list --tree with > threshold entries and no filter: exits non-zero."""

    def test_exits_nonzero_over_threshold(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree exits non-zero when catalog > threshold and no filter given.

        AC-CYCLE-001 evidence: 25-entry repo, no filter, expect non-zero exit.
        """
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for {_OVER_THRESHOLD}-entry catalog with no filter; "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_stderr_contains_error_over_threshold(self, tmp_path: pathlib.Path) -> None:
        """kanon list --tree writes ERROR: to stderr when guardrail fires."""
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-err")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "ERROR:" in result.stderr, f"Expected ERROR: in stderr for guardrail; got: {result.stderr!r}"

    def test_env_override_raises_threshold(self, tmp_path: pathlib.Path) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD=30 env override allows 25-entry catalog.

        AC-CYCLE-001 evidence: re-run with threshold override; expect exit 0.
        """
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-env")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={
                "KANON_ALLOW_INSECURE_REMOTES": "1",
                "KANON_TREE_NO_FILTER_THRESHOLD": "30",
            },
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with KANON_TREE_NO_FILTER_THRESHOLD=30 for {_OVER_THRESHOLD} entries; "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_no_filter_required_bypasses_guardrail(self, tmp_path: pathlib.Path) -> None:
        """--no-filter-required bypasses guardrail for 25-entry catalog.

        AC-CYCLE-001 evidence: re-run with --no-filter-required; expect exit 0.
        """
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-nfr")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            [
                "list",
                "--tree",
                "--no-filter-required",
                "--max-depth",
                "0",
                "--catalog-source",
                catalog_source,
            ],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with --no-filter-required for {_OVER_THRESHOLD} entries; "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_max_depth_0_bypasses_guardrail(self, tmp_path: pathlib.Path) -> None:
        """--max-depth 0 counts as a filter and bypasses guardrail for 25-entry catalog.

        AC-CYCLE-001 evidence: re-run with --max-depth 0; expect exit 0 and one root line per entry.
        """
        count = _OVER_THRESHOLD
        bare = _create_manifest_repo(tmp_path, _entry_names(count), dir_suffix="over-md0")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--max-depth", "0", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with --max-depth 0 for {count} entries; "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        entry_lines = [ln for ln in result.stdout.splitlines() if ln.strip().startswith("entry ")]
        assert len(entry_lines) == count, (
            f"Expected {count} 'entry ...' root lines (one per entry); got {len(entry_lines)}: {result.stdout!r}"
        )

    def test_guardrail_error_names_threshold_value(self, tmp_path: pathlib.Path) -> None:
        """Guardrail error message names the threshold value (AC-FUNC-004)."""
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-thresh")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert str(KANON_TREE_NO_FILTER_THRESHOLD) in result.stderr, (
            f"Guardrail message must name threshold ({KANON_TREE_NO_FILTER_THRESHOLD}); got: {result.stderr!r}"
        )

    def test_guardrail_error_names_actual_count(self, tmp_path: pathlib.Path) -> None:
        """Guardrail error message names the actual entry count (AC-FUNC-004)."""
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-count")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert str(_OVER_THRESHOLD) in result.stderr, (
            f"Guardrail message must name actual count ({_OVER_THRESHOLD}); got: {result.stderr!r}"
        )

    def test_guardrail_error_suggests_no_filter_required(self, tmp_path: pathlib.Path) -> None:
        """Guardrail error suggests --no-filter-required as a resolution path."""
        bare = _create_manifest_repo(tmp_path, _entry_names(_OVER_THRESHOLD), dir_suffix="over-suggest")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["list", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "--no-filter-required" in result.stderr, (
            f"Guardrail message must suggest --no-filter-required; got: {result.stderr!r}"
        )
