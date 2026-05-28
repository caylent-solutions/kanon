"""Integration test: `kanon doctor --refresh-completion-cache --prune-cache` combined.

COMBINED-MODE (E44 row 77): invoking `kanon doctor` with both cache flags AND in
a valid workspace context must produce BOTH groups of output simultaneously:

- Per-subcheck `[ok] <name>` lines on stdout (E33's contract -- DEFECT-012 fix).
- Cache-action `INFO: ...` lines on stderr (E27's contract -- DEFECT-013 fix).

When invoked via subprocess the argparse layer always sets `catalog_source` to the
`_UNSET` sentinel (a truthy `object()`), which is NOT in WORKSPACE_FREE_FLAGS.
Therefore `active_flag_names` is NOT a subset of WORKSPACE_FREE_FLAGS and the
workspace-free short-circuit does NOT fire -- both cache actions and all workspace
subchecks execute in the same invocation.

Autouse fixtures from tests/integration/conftest.py (spec sec 3.2) are inherited
automatically: _mock_resolve_ref_to_sha, _mock_check_sha_reachable,
_auto_create_manifest_on_walk, _default_allow_insecure_remotes.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E44 (Failing test + Verification row 77),
Section 3.1 (synthetic-fixture helpers), Section 3.2 (autouse fixtures).
"""

from __future__ import annotations

import datetime
import os
import pathlib
import re
import subprocess
import sys

import pytest

from kanon_cli.constants import KANON_CACHE_DIR_MODE
from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- per CLAUDE.md "ALL CODE MUST BE DYNAMIC AND
# INPUT-DRIVEN"; subcheck names and output substrings live here, not inside
# the test body.
# ---------------------------------------------------------------------------

# Subcheck names as emitted by `[ok] <name>` per the E33 structured-output
# contract (DOCTOR_SUBCHECK_* constants in commands/doctor.py).
EXPECTED_SUBCHECK_NAMES: list[str] = [
    "kanon_hash consistency",
    "no orphaned lock entries",
    "no branch drift",
]

# Substrings that must appear in combined (stdout + stderr) output per the
# E27 cache-action contract.  `_print_finding` emits `INFO: {message}` to
# stderr; we match the stable message prefix rather than the full message.
EXPECTED_CACHE_ACTION_SUBSTRINGS: list[str] = [
    "Completion cache refreshed:",
    "Cache pruned:",
]

# Number of days used to create "old" (expired) cache files.  Must exceed
# KANON_CACHE_PRUNE_AGE_DAYS (default 30) so the prune subcheck removes them.
_OLD_DAYS: int = 35


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_atime_old(path: pathlib.Path) -> None:
    """Set path atime to _OLD_DAYS ago, leaving mtime unchanged.

    Args:
        path: File whose atime is to be aged.
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    old_dt = now - datetime.timedelta(days=_OLD_DAYS)
    mtime = path.stat().st_mtime
    os.utime(str(path), (old_dt.timestamp(), mtime))


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorCombinedFlags:
    """kanon doctor combined-mode: cache flags + workspace subchecks run together.

    When `kanon doctor --refresh-completion-cache --prune-cache` is invoked via
    subprocess in a valid workspace, BOTH cache-action output (stderr) AND
    per-subcheck status lines (stdout) must be emitted in the same invocation.
    """

    def test_combined_flags_run_all_subchecks_plus_cache_actions(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Combined cache flags + workspace subchecks produce both output groups.

        Steps:
        1. Create a synthetic catalog bare repo with a `widget` entry tagged 1.0.0
           (via _create_manifest_repo_with_tags per spec section 3.1).
        2. Run `kanon add widget --catalog-source <file-url>` to write .kanon.
        3. Run `kanon install` to write .kanon.lock.
        4. Create a KANON_CACHE_DIR with a completion-cache subdir containing one
           old (expired) file, plus one old top-level file.
        5. Run `kanon doctor --refresh-completion-cache --prune-cache` in the
           workspace with KANON_CACHE_DIR set.
        6. Assert exit code is 0 (all subchecks pass, all cache actions succeed).
        7. For each name in EXPECTED_SUBCHECK_NAMES, assert stdout contains a
           line matching `[ok] <name>` (E33's structured Finding contract).
        8. For each substring in EXPECTED_CACHE_ACTION_SUBSTRINGS, assert the
           combined output (stdout + stderr) contains the substring (E27's contract).

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        # -- Step 1: synthetic catalog repo --
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["widget"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # -- Step 2: kanon add --
        add_result = _run_kanon(
            ["add", "widget", "--catalog-source", catalog_source],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected exit 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        # -- Step 3: kanon install (reads [catalog].source from .kanon file) --
        env_no_catalog = dict(os.environ)
        env_no_catalog.pop("KANON_CATALOG_SOURCE", None)

        install_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env_no_catalog,
            cwd=str(workspace),
        )
        assert install_result.returncode == 0, (
            f"kanon install failed (expected exit 0, got {install_result.returncode}).\n"
            f"stdout: {install_result.stdout!r}\nstderr: {install_result.stderr!r}"
        )

        # -- Step 4: create cache dir with expired content --
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_CACHE_DIR_MODE)

        # One expired file in completion-cache (refresh clears it).
        comp_file = completion_cache / "comp.json"
        comp_file.write_bytes(b"c" * 64)
        _set_atime_old(comp_file)

        # One expired top-level file (prune removes it).
        old_top = cache_dir / "old.json"
        old_top.write_bytes(b"o" * 128)
        _set_atime_old(old_top)

        # -- Step 5: kanon doctor --refresh-completion-cache --prune-cache --
        env_with_cache = dict(env_no_catalog)
        env_with_cache["KANON_CACHE_DIR"] = str(cache_dir)

        doctor_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "doctor",
                "--refresh-completion-cache",
                "--prune-cache",
            ],
            capture_output=True,
            text=True,
            env=env_with_cache,
            cwd=str(workspace),
        )

        # -- Step 6: exit code must be 0 --
        assert doctor_result.returncode == 0, (
            f"kanon doctor combined-flags failed (expected exit 0, got "
            f"{doctor_result.returncode}).\n"
            f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )

        stdout_lines = doctor_result.stdout.splitlines()
        combined_output = doctor_result.stdout + doctor_result.stderr

        # -- Step 7: per-subcheck `[ok] <name>` lines on stdout (E33 contract) --
        for subcheck_name in EXPECTED_SUBCHECK_NAMES:
            pattern = re.compile(r"^\[ok\] " + re.escape(subcheck_name) + r"$")
            matching_lines = [line for line in stdout_lines if pattern.match(line)]
            assert len(matching_lines) >= 1, (
                f"Expected at least one stdout line matching "
                f"`[ok] {subcheck_name}` but found none.\n"
                f"Full stdout:\n{doctor_result.stdout!r}\n"
                f"Full stderr:\n{doctor_result.stderr!r}"
            )

        # -- Step 8: cache-action substrings in combined output (E27 contract) --
        for expected_substring in EXPECTED_CACHE_ACTION_SUBSTRINGS:
            assert expected_substring in combined_output, (
                f"Expected cache-action output containing '{expected_substring}' "
                f"but it was not found in combined output.\n"
                f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
            )
