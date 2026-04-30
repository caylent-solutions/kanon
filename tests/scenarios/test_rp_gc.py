"""RP-gc-01..04: `kanon repo gc` maintenance scenarios.

Automates §26 of `docs/integration-testing.md`.

Valid flags: `-n`/`--dry-run`, `-y`/`--yes`, `--repack`.
Flags `--aggressive`, `-a`/`--all`, and `--repack-full-clone` do NOT exist.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.fixture(scope="module")
def gc_ws(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced workspace for RP-gc-* tests."""
    base = tmp_path_factory.mktemp("rp_gc")
    manifest_bare = build_rp_ro_manifest(base / "fixtures")
    ws = base / "workspace"
    rp_ro_setup(ws, manifest_bare)
    return ws


@pytest.mark.scenario
class TestRPGC:
    """RP-gc-01..04: git garbage collection via `kanon repo gc`."""

    def test_rp_gc_01_bare(self, gc_ws: pathlib.Path) -> None:
        """RP-gc-01: bare `kanon repo gc` exits 0."""
        result = run_kanon("repo", "gc", cwd=gc_ws)

        assert result.returncode == 0, (
            f"repo gc exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_gc_02_dry_run(self, gc_ws: pathlib.Path) -> None:
        """RP-gc-02: `--dry-run` flag accepted; no actual gc work performed."""
        result = run_kanon("repo", "gc", "--dry-run", cwd=gc_ws)

        assert result.returncode == 0, (
            f"repo gc --dry-run exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_gc_03_yes_auto_confirm(self, gc_ws: pathlib.Path) -> None:
        """RP-gc-03: `--yes` / `-y` auto-confirm flag accepted; combined with --dry-run."""
        result = run_kanon("repo", "gc", "--yes", "--dry-run", cwd=gc_ws)

        assert result.returncode == 0, (
            f"repo gc --yes --dry-run exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_gc_04_repack(self, gc_ws: pathlib.Path) -> None:
        """RP-gc-04: `--repack` flag accepted; combined with --dry-run for safety."""
        result = run_kanon("repo", "gc", "--repack", "--dry-run", cwd=gc_ws)

        assert result.returncode == 0, (
            f"repo gc --repack --dry-run exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
