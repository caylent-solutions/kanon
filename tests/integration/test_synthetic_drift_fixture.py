"""Integration test: synthetic.drift fixture helper schema-acceptance gate.

Verifies that the `create_drift_fixture` helper emits a manifest.xml
that `repo init` accepts without parse errors. This is the spec-prescribed
failing-test-first guard for the <remote> + <default> declaration requirement
described in spec §4 E36.

AC-TEST-001, AC-TEST-002, AC-CYCLE-001
"""

import pathlib
import subprocess

import pytest

from kanon_cli.repo.main import run_from_args
from tests.integration.fixtures.synthetic.drift import create_drift_fixture


@pytest.mark.integration
def test_drift_manifest_xml_includes_remote_and_default_so_repo_init_accepts_it(
    tmp_path: pathlib.Path,
) -> None:
    """Invoke create_drift_fixture and verify repo init accepts the manifest.

    Steps:
    1. Materialise the bare repo via create_drift_fixture.
    2. Read the raw manifest.xml bytes from the bare repo and verify structural
       correctness: <remote> and <default> appear before any <project>,
       and the fetch URL uses the RFC 6761 .invalid TLD.
    3. Create a fresh client directory.
    4. Run `repo init` against the bare repo URL with branch=main and
       manifest=manifest.xml via the vendored repo (run_from_args).
    5. Assert that run_from_args returns without raising RepoCommandError
       (i.e., the manifest schema was accepted -- exit code 0).

    The test is the spec-prescribed failing-test-first schema-acceptance
    gate: before drift.py is authored it must fail with ModuleNotFoundError;
    after drift.py is authored it must pass.
    """
    bare_path = create_drift_fixture(tmp_path)

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
