"""Verification tests for copied test files and fixture files.

Confirms that all test files from rpm-git-repo/tests/ have been copied to
tests/unit/repo/ and all fixture files have been copied to tests/fixtures/repo/.

AC-FUNC-001: All 111 non-conftest Python test files copied to tests/unit/repo/
AC-FUNC-002: All fixture files copied to tests/fixtures/repo/
AC-FUNC-003: Directory structure preserved (subdirectories maintained)
AC-FUNC-004: File content matches source (verbatim copy, modulo ruff formatting)
AC-TEST-001: test_repo_test_files_exist verifies test file presence
AC-TEST-002: test_repo_fixture_files_exist verifies fixture file presence
AC-TEST-003: test_repo_file_content_matches_source verifies content integrity
"""

import hashlib
import os
import pathlib

import pytest

from tests.unit.repo.conftest import ruff_format_source, strip_noqa_annotations

# Resolve the kanon repository root (4 levels up from this file:
# tests/unit/repo/test_file_copy_verification.py -> tests/unit/repo/ ->
# tests/unit/ -> tests/ -> kanon/)
_KANON_REPO_ROOT = pathlib.Path(__file__).parents[3]

# Target directory where rpm-git-repo test files were copied.
_TEST_TARGET_DIR = _KANON_REPO_ROOT / "tests" / "unit" / "repo"

# Target directory where rpm-git-repo fixture files were copied.
_FIXTURE_TARGET_DIR = _KANON_REPO_ROOT / "tests" / "fixtures" / "repo"

# All 111 Python test-file paths (relative to rpm-git-repo/tests/) that should
# exist in tests/unit/repo/ after the verbatim copy.
# conftest.py is excluded because overwriting the existing kanon-specific
# tests/unit/repo/conftest.py would break existing infrastructure tests.
# The kanon conftest is preserved; T2 (E0-F5-S1-T2) creates the repo conftest.
_COPIED_TEST_FILES = [
    "fixtures/linter-test-bad.py",
    "functional/__init__.py",
    "functional/test_features.py",
    "test_abandon_massive.py",
    "test_branches_coverage.py",
    "test_checkout_massive.py",
    "test_cherrypick_coverage.py",
    "test_color.py",
    "test_command.py",
    "test_conftest_fixtures.py",
    "test_diffmanifests_deep.py",
    "test_download_coverage.py",
    "test_editor.py",
    "test_envsubst_massive.py",
    "test_error.py",
    "test_event_log_massive.py",
    "test_event_log.py",
    "test_fetch.py",
    "test_fixture_files.py",
    "test_forall_deep.py",
    "test_git_command.py",
    "test_gitconfig_coverage.py",
    "test_git_config.py",
    "test_git_refs.py",
    "test_git_superproject.py",
    "test_git_trace2_event_log.py",
    "test_grep_deep.py",
    "test_harness_smoke.py",
    "test_hooks.py",
    "test_info_deep.py",
    "test_init_deep.py",
    "test_list_massive.py",
    "test_main_coverage.py",
    "test_main_init_download_boost.py",
    "test_main.py",
    "test_makefile_lint_format.py",
    "test_makefile_structure.py",
    "test_makefile_test_targets.py",
    "test_manifest_coverage_boost.py",
    "test_manifest_deep.py",
    "test_manifest_massive.py",
    "test_manifest_subcmd_massive.py",
    "test_manifest_xml.py",
    "test_medium_files_boost.py",
    "test_overview_massive.py",
    "test_pager.py",
    "test_platform_utils.py",
    "test_progress.py",
    "test_project_coverage_boost.py",
    "test_project_deep_boost.py",
    "test_project_deep.py",
    "test_project_final_boost.py",
    "test_project_integration.py",
    "test_project_massive.py",
    "test_project_metaproject_boost.py",
    "test_project_methods.py",
    "test_project.py",
    "test_project_sync.py",
    "test_prune_massive.py",
    "test_rebase_coverage.py",
    "test_remaining_coverage_boost.py",
    "test_repo_logging.py",
    "test_repo_trace.py",
    "test_ruff_config.py",
    "test_selfupdate_massive.py",
    "test_small_files_boost.py",
    "test_ssh_deep.py",
    "test_ssh.py",
    "test_stage_coverage.py",
    "test_stage_massive.py",
    "test_start_coverage.py",
    "test_status_coverage.py",
    "test_status_massive.py",
    "test_subcmds_abandon.py",
    "test_subcmds_branches.py",
    "test_subcmds_checkout.py",
    "test_subcmds_cherry_pick.py",
    "test_subcmds_diffmanifests.py",
    "test_subcmds_diff.py",
    "test_subcmds_download.py",
    "test_subcmds_envsubst.py",
    "test_subcmds_forall.py",
    "test_subcmds_gc.py",
    "test_subcmds_grep.py",
    "test_subcmds_help.py",
    "test_subcmds_info.py",
    "test_subcmds_init.py",
    "test_subcmds_list.py",
    "test_subcmds_manifest.py",
    "test_subcmds_overview.py",
    "test_subcmds_prune.py",
    "test_subcmds.py",
    "test_subcmds_rebase.py",
    "test_subcmds_selfupdate.py",
    "test_subcmds_smartsync.py",
    "test_subcmds_stage.py",
    "test_subcmds_start.py",
    "test_subcmds_status.py",
    "test_subcmds_sync.py",
    "test_subcmds_upload.py",
    "test_subcmds_version.py",
    "test_superproject_deep.py",
    "test_sync_coverage_boost.py",
    "test_sync_deep_boost.py",
    "test_sync_deep.py",
    "test_sync_massive.py",
    "test_upload_deep.py",
    "test_version_constraints.py",
    "test_version_massive.py",
    "test_wrapper.py",
    "test_yamllint_config.py",
]

# All fixture file paths (relative to rpm-git-repo/tests/fixtures/) that should
# exist in tests/fixtures/repo/ after the verbatim copy.
_COPIED_FIXTURE_FILES = [
    ".gitignore",
    ".repo_not.present.gitconfig.json",
    ".repo_test.gitconfig.json",
    "README.md",
    "linter-test-bad.md",
    "linter-test-bad.py",
    "linter-test-bad.yml",
    "sample-manifest.xml",
    "sample-project-config.json",
    "test.gitconfig",
    "version_constraints_data.json",
]


def _get_rpm_tests_source_dir() -> pathlib.Path:
    """Return the rpm-git-repo/tests/ source directory.

    Skips the calling test via pytest.skip() when RPM_GIT_REPO_PATH is not set,
    so tests are gracefully skipped rather than erroring in environments without
    the source repository.

    Returns:
        The resolved rpm-git-repo/tests/ directory path.

    Raises:
        RuntimeError: If RPM_GIT_REPO_PATH is set but does not point to a valid
            rpm-git-repo directory, or if the tests/ subdirectory does not exist.
    """
    raw = os.environ.get("RPM_GIT_REPO_PATH")
    if not raw:
        pytest.skip("RPM_GIT_REPO_PATH is not set -- skipping content-match tests")
    source_root = pathlib.Path(raw)
    if not source_root.is_dir():
        raise RuntimeError(f"RPM_GIT_REPO_PATH={raw!r} does not point to an existing directory.")
    tests_dir = source_root / "tests"
    if not tests_dir.is_dir():
        raise RuntimeError(f"Expected tests/ directory at {tests_dir} but it does not exist.")
    return tests_dir


def _sha256(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of the file at path.

    Args:
        path: Absolute path to the file to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest string.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_python(path: pathlib.Path) -> str:
    """Return a canonical normalized form of a Python source file.

    Applies ruff format and strips noqa annotations so that pure style
    differences between the source (rpm-git-repo) and the copy (kanon) do
    not cause spurious content-mismatch failures.

    Args:
        path: Absolute path to the Python source file.

    Returns:
        Normalized source string suitable for equality comparison.
    """
    return strip_noqa_annotations(ruff_format_source(path.read_bytes()))


# ---------------------------------------------------------------------------
# AC-TEST-001: test_repo_test_files_exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", _COPIED_TEST_FILES)
def test_repo_test_files_exist(relative_path: str) -> None:
    """Verify each copied test file exists under tests/unit/repo/.

    AC-FUNC-001: All test Python files from rpm-git-repo/tests/ are present
    in tests/unit/repo/ preserving the original directory structure.

    Args:
        relative_path: Path relative to rpm-git-repo/tests/ (and thus to
            tests/unit/repo/) where the copied file should reside.
    """
    target = _TEST_TARGET_DIR / relative_path
    assert target.is_file(), (
        f"Expected copied test file {target} to exist but it is missing. "
        f"Copy {relative_path!r} from rpm-git-repo/tests/ to tests/unit/repo/."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: test_repo_fixture_files_exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", _COPIED_FIXTURE_FILES)
def test_repo_fixture_files_exist(relative_path: str) -> None:
    """Verify each fixture file exists under tests/fixtures/repo/.

    AC-FUNC-002: All files from rpm-git-repo/tests/fixtures/ are present
    under tests/fixtures/repo/.

    Args:
        relative_path: Path relative to rpm-git-repo/tests/fixtures/ (and
            thus to tests/fixtures/repo/) where the copied file should reside.
    """
    target = _FIXTURE_TARGET_DIR / relative_path
    assert target.is_file(), (
        f"Expected copied fixture file {target} to exist but it is missing. "
        f"Copy {relative_path!r} from rpm-git-repo/tests/fixtures/ to tests/fixtures/repo/."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: test_repo_file_content_matches_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", _COPIED_TEST_FILES)
def test_repo_test_file_content_matches_source(relative_path: str) -> None:
    """Verify each copied test file has content equivalent to its source.

    AC-FUNC-004: File content matches source (verbatim copy modulo ruff
    formatting).  Both source and target are normalized through ruff format
    and noqa-annotation stripping before comparison so that pure style
    differences (quote style, trailing commas) do not cause false failures.

    Args:
        relative_path: Path relative to rpm-git-repo/tests/ identifying the
            source and target file.
    """
    source_tests_dir = _get_rpm_tests_source_dir()
    source = source_tests_dir / relative_path
    target = _TEST_TARGET_DIR / relative_path

    if not source.is_file():
        raise RuntimeError(
            f"Source file {source} does not exist in rpm-git-repo. "
            f"Verify RPM_GIT_REPO_PATH={source_tests_dir.parent!r} is correct."
        )
    if not target.is_file():
        pytest.fail(
            f"Target file {target} does not exist. "
            f"Copy {relative_path!r} from rpm-git-repo/tests/ to tests/unit/repo/ first."
        )

    source_normalized = _normalize_python(source)
    target_normalized = _normalize_python(target)
    assert source_normalized == target_normalized, (
        f"Content mismatch for {relative_path!r} after normalization. "
        f"The copy at {target} must preserve all source content -- "
        f"only ruff-format style differences are permitted in T1."
    )


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", _COPIED_FIXTURE_FILES)
def test_repo_fixture_file_content_matches_source(relative_path: str) -> None:
    """Verify each copied fixture file has identical raw content to its source.

    AC-FUNC-004: Fixture file content matches source (verbatim copy).
    Fixture files are not Python source, so raw SHA-256 checksums are used
    to verify that no byte-level changes occurred during the copy.

    Args:
        relative_path: Path relative to rpm-git-repo/tests/fixtures/ identifying
            the source and target file.
    """
    source_tests_dir = _get_rpm_tests_source_dir()
    source = source_tests_dir / "fixtures" / relative_path
    target = _FIXTURE_TARGET_DIR / relative_path

    if not source.is_file():
        raise RuntimeError(
            f"Source fixture {source} does not exist in rpm-git-repo. "
            f"Verify RPM_GIT_REPO_PATH={source_tests_dir.parent!r} is correct."
        )
    if not target.is_file():
        pytest.fail(
            f"Target fixture {target} does not exist. "
            f"Copy {relative_path!r} from rpm-git-repo/tests/fixtures/ to tests/fixtures/repo/ first."
        )

    source_digest = _sha256(source)
    target_digest = _sha256(target)
    assert source_digest == target_digest, (
        f"Content mismatch for fixture {relative_path!r}: "
        f"source SHA-256={source_digest!r}, target SHA-256={target_digest!r}. "
        f"Fixture files must be copied verbatim -- no modifications allowed."
    )
