"""Functional tests for ``kanon repo manifest --revision-as-tag``.

Exercises the ``--revision-as-tag`` flag end-to-end in a real ``.repo``-
initialized and synced workspace.  Confirms:

- AC-FUNC-001: ``kanon repo manifest --revision-as-tag`` exits 0 and outputs
  the current manifest with each project's revision replaced by the nearest
  git tag (``refs/tags/<name>``).
- AC-TEST-002: Functional test runs in a real ``.repo``-initialized workspace
  and asserts exit 0.

Tests are decorated with ``@pytest.mark.functional``.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _git,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no literals in assertions.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Manifest Revision-As-Tag Test User"
_GIT_USER_EMAIL = "repo-manifest-rat@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "rat-test-project"

_CLI_TOKEN_MANIFEST = "manifest"
_FLAG_REVISION_AS_TAG = "--revision-as-tag"

_EXPECTED_EXIT_CODE = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

_REFS_TAGS_PREFIX = "refs/tags/"
_TEST_TAG_NAME = "v1.0.0"
_TEST_TAG_REFS = f"{_REFS_TAGS_PREFIX}{_TEST_TAG_NAME}"

_XML_DECLARATION_FRAGMENT = "<?xml"
_TRACEBACK_MARKER = "Traceback (most recent call last)"


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------


def _setup_tagged_synced_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a synced repo where the content project commit is tagged.

    Calls ``_setup_synced_repo`` to create bare repos and run init + sync,
    then pushes an annotated tag to the bare content repo and fetches it
    into the project worktree so that ``git describe --exact-match HEAD``
    succeeds.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of ``(checkout_dir, repo_dir)`` after init, sync, and tag setup.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
    )

    # Locate the bare content repo created by _create_bare_content_repo.
    bare_content_dir = tmp_path / "repos" / f"{_PROJECT_NAME}.git"

    # Create a tag in the bare content repo pointing at its HEAD commit.
    _git(
        ["tag", "-a", _TEST_TAG_NAME, "-m", f"Tag {_TEST_TAG_NAME}", "HEAD"],
        cwd=bare_content_dir,
    )

    # Fetch the tag into the project's working tree checkout so
    # 'git describe --exact-match HEAD' resolves the tag locally.
    project_worktree = checkout_dir / _PROJECT_PATH
    _git(["fetch", "--tags"], cwd=project_worktree)

    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-TEST-002: Real synced workspace tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestRevisionAsTagHappyPath:
    """AC-FUNC-001 / AC-TEST-002: ``--revision-as-tag`` exits 0 and rewrites revisions.

    Uses a real ``.repo``-initialized workspace where the content project's
    HEAD commit has an exact annotated tag.  Confirms that the flag is
    accepted and that the manifest output contains the tag reference.
    """

    def test_revision_as_tag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """``kanon repo manifest --revision-as-tag`` must exit 0 in a tagged repo.

        On a synced repository where the content project commit has an exact
        tag, the flag must be accepted and the command must exit 0.
        """
        checkout_dir, repo_dir = _setup_tagged_synced_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo manifest {_FLAG_REVISION_AS_TAG}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_revision_as_tag_produces_xml_output(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-tag`` must produce XML output with the declaration header.

        The manifest output format is XML by default.  The output must start
        with the XML declaration even when ``--revision-as-tag`` is active.
        """
        checkout_dir, repo_dir = _setup_tagged_synced_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: 'kanon repo manifest {_FLAG_REVISION_AS_TAG}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected XML declaration {_XML_DECLARATION_FRAGMENT!r} in stdout "
            f"with '{_FLAG_REVISION_AS_TAG}'.\n  stdout: {result.stdout!r}"
        )

    def test_revision_as_tag_contains_tag_reference(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-tag`` must replace project revision with ``refs/tags/<name>``.

        When the content project's HEAD is tagged exactly with ``_TEST_TAG_NAME``,
        the output manifest must contain a ``revision`` attribute equal to
        ``refs/tags/_TEST_TAG_NAME``.
        """
        checkout_dir, repo_dir = _setup_tagged_synced_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: 'kanon repo manifest {_FLAG_REVISION_AS_TAG}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _TEST_TAG_REFS in result.stdout, (
            f"Expected tag reference {_TEST_TAG_REFS!r} in stdout after "
            f"'{_FLAG_REVISION_AS_TAG}'.\n  stdout: {result.stdout!r}"
        )

    def test_revision_as_tag_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-tag`` must not emit a Python traceback to stdout.

        Successful invocations must not leak exception details to stdout.
        """
        checkout_dir, repo_dir = _setup_tagged_synced_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: 'kanon repo manifest {_FLAG_REVISION_AS_TAG}' failed.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback must not appear in stdout for successful invocation.\n  stdout: {result.stdout!r}"
        )


@pytest.mark.functional
class TestRepoManifestRevisionAsTagUntagged:
    """``--revision-as-tag`` preserves original revision when no exact tag exists.

    When a project's HEAD commit is not tagged exactly, the manifest output
    must keep the original revision value and must still exit 0.
    """

    def test_revision_as_tag_exits_zero_without_tag(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-tag`` exits 0 and warns to stderr when no exact tag is available.

        On a synced repo where the project has no exact tag, the command must
        still exit 0 (untagged projects are skipped with a structured warning on
        stderr identifying the project by its relative path).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo manifest {_FLAG_REVISION_AS_TAG}' exited {result.returncode} "
            f"on an untagged repo, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_PATH in result.stderr, (
            f"Expected a warning containing project path {_PROJECT_PATH!r} on stderr "
            f"for an untagged project, got: {result.stderr!r}"
        )
        assert "warning" in result.stderr.lower(), (
            f"Expected 'warning' in stderr for an untagged project, got: {result.stderr!r}"
        )

    def test_revision_as_tag_xml_still_produced_without_tag(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-tag`` produces XML output even when no exact tag exists.

        On a repo with no tagged commits, the manifest must still be output
        in XML format (original revisions preserved).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_REVISION_AS_TAG,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite failed.\n  stderr: {result.stderr!r}"
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected XML declaration in stdout even when no tags exist.\n  stdout: {result.stdout!r}"
        )
