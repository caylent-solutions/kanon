"""RP-abandon-01..03: `kanon repo abandon` branch deletion scenarios.

Automates §24 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPAbandon:
    """RP-abandon-01..03: branch deletion via `kanon repo abandon`."""

    def test_rp_abandon_01_all(self, tmp_path: pathlib.Path) -> None:
        """RP-abandon-01: `kanon repo abandon <branch>` removes branch from every project.

        The `--all` flag and the positional `<branch>` argument are mutually
        exclusive; to remove a named branch from every project, pass only the
        branch name.
        """
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        start_result = run_kanon("repo", "start", "tmp-a", "--all", cwd=ws)
        assert start_result.returncode == 0, f"repo start tmp-a --all failed: {start_result.stderr!r}"

        result = run_kanon("repo", "abandon", "tmp-a", cwd=ws)

        assert result.returncode == 0, (
            f"repo abandon tmp-a exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_abandon_02_single_project(self, tmp_path: pathlib.Path) -> None:
        """RP-abandon-02: `kanon repo abandon <branch> <project>` removes branch from one project."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        start_result = run_kanon("repo", "start", "tmp-b", "pkg-alpha", cwd=ws)
        assert start_result.returncode == 0, f"repo start tmp-b pkg-alpha failed: {start_result.stderr!r}"

        result = run_kanon("repo", "abandon", "tmp-b", "pkg-alpha", cwd=ws)

        assert result.returncode == 0, (
            f"repo abandon tmp-b pkg-alpha exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_abandon_03_all_branches(self, tmp_path: pathlib.Path) -> None:
        """RP-abandon-03: `kanon repo abandon --all` deletes all topic branches."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        start_result = run_kanon("repo", "start", "tmp-c", "--all", cwd=ws)
        assert start_result.returncode == 0, f"repo start tmp-c --all failed: {start_result.stderr!r}"

        result = run_kanon("repo", "abandon", "--all", cwd=ws)

        assert result.returncode == 0, (
            f"repo abandon --all exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
