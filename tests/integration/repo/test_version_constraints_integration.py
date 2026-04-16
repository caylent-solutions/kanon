"""Integration tests for version constraint resolution against real git repositories.

Each test creates an actual git repository with tagged commits using the
file:// protocol and verifies that PEP 440 version constraint operators select
the correct revision.

Tests cover:
- All PEP 440 operators: ==, !=, <, <=, >, >=, ~=, ===
- Compound constraints (e.g., >=1.0.0,<2.0.0)
- Pre-release version handling
- Invalid constraint syntax (error paths)
- No matching version scenario
- Wildcard operator (*)

All tests are marked @pytest.mark.integration and use real git repositories
with no mocks.
"""

import pathlib
import subprocess

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import version_constraints


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Version Constraint Test User"
_GIT_USER_EMAIL = "version-constraint-test@example.com"
_TAG_PREFIX = "refs/tags/project"


# ---------------------------------------------------------------------------
# Shared helpers
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


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config.

    Args:
        work_dir: Directory in which to run git init.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _commit_file(work_dir: pathlib.Path, filename: str, content: str, message: str) -> None:
    """Write a file, stage it, and commit it in work_dir.

    Args:
        work_dir: Git working directory.
        filename: Name of the file to create.
        content: Text content to write to the file.
        message: Commit message.
    """
    (work_dir / filename).write_text(content, encoding="utf-8")
    _git(["add", filename], cwd=work_dir)
    _git(["commit", "-m", message], cwd=work_dir)


def _tag(work_dir: pathlib.Path, tag_name: str) -> None:
    """Create a lightweight git tag at HEAD in work_dir.

    Args:
        work_dir: Git working directory.
        tag_name: The tag name to create (e.g., 'project/1.0.0').
    """
    _git(["tag", tag_name], cwd=work_dir)


def _make_bare_clone(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> None:
    """Clone work_dir into a bare repository at bare_dir.

    Args:
        work_dir: Source git working directory.
        bare_dir: Destination path for the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)


def _create_versioned_repo(
    base: pathlib.Path,
    name: str,
    versions: list[str],
    tag_prefix: str = "project",
) -> pathlib.Path:
    """Create a bare git repo with multiple tagged commits and return its path.

    Creates one commit per version in ``versions``, tagging each commit with
    ``<tag_prefix>/<version>``. Returns the path to the bare clone.

    Args:
        base: Parent directory under which the repo is created.
        name: Unique name prefix for the work and bare directories.
        versions: List of version strings (e.g., ['1.0.0', '1.1.0', '2.0.0']).
        tag_prefix: Tag path prefix used before each version (default: 'project').

    Returns:
        Absolute path to the bare git repository directory.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    for version in versions:
        _commit_file(work_dir, "VERSION", f"{version}\n", f"Release {version}")
        _tag(work_dir, f"{tag_prefix}/{version}")

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return bare_dir


def _list_tags_from_repo(repo_path: pathlib.Path) -> list[str]:
    """Return all tag refs from a bare repository using git ls-remote.

    Args:
        repo_path: Absolute path to the bare git repository.

    Returns:
        List of full tag ref strings (e.g., ['refs/tags/project/1.0.0', ...]).

    Raises:
        RuntimeError: If git ls-remote fails.
    """
    url = f"file://{repo_path}"
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed for {url!r}: {result.stderr!r}")
    tags = []
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def multi_version_repo(tmp_path: pathlib.Path) -> list[str]:
    """Create a bare git repo with versions 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0.

    Returns the list of available tag strings (as returned by git ls-remote).
    """
    versions = ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "2.0.0"]
    bare_dir = _create_versioned_repo(tmp_path, "multi-version", versions)
    return _list_tags_from_repo(bare_dir)


@pytest.fixture()
def patch_version_repo(tmp_path: pathlib.Path) -> list[str]:
    """Create a bare git repo with versions 1.2.0, 1.2.3, 1.2.7, 1.3.0.

    Returns the list of available tag strings (as returned by git ls-remote).
    """
    versions = ["1.2.0", "1.2.3", "1.2.7", "1.3.0"]
    bare_dir = _create_versioned_repo(tmp_path, "patch-version", versions)
    return _list_tags_from_repo(bare_dir)


@pytest.fixture()
def prerelease_repo(tmp_path: pathlib.Path) -> list[str]:
    """Create a bare git repo with versions 1.0.0a1, 1.0.0b1, 1.0.0rc1, 1.0.0, 1.1.0.

    Returns the list of available tag strings (as returned by git ls-remote).
    """
    versions = ["1.0.0a1", "1.0.0b1", "1.0.0rc1", "1.0.0", "1.1.0"]
    bare_dir = _create_versioned_repo(tmp_path, "prerelease", versions)
    return _list_tags_from_repo(bare_dir)


# ---------------------------------------------------------------------------
# Tests: is_version_constraint detection (AC-FUNC-003)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_is_version_constraint_detects_all_operators() -> None:
    """is_version_constraint returns True for every PEP 440 operator.

    Verifies that the detection function recognises ==, !=, <, <=, >, >=, ~=,
    and === when they appear as the last path component of a revision string.

    AC-FUNC-003
    """
    constraint_revisions = [
        f"{_TAG_PREFIX}/==1.0.0",
        f"{_TAG_PREFIX}/!=1.0.0",
        f"{_TAG_PREFIX}/<2.0.0",
        f"{_TAG_PREFIX}/<=2.0.0",
        f"{_TAG_PREFIX}/>1.0.0",
        f"{_TAG_PREFIX}/>=1.0.0",
        f"{_TAG_PREFIX}/~=1.0.0",
        f"{_TAG_PREFIX}/===1.0.0",
        f"{_TAG_PREFIX}/*",
        f"{_TAG_PREFIX}/>=1.0.0,<2.0.0",
    ]
    for revision in constraint_revisions:
        assert version_constraints.is_version_constraint(revision), (
            f"Expected is_version_constraint({revision!r}) to return True, but got False."
        )


# ---------------------------------------------------------------------------
# Tests: resolve_version_constraint -- individual operators (AC-FUNC-003)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_equal_operator_resolves_exact_version(multi_version_repo: list[str]) -> None:
    """== operator selects the exact specified version.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is ==1.2.0
    Then:  resolves to refs/tags/project/1.2.0

    AC-FUNC-003: == operator
    """
    revision = f"{_TAG_PREFIX}/==1.2.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.2.0", (
        f"Expected {_TAG_PREFIX}/1.2.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_not_equal_operator_excludes_specified_version(multi_version_repo: list[str]) -> None:
    """!= operator excludes the specified version and returns the highest remaining.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is !=2.0.0
    Then:  resolves to refs/tags/project/1.3.0 (highest excluding 2.0.0)

    AC-FUNC-003: != operator
    """
    revision = f"{_TAG_PREFIX}/!=2.0.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_less_than_operator_resolves_highest_below_bound(multi_version_repo: list[str]) -> None:
    """< operator selects the highest version strictly below the bound.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is <2.0.0
    Then:  resolves to refs/tags/project/1.3.0

    AC-FUNC-003: < operator
    """
    revision = f"{_TAG_PREFIX}/<2.0.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_less_than_or_equal_operator_includes_upper_boundary(multi_version_repo: list[str]) -> None:
    """<= operator selects the highest version at or below the bound.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is <=1.3.0
    Then:  resolves to refs/tags/project/1.3.0 (boundary version is included)

    AC-FUNC-003: <= operator
    """
    revision = f"{_TAG_PREFIX}/<=1.3.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_greater_than_operator_resolves_highest_above_bound(multi_version_repo: list[str]) -> None:
    """> operator selects the highest version strictly above the bound.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is >1.3.0
    Then:  resolves to refs/tags/project/2.0.0

    AC-FUNC-003: > operator
    """
    revision = f"{_TAG_PREFIX}/>1.3.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/2.0.0", (
        f"Expected {_TAG_PREFIX}/2.0.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_greater_than_or_equal_operator_includes_lower_boundary(multi_version_repo: list[str]) -> None:
    """>= operator selects the highest version at or above the bound.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is >=2.0.0
    Then:  resolves to refs/tags/project/2.0.0 (boundary version is included)

    AC-FUNC-003: >= operator
    """
    revision = f"{_TAG_PREFIX}/>=2.0.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/2.0.0", (
        f"Expected {_TAG_PREFIX}/2.0.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_compatible_release_operator_patch_level(patch_version_repo: list[str]) -> None:
    """~= operator with three-part version selects highest patch-compatible version.

    Given: tags 1.2.0, 1.2.3, 1.2.7, 1.3.0
    When:  constraint is ~=1.2.0
    Then:  resolves to refs/tags/project/1.2.7 (highest 1.2.x, excludes 1.3.0)

    AC-FUNC-003: ~= operator (patch compatibility)
    """
    revision = f"{_TAG_PREFIX}/~=1.2.0"
    result = version_constraints.resolve_version_constraint(revision, patch_version_repo)
    assert result == f"{_TAG_PREFIX}/1.2.7", (
        f"Expected {_TAG_PREFIX}/1.2.7 but got {result!r}. Available tags: {patch_version_repo!r}"
    )


@pytest.mark.integration
def test_compatible_release_operator_minor_level(multi_version_repo: list[str]) -> None:
    """~= operator with two-part version selects highest minor-compatible version.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is ~=1.1
    Then:  resolves to refs/tags/project/1.3.0 (highest 1.x >= 1.1, excludes 2.0.0)

    AC-FUNC-003: ~= operator (minor compatibility)
    """
    revision = f"{_TAG_PREFIX}/~=1.1"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_arbitrary_equality_operator_selects_exact_string(multi_version_repo: list[str]) -> None:
    """=== operator (arbitrary equality) selects the version with an exact string match.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is ===1.1.0
    Then:  resolves to refs/tags/project/1.1.0

    AC-FUNC-003: === operator (arbitrary equality)
    """
    revision = f"{_TAG_PREFIX}/===1.1.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.1.0", (
        f"Expected {_TAG_PREFIX}/1.1.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_wildcard_operator_returns_highest_version(multi_version_repo: list[str]) -> None:
    """Wildcard (*) operator returns the highest available version under the prefix.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is *
    Then:  resolves to refs/tags/project/2.0.0

    AC-FUNC-003: * wildcard
    """
    revision = f"{_TAG_PREFIX}/*"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/2.0.0", (
        f"Expected {_TAG_PREFIX}/2.0.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


# ---------------------------------------------------------------------------
# Tests: compound constraints (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_compound_range_constraint_selects_highest_within_range(multi_version_repo: list[str]) -> None:
    """Compound >=X,<Y constraint selects the highest version within the range.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is >=1.0.0,<2.0.0
    Then:  resolves to refs/tags/project/1.3.0

    AC-FUNC-004: compound constraint
    """
    revision = f"{_TAG_PREFIX}/>=1.0.0,<2.0.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/1.3.0", (
        f"Expected {_TAG_PREFIX}/1.3.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


@pytest.mark.integration
def test_compound_constraint_with_exclusion(multi_version_repo: list[str]) -> None:
    """Compound >=X,!=Y constraint excludes the unwanted version from matches.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is >=1.1.0,!=1.3.0
    Then:  resolves to refs/tags/project/2.0.0 (1.3.0 excluded; 2.0.0 is highest)

    AC-FUNC-004: compound constraint with != exclusion
    """
    revision = f"{_TAG_PREFIX}/>=1.1.0,!=1.3.0"
    result = version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert result == f"{_TAG_PREFIX}/2.0.0", (
        f"Expected {_TAG_PREFIX}/2.0.0 but got {result!r}. Available tags: {multi_version_repo!r}"
    )


# ---------------------------------------------------------------------------
# Tests: pre-release handling (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_prerelease_versions_excluded_by_stable_constraint(prerelease_repo: list[str]) -> None:
    """Stable constraint (>=1.0.0) does not return pre-release versions by default.

    Given: tags 1.0.0a1, 1.0.0b1, 1.0.0rc1, 1.0.0, 1.1.0
    When:  constraint is >=1.0.0
    Then:  resolves to refs/tags/project/1.1.0 (pre-releases are excluded)

    AC-FUNC-005: pre-release handling
    """
    revision = f"{_TAG_PREFIX}/>=1.0.0"
    result = version_constraints.resolve_version_constraint(revision, prerelease_repo)
    assert result == f"{_TAG_PREFIX}/1.1.0", (
        f"Expected {_TAG_PREFIX}/1.1.0 (stable) but got {result!r}. Available tags: {prerelease_repo!r}"
    )


@pytest.mark.integration
def test_prerelease_selected_by_explicit_prerelease_constraint(prerelease_repo: list[str]) -> None:
    """Exact == constraint on a pre-release tag selects that pre-release version.

    Given: tags 1.0.0a1, 1.0.0b1, 1.0.0rc1, 1.0.0, 1.1.0
    When:  constraint is ==1.0.0a1
    Then:  resolves to refs/tags/project/1.0.0a1

    AC-FUNC-005: explicit pre-release selection
    """
    revision = f"{_TAG_PREFIX}/==1.0.0a1"
    result = version_constraints.resolve_version_constraint(revision, prerelease_repo)
    assert result == f"{_TAG_PREFIX}/1.0.0a1", (
        f"Expected {_TAG_PREFIX}/1.0.0a1 but got {result!r}. Available tags: {prerelease_repo!r}"
    )


# ---------------------------------------------------------------------------
# Tests: error paths (AC-FUNC-006, AC-FUNC-007)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_no_matching_version_raises_manifest_invalid_revision_error(multi_version_repo: list[str]) -> None:
    """Constraint that matches no available tag raises ManifestInvalidRevisionError.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is ==9.9.9 (no such tag exists)
    Then:  raises ManifestInvalidRevisionError

    AC-FUNC-007: no matching version
    """
    revision = f"{_TAG_PREFIX}/==9.9.9"
    with pytest.raises(error.ManifestInvalidRevisionError) as exc_info:
        version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert exc_info.value is not None, (
        "Expected ManifestInvalidRevisionError to be raised when no tag matches the constraint."
    )


@pytest.mark.integration
def test_invalid_constraint_syntax_raises_manifest_invalid_revision_error(
    multi_version_repo: list[str],
) -> None:
    """Unparseable constraint string raises ManifestInvalidRevisionError.

    Given: tags 1.0.0, 1.1.0, 1.2.0, 1.3.0, 2.0.0
    When:  constraint is >!invalid (not valid PEP 440)
    Then:  raises ManifestInvalidRevisionError

    AC-FUNC-006: invalid constraint syntax
    """
    revision = f"{_TAG_PREFIX}/>!invalid"
    with pytest.raises(error.ManifestInvalidRevisionError) as exc_info:
        version_constraints.resolve_version_constraint(revision, multi_version_repo)
    assert exc_info.value is not None, "Expected ManifestInvalidRevisionError to be raised for invalid PEP 440 syntax."


@pytest.mark.integration
def test_empty_tag_list_raises_manifest_invalid_revision_error() -> None:
    """Empty available_tags list raises ManifestInvalidRevisionError.

    Given: no available tags
    When:  constraint is >=1.0.0
    Then:  raises ManifestInvalidRevisionError

    AC-FUNC-006, AC-FUNC-007: no matching version with empty list
    """
    revision = f"{_TAG_PREFIX}/>=1.0.0"
    with pytest.raises(error.ManifestInvalidRevisionError) as exc_info:
        version_constraints.resolve_version_constraint(revision, [])
    assert exc_info.value is not None, (
        "Expected ManifestInvalidRevisionError to be raised when available_tags is empty."
    )
