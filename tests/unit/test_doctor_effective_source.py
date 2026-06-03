"""Unit tests for kanon_cli.commands.doctor._check_effective_catalog_source.

Covers all precedence permutations for catalog source resolution:
  1. CLI flag (--catalog-source) takes highest precedence.
  2. KANON_CATALOG_SOURCE env var wins when CLI flag is absent.
  3. Lockfile [catalog].source wins when neither CLI flag nor env var is set.
  4. When none of the above is present, a "none configured" message is returned.

AC-TEST-001: Every parametrized case asserts DoctorFinding.message contains
the expected provenance suffix.
AC-FUNC-005: _check_effective_catalog_source is a pure function that returns
a DoctorFinding(kind="info", ...) and reads no global state directly.
AC-FUNC-006: The provenance suffix is mandatory in every output path.
"""

from __future__ import annotations

import argparse

import pytest

from kanon_cli.commands.doctor import DoctorFinding, _UNSET, _check_effective_catalog_source
from kanon_cli.constants import CATALOG_ENV_VAR
from kanon_cli.core.lockfile import CatalogBlock, Lockfile


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_args(catalog_source: str | None) -> argparse.Namespace:
    """Return an argparse Namespace with catalog_source set to the sentinel when None.

    When catalog_source is None, uses _UNSET (the sentinel) to simulate the
    argparse default (i.e. the user did NOT supply --catalog-source on the
    command line).  When a string is provided, it simulates an explicit CLI
    flag value.
    """
    if catalog_source is None:
        return argparse.Namespace(catalog_source=_UNSET)
    return argparse.Namespace(catalog_source=catalog_source)


def _make_lockfile_with_catalog(catalog_source: str) -> Lockfile:
    """Return a minimal Lockfile with the given catalog source value."""
    return Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source=catalog_source,
            url="https://example.com/org/catalog.git",
            revision_spec="main",
            resolved_ref="main",
            resolved_sha="a" * 40,
        ),
        sources=[],
    )


def _make_lockfile_empty_catalog() -> Lockfile:
    """Return a Lockfile whose catalog.source is an empty string."""
    return Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=[],
    )


# ---------------------------------------------------------------------------
# Tests: _check_effective_catalog_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckEffectiveCatalogSource:
    """Unit tests for _check_effective_catalog_source covering all precedence rules."""

    # AC-FUNC-001: CLI flag wins when BOTH CLI and env var are set.
    def test_cli_flag_wins_over_env_var(self) -> None:
        """CLI flag takes precedence over KANON_CATALOG_SOURCE env var."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        args = _make_args(catalog_source=cli_value)
        env = {CATALOG_ENV_VAR: env_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message
        assert env_value not in finding.message

    # AC-FUNC-001: CLI flag wins when env var differs.
    def test_cli_flag_overrides_different_lockfile_value(self) -> None:
        """CLI flag takes precedence over a lockfile catalog source."""
        cli_value = "https://cli.example.com/repo.git@main"
        lock_value = "https://lock.example.com/repo.git@v1.0.0"
        args = _make_args(catalog_source=cli_value)
        lockfile = _make_lockfile_with_catalog(lock_value)
        env: dict[str, str] = {}

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message
        assert lock_value not in finding.message

    # AC-FUNC-002: env var wins when CLI is absent.
    def test_env_var_wins_when_cli_absent(self) -> None:
        """KANON_CATALOG_SOURCE env var is used when CLI flag is not set."""
        env_value = "https://env.example.com/repo.git@main"
        args = _make_args(catalog_source=None)
        env = {CATALOG_ENV_VAR: env_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert env_value in finding.message
        assert "(from KANON_CATALOG_SOURCE env var)" in finding.message

    # AC-FUNC-003: lockfile wins when no CLI flag and no env var.
    def test_lockfile_wins_when_no_cli_and_no_env(self) -> None:
        """Lockfile [catalog].source is used when CLI flag and env var are absent."""
        lock_value = "https://lock.example.com/repo.git@v1.0.0"
        args = _make_args(catalog_source=None)
        env: dict[str, str] = {}
        lockfile = _make_lockfile_with_catalog(lock_value)

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert lock_value in finding.message
        assert "(from .kanon.lock [catalog].source)" in finding.message

    # AC-FUNC-004: none configured when no CLI, no env, and no lockfile.
    def test_none_configured_when_no_source(self) -> None:
        """Returns 'none configured' message when no source is available."""
        args = _make_args(catalog_source=None)
        env: dict[str, str] = {}

        finding = _check_effective_catalog_source(args, env, None)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert "(none configured)" in finding.message
        assert "commands requiring" in finding.message

    # AC-FUNC-004 variant: no CLI, no env, lockfile present but catalog.source empty.
    def test_none_configured_when_lockfile_empty_catalog(self) -> None:
        """Returns 'none configured' when lockfile is present but catalog.source is empty."""
        args = _make_args(catalog_source=None)
        env: dict[str, str] = {}
        lockfile = _make_lockfile_empty_catalog()

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert "(none configured)" in finding.message

    # AC-FUNC-005: return type is always DoctorFinding.
    @pytest.mark.parametrize(
        "catalog_source,env,has_lockfile",
        [
            ("https://cli.example.com/repo.git@main", {}, False),
            (None, {CATALOG_ENV_VAR: "https://env.example.com/repo.git@main"}, False),
            (None, {}, True),
            (None, {}, False),
        ],
    )
    def test_always_returns_doctor_finding(
        self,
        catalog_source: str | None,
        env: dict[str, str],
        has_lockfile: bool,
    ) -> None:
        """_check_effective_catalog_source always returns a DoctorFinding instance."""
        args = _make_args(catalog_source=catalog_source)
        lockfile = _make_lockfile_with_catalog("https://lock.example.com/r.git@main") if has_lockfile else None

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"

    # AC-FUNC-006: provenance suffix present in all paths.
    @pytest.mark.parametrize(
        "catalog_source,env,has_lockfile,expected_suffix",
        [
            (
                "https://cli.example.com/repo.git@main",
                {CATALOG_ENV_VAR: "https://env.example.com/repo.git@main"},
                False,
                "(from --catalog-source CLI flag)",
            ),
            (
                None,
                {CATALOG_ENV_VAR: "https://env.example.com/repo.git@main"},
                False,
                "(from KANON_CATALOG_SOURCE env var)",
            ),
            (
                None,
                {},
                True,
                "(from .kanon.lock [catalog].source)",
            ),
            (
                None,
                {},
                False,
                "(none configured)",
            ),
        ],
    )
    def test_provenance_suffix_present_in_all_paths(
        self,
        catalog_source: str | None,
        env: dict[str, str],
        has_lockfile: bool,
        expected_suffix: str,
    ) -> None:
        """Provenance suffix is present in every output path (AC-FUNC-006)."""
        args = _make_args(catalog_source=catalog_source)
        lockfile = _make_lockfile_with_catalog("https://lock.example.com/r.git@main") if has_lockfile else None

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert expected_suffix in finding.message

    # AC-CYCLE-001: leaked env var scenario.
    def test_leaked_env_var_is_surfaced(self) -> None:
        """KANON_CATALOG_SOURCE leakage from a shell profile is detected.

        When a workspace has no CLI flag set and no lockfile but the operator's
        shell profile leaked KANON_CATALOG_SOURCE from an unrelated project, the
        provenance suffix names the env var so the operator sees the leakage.
        """
        leaked_value = "https://example.invalid/leaked.git@main"
        args = _make_args(catalog_source=None)
        env = {CATALOG_ENV_VAR: leaked_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert finding.kind == "info"
        assert leaked_value in finding.message
        assert "(from KANON_CATALOG_SOURCE env var)" in finding.message

    # Additional: CLI-only (no env, no lockfile).
    def test_cli_only_no_env_no_lockfile(self) -> None:
        """CLI flag is used when neither env var nor lockfile is present."""
        cli_value = "https://cli.example.com/repo.git@release"
        args = _make_args(catalog_source=cli_value)
        env: dict[str, str] = {}

        finding = _check_effective_catalog_source(args, env, None)

        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message

    # Additional: CLI wins over both env and lockfile.
    def test_cli_wins_over_env_and_lockfile(self) -> None:
        """CLI flag overrides env var AND lockfile simultaneously."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        lock_value = "https://lock.example.com/repo.git@v1.0.0"
        args = _make_args(catalog_source=cli_value)
        env = {CATALOG_ENV_VAR: env_value}
        lockfile = _make_lockfile_with_catalog(lock_value)

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message

    # AC-FUNC-001 edge case: CLI value equals env var value -- must still attribute to CLI.
    def test_cli_wins_when_cli_value_equals_env_value(self) -> None:
        """CLI flag is attributed to CLI even when its value matches KANON_CATALOG_SOURCE.

        This is the sentinel-based disambiguation edge case: without a sentinel
        the old comparison `cli_value != env_value` evaluated False and the
        provenance was incorrectly attributed to the env var.  With _UNSET as
        the argparse default, any non-sentinel value unambiguously means the
        user typed the flag.
        """
        shared_value = "https://shared.example.com/repo.git@main"
        # Both CLI flag and env var carry the same URL.
        args = _make_args(catalog_source=shared_value)
        env = {CATALOG_ENV_VAR: shared_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert shared_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message
        assert "(from KANON_CATALOG_SOURCE env var)" not in finding.message
