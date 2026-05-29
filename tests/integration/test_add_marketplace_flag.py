"""Integration tests for the kanon add --marketplace-install flag (AC-TEST-001).

Verifies that the mutually-exclusive --marketplace-install /
--no-marketplace-install flag pair is wired into 'kanon add' with the
precedence: explicit flag > env KANON_MARKETPLACE_INSTALL > default false.

Spec reference: spec/manual-matrix-gap-closure-2026-05/spec.md section 4
E49-F3, section 13 D4.

AC-TEST-001, AC-TEST-002
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

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


def _create_manifest_repo(
    base: pathlib.Path,
    entry_names: list[str],
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo with marketplace XML files and git tags.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_names: Catalog entry names.
        tags: PEP 440-valid tag names to apply to the initial commit.

    Returns:
        The absolute path to the bare repo directory.
    """
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
) -> "subprocess.CompletedProcess[str]":
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after 'kanon'.
        extra_env: Extra environment variables merged onto os.environ (keys
            with a value of None are removed from the environment entirely).
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddMarketplaceFlag:
    """kanon add --marketplace-install / --no-marketplace-install flag tests.

    Spec: section 4 E49-F3, section 13 D4 (flag > env > default).
    """

    def _make_bare(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a single-entry bare repo used by most test cases."""
        return _create_manifest_repo(
            tmp_path / "repo",
            entry_names=["pkg-a"],
            tags=["1.0.0"],
        )

    def test_flag_true_writes_true(self, tmp_path: pathlib.Path) -> None:
        """--marketplace-install writes KANON_MARKETPLACE_INSTALL=true to header."""
        bare = self._make_bare(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--marketplace-install",
            ],
            # Ensure env does not influence the result
            extra_env={"KANON_MARKETPLACE_INSTALL": None},
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "KANON_MARKETPLACE_INSTALL=true" in content, (
            f"Expected KANON_MARKETPLACE_INSTALL=true in .kanon header.\nActual content:\n{content}"
        )

    def test_no_flag_writes_false_default(self, tmp_path: pathlib.Path) -> None:
        """No flag, no env: KANON_MARKETPLACE_INSTALL=false (default)."""
        bare = self._make_bare(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            # Remove env override so only the default applies
            extra_env={"KANON_MARKETPLACE_INSTALL": None},
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "KANON_MARKETPLACE_INSTALL=false" in content, (
            f"Expected KANON_MARKETPLACE_INSTALL=false in .kanon header.\nActual content:\n{content}"
        )

    def test_flag_overrides_env(self, tmp_path: pathlib.Path) -> None:
        """--marketplace-install flag wins over conflicting KANON_MARKETPLACE_INSTALL env."""
        bare = self._make_bare(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--marketplace-install",
            ],
            # Env says false, flag says true -- flag must win
            extra_env={"KANON_MARKETPLACE_INSTALL": "false"},
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "KANON_MARKETPLACE_INSTALL=true" in content, (
            f"Expected flag to override env: KANON_MARKETPLACE_INSTALL=true "
            f"must appear in header.\nActual content:\n{content}"
        )

    def test_env_applies_when_flag_absent(self, tmp_path: pathlib.Path) -> None:
        """When no flag is passed, the env var value is used."""
        bare = self._make_bare(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            extra_env={"KANON_MARKETPLACE_INSTALL": "true"},
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "KANON_MARKETPLACE_INSTALL=true" in content, (
            f"Expected env value to apply: KANON_MARKETPLACE_INSTALL=true "
            f"must appear in header.\nActual content:\n{content}"
        )

    def test_both_flags_is_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """Passing both --marketplace-install and --no-marketplace-install is exit 2."""
        bare = self._make_bare(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--marketplace-install",
                "--no-marketplace-install",
            ],
            cwd=workspace,
        )
        assert result.returncode == 2, (
            f"Expected argparse error exit 2, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_append_does_not_rewrite_existing_marketplace_install_line(self, tmp_path: pathlib.Path) -> None:
        """Appending to an existing .kanon does not overwrite existing KANON_MARKETPLACE_INSTALL."""
        bare = _create_manifest_repo(
            tmp_path / "repo",
            entry_names=["pkg-a", "pkg-b"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # First invocation: creates the header with the env value
        first = _run_kanon(
            [
                "add",
                "pkg-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            extra_env={"KANON_MARKETPLACE_INSTALL": "true"},
            cwd=workspace,
        )
        assert first.returncode == 0, (
            f"First add failed: {first.returncode}.\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
        )
        content_after_first = kanon_file.read_text()
        assert "KANON_MARKETPLACE_INSTALL=true" in content_after_first, (
            f"First add must write KANON_MARKETPLACE_INSTALL=true.\nContent:\n{content_after_first}"
        )

        # Second invocation: append with a different flag value -- the header
        # must NOT be rewritten; the existing KANON_MARKETPLACE_INSTALL=true
        # line must survive unchanged.
        second = _run_kanon(
            [
                "add",
                "pkg-b",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
                "--no-marketplace-install",
            ],
            extra_env={"KANON_MARKETPLACE_INSTALL": None},
            cwd=workspace,
        )
        assert second.returncode == 0, (
            f"Second add failed: {second.returncode}.\nstdout: {second.stdout!r}\nstderr: {second.stderr!r}"
        )
        content_after_second = kanon_file.read_text()
        # The original KANON_MARKETPLACE_INSTALL=true must still be present
        assert "KANON_MARKETPLACE_INSTALL=true" in content_after_second, (
            f"Append must not rewrite existing KANON_MARKETPLACE_INSTALL line.\n"
            f"Content after second add:\n{content_after_second}"
        )
        # And it must appear exactly once (no duplicate lines)
        occurrences = content_after_second.count("KANON_MARKETPLACE_INSTALL=")
        assert occurrences == 1, (
            f"Expected exactly 1 KANON_MARKETPLACE_INSTALL= line, found {occurrences}.\n"
            f"Content:\n{content_after_second}"
        )
