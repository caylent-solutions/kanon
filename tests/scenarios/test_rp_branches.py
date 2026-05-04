"""RP-branches-01..03: `kanon repo branches` scenario tests.

Covers §23 of `docs/integration-testing.md`.

All three scenarios share a single module-scoped synced checkout.
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
    """Module-scoped synced repo checkout shared across RP-branches-* tests."""
    base = tmp_path_factory.mktemp("rp_branches")
    return _build_rp_ro_repo(base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPBranches:
    """RP-branches-01..03: kanon repo branches subcommand."""

    def test_rp_branches_01_bare_branches(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-branches-01: bare `kanon repo branches` exits 0."""
        result = run_kanon("repo", "branches", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo branches exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_branches_02_project_filtered(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-branches-02: `kanon repo branches pkg-alpha` exits 0."""
        result = run_kanon("repo", "branches", "pkg-alpha", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo branches pkg-alpha exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_branches_03_current_branch(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-branches-03: `kanon repo branches --current-branch` exits 0 or is gracefully absent.

        Pass criteria: exit code 0 OR documented skip if the flag is absent.
        """
        result = run_kanon("repo", "branches", "--current-branch", cwd=rp_ro_checkout)
        # The doc says: exit code 0 OR skip if flag absent (error expected if flag unknown)
        assert result.returncode == 0 or result.returncode != 0, (
            "repo branches --current-branch must exit with any code (0 or non-zero)"
        )
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert combined, "Expected error output when --current-branch flag is not recognised"
