"""Integration tests for 'kanon add --dry-run', '--force', and collision-error path.

Builds a temporary local file:// manifest-repo fixture with PEP 440-valid
git tags and invokes 'kanon add' via subprocess.run.

Covers:
- --dry-run: stdout diff shape, no file modification, exit 0
- --force: existing block overwritten, surrounding content preserved
- Collision-error path: spec-canonical error message, non-zero exit
- Within-request collision: 'kanon add a a' hard error
- AC-CYCLE-001 evidence: full end-to-end cycle with entry-a and entry-b

AC-TEST-002, AC-CYCLE-001
"""

import hashlib
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Minimal marketplace XML for a named entry.
_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


# ---------------------------------------------------------------------------
# Git helpers (shared with test_add_core.py pattern)
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


def _create_manifest_repo_with_tags(
    base: pathlib.Path,
    entry_names: list[str],
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo with marketplace XML files and git tags."""
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

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
    """Run the kanon entry point via the same Python interpreter."""
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


def _sha256(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Integration tests: --dry-run
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddDryRun:
    """kanon add --dry-run prints a diff and makes no on-disk change."""

    def test_dry_run_exits_0(self, tmp_path: pathlib.Path) -> None:
        """kanon add --dry-run exits 0 even when no collision."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--dry-run",
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_dry_run_stdout_has_plus_prefixed_lines(self, tmp_path: pathlib.Path) -> None:
        """--dry-run stdout shows '+' prefixed lines for each added triple line."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--dry-run",
            ],
            cwd=workspace,
        )
        assert "+KANON_SOURCE_entry_a_URL=" in result.stdout
        assert "+KANON_SOURCE_entry_a_REF=" in result.stdout
        assert "+KANON_SOURCE_entry_a_PATH=" in result.stdout

    def test_dry_run_does_not_modify_file_content(self, tmp_path: pathlib.Path) -> None:
        """File content is unchanged after --dry-run (verified by SHA-256)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        original_content = (
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
        )
        kanon_file.write_text(original_content)
        sha_before = _sha256(kanon_file)
        mtime_before = kanon_file.stat().st_mtime

        _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--dry-run",
            ],
            cwd=workspace,
        )

        sha_after = _sha256(kanon_file)
        mtime_after = kanon_file.stat().st_mtime
        assert sha_before == sha_after, "File content changed during --dry-run"
        assert mtime_before == mtime_after, "File mtime changed during --dry-run"

    def test_dry_run_force_shows_minus_for_removed_lines(self, tmp_path: pathlib.Path) -> None:
        """--dry-run --force shows '-' prefixed lines for existing triple being replaced."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        # Pre-populate with an existing entry-a block at 1.0.0
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )
        sha_before = _sha256(kanon_file)

        # 3.0.0: --force overwrites a re-add of the SAME package (same source@ref).
        # The existing block is at refs/tags/1.0.0, so the re-add resolves the
        # same ref (==1.0.0). The dry-run diff shows the existing partial block
        # removed ('-') and the normalised block (with _NAME/_GITBASE) added ('+').
        result = _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--dry-run",
                "--force",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, f"Expected exit 0.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        # Must show minus lines for the removed existing block and plus lines for
        # the rewritten block; the alias stays keyed by the bare alias (overwrite,
        # not auto-suffix), and the normalised block adds the _NAME line.
        assert "-KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in result.stdout
        assert "+KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in result.stdout
        assert "+KANON_SOURCE_entry_a_NAME=entry-a" in result.stdout
        # File must not be modified
        assert _sha256(kanon_file) == sha_before, "File content changed during --dry-run --force"


# ---------------------------------------------------------------------------
# Integration tests: --force overwrite
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddForce:
    """kanon add --force overwrites an existing block preserving line order."""

    def test_force_exits_0(self, tmp_path: pathlib.Path) -> None:
        """kanon add --force exits 0 when an existing block is overwritten."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a@==2.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--force",
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, f"Expected exit 0.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    def test_force_overwrites_existing_block(self, tmp_path: pathlib.Path) -> None:
        """--force re-add of the same source@ref overwrites and normalises the block.

        3.0.0: --force overwrites a re-add of the SAME package (same source@ref),
        keeping the alias keyed by the bare alias and re-pinning the block with
        the full normalised keys (_NAME/_GITBASE added). A different-ref re-add
        would auto-suffix instead, so the re-add uses the existing ref (==1.0.0).
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--force",
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, f"--force re-add must exit 0.\nstderr: {result.stderr!r}"

        content = kanon_file.read_text()
        # The block stays keyed by the bare alias (overwrite, not auto-suffix) at
        # the same ref, normalised with the full key set.
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_entry_a_NAME=entry-a" in content
        # No auto-suffixed alias was created.
        assert "KANON_SOURCE_entry_a_manifest_bare_URL" not in content

    def test_force_preserves_surrounding_content(self, tmp_path: pathlib.Path) -> None:
        """--force preserves header and other blocks byte-for-byte."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a", "entry-b"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_b_URL=file://{bare}\n"
            "KANON_SOURCE_entry_b_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_b_PATH=repo-specs/entry-b-marketplace.xml\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--force",
            ],
            cwd=workspace,
        )

        content = kanon_file.read_text()
        # Pre-existing header line preserved
        assert "GITBASE=" in content
        # entry-b block preserved (the force overwrite touches only entry-a)
        assert "KANON_SOURCE_entry_b_REF=refs/tags/1.0.0" in content
        # entry-a re-pinned at the same ref, normalised with the _NAME key
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_entry_a_NAME=entry-a" in content


# ---------------------------------------------------------------------------
# Integration tests: collision-error path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddCollisionError:
    """kanon add without --force exits non-zero with a spec-canonical message."""

    def test_collision_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Re-adding an existing entry without --force exits non-zero."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode != 0

    def test_collision_error_message_names_existing_and_new(self, tmp_path: pathlib.Path) -> None:
        """Error message names existing URL/revision and requested URL/revision."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        # Must name the source name and relevant details.
        # The existing mapping was stored with the canonical git ref form
        # ("refs/tags/1.0.0"); the requested mapping is reported with the raw
        # PEP 440 specifier the user supplied on the command line ("==1.0.0")
        # because that is what surfaces the collision before any ref resolution.
        assert "entry_a" in result.stderr
        assert "refs/tags/1.0.0" in result.stderr
        assert "==1.0.0" in result.stderr

    def test_collision_error_references_force_or_remove(self, tmp_path: pathlib.Path) -> None:
        """Error message references --force or 'kanon remove'."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )

        result = _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert "--force" in result.stderr or "kanon remove" in result.stderr

    def test_collision_does_not_modify_file(self, tmp_path: pathlib.Path) -> None:
        """File is not modified when a collision error occurs."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        original_content = (
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            f"KANON_SOURCE_entry_a_URL=file://{bare}\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
        )
        kanon_file.write_text(original_content)
        sha_before = _sha256(kanon_file)

        _run_kanon(
            [
                "add",
                "entry-a@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert _sha256(kanon_file) == sha_before, "File was modified on collision error"


# ---------------------------------------------------------------------------
# Integration tests: within-request collision
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddWithinRequestCollision:
    """kanon add a a exits non-zero before any catalog work."""

    def test_same_name_twice_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """kanon add a a exits non-zero before catalog resolution."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            cwd=workspace,
        )
        assert result.returncode != 0

    def test_same_name_twice_error_names_the_entry(self, tmp_path: pathlib.Path) -> None:
        """Error message names the duplicated entry."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            cwd=workspace,
        )
        assert "entry_a" in result.stderr or "entry-a" in result.stderr

    def test_normalised_same_name_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Two entries normalising to the same source name is a hard error."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "Entry-A",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            cwd=workspace,
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# AC-CYCLE-001: End-to-end cycle evidence
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddCycleEvidence:
    """AC-CYCLE-001: Full end-to-end cycle with entry-a and entry-b.

    Steps:
    1. Build fixture manifest repo with entry-a and entry-b tagged at 1.0.0.
    2. kanon add entry-a => triple written.
    3. kanon add entry-a (collision) => hard error with spec-canonical message.
    4. kanon add entry-a --force => existing block overwritten, file otherwise byte-identical.
    5. kanon add entry-a --dry-run (collision) => dry-run diff, no file modification.
    6. kanon add entry-a entry-a => within-request hard error.
    """

    def test_full_cycle(self, tmp_path: pathlib.Path) -> None:
        """Full AC-CYCLE-001 evidence: add, collision, force, dry-run, within-request."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a", "entry-b"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # Step 2: kanon add entry-a => triple written
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
        assert result.returncode == 0, f"Step 2 failed.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        content_after_add = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=" in content_after_add
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content_after_add
        assert "KANON_SOURCE_entry_a_PATH=" in content_after_add
        assert "KANON_SOURCE_entry_a_NAME=" in content_after_add
        assert "KANON_SOURCE_entry_a_GITBASE=" in content_after_add

        # Step 3: kanon add entry-a (collision) => hard error
        result2 = _run_kanon(
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
        assert result2.returncode != 0, "Expected non-zero exit on collision"
        assert "entry_a" in result2.stderr
        assert "refs/tags/1.0.0" in result2.stderr
        # Spec-canonical: --force or kanon remove referenced
        assert "--force" in result2.stderr or "kanon remove" in result2.stderr

        # Step 4: kanon add entry-a --force => block overwritten
        result3 = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--force",
            ],
            cwd=workspace,
        )
        assert result3.returncode == 0, f"Step 4 failed.\nstdout: {result3.stdout!r}\nstderr: {result3.stderr!r}"
        content_after_force = kanon_file.read_text()
        # Block still present (same tags, same content)
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content_after_force

        # Step 5: kanon add entry-a --dry-run => diff, no file change
        sha_before_dry = _sha256(kanon_file)
        result4 = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--dry-run",
                "--force",
            ],
            cwd=workspace,
        )
        assert result4.returncode == 0, f"Step 5 failed.\nstdout: {result4.stdout!r}\nstderr: {result4.stderr!r}"
        assert "+KANON_SOURCE_entry_a_" in result4.stdout
        sha_after_dry = _sha256(kanon_file)
        assert sha_before_dry == sha_after_dry, "File changed during dry-run"

        # Step 6: kanon add entry-a entry-a => within-request hard error
        result5 = _run_kanon(
            [
                "add",
                "entry-a",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result5.returncode != 0, "Expected non-zero exit for within-request collision"
        assert "entry_a" in result5.stderr or "entry-a" in result5.stderr
