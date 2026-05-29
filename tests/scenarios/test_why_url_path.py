"""Operator-path scenario tests for ``kanon why`` url/path live-resolve (E49-F1).

These are subprocess (real CLI) tests asserting that ``kanon why <project-url>``
and ``kanon why <include-xml-path>`` exit 0 against a synthetic catalog with no
lockfile present.  They exercise the full operator path to close findings rows 68
and 69 from the 2026-05-29 manual re-run.

All subprocess calls use the same Python interpreter via ``sys.executable -m kanon_cli``
to match the installed CLI behaviour.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from tests.integration.test_why_live_resolve import _create_catalog_with_project_and_include


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon_scenario(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via subprocess with KANON_ALLOW_INSECURE_REMOTES=1.

    Sets ``KANON_ALLOW_INSECURE_REMOTES=1`` so that ``file://`` source URLs
    (used in synthetic local-repo tests) pass the remote-URL security policy
    check in ``_live_resolve_tree`` and related code paths.  This is equivalent
    to the autouse ``_default_allow_insecure_remotes`` fixture in the
    integration conftest but applies to real subprocess invocations where
    pytest monkeypatch is not active.

    Args:
        args: Arguments to pass to ``kanon_cli``.
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
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Subprocess operator-path tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestWhyUrlPathOperatorPath:
    """Real CLI operator-path tests for ``kanon why`` url/path on the live-resolve path.

    Each test creates a fresh synthetic catalog bare repo, runs ``kanon add``
    (no install, no lockfile), and then asserts that ``kanon why <url>`` or
    ``kanon why <xml-path>`` exits 0 with the source name in stdout.
    """

    def test_why_url_exits_zero_no_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <project-url>`` exits 0 on live-resolve path (findings row 68).

        Flow:
          1. Build a synthetic catalog with entry ``zeta`` whose marketplace XML
             declares a project at ``https://github.com/oporg/zeta-project``.
          2. ``kanon add zeta --catalog-source <url>`` (no install, no lockfile).
          3. ``kanon why https://github.com/oporg/zeta-project --catalog-source <url>``.
          4. Assert exit 0.
          5. Assert ``ZETA`` (derived source name) appears in stdout.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "zeta"
        project_name = "zeta-project"
        project_fetch_url = "https://github.com/oporg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_catalog_with_project_and_include(
            catalog_dir,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        add_result = _run_kanon_scenario(
            [
                "add",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock absent after 'kanon add' (no install), but found it at {lock_file}"
        )

        why_result = _run_kanon_scenario(
            [
                "why",
                project_url,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {project_url}' on live-resolve path, "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert entry_name in why_result.stdout, f"Expected {entry_name!r} in stdout but got: {why_result.stdout!r}"

    def test_why_xml_path_exits_zero_no_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <include-xml-path>`` exits 0 on live-resolve path (findings row 69).

        Flow:
          1. Build a synthetic catalog with entry ``eta`` whose marketplace XML
             contains ``<include name="repo-specs/extra-eta.xml">``.
          2. ``kanon add eta --catalog-source <url>`` (no install, no lockfile).
          3. ``kanon why repo-specs/extra-eta.xml --catalog-source <url>``.
          4. Assert exit 0.
          5. Assert ``ETA`` (derived source name) appears in stdout.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "eta"
        include_xml_path = f"repo-specs/extra-{entry_name}.xml"

        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_catalog_with_project_and_include(
            catalog_dir,
            entry_name=entry_name,
            project_name="eta-project",
            project_fetch_url="https://github.com/oporg",
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        add_result = _run_kanon_scenario(
            [
                "add",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock absent after 'kanon add' (no install), but found it at {lock_file}"
        )

        why_result = _run_kanon_scenario(
            [
                "why",
                include_xml_path,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {include_xml_path}' on live-resolve path, "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert entry_name in why_result.stdout, f"Expected {entry_name!r} in stdout but got: {why_result.stdout!r}"
