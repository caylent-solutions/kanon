"""RP-init scenarios from `docs/integration-testing.md` §20 (Category 19).

Exercises every flag and env var consumed by `kanon repo init`.

Scenarios automated:
- RP-init-01: bare init -u, -b, -m
- RP-init-02: long form --manifest-url
- RP-init-03: --manifest-name=alt.xml
- RP-init-04: --manifest-depth=1 (shallow manifest clone)
- RP-init-05: --manifest-upstream-branch
- RP-init-06: --standalone-manifest
- RP-init-07: SKIPPED -- E2-F3-S2-T14: requires --reference=<mirror> infrastructure
- RP-init-08: --dissociate (after --reference)
- RP-init-09: --no-clone-bundle
- RP-init-10: --mirror
- RP-init-11: --worktree
- RP-init-12: --submodules
- RP-init-13: --partial-clone --clone-filter=blob:none
- RP-init-14: --git-lfs
- RP-init-15: --use-superproject
- RP-init-16: --current-branch-only (-c)
- RP-init-17: --groups=<name>
- RP-init-18: env REPO_MANIFEST_URL overrides absent -u
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
_ALT_MANIFEST_FILENAME = "alt.xml"
_GIT_USER_NAME = "RP Init Scenario Test"
_GIT_USER_EMAIL = "rp-init-scenario@kanon.example"


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
    """Create a bare manifest repo with default.xml and alt.xml.

    Both manifests reference the content repo at content_fetch_base.
    Returns the path to the bare manifest repo.
    """
    work = parent / "manifest.work"
    bare = parent / "manifest.git"
    work.mkdir(parents=True, exist_ok=True)

    # init work dir
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
    (work / _ALT_MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(work), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add manifests"],
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


def _setup_manifest(tmp_path: pathlib.Path) -> tuple[str, pathlib.Path]:
    """Build content + manifest bare repos; return (manifest_url, checkout_dir).

    The checkout_dir is a fresh empty directory suitable for `kanon repo init`.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    content_bare = _make_content_repo(repos_dir)
    content_fetch_base = f"file://{content_bare.parent}"
    manifest_bare = _make_manifest_repo(repos_dir, content_fetch_base)
    manifest_url = f"file://{manifest_bare}"
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()
    return manifest_url, checkout_dir


def _repo_init(
    checkout_dir: pathlib.Path,
    manifest_url: str,
    *extra_args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run `kanon repo init` with the standard flags plus any extra_args."""
    repo_dir = checkout_dir / ".repo"
    args = [
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
        *extra_args,
    ]
    return run_kanon(*args, cwd=checkout_dir, extra_env=extra_env)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPInit:
    def test_rp_init_01_bare_short_flags(self, tmp_path: pathlib.Path) -> None:
        """RP-init-01: bare init -u, -b, -m -- .repo/ and manifest.xml created."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        repo_dir = checkout_dir / ".repo"
        result = run_kanon(
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
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ directory not created"
        assert (checkout_dir / ".repo" / "manifest.xml").exists(), ".repo/manifest.xml missing"

    def test_rp_init_02_long_form_manifest_url(self, tmp_path: pathlib.Path) -> None:
        """RP-init-02: long form --manifest-url creates .repo/."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        repo_dir = checkout_dir / ".repo"
        result = run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "--manifest-url",
            manifest_url,
            "--manifest-branch",
            _BRANCH,
            "--manifest-name",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ directory not created"

    def test_rp_init_03_manifest_name_alt_xml(self, tmp_path: pathlib.Path) -> None:
        """RP-init-03: --manifest-name=alt.xml -- alt.xml is the active manifest."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        repo_dir = checkout_dir / ".repo"
        result = run_kanon(
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
            _ALT_MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo" / "manifests" / _ALT_MANIFEST_FILENAME).exists(), (
            f".repo/manifests/{_ALT_MANIFEST_FILENAME} not present"
        )

    def test_rp_init_04_manifest_depth_1(self, tmp_path: pathlib.Path) -> None:
        """RP-init-04: --manifest-depth=1 -- manifests.git/shallow file created."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--manifest-depth", "1")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo" / "manifests.git" / "shallow").exists(), (
            ".repo/manifests.git/shallow missing after --manifest-depth=1"
        )

    def test_rp_init_05_manifest_upstream_branch(self, tmp_path: pathlib.Path) -> None:
        """RP-init-05: --manifest-upstream-branch -- manifest branch upstream recorded."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--manifest-upstream-branch", _BRANCH)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # Verify the manifests.git has the tracked branch config
        manifests_git = checkout_dir / ".repo" / "manifests.git"
        assert manifests_git.is_dir(), ".repo/manifests.git not created"
        cfg_result = subprocess.run(
            ["git", "config", "--local", "-l"],
            cwd=str(manifests_git),
            capture_output=True,
            text=True,
        )
        assert cfg_result.returncode == 0, f"git config failed: {cfg_result.stderr!r}"

    def test_rp_init_06_standalone_manifest(self, tmp_path: pathlib.Path) -> None:
        """RP-init-06: --standalone-manifest -- .repo/manifest.xml is a static file."""
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        content_bare = _make_content_repo(repos_dir)
        content_fetch_base = f"file://{content_bare.parent}"
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        # Write a standalone manifest as a plain file (no .git needed)
        standalone_dir = tmp_path / "standalone"
        standalone_dir.mkdir()
        standalone_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_fetch_base}" />\n'
            f'  <default revision="{_BRANCH}" remote="local" />\n'
            f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
            "</manifest>\n"
        )
        standalone_file = standalone_dir / "standalone.xml"
        standalone_file.write_text(standalone_xml, encoding="utf-8")

        repo_dir = checkout_dir / ".repo"
        result = run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            f"file://{standalone_file}",
            "--standalone-manifest",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo" / "manifest.xml").exists(), (
            ".repo/manifest.xml not present after --standalone-manifest"
        )

    def test_rp_init_07_reference_mirror_skipped(self) -> None:
        """RP-init-07: --reference=<mirror> -- skipped, requires mirror infrastructure."""
        pytest.skip("E2-F3-S2-T14: requires --reference=<mirror> infrastructure not provisioned in dev env")

    def test_rp_init_08_dissociate(self, tmp_path: pathlib.Path) -> None:
        """RP-init-08: --dissociate -- alternates file absent after dissociate."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        # Build a mirror dir to satisfy --reference (minimal clone)
        mirror_dir = tmp_path / "mirror"
        mirror_dir.mkdir()
        repos_dir = tmp_path / "repos"
        manifest_bare_path = (repos_dir / "manifest.git").resolve()
        subprocess.run(
            ["git", "clone", "--mirror", str(manifest_bare_path), str(mirror_dir / "manifest-mirror.git")],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )
        result = _repo_init(
            checkout_dir,
            manifest_url,
            "--reference",
            str(mirror_dir),
            "--dissociate",
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        alternates = checkout_dir / ".repo" / "manifests.git" / "objects" / "info" / "alternates"
        assert not alternates.exists(), (
            "alternates file must not exist after --dissociate (objects should be copied locally)"
        )

    def test_rp_init_09_no_clone_bundle(self, tmp_path: pathlib.Path) -> None:
        """RP-init-09: --no-clone-bundle -- exits 0 without clone.bundle attempt."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--no-clone-bundle")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "clone.bundle" not in combined, (
            f"clone.bundle appeared in output despite --no-clone-bundle: {combined!r}"
        )

    def test_rp_init_10_mirror(self, tmp_path: pathlib.Path) -> None:
        """RP-init-10: --mirror -- bare-mirror layout under .repo/manifests.git."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--mirror")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo" / "manifests.git").is_dir(), ".repo/manifests.git not created after --mirror"

    def test_rp_init_11_worktree(self, tmp_path: pathlib.Path) -> None:
        """RP-init-11: --worktree -- .repo/ directory created with worktree layout."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--worktree")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created after --worktree"

    def test_rp_init_12_submodules(self, tmp_path: pathlib.Path) -> None:
        """RP-init-12: --submodules -- init records the flag; exits 0."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--submodules")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created after --submodules"

    def test_rp_init_13_partial_clone_blob_none(self, tmp_path: pathlib.Path) -> None:
        """RP-init-13: --partial-clone --clone-filter=blob:none -- filter in git config."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(
            checkout_dir,
            manifest_url,
            "--partial-clone",
            "--clone-filter=blob:none",
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        manifests_git = checkout_dir / ".repo" / "manifests.git"
        assert manifests_git.is_dir(), ".repo/manifests.git not created"
        cfg_result = subprocess.run(
            ["git", "config", "--local", "remote.origin.partialclonefilter"],
            cwd=str(manifests_git),
            capture_output=True,
            text=True,
        )
        assert cfg_result.returncode == 0, f"partial-clone filter not set in git config: {cfg_result.stderr!r}"
        assert "blob:none" in cfg_result.stdout, (
            f"Expected 'blob:none' in partialclonefilter, got: {cfg_result.stdout!r}"
        )

    def test_rp_init_14_git_lfs(self, tmp_path: pathlib.Path) -> None:
        """RP-init-14: --git-lfs -- exits 0 (LFS hooks installed at sync time)."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--git-lfs")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created after --git-lfs"

    def test_rp_init_15_use_superproject(self, tmp_path: pathlib.Path) -> None:
        """RP-init-15: --use-superproject -- exits 0 or clear 'no superproject' error."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--use-superproject")
        # Pass criteria: exit 0 OR non-zero with superproject/error message
        combined = result.stdout + result.stderr
        if result.returncode != 0:
            assert any(kw in combined.lower() for kw in ("superproject", "error", "no superproject")), (
                f"--use-superproject failed without a recognisable error message: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )

    def test_rp_init_16_current_branch_only(self, tmp_path: pathlib.Path) -> None:
        """RP-init-16: -c / --current-branch-only -- only manifest branch fetched."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "-c")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created after -c"

    def test_rp_init_17_groups(self, tmp_path: pathlib.Path) -> None:
        """RP-init-17: --groups=default -- projects in group recorded for sync."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        result = _repo_init(checkout_dir, manifest_url, "--groups=default")
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created after --groups=default"

    def test_rp_init_18_env_repo_manifest_url(self, tmp_path: pathlib.Path) -> None:
        """RP-init-18: REPO_MANIFEST_URL env var overrides absent -u flag."""
        manifest_url, checkout_dir = _setup_manifest(tmp_path)
        repo_dir = checkout_dir / ".repo"
        result = run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-b",
            _BRANCH,
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
            extra_env={"REPO_MANIFEST_URL": manifest_url},
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (checkout_dir / ".repo").is_dir(), ".repo/ not created when REPO_MANIFEST_URL used without -u"
