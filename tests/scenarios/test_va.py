"""VA (Validate) scenarios from `docs/integration-testing.md` §12.

Each scenario exercises `kanon validate xml` or `kanon validate marketplace`
against on-disk git repos -- no network access required.

Scenarios automated:
- VA-01: Validate xml in a repo with manifests
- VA-02: Validate marketplace in a repo with marketplace manifests
- VA-03: Validate xml with --repo-root from outside the repo
- VA-04: Validate in empty directory (no repo-specs XML files)
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    init_git_work_dir,
    run_git,
    run_kanon,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_VALID_XML_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <project name="proj" path=".packages/proj" remote="origin" revision="main" />\n'
    "</manifest>\n"
)

_VALID_MARKETPLACE_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <project name="proj" path=".packages/proj" remote="r"'
    ' revision="refs/tags/ex/proj/1.0.0">\n'
    '    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />\n'
    "  </project>\n"
    "</manifest>\n"
)


def _init_committed_repo(
    repo_dir: pathlib.Path,
    files: dict[str, str],
    commit_message: str = "Add files",
) -> pathlib.Path:
    """Initialise a non-bare git repo, write files, and commit them.

    Returns the repo directory for convenience.
    """
    init_git_work_dir(repo_dir)
    for relpath, content in files.items():
        target = repo_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        run_git(["add", relpath], repo_dir)
    run_git(["commit", "-m", commit_message], repo_dir)
    return repo_dir


def _init_empty_committed_repo(repo_dir: pathlib.Path) -> pathlib.Path:
    """Initialise a non-bare git repo with a single empty commit."""
    init_git_work_dir(repo_dir)
    run_git(["commit", "--allow-empty", "-m", "empty repo"], repo_dir)
    return repo_dir


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestVA:
    def test_va_01_validate_xml_with_manifests(self, tmp_path: pathlib.Path) -> None:
        """VA-01: Validate xml in a repo containing a valid manifest XML file."""
        repo_dir = tmp_path / "test-va01"
        _init_committed_repo(
            repo_dir,
            {"repo-specs/test.xml": _VALID_XML_MANIFEST},
            commit_message="Add valid manifest",
        )

        result = run_kanon("validate", "xml", "--repo-root", str(repo_dir))

        assert result.returncode == 0, (
            f"kanon validate xml exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "valid" in combined, f"Expected 'valid' in output, got stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_va_02_validate_marketplace_with_manifests(self, tmp_path: pathlib.Path) -> None:
        """VA-02: Validate marketplace in a repo with marketplace manifests."""
        repo_dir = tmp_path / "test-va02"
        _init_committed_repo(
            repo_dir,
            {"repo-specs/test-marketplace.xml": _VALID_MARKETPLACE_MANIFEST},
            commit_message="Add valid marketplace manifest",
        )

        result = run_kanon("validate", "marketplace", "--repo-root", str(repo_dir))

        assert result.returncode == 0, (
            f"kanon validate marketplace exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "passed" in combined, (
            f"Expected 'passed' in output, got stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_va_03_validate_xml_with_repo_root_from_outside(self, tmp_path: pathlib.Path) -> None:
        """VA-03: Validate xml with --repo-root from outside the repo."""
        repo_dir = tmp_path / "test-va03"
        _init_committed_repo(
            repo_dir,
            {"repo-specs/another.xml": _VALID_XML_MANIFEST},
            commit_message="Add manifest",
        )

        # Run from a different directory, pointing --repo-root at the repo
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        result = run_kanon(
            "validate",
            "xml",
            "--repo-root",
            str(repo_dir),
            cwd=outside_dir,
        )

        assert result.returncode == 0, (
            f"kanon validate xml exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "valid" in combined, f"Expected 'valid' in output, got stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_va_04_validate_empty_repo_specs(self, tmp_path: pathlib.Path) -> None:
        """VA-04: Validate xml in a repo with an empty repo-specs directory exits 1."""
        repo_dir = tmp_path / "test-va04"
        # Create repo-specs directory but add no XML files, then empty commit
        repo_dir.mkdir(parents=True)
        init_git_work_dir(repo_dir)
        (repo_dir / "repo-specs").mkdir()
        run_git(["commit", "--allow-empty", "-m", "empty repo"], repo_dir)

        result = run_kanon("validate", "xml", "--repo-root", str(repo_dir))

        assert result.returncode == 1, (
            f"Expected exit code 1, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "No XML files found" in result.stderr, (
            f"Expected 'No XML files found' in stderr, got stderr={result.stderr!r}"
        )
