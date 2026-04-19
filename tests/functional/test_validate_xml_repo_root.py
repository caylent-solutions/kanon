"""Functional tests for `kanon validate xml` happy-path and repo-root resolution.

Covers:
  AC-TEST-001 -- auto-detect repo root via git when --repo-root is omitted
  AC-TEST-002 -- explicit absolute --repo-root is used as-is
  AC-TEST-003 -- --repo-root . resolves to CWD
  AC-TEST-004 -- --repo-root /nonexistent exits 1 with "--repo-root directory not found"
  AC-FUNC-001 -- --repo-root is resolved to absolute at the CLI boundary
  AC-CHANNEL-001 -- stdout vs stderr channel discipline is verified
"""

import textwrap
from pathlib import Path

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_EMAIL = "validate-xml-test@example.com"
_GIT_USER_NAME = "Validate XML Test"
_VALID_MANIFEST_CONTENT = textwrap.dedent("""\
    <manifest>
      <remote name="origin" fetch="https://example.com" />
      <project name="proj" path=".packages/proj" remote="origin" revision="main" />
    </manifest>
""")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# NOTE: _write_xml duplicates the same helper in test_validate_lifecycle.py.
# Consolidation into conftest.py requires updating that file too, which is
# outside this task's Changes Manifest. Tracked as a follow-up DRY cleanup.


def _write_xml(path: Path, content: str) -> Path:
    """Write an XML file, creating parent directories as needed.

    Args:
        path: Target file path.
        content: XML body (without the XML declaration header).

    Returns:
        The path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


def _init_git_repo(directory: Path) -> None:
    """Initialise a minimal git repo with a committed file.

    Args:
        directory: Directory to initialise.
    """
    _git(["init", "-b", "main"], cwd=directory)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=directory)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=directory)
    placeholder = directory / ".gitkeep"
    placeholder.write_text("")
    _git(["add", ".gitkeep"], cwd=directory)
    _git(["commit", "-m", "Initial commit"], cwd=directory)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestValidateXmlRepoRootResolution:
    """Tests for repo-root resolution in `kanon validate xml`."""

    def test_auto_detects_repo_root_via_git(self, tmp_path: Path) -> None:
        """AC-TEST-001: omitting --repo-root auto-detects root via git.

        The command is run with cwd set to a subdirectory of a git repo that
        contains a valid repo-specs/ tree. Without --repo-root the CLI must
        invoke git rev-parse --show-toplevel internally to resolve the root.
        """
        repo_root = tmp_path / "myrepo"
        repo_root.mkdir()
        _init_git_repo(repo_root)

        _write_xml(repo_root / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        # Run from a subdirectory so we confirm git traversal finds the root.
        subdir = repo_root / "some" / "nested" / "dir"
        subdir.mkdir(parents=True)

        result = _run_kanon("validate", "xml", cwd=subdir)

        assert result.returncode == 0, (
            f"Expected exit 0 for valid manifest with git auto-detect.\n"
            f"stdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
        # Valid summary goes to stdout, not stderr
        assert "valid" in result.stdout.lower(), f"Expected success message in stdout.\nstdout: {result.stdout!r}"
        assert result.stderr == "", f"AC-CHANNEL-001: no stderr output expected on success.\nstderr: {result.stderr!r}"

    def test_explicit_absolute_repo_root(self, tmp_path: Path) -> None:
        """AC-TEST-002 + AC-FUNC-001: --repo-root /abs/dir uses that directory directly.

        AC-TEST-002: the CLI must accept and use an explicit absolute path.
        AC-FUNC-001: the CLI resolves paths to absolute at the CLI boundary --
        verified by passing a relative path from a subprocess cwd that differs
        from the actual repo-root parent, and confirming the resolved absolute
        form appears in the error message when the path does not exist. This
        assertion FAILS if the production code stops calling .resolve().
        """
        repo_root = tmp_path / "explicit_root"
        repo_root.mkdir()
        _write_xml(repo_root / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        # AC-TEST-002: explicit absolute path succeeds.
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"Expected exit 0 for explicit absolute --repo-root.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "valid" in result.stdout.lower(), f"Expected success message in stdout.\nstdout: {result.stdout!r}"
        assert result.stderr == "", f"AC-CHANNEL-001: no stderr output expected on success.\nstderr: {result.stderr!r}"

        # AC-FUNC-001: verify that the CLI resolves a relative --repo-root to
        # absolute at the CLI boundary. We pass a relative nonexistent path from
        # tmp_path as cwd; the production code must call .resolve() so that the
        # error message contains the absolute form. If .resolve() is removed the
        # error message would show the bare relative name, and this assertion fails.
        relative_name = "nonexistent_sub"
        absolute_form = str(tmp_path / relative_name)
        resolution_check = _run_kanon("validate", "xml", "--repo-root", relative_name, cwd=tmp_path)
        assert resolution_check.returncode == 1, (
            f"AC-FUNC-001: expected exit 1 for nonexistent relative --repo-root.\nstderr: {resolution_check.stderr!r}"
        )
        assert absolute_form in resolution_check.stderr, (
            f"AC-FUNC-001: expected absolute path {absolute_form!r} in stderr, "
            f"confirming the CLI resolved the relative argument to absolute.\n"
            f"stderr: {resolution_check.stderr!r}"
        )

    def test_dot_repo_root_resolves_to_cwd(self, tmp_path: Path) -> None:
        """AC-TEST-003: --repo-root . resolves to the process CWD.

        The CLI must resolve a relative '.' argument to an absolute path so
        downstream pathlib operations work correctly.
        """
        repo_root = tmp_path / "dot_root"
        repo_root.mkdir()
        _write_xml(repo_root / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        result = _run_kanon("validate", "xml", "--repo-root", ".", cwd=repo_root)

        assert result.returncode == 0, (
            f"Expected exit 0 when --repo-root . resolves to cwd.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "valid" in result.stdout.lower(), f"Expected success message in stdout.\nstdout: {result.stdout!r}"
        assert result.stderr == "", f"AC-CHANNEL-001: no stderr output expected on success.\nstderr: {result.stderr!r}"

    def test_nonexistent_repo_root_exits_one_with_message(self, tmp_path: Path) -> None:
        """AC-TEST-004: --repo-root /nonexistent exits 1 with --repo-root directory not found.

        The CLI must fail fast with exit code 1 and an error message that
        contains the phrase '--repo-root directory not found'. The error must
        go to stderr, not stdout.
        """
        nonexistent = tmp_path / "does_not_exist"

        result = _run_kanon("validate", "xml", "--repo-root", str(nonexistent))

        assert result.returncode == 1, (
            f"Expected exit code 1 for nonexistent --repo-root.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # AC-CHANNEL-001: error message must appear on stderr
        assert "--repo-root directory not found" in result.stderr, (
            f"AC-TEST-004 + AC-CHANNEL-001: expected '--repo-root directory not found' in stderr.\n"
            f"stderr: {result.stderr!r}"
        )
        assert "--repo-root directory not found" not in result.stdout, (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )
