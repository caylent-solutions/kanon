"""Subprocess operator-path tests for 'kanon doctor' cache-only flags.

These tests verify that --refresh-completion-cache and --prune-cache work in
a workspace-free directory (no .kanon present) by invoking the real 'kanon'
CLI as a subprocess, exactly as an operator would.

Both tests FAIL against the unfixed feat branch HEAD: the WORKSPACE_FREE_FLAGS
short-circuit does not fire because the argparse Namespace injected by the real
CLI dispatch includes extra truthy attributes (catalog_source=_UNSET, func=...)
that prevent the active-flag set from being a subset of WORKSPACE_FREE_FLAGS.
The result is that _check_kanon_hash is reached and exits 1 with "no kanon
workspace". Findings rows 75 and 76.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


# ---------------------------------------------------------------------------
# Parametrize constants
# ---------------------------------------------------------------------------

_CACHE_FLAG_PARAMS = [
    pytest.param(
        "--refresh-completion-cache",
        "Completion cache refreshed:",
        id="refresh_completion_cache",
    ),
    pytest.param(
        "--prune-cache",
        "Cache pruned:",
        id="prune_cache",
    ),
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_doctor_cache_flag(
    tmp_path: pathlib.Path,
    flag: str,
    expected_output_substring: str,
) -> None:
    """Run 'kanon doctor <flag>' from an empty cwd and assert pass contract.

    Invokes the real 'kanon' CLI as a subprocess from tmp_path (no .kanon
    present). Sets KANON_HOME to tmp_path so the cache resolves under
    <KANON_HOME>/cache. Asserts exit 0, a cache-op info-line in combined
    output, and no "no kanon workspace" error in stderr.

    Args:
        tmp_path: Empty temporary directory with no .kanon file.
        flag: CLI flag string to pass to 'kanon doctor', e.g.
            '--refresh-completion-cache'.
        expected_output_substring: Substring that must appear in stdout+stderr,
            e.g. 'Completion cache refreshed:' or 'Cache pruned:'.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(mode=0o700)

    # The cache always resolves under <KANON_HOME>/cache; KANON_HOME=tmp_path
    # makes the resolved cache equal cache_dir (= tmp_path / "cache").
    extra_env: dict[str, str] = {"KANON_HOME": str(cache_dir.parent)}

    result = run_kanon(
        "doctor",
        flag,
        cwd=tmp_path,
        extra_env=extra_env,
    )

    combined_output = result.stdout + result.stderr

    assert result.returncode == 0, (
        f"Expected exit 0 for 'kanon doctor {flag}' in workspace-free cwd; "
        f"got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert expected_output_substring in combined_output, (
        f"Expected cache-op info-line '{expected_output_substring}' in combined output; "
        f"got:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "no kanon workspace" not in result.stderr, (
        f"Expected no workspace-not-found error in stderr; got:\nstderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestDoctorCacheFlagsWorkspaceFree:
    """kanon doctor cache flags must succeed with no .kanon workspace present.

    These tests invoke the real 'kanon' CLI as a subprocess from an empty
    temporary directory to exercise the full dispatch path, including argparse,
    the CLI entrypoint, and the WORKSPACE_FREE_FLAGS short-circuit in
    doctor_command. Both --refresh-completion-cache and --prune-cache must exit
    0 and emit a cache-op info-line even when no .kanon workspace is present.
    """

    @pytest.mark.parametrize("flag,expected_output_substring", _CACHE_FLAG_PARAMS)
    def test_refresh_completion_cache_succeeds_in_empty_cwd(
        self,
        tmp_path: pathlib.Path,
        flag: str,
        expected_output_substring: str,
    ) -> None:
        """Cache flag exits 0 and emits info-line in empty cwd (no .kanon).

        Runs 'kanon doctor <flag>' from a temporary directory with no .kanon
        workspace. Asserts exit 0, a cache-op output line, and no
        "no kanon workspace" error in stderr. Covers both flags via parametrize.

        Args:
            tmp_path: Pytest-provided empty temporary directory.
            flag: CLI flag to pass to 'kanon doctor'.
            expected_output_substring: Substring that must appear in combined
                stdout+stderr output.
        """
        _run_doctor_cache_flag(tmp_path, flag, expected_output_substring)

    @pytest.mark.parametrize("flag,expected_output_substring", _CACHE_FLAG_PARAMS)
    def test_prune_cache_succeeds_in_empty_cwd(
        self,
        tmp_path: pathlib.Path,
        flag: str,
        expected_output_substring: str,
    ) -> None:
        """Cache flag exits 0 and does not emit workspace error (no .kanon).

        Mirrors test_refresh_completion_cache_succeeds_in_empty_cwd to satisfy
        AC-FUNC-001 which requires both named test methods to be present.
        Covers both flags via parametrize.

        Args:
            tmp_path: Pytest-provided empty temporary directory.
            flag: CLI flag to pass to 'kanon doctor'.
            expected_output_substring: Substring that must appear in combined
                stdout+stderr output.
        """
        _run_doctor_cache_flag(tmp_path, flag, expected_output_substring)
