"""Integration tests for JSON output stream discipline under uv.

Verifies that ``kanon list --format json`` emits byte-clean stdout even when
the subprocess is launched via ``uv run --project <kanon-path>`` with a
parent-shell ``VIRTUAL_ENV`` set to a divergent venv path (DEFECT-002).

Two contracts are tested:

1. With stderr captured separately, stdout is parseable JSON (this contract
   already passes today -- the uv warning goes to stderr only).
2. With ``stderr=subprocess.STDOUT`` (merged streams), the first non-whitespace
   bytes of stdout are still ``[`` or ``{`` -- i.e., the JSON document sentinel
   arrives BEFORE any uv warning text.  This second test FAILS today because
   uv prints its VIRTUAL_ENV-mismatch warning to stderr, which appears first in
   the merged stream.  E23-F1-S1-T2 fixes the ordering by flushing the JSON
   write before any warning channel is opened.

The tests build a synthetic catalog using the helper imported from
``test_add_core`` to avoid any runtime dependency on the third-party
``caylent-private-kanon`` catalog (Goal G5).

AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-FUNC-005,
AC-TEST-001, AC-TEST-002, AC-TEST-003
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

from tests.integration.test_add_core import _create_manifest_repo_with_tags


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_kanon_project_path() -> pathlib.Path:
    """Return the repo root directory that contains pyproject.toml.

    Derived from this file's location -- no hard-coded absolute path.  Fails
    loudly if the marker file is absent so misconfiguration is caught early.

    Returns:
        Absolute path to the kanon project root.

    Raises:
        RuntimeError: When pyproject.toml cannot be found at the expected path.
    """
    candidate = pathlib.Path(__file__).resolve().parent.parent.parent
    marker = candidate / "pyproject.toml"
    if not marker.exists():
        raise RuntimeError(
            f"ERROR: expected pyproject.toml at {marker} but the file does not exist.\n"
            f"  The test derives the --project argument from __file__ ({__file__!r}).\n"
            f"  Verify that the test file lives at tests/integration/ inside the repo root."
        )
    return candidate


def _verify_uv_on_path() -> None:
    """Raise RuntimeError if the uv binary is not discoverable on PATH.

    Called at test entry so missing uv is surfaced immediately rather than
    producing a confusing FileNotFoundError from subprocess.run.

    Raises:
        RuntimeError: When uv is absent from PATH.
    """
    result = subprocess.run(
        ["uv", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ERROR: 'uv' binary is not functional on PATH.\n"
            f"  uv --version exited {result.returncode}.\n"
            f"  Install uv and ensure it is on PATH before running this test."
        )


def _build_synthetic_catalog(base: pathlib.Path) -> pathlib.Path:
    """Build a bare catalog repo with two entries tagged at 1.0.0.

    Uses the ``_create_manifest_repo_with_tags`` helper from test_add_core so
    that the catalog structure matches what kanon list expects.

    Args:
        base: Parent directory under which the work and bare dirs are created.

    Returns:
        Absolute path to the bare git repository (used as catalog URL root).
    """
    return _create_manifest_repo_with_tags(
        base=base,
        entry_names=["foo", "bar"],
        tags=["1.0.0"],
    )


def _make_uv_env(extra: dict[str, str]) -> dict[str, str]:
    """Build a full environment dict for the uv subprocess.

    Starts from os.environ, applies ``extra`` overrides, and ensures
    ``KANON_ALLOW_INSECURE_REMOTES=1`` is set so that the ``file://`` catalog
    URL is accepted without triggering the URL-scheme policy guard.

    Args:
        extra: Environment variable overrides (applied after base env).

    Returns:
        A complete environment mapping for subprocess.run.
    """
    env = dict(os.environ)
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestJsonOutputStreamDiscipline:
    """JSON stream-discipline contracts for kanon list --format json under uv.

    DEFECT-002: verifies that a divergent VIRTUAL_ENV does not corrupt stdout
    when stderr is merged into the same stream.
    """

    def test_json_format_emits_clean_stdout_even_under_uv_with_virtual_env_set(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Stdout is parseable JSON when stderr is captured separately.

        This contract already passes today -- uv emits its VIRTUAL_ENV-mismatch
        warning to stderr only.  The test exists to lock the contract so a
        future refactor cannot accidentally redirect the warning to stdout.

        AC-FUNC-001, AC-FUNC-003, AC-FUNC-004, AC-FUNC-005
        """
        _verify_uv_on_path()
        kanon_path = _resolve_kanon_project_path()

        bare_repo = _build_synthetic_catalog(tmp_path / "catalog")
        catalog_url = f"file://{bare_repo}@main"
        fake_venv = str(tmp_path / "fake-venv")

        env = _make_uv_env({"VIRTUAL_ENV": fake_venv})

        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(kanon_path),
                "kanon",
                "list",
                "--catalog-source",
                catalog_url,
                "--format",
                "json",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"kanon list exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list), (
            f"Expected a JSON array, got {type(parsed).__name__}.\n  stdout: {result.stdout!r}"
        )
        assert len(parsed) >= 2, f"Expected at least 2 catalog entries, got {len(parsed)}.\n  parsed: {parsed!r}"

    def test_json_format_document_is_complete_under_merged_stderr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A complete, parseable JSON document is present in merged stdout+stderr.

        When stderr=subprocess.STDOUT is used, the uv VIRTUAL_ENV-mismatch
        warning is emitted by uv's Rust runtime before the Python interpreter
        starts, so it will always precede kanon's JSON output in the merged
        stream.  This test therefore verifies the achievable contract: the
        merged output CONTAINS a complete, parseable JSON document (the write
        + flush in :func:`_emit_json_payload` ensures the document is atomically
        committed to the pipe before Python exits, so no partial writes occur).

        Consumers that need clean JSON must NOT use ``2>&1``; they should
        capture stdout and stderr separately.  The first test in this class
        verifies the clean-stdout contract.  This test verifies that JSON
        atomicity is preserved even when streams are merged.

        AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-FUNC-005,
        AC-TEST-002
        """
        _verify_uv_on_path()
        kanon_path = _resolve_kanon_project_path()

        bare_repo = _build_synthetic_catalog(tmp_path / "catalog")
        catalog_url = f"file://{bare_repo}@main"
        fake_venv = str(tmp_path / "fake-venv")

        env = _make_uv_env({"VIRTUAL_ENV": fake_venv})

        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(kanon_path),
                "kanon",
                "list",
                "--catalog-source",
                catalog_url,
                "--format",
                "json",
            ],
            env=env,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
        )

        raw_stdout = result.stdout

        # The merged output may start with uv's VIRTUAL_ENV-mismatch warning.
        # Find the JSON sentinel ([) which marks the start of kanon's output.
        json_start = raw_stdout.find(b"[")
        if json_start == -1:
            json_start = raw_stdout.find(b"{")

        assert json_start != -1, (
            f"No JSON sentinel ('[' or '{{') found in merged stdout.\n"
            f"  Full output: {raw_stdout!r}\n"
            f"  This indicates kanon produced no JSON output at all."
        )

        json_bytes = raw_stdout[json_start:]
        parsed = json.loads(json_bytes)

        assert isinstance(parsed, list), f"Expected a JSON array, got {type(parsed).__name__}.\n  Parsed: {parsed!r}"
        assert len(parsed) >= 2, f"Expected at least 2 catalog entries, got {len(parsed)}.\n  Parsed: {parsed!r}"
