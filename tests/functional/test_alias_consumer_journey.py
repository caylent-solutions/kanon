"""J6 functional journey: remove / why / outdated alias render (AC-51).

Spec reference: ``specs/kanon-refinements.md`` Section 10.4 (J6), Section 5.1
(``.kanon`` alias-keyed blocks, ``_REVISION`` -> ``_REF``, ``_NAME`` /
``_GITBASE``), FR-59, FR-6.

This is a hermetic black-box journey driven via the real ``kanon`` CLI in a
subprocess.  It builds two *same-NAME* dependencies (manifest name ``history``)
that originate from two different source repos, keyed in ``.kanon`` by two
distinct local aliases (``history`` and ``history_caylent_private_kanon``).  The per-dependency
``KANON_SOURCE_<alias>_NAME`` field carries the shared original manifest name.

It then drives the alias-keyed consumers:

  - ``kanon outdated`` renders ``alias -> name from <source>@<ref>`` for BOTH
    aliases via the ``_NAME`` field (FR-59, FR-6).
  - ``kanon why`` (lockfile path, no network) renders the
    ``alias -> name from <source>@<ref>`` line for the queried alias.
  - ``kanon remove <alias>`` keys on the alias and deletes ONLY that alias
    block, leaving the same-name sibling block intact.

No ``skipif``: the journey uses real ``file://`` git repos so it runs without
network access on every platform that has ``git``.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


_GIT_USER_NAME = "Alias Journey Test User"
_GIT_USER_EMAIL = "alias-journey@example.com"


_MANIFEST_NAME = "history"


_ALIAS_FIRST = "history"
_ALIAS_SECOND = "history_caylent_private_kanon"


_TAGS_FIRST = ["1.0.0", "1.0.1"]
_TAGS_SECOND = ["2.0.0", "2.1.0"]


_REF_FIRST = ">=1.0.0,<2.0.0"
_REF_SECOND = ">=2.0.0,<3.0.0"


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
    """Run a git command in cwd and return stripped stdout, raising on failure."""
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
    """Initialise a git working directory with deterministic test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _create_project_repo_with_tags(
    base: pathlib.Path,
    name: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare project repo with the given PEP 440 tags; return its bare path."""
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    _git(["tag", "-a", tags[0], "-m", f"Release {tags[0]}"], cwd=work_dir)

    for tag in tags[1:]:
        (work_dir / f"v{tag}.md").write_text(f"Version {tag}\n", encoding="utf-8")
        _git(["add", "."], cwd=work_dir)
        _git(["commit", "-m", f"Bump to {tag}"], cwd=work_dir)
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = base / f"{name}-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the current interpreter (real black-box invocation)."""
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


def _write_two_same_name_kanon(
    workspace: pathlib.Path,
    url_first: str,
    url_second: str,
) -> pathlib.Path:
    """Write a .kanon with two same-NAME deps keyed by two distinct aliases.

    Both blocks carry ``KANON_SOURCE_<alias>_NAME=history`` (the shared original
    manifest name); the aliases (``history`` and ``history_caylent_private_kanon``)
    and the URLs differ. Each block declares the full alias-keyed schema
    (``_URL``, ``_REF``, ``_PATH``, ``_NAME``, ``_GITBASE``).
    """
    content = textwrap.dedent(
        f"""\
        CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces
        KANON_SOURCE_{_ALIAS_FIRST}_URL={url_first}
        KANON_SOURCE_{_ALIAS_FIRST}_REF={_REF_FIRST}
        KANON_SOURCE_{_ALIAS_FIRST}_PATH=./{_MANIFEST_NAME}
        KANON_SOURCE_{_ALIAS_FIRST}_NAME={_MANIFEST_NAME}
        KANON_SOURCE_{_ALIAS_FIRST}_GITBASE=file:///org-a
        KANON_SOURCE_{_ALIAS_SECOND}_URL={url_second}
        KANON_SOURCE_{_ALIAS_SECOND}_REF={_REF_SECOND}
        KANON_SOURCE_{_ALIAS_SECOND}_PATH=./{_MANIFEST_NAME}
        KANON_SOURCE_{_ALIAS_SECOND}_NAME={_MANIFEST_NAME}
        KANON_SOURCE_{_ALIAS_SECOND}_GITBASE=file:///org-b
        """
    )
    kanon_file = workspace / ".kanon"
    kanon_file.write_text(content, encoding="utf-8")
    kanon_file.chmod(0o644)
    return kanon_file


def _write_lockfile(
    workspace: pathlib.Path,
    url_first: str,
    url_second: str,
    sha_first: str,
    sha_second: str,
) -> pathlib.Path:
    """Write a v5 .kanon.lock keyed by the two aliases (no network on why path)."""
    content = (
        "schema_version = 5\n"
        'generated_at = "2026-01-01T00:00:00Z"\n'
        'generator = "kanon-cli/test"\n'
        f'kanon_hash = "sha256:{"a" * 64}"\n'
        "\n"
        "[[sources]]\n"
        f'alias = "{_ALIAS_FIRST}"\n'
        f'name = "{_ALIAS_FIRST}"\n'
        f"url = {url_first!r}\n"
        f'ref_spec = "{_REF_FIRST}"\n'
        'resolved_ref = "refs/tags/1.0.1"\n'
        f'resolved_sha = "{sha_first}"\n'
        f'path = "./{_MANIFEST_NAME}"\n'
        "\n"
        "[[sources]]\n"
        f'alias = "{_ALIAS_SECOND}"\n'
        f'name = "{_ALIAS_SECOND}"\n'
        f"url = {url_second!r}\n"
        f'ref_spec = "{_REF_SECOND}"\n'
        'resolved_ref = "refs/tags/2.1.0"\n'
        f'resolved_sha = "{sha_second}"\n'
        f'path = "./{_MANIFEST_NAME}"\n'
    )
    lock_file = workspace / ".kanon.lock"
    lock_file.write_text(content, encoding="utf-8")
    return lock_file


@pytest.mark.functional
class TestAliasConsumerJourney:
    """J6: remove / why / outdated key on the alias and render via ``_NAME``."""

    def _build_workspace(self, tmp_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
        """Build two project repos and a .kanon with two same-name aliases."""
        repos = tmp_path / "repos"
        repos.mkdir()
        project_first = _create_project_repo_with_tags(repos, "hist-a", _TAGS_FIRST)
        project_second = _create_project_repo_with_tags(repos, "hist-b", _TAGS_SECOND)
        url_first = f"file://{project_first}"
        url_second = f"file://{project_second}"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_two_same_name_kanon(workspace, url_first, url_second)
        return workspace, url_first, url_second

    def test_outdated_renders_alias_to_name_from_source_for_both_aliases(self, tmp_path: pathlib.Path) -> None:
        """outdated renders ``alias -> name from <source>@<ref>`` via _NAME for both deps."""
        workspace, url_first, url_second = self._build_workspace(tmp_path)

        result = _run_kanon(
            [
                "outdated",
                "--kanon-file",
                str(workspace / ".kanon"),
                "--catalog-source",
                "file:///unused@main",
            ],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"kanon outdated must exit 0.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        out = result.stdout

        assert f"{_ALIAS_FIRST} -> {_MANIFEST_NAME} from {url_first}@{_REF_FIRST}" in out, (
            f"missing first alias render in:\n{out}"
        )
        assert f"{_ALIAS_SECOND} -> {_MANIFEST_NAME} from {url_second}@{_REF_SECOND}" in out, (
            f"missing second alias render in:\n{out}"
        )

    def test_why_renders_alias_to_name_from_source_for_queried_alias(self, tmp_path: pathlib.Path) -> None:
        """why (lockfile path) renders the alias -> name from <source>@<ref> line."""
        workspace, url_first, url_second = self._build_workspace(tmp_path)

        sha_first = _git_output(["ls-remote", url_first, "refs/tags/1.0.1"], cwd=workspace).split("\t")[0]
        sha_second = _git_output(["ls-remote", url_second, "refs/tags/2.1.0"], cwd=workspace).split("\t")[0]
        _write_lockfile(workspace, url_first, url_second, sha_first, sha_second)

        result = _run_kanon(
            ["why", _ALIAS_SECOND, "--kanon-file", str(workspace / ".kanon")],
            cwd=workspace,
        )

        assert result.returncode == 0, (
            f"kanon why must exit 0.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        out = result.stdout

        assert f"{_ALIAS_SECOND} -> {_MANIFEST_NAME} from {url_second}@{_REF_SECOND}" in out, (
            f"missing alias render for queried alias in:\n{out}"
        )

        assert f"{_ALIAS_FIRST} -> {_MANIFEST_NAME} from {url_first}@{_REF_FIRST}" not in out, (
            f"why must render only the queried alias, not the sibling, in:\n{out}"
        )

    def test_remove_deletes_only_the_named_alias_block(self, tmp_path: pathlib.Path) -> None:
        """remove keys on the alias and deletes only that alias block (FR-59)."""
        workspace, _url_first, _url_second = self._build_workspace(tmp_path)
        kanon_file = workspace / ".kanon"

        result = _run_kanon(["remove", _ALIAS_SECOND, "--kanon-file", str(kanon_file)], cwd=workspace)

        assert result.returncode == 0, (
            f"kanon remove must exit 0.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        remaining = kanon_file.read_text(encoding="utf-8")

        for suffix in ("_URL", "_REF", "_PATH", "_NAME", "_GITBASE"):
            assert f"KANON_SOURCE_{_ALIAS_SECOND}{suffix}=" not in remaining, (
                f"removed alias key KANON_SOURCE_{_ALIAS_SECOND}{suffix} still present in:\n{remaining}"
            )

        for suffix in ("_URL", "_REF", "_PATH", "_NAME", "_GITBASE"):
            assert f"KANON_SOURCE_{_ALIAS_FIRST}{suffix}=" in remaining, (
                f"sibling alias key KANON_SOURCE_{_ALIAS_FIRST}{suffix} unexpectedly removed from:\n{remaining}"
            )
