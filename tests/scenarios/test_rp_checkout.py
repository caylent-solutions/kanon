"""RP-checkout-01..02: `kanon repo checkout` branch-switching scenarios.

Automates §24 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPCheckout:
    """RP-checkout-01..02: branch switching via `kanon repo checkout`."""

    def test_rp_checkout_01_existing_branch(self, tmp_path: pathlib.Path) -> None:
        """RP-checkout-01: checkout succeeds after `repo start mybr --all` creates the branch.

        Per E2-F3-S2-T4, `kanon repo checkout` operates on repo-tracked topic
        branches created by `kanon repo start`.  Must use `repo start mybr --all`
        then `repo checkout mybr` (NOT `main`).
        """
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        start_result = run_kanon("repo", "start", "mybr", "--all", cwd=ws)
        assert start_result.returncode == 0, f"repo start mybr --all failed: {start_result.stderr!r}"

        result = run_kanon("repo", "checkout", "mybr", cwd=ws)

        assert result.returncode == 0, (
            f"repo checkout mybr exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_checkout_02_nonexistent_branch_errors(self, tmp_path: pathlib.Path) -> None:
        """RP-checkout-02: checkout of a nonexistent branch exits non-zero."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "checkout", "no-such-branch", "--all", cwd=ws)

        assert result.returncode != 0, (
            "repo checkout of nonexistent branch should have failed but exited 0\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "no-such-branch" in combined, f"Expected missing branch name in output: {combined!r}"
