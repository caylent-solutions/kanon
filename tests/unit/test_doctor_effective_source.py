"""Unit tests for kanon_cli.commands.doctor._check_effective_catalog_source.

Covers all precedence permutations for catalog source resolution (schema v4):
  1. CLI flag (--catalog-source) takes highest precedence.
  2. KANON_CATALOG_SOURCES env var wins when CLI flag is absent.
  3. When neither CLI flag nor env var is set, a "none configured" message is
     returned.

Schema v4 (FR-7) removed the lockfile [catalog] block, so the lockfile no longer
participates in catalog-source provenance.  The function still accepts a
``lockfile`` parameter for call-site symmetry, but it is unused: a lockfile
present with no CLI flag and no env var yields "(none configured)".

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
from kanon_cli.constants import CATALOG_SOURCES_ENV_VAR
from kanon_cli.core.lockfile import CURRENT_SCHEMA_VERSION, Lockfile, SourceEntry


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


def _make_lockfile() -> Lockfile:
    """Return a minimal valid schema-v4 Lockfile with a single source.

    The v4 lock carries no [catalog] block, so this lockfile contributes nothing
    to the catalog-source precedence chain. It exists to verify that an
    otherwise-valid lockfile present in the workspace does NOT supply a catalog
    source (the provenance must fall through to "(none configured)").
    """
    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        sources=[
            SourceEntry(
                alias="src",
                name="src",
                url="https://example.com/org/catalog.git",
                ref_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha="a" * 40,
                path="repo-specs/meta.xml",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Tests: _check_effective_catalog_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckEffectiveCatalogSource:
    """Unit tests for _check_effective_catalog_source covering all precedence rules."""

    # AC-FUNC-001: CLI flag wins when BOTH CLI and env var are set.
    def test_cli_flag_wins_over_env_var(self) -> None:
        """CLI flag takes precedence over KANON_CATALOG_SOURCES env var."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        args = _make_args(catalog_source=cli_value)
        env = {CATALOG_SOURCES_ENV_VAR: env_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message
        assert env_value not in finding.message

    # AC-FUNC-001: CLI flag wins even when a v4 lockfile is present.
    def test_cli_flag_used_when_lockfile_present(self) -> None:
        """CLI flag is reported even when a v4 lockfile (which carries no catalog) is present."""
        cli_value = "https://cli.example.com/repo.git@main"
        args = _make_args(catalog_source=cli_value)
        lockfile = _make_lockfile()
        env: dict[str, str] = {}

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message

    # AC-FUNC-002: env var wins when CLI is absent.
    def test_env_var_wins_when_cli_absent(self) -> None:
        """KANON_CATALOG_SOURCES env var is used when CLI flag is not set."""
        env_value = "https://env.example.com/repo.git@main"
        args = _make_args(catalog_source=None)
        env = {CATALOG_SOURCES_ENV_VAR: env_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert env_value in finding.message
        assert "(from KANON_CATALOG_SOURCES env var)" in finding.message

    # FR-7: the v4 lockfile no longer supplies a catalog source.
    def test_lockfile_present_no_cli_no_env_yields_none_configured(self) -> None:
        """A v4 lockfile present with no CLI flag and no env var yields "(none configured)".

        Schema v4 removed the lockfile [catalog] block, so a lockfile that exists
        in the workspace contributes nothing to the catalog-source provenance: the
        chain falls through to "(none configured)".
        """
        args = _make_args(catalog_source=None)
        env: dict[str, str] = {}
        lockfile = _make_lockfile()

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"
        assert "(none configured)" in finding.message
        assert "commands requiring" in finding.message

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

    # AC-FUNC-005: return type is always DoctorFinding.
    @pytest.mark.parametrize(
        "catalog_source,env,has_lockfile",
        [
            ("https://cli.example.com/repo.git@main", {}, False),
            (None, {CATALOG_SOURCES_ENV_VAR: "https://env.example.com/repo.git@main"}, False),
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
        lockfile = _make_lockfile() if has_lockfile else None

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert isinstance(finding, DoctorFinding)
        assert finding.kind == "info"

    # AC-FUNC-006: provenance suffix present in all paths.
    @pytest.mark.parametrize(
        "catalog_source,env,has_lockfile,expected_suffix",
        [
            (
                "https://cli.example.com/repo.git@main",
                {CATALOG_SOURCES_ENV_VAR: "https://env.example.com/repo.git@main"},
                False,
                "(from --catalog-source CLI flag)",
            ),
            (
                None,
                {CATALOG_SOURCES_ENV_VAR: "https://env.example.com/repo.git@main"},
                False,
                "(from KANON_CATALOG_SOURCES env var)",
            ),
            (
                None,
                {},
                True,
                "(none configured)",
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
        lockfile = _make_lockfile() if has_lockfile else None

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert expected_suffix in finding.message

    # AC-CYCLE-001: leaked env var scenario.
    def test_leaked_env_var_is_surfaced(self) -> None:
        """KANON_CATALOG_SOURCES leakage from a shell profile is detected.

        When a workspace has no CLI flag set and no lockfile but the operator's
        shell profile leaked KANON_CATALOG_SOURCES from an unrelated project, the
        provenance suffix names the env var so the operator sees the leakage.
        """
        leaked_value = "https://example.invalid/leaked.git@main"
        args = _make_args(catalog_source=None)
        env = {CATALOG_SOURCES_ENV_VAR: leaked_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert finding.kind == "info"
        assert leaked_value in finding.message
        assert "(from KANON_CATALOG_SOURCES env var)" in finding.message

    # Additional: CLI-only (no env, no lockfile).
    def test_cli_only_no_env_no_lockfile(self) -> None:
        """CLI flag is used when neither env var nor lockfile is present."""
        cli_value = "https://cli.example.com/repo.git@release"
        args = _make_args(catalog_source=cli_value)
        env: dict[str, str] = {}

        finding = _check_effective_catalog_source(args, env, None)

        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message

    # Additional: CLI wins over both env and a present lockfile.
    def test_cli_wins_over_env_and_lockfile(self) -> None:
        """CLI flag overrides env var AND is reported even when a lockfile is present."""
        cli_value = "https://cli.example.com/repo.git@main"
        env_value = "https://env.example.com/repo.git@main"
        args = _make_args(catalog_source=cli_value)
        env = {CATALOG_SOURCES_ENV_VAR: env_value}
        lockfile = _make_lockfile()

        finding = _check_effective_catalog_source(args, env, lockfile)

        assert cli_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message

    # AC-FUNC-001 edge case: CLI value equals env var value -- must still attribute to CLI.
    def test_cli_wins_when_cli_value_equals_env_value(self) -> None:
        """CLI flag is attributed to CLI even when its value matches KANON_CATALOG_SOURCES.

        This is the sentinel-based disambiguation edge case: without a sentinel
        the old comparison `cli_value != env_value` evaluated False and the
        provenance was incorrectly attributed to the env var.  With _UNSET as
        the argparse default, any non-sentinel value unambiguously means the
        user typed the flag.
        """
        shared_value = "https://shared.example.com/repo.git@main"
        # Both CLI flag and env var carry the same URL.
        args = _make_args(catalog_source=shared_value)
        env = {CATALOG_SOURCES_ENV_VAR: shared_value}

        finding = _check_effective_catalog_source(args, env, None)

        assert shared_value in finding.message
        assert "(from --catalog-source CLI flag)" in finding.message
        assert "(from KANON_CATALOG_SOURCES env var)" not in finding.message
