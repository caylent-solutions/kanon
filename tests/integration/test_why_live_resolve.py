"""Integration tests for `kanon why` live-resolve path (no .kanon.lock present).

This module contains:

- ``TestWhyLiveResolve``: asserts that `kanon why <name> --catalog-source <url>`
  exits 0 and returns a dependency chain when no .kanon.lock is present.
  This exercises the live-resolve path in ``commands/why.py``.

E32 extends this file with ``TestWhyLockfilePresent`` (lockfile-present path,
DEFECT-009) without modification to this module.

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

    def test_why_succeeds_with_no_lockfile_when_catalog_source_provided(
        self, tmp_path: pathlib.Path
    ) -> None:
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
            "Expected .kanon.lock to be absent after 'kanon add' (no install ran), "
            f"but found it at {lock_file}"
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
        assert "foo" in why_result.stdout, (
            f"Expected 'foo' in stdout but got: {why_result.stdout!r}"
        )

        # -- Assert: stub diagnostic absent from stdout --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\n"
            f"stdout: {why_result.stdout!r}"
        )
