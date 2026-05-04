"""RP-start-01..04: `kanon repo start` branch creation scenarios.

Automates §24 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPStart:
    """RP-start-01..04: branch creation via `kanon repo start`."""

    def test_rp_start_01_all(self, tmp_path: pathlib.Path) -> None:
        """RP-start-01: `kanon repo start <branch> --all` creates branch in every project."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "start", "tmp-1", "--all", cwd=ws)

        assert result.returncode == 0, (
            f"repo start --all exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_start_02_single_project(self, tmp_path: pathlib.Path) -> None:
        """RP-start-02: `kanon repo start <branch> <project>` targets one project."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "start", "tmp-2", "pkg-alpha", cwd=ws)

        assert result.returncode == 0, (
            f"repo start <project> exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_start_03_rev(self, tmp_path: pathlib.Path) -> None:
        """RP-start-03: `kanon repo start <branch> --all --rev=HEAD` uses HEAD revision."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "start", "tmp-3", "--all", "--rev=HEAD", cwd=ws)

        assert result.returncode == 0, (
            f"repo start --rev=HEAD exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_start_04_head(self, tmp_path: pathlib.Path) -> None:
        """RP-start-04: `kanon repo start <branch> --all --head` starts from HEAD."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "start", "tmp-4", "--all", "--head", cwd=ws)

        assert result.returncode == 0, (
            f"repo start --head exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
