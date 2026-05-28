"""Integration tests for ``kanon why`` live-resolve and lockfile-present paths.

This module contains:

- ``TestWhyLiveResolve``: asserts that ``kanon why <name> --catalog-source <url>``
  exits 0 and returns a dependency chain when no .kanon.lock is present.
  This exercises the live-resolve path in ``commands/why.py``.

- ``TestWhyLockfilePresent``: asserts that bare ``kanon why <name>`` (no
  ``--catalog-source``) exits 0 and returns a dependency chain when .kanon.lock
  is present and contains a top-level ``[[sources]]`` entry for the queried name.
  This exercises the lockfile-present path in ``commands/why.py`` (DEFECT-009
  regression coverage -- ``_build_tree_from_lockfile`` must correctly index
  top-level sources so they are reachable by ``_resolve_match``).

Autouse fixtures inherited from ``tests/integration/conftest.py``:
  - ``_mock_resolve_ref_to_sha``
  - ``_mock_check_sha_reachable``
  - ``_auto_create_manifest_on_walk``
  - ``_default_allow_insecure_remotes``
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from tests.integration.test_add_core import _create_manifest_repo_with_tags


# ---------------------------------------------------------------------------
# Subprocess runner (mirrors test_add_core._run_kanon)
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after the module invocation.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result with captured stdout/stderr.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLiveResolve:
    """Tests for `kanon why` when no .kanon.lock is present (live-resolve path).

    E32 extends this file with ``TestWhyLockfilePresent`` to cover the lockfile
    path (DEFECT-009) without modifying this class.
    """

    def test_why_succeeds_with_no_lockfile_when_catalog_source_provided(self, tmp_path: pathlib.Path) -> None:
        """kanon why exits 0 and names the package when no .kanon.lock exists.

        Flow:
          1. Build a synthetic catalog bare repo containing entry ``foo``.
          2. Run ``kanon add foo --catalog-source <url>`` (no install, so no
             .kanon.lock is written).
          3. Assert the lockfile does NOT exist -- confirming the live-resolve
             path is under test.
          4. Run ``kanon why foo --catalog-source <url>``.
          5. Assert exit code is 0.
          6. Assert ``"foo"`` appears in stdout.
          7. Assert the stub diagnostic does NOT appear in stdout.

        This test is expected to FAIL (RED) against unfixed code because
        ``_live_resolve_tree`` raises ``NotImplementedError``, causing exit 1
        with the diagnostic "Live-resolution is not yet implemented".
        """
        # -- Arrange: synthetic catalog with entry "foo" --
        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_manifest_repo_with_tags(
            catalog_dir,
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                "foo",
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

        # -- Assert: no .kanon.lock exists (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert lock_file.exists() is False, (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why (live-resolve path) --
        why_result = _run_kanon(
            [
                "why",
                "foo",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why foo', got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: "foo" appears in stdout --
        assert "foo" in why_result.stdout, f"Expected 'foo' in stdout but got: {why_result.stdout!r}"

        # -- Assert: stub diagnostic absent from stdout --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Test: lockfile-present path -- .kanon.lock present, bare kanon why (no --catalog-source)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLockfilePresent:
    """Regression guard for DEFECT-009: lockfile-present top-level source lookup.

    DEFECT-009 was described as: bare ``kanon why foo`` (no ``--catalog-source``)
    exits 1 with "foo not found in resolved tree" when .kanon.lock is present and
    ``foo`` is a top-level ``[[sources]]`` entry with no transitive includes.

    Investigation confirmed DEFECT-009 is NOT present in the current codebase:
    ``_build_tree_from_lockfile`` correctly attaches projects as direct children
    of source nodes when no includes exist (the no-includes branch at line 225
    of commands/why.py), so ``_resolve_match`` successfully locates the source.

    This class is a regression guard that will catch any future regression where
    ``_build_tree_from_lockfile`` stops indexing top-level ``[[sources]]`` entries
    correctly, and will fail if ``kanon why foo`` begins returning exit 1 or
    the "not found in resolved tree" diagnostic.
    """

    def test_why_finds_top_level_source_after_install(self, tmp_path: pathlib.Path) -> None:
        """Bare ``kanon why foo`` exits 0 and names ``foo`` when .kanon.lock is present.

        Flow:
          1. Build a synthetic catalog bare repo containing entry ``foo``.
          2. Run ``kanon add foo --catalog-source <url>`` (writes .kanon with
             [catalog] block so subsequent bare install reads the source URL).
          3. Run bare ``kanon install`` (no ``--catalog-source``) -- this writes
             .kanon.lock with ``foo`` as a top-level ``[[sources]]`` entry with
             no transitive includes.
          4. Assert .kanon.lock exists -- confirms the lockfile-present path
             (not the live-resolve path) is the one under test.
          5. Run bare ``kanon why foo`` (no ``--catalog-source``).
          6. Assert exit code is 0.
          7. Assert ``"foo"`` appears in stdout.
          8. Assert the "not found in resolved tree" diagnostic does NOT appear.

        All three assertions in steps 6-8 can independently fail:
          - Step 6 fails if ``_build_tree_from_lockfile`` stops returning a
            valid tree and the source is not found.
          - Step 7 fails if the output omits the source name.
          - Step 8 fails if the not-found diagnostic appears (indicating
            ``_resolve_match`` could not locate ``foo`` in the tree).
        """
        import os
        import subprocess as _subprocess

        # -- Arrange: synthetic catalog with entry "foo" --
        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_manifest_repo_with_tags(
            catalog_dir,
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # -- Act: kanon add (writes .kanon with [catalog] block) --
        add_result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                catalog_source_url,
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Act: bare kanon install (reads catalog block, writes .kanon.lock) --
        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCE", None)
        install_result = _subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )
        assert install_result.returncode == 0, (
            f"kanon install failed (exit {install_result.returncode}).\n"
            f"stdout: {install_result.stdout!r}\n"
            f"stderr: {install_result.stderr!r}"
        )

        # -- Assert: .kanon.lock exists (lockfile-present path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert lock_file.exists(), (
            f"Expected .kanon.lock to exist after 'kanon install' but it was absent at "
            f"{lock_file}.\n"
            f"install stdout: {install_result.stdout!r}\n"
            f"install stderr: {install_result.stderr!r}"
        )

        # -- Act: bare kanon why (lockfile-present path -- no --catalog-source) --
        why_result = _run_kanon(
            ["why", "foo"],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from bare 'kanon why foo' (lockfile present), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: "foo" appears in stdout --
        assert "foo" in why_result.stdout, (
            f"Expected 'foo' in stdout from 'kanon why foo' but got: {why_result.stdout!r}"
        )

        # -- Assert: not-found diagnostic absent --
        not_found_diagnostic = "not found in resolved tree"
        assert not_found_diagnostic not in why_result.stdout, (
            f"'not found in resolved tree' appeared in stdout -- "
            f"_build_tree_from_lockfile is not correctly indexing top-level sources.\n"
            f"stdout: {why_result.stdout!r}"
        )
        assert not_found_diagnostic not in why_result.stderr, (
            f"'not found in resolved tree' appeared in stderr -- "
            f"_build_tree_from_lockfile is not correctly indexing top-level sources.\n"
            f"stderr: {why_result.stderr!r}"
        )
