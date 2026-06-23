"""Integration test: bare `kanon doctor` (no flags) emits per-subcheck status lines.

DEFECT-012: the default `kanon doctor` run emits only the "Effective catalog
source: <url>" line and no per-subcheck `[ok] <name>` status lines for
subchecks 1, 3, and 4.

This test asserts the expected post-fix contract and FAILS against the
unfixed feat-branch HEAD: each subcheck must emit at least one `[ok] <name>`
line on stdout when the workspace is healthy.

Autouse fixtures from tests/integration/conftest.py (spec sec 3.2) are
inherited automatically: _mock_resolve_ref_to_sha, _mock_check_sha_reachable,
_auto_create_manifest_on_walk, _default_allow_insecure_remotes.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E33 (Failing test + Verification + Edge cases),
Section 3.1 (synthetic-fixture helpers), Section 3.2 (autouse fixtures).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- per CLAUDE.md "ALL CODE MUST BE DYNAMIC AND
# INPUT-DRIVEN"; subcheck names live here, not inside the test body.
# ---------------------------------------------------------------------------

EXPECTED_DOCTOR_SUBCHECK_NAMES: list[str] = [
    "kanon_hash consistency",
    "no orphaned lock entries",
    "no branch drift",
]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorDefaultSubcheckOutput:
    """Bare `kanon doctor` must emit `[ok] <name>` per-subcheck lines on a healthy workspace."""

    def test_default_run_emits_per_subcheck_status_lines(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """kanon doctor (no flags) emits `[ok] <name>` for every expected subcheck.

        Steps:
        1. Create a synthetic catalog bare repo with a `foo` entry tagged 1.0.0.
        2. Run `kanon add foo --catalog-source <synthetic-url>` (writes .kanon).
        3. Run `kanon install` (hermetic: installs the sources declared in .kanon
           and writes the schema-v4 .kanon.lock; no catalog source is consulted).
        4. Run `kanon doctor` (no flags) in the workspace.
        5. Assert exit code is 0.
        6. For each name in EXPECTED_DOCTOR_SUBCHECK_NAMES, assert that at least
           one line in stdout matches the regex `^\\[ok\\] <name>`.

        The assertion is per-name: a missing single subcheck causes a descriptive
        failure message naming the specific absent subcheck line.
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Step 2: kanon add foo --catalog-source <url>
        add_result = _run_kanon(
            ["add", "foo", "--catalog-source", catalog_source],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected exit 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        # Step 3: kanon install is hermetic -- it installs exactly the sources
        # declared in .kanon and never resolves a catalog source. Strip
        # KANON_CATALOG_SOURCES so install's hermetic guard does not reject the run.
        env_without_catalog = dict(os.environ)
        env_without_catalog.pop("KANON_CATALOG_SOURCES", None)

        install_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env_without_catalog,
            cwd=str(workspace),
        )
        assert install_result.returncode == 0, (
            f"kanon install failed (expected exit 0, got {install_result.returncode}).\n"
            f"stdout: {install_result.stdout!r}\nstderr: {install_result.stderr!r}"
        )

        # Step 4 + 5: kanon doctor (no flags) must exit 0
        doctor_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "doctor"],
            capture_output=True,
            text=True,
            env=env_without_catalog,
            cwd=str(workspace),
        )
        assert doctor_result.returncode == 0, (
            f"kanon doctor failed (expected exit 0, got {doctor_result.returncode}).\n"
            f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )

        stdout_lines = doctor_result.stdout.splitlines()

        # Step 6: each expected subcheck name must appear as `[ok] <name>`
        for subcheck_name in EXPECTED_DOCTOR_SUBCHECK_NAMES:
            pattern = re.compile(r"^\[ok\] " + re.escape(subcheck_name) + r"$")
            matching_lines = [line for line in stdout_lines if pattern.match(line)]
            assert len(matching_lines) >= 1, (
                f"Expected at least one stdout line matching "
                f"`[ok] {subcheck_name}` but found none.\n"
                f"Full stdout:\n{doctor_result.stdout!r}\n"
                f"Full stderr:\n{doctor_result.stderr!r}"
            )
