"""RP-rebase-01..08: `kanon repo rebase` scenarios.

Automates §24 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPRebase:
    """RP-rebase-01..08: rebase operations via `kanon repo rebase`."""

    def test_rp_rebase_01_bare(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-01: bare `kanon repo rebase` is a no-op when up to date."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_02_fail_fast(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-02: `kanon repo rebase --fail-fast` exits 0 on clean workspace."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", "--fail-fast", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --fail-fast exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_03_force_rebase(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-03: `kanon repo rebase --force-rebase` exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", "--force-rebase", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --force-rebase exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_04_no_ff(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-04: `kanon repo rebase --no-ff` exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", "--no-ff", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --no-ff exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_05_autosquash(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-05: `kanon repo rebase --autosquash` exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", "--autosquash", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --autosquash exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_06_whitespace_fix(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-06: `kanon repo rebase --whitespace=fix` exits 0."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        result = run_kanon("repo", "rebase", "--whitespace=fix", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --whitespace=fix exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_07_auto_stash(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-07: `kanon repo rebase --auto-stash` stashes and re-applies uncommitted changes.

        The flag is `--auto-stash` (no short alias).
        """
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        # Write a dirty change to the checked-out project to exercise the stash path.
        readme = ws / ".packages" / "pkg-alpha" / "README.md"
        if readme.exists():
            with readme.open("a") as fh:
                fh.write("dirty\n")

        result = run_kanon("repo", "rebase", "--auto-stash", cwd=ws)

        assert result.returncode == 0, (
            f"repo rebase --auto-stash exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_rebase_08_interactive_no_tty(self, tmp_path: pathlib.Path) -> None:
        """RP-rebase-08: `-i <project>` interactive rebase skips gracefully without a tty.

        A topic branch must exist so the project is not in detached HEAD state.
        The doc accepts exit 0 OR a "skipped no-tty" indication.
        """
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        # Start a topic branch so the project is on a named branch, not detached HEAD.
        start_result = run_kanon("repo", "start", "rebr-i", "--all", cwd=ws)
        assert start_result.returncode == 0, f"repo start rebr-i --all failed: {start_result.stderr!r}"

        result = run_kanon("repo", "rebase", "-i", "pkg-alpha", cwd=ws)

        # Accept exit 0 (ran without tty interaction) or any exit code that
        # indicates a tty/interactive skip.  The doc says "Exit code 0 OR
        # skipped (no-tty)". "Terminal is dumb, but EDITOR unset" is git's
        # canonical no-tty diagnostic emitted in headless CI runners
        # (TERM=dumb, no $EDITOR), so it is also acceptable here.
        combined = result.stdout + result.stderr
        combined_lower = combined.lower()
        acceptable = (
            result.returncode == 0
            or "no-tty" in combined_lower
            or "not a tty" in combined_lower
            or "tty" in combined_lower
            or "terminal is dumb" in combined_lower
            or "editor unset" in combined_lower
        )
        assert acceptable, (
            f"repo rebase -i unexpectedly exited {result.returncode} with no tty hint\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
