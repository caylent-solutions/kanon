"""Integration tests for 'kanon doctor' effective catalog source resolution (subcheck 6).

Drives the full CLI via subprocess with controlled environment variables for
each catalog-source precedence combination.

AC-TEST-002: Integration tests in this file cover all precedence combinations
and assert stdout contains the resolved value AND the provenance suffix.
AC-CYCLE-001: End-to-end cycle test with a leaked KANON_CATALOG_SOURCE env var.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from tests.conftest import (
    write_kanon_doctor_integration as _write_kanon,
    write_lockfile_doctor_integration as _write_lockfile,
)


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


def _run_kanon_doctor(
    kanon_file: pathlib.Path,
    *,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run 'kanon doctor' via subprocess with controlled environment.

    Starts from a clean copy of os.environ with KANON_CATALOG_SOURCE stripped,
    then applies extra_env on top. This ensures tests start with a predictable
    environment regardless of what the operator's shell has exported.

    Args:
        kanon_file: Path to the .kanon file to pass as --kanon-file.
        extra_env: Additional environment variables to set before running.
        extra_args: Additional CLI arguments (beyond --kanon-file).

    Returns:
        The completed process object with stdout, stderr, and returncode.
    """
    env = dict(os.environ)
    # Strip any inherited catalog source to ensure test isolation.
    env.pop("KANON_CATALOG_SOURCE", None)
    if extra_env:
        env.update(extra_env)

    cmd = [sys.executable, "-m", "kanon_cli", "doctor", "--kanon-file", str(kanon_file)]
    if extra_args:
        cmd.extend(extra_args)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_minimal_kanon(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write a minimal .kanon file and return its path."""
    return _write_kanon(tmp_path, "src", "https://example.com/org/repo.git")


# ---------------------------------------------------------------------------
# AC-FUNC-002: Only KANON_CATALOG_SOURCE is set (no CLI flag, no lockfile).
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorEffectiveSourceEnvVarOnly:
    """kanon doctor with only KANON_CATALOG_SOURCE set prints env var value + provenance."""

    def test_env_var_value_appears_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """Stdout contains the KANON_CATALOG_SOURCE value."""
        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
        )

        assert env_value in result.stdout

    def test_env_var_provenance_suffix_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """Stdout contains the env-var provenance suffix."""
        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
        )

        assert "(from KANON_CATALOG_SOURCE env var)" in result.stdout


# ---------------------------------------------------------------------------
# AC-FUNC-001: CLI flag takes precedence over KANON_CATALOG_SOURCE env var.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorEffectiveSourceCliWins:
    """kanon doctor --catalog-source wins over KANON_CATALOG_SOURCE when both are set."""

    def test_cli_value_appears_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """Stdout contains the --catalog-source CLI flag value, not the env var value."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
            extra_args=["--catalog-source", cli_value],
        )

        assert cli_value in result.stdout

    def test_cli_provenance_suffix_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """Stdout contains the CLI-flag provenance suffix when both CLI and env var are set."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
            extra_args=["--catalog-source", cli_value],
        )

        assert "(from --catalog-source CLI flag)" in result.stdout

    def test_env_value_absent_from_stdout_when_cli_wins(self, tmp_path: pathlib.Path) -> None:
        """Env var value does not appear in stdout when CLI flag overrides it."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
            extra_args=["--catalog-source", cli_value],
        )

        assert env_value not in result.stdout


# ---------------------------------------------------------------------------
# AC-FUNC-003: A schema-v4 lockfile no longer contributes a catalog source.
#
# Schema v4 (spec Section 5.2 / FR-7) removed the lockfile [catalog] block, so
# the lockfile no longer participates in the effective-source precedence chain.
# The chain is now: --catalog-source CLI flag -> KANON_CATALOG_SOURCE env var ->
# none. When a v4 lockfile is the only thing present (no CLI flag, no env var),
# the effective source is "(none configured)" -- the lockfile does NOT supply
# a catalog source the way the removed [catalog].source tier used to.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorEffectiveSourceLockfilePresent:
    """A present v4 lockfile does not contribute a catalog source to provenance."""

    def _write_v4_lockfile(self, directory: pathlib.Path, kanon_hash_val: str) -> pathlib.Path:
        """Write a schema-v4 .kanon.lock with one source and no [catalog] block."""
        return _write_lockfile(
            directory,
            kanon_hash_val=kanon_hash_val,
            source_name="src",
            url="https://example.com/org/repo.git",
            revision_spec="main",
            resolved_sha="a" * 40,
        )

    def test_lockfile_present_reports_none_configured(self, tmp_path: pathlib.Path) -> None:
        """With only a v4 lockfile (no CLI flag, no env var), doctor reports none configured.

        Under schema v4 the lockfile carries no catalog source, so it cannot stand
        in for the removed [catalog].source tier: the effective source is none.
        """
        from kanon_cli.core.kanon_hash import kanon_hash

        kanon_file = _write_minimal_kanon(tmp_path)
        real_hash = kanon_hash(kanon_file)
        self._write_v4_lockfile(tmp_path, real_hash)

        result = _run_kanon_doctor(kanon_file)

        assert "(none configured)" in result.stdout

    def test_lockfile_present_no_lockfile_catalog_provenance(self, tmp_path: pathlib.Path) -> None:
        """The removed lockfile-catalog provenance suffix never appears with a v4 lock."""
        from kanon_cli.core.kanon_hash import kanon_hash

        kanon_file = _write_minimal_kanon(tmp_path)
        real_hash = kanon_hash(kanon_file)
        self._write_v4_lockfile(tmp_path, real_hash)

        result = _run_kanon_doctor(kanon_file)

        assert "(from .kanon.lock [catalog].source)" not in result.stdout

    def test_env_var_wins_over_present_lockfile(self, tmp_path: pathlib.Path) -> None:
        """KANON_CATALOG_SOURCE supplies the effective source even when a v4 lockfile is present.

        Confirms the lockfile does not pre-empt the env-var tier: with a v4 lock on
        disk and KANON_CATALOG_SOURCE set, the env-var value (and its provenance
        suffix) is what doctor reports.
        """
        from kanon_cli.core.kanon_hash import kanon_hash

        env_value = "https://env.example.com/repo.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)
        real_hash = kanon_hash(kanon_file)
        self._write_v4_lockfile(tmp_path, real_hash)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": env_value},
        )

        assert env_value in result.stdout
        assert "(from KANON_CATALOG_SOURCE env var)" in result.stdout


# ---------------------------------------------------------------------------
# AC-FUNC-004: No source configured (no CLI flag, no env var, no lockfile).
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorEffectiveSourceNoneConfigured:
    """kanon doctor reports 'none configured' when no catalog source is available."""

    def test_none_configured_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """Stdout contains 'none configured' indicator when no source is set."""
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(kanon_file)

        assert "(none configured)" in result.stdout

    def test_none_configured_mentions_commands_will_fail(self, tmp_path: pathlib.Path) -> None:
        """Stdout mentions that commands requiring a catalog source will fail."""
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(kanon_file)

        assert "commands requiring" in result.stdout or "will fail" in result.stdout


# ---------------------------------------------------------------------------
# AC-CYCLE-001: Leaked env var scenario.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorEffectiveSourceLeakedEnvVar:
    """kanon doctor surfaces KANON_CATALOG_SOURCE leakage from a shell profile.

    This is the primary user-facing purpose of subcheck 6 (spec Section 3.6):
    an operator in a workspace that should NOT use a particular catalog can
    run 'kanon doctor' and see, via the provenance suffix, that their env var
    is leaking into the session.
    """

    def test_leaked_value_appears_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """The leaked KANON_CATALOG_SOURCE value appears in stdout."""
        leaked_value = "https://example.invalid/leaked.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": leaked_value},
        )

        assert leaked_value in result.stdout

    def test_leaked_env_var_provenance_is_surfaced(self, tmp_path: pathlib.Path) -> None:
        """Provenance suffix names the env var so the operator sees the leakage.

        AC-CYCLE-001: Set KANON_CATALOG_SOURCE to a leaked value in the environment;
        run kanon doctor in a workspace that should NOT use that catalog;
        assert stdout's provenance suffix names the env var.
        """
        leaked_value = "https://example.invalid/leaked.git@main"
        kanon_file = _write_minimal_kanon(tmp_path)

        result = _run_kanon_doctor(
            kanon_file,
            extra_env={"KANON_CATALOG_SOURCE": leaked_value},
        )

        assert "(from KANON_CATALOG_SOURCE env var)" in result.stdout
