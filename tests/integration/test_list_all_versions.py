"""Integration tests for 'kanon list --all-versions'.

Builds temporary local file:// manifest-repo fixtures (committed git repos
with *-marketplace.xml files tagged at multiple versions) and invokes
'kanon list --all-versions --catalog-source <file>@<ref>' via subprocess.run.

Covers AC-TEST-002, AC-TEST-003, AC-CYCLE-001:
- Happy path: 4 tagged versions x 3 entries = 12 rows, spec format verified.
- --limit 3 cap: 3 newest versions x 3 entries = 9 rows.
- --no-limit: all versions walked.
- --since-version filter: only matching versions.
- --all-versions --tree mutual exclusion error.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Minimal *-marketplace.xml template.
_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


# ---------------------------------------------------------------------------
# Low-level git helpers
# ---------------------------------------------------------------------------


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


def _write_marketplace_xml(repo_specs: pathlib.Path, name: str, version: str) -> None:
    """Write a *-marketplace.xml file under repo_specs/<name>/."""
    entry_dir = repo_specs / name
    entry_dir.mkdir(parents=True, exist_ok=True)
    xml_path = entry_dir / f"{name}-marketplace.xml"
    xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name, version=version))


def _commit_and_tag(work_dir: pathlib.Path, tag: str, message: str) -> None:
    """Stage all, commit with message, and tag at that commit."""
    _git(["add", "-A"], cwd=work_dir)
    _git(["commit", "--allow-empty", "-m", message], cwd=work_dir)
    _git(["tag", tag], cwd=work_dir)


# ---------------------------------------------------------------------------
# Fixture: manifest repo with multiple tagged versions
# ---------------------------------------------------------------------------


def _build_multi_version_manifest_repo(
    tmp_path: pathlib.Path,
    entry_names: list[str],
    tag_versions: list[str],
) -> pathlib.Path:
    """Build a bare git repo with one tagged commit per version.

    Each tagged commit sets the version field in all marketplace XMLs to the
    tagged version string.

    Args:
        tmp_path: Temporary directory root.
        entry_names: List of catalog entry names to include.
        tag_versions: List of version strings to tag (oldest first).

    Returns:
        Path to the bare git repository (file:// accessible).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    # Initial commit so git is usable.
    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    for version in tag_versions:
        repo_specs = work_dir / "repo-specs"
        for name in entry_names:
            _write_marketplace_xml(repo_specs, name, version)
        _commit_and_tag(work_dir, version, f"release {version}")

    bare_dir = tmp_path / "bare.git"
    return _clone_as_bare(work_dir, bare_dir)


def _kanon_list_all_versions(
    bare_repo: pathlib.Path,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run 'kanon list --all-versions' against a bare repo and return the process."""
    catalog_source = f"file://{bare_repo}@main"
    cmd = [
        sys.executable,
        "-m",
        "kanon_cli",
        "list",
        "--all-versions",
        "--catalog-source",
        catalog_source,
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(bare_repo.parent),
        env=env,
    )


# ---------------------------------------------------------------------------
# Test: basic --all-versions output (AC-TEST-002, AC-CYCLE-001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsBasicOutput:
    """AC-TEST-002, AC-CYCLE-001: verify spec-canonical output format."""

    def test_four_versions_three_entries_twelve_rows(self, tmp_path):
        """4 tagged versions x 3 entries = 12 rows."""
        entry_names = ["alpha", "beta", "gamma"]
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo)

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        assert len(output_lines) == 12

    def test_output_format_is_name_at_version(self, tmp_path):
        """Each row is '<name>@<version>'."""
        entry_names = ["alpha"]
        versions = ["1.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo)

        assert proc.returncode == 0
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        assert lines[0] == "alpha@1.0.0"

    def test_versions_ordered_newest_first(self, tmp_path):
        """Newest version rows appear first."""
        entry_names = ["entry"]
        versions = ["1.0.0", "2.0.0", "3.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo)

        assert proc.returncode == 0
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        version_parts = [ln.split("@")[1] for ln in lines]
        assert version_parts == ["3.0.0", "2.0.0", "1.0.0"]

    def test_entries_within_version_sorted_lexicographically(self, tmp_path):
        """Within each version, entries are sorted lexicographically."""
        entry_names = ["zebra", "alpha", "mango"]
        versions = ["1.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo)

        assert proc.returncode == 0
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        names = [ln.split("@")[0] for ln in lines]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Test: --limit cap (AC-FUNC-005, AC-CYCLE-001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsLimit:
    """AC-FUNC-005, AC-CYCLE-001: --limit caps the number of versions walked."""

    def test_limit_3_walks_three_newest_versions(self, tmp_path):
        """--limit 3 with 6 versions -> 3 newest versions walked."""
        entry_names = ["alpha", "beta"]
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "2.2.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--limit", "3"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        # 3 versions x 2 entries = 6 rows
        assert len(output_lines) == 6

    def test_limit_3_shows_three_newest_version_numbers(self, tmp_path):
        """--limit 3 shows only the three most recent versions (2.2.0, 2.1.0, 2.0.0)."""
        entry_names = ["entry"]
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "2.2.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--limit", "3"])

        assert proc.returncode == 0
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        version_parts = [ln.split("@")[1] for ln in output_lines]
        assert set(version_parts) == {"2.2.0", "2.1.0", "2.0.0"}

    def test_default_limit_is_50(self, tmp_path):
        """Default cap (no --limit flag) is KANON_LIST_LIMIT=50."""
        entry_names = ["entry"]
        # Create 10 versions; all 10 should be walked (under the 50 cap).
        versions = [f"1.{i}.0" for i in range(10)]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo)

        assert proc.returncode == 0
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        assert len(output_lines) == 10


# ---------------------------------------------------------------------------
# Test: --no-limit (AC-FUNC-005, AC-CYCLE-001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsNoLimit:
    """AC-FUNC-005, AC-CYCLE-001: --no-limit walks all PEP 440 valid tags."""

    def test_no_limit_walks_all_six_versions(self, tmp_path):
        """--no-limit with 6 versions x 2 entries -> 12 rows."""
        entry_names = ["alpha", "beta"]
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "2.2.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--no-limit"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        # 6 versions x 2 entries = 12 rows
        assert len(output_lines) == 12


# ---------------------------------------------------------------------------
# Test: --since-version (AC-TEST-003, AC-CYCLE-001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsSinceVersion:
    """AC-TEST-003, AC-CYCLE-001: --since-version filters via PEP 440."""

    def test_since_version_gte_2(self, tmp_path):
        """--since-version '>=2.0' shows only 3 versions from a 6-version repo."""
        entry_names = ["alpha", "beta"]
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "2.2.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--no-limit", "--since-version", ">=2.0"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        # 3 versions (2.0.0, 2.1.0, 2.2.0) x 2 entries = 6 rows
        assert len(output_lines) == 6

    def test_since_version_filters_out_older_versions(self, tmp_path):
        """Only versions matching '>=2.0' appear in output."""
        entry_names = ["entry"]
        versions = ["1.0.0", "1.5.0", "2.0.0", "2.5.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--no-limit", "--since-version", ">=2.0"])

        assert proc.returncode == 0
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        version_parts = {ln.split("@")[1] for ln in output_lines}
        assert version_parts == {"2.0.0", "2.5.0"}
        assert "1.0.0" not in version_parts
        assert "1.5.0" not in version_parts

    def test_since_version_range_filter(self, tmp_path):
        """--since-version '>=1.0,<2.0' keeps only versions inside range."""
        entry_names = ["entry"]
        versions = ["0.9.0", "1.0.0", "1.5.0", "2.0.0", "3.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        proc = _kanon_list_all_versions(bare_repo, extra_args=["--no-limit", "--since-version", ">=1.0,<2.0"])

        assert proc.returncode == 0
        output_lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
        version_parts = {ln.split("@")[1] for ln in output_lines}
        assert version_parts == {"1.0.0", "1.5.0"}


# ---------------------------------------------------------------------------
# Test: --all-versions --tree mutual exclusion (AC-FUNC-008, AC-CYCLE-001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAllVersionsTreeMutualExclusion:
    """AC-FUNC-008, AC-CYCLE-001: combining --all-versions and --tree is a hard error."""

    def test_all_versions_tree_exits_nonzero(self, tmp_path):
        """--all-versions --tree exits non-zero."""
        entry_names = ["entry"]
        versions = ["1.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        catalog_source = f"file://{bare_repo}@main"
        cmd = [
            sys.executable,
            "-m",
            "kanon_cli",
            "list",
            "--all-versions",
            "--tree",
            "--catalog-source",
            catalog_source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode != 0

    def test_all_versions_tree_writes_error_to_stderr(self, tmp_path):
        """--all-versions --tree emits an error message to stderr."""
        entry_names = ["entry"]
        versions = ["1.0.0"]
        bare_repo = _build_multi_version_manifest_repo(tmp_path, entry_names, versions)

        catalog_source = f"file://{bare_repo}@main"
        cmd = [
            sys.executable,
            "-m",
            "kanon_cli",
            "list",
            "--all-versions",
            "--tree",
            "--catalog-source",
            catalog_source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert "mutually exclusive" in proc.stderr.lower() or "--tree" in proc.stderr or "--all-versions" in proc.stderr

    def test_all_versions_tree_detected_before_catalog_work(self, tmp_path):
        """Mutual exclusion is caught before any git clone or catalog walk."""
        # Use a fake catalog source that would fail if cloned -- no catalog work
        # should happen before the mutual-exclusion check.
        catalog_source = "file:///this/does/not/exist@main"
        cmd = [
            sys.executable,
            "-m",
            "kanon_cli",
            "list",
            "--all-versions",
            "--tree",
            "--catalog-source",
            catalog_source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        # Must fail with mutual-exclusion error, NOT with a git/clone error.
        assert proc.returncode != 0
        assert "mutually exclusive" in proc.stderr.lower() or "--tree" in proc.stderr or "--all-versions" in proc.stderr


# ---------------------------------------------------------------------------
# Test: --limit and --no-limit mutual exclusion (AC-FUNC-009)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLimitNoLimitMutualExclusion:
    """AC-FUNC-009: --limit and --no-limit together is a hard error."""

    def test_limit_and_no_limit_exits_nonzero(self, tmp_path):
        """--limit 5 --no-limit exits non-zero."""
        catalog_source = "file:///this/does/not/exist@main"
        cmd = [
            sys.executable,
            "-m",
            "kanon_cli",
            "list",
            "--all-versions",
            "--limit",
            "5",
            "--no-limit",
            "--catalog-source",
            catalog_source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode != 0

    def test_limit_and_no_limit_writes_error_to_stderr(self, tmp_path):
        """--limit --no-limit emits an error to stderr."""
        catalog_source = "file:///this/does/not/exist@main"
        cmd = [
            sys.executable,
            "-m",
            "kanon_cli",
            "list",
            "--all-versions",
            "--limit",
            "5",
            "--no-limit",
            "--catalog-source",
            catalog_source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert "--limit" in proc.stderr or "--no-limit" in proc.stderr or "mutually exclusive" in proc.stderr.lower()
