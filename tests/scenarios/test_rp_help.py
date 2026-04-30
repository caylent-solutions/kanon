"""RP-help-01..03: `kanon repo help` scenario tests.

Covers §26 of `docs/integration-testing.md`.

Help subcommand tests do not require a synced checkout -- they run against
the installed CLI directly.
"""

from __future__ import annotations

import pytest

from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPHelp:
    """RP-help-01..03: kanon repo help subcommand."""

    def test_rp_help_01_bare_help(self) -> None:
        """RP-help-01: bare `kanon repo help` exits 0; usage printed."""
        result = run_kanon("repo", "help")
        assert result.returncode == 0, (
            f"repo help exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "usage" in combined, f"Expected 'usage' in help output: {combined[:200]!r}"

    def test_rp_help_02_all(self) -> None:
        """RP-help-02: `kanon repo help --all` exits 0; usage printed."""
        result = run_kanon("repo", "help", "--all")
        assert result.returncode == 0, (
            f"repo help --all exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "usage" in combined, f"Expected 'usage' in help --all output: {combined[:200]!r}"

    def test_rp_help_03_help_all(self) -> None:
        """RP-help-03: `kanon repo help --help-all` exits 0; help for all subcommands shown."""
        result = run_kanon("repo", "help", "--help-all")
        assert result.returncode == 0, (
            f"repo help --help-all exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined, "Expected non-empty output from repo help --help-all"
