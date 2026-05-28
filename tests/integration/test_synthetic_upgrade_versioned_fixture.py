"""Integration test: synthetic.upgrade_versioned fixture helper schema-acceptance gate.

Verifies that the `create_upgrade_versioned_repo_fixture` helper emits a
manifest.xml that `repo init` accepts without parse errors, and that the bare
repo carries the documented 3-tag annotated set (0.1.0, 0.2.0, 1.0.0). This
is the spec-prescribed failing-test-first guard for the <remote> + <default>
declaration requirement described in spec §4 E36, row 80 (upgrade-versioned-repo).

AC-TEST-001, AC-TEST-002
"""

import pathlib
import subprocess

import pytest

from kanon_cli.repo.main import run_from_args
from tests.integration.fixtures.synthetic.upgrade_versioned import (
    create_upgrade_versioned_repo_fixture,
)

_REQUIRED_TAGS = ("0.1.0", "0.2.0", "1.0.0")


@pytest.mark.integration
def test_upgrade_versioned_manifest_xml_includes_remote_and_default_so_repo_init_accepts_it(
    tmp_path: pathlib.Path,
) -> None:
    """Invoke create_upgrade_versioned_repo_fixture and verify repo init accepts the manifest.

    Steps:
    1. Materialise the bare repo via create_upgrade_versioned_repo_fixture.
    2. Read the raw manifest.xml bytes from the bare repo and verify structural
       correctness: <remote> and <default> appear before any <project>,
       and the fetch URL uses the RFC 6761 .invalid TLD.
    3. Verify the bare repo carries the documented 3 annotated tags
       (0.1.0, 0.2.0, 1.0.0) via `git tag --list`.
    4. Create a fresh client directory.
    5. Run `repo init` against the bare repo URL with branch=main and
       manifest=manifest.xml via the vendored repo (run_from_args).
    6. Assert that run_from_args returns without raising RepoCommandError
       (i.e., the manifest schema was accepted -- exit code 0).

    The test is the spec-prescribed failing-test-first schema-acceptance
    gate: before upgrade_versioned.py is authored it must fail with
    ModuleNotFoundError; after upgrade_versioned.py is authored it must pass.
    """
    bare_path = create_upgrade_versioned_repo_fixture(tmp_path)

    # Read the manifest from the bare repo and verify structural correctness
    # using byte-level string checks (no XML parser required for controlled
    # fixture content -- avoids B314 bandit issue on untrusted-XML scanner).
    manifest_text = _read_manifest_text_from_bare(bare_path)

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
    assert ".invalid" in manifest_text, (
        f"<remote fetch> URL must use the RFC 6761 .invalid TLD; content:\n{manifest_text}"
    )

    # Assert the bare repo carries all documented annotated tags.
    actual_tags = _list_git_tags(bare_path)
    for expected_tag in _REQUIRED_TAGS:
        assert expected_tag in actual_tags, (
            f"bare repo at {bare_path!r} must carry annotated tag {expected_tag!r}; found tags: {sorted(actual_tags)!r}"
        )

    client_dir = tmp_path / "client"
    client_dir.mkdir()
    repo_dot_dir = str(client_dir / ".repo")

    # run_from_args raises RepoCommandError on non-zero exit; returning normally
    # confirms the manifest schema was accepted (exit code 0).
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            f"file://{bare_path}",
            "-b",
            "main",
            "-m",
            "manifest.xml",
        ],
        repo_dir=repo_dot_dir,
    )


def _read_manifest_text_from_bare(bare_path: pathlib.Path) -> str:
    """Return the UTF-8 text of manifest.xml from a bare git repository.

    Uses `git show HEAD:manifest.xml` so no working-tree checkout is required.

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

    Uses `git tag --list` so no working-tree checkout is required.

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
