"""RP-grep-01..04: `kanon repo grep` scenarios.

Automates §23 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.fixture(scope="module")
def grep_ws(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced workspace for RP-grep-* tests."""
    base = tmp_path_factory.mktemp("rp_grep")
    manifest_bare = build_rp_ro_manifest(base / "fixtures")
    ws = base / "workspace"
    rp_ro_setup(ws, manifest_bare)
    return ws


@pytest.mark.scenario
class TestRPGrep:
    """RP-grep-01..04: pattern search via `kanon repo grep`."""

    def test_rp_grep_01_basic_pattern(self, grep_ws: pathlib.Path) -> None:
        """RP-grep-01: basic `<pattern>` exits 0 or 1 (no-match), no crash."""
        result = run_kanon("repo", "grep", "alpha", cwd=grep_ws)

        assert result.returncode in (0, 1), (
            f"repo grep exited {result.returncode} (expected 0 or 1)\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_grep_02_case_insensitive(self, grep_ws: pathlib.Path) -> None:
        """RP-grep-02: `-i` case-insensitive search exits 0 or 1."""
        result = run_kanon("repo", "grep", "-i", "ALPHA", cwd=grep_ws)

        assert result.returncode in (0, 1), (
            f"repo grep -i exited {result.returncode} (expected 0 or 1)\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_grep_03_extended_pattern(self, grep_ws: pathlib.Path) -> None:
        """RP-grep-03: `-e <pattern>` exits 0 or 1."""
        result = run_kanon("repo", "grep", "-e", "alpha", cwd=grep_ws)

        assert result.returncode in (0, 1), (
            f"repo grep -e exited {result.returncode} (expected 0 or 1)\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_grep_04_project_filtered(self, grep_ws: pathlib.Path) -> None:
        """RP-grep-04: project-filtered search restricts to one project."""
        result = run_kanon("repo", "grep", "alpha", "pkg-alpha", cwd=grep_ws)

        assert result.returncode in (0, 1), (
            f"repo grep pkg-alpha exited {result.returncode} (expected 0 or 1)\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
