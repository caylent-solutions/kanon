"""Operator-path scenario tests for ``kanon why`` with placeholder remote fetch URLs.

These tests cover the BUG-2 root cause: when a catalog manifest uses
``<remote fetch="${GITBASE}">`` (a ``${VAR}`` placeholder), the live-resolve
path must substitute the placeholder from the ``.kanon`` globals BEFORE calling
``canonicalize_repo_url``, so that project nodes are populated and
``kanon why <project-url>`` exits 0.

Two fixture variants are parametrized:
- PLACEHOLDER: ``<remote fetch="${GITBASE}" />``; ``.kanon`` declares
  ``GITBASE=file://<pkgs-dir>``. This is the bug-trigger variant (RED today).
- CONCRETE: ``<remote fetch="file://<pkgs-dir>" />``; no ``${VAR}`` in the XML;
  ``.kanon`` declares no GITBASE. This is a regression guard (green today and after).

For each variant the following sub-cases are exercised:
- T-URL: ``kanon why <project-url>`` -> exit 0, chain contains source name.
- T-PATH: ``kanon why <root-manifest-path>`` -> exit 0, chain contains source name.
- T-SRCURL: ``kanon why <source-url>`` -> exit 0, chain contains source name.
- T-MISS: ``kanon why <unknown-url>`` -> exit 1, "not found in resolved tree" in stderr.

No xfail/skip markers.  All assertions must be capable of failing.

All subprocess calls use ``KANON_ALLOW_INSECURE_REMOTES=1`` per-test (never globally).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from tests.integration.test_add_core import (
    _git,
    _init_git_work_dir,
    _clone_as_bare,
)


# ---------------------------------------------------------------------------
# Fixture variant identifiers
# ---------------------------------------------------------------------------

_VARIANT_PLACEHOLDER = "placeholder"
_VARIANT_CONCRETE = "concrete"

_ENTRY_NAME = "myentry"
_PROJECT_NAME = "myproject"
_MANIFEST_PATH = f"repo-specs/{_ENTRY_NAME}-marketplace.xml"
_UNKNOWN_URL = "https://github.com/unknown-org/no-such-project-x99"


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_why(
    args: list[str],
    cwd: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """Run ``kanon why`` via subprocess with ``KANON_ALLOW_INSECURE_REMOTES=1``.

    Sets ``KANON_ALLOW_INSECURE_REMOTES=1`` per-test so that ``file://`` source
    URLs in synthetic local-repo fixtures pass the remote-URL security policy.
    This env var is applied only to this subprocess, never globally.

    Args:
        args: Arguments to pass to ``kanon_cli`` after the base invocation.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result with captured stdout/stderr.
    """
    env = dict(os.environ)
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


# ---------------------------------------------------------------------------
# XML template builders
# ---------------------------------------------------------------------------

_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{entry_name}</name>
        <display-name>{entry_name} Display</display-name>
        <description>Placeholder fixture catalog entry for {entry_name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Placeholder Tester</owner-name>
        <owner-email>placeholder-test@example.com</owner-email>
        <keywords>test, placeholder</keywords>
      </catalog-metadata>
      <remote name="pkgs" fetch="{remote_fetch}" />
      <project remote="pkgs" name="{project_name}" path="{project_name}" />
    </manifest>
""")


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _build_placeholder_fixture(
    tmp_path: pathlib.Path,
    variant: str,
) -> dict:
    """Build a synthetic catalog bare repo and workspace for the given fixture variant.

    Creates:
    - A ``pkgs`` directory under ``tmp_path`` containing a bare git repo for the
      project (needed so ``file://`` URLs are syntactically valid).
    - A catalog bare repo whose marketplace XML uses either ``${GITBASE}``
      (PLACEHOLDER) or a concrete ``file://`` fetch URL (CONCRETE).
    - A workspace directory with a ``.kanon`` file populated via ``kanon add``
      (CONCRETE) or via ``kanon add`` followed by a direct GITBASE override
      (PLACEHOLDER) so the ``.kanon`` globals carry the correct GITBASE value.

    The returned dict contains:
      - ``catalog_source_url``: ``file://<bare-path>@main`` string.
      - ``workspace``: path to the workspace directory.
      - ``kanon_file``: path to the ``.kanon`` file.
      - ``project_url``: the expected project URL (``file://<pkgs-dir>/<project-name>``).
      - ``source_url``: the source (catalog) URL (same as catalog bare-repo URL).
      - ``manifest_path``: the KANON_SOURCE_<name>_PATH value.

    Args:
        tmp_path: pytest per-test temporary directory.
        variant: One of ``_VARIANT_PLACEHOLDER`` or ``_VARIANT_CONCRETE``.

    Returns:
        A dict with keys as described above.

    Raises:
        AssertionError: If ``kanon add`` fails.
    """
    pkgs_dir = tmp_path / "pkgs"
    pkgs_dir.mkdir()

    # Create a minimal bare project repo so the URL is syntactically valid.
    proj_work = pkgs_dir / f"{_PROJECT_NAME}.work"
    proj_work.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(proj_work)
    (proj_work / "README.md").write_text("project placeholder\n")
    _git(["add", "README.md"], proj_work)
    _git(["commit", "-m", "init project"], proj_work)
    _clone_as_bare(proj_work, pkgs_dir / f"{_PROJECT_NAME}.git")

    # The concrete project URL for the remote+project combo.
    project_url = f"file://{pkgs_dir}/{_PROJECT_NAME}"

    # Build the remote fetch value based on variant.
    if variant == _VARIANT_PLACEHOLDER:
        remote_fetch = "${GITBASE}"
    else:
        remote_fetch = str(pkgs_dir.as_uri())

    # Create the catalog bare repo.
    catalog_work = tmp_path / "catalog.work"
    catalog_work.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(catalog_work)
    repo_specs_dir = catalog_work / "repo-specs"
    repo_specs_dir.mkdir()
    xml_content = _MARKETPLACE_XML_TEMPLATE.format(
        entry_name=_ENTRY_NAME,
        remote_fetch=remote_fetch,
        project_name=_PROJECT_NAME,
    )
    (repo_specs_dir / f"{_ENTRY_NAME}-marketplace.xml").write_text(xml_content)
    _git(["add", "."], catalog_work)
    _git(["commit", "-m", f"Add {_ENTRY_NAME} entry"], catalog_work)
    _git(["tag", "-a", "1.0.0", "-m", "Release 1.0.0"], catalog_work)

    catalog_bare = _clone_as_bare(catalog_work, tmp_path / "catalog.git")
    catalog_source_url = f"file://{catalog_bare}@main"

    # Create workspace and run kanon add.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kanon_file = workspace / ".kanon"

    add_env = dict(os.environ)
    add_env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    add_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "add",
            _ENTRY_NAME,
            "--catalog-source",
            catalog_source_url,
            "--kanon-file",
            str(kanon_file),
        ],
        capture_output=True,
        text=True,
        env=add_env,
        cwd=str(workspace),
    )
    assert add_result.returncode == 0, (
        f"kanon add failed (exit {add_result.returncode}).\n"
        f"stdout: {add_result.stdout!r}\n"
        f"stderr: {add_result.stderr!r}"
    )

    # For the PLACEHOLDER variant, `kanon add` derives GITBASE as
    # file://<catalog-parent-dir> = file://<tmp_path>.  The remote XML uses
    # "${GITBASE}" as the fetch URL, so the full project URL resolved at
    # why-time is ${GITBASE}/<project-name>.  We need GITBASE to equal
    # file://<pkgs_dir> so the URL matches `project_url` above.
    # Override GITBASE in the .kanon file to point at pkgs_dir.
    if variant == _VARIANT_PLACEHOLDER:
        text = kanon_file.read_text()
        # Replace the GITBASE line written by kanon add with our pkgs_dir value.
        new_gitbase_line = f"GITBASE={pkgs_dir.as_uri()}"
        lines = text.splitlines()
        replaced = False
        new_lines = []
        for line in lines:
            if line.startswith("GITBASE="):
                new_lines.append(new_gitbase_line)
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.insert(0, new_gitbase_line)
        kanon_file.write_text("\n".join(new_lines) + "\n")

    # Verify no lockfile exists (live-resolve path).
    lock_file = workspace / ".kanon.lock"
    assert not lock_file.exists(), f"Expected no .kanon.lock after kanon add (no install), but found {lock_file}"

    source_url = f"file://{catalog_bare}"

    return {
        "catalog_source_url": catalog_source_url,
        "workspace": workspace,
        "kanon_file": kanon_file,
        "project_url": project_url,
        "source_url": source_url,
        "manifest_path": _MANIFEST_PATH,
    }


# ---------------------------------------------------------------------------
# Parametrized operator-path tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
@pytest.mark.parametrize("variant", [_VARIANT_PLACEHOLDER, _VARIANT_CONCRETE])
class TestWhyUrlPathPlaceholder:
    """Real CLI operator-path tests for ``kanon why`` with placeholder vs concrete fetch URLs.

    Both variants exercise T-URL, T-PATH, T-SRCURL, and T-MISS sub-cases.
    The PLACEHOLDER variant is the bug-trigger: its remote uses ``${GITBASE}``
    and is RED against unfixed code.  The CONCRETE variant is a regression
    guard: green today and after the fix.
    """

    def test_t_url_project_url_exits_zero(
        self,
        tmp_path: pathlib.Path,
        variant: str,
    ) -> None:
        """T-URL: ``kanon why <project-url>`` exits 0 with source name in stdout.

        The PLACEHOLDER variant (BUG-2 trigger) is RED against unfixed code:
        ``_build_project_nodes_from_xml`` silently drops projects because
        ``${GITBASE}`` is not substituted before ``canonicalize_repo_url``.
        The CONCRETE variant (regression guard) is green today.

        Args:
            tmp_path: pytest per-test temp directory.
            variant: Fixture variant identifier (``_VARIANT_PLACEHOLDER`` or
                ``_VARIANT_CONCRETE``).
        """
        ctx = _build_placeholder_fixture(tmp_path, variant)
        project_url = ctx["project_url"]

        why_result = _run_why(
            [
                "why",
                project_url,
                "--catalog-source",
                ctx["catalog_source_url"],
                "--kanon-file",
                str(ctx["kanon_file"]),
            ],
            cwd=ctx["workspace"],
        )

        assert why_result.returncode == 0, (
            f"[{variant}] Expected exit 0 from 'kanon why {project_url}' on live-resolve path, "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )
        assert _ENTRY_NAME in why_result.stdout, (
            f"[{variant}] Expected source name {_ENTRY_NAME!r} in stdout but got: {why_result.stdout!r}"
        )

    def test_t_path_root_manifest_exits_zero(
        self,
        tmp_path: pathlib.Path,
        variant: str,
    ) -> None:
        """T-PATH: ``kanon why <root-manifest-path>`` exits 0 with source name in stdout.

        The ``_match_by_xml_path`` function currently only matches ``include``
        nodes, not source root-manifest paths. This test is RED today for both
        variants because the source root-manifest path is not a matchable node.

        Args:
            tmp_path: pytest per-test temp directory.
            variant: Fixture variant identifier.
        """
        ctx = _build_placeholder_fixture(tmp_path, variant)
        manifest_path = ctx["manifest_path"]

        why_result = _run_why(
            [
                "why",
                manifest_path,
                "--catalog-source",
                ctx["catalog_source_url"],
                "--kanon-file",
                str(ctx["kanon_file"]),
            ],
            cwd=ctx["workspace"],
        )

        assert why_result.returncode == 0, (
            f"[{variant}] Expected exit 0 from 'kanon why {manifest_path}' on live-resolve path, "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )
        assert _ENTRY_NAME in why_result.stdout, (
            f"[{variant}] Expected source name {_ENTRY_NAME!r} in stdout but got: {why_result.stdout!r}"
        )

    def test_t_srcurl_source_url_exits_zero(
        self,
        tmp_path: pathlib.Path,
        variant: str,
    ) -> None:
        """T-SRCURL: ``kanon why <source-url>`` exits 0 with source name in stdout.

        ``_match_by_url`` currently only matches ``project`` nodes, not
        ``source`` nodes by URL. This test is RED today for both variants.

        Args:
            tmp_path: pytest per-test temp directory.
            variant: Fixture variant identifier.
        """
        ctx = _build_placeholder_fixture(tmp_path, variant)
        source_url = ctx["source_url"]

        why_result = _run_why(
            [
                "why",
                source_url,
                "--catalog-source",
                ctx["catalog_source_url"],
                "--kanon-file",
                str(ctx["kanon_file"]),
            ],
            cwd=ctx["workspace"],
        )

        assert why_result.returncode == 0, (
            f"[{variant}] Expected exit 0 from 'kanon why {source_url}' on live-resolve path, "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )
        assert _ENTRY_NAME in why_result.stdout, (
            f"[{variant}] Expected source name {_ENTRY_NAME!r} in stdout but got: {why_result.stdout!r}"
        )

    def test_t_miss_unknown_url_exits_one(
        self,
        tmp_path: pathlib.Path,
        variant: str,
    ) -> None:
        """T-MISS: ``kanon why <unknown-url>`` exits 1 with "not found in resolved tree".

        The miss path must produce the same handled error regardless of variant.
        This test is green today and after the fix (regression guard for miss behavior).

        Args:
            tmp_path: pytest per-test temp directory.
            variant: Fixture variant identifier.
        """
        ctx = _build_placeholder_fixture(tmp_path, variant)

        why_result = _run_why(
            [
                "why",
                _UNKNOWN_URL,
                "--catalog-source",
                ctx["catalog_source_url"],
                "--kanon-file",
                str(ctx["kanon_file"]),
            ],
            cwd=ctx["workspace"],
        )

        assert why_result.returncode == 1, (
            f"[{variant}] Expected exit 1 from 'kanon why {_UNKNOWN_URL}' (unknown URL), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )
        assert "not found in resolved tree" in why_result.stderr, (
            f"[{variant}] Expected 'not found in resolved tree' in stderr for unknown URL, "
            f"but got stderr: {why_result.stderr!r}"
        )
        assert "Traceback" not in why_result.stderr, (
            f"[{variant}] Expected a handled error (no traceback), "
            f"but a Python traceback appeared in stderr: {why_result.stderr!r}"
        )
