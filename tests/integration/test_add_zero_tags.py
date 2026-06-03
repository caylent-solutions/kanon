"""Integration tests for the zero-PEP-440-tags loud-error path in kanon add.

Builds temporary local file:// manifest-repo fixtures (via git init + tag)
and invokes 'kanon add <entry>' (no @<spec>) via subprocess to exercise the
default-spec error path described in spec Section 4.2, step 4.

Covers:
- Zero-tags-total subcase: bare repo with no git tags.
- Zero-PEP-440-tags subcase: repo with only non-PEP-440 tag names.
- Explicit @main bypasses the default-spec error path (AC-FUNC-005,
  AC-CYCLE-001 evidence).
- Destination .kanon file is unchanged/absent after the error (AC-FUNC-004).

AC-TEST-002, AC-CYCLE-001
"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Spec-verbatim error string
# ---------------------------------------------------------------------------

_SPEC_ERROR_MSG = (
    "manifest repo has no PEP 440-valid tags; pin to a branch or SHA"
    " explicitly (e.g., 'kanon add foo@main') or ask the catalog author"
    " to publish a release tag."
)

# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Path to the static fixture files shipped with the test suite.
_FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "catalogs" / "zero-pep440-tags"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _create_manifest_repo(
    base: pathlib.Path,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo from the zero-pep440-tags fixture files.

    Copies the static fixture content (repo-specs/entry-a/entry-a-marketplace.xml)
    into a temporary git working tree, commits it, optionally applies the given
    tags, and returns a bare clone suitable for use as a file:// URL.

    Args:
        base: Parent directory for the temporary work and bare dirs.
        tags: Tag names to apply. Pass an empty list for the zero-tags-total subcase.

    Returns:
        Absolute path to the bare repo (a ``file://`` URL can be built from it).
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    # Copy fixture content into the working tree.
    dest_specs = work_dir / "repo-specs"
    shutil.copytree(str(_FIXTURE_DIR / "repo-specs"), str(dest_specs))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries from fixture"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Tag {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after 'kanon'.
        extra_env: Extra environment variables merged onto os.environ.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Integration tests -- parameterised across both subcases
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "tags,subcase",
    [
        ([], "zero-tags-total"),
        (
            ["release-2024", "ops-marker"],
            "zero-pep440-tags",
        ),
    ],
)
class TestAddZeroTagsErrorPath:
    """kanon add exits non-zero with spec-verbatim error for both zero-tags subcases."""

    def test_exits_nonzero(
        self,
        tmp_path: pathlib.Path,
        tags: list[str],
        subcase: str,
    ) -> None:
        """Exit code is non-zero when the manifest repo has no PEP 440-valid tags."""
        bare = _create_manifest_repo(tmp_path / subcase, tags=tags)
        workspace = tmp_path / f"ws-{subcase}"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode != 0, (
            f"subcase={subcase}: expected non-zero exit, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_stderr_contains_spec_verbatim_error(
        self,
        tmp_path: pathlib.Path,
        tags: list[str],
        subcase: str,
    ) -> None:
        """Stderr output contains the spec-verbatim error message."""
        bare = _create_manifest_repo(tmp_path / subcase, tags=tags)
        workspace = tmp_path / f"ws-{subcase}"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert _SPEC_ERROR_MSG in result.stderr, (
            f"subcase={subcase}: spec-verbatim error not found in stderr.\nstderr: {result.stderr!r}"
        )

    def test_kanon_file_absent_after_error(
        self,
        tmp_path: pathlib.Path,
        tags: list[str],
        subcase: str,
    ) -> None:
        """Destination .kanon file is absent (unchanged) after the error (AC-FUNC-004)."""
        bare = _create_manifest_repo(tmp_path / subcase, tags=tags)
        workspace = tmp_path / f"ws-{subcase}"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        assert not kanon_file.exists(), f"precondition: {kanon_file} must not exist before the run"

        _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert not kanon_file.exists(), (
            f"subcase={subcase}: .kanon file was created despite error; it must remain absent.\n"
            f"contents: {kanon_file.read_text()!r}"
        )


# ---------------------------------------------------------------------------
# Integration test -- zero-PEP-440 subcase lists skipped tag names
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddZeroPEP440TagsListsSkipped:
    """When tags exist but none are PEP 440-valid, stderr lists their names."""

    def test_skipped_tag_names_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """Non-PEP-440 tag names appear in stderr alongside the spec error."""
        bare = _create_manifest_repo(
            tmp_path / "non-pep440",
            tags=["release-2024", "ops-marker"],
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert "release-2024" in result.stderr or "ops-marker" in result.stderr, (
            f"expected skipped tag names in stderr, got: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CYCLE-001 evidence: explicit @main bypasses the default-spec error path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddExplicitSpecBypassesZeroTagsError:
    """Explicit @<spec> bypasses the default-spec error path (AC-FUNC-005, AC-CYCLE-001)."""

    def test_explicit_main_spec_succeeds(self, tmp_path: pathlib.Path) -> None:
        """'kanon add entry-a@main' succeeds even when the repo has no PEP 440-valid tags.

        The @main spec is resolved as a branch name, not via the default-spec
        PEP 440 tag selection. The command must exit 0 and write the triple.

        AC-CYCLE-001 evidence: explicit @<spec> variant.
        """
        # Build a repo with non-PEP-440 tags only.
        bare = _create_manifest_repo(
            tmp_path / "explicit-main",
            tags=["release-2024", "ops-marker"],
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a@main",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"expected exit 0 for explicit @main spec, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert kanon_file.exists(), "expected .kanon file to be created"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_ENTRY_A_URL=" in content or "KANON_SOURCE_entry_a_URL=" in content, (
            f"expected triple written to .kanon, got: {content!r}"
        )
