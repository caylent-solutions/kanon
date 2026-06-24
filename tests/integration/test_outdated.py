"""Integration tests for 'kanon outdated' end-to-end.

Builds real file:// fixture repos:
  - A manifest repo (catalog) hosting one *-marketplace.xml with
    <catalog-metadata> pointing to a project repo, and a repo-specs/ dir.
  - A project repo with tags 1.0.0, 1.0.1, 1.1.0.

Invokes 'kanon outdated' via subprocess with a .kanon file pinned to
the project repo and asserts the table output contains the correct row.

AC-TEST-002, AC-TEST-003, AC-CYCLE-001
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


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


_KANON_TEMPLATE = textwrap.dedent("""\
    KANON_SOURCE_{name_upper}_URL={url}
    KANON_SOURCE_{name_upper}_REF={revision}
    KANON_SOURCE_{name_upper}_PATH=./{name_lower}
    KANON_SOURCE_{name_upper}_NAME={name_upper}
    KANON_SOURCE_{name_upper}_GITBASE=https://example.com
""")


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


def _git_output(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command in cwd and return stdout, raising RuntimeError on failure."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")
    return result.stdout.strip()


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_project_repo_with_tags(
    base: pathlib.Path,
    name: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare project repo with the given PEP 440 tags.

    Args:
        base: Parent directory under which work and bare dirs are created.
        name: Name used for directory naming.
        tags: List of tag strings to apply in order (first tag is on the
            initial commit; subsequent tags are added on extra commits so each
            has a distinct object).

    Returns:
        Absolute path to the bare repo directory.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text(f"# {name}\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    _git(["tag", "-a", tags[0], "-m", f"Release {tags[0]}"], cwd=work_dir)

    for tag in tags[1:]:
        (work_dir / f"v{tag}.md").write_text(f"Version {tag}\n")
        _git(["add", "."], cwd=work_dir)
        _git(["commit", "-m", f"Bump to {tag}"], cwd=work_dir)
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{name}-bare.git")
    return bare_dir.resolve()


def _create_manifest_repo(
    base: pathlib.Path,
    entry_names: list[str],
) -> pathlib.Path:
    """Create a bare manifest (catalog) repo with marketplace XMLs.

    Args:
        base: Parent directory for the repo.
        entry_names: Catalog entry names (each gets its own *-marketplace.xml).

    Returns:
        Absolute path to the bare manifest repo.
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

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the same Python interpreter.

    Args:
        args: Arguments to pass after 'python -m kanon_cli'.
        extra_env: Extra environment variables merged onto os.environ.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


@pytest.mark.integration
class TestOutdatedCoreTableOutput:
    """End-to-end kanon outdated test against a real file:// catalog.

    AC-TEST-002, AC-TEST-003, AC-CYCLE-001
    """

    def test_row_content_with_lockfile(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: full cycle with .kanon.lock pinned to 1.0.0.

        Tags: 1.0.0, 1.0.1, 1.1.0. Revision spec: >=1.0.0,<1.1.
        Lock pins to 1.0.0.
        Expected row: current=1.0.0, latest-matching-spec=1.0.1,
                      latest-available=1.1.0, upgrade-type=patch.
        """

        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "foo", ["1.0.0", "1.0.1", "1.1.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["foo"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_content = _KANON_TEMPLATE.format(
            name_upper="FOO",
            name_lower="foo",
            url=project_url,
            revision=">=1.0.0,<1.1",
        )
        kanon_file.write_text(kanon_content)
        kanon_file.chmod(0o644)

        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        lock_content = (
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            f"url = {project_url!r}\n"
            'ref_spec = ">=1.0.0,<1.1"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha_100}"\n'
            'path = "./foo"\n'
        )
        lock_file.write_text(lock_content)

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "FOO" in result.stdout, f"Expected source name 'FOO' in output:\n{result.stdout}"
        assert "1.0.0" in result.stdout, f"Expected current=1.0.0 in output:\n{result.stdout}"
        assert "1.0.1" in result.stdout, f"Expected latest-matching-spec=1.0.1 in output:\n{result.stdout}"
        assert "1.1.0" in result.stdout, f"Expected latest-available=1.1.0 in output:\n{result.stdout}"
        assert "patch" in result.stdout, f"Expected upgrade-type=patch in output:\n{result.stdout}"

    def test_exit_code_zero_always(self, tmp_path: pathlib.Path) -> None:
        """kanon outdated exits 0 even when upgrades are available (AC-FUNC-008)."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "bar", ["1.0.0", "2.0.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["bar"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_TEMPLATE.format(
                name_upper="BAR",
                name_lower="bar",
                url=project_url,
                revision=">=1.0.0",
            )
        )
        kanon_file.chmod(0o644)

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_missing_catalog_source_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Absent catalog source must exit non-zero (AC-FUNC-009)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_FOO_URL=file:///fake\nKANON_SOURCE_FOO_REF=>=1.0.0\nKANON_SOURCE_FOO_PATH=./foo\n"
        )
        kanon_file.chmod(0o644)

        result = _run_kanon(
            ["outdated", "--kanon-file", str(kanon_file)],
            extra_env={"KANON_CATALOG_SOURCES": ""},
            cwd=workspace,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "ERROR:" in result.stderr

    def test_missing_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Absent .kanon file must exit non-zero (AC-FUNC-010)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                "file:///fake@HEAD",
                "--kanon-file",
                str(workspace / "does_not_exist" / ".kanon"),
            ],
            cwd=workspace,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "ERROR:" in result.stderr

    def test_row_without_lockfile_live_resolves(self, tmp_path: pathlib.Path) -> None:
        """Without a lockfile, 'current' is live-resolved (AC-FUNC-003)."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "baz", ["1.0.0", "1.0.1", "1.1.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["baz"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_TEMPLATE.format(
                name_upper="BAZ",
                name_lower="baz",
                url=project_url,
                revision=">=1.0.0,<1.1",
            )
        )
        kanon_file.chmod(0o644)

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        assert "1.0.1" in result.stdout, f"Expected 1.0.1 in output:\n{result.stdout}"
        assert "none" in result.stdout, f"Expected upgrade-type=none in output:\n{result.stdout}"

    def test_invoked_via_subprocess_public_entry_point(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: command invoked via subprocess (python -m kanon_cli outdated)."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "qux", ["1.0.0", "1.1.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["qux"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_TEMPLATE.format(
                name_upper="QUX",
                name_lower="qux",
                url=project_url,
                revision=">=1.0.0",
            )
        )
        kanon_file.chmod(0o644)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "KANON_CATALOG_SOURCES": ""},
            cwd=str(workspace),
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "QUX" in result.stdout
        assert "upgrade-type" in result.stdout or "none" in result.stdout or "major" in result.stdout
