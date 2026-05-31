"""Operator-path scenario tests for ``kanon why`` match-annotation surface (E56-F1).

These are subprocess (real CLI) tests asserting that ``kanon why`` surfaces the
matched category and queried token in its output for every query form:
  - T-PATH: ``kanon why <root-manifest-path>`` echoes the queried manifest path.
  - T-URL:  ``kanon why <project-url>`` echoes the queried canonical URL.
  - T-NAME: ``kanon why <name>`` still exits 0 with its source-rooted chain preserved.
  - T-MISS: ``kanon why <unknown>`` exits 1 with "not found in resolved tree" message.
  - T-JSON: ``kanon why <project-url> --format json`` carries a ``matched`` field
    with ``category`` and ``token``, with the ``chains`` array still present.

All subprocess calls use ``sys.executable -m kanon_cli`` and set
``KANON_ALLOW_INSECURE_REMOTES=1`` so that ``file://`` source URLs pass the
remote-URL security policy check.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from tests.integration.test_why_live_resolve import _create_catalog_with_project_and_include


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via subprocess with KANON_ALLOW_INSECURE_REMOTES=1.

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
) -> tuple[str, pathlib.Path, pathlib.Path, str]:
    """Build a synthetic catalog bare repo and a fresh workspace with a .kanon file.

    Creates a bare catalog repo containing entry ``entry_name`` whose marketplace
    XML has a ``<project>`` at ``<project_fetch_url>/<project_name>`` and an
    ``<include name="repo-specs/extra-<entry_name>.xml">`` element.  Runs
    ``kanon add <entry_name>`` to write the .kanon file without creating a lockfile.

    Args:
        tmp_path: pytest per-test temp directory.
        entry_name: The catalog entry name (e.g. ``"alpha"``).
        project_name: The project name suffix for the ``<project>`` element.
        project_fetch_url: The fetch URL base for the ``<remote>`` element.
        catalog_subdir: Subdirectory name under tmp_path for the catalog bare repo.

    Returns:
        A four-tuple of (catalog_source_url, workspace, kanon_file, root_manifest_path)
        where ``root_manifest_path`` is the relative path
        ``repo-specs/<entry_name>-marketplace.xml`` (the root-manifest path for T-PATH).

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

    add_result = _run_kanon(
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

    root_manifest_path = f"repo-specs/{entry_name}-marketplace.xml"
    return catalog_source_url, workspace, kanon_file, root_manifest_path


# ---------------------------------------------------------------------------
# Operator-path scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestWhySurfaceQueryAnnotation:
    """Real CLI operator-path tests for ``kanon why`` match-annotation output (AC-1..AC-7).

    Each test creates a fresh synthetic catalog bare repo, runs ``kanon add``
    (no install, no lockfile), and then asserts that ``kanon why`` surfaces the
    matched token in its output.
    """

    def test_why_path_token_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """T-PATH: ``kanon why <root-manifest-path>`` stdout CONTAINS the queried path (AC-1).

        Queries by the root-manifest XML path (``repo-specs/<entry>-marketplace.xml``).
        Asserts exit 0 and that the queried path string appears in stdout (annotation).
        FAILS at HEAD because the path is not echoed.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "surface-path"
        project_name = "surface-path-proj"
        project_fetch_url = "https://github.com/surfaceorg"

        catalog_source_url, workspace, kanon_file, root_manifest_path = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
        )

        why_result = _run_kanon(
            [
                "why",
                root_manifest_path,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {root_manifest_path}', "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert root_manifest_path in why_result.stdout, (
            f"Expected queried path {root_manifest_path!r} in stdout (match annotation) but got: {why_result.stdout!r}"
        )

    def test_why_url_token_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """T-URL: ``kanon why <project-url>`` stdout CONTAINS the queried canonical URL (AC-2).

        Queries by the project fetch URL.
        Asserts exit 0 and that the queried URL string appears in stdout (annotation).
        FAILS at HEAD because only ``<project>@<sha>`` appears.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "surface-url"
        project_name = "surface-url-proj"
        project_fetch_url = "https://github.com/surfaceorg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_source_url, workspace, kanon_file, _ = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
        )

        why_result = _run_kanon(
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
            f"Expected exit 0 from 'kanon why {project_url}', "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert project_url in why_result.stdout, (
            f"Expected queried URL {project_url!r} in stdout (match annotation) but got: {why_result.stdout!r}"
        )

    def test_why_name_chain_preserved(self, tmp_path: pathlib.Path) -> None:
        """T-NAME: ``kanon why <entry-name>`` exits 0 with source chain preserved (AC-3).

        Regression guard: the name path must still return the chain with ' -> '
        separators and the project at the end.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "surface-name"
        project_name = "surface-name-proj"
        project_fetch_url = "https://github.com/surfaceorg"

        catalog_source_url, workspace, kanon_file, _ = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
        )

        why_result = _run_kanon(
            [
                "why",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {entry_name}', "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        assert " -> " in why_result.stdout, f"Expected ' -> ' chain separator in stdout but got: {why_result.stdout!r}"

        assert project_name in why_result.stdout, (
            f"Expected project name {project_name!r} in stdout but got: {why_result.stdout!r}"
        )

    def test_why_miss_exits_one_with_message(self, tmp_path: pathlib.Path) -> None:
        """T-MISS: ``kanon why <unknown>`` exits 1 with "not found in resolved tree" (AC-4).

        The miss path must produce a handled error -- no traceback.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "surface-miss"
        project_name = "surface-miss-proj"
        project_fetch_url = "https://github.com/surfaceorg"
        unknown_url = "https://github.com/surfaceorg/does-not-exist"

        catalog_source_url, workspace, kanon_file, _ = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
        )

        why_result = _run_kanon(
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

    def test_why_json_matched_field_present(self, tmp_path: pathlib.Path) -> None:
        """T-JSON: ``kanon why <project-url> --format json`` carries a ``matched`` field (AC-6).

        Asserts:
          - Exit 0.
          - stdout is valid JSON.
          - Top-level object has a ``matched`` key with ``category`` and ``token`` sub-keys.
          - ``token`` contains the queried URL.
          - ``chains`` key is present and non-empty (existing chains data preserved).

        FAILS at HEAD because the JSON output has no ``matched`` field.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "surface-json"
        project_name = "surface-json-proj"
        project_fetch_url = "https://github.com/surfaceorg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_source_url, workspace, kanon_file, _ = _build_catalog_and_workspace(
            tmp_path,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
        )

        why_result = _run_kanon(
            [
                "why",
                project_url,
                "--format",
                "json",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {project_url} --format json', "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        parsed = json.loads(why_result.stdout)
        assert isinstance(parsed, dict), (
            f"Expected JSON dict from 'kanon why --format json', got {type(parsed).__name__}: {parsed!r}"
        )

        assert "matched" in parsed, f"Expected 'matched' key in JSON output, got keys: {list(parsed.keys())}"

        matched = parsed["matched"]
        assert "category" in matched, f"Expected 'category' in 'matched', got keys: {list(matched.keys())}"
        assert "token" in matched, f"Expected 'token' in 'matched', got keys: {list(matched.keys())}"

        assert project_url in matched["token"], (
            f"Expected queried URL {project_url!r} in matched['token'], got: {matched['token']!r}"
        )

        assert "chains" in parsed, (
            f"Expected 'chains' key in JSON output (chains data preserved), got keys: {list(parsed.keys())}"
        )
        assert len(parsed["chains"]) >= 1, f"Expected non-empty 'chains' list in JSON output, got: {parsed['chains']!r}"
