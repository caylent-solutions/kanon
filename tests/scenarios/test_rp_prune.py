"""RP-prune-01..02: `kanon repo prune` maintenance scenarios.

Automates §26 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.fixture(scope="module")
def prune_ws(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced workspace for RP-prune-* tests."""
    base = tmp_path_factory.mktemp("rp_prune")
    manifest_bare = build_rp_ro_manifest(base / "fixtures")
    ws = base / "workspace"
    rp_ro_setup(ws, manifest_bare)
    return ws


@pytest.mark.scenario
class TestRPPrune:
    """RP-prune-01..02: stale object pruning via `kanon repo prune`."""

    def test_rp_prune_01_bare(self, prune_ws: pathlib.Path) -> None:
        """RP-prune-01: bare `kanon repo prune` exits 0."""
        result = run_kanon("repo", "prune", cwd=prune_ws)

        assert result.returncode == 0, (
            f"repo prune exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_prune_02_project_filtered(self, prune_ws: pathlib.Path) -> None:
        """RP-prune-02: project-filtered prune restricts to one project."""
        result = run_kanon("repo", "prune", "pkg-alpha", cwd=prune_ws)

        assert result.returncode == 0, (
            f"repo prune pkg-alpha exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
