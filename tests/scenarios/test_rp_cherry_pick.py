"""RP-cherry-pick-01..02: `kanon repo cherry-pick` scenarios.

Automates §25 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon, run_git


@pytest.mark.scenario
class TestRPCherryPick:
    """RP-cherry-pick-01..02: cherry-pick via `kanon repo cherry-pick`."""

    def test_rp_cherry_pick_01_happy_path(self, tmp_path: pathlib.Path) -> None:
        """RP-cherry-pick-01: cherry-pick a valid SHA exits 0.

        Per §25 of the doc, `cd` into the workspace is required because
        `kanon repo cherry-pick` runs `git rev-parse --verify` from the cwd;
        the cwd must be inside a git worktree.

        Setup: start a topic branch, add a commit to a secondary branch in the
        bare content repo, then cherry-pick that commit into the topic branch.
        """
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        pkg_alpha = ws / ".packages" / "pkg-alpha"
        if not pkg_alpha.exists():
            pytest.skip("pkg-alpha not checked out; cannot resolve SHA")

        # Start a topic branch so the project is on a named branch.
        start_result = run_kanon("repo", "start", "cp-topic", "--all", cwd=ws)
        assert start_result.returncode == 0, f"repo start cp-topic failed: {start_result.stderr!r}"

        # Add a new commit directly to the pkg-alpha worktree on a temporary
        # branch, then cherry-pick it back onto cp-topic.
        try:
            run_git(["checkout", "-b", "cp-source"], pkg_alpha)
            (pkg_alpha / "cherry.txt").write_text("cherry content\n")
            run_git(["add", "cherry.txt"], pkg_alpha)
            run_git(
                [
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "cherry commit",
                ],
                pkg_alpha,
            )
            rev_result = run_git(["rev-parse", "HEAD"], pkg_alpha)
            sha = rev_result.stdout.strip()
            # Switch back to the topic branch before cherry-picking.
            run_git(["checkout", "cp-topic"], pkg_alpha)
        except RuntimeError as exc:
            pytest.skip(f"Failed to prepare cherry-pick fixture: {exc}")

        if not sha:
            pytest.skip("Empty SHA from cp-source HEAD; skipping cherry-pick test")

        # `kanon repo cherry-pick` runs `git rev-parse --verify <sha>` from
        # the cwd; the cwd must be inside a git worktree.
        result = run_kanon("repo", "cherry-pick", sha, cwd=pkg_alpha)

        assert result.returncode == 0, (
            f"repo cherry-pick {sha} exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_cherry_pick_02_nonexistent_sha_errors(self, tmp_path: pathlib.Path) -> None:
        """RP-cherry-pick-02: cherry-pick of a nonexistent SHA exits non-zero."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        ws = tmp_path / "ws"
        rp_ro_setup(ws, manifest_bare)

        pkg_alpha = ws / ".packages" / "pkg-alpha"
        if not pkg_alpha.exists():
            pytest.skip("pkg-alpha not checked out")

        result = run_kanon(
            "repo",
            "cherry-pick",
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            cwd=pkg_alpha,
        )

        assert result.returncode != 0, (
            "repo cherry-pick with nonexistent SHA should have failed but exited 0\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
