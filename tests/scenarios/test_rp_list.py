"""RP-list-01..10: `kanon repo list` scenario tests.

Covers §23 of `docs/integration-testing.md`.

All ten scenarios share a single module-scoped synced checkout.
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
    """Module-scoped synced repo checkout shared across RP-list-* tests."""
    base = tmp_path_factory.mktemp("rp_list")
    return _build_rp_ro_repo(base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPList:
    """RP-list-01..10: kanon repo list subcommand."""

    def test_rp_list_01_bare_list(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-01: bare `kanon repo list` exits 0; project paths printed."""
        result = run_kanon("repo", "list", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip(), "Expected non-empty output from repo list"

    def test_rp_list_02_regex_long(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-02: `kanon repo list --regex pkg-` exits 0; only matching projects."""
        result = run_kanon("repo", "list", "--regex", "pkg-", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --regex exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "pkg-alpha" in result.stdout or "pkg-bravo" in result.stdout, (
            f"Expected a pkg- project in output: {result.stdout!r}"
        )

    def test_rp_list_03_regex_short(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-03: `kanon repo list -r '^pkg-'` exits 0."""
        result = run_kanon("repo", "list", "-r", "^pkg-", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list -r exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_list_04_groups(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-04: `kanon repo list --groups=default` exits 0."""
        result = run_kanon("repo", "list", "--groups=default", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --groups=default exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_list_05_all_manifests(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-05: `kanon repo list --all-manifests` exits 0."""
        result = run_kanon("repo", "list", "--all-manifests", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --all-manifests exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_list_06_name_only(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-06: `kanon repo list -n` exits 0; only repo names printed."""
        result = run_kanon("repo", "list", "-n", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list -n exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        first_line = result.stdout.splitlines()[0] if result.stdout.strip() else ""
        assert first_line, "Expected at least one name in repo list -n output"
        # Name-only output should not contain path separators (just the project name)
        assert " : " not in first_line, f"Name-only output should not include path info: {first_line!r}"

    def test_rp_list_07_path_only(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-07: `kanon repo list -p` exits 0; only paths printed."""
        result = run_kanon("repo", "list", "-p", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list -p exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip(), "Expected non-empty output from repo list -p"

    def test_rp_list_08_fullpath(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-08: `kanon repo list --fullpath` exits 0; absolute paths printed."""
        result = run_kanon("repo", "list", "--fullpath", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --fullpath exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        first_line = result.stdout.splitlines()[0] if result.stdout.strip() else ""
        assert first_line.startswith("/"), f"Expected absolute path in fullpath output, got: {first_line!r}"

    def test_rp_list_09_outer_manifest(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-09: `kanon repo list --outer-manifest` exits 0."""
        result = run_kanon("repo", "list", "--outer-manifest", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --outer-manifest exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_list_10_this_manifest_only(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-list-10: `kanon repo list --this-manifest-only` exits 0."""
        result = run_kanon("repo", "list", "--this-manifest-only", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo list --this-manifest-only exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
