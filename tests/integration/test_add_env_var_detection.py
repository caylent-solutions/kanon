"""Integration tests: kanon add detects per-dependency ${VAR} env vars from the manifest.

A catalog entry needs an env var only when its manifest references a ``${VAR}``
placeholder in a ``<remote>`` its ``<project>`` depends on (or in the project's
own attributes). ``kanon add`` writes one ``KANON_SOURCE_<alias>_<VAR>=<value>``
line per detected var: auto-derived for the var named exactly ``GITBASE`` and
empty for every other var name. An entry whose manifest references no ``${VAR}``
remote gets no env-var line.

These tests drive the real ``kanon add`` CLI against real bare git manifest
repositories whose entry XML embeds the relevant ``<remote>``/``<project>``
shapes, asserting the exact env-var lines ``add`` writes.

Spec reference: specs/kanon-refinements.md Section 5.1 (optional per-dependency
env vars), Section 4.2 (add detection).
"""

from __future__ import annotations

import pathlib
import textwrap
from urllib.parse import urlparse

import pytest

from tests.integration.test_add_core import (
    _git,
    _init_git_work_dir,
    _run_kanon,
)


def _make_manifest_repo_with_body(
    base: pathlib.Path,
    entry_name: str,
    manifest_body: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo whose entry XML embeds ``manifest_body``.

    ``manifest_body`` is the inner XML placed inside ``<manifest>...</manifest>``
    after the ``<catalog-metadata>`` element, so the caller controls the
    ``<remote>``/``<default>``/``<project>`` shape that drives var detection.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_name: The catalog entry name (also the XML file stem).
        manifest_body: Inner XML (remotes/defaults/projects) for the entry.
        tags: PEP 440-valid tag names to apply to the initial commit.

    Returns:
        The absolute path to the bare repo directory.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("", encoding="utf-8")

    xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <manifest>
          <catalog-metadata>
            <name>{name}</name>
            <display-name>{name} Display</display-name>
            <description>Entry {name}.</description>
            <version>1.0.0</version>
          </catalog-metadata>
        {body}
        </manifest>
    """).format(name=entry_name, body=manifest_body)
    (repo_specs_dir / f"{entry_name}-marketplace.xml").write_text(xml, encoding="utf-8")

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add entry"], cwd=work_dir)
    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = base / "manifest-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _env_var_lines(content: str, alias: str) -> dict[str, str]:
    """Return the ``{VAR: value}`` map of per-dependency env-var lines for ``alias``.

    Excludes the four required structural suffixes so only the optional
    env-var lines (e.g. ``GITBASE``, ``MYBASE``) are returned.
    """
    prefix = f"KANON_SOURCE_{alias}_"
    structural = {"URL", "REF", "PATH", "NAME"}
    env: dict[str, str] = {}
    for line in content.splitlines():
        if line.startswith(prefix) and "=" in line:
            key, _, value = line.partition("=")
            var = key[len(prefix) :]
            if var not in structural:
                env[var] = value
    return env


@pytest.mark.integration
class TestAddEnvVarDetection:
    """kanon add writes one env-var line per ${VAR} the entry's manifest needs."""

    def test_no_var_remote_writes_no_env_var_line(self, tmp_path: pathlib.Path) -> None:
        """Case (a): a manifest with a fully-literal remote writes no env-var line."""
        body = textwrap.dedent("""\
              <remote name="origin" fetch="https://example.com/repos" />
              <default revision="main" remote="origin" />
              <project name="pkg" path="pkg" />
        """)
        bare = _make_manifest_repo_with_body(tmp_path / "catalog", "noenv", body, ["1.0.0"])
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            ["add", "noenv", "--catalog-source", f"file://{bare}@main"],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"

        content = (workspace / ".kanon").read_text()
        assert _env_var_lines(content, "noenv") == {}, f"a literal remote must yield no env-var line; got:\n{content}"
        assert "KANON_SOURCE_noenv_URL=" in content

    def test_custom_var_remote_writes_empty_placeholder(self, tmp_path: pathlib.Path) -> None:
        """Case (b): a custom ${MYBASE} remote writes an EMPTY KANON_SOURCE_<alias>_MYBASE= line."""
        body = textwrap.dedent("""\
              <remote name="origin" fetch="${MYBASE}/repos" />
              <default revision="main" remote="origin" />
              <project name="pkg" path="pkg" />
        """)
        bare = _make_manifest_repo_with_body(tmp_path / "catalog", "custom", body, ["1.0.0"])
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            ["add", "custom", "--catalog-source", f"file://{bare}@main"],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"

        content = (workspace / ".kanon").read_text()
        env = _env_var_lines(content, "custom")
        assert env == {"MYBASE": ""}, (
            f"a custom ${{MYBASE}} remote must write an empty MYBASE placeholder; got:\n{content}"
        )

    def test_gitbase_remote_auto_derives_value(self, tmp_path: pathlib.Path) -> None:
        """Case (c): a ${GITBASE} remote writes a KANON_SOURCE_<alias>_GITBASE= line
        whose value is auto-derived from the catalog-source URL.
        """
        body = textwrap.dedent("""\
              <remote name="origin" fetch="${GITBASE}/repos" />
              <default revision="main" remote="origin" />
              <project name="pkg" path="pkg" />
        """)
        bare = _make_manifest_repo_with_body(tmp_path / "catalog", "gb", body, ["1.0.0"])
        catalog_source = f"file://{bare}@main"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            ["add", "gb", "--catalog-source", catalog_source],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"

        content = (workspace / ".kanon").read_text()
        env = _env_var_lines(content, "gb")
        assert "GITBASE" in env, f"a ${{GITBASE}} remote must write a GITBASE line; got:\n{content}"

        parsed = urlparse(f"file://{bare}")
        expected_gitbase = f"{parsed.scheme}://{parsed.netloc}{pathlib.PurePosixPath(parsed.path).parent}"
        assert env["GITBASE"] == expected_gitbase, (
            f"GITBASE value must be auto-derived from the catalog-source URL.\n"
            f"  expected: {expected_gitbase!r}\n  got: {env['GITBASE']!r}"
        )

    def test_prose_var_in_comment_and_cdata_writes_no_env_var_line(self, tmp_path: pathlib.Path) -> None:
        """A ${VAR} that appears only in an XML comment / CDATA is documentation, not detected.

        Mirrors the install-side guard: add and install share
        ``functional_vars_in_manifest_files`` via ``detect_functional_manifest_vars``,
        so a ${HOME} that survives only in a <description> CDATA block (and not in
        any functional <remote>/<default>/<project> attribute) writes no env-var
        line, exactly as the install guard ignores it.
        """
        body = textwrap.dedent("""\
              <!-- Set ${GITBASE} to your org base, e.g. https://github.com/caylent -->
              <remote name="origin" fetch="https://example.com/repos" />
              <default revision="main" remote="origin" />
              <project name="pkg" path="pkg">
                <description><![CDATA[Override ${HOME} to relocate the cache.]]></description>
              </project>
        """)
        bare = _make_manifest_repo_with_body(tmp_path / "catalog", "prose", body, ["1.0.0"])
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            ["add", "prose", "--catalog-source", f"file://{bare}@main"],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"

        content = (workspace / ".kanon").read_text()
        assert _env_var_lines(content, "prose") == {}, (
            f"a ${{VAR}} only in a comment / CDATA must write no env-var line; got:\n{content}"
        )

    def test_project_attribute_var_is_detected(self, tmp_path: pathlib.Path) -> None:
        """A ${VAR} in the entry's <project> attributes is detected even with a literal remote."""
        body = textwrap.dedent("""\
              <remote name="origin" fetch="https://example.com/repos" />
              <default revision="main" remote="origin" />
              <project name="pkg" path="${SUBPATH}/pkg" />
        """)
        bare = _make_manifest_repo_with_body(tmp_path / "catalog", "projvar", body, ["1.0.0"])
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            ["add", "projvar", "--catalog-source", f"file://{bare}@main"],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"

        content = (workspace / ".kanon").read_text()
        env = _env_var_lines(content, "projvar")
        assert env == {"SUBPATH": ""}, (
            f"a ${{SUBPATH}} project attribute must be detected and written empty; got:\n{content}"
        )
