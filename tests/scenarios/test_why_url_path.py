"""Operator-path scenario tests for ``kanon why`` url/path live-resolve (E51-F2).

These are subprocess (real CLI) tests asserting that ``kanon why <project-url>``
and ``kanon why <include-xml-path>`` exit 0 against a synthetic catalog with no
lockfile present, and that an unknown URL exits 1 with a handled error message.
They exercise the full operator path to close findings rows 68 and 69 from the
2026-05-30 manual re-run.

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
# Shared fixture builder
# ---------------------------------------------------------------------------


def _build_catalog_and_workspace(
    tmp_path: pathlib.Path,
    entry_name: str,
    project_name: str,
    project_fetch_url: str,
    catalog_subdir: str = "catalog",
) -> tuple[str, pathlib.Path, pathlib.Path]:
    """Build a synthetic catalog bare repo and a fresh workspace with a .kanon file.

    Creates a bare catalog repo containing entry ``entry_name`` whose marketplace
    XML has a ``<project>`` at ``<project_fetch_url>/<project_name>`` and an
    ``<include name="repo-specs/extra-<entry_name>.xml">`` element.  Runs
    ``kanon add <entry_name>`` to write the .kanon file without creating a lockfile.

    Args:
        tmp_path: pytest per-test temp directory.
        entry_name: The catalog entry name (e.g. ``"zeta"``).
        project_name: The project name suffix for the ``<project>`` element.
        project_fetch_url: The fetch URL base for the ``<remote>`` element.
        catalog_subdir: Subdirectory name under tmp_path for the catalog bare repo.

    Returns:
        A three-tuple of (catalog_source_url, workspace, kanon_file).

    Raises:
        AssertionError: If ``kanon add`` fails or unexpectedly creates a lockfile.
    """
    catalog_dir = tmp_path / catalog_subdir
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

    return catalog_source_url, workspace, kanon_file


# ---------------------------------------------------------------------------
# Subprocess operator-path tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestWhyUrlPathOperatorPath:
    """Real CLI operator-path tests for ``kanon why`` url/path on the live-resolve path.

    Each test creates a fresh synthetic catalog bare repo, runs ``kanon add``
    (no install, no lockfile), and then asserts that ``kanon why <url>`` or
    ``kanon why <xml-path>`` exits 0 with the source name in stdout.

    The negative test verifies that an unknown URL exits 1 with the handled
    "not found in resolved tree" message (not a traceback).
    """

    def test_why_url_exits_zero_no_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <project-url>`` exits 0 on live-resolve path (findings row 68).

        Flow:
          1. Build a synthetic catalog with entry ``zeta`` whose marketplace XML
             declares a project at ``https://github.com/oporg/zeta-project``.
          2. ``kanon add zeta --catalog-source <url>`` (no install, no lockfile).
          3. ``kanon why https://github.com/oporg/zeta-project --catalog-source <url>``.
          4. Assert exit 0.
          5. Assert ``zeta`` (source entry name) appears in stdout.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "zeta"
        project_name = "zeta-project"
        project_fetch_url = "https://github.com/oporg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_source_url, workspace, kanon_file = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
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
          5. Assert ``eta`` (source entry name) appears in stdout.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "eta"
        include_xml_path = f"repo-specs/extra-{entry_name}.xml"

        catalog_source_url, workspace, kanon_file = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name="eta-project",
            project_fetch_url="https://github.com/oporg",
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

    def test_why_unknown_url_exits_one_no_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <unknown-url>`` exits 1 with "not found in resolved tree" message.

        Flow:
          1. Build a synthetic catalog with entry ``theta`` (project URL resolvable).
          2. ``kanon add theta --catalog-source <url>`` (no install, no lockfile).
          3. ``kanon why https://github.com/unknown-org/no-such-project --catalog-source <url>``.
          4. Assert exit 1.
          5. Assert "not found in resolved tree" appears in stderr.
          6. Assert no Python traceback appears in stderr (handled error, not a crash).

        The miss path on the live-resolve path must produce the same handled error
        as on the lockfile path -- no raw traceback, no silent success.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "theta"
        unknown_url = "https://github.com/unknown-org/no-such-project"

        catalog_source_url, workspace, kanon_file = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name="theta-project",
            project_fetch_url="https://github.com/oporg",
        )

        why_result = _run_kanon_scenario(
            [
                "why",
                unknown_url,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 1, (
            f"Expected exit 1 from 'kanon why {unknown_url}' (unknown URL), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert "not found in resolved tree" in why_result.stderr, (
            f"Expected 'not found in resolved tree' in stderr for unknown URL, but got stderr: {why_result.stderr!r}"
        )

        assert "Traceback" not in why_result.stderr, (
            f"Expected a handled error message (no traceback), "
            f"but a Python traceback appeared in stderr: {why_result.stderr!r}"
        )
