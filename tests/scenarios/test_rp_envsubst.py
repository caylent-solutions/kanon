"""RP-envsubst-01..02: `kanon repo envsubst` manifest variable substitution scenarios.

Automates §26 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPEnvsubst:
    """RP-envsubst-01..02: variable substitution in XML manifests."""

    def test_rp_envsubst_01_inplace(self, tmp_path: pathlib.Path) -> None:
        """RP-envsubst-01: bare `kanon repo envsubst` exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "envsubst", cwd=ws)

        assert result.returncode == 0, (
            f"repo envsubst exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_envsubst_02_substitution_check(self, tmp_path: pathlib.Path) -> None:
        """RP-envsubst-02: `kanon repo envsubst` with MY_VAR set exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon(
            "repo",
            "envsubst",
            cwd=ws,
            extra_env={"MY_VAR": "substituted_value"},
        )

        assert result.returncode == 0, (
            f"repo envsubst with MY_VAR exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
