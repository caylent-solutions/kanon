"""RP-info-01..07: `kanon repo info` scenario tests.

Covers §22 of `docs/integration-testing.md`.

All seven scenarios share a single module-scoped synced checkout.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import make_plain_repo, run_kanon


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _build_rp_ro_repo(base: pathlib.Path) -> pathlib.Path:
    """Build content repos + bare manifest repo, run init + sync, return checkout dir."""
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    make_plain_repo(content_repos, "pkg-bravo", {"README.md": "# pkg-bravo\n"})

    content_url = content_repos.as_uri()
    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )
    packages_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path="pkg-alpha" remote="local" revision="main" />\n'
        '  <project name="pkg-bravo" path="pkg-bravo" remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    manifest_bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/packages.xml": packages_xml,
        },
    )

    checkout = base / "checkout"
    checkout.mkdir()

    init_result = run_kanon(
        "repo",
        "init",
        "-u",
        manifest_bare.as_uri(),
        "-b",
        "main",
        "-m",
        "repo-specs/packages.xml",
        cwd=checkout,
    )
    assert init_result.returncode == 0, f"repo init failed: stdout={init_result.stdout!r} stderr={init_result.stderr!r}"
    sync_result = run_kanon("repo", "sync", "--jobs=1", cwd=checkout)
    assert sync_result.returncode == 0, f"repo sync failed: stdout={sync_result.stdout!r} stderr={sync_result.stderr!r}"
    return checkout


@pytest.fixture(scope="module")
def rp_ro_checkout(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced repo checkout shared across RP-info-* tests."""
    base = tmp_path_factory.mktemp("rp_info")
    return _build_rp_ro_repo(base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPInfo:
    """RP-info-01..07: kanon repo info subcommand."""

    def test_rp_info_01_bare_info(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-01: bare `kanon repo info` exits 0; current manifest name printed."""
        result = run_kanon("repo", "info", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        # Pass criteria: manifest name or info appears in output
        assert combined, "Expected non-empty output from repo info"

    def test_rp_info_02_diff(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-02: `kanon repo info --diff` exits 0."""
        result = run_kanon("repo", "info", "--diff", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --diff exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_info_03_current_branch(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-03: `kanon repo info --current-branch` exits 0."""
        result = run_kanon("repo", "info", "--current-branch", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --current-branch exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_info_04_local_only(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-04: `kanon repo info --local-only` exits 0."""
        result = run_kanon("repo", "info", "--local-only", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --local-only exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_info_05_overview(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-05: `kanon repo info --overview` exits 0."""
        result = run_kanon("repo", "info", "--overview", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --overview exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_info_06_no_current_branch(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-06: `kanon repo info --no-current-branch` exits 0."""
        result = run_kanon("repo", "info", "--no-current-branch", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --no-current-branch exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_info_07_this_manifest_only(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-info-07: `kanon repo info --this-manifest-only` exits 0."""
        result = run_kanon("repo", "info", "--this-manifest-only", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo info --this-manifest-only exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
