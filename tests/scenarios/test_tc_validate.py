"""TC-validate scenarios from `docs/integration-testing.md` §27.

Each scenario exercises top-level `kanon validate` surface area.

Scenarios automated:
- TC-validate-01: validate xml --repo-root=<path>
- TC-validate-02: validate marketplace --repo-root=<path> (mk19-validate fixture)
- TC-validate-03: auto-detect repo root via git rev-parse
- TC-validate-04: rejected when neither flag nor git root works
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
# XML content constants
# ---------------------------------------------------------------------------

_VALID_XML_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <project name="proj" path=".packages/proj" remote="origin" revision="main" />\n'
    "</manifest>\n"
)

# A valid marketplace manifest: dest prefixed with ${CLAUDE_MARKETPLACES_DIR}
# so the marketplace validator accepts it (mirrors the VA-02 / MK-fixture pattern).
_VALID_MARKETPLACE_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <project name="mk19" path=".packages/mk19" remote="origin"'
    ' revision="refs/tags/ex/mk19/1.0.0">\n'
    '    <linkfile src="." dest="${CLAUDE_MARKETPLACES_DIR}/mk19" />\n'
    "  </project>\n"
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _init_committed_repo(
    repo_dir: pathlib.Path,
    files: dict[str, str],
    commit_message: str = "Add files",
) -> pathlib.Path:
    """Initialise a non-bare git repo, write files, and commit them."""
    init_git_work_dir(repo_dir)
    for relpath, content in files.items():
        target = repo_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        run_git(["add", relpath], repo_dir)
    run_git(["commit", "-m", commit_message], repo_dir)
    return repo_dir


def _build_mk19_validate_fixture(base: pathlib.Path) -> pathlib.Path:
    """Build a git repo that mirrors the mk19-validate fixture layout.

    Provides ``repo-specs/mk19-marketplace.xml`` with a valid marketplace
    manifest (dest prefixed with ``${CLAUDE_MARKETPLACES_DIR}``) so that
    ``kanon validate marketplace`` exits 0.

    Returns the repo root path.
    """
    repo_dir = base / "mk19-validate"
    return _init_committed_repo(
        repo_dir,
        {"repo-specs/mk19-marketplace.xml": _VALID_MARKETPLACE_MANIFEST},
        commit_message="mk19-validate fixture",
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestTCValidate:
    # ------------------------------------------------------------------
    # TC-validate-01: validate xml --repo-root=<path>
    # ------------------------------------------------------------------

    def test_tc_validate_01_validate_xml_repo_root(self, tmp_path: pathlib.Path) -> None:
        """TC-validate-01: kanon validate xml --repo-root <path> exits 0 for a valid repo."""
        repo_dir = _init_committed_repo(
            tmp_path / "tc-val-01",
            {"repo-specs/test.xml": _VALID_XML_MANIFEST},
            commit_message="TC-validate-01 manifests",
        )

        result = run_kanon("validate", "xml", "--repo-root", str(repo_dir))

        assert result.returncode == 0, (
            f"validate xml exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "valid" in combined.lower(), (
            f"Expected 'valid' in output: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    # ------------------------------------------------------------------
    # TC-validate-02: validate marketplace --repo-root=<path> (mk19-validate fixture)
    # ------------------------------------------------------------------

    def test_tc_validate_02_validate_marketplace_mk19_fixture(self, tmp_path: pathlib.Path) -> None:
        """TC-validate-02: kanon validate marketplace --repo-root uses mk19-validate fixture layout."""
        mk19_repo = _build_mk19_validate_fixture(tmp_path / "fixtures")

        result = run_kanon("validate", "marketplace", "--repo-root", str(mk19_repo))

        assert result.returncode == 0, (
            f"validate marketplace exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "passed" in combined.lower() or "valid" in combined.lower(), (
            f"Expected 'passed' or 'valid' in output: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    # ------------------------------------------------------------------
    # TC-validate-03: auto-detect via git rev-parse
    # ------------------------------------------------------------------

    def test_tc_validate_03_auto_detect_repo_root(self, tmp_path: pathlib.Path) -> None:
        """TC-validate-03: kanon validate xml without --repo-root auto-detects from git checkout."""
        repo_dir = _init_committed_repo(
            tmp_path / "tc-val-03",
            {"repo-specs/auto.xml": _VALID_XML_MANIFEST},
            commit_message="TC-validate-03 manifests",
        )

        # Run from inside the git repo; no --repo-root flag supplied.
        result = run_kanon("validate", "xml", cwd=repo_dir)

        assert result.returncode == 0, (
            f"validate xml exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "valid" in combined.lower(), (
            f"Expected 'valid' in output: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    # ------------------------------------------------------------------
    # TC-validate-04: rejected when neither flag nor git root works
    # ------------------------------------------------------------------

    def test_tc_validate_04_rejected_without_repo_root(self, tmp_path: pathlib.Path) -> None:
        """TC-validate-04: kanon validate xml from a non-git directory exits non-zero."""
        # tmp_path itself is not a git repo; no --repo-root is supplied.
        non_git_dir = tmp_path / "not-a-repo"
        non_git_dir.mkdir()

        result = run_kanon("validate", "xml", cwd=non_git_dir)

        assert result.returncode != 0, (
            f"Expected non-zero exit from non-git dir, got 0\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stderr.strip(), "Expected a non-empty stderr diagnostic message"
