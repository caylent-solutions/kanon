"""Integration tests for 'kanon outdated --fail-on-upgrade' end-to-end.

Builds real file:// fixture repos and invokes the CLI via subprocess to
assert that exit codes are correct both with and without the flag.

AC-TEST-002, AC-CYCLE-001
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

_KANON_SINGLE_TEMPLATE = textwrap.dedent("""\
    GITBASE=file:///unused
    CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=false
    KANON_SOURCE_{name_upper}_URL={url}
    KANON_SOURCE_{name_upper}_REVISION={revision}
    KANON_SOURCE_{name_upper}_PATH=./{name_lower}
""")

_KANON_TWO_SOURCES_TEMPLATE = textwrap.dedent("""\
    GITBASE=file:///unused
    CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=false
    KANON_SOURCE_{name_upper_a}_URL={url_a}
    KANON_SOURCE_{name_upper_a}_REVISION={revision_a}
    KANON_SOURCE_{name_upper_a}_PATH=./{name_lower_a}
    KANON_SOURCE_{name_upper_b}_URL={url_b}
    KANON_SOURCE_{name_upper_b}_REVISION={revision_b}
    KANON_SOURCE_{name_upper_b}_PATH=./{name_lower_b}
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


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _create_project_repo_with_tags(
    base: pathlib.Path,
    name: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare project repo with the given PEP 440 tags.

    Args:
        base: Parent directory under which work and bare dirs are created.
        name: Name used for directory naming.
        tags: List of tag strings to apply in order (first on initial commit;
            subsequent tags get extra commits so each has a distinct object).

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
    """Create a bare manifest (catalog) repo with marketplace XMLs."""
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


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


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
    env.pop("KANON_CATALOG_SOURCE", None)
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
# Lockfile builder helper
# ---------------------------------------------------------------------------


def _write_lockfile(
    lock_file: pathlib.Path,
    sources: list[dict[str, str]],
) -> None:
    """Write a minimal schema-v4 .kanon.lock file.

    Schema v4 removed the global [catalog] block; the lock is alias-keyed and
    each [[sources]] entry carries the per-entry ref_spec field.

    Args:
        lock_file: Path to write the lockfile.
        sources: List of dicts with keys: name, url, ref_spec,
            resolved_ref, resolved_sha, path.
    """
    lines = [
        "schema_version = 4",
        'generated_at = "2026-01-01T00:00:00Z"',
        'generator = "kanon-cli/test"',
        f'kanon_hash = "sha256:{"a" * 64}"',
    ]
    for source in sources:
        lines.append("")
        lines.append("[[sources]]")
        lines.append(f"alias = {source['name']!r}")
        lines.append(f"name = {source['name']!r}")
        lines.append(f"url = {source['url']!r}")
        lines.append(f"ref_spec = {source['ref_spec']!r}")
        lines.append(f"resolved_ref = {source['resolved_ref']!r}")
        lines.append(f"resolved_sha = {source['resolved_sha']!r}")
        lines.append(f"path = {source['path']!r}")
    lock_file.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOutdatedFailOnUpgradeFlag:
    """End-to-end tests for 'kanon outdated --fail-on-upgrade'.

    AC-TEST-002, AC-CYCLE-001
    """

    def test_without_flag_exits_zero_when_upgrade_available(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-004: without --fail-on-upgrade, exit 0 even when an upgrade is available."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "alpha", ["1.0.0", "1.0.1"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["alpha"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_SINGLE_TEMPLATE.format(
                name_upper="ALPHA",
                name_lower="alpha",
                url=project_url,
                revision=">=1.0.0,<1.1",
            )
        )
        kanon_file.chmod(0o644)

        # Lockfile pins to 1.0.0 so there is a patch upgrade available (1.0.1)
        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]
        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "ALPHA",
                    "url": project_url,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.0",
                    "resolved_sha": sha_100,
                    "path": "./alpha",
                }
            ],
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
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 without --fail-on-upgrade even with upgrade available.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # Verify the upgrade IS present in the output (patch upgrade exists)
        assert "patch" in result.stdout, f"Expected 'patch' upgrade-type in output:\n{result.stdout}"

    def test_with_flag_exits_one_when_upgrade_available(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: with --fail-on-upgrade, exit 1 when a source has an upgrade."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "beta", ["1.0.0", "1.0.1"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["beta"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_SINGLE_TEMPLATE.format(
                name_upper="BETA",
                name_lower="beta",
                url=project_url,
                revision=">=1.0.0,<1.1",
            )
        )
        kanon_file.chmod(0o644)

        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]
        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "BETA",
                    "url": project_url,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.0",
                    "resolved_sha": sha_100,
                    "path": "./beta",
                }
            ],
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
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 1, (
            f"Expected exit 1 with --fail-on-upgrade and patch upgrade available.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_with_flag_exits_zero_when_all_at_latest(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-003 / AC-CYCLE-001: --fail-on-upgrade exits 0 when all sources are at latest."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        project_bare = _create_project_repo_with_tags(project_base, "gamma", ["1.0.0", "1.0.1"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["gamma"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_SINGLE_TEMPLATE.format(
                name_upper="GAMMA",
                name_lower="gamma",
                url=project_url,
                revision=">=1.0.0,<1.1",
            )
        )
        kanon_file.chmod(0o644)

        # Pin to 1.0.1 which IS the latest-matching-spec -> no upgrade -> exit 0
        sha_101 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.1"],
            cwd=workspace,
        ).split("\t")[0]
        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "GAMMA",
                    "url": project_url,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.1",
                    "resolved_sha": sha_101,
                    "path": "./gamma",
                }
            ],
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
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 with --fail-on-upgrade when all sources at latest.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "none" in result.stdout, f"Expected upgrade-type=none in output:\n{result.stdout}"

    def test_two_sources_one_upgradable_flag_set_exits_one(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: two sources, one at latest, one upgradable; --fail-on-upgrade exits 1."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()

        # Source A: at latest (no upgrade)
        bare_a = _create_project_repo_with_tags(project_base, "srcA", ["1.0.0", "1.0.1"])
        url_a = f"file://{bare_a}"

        # Source B: upgradable (locked to 2.0.0, latest is 2.1.0)
        bare_b = _create_project_repo_with_tags(project_base, "srcB", ["2.0.0", "2.1.0"])
        url_b = f"file://{bare_b}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["srcA", "srcB"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_TWO_SOURCES_TEMPLATE.format(
                name_upper_a="SRCA",
                name_lower_a="srcA",
                url_a=url_a,
                revision_a=">=1.0.0,<1.1",
                name_upper_b="SRCB",
                name_lower_b="srcB",
                url_b=url_b,
                revision_b=">=2.0.0",
            )
        )
        kanon_file.chmod(0o644)

        sha_a = _git_output(["ls-remote", url_a, "refs/tags/1.0.1"], cwd=workspace).split("\t")[0]
        sha_b = _git_output(["ls-remote", url_b, "refs/tags/2.0.0"], cwd=workspace).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "SRCA",
                    "url": url_a,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.1",
                    "resolved_sha": sha_a,
                    "path": "./srcA",
                },
                {
                    "name": "SRCB",
                    "url": url_b,
                    "ref_spec": ">=2.0.0",
                    "resolved_ref": "refs/tags/2.0.0",
                    "resolved_sha": sha_b,
                    "path": "./srcB",
                },
            ],
        )

        # Without --fail-on-upgrade: exit 0
        result_no_flag = _run_kanon(
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
        assert result_no_flag.returncode == 0, (
            f"Expected exit 0 without flag.\nstdout: {result_no_flag.stdout!r}\nstderr: {result_no_flag.stderr!r}"
        )

        # With --fail-on-upgrade: exit 1 because SRCB has a minor upgrade
        result_with_flag = _run_kanon(
            [
                "outdated",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )
        assert result_with_flag.returncode == 1, (
            f"Expected exit 1 with --fail-on-upgrade (SRCB has minor upgrade).\n"
            f"stdout: {result_with_flag.stdout!r}\nstderr: {result_with_flag.stderr!r}"
        )

    def test_stderr_diagnostic_on_fail_on_upgrade(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: --fail-on-upgrade emits 'outdated source(s) found' to stderr on exit 1.

        Builds a 3-tag synthetic fixture, pins lockfile to the oldest tag so two
        upgrades are available, then verifies returncode==1 AND stderr contains the
        diagnostic message with the outdated source name.
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        # 3-tag fixture: 1.0.0, 1.0.1, 1.0.2
        project_bare = _create_project_repo_with_tags(project_base, "delta", ["1.0.0", "1.0.1", "1.0.2"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["delta"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_SINGLE_TEMPLATE.format(
                name_upper="DELTA",
                name_lower="delta",
                url=project_url,
                revision=">=1.0.0,<1.1",
            )
        )
        kanon_file.chmod(0o644)

        # Pin to oldest tag so a patch upgrade is available
        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]
        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "DELTA",
                    "url": project_url,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.0",
                    "resolved_sha": sha_100,
                    "path": "./delta",
                }
            ],
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
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 1, (
            f"Expected exit 1 with --fail-on-upgrade and upgrade available.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "outdated source(s) found" in result.stderr, (
            f"Expected 'outdated source(s) found' in stderr.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "DELTA" in result.stderr, (
            f"Expected outdated source name 'DELTA' in stderr diagnostic.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_two_sources_both_at_latest_flag_set_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: two sources both at latest; --fail-on-upgrade exits 0."""
        project_base = tmp_path / "project-repos"
        project_base.mkdir()

        bare_a = _create_project_repo_with_tags(project_base, "latA", ["1.0.0", "1.0.1"])
        url_a = f"file://{bare_a}"

        bare_b = _create_project_repo_with_tags(project_base, "latB", ["2.0.0", "2.0.1"])
        url_b = f"file://{bare_b}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["latA", "latB"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_TWO_SOURCES_TEMPLATE.format(
                name_upper_a="LATA",
                name_lower_a="latA",
                url_a=url_a,
                revision_a=">=1.0.0,<1.1",
                name_upper_b="LATB",
                name_lower_b="latB",
                url_b=url_b,
                revision_b=">=2.0.0,<2.1",
            )
        )
        kanon_file.chmod(0o644)

        sha_a = _git_output(["ls-remote", url_a, "refs/tags/1.0.1"], cwd=workspace).split("\t")[0]
        sha_b = _git_output(["ls-remote", url_b, "refs/tags/2.0.1"], cwd=workspace).split("\t")[0]

        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "LATA",
                    "url": url_a,
                    "ref_spec": ">=1.0.0,<1.1",
                    "resolved_ref": "refs/tags/1.0.1",
                    "resolved_sha": sha_a,
                    "path": "./latA",
                },
                {
                    "name": "LATB",
                    "url": url_b,
                    "ref_spec": ">=2.0.0,<2.1",
                    "resolved_ref": "refs/tags/2.0.1",
                    "resolved_sha": sha_b,
                    "path": "./latB",
                },
            ],
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
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 with --fail-on-upgrade when both sources at latest.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# FAIL-path class: 3-tag fixture pinned to oldest tag
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFailOnUpgradeFail:
    """Tests that --fail-on-upgrade exits 1 when upgrades are available.

    Uses a 3-tag synthetic fixture (1.0.0, 1.1.0, 1.2.0) pinned to the oldest
    tag so two upgrades are available, asserting exit 1 and the documented
    stderr diagnostic. Spec §4 E40 row 65.
    """

    def test_exit_one_when_upgrade_available(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001 to AC-FUNC-004: 3-tag fixture pinned to oldest tag exits 1 with diagnostic.

        Builds a bare fixture repo with tags 1.0.0, 1.1.0 and 1.2.0.
        Pins the lockfile to refs/tags/1.0.0 (two upgrades are available).
        Runs 'kanon outdated --fail-on-upgrade' and asserts:
        - returncode == 1
        - 'outdated source(s) found' appears in stderr
        """
        project_base = tmp_path / "project-repos"
        project_base.mkdir()
        # 3-tag fixture: 1.0.0 (oldest, pinned), 1.1.0, 1.2.0 (two upgrades available)
        project_bare = _create_project_repo_with_tags(project_base, "epsilon", ["1.0.0", "1.1.0", "1.2.0"])
        project_url = f"file://{project_bare}"

        manifest_base = tmp_path / "manifest-repos"
        manifest_base.mkdir()
        manifest_bare = _create_manifest_repo(manifest_base, ["epsilon"])
        catalog_source = f"file://{manifest_bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(
            _KANON_SINGLE_TEMPLATE.format(
                name_upper="EPSILON",
                name_lower="epsilon",
                url=project_url,
                revision=">=1.0.0",
            )
        )
        kanon_file.chmod(0o644)

        # Pin lockfile to oldest tag (1.0.0) so two upgrades (1.1.0, 1.2.0) are available
        sha_100 = _git_output(
            ["ls-remote", project_url, "refs/tags/1.0.0"],
            cwd=workspace,
        ).split("\t")[0]
        lock_file = workspace / ".kanon.lock"
        _write_lockfile(
            lock_file,
            sources=[
                {
                    "name": "EPSILON",
                    "url": project_url,
                    "ref_spec": ">=1.0.0",
                    "resolved_ref": "refs/tags/1.0.0",
                    "resolved_sha": sha_100,
                    "path": "./epsilon",
                }
            ],
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
                "--fail-on-upgrade",
            ],
            cwd=workspace,
        )

        assert result.returncode == 1, (
            f"Expected exit 1 with --fail-on-upgrade and 2 upgrades available "
            f"(pinned 1.0.0, latest 1.2.0).\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "outdated source(s) found" in result.stderr, (
            f"Expected 'outdated source(s) found' in stderr.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
