"""E2E tests: version constraint resolution with real git tags.

Each test creates a local bare git repository with multiple semver tags using
the file:// protocol and verifies that PEP 440 version constraint operators
select the correct revision through the consolidated version_constraints module.

The tags are fetched from the real local git repositories using git ls-remote,
mirroring the exact data path used by project._ResolveVersionConstraint, which
calls git ls-remote then delegates to version_constraints.resolve_version_constraint.

Constraint operators tested:
- ~= compatible release (AC-TEST-001)
- >=/<  range constraint (AC-TEST-002)
- == exact match (AC-TEST-003)
- * wildcard latest (AC-TEST-004)
- ==1.* wildcard partial major version (AC-TEST-005)

All tests create real git repositories with actual semver tags (AC-TEST-006).
All tests are marked @pytest.mark.integration.
"""

import pathlib
import subprocess

import pytest

from kanon_cli.repo import version_constraints


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "E2E Constraint Test User"
_GIT_USER_EMAIL = "e2e-constraint-test@example.com"
_TAG_PREFIX = "refs/tags/pkg"


# ---------------------------------------------------------------------------
# Fixture: reusable git repo builder
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _build_tagged_bare_repo(
    base: pathlib.Path,
    name: str,
    tag_prefix: str,
    versions: list[str],
) -> pathlib.Path:
    """Create a bare git repo with semver-tagged commits and return its path.

    One commit per version is created in ``versions`` order. Each commit is
    tagged as ``<tag_prefix>/<version>``. The work directory is cloned into a
    bare repository to produce a URL-accessible repository.

    Args:
        base: Parent directory under which the repo is created.
        name: Unique name prefix for the work and bare subdirectories.
        tag_prefix: Tag path prefix used before each version string.
        versions: Ordered list of version strings (e.g., ['1.0.0', '1.1.0']).

    Returns:
        Absolute path to the bare git repository directory.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)

    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

    for version in versions:
        version_file = work_dir / "VERSION"
        version_file.write_text(f"{version}\n", encoding="utf-8")
        _git(["add", "VERSION"], cwd=work_dir)
        _git(["commit", "-m", f"Release {version}"], cwd=work_dir)
        _git(["tag", f"{tag_prefix}/{version}"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir


def _fetch_tags_from_repo(repo_path: pathlib.Path) -> list[str]:
    """Return all non-peeled tag refs from a bare repository via git ls-remote.

    Mirrors the exact data source used by project._ResolveVersionConstraint:
    git ls-remote is run against the file:// URL of the bare repo, and only
    refs/tags/ entries that do not end with '^{}' are included.

    Args:
        repo_path: Absolute path to the bare git repository.

    Returns:
        List of full tag ref strings (e.g., ['refs/tags/pkg/1.0.0', ...]).

    Raises:
        RuntimeError: If git ls-remote exits with a non-zero exit code.
    """
    url = f"file://{repo_path}"
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed for {url!r}: {result.stderr!r}")

    tags: list[str] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref)
    return tags


@pytest.fixture()
def semver_repo(tmp_path: pathlib.Path) -> list[str]:
    """Build a bare git repo with semver tags and return the tag list.

    Tags created under prefix 'pkg':
        pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0

    Returns:
        List of full tag ref strings as returned by git ls-remote, mirroring
        what project._ResolveVersionConstraint passes to
        version_constraints.resolve_version_constraint.
    """
    versions = ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "2.0.0"]
    bare_dir = _build_tagged_bare_repo(tmp_path, "semver", "pkg", versions)
    return _fetch_tags_from_repo(bare_dir)


# ---------------------------------------------------------------------------
# AC-TEST-001: ~= compatible release
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_compatible_release_constraint_resolves_to_correct_tag(semver_repo: list[str]) -> None:
    """AC-TEST-001: ~= constraint resolves to the correct compatible release tag.

    Given: real git repo with tags pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0
    When:  constraint is refs/tags/pkg/~=1.1 (two-part compatible release)
    Then:  resolves to refs/tags/pkg/1.3.0 (highest 1.x >= 1.1, excluding 2.0.0)

    The tags are fetched from a real local bare git repo via git ls-remote,
    matching the exact call sequence used by project._ResolveVersionConstraint.
    """
    revision = f"{_TAG_PREFIX}/~=1.1"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 from constraint ~=1.1 but got {result!r}. Available tags: {semver_repo!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: >=/<  range constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_range_constraint_resolves_to_highest_within_range(semver_repo: list[str]) -> None:
    """AC-TEST-002: >=/<  range constraint resolves to the highest matching tag within range.

    Given: real git repo with tags pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0
    When:  constraint is refs/tags/pkg/>=1.0.0,<2.0.0
    Then:  resolves to refs/tags/pkg/1.3.0 (highest version in [1.0.0, 2.0.0))

    Tags are fetched from a real local bare git repo via git ls-remote,
    mirroring project._ResolveVersionConstraint behavior.
    """
    revision = f"{_TAG_PREFIX}/>=1.0.0,<2.0.0"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 from constraint >=1.0.0,<2.0.0 but got {result!r}. "
        f"Available tags: {semver_repo!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: == exact match
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_exact_constraint_resolves_to_exact_tag(semver_repo: list[str]) -> None:
    """AC-TEST-003: == constraint resolves to the exact matching tag.

    Given: real git repo with tags pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0
    When:  constraint is refs/tags/pkg/==1.2.0
    Then:  resolves to refs/tags/pkg/1.2.0 (exact match only)

    Tags are fetched from a real local bare git repo via git ls-remote,
    mirroring project._ResolveVersionConstraint behavior.
    """
    revision = f"{_TAG_PREFIX}/==1.2.0"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == f"{_TAG_PREFIX}/1.2.0", (
        f"Expected {_TAG_PREFIX}/1.2.0 from constraint ==1.2.0 but got {result!r}. Available tags: {semver_repo!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: * wildcard resolves to latest tag
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wildcard_constraint_resolves_to_latest_tag(semver_repo: list[str]) -> None:
    """AC-TEST-004: * wildcard constraint resolves to the latest available tag.

    Given: real git repo with tags pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0
    When:  constraint is refs/tags/pkg/*
    Then:  resolves to refs/tags/pkg/2.0.0 (highest version overall)

    Tags are fetched from a real local bare git repo via git ls-remote,
    mirroring project._ResolveVersionConstraint behavior.
    """
    revision = f"{_TAG_PREFIX}/*"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == f"{_TAG_PREFIX}/2.0.0", (
        f"Expected {_TAG_PREFIX}/2.0.0 from wildcard * but got {result!r}. Available tags: {semver_repo!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: ==1.* wildcard partial major version
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_partial_wildcard_constraint_resolves_to_latest_matching_major(semver_repo: list[str]) -> None:
    """AC-TEST-005: ==1.* wildcard partial version resolves to the latest matching major version tag.

    Given: real git repo with tags pkg/1.0.0, pkg/1.1.0, pkg/1.2.0, pkg/1.3.0, pkg/2.0.0
    When:  constraint is refs/tags/pkg/==1.*
    Then:  resolves to refs/tags/pkg/1.3.0 (highest 1.x tag, excluding 2.0.0)

    The PEP 440 equality wildcard (==1.*) matches all 1.x releases. The highest
    version matching that constraint is 1.3.0.

    Tags are fetched from a real local bare git repo via git ls-remote,
    mirroring project._ResolveVersionConstraint behavior.
    """
    revision = f"{_TAG_PREFIX}/==1.*"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 from constraint ==1.* but got {result!r}. Available tags: {semver_repo!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-006 is structural: all tests above use real git repos (verified by
# fixture semver_repo, which creates a bare repo and fetches tags via git ls-remote).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Parametrized coverage: all five constraint types in one parametrize block
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("revision_suffix", "expected_version"),
    [
        ("~=1.1", "1.3.0"),
        (">=1.0.0,<2.0.0", "1.3.0"),
        ("==1.2.0", "1.2.0"),
        ("*", "2.0.0"),
        ("==1.*", "1.3.0"),
    ],
    ids=[
        "compatible-release",
        "range-ge-lt",
        "exact-equality",
        "wildcard-latest",
        "wildcard-major",
    ],
)
def test_constraint_resolution_parametrized(
    semver_repo: list[str],
    revision_suffix: str,
    expected_version: str,
) -> None:
    """Parametrized E2E constraint resolution against a real git repo.

    Covers all five constraint types (AC-TEST-001 through AC-TEST-005) in a
    single parametrize block. The tag list is fetched from a real bare git
    repository via git ls-remote on each test run (AC-TEST-006).

    Args:
        semver_repo: Tag list fetched from the real git repo fixture.
        revision_suffix: The constraint suffix (e.g., '~=1.1').
        expected_version: The version string expected in the resolved tag.
    """
    revision = f"{_TAG_PREFIX}/{revision_suffix}"
    expected_tag = f"{_TAG_PREFIX}/{expected_version}"
    result = version_constraints.resolve_version_constraint(revision, semver_repo)
    assert result == expected_tag, (
        f"Constraint '{revision_suffix}': expected '{expected_tag}' but got {result!r}. Available tags: {semver_repo!r}"
    )
