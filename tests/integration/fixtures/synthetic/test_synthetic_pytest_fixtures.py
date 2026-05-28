"""Integration test: pytest fixture ergonomics for synthetic fixture helpers.

Verifies that the shared pytest fixtures ``synthetic_drift_repo`` and
``synthetic_upgrade_versioned_repo`` (defined in
``tests/integration/fixtures/synthetic/conftest.py``) are auto-discovered
by pytest and that each returned bare-repo path is accepted by ``repo init``
with exit code 0.

These fixture-consumer tests are the failing-test-first guard for E36-F1-S1-T3:
they FAIL before ``conftest.py`` is authored (FixtureLookupError) and PASS
after ``conftest.py`` is present.

AC-TEST-001, AC-TEST-002 (T3)
"""

import pathlib
import subprocess

import pytest

from kanon_cli.repo.main import run_from_args


_REQUIRED_TAGS = ("0.1.0", "0.2.0", "1.0.0")


@pytest.mark.integration
def test_synthetic_drift_repo_fixture_returns_repo_init_acceptable_bare(
    synthetic_drift_repo: pathlib.Path,
) -> None:
    """Verify synthetic_drift_repo fixture returns a bare repo accepted by repo init.

    Steps:
    1. Receive the bare-repo path from the pytest fixture.
    2. Assert the path exists and is a directory.
    3. Verify structural correctness of manifest.xml: <remote> and <default>
       appear before any <project>.
    4. Run ``repo init`` against the bare repo URL with branch=main and
       manifest=manifest.xml via the vendored repo (run_from_args).
    5. Assert that run_from_args returns without raising RepoCommandError
       (i.e., repo init accepted the manifest -- exit code 0).

    The test fails with FixtureLookupError before conftest.py is authored
    (RED) and passes after conftest.py defines the fixture (GREEN).
    """
    assert isinstance(synthetic_drift_repo, pathlib.Path), (
        f"synthetic_drift_repo must be a pathlib.Path; got {type(synthetic_drift_repo)!r}"
    )
    assert synthetic_drift_repo.exists(), f"synthetic_drift_repo path must exist: {synthetic_drift_repo!r}"
    assert synthetic_drift_repo.is_dir(), f"synthetic_drift_repo path must be a directory: {synthetic_drift_repo!r}"

    # Verify the manifest structural correctness before repo init
    manifest_text = _read_manifest_text_from_bare(synthetic_drift_repo)
    remote_pos = manifest_text.find("<remote ")
    default_pos = manifest_text.find("<default ")
    project_pos = manifest_text.find("<project ")
    assert remote_pos != -1, f"manifest.xml must contain a <remote> element; content:\n{manifest_text}"
    assert default_pos != -1, f"manifest.xml must contain a <default> element; content:\n{manifest_text}"
    assert project_pos != -1, f"manifest.xml must contain a <project> element; content:\n{manifest_text}"
    assert remote_pos < project_pos, (
        f"<remote> (offset {remote_pos}) must appear before <project> (offset {project_pos})"
    )
    assert default_pos < project_pos, (
        f"<default> (offset {default_pos}) must appear before <project> (offset {project_pos})"
    )

    client_dir = synthetic_drift_repo.parent / "fixture-drift-client"
    client_dir.mkdir(parents=True, exist_ok=True)
    repo_dot_dir = str(client_dir / ".repo")

    # run_from_args raises RepoCommandError on non-zero exit; returning normally
    # confirms the manifest schema was accepted (exit code 0).
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            f"file://{synthetic_drift_repo}",
            "-b",
            "main",
            "-m",
            "manifest.xml",
        ],
        repo_dir=repo_dot_dir,
    )


@pytest.mark.integration
def test_synthetic_upgrade_versioned_repo_fixture_returns_tagged_bare(
    synthetic_upgrade_versioned_repo: pathlib.Path,
) -> None:
    """Verify synthetic_upgrade_versioned_repo fixture returns a tagged bare repo accepted by repo init.

    Steps:
    1. Receive the bare-repo path from the pytest fixture.
    2. Assert the path exists and is a directory.
    3. Assert the bare repo carries all documented annotated tags
       (0.1.0, 0.2.0, 1.0.0) via ``git tag --list``.
    4. Run ``repo init`` against the bare repo URL with branch=main and
       manifest=manifest.xml via the vendored repo (run_from_args).
    5. Assert that run_from_args returns without raising RepoCommandError
       (i.e., repo init accepted the manifest -- exit code 0).

    The test fails with FixtureLookupError before conftest.py is authored
    (RED) and passes after conftest.py defines the fixture (GREEN).
    """
    assert isinstance(synthetic_upgrade_versioned_repo, pathlib.Path), (
        f"synthetic_upgrade_versioned_repo must be a pathlib.Path; got {type(synthetic_upgrade_versioned_repo)!r}"
    )
    assert synthetic_upgrade_versioned_repo.exists(), (
        f"synthetic_upgrade_versioned_repo path must exist: {synthetic_upgrade_versioned_repo!r}"
    )
    assert synthetic_upgrade_versioned_repo.is_dir(), (
        f"synthetic_upgrade_versioned_repo path must be a directory: {synthetic_upgrade_versioned_repo!r}"
    )

    # Assert all documented annotated tags are present
    actual_tags = _list_git_tags(synthetic_upgrade_versioned_repo)
    for expected_tag in _REQUIRED_TAGS:
        assert expected_tag in actual_tags, (
            f"bare repo at {synthetic_upgrade_versioned_repo!r} must carry annotated tag "
            f"{expected_tag!r}; found tags: {sorted(actual_tags)!r}"
        )

    client_dir = synthetic_upgrade_versioned_repo.parent / "fixture-upgrade-client"
    client_dir.mkdir(parents=True, exist_ok=True)
    repo_dot_dir = str(client_dir / ".repo")

    # run_from_args raises RepoCommandError on non-zero exit; returning normally
    # confirms the manifest schema was accepted (exit code 0).
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            f"file://{synthetic_upgrade_versioned_repo}",
            "-b",
            "main",
            "-m",
            "manifest.xml",
        ],
        repo_dir=repo_dot_dir,
    )


def _read_manifest_text_from_bare(bare_path: pathlib.Path) -> str:
    """Return the UTF-8 text of manifest.xml from a bare git repository.

    Uses ``git show HEAD:manifest.xml`` so no working-tree checkout is required.

    Args:
        bare_path: Absolute path to a bare git repository.

    Returns:
        UTF-8 text of manifest.xml at HEAD.

    Raises:
        RuntimeError: If git show exits non-zero.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:manifest.xml"],
        cwd=str(bare_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git show HEAD:manifest.xml failed in {bare_path!r}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    return result.stdout


def _list_git_tags(bare_path: pathlib.Path) -> set[str]:
    """Return the set of tag names from a bare git repository.

    Uses ``git tag --list`` so no working-tree checkout is required.

    Args:
        bare_path: Absolute path to a bare git repository.

    Returns:
        Set of tag name strings.

    Raises:
        RuntimeError: If git tag exits non-zero.
    """
    result = subprocess.run(
        ["git", "tag", "--list"],
        cwd=str(bare_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git tag --list failed in {bare_path!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}
