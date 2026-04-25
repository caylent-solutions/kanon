"""Functional tests for --groups filter grammar in 'kanon repo list'.

Exercises the group-filter grammar described in MatchesGroups():
- ``all``       -- implicit group present on every project
- ``default``   -- implicit group on projects that lack the ``notdefault`` group
- ``-group1``   -- negation prefix excludes projects that carry ``group1``
- unknown group -- requests a specific project that does not match the filter

All tests invoke ``kanon repo list`` as a subprocess against a real temporary
repository whose manifest declares projects with specific group attributes.
No mocks are used.

Covers:
- AC-TEST-001: ``--groups all`` matches all projects
- AC-TEST-002: ``--groups default`` matches projects without ``notdefault``
- AC-TEST-003: ``--groups -group1`` excludes group1 projects
- AC-TEST-004: ``--groups unknown`` with a named project raises a clear error
- AC-FUNC-001: ``--groups`` grammar matches documented behavior
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _create_bare_content_repo,
    _git,
    _init_git_work_dir,
    _clone_as_bare,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no domain literals embedded in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Groups Filter Test User"
_GIT_USER_EMAIL = "groups-filter@example.com"
_GIT_BRANCH = "main"
_MANIFEST_FILENAME = "default.xml"

# Project names and paths used in multi-project manifests.
_PROJECT_ALPHA_NAME = "content-alpha"
_PROJECT_ALPHA_PATH = "alpha"

_PROJECT_BETA_NAME = "content-beta"
_PROJECT_BETA_PATH = "beta"

# Group name used in negation tests.
_GROUP_FILTER_NAME = "group1"

# The ``notdefault`` sentinel group (excluded from ``default`` matching).
_NOTDEFAULT_GROUP = "notdefault"

# Expected error message fragment when a project does not match the group filter.
_GROUP_ERROR_FRAGMENT = "project group must be enabled"

# Traceback marker -- must not appear in stdout on successful runs.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# Shared helpers for multi-project manifest setup.
# ---------------------------------------------------------------------------


def _create_two_project_manifest(
    base: pathlib.Path,
    fetch_base: str,
    *,
    project_alpha_groups: str = "",
    project_beta_groups: str = "",
    manifest_bare_dir_name: str = "manifest-bare.git",
) -> pathlib.Path:
    """Create a bare manifest repo with two projects and optional group attributes.

    Writes a manifest XML that declares two projects:
    - ``_PROJECT_ALPHA_NAME`` / ``_PROJECT_ALPHA_PATH``
    - ``_PROJECT_BETA_NAME`` / ``_PROJECT_BETA_PATH``

    Each project gets the group attribute in ``project_alpha_groups`` /
    ``project_beta_groups`` (empty string means no ``groups`` attribute).

    Args:
        base: Parent directory under which the manifest work tree and bare clone
            are created.
        fetch_base: The fetch URL (``file://...``) pointing to the bare content
            repos directory.
        project_alpha_groups: Groups attribute value for the alpha project.
            Empty string omits the attribute.
        project_beta_groups: Groups attribute value for the beta project.
            Empty string omits the attribute.
        manifest_bare_dir_name: Directory name for the bare manifest clone.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(
        work_dir,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        branch=_GIT_BRANCH,
    )

    alpha_groups_attr = f' groups="{project_alpha_groups}"' if project_alpha_groups else ""
    beta_groups_attr = f' groups="{project_beta_groups}"' if project_beta_groups else ""

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        f'  <default revision="{_GIT_BRANCH}" remote="local" />\n'
        f'  <project name="{_PROJECT_ALPHA_NAME}" path="{_PROJECT_ALPHA_PATH}"{alpha_groups_attr} />\n'
        f'  <project name="{_PROJECT_BETA_NAME}" path="{_PROJECT_BETA_PATH}"{beta_groups_attr} />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add two-project manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / manifest_bare_dir_name)


def _create_two_bare_content_repos(base: pathlib.Path) -> str:
    """Create two bare content repos and return the shared fetch-base URL.

    Creates bare repos for ``_PROJECT_ALPHA_NAME`` and ``_PROJECT_BETA_NAME``
    inside ``base``.  Both repos share the same parent directory, which is used
    as the ``fetch`` base in the manifest remote element.

    ``_create_bare_content_repo`` uses a fixed ``content-work`` subdirectory
    for the non-bare working tree, so each call receives its own unique
    subdirectory of ``base`` to avoid the ``FileExistsError`` that occurs
    when two repos are built under the same parent.

    Args:
        base: Directory under which the bare repos are created.

    Returns:
        A ``file://`` URL string pointing at ``base``, which contains both
        bare repo directories (used as the fetch base URL in the manifest).
    """
    alpha_base = base / "alpha-work-root"
    alpha_base.mkdir()
    beta_base = base / "beta-work-root"
    beta_base.mkdir()

    alpha_bare = _create_bare_content_repo(
        alpha_base,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_ALPHA_NAME,
        content_file_name="README.md",
        content_file_text="alpha content",
    )
    beta_bare = _create_bare_content_repo(
        beta_base,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_BETA_NAME,
        content_file_name="README.md",
        content_file_text="beta content",
    )
    # Move the bare repos up to ``base`` so the manifest remote fetch URL
    # (file://<base>) resolves both <project>.git directories correctly.
    alpha_bare.rename(base / alpha_bare.name)
    beta_bare.rename(base / beta_bare.name)
    return f"file://{base}"


def _setup_two_project_synced_repo(
    tmp_path: pathlib.Path,
    *,
    project_alpha_groups: str = "",
    project_beta_groups: str = "",
    init_groups: str = "all",
) -> "tuple[pathlib.Path, pathlib.Path]":
    """Set up a synced two-project repo and return (checkout_dir, repo_dir).

    Creates two bare content repos and one bare manifest repo, then runs
    ``kanon repo init`` and ``kanon repo sync`` so both project worktrees
    exist on disk.

    Args:
        tmp_path: pytest-provided temporary directory root.
        project_alpha_groups: Groups attribute for the alpha project in the
            manifest (empty means no groups attribute).
        project_beta_groups: Groups attribute for the beta project in the
            manifest (empty means no groups attribute).
        init_groups: Groups value passed to ``kanon repo init --groups``.
            Defaults to ``"all"`` so that ALL manifest projects (including
            those tagged ``notdefault``) are synced, giving tests full
            visibility of both worktrees.

    Returns:
        A tuple of ``(checkout_dir, repo_dir)`` after a successful init and sync.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` fails.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    fetch_base = _create_two_bare_content_repos(repos_dir)
    manifest_bare = _create_two_project_manifest(
        repos_dir,
        fetch_base,
        project_alpha_groups=project_alpha_groups,
        project_beta_groups=project_beta_groups,
    )
    manifest_url = f"file://{manifest_bare}"
    repo_dir = checkout_dir / ".repo"

    init_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        _GIT_BRANCH,
        "-m",
        _MANIFEST_FILENAME,
        "--groups",
        init_groups,
        cwd=checkout_dir,
    )
    assert init_result.returncode == 0, (
        f"Prerequisite 'kanon repo init' failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )

    sync_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        "--jobs=1",
        cwd=checkout_dir,
    )
    assert sync_result.returncode == 0, (
        f"Prerequisite 'kanon repo sync' failed with exit {sync_result.returncode}.\n"
        f"  stdout: {sync_result.stdout!r}\n"
        f"  stderr: {sync_result.stderr!r}"
    )

    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: --groups all matches all projects
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterAll:
    """AC-TEST-001: ``--groups all`` matches all projects.

    The ``all`` pseudo-group is implicitly assigned to every project.
    Passing ``--groups all`` must list every project regardless of any
    explicit groups attribute in the manifest.
    """

    def test_groups_all_shows_project_with_notdefault(self, tmp_path: pathlib.Path) -> None:
        """``--groups all`` lists a project even if it has the ``notdefault`` group.

        A project tagged with ``notdefault`` is excluded by ``--groups default``
        but must still appear when ``--groups all`` is supplied, because every
        project is implicitly a member of the ``all`` pseudo-group.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_NOTDEFAULT_GROUP,
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=all' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Expected alpha project path {_PROJECT_ALPHA_PATH!r} in '--groups=all' stdout "
            f"(alpha has {_NOTDEFAULT_GROUP!r} group).\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Expected beta project path {_PROJECT_BETA_PATH!r} in '--groups=all' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_all_shows_project_with_explicit_group(self, tmp_path: pathlib.Path) -> None:
        """``--groups all`` lists a project that has an explicit group attribute.

        Projects with any explicit group attribute (e.g. ``group1``) are still
        members of the implicit ``all`` group.  ``--groups all`` must include them.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_GROUP_FILTER_NAME,
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=all' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Expected alpha project (groups={_GROUP_FILTER_NAME!r}) in '--groups=all' stdout.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Expected beta project in '--groups=all' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_all_shows_both_projects_with_no_manifest_groups(self, tmp_path: pathlib.Path) -> None:
        """``--groups all`` shows all projects when no manifest-level groups are set.

        When neither project declares a groups attribute, every project is in
        ``all`` and ``default``.  ``--groups all`` must show both.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=all' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Expected alpha project in '--groups=all' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Expected beta project in '--groups=all' stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: --groups default matches projects without notdefault
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterDefault:
    """AC-TEST-002: ``--groups default`` matches projects without ``notdefault``.

    The ``default`` pseudo-group is implicit on every project that does NOT
    carry the ``notdefault`` group label.  ``--groups default`` must include
    ordinary projects and exclude those tagged ``notdefault``.
    """

    def test_groups_default_excludes_notdefault_project(self, tmp_path: pathlib.Path) -> None:
        """``--groups default`` omits a project tagged ``notdefault``.

        When a project carries the ``notdefault`` group attribute the implicit
        ``default`` group is NOT added to it.  ``--groups default`` must
        therefore exclude that project.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_NOTDEFAULT_GROUP,
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=default",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=default' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH not in result.stdout, (
            f"Alpha project (groups={_NOTDEFAULT_GROUP!r}) must NOT appear in "
            f"'--groups=default' stdout.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta project (no notdefault) must appear in '--groups=default' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_default_includes_project_without_notdefault(self, tmp_path: pathlib.Path) -> None:
        """``--groups default`` includes projects that do not declare ``notdefault``.

        A project that carries no groups attribute (or carries a group other
        than ``notdefault``) gets the implicit ``default`` group and must appear
        in the output of ``--groups default``.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=default",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=default' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Alpha project (no notdefault) must appear in '--groups=default' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta project (no notdefault) must appear in '--groups=default' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_default_excludes_notdefault_includes_other(self, tmp_path: pathlib.Path) -> None:
        """``--groups default`` shows beta but not alpha when alpha is ``notdefault``.

        This test uses the same data as the exclusion test above and additionally
        asserts that beta -- which does not carry ``notdefault`` -- is present.
        It provides a single-assertion summary of the complete default-filter
        behavior in a two-project manifest.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_NOTDEFAULT_GROUP,
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=default",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=default' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        lines = result.stdout.splitlines()
        alpha_present = any(_PROJECT_ALPHA_PATH in line for line in lines)
        beta_present = any(_PROJECT_BETA_PATH in line for line in lines)
        assert not alpha_present, (
            f"Alpha project tagged {_NOTDEFAULT_GROUP!r} must NOT appear with "
            f"'--groups=default'.\n  stdout: {result.stdout!r}"
        )
        assert beta_present, (
            f"Beta project (no {_NOTDEFAULT_GROUP!r}) must appear with '--groups=default'.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: --groups -group1 excludes group1 projects
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterNegation:
    """AC-TEST-003: The ``-group1`` negation prefix excludes projects tagged ``group1``.

    The negation prefix ``-`` removes matching projects from an otherwise
    inclusive result set.  The canonical usage is a compound filter such as
    ``all,-group1`` (include all, then subtract group1) or
    ``default,-group1`` (include default, then subtract group1).

    A bare ``-group1`` filter (no positive prefix) matches nothing because
    the evaluation starts with ``matched=False`` and the negation token never
    sets it to ``True``.
    """

    def test_all_minus_group1_excludes_alpha_includes_beta(self, tmp_path: pathlib.Path) -> None:
        """``--groups all,-group1`` omits the project that carries ``group1``.

        Alpha is tagged ``group1``; beta is untagged.  The compound filter
        ``all,-group1`` first sets matched for all projects (via ``all``),
        then the ``-group1`` token clears the match for alpha.  Beta must
        remain in the output; alpha must not appear.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_GROUP_FILTER_NAME,
            project_beta_groups="",
        )
        combined_filter = f"all,-{_GROUP_FILTER_NAME}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--groups={combined_filter}",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups={combined_filter}' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH not in result.stdout, (
            f"Alpha project (groups={_GROUP_FILTER_NAME!r}) must NOT appear with "
            f"'--groups={combined_filter}'.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta project (untagged) must appear with '--groups={combined_filter}'.\n  stdout: {result.stdout!r}"
        )

    def test_default_minus_group1_excludes_alpha_includes_beta(self, tmp_path: pathlib.Path) -> None:
        """``--groups default,-group1`` omits a project carrying both ``default`` and ``group1``.

        Alpha has ``group1`` in its manifest groups.  Because ``group1`` is its
        only explicit group, alpha also has the implicit ``default`` group (since
        ``notdefault`` is not present).  The filter ``default,-group1`` first
        matches alpha via ``default`` and then clears it via ``-group1``.
        Beta (no ``group1`` attribute) remains matched through ``default``.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_GROUP_FILTER_NAME,
            project_beta_groups="",
        )
        combined_filter = f"default,-{_GROUP_FILTER_NAME}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--groups={combined_filter}",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups={combined_filter}' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH not in result.stdout, (
            f"Alpha project (groups={_GROUP_FILTER_NAME!r}) must NOT appear with "
            f"'--groups={combined_filter}'.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta project (no {_GROUP_FILTER_NAME!r}) must appear with "
            f"'--groups={combined_filter}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_negation_only_without_positive_matches_nothing(self, tmp_path: pathlib.Path) -> None:
        """A bare ``-group1`` filter (no positive prefix) matches no projects.

        The ``MatchesGroups`` evaluation starts with ``matched=False``.  A
        negation token can only set ``matched=False`` (its initial value); it
        cannot set it to ``True``.  Without a preceding positive token, no
        project is included.  The command exits 0 with empty output.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        bare_negation = f"-{_GROUP_FILTER_NAME}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--groups={bare_negation}",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups={bare_negation}' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout.strip() == "", (
            f"Expected empty output with bare negation filter '{bare_negation}', got: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: --groups unknown with a named project raises a clear error
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterUnknown:
    """AC-TEST-004: Requesting a named project under an unmatched group filter raises a clear error.

    When a specific project is requested by name (positional argument) but
    the ``--groups`` filter does not match that project, the CLI raises
    ``InvalidProjectGroupsError`` and exits non-zero with the message
    "project group must be enabled for project <name>" on stderr.
    """

    def test_unknown_group_with_project_path_raises_error(self, tmp_path: pathlib.Path) -> None:
        """``--groups notreal <project-path>`` exits non-zero with a clear error message.

        The filter ``notreal`` does not match any project group.  Passing the
        alpha project path as a positional argument causes ``GetProjects()`` to:
        1. Find no projects by name matching the group filter.
        2. Locate the project by path (``_GetProjectByPath``), which bypasses
           the group filter in the initial lookup.
        3. Evaluate ``MatchesGroups`` in the per-project loop and raise
           ``InvalidProjectGroupsError``.

        The exit code must be non-zero and stderr must contain the phrase
        ``"project group must be enabled"``.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=notreal",
            _PROJECT_ALPHA_PATH,
            cwd=checkout_dir,
        )
        assert result.returncode != 0, (
            f"'kanon repo list --groups=notreal {_PROJECT_ALPHA_PATH}' expected non-zero exit "
            f"but got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _GROUP_ERROR_FRAGMENT in result.stderr, (
            f"Expected error fragment {_GROUP_ERROR_FRAGMENT!r} in stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_group_error_message_contains_project_path(self, tmp_path: pathlib.Path) -> None:
        """The error message names the project that failed the group check.

        When ``InvalidProjectGroupsError`` is raised, the logged message is
        "error: project group must be enabled for project <arg>".  The
        project path argument must appear in stderr so the user knows which
        project did not satisfy the requested groups filter.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=notreal",
            _PROJECT_ALPHA_PATH,
            cwd=checkout_dir,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit but got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stderr, (
            f"Expected project path {_PROJECT_ALPHA_PATH!r} in stderr error message.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_group_without_named_project_exits_zero_with_empty_output(self, tmp_path: pathlib.Path) -> None:
        """``--groups notreal`` without a named project exits 0 with empty output.

        When no positional project argument is supplied, ``GetProjects()`` just
        applies the group filter to all projects.  An unmatched filter produces
        an empty result set, which is not an error -- the command exits 0.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="",
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=notreal",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=notreal' (no named project) expected exit 0 "
            f"but got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout.strip() == "", f"Expected empty stdout with unmatched group filter, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-001: --groups grammar matches documented behavior
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterDocumentedBehavior:
    """AC-FUNC-001: ``--groups`` grammar matches the documented filter behavior.

    Verifies that the complete documented grammar -- including comma separation,
    the implicit ``all`` group, and the ``default``/``notdefault`` interaction --
    produces the results described in the MatchesGroups docstring.
    """

    def test_comma_separated_filter_matches_project_in_any_listed_group(self, tmp_path: pathlib.Path) -> None:
        """Comma-separated groups filter matches projects in any of the listed groups.

        The filter ``group1,group2`` must match projects tagged ``group1`` and
        projects tagged ``group2``.  Both projects appear in the output.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups="group1",
            project_beta_groups="group2",
        )
        combined_filter = "group1,group2"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--groups={combined_filter}",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups={combined_filter}' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Alpha project (groups=group1) must appear with '--groups={combined_filter}'.\n  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta project (groups=group2) must appear with '--groups={combined_filter}'.\n  stdout: {result.stdout!r}"
        )

    def test_groups_all_overrides_notdefault(self, tmp_path: pathlib.Path) -> None:
        """``--groups all`` shows projects even when they carry ``notdefault``.

        The implicit ``all`` group takes precedence as an inclusion filter.
        Even a project tagged ``notdefault`` is shown because ``all`` matches
        it unconditionally.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_NOTDEFAULT_GROUP,
            project_beta_groups="",
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=all' exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH in result.stdout, (
            f"Alpha ({_NOTDEFAULT_GROUP!r}) must appear with '--groups=all'.\n  stdout: {result.stdout!r}"
        )

    def test_default_filter_used_when_no_groups_flag(self, tmp_path: pathlib.Path) -> None:
        """When ``--groups`` is omitted, the manifest's stored groups filter is applied.

        ``repo init`` stores the chosen groups in the manifest config.  When
        ``repo list`` is run without an explicit ``--groups`` flag, that stored
        value is used.  In this test both projects are synced by initialising
        with ``--groups all``, but then we re-initialise in-place with the
        default groups (no ``--groups`` flag), which resets the stored filter
        to ``default``.  A subsequent ``repo list`` with no ``--groups`` flag
        must apply the ``default`` filter and exclude the alpha project that
        carries ``notdefault``.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(
            tmp_path,
            project_alpha_groups=_NOTDEFAULT_GROUP,
            project_beta_groups="",
            init_groups="all",
        )
        # Re-initialise without --groups to reset the manifest-stored groups
        # to "default".  Both worktrees are already on disk from the first sync.
        repos_dir = tmp_path / "repos"
        manifest_bare = repos_dir / "manifest-bare.git"
        manifest_url = f"file://{manifest_bare}"
        reinit_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            _GIT_BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert reinit_result.returncode == 0, (
            f"Re-init without --groups failed with exit {reinit_result.returncode}.\n"
            f"  stdout: {reinit_result.stdout!r}\n"
            f"  stderr: {reinit_result.stderr!r}"
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list' (no --groups after reinit) exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _PROJECT_ALPHA_PATH not in result.stdout, (
            f"Alpha ({_NOTDEFAULT_GROUP!r}) must NOT appear after re-init to default groups.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _PROJECT_BETA_PATH in result.stdout, (
            f"Beta (no {_NOTDEFAULT_GROUP!r}) must appear after re-init to default groups.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestGroupsFilterChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for groups-filter invocations.

    Verifies that successful invocations do not write Python tracebacks or
    ``Error:`` prefixed messages to stdout, and that error paths write their
    diagnostic messages to stderr (not stdout).
    """

    def test_successful_groups_filter_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful ``--groups all`` invocation must not emit tracebacks to stdout."""
        checkout_dir, repo_dir = _setup_two_project_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite '--groups=all' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Traceback found in stdout of '--groups=all'.\n  stdout: {result.stdout!r}"
        )

    def test_successful_groups_filter_has_no_error_prefix_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful ``--groups default`` must not write 'Error:' lines to stdout."""
        checkout_dir, repo_dir = _setup_two_project_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=default",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite '--groups=default' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of '--groups=default': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_group_error_writes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Group-mismatch error message must appear on stderr, not stdout.

        When ``InvalidProjectGroupsError`` is raised, the error message must
        be written to stderr.  stdout must be empty on error.
        """
        checkout_dir, repo_dir = _setup_two_project_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=notreal",
            _PROJECT_ALPHA_PATH,
            cwd=checkout_dir,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit but got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _GROUP_ERROR_FRAGMENT in result.stderr, (
            f"Error message {_GROUP_ERROR_FRAGMENT!r} must be on stderr.\n  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", f"stdout must be empty on group-filter error, got: {result.stdout!r}"

    def test_successful_groups_filter_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful ``--groups all`` must not emit tracebacks to stderr."""
        checkout_dir, repo_dir = _setup_two_project_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite '--groups=all' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Traceback found in stderr of '--groups=all'.\n  stderr: {result.stderr!r}"
        )
