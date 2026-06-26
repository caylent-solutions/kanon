"""Integration tests for 'kanon outdated --format json' end-to-end.

Builds real file:// fixture repos with two sources:
  - A tag-pinned source (foo) with tags 1.0.0, 1.0.1, locked to 1.0.0.
    Expected: current=1.0.0, latest-matching-spec=1.0.1,
              latest-available=1.0.1, upgrade-type=patch.
  - A branch-pinned source (mylib) with a ``main`` branch advanced from
    SHA A to SHA B, locked to SHA A.
    Expected: current=<A-12>, latest-matching-spec=<B-12>,
              latest-available=<B-12>, upgrade-type=drift.

Invokes 'kanon outdated --format json' via subprocess, parses stdout with
json.loads, and asserts both shape and per-source field values. The JSON
payload is an object ``{"aliases": [...], "sources": [...]}`` where the row
dicts live under ``"sources"`` and the per-source render strings under
``"aliases"``.

AC-TEST-002, AC-CYCLE-001
"""

import json
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
        tags: List of tag strings to apply in order (first on the initial
              commit; subsequent tags on extra commits).

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


def _create_project_repo_with_two_commits(
    base: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, str, str]:
    """Create a bare project repo with a ``main`` branch at two commits.

    Returns (bare_path, sha_a, sha_b) where sha_a is the first commit and
    sha_b is the second (HEAD). Both SHAs are full 40-character hex strings.

    Args:
        base: Parent directory for the work and bare repos.
        name: Name used for directory naming.

    Returns:
        A tuple of (bare_path, sha_a, sha_b).
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text(f"# {name} initial\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    sha_a = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    (work_dir / "README.md").write_text(f"# {name} second\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Second commit"], cwd=work_dir)
    sha_b = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{name}-bare.git")
    return bare_dir.resolve(), sha_a, sha_b


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
    env.pop("KANON_OUTDATED_FORMAT", None)
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
class TestOutdatedFormatJson:
    """End-to-end tests for 'kanon outdated --format json'.

    AC-TEST-002, AC-CYCLE-001
    """

    def test_single_tag_pinned_source_json_shape(self, tmp_path: pathlib.Path) -> None:
        """Single tag-pinned source: JSON 'sources' list has one element with correct fields.

        AC-TEST-002: subprocess invocation with --format json; json.loads; shape and values.
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "foo", ["1.0.0", "1.0.1"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["foo"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            f"KANON_SOURCE_FOO_URL={project_url}\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            f"url = {project_url!r}\n"
            'ref_spec = ">=1.0.0"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha_100}"\n'
            'path = "./foo"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
                "--format",
                "json",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        parsed = json.loads(result.stdout)

        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {"aliases", "sources"}
        assert isinstance(parsed["sources"], list)
        assert len(parsed["sources"]) == 1
        assert isinstance(parsed["aliases"], list)
        assert len(parsed["aliases"]) == 1
        assert all(isinstance(render, str) and render for render in parsed["aliases"])
        assert "FOO" in parsed["aliases"][0]

        obj = parsed["sources"][0]
        assert set(obj.keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }
        assert obj["name"] == "FOO"
        assert obj["current"] == "1.0.0"
        assert obj["latest-matching-spec"] == "1.0.1"
        assert obj["latest-available"] == "1.0.1"
        assert obj["upgrade-type"] == "patch"

    def test_two_sources_mixed_shapes_json_shape(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: two sources (tag-pinned upgradable + branch-pinned drift).

        Build a fixture with two sources:
          - FOO: tag-pinned, locked to 1.0.0, latest 1.0.1 -> upgrade-type=patch
          - MYLIB: branch-pinned, locked SHA A, HEAD at SHA B -> upgrade-type=drift

        Assert array has exactly 2 elements with matching upgrade-type values
        and correct SHA truncations for the branch-pinned source.
        """

        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        foo_bare = _create_project_repo_with_tags(project_base, "foo", ["1.0.0", "1.0.1"])
        foo_url = f"file://{foo_bare}"

        mylib_bare, sha_a, sha_b = _create_project_repo_with_two_commits(project_base, "mylib")
        mylib_url = f"file://{mylib_bare}"
        sha_a_12 = sha_a[:12]
        sha_b_12 = sha_b[:12]

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["foo", "mylib"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            f"KANON_SOURCE_FOO_URL={foo_url}\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
            f"KANON_SOURCE_MYLIB_URL={mylib_url}\n"
            "KANON_SOURCE_MYLIB_REF=main\n"
            "KANON_SOURCE_MYLIB_PATH=./mylib\n"
            "KANON_SOURCE_MYLIB_NAME=MYLIB\n"
            "KANON_SOURCE_MYLIB_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        sha_100 = _git_output(
            ["ls-remote", foo_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            f"url = {foo_url!r}\n"
            'ref_spec = ">=1.0.0"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha_100}"\n'
            'path = "./foo"\n'
            "\n"
            "[[sources]]\n"
            'alias = "MYLIB"\n'
            'name = "MYLIB"\n'
            f"url = {mylib_url!r}\n"
            'ref_spec = "main"\n'
            'resolved_ref = "main"\n'
            f'resolved_sha = "{sha_a}"\n'
            'path = "./mylib"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
                "--format",
                "json",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        parsed = json.loads(result.stdout)

        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {"aliases", "sources"}
        sources = parsed["sources"]
        assert isinstance(sources, list)
        assert len(sources) == 2, f"Expected 2 sources, got {len(sources)}: {sources}"

        assert isinstance(parsed["aliases"], list)
        assert len(parsed["aliases"]) == 2
        assert all(isinstance(render, str) and render for render in parsed["aliases"])
        alias_text = "\n".join(parsed["aliases"])
        assert "FOO" in alias_text
        assert "MYLIB" in alias_text

        by_name = {obj["name"]: obj for obj in sources}

        assert "FOO" in by_name, f"Expected 'FOO' in JSON output, got names: {list(by_name.keys())}"
        foo_obj = by_name["FOO"]
        assert set(foo_obj.keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }
        assert foo_obj["current"] == "1.0.0"
        assert foo_obj["latest-matching-spec"] == "1.0.1"
        assert foo_obj["upgrade-type"] == "patch"

        assert "MYLIB" in by_name, f"Expected 'MYLIB' in JSON output, got names: {list(by_name.keys())}"
        mylib_obj = by_name["MYLIB"]
        assert set(mylib_obj.keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }
        assert mylib_obj["current"] == sha_a_12, (
            f"Expected current={sha_a_12!r} (12-char SHA A), got {mylib_obj['current']!r}"
        )
        assert mylib_obj["latest-matching-spec"] == sha_b_12, (
            f"Expected latest-matching-spec={sha_b_12!r} (12-char SHA B), got {mylib_obj['latest-matching-spec']!r}"
        )
        assert mylib_obj["latest-available"] == sha_b_12
        assert mylib_obj["upgrade-type"] == "drift"

    def test_env_var_kanon_outdated_format_json(self, tmp_path: pathlib.Path) -> None:
        """KANON_OUTDATED_FORMAT=json selects JSON output without --format flag."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "baz", ["1.0.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["baz"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            f"KANON_SOURCE_BAZ_URL={project_url}\n"
            "KANON_SOURCE_BAZ_REF=>=1.0.0\n"
            "KANON_SOURCE_BAZ_PATH=./baz\n"
            "KANON_SOURCE_BAZ_NAME=BAZ\n"
            "KANON_SOURCE_BAZ_GITBASE=https://example.com\n"
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
            extra_env={"KANON_OUTDATED_FORMAT": "json"},
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        parsed = json.loads(result.stdout)

        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {"aliases", "sources"}
        assert isinstance(parsed["sources"], list)
        assert len(parsed["sources"]) == 1
        assert isinstance(parsed["aliases"], list)
        assert len(parsed["aliases"]) == 1
        assert "BAZ" in parsed["aliases"][0]
        obj = parsed["sources"][0]
        assert obj["name"] == "BAZ"
        assert set(obj.keys()) == {
            "name",
            "current",
            "latest-matching-spec",
            "latest-available",
            "upgrade-type",
        }

    def test_fail_on_upgrade_exit_code_unchanged_by_json_format(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-008: --fail-on-upgrade exit-code logic is unchanged by --format json.

        A source with upgrade-type != none and --fail-on-upgrade must still exit 1,
        regardless of whether --format json or --format table is selected.
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "qux", ["1.0.0", "1.0.1"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["qux"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            f"KANON_SOURCE_QUX_URL={project_url}\n"
            "KANON_SOURCE_QUX_REF=>=1.0.0,<1.1\n"
            "KANON_SOURCE_QUX_PATH=./qux\n"
            "KANON_SOURCE_QUX_NAME=QUX\n"
            "KANON_SOURCE_QUX_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "QUX"\n'
            'name = "QUX"\n'
            f"url = {project_url!r}\n"
            'ref_spec = ">=1.0.0,<1.1"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha_100}"\n'
            'path = "./qux"\n'
        )

        result = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
                "--format",
                "json",
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 1, (
            f"Expected exit 1 (upgrade available + --fail-on-upgrade), "
            f"got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {"aliases", "sources"}
        assert isinstance(parsed["sources"], list)
        assert len(parsed["sources"]) == 1
        assert isinstance(parsed["aliases"], list)
        assert len(parsed["aliases"]) == 1
        assert "QUX" in parsed["aliases"][0]
        assert parsed["sources"][0]["upgrade-type"] == "patch"
