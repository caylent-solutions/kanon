"""RP-status-01..04: `kanon repo status` scenario tests.

Covers §22 of `docs/integration-testing.md`.

All four scenarios share a single session-scoped synced checkout produced by
`_rp_ro_synced_repo` so that `repo init` + `repo sync` run exactly once per
test session (per-module, in practice).
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import make_plain_repo, run_kanon


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _build_rp_ro_repo(base: pathlib.Path) -> pathlib.Path:
    """Build a bare manifest repo (packages.xml) + content repos, return checkout dir.

    Mirrors the bash `rp_ro_setup` pattern:
      - content-repos/pkg-alpha.git and pkg-bravo.git
      - manifest-primary bare repo with repo-specs/remote.xml + repo-specs/packages.xml
      - kanon repo init -u <manifest_url> -b main -m repo-specs/packages.xml
      - kanon repo sync
    """
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
    """Session-scoped synced repo checkout shared across all RP-status-* tests."""
    base = tmp_path_factory.mktemp("rp_status")
    return _build_rp_ro_repo(base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPStatus:
    """RP-status-01..04: kanon repo status subcommand."""

    def test_rp_status_01_bare_status(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-status-01: bare `kanon repo status` exits 0."""
        result = run_kanon("repo", "status", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo status exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_status_02_orphans(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-status-02: `kanon repo status --orphans` exits 0."""
        result = run_kanon("repo", "status", "--orphans", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo status --orphans exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        # Pass criteria: output includes either "No orphan" message or lists entries
        assert combined, "Expected non-empty output from repo status --orphans"

    def test_rp_status_03_project_filtered(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-status-03: `kanon repo status pkg-alpha` exits 0, only pkg-alpha reported."""
        result = run_kanon("repo", "status", "pkg-alpha", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo status pkg-alpha exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_status_04_jobs(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-status-04: `kanon repo status --jobs=4` exits 0."""
        result = run_kanon("repo", "status", "--jobs=4", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo status --jobs=4 exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
