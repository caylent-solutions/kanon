"""Integration test: `kanon doctor --refresh-completion-cache --prune-cache` combined.

COMBINED-MODE (E44 row 77): invoking `kanon doctor` with both cache flags must
produce cache-action output for both operations and exit 0.

After the E49-F5 fix, the WORKSPACE_FREE_FLAGS short-circuit fires correctly
when only cache flags are active. The `active_flag_names` computation now uses
`value is True` (boolean strict equality) rather than `if value` (truthiness)
to exclude non-flag attributes injected by argparse set_defaults() -- specifically
`catalog_source=_UNSET` (a truthy sentinel) and `func=run_doctor` (a callable).
As a result, when only `--refresh-completion-cache` and `--prune-cache` are
active, the active_flag_names set is exactly `{"refresh_completion_cache",
"prune_cache"}`, which IS a subset of WORKSPACE_FREE_FLAGS, so the
short-circuit fires and workspace subchecks are skipped.

This test was updated from its original E44 form: the original asserted that
per-subcheck `[ok] <name>` lines appeared on stdout alongside cache-action
output. That assertion relied on `catalog_source=_UNSET` being truthy and
preventing the short-circuit -- i.e., it depended on the DEFECT-013 bug to
make both paths run simultaneously. After E49-F5 fixes the bug, only cache ops
run when only cache flags are active; workspace subchecks are skipped.

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
# INPUT-DRIVEN"; output substrings live here, not inside the test body.
# ---------------------------------------------------------------------------

# Substrings that must appear in combined (stdout + stderr) output per the
# E27 cache-action contract. `_print_finding` emits `INFO: {message}` to
# stderr; we match the stable message prefix rather than the full message.
EXPECTED_CACHE_ACTION_SUBSTRINGS: list[str] = [
    "Completion cache refreshed:",
    "Cache pruned:",
]

# Number of days used to create "old" (expired) cache files. Must exceed
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
    """kanon doctor combined-mode: both cache flags produce cache-op output.

    When `kanon doctor --refresh-completion-cache --prune-cache` is invoked via
    subprocess, both cache-action output lines must be emitted and the command
    must exit 0. After the E49-F5 fix, the WORKSPACE_FREE_FLAGS short-circuit
    fires when only cache flags are active (whether or not a workspace is
    present), so workspace subchecks are skipped.
    """

    def test_combined_flags_run_all_cache_actions(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Combined cache flags produce both cache-op output lines and exit 0.

        Steps:
        1. Create a KANON_CACHE_DIR with a completion-cache subdir containing
           one old (expired) file, plus one old top-level file.
        2. Run `kanon doctor --refresh-completion-cache --prune-cache` from
           an empty directory with KANON_CACHE_DIR set.
        3. Assert exit code is 0 (both cache actions succeed).
        4. For each substring in EXPECTED_CACHE_ACTION_SUBSTRINGS, assert the
           combined output (stdout + stderr) contains the substring.

        Note: workspace subchecks (`[ok] <name>` lines) are NOT expected
        because the WORKSPACE_FREE_FLAGS short-circuit fires when only cache
        flags are active. Workspace subchecks only run when a workspace-requiring
        flag (e.g. --strict-drift) is combined with the cache flags.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        # -- Step 1: create cache dir with expired content --
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

        # -- Step 2: kanon doctor --refresh-completion-cache --prune-cache --
        env_with_cache = dict(os.environ)
        env_with_cache["KANON_CACHE_DIR"] = str(cache_dir)
        env_with_cache.pop("KANON_CATALOG_SOURCES", None)

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
            cwd=str(tmp_path),
        )

        combined_output = doctor_result.stdout + doctor_result.stderr

        # -- Step 3: exit code must be 0 --
        assert doctor_result.returncode == 0, (
            f"kanon doctor combined-flags failed (expected exit 0, got "
            f"{doctor_result.returncode}).\n"
            f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )

        # -- Step 4: cache-action substrings in combined output (E27 contract) --
        for expected_substring in EXPECTED_CACHE_ACTION_SUBSTRINGS:
            assert expected_substring in combined_output, (
                f"Expected cache-action output containing '{expected_substring}' "
                f"but it was not found in combined output.\n"
                f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
            )

    def test_combined_flags_workspace_workspace_requiring_flag_still_checks(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Combining cache flags with --strict-drift requires a workspace.

        When --refresh-completion-cache or --prune-cache is combined with a
        workspace-requiring flag (--strict-drift), the WORKSPACE_FREE_FLAGS
        short-circuit does NOT fire because strict_drift=True is not in
        WORKSPACE_FREE_FLAGS. Running in an empty cwd (no .kanon) must produce
        a non-zero exit and a "no kanon workspace" error.

        Args:
            tmp_path: Pytest-provided temporary directory with no .kanon file.
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(mode=KANON_CACHE_DIR_MODE)

        env_with_cache = dict(os.environ)
        env_with_cache["KANON_CACHE_DIR"] = str(cache_dir)
        env_with_cache.pop("KANON_CATALOG_SOURCES", None)

        doctor_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "doctor",
                "--refresh-completion-cache",
                "--strict-drift",
            ],
            capture_output=True,
            text=True,
            env=env_with_cache,
            cwd=str(tmp_path),
        )

        assert doctor_result.returncode == 1, (
            f"Expected exit 1 when combining cache flag with --strict-drift in "
            f"empty cwd; got {doctor_result.returncode}.\n"
            f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )
        assert "no kanon workspace" in doctor_result.stderr, (
            f"Expected 'no kanon workspace' error in stderr when workspace-requiring "
            f"flag is active; got:\nstderr: {doctor_result.stderr!r}"
        )

    def test_combined_flags_with_workspace_requiring_flag_in_workspace_runs_subchecks(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Cache flag + --strict-drift in a valid workspace runs workspace subchecks.

        When a cache flag is combined with --strict-drift and a valid workspace
        is present, the short-circuit does NOT fire and workspace subchecks run.
        Assertions verify exit 0 (all subchecks pass) and cache-op output.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        # Create a synthetic catalog repo and workspace.
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["widget"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        add_result = _run_kanon(
            ["add", "widget", "--catalog-source", catalog_source],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected exit 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        env_no_catalog = dict(os.environ)
        env_no_catalog.pop("KANON_CATALOG_SOURCES", None)

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

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        completion_cache = cache_dir / "completion-cache"
        completion_cache.mkdir(mode=KANON_CACHE_DIR_MODE)
        comp_file = completion_cache / "comp.json"
        comp_file.write_bytes(b"c" * 64)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        old_dt = now - datetime.timedelta(days=_OLD_DAYS)
        mtime = comp_file.stat().st_mtime
        os.utime(str(comp_file), (old_dt.timestamp(), mtime))

        env_with_cache = dict(env_no_catalog)
        env_with_cache["KANON_CACHE_DIR"] = str(cache_dir)

        doctor_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "doctor",
                "--refresh-completion-cache",
                "--strict-drift",
            ],
            capture_output=True,
            text=True,
            env=env_with_cache,
            cwd=str(workspace),
        )

        assert doctor_result.returncode == 0, (
            f"Expected exit 0 for cache flag + --strict-drift in valid workspace; "
            f"got {doctor_result.returncode}.\n"
            f"stdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )
        assert "Completion cache refreshed:" in (doctor_result.stdout + doctor_result.stderr), (
            f"Expected 'Completion cache refreshed:' in output; "
            f"got:\nstdout: {doctor_result.stdout!r}\nstderr: {doctor_result.stderr!r}"
        )
        assert "kanon_hash consistency" in doctor_result.stdout, (
            f"Expected 'kanon_hash consistency' workspace subcheck in stdout; got:\nstdout: {doctor_result.stdout!r}"
        )
