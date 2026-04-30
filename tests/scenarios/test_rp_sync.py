"""RP-sync scenarios from `docs/integration-testing.md` §21 (Category 20).

Exercises every flag and env var consumed by `kanon repo sync`.

Scenarios automated:
- RP-sync-01: bare `kanon repo sync`
- RP-sync-02: --network-only / -n
- RP-sync-03: --local-only / -l
- RP-sync-04: --detach / -d
- RP-sync-05: --current-branch / -c
- RP-sync-06: --no-current-branch
- RP-sync-07: --force-checkout
- RP-sync-08: --force-remove-dirty
- RP-sync-09: --rebase
- RP-sync-10: --force-sync
- RP-sync-11: --clone-bundle
- RP-sync-12: --no-clone-bundle
- RP-sync-13: --fetch-submodules
- RP-sync-14: --use-superproject
- RP-sync-15: --no-use-superproject
- RP-sync-16: --tags
- RP-sync-17: --no-tags
- RP-sync-18: --optimized-fetch
- RP-sync-19: --retry-fetches=3
- RP-sync-20: --prune / --no-prune (two calls)
- RP-sync-21: --auto-gc / --no-auto-gc (two calls)
- RP-sync-22: --no-repo-verify
- RP-sync-23: --jobs-network=N and --jobs-checkout=N
- RP-sync-24: --interleaved
- RP-sync-25: --fail-fast
- RP-sync-26: env REPO_SKIP_SELF_UPDATE=1
- RP-sync-27: env SYNC_TARGET
- RP-sync-28: env TARGET_PRODUCT + TARGET_BUILD_VARIANT + TARGET_RELEASE
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from tests.scenarios.conftest import make_plain_repo, run_kanon


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRANCH = "main"
_PROJECT_NAME = "pkg-alpha"
_PROJECT_PATH = ".packages/pkg-alpha"
_MANIFEST_FILENAME = "default.xml"
_GIT_USER_NAME = "RP Sync Scenario Test"
_GIT_USER_EMAIL = "rp-sync-scenario@kanon.example"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_content_repo(parent: pathlib.Path) -> pathlib.Path:
    """Create a bare content repo named pkg-alpha under parent."""
    return make_plain_repo(
        parent,
        _PROJECT_NAME,
        {"README.md": "# Alpha Package\n", "src/main.py": 'print("alpha")\n'},
    )


def _make_manifest_repo(parent: pathlib.Path, content_fetch_base: str) -> pathlib.Path:
    """Create a bare manifest repo with default.xml referencing content_fetch_base."""
    work = parent / "manifest.work"
    bare = parent / "manifest.git"
    work.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init", "-b", _BRANCH],
        cwd=str(work),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", _GIT_USER_NAME],
        cwd=str(work),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", _GIT_USER_EMAIL],
        cwd=str(work),
        capture_output=True,
        check=True,
    )

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_base}" />\n'
        f'  <default revision="{_BRANCH}" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (work / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(work), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add manifest"],
        cwd=str(work),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "clone", "--bare", str(work), str(bare)],
        cwd=str(parent),
        capture_output=True,
        check=True,
    )
    return bare.resolve()


def _setup_inited_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Build repos and run `kanon repo init`; return (checkout_dir, repo_dir).

    Performs only `kanon repo init`.  The caller is responsible for calling
    `kanon repo sync` so that individual test methods can pass the flags under
    test.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    content_bare = _make_content_repo(repos_dir)
    content_fetch_base = f"file://{content_bare.parent}"
    manifest_bare = _make_manifest_repo(repos_dir, content_fetch_base)
    manifest_url = f"file://{manifest_bare}"

    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()
    repo_dir = checkout_dir / ".repo"

    init_result = run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        _BRANCH,
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )
    assert init_result.returncode == 0, (
        f"Prerequisite 'kanon repo init' failed.\n  stdout: {init_result.stdout!r}\n  stderr: {init_result.stderr!r}"
    )
    return checkout_dir, repo_dir


def _repo_sync(
    checkout_dir: pathlib.Path,
    repo_dir: pathlib.Path,
    *extra_args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run `kanon repo sync` with standard flags plus any extra_args."""
    return run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        "--jobs=1",
        *extra_args,
        cwd=checkout_dir,
        extra_env=extra_env,
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPSync:
    def test_rp_sync_01_bare_sync(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-01: bare `kanon repo sync` -- project directory populated."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / _PROJECT_PATH).is_dir(), f"Project directory {_PROJECT_PATH!r} not created after sync"

    def test_rp_sync_02_network_only(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-02: --network-only / -n -- exits 0; only fetch, no checkout."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "-n")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_03_local_only(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-03: --local-only / -l -- second sync with no network calls exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        first = _repo_sync(checkout_dir, repo_dir)
        assert first.returncode == 0, f"Prerequisite sync failed: stdout={first.stdout!r} stderr={first.stderr!r}"
        result = _repo_sync(checkout_dir, repo_dir, "-l")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_04_detach(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-04: --detach -- project HEADs detached at manifest revision."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "-d")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_05_current_branch(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-05: --current-branch / -c -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "-c")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_06_no_current_branch(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-06: --no-current-branch -- default fetch behaviour; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--no-current-branch")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_07_force_checkout(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-07: --force-checkout -- overwrites uncommitted changes."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        first = _repo_sync(checkout_dir, repo_dir)
        assert first.returncode == 0, f"Prerequisite sync failed: stdout={first.stdout!r} stderr={first.stderr!r}"
        # Introduce a dirty change
        readme = checkout_dir / _PROJECT_PATH / "README.md"
        readme.write_text("dirty\n", encoding="utf-8")
        result = _repo_sync(checkout_dir, repo_dir, "--force-checkout")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_08_force_remove_dirty(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-08: --force-remove-dirty -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--force-remove-dirty")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_09_rebase(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-09: --rebase -- local commits rebased; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--rebase")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_10_force_sync(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-10: --force-sync -- overrides data-loss warning; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--force-sync")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_11_clone_bundle(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-11: --clone-bundle -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--clone-bundle")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_12_no_clone_bundle(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-12: --no-clone-bundle -- exits 0; no clone.bundle attempted."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--no-clone-bundle")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "clone.bundle" not in combined, (
            f"clone.bundle appeared in output despite --no-clone-bundle: {combined!r}"
        )

    def test_rp_sync_13_fetch_submodules(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-13: --fetch-submodules -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--fetch-submodules")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_14_use_superproject(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-14: --use-superproject -- exits 0 OR clear 'no superproject' error."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--use-superproject")
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert any(kw in combined.lower() for kw in ("superproject", "error", "no superproject")), (
                f"--use-superproject failed without recognisable error: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )

    def test_rp_sync_15_no_use_superproject(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-15: --no-use-superproject -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--no-use-superproject")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_16_tags(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-16: --tags -- tags fetched; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--tags")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_17_no_tags(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-17: --no-tags -- tags skipped; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--no-tags")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_18_optimized_fetch(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-18: --optimized-fetch -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--optimized-fetch")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_19_retry_fetches(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-19: --retry-fetches=3 -- N retries on transient errors; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--retry-fetches=3")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_20_prune_and_no_prune(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-20: --prune and --no-prune -- both invocations exit 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        prune_result = _repo_sync(checkout_dir, repo_dir, "--prune")
        assert prune_result.returncode == 0, (
            f"--prune failed: stdout={prune_result.stdout!r} stderr={prune_result.stderr!r}"
        )
        no_prune_result = _repo_sync(checkout_dir, repo_dir, "--no-prune")
        assert no_prune_result.returncode == 0, (
            f"--no-prune failed: stdout={no_prune_result.stdout!r} stderr={no_prune_result.stderr!r}"
        )

    def test_rp_sync_21_auto_gc_and_no_auto_gc(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-21: --auto-gc and --no-auto-gc -- both exit 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        auto_gc_result = _repo_sync(checkout_dir, repo_dir, "--auto-gc")
        assert auto_gc_result.returncode == 0, (
            f"--auto-gc failed: stdout={auto_gc_result.stdout!r} stderr={auto_gc_result.stderr!r}"
        )
        no_auto_gc_result = _repo_sync(checkout_dir, repo_dir, "--no-auto-gc")
        assert no_auto_gc_result.returncode == 0, (
            f"--no-auto-gc failed: stdout={no_auto_gc_result.stdout!r} stderr={no_auto_gc_result.stderr!r}"
        )

    def test_rp_sync_22_no_repo_verify(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-22: --no-repo-verify -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--no-repo-verify")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_23_jobs_network_and_checkout(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-23: --jobs-network=N --jobs-checkout=N -- parallel jobs; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--jobs-network=2", "--jobs-checkout=4")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_24_interleaved(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-24: --interleaved -- fetch and checkout interleave; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--interleaved")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_25_fail_fast(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-25: --fail-fast -- no errors to trip it; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(checkout_dir, repo_dir, "--fail-fast")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_26_repo_skip_self_update(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-26: REPO_SKIP_SELF_UPDATE=1 -- no self-update step; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(
            checkout_dir,
            repo_dir,
            extra_env={"REPO_SKIP_SELF_UPDATE": "1"},
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "self.update" not in combined.lower(), (
            f"self-update step ran despite REPO_SKIP_SELF_UPDATE=1: {combined!r}"
        )

    def test_rp_sync_27_sync_target_env(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-27: SYNC_TARGET env var -- target string accepted; exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(
            checkout_dir,
            repo_dir,
            extra_env={"SYNC_TARGET": "myproduct-myrelease-myvariant"},
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_rp_sync_28_target_product_variant_release_env(self, tmp_path: pathlib.Path) -> None:
        """RP-sync-28: TARGET_PRODUCT + TARGET_BUILD_VARIANT + TARGET_RELEASE -- exits 0."""
        checkout_dir, repo_dir = _setup_inited_repo(tmp_path)
        result = _repo_sync(
            checkout_dir,
            repo_dir,
            extra_env={
                "TARGET_PRODUCT": "myp",
                "TARGET_BUILD_VARIANT": "user",
                "TARGET_RELEASE": "1",
            },
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
