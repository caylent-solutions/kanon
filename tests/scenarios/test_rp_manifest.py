"""RP-manifest-01..11: `kanon repo manifest` scenario tests.

Covers §22 of `docs/integration-testing.md`.

All eleven scenarios share a single module-scoped synced checkout.
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
    """Module-scoped synced repo checkout shared across RP-manifest-* tests."""
    base = tmp_path_factory.mktemp("rp_manifest")
    return _build_rp_ro_repo(base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPManifest:
    """RP-manifest-01..11: kanon repo manifest subcommand."""

    def test_rp_manifest_01_bare_manifest_stdout(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-01: bare `kanon repo manifest` exits 0; XML printed to stdout."""
        result = run_kanon("repo", "manifest", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), (
            f"Expected XML output starting with '<?xml', got: {result.stdout[:80]!r}"
        )

    def test_rp_manifest_02_output_file(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-manifest-02: `kanon repo manifest --output=<file>` writes XML to file."""
        out_file = tmp_path / "m.xml"
        result = run_kanon("repo", "manifest", f"--output={out_file}", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --output exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert out_file.exists(), f"Expected manifest output at {out_file}"
        content = out_file.read_text()
        assert content.lstrip().startswith("<?xml"), f"Expected XML in output file, got: {content[:80]!r}"

    def test_rp_manifest_03_manifest_name(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-03: `kanon repo manifest --manifest-name=default.xml` exits 0."""
        result = run_kanon(
            "repo",
            "manifest",
            "--manifest-name=repo-specs/packages.xml",
            cwd=rp_ro_checkout,
        )
        assert result.returncode == 0, (
            f"repo manifest --manifest-name exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_manifest_04_revision_as_head(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-04: `kanon repo manifest --revision-as-HEAD` exits 0; revision= present."""
        result = run_kanon("repo", "manifest", "--revision-as-HEAD", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --revision-as-HEAD exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "revision=" in result.stdout, f"Expected 'revision=' in output: {result.stdout!r}"

    def test_rp_manifest_05_suppress_upstream_revision(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-05: `kanon repo manifest -r --suppress-upstream-revision` omits upstream=."""
        result = run_kanon(
            "repo",
            "manifest",
            "--revision-as-HEAD",
            "--suppress-upstream-revision",
            cwd=rp_ro_checkout,
        )
        assert result.returncode == 0, (
            f"repo manifest --suppress-upstream-revision exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "upstream=" not in result.stdout, f"Expected 'upstream=' to be omitted from output: {result.stdout!r}"

    def test_rp_manifest_06_suppress_dest_branch(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-06: `kanon repo manifest -r --suppress-dest-branch` omits dest-branch=."""
        result = run_kanon(
            "repo",
            "manifest",
            "--revision-as-HEAD",
            "--suppress-dest-branch",
            cwd=rp_ro_checkout,
        )
        assert result.returncode == 0, (
            f"repo manifest --suppress-dest-branch exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "dest-branch=" not in result.stdout, (
            f"Expected 'dest-branch=' to be omitted from output: {result.stdout!r}"
        )

    def test_rp_manifest_07_pretty(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-07: `kanon repo manifest --pretty` exits 0; human-formatted output."""
        result = run_kanon("repo", "manifest", "--pretty", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --pretty exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), f"Expected XML output from --pretty: {result.stdout[:80]!r}"

    def test_rp_manifest_08_no_local_manifests(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-08: `kanon repo manifest --no-local-manifests` exits 0."""
        result = run_kanon("repo", "manifest", "--no-local-manifests", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --no-local-manifests exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), f"Expected XML output: {result.stdout[:80]!r}"

    def test_rp_manifest_09_outer_manifest(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-09: `kanon repo manifest --outer-manifest` exits 0."""
        result = run_kanon("repo", "manifest", "--outer-manifest", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --outer-manifest exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), f"Expected XML output: {result.stdout[:80]!r}"

    def test_rp_manifest_10_no_outer_manifest(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-10: `kanon repo manifest --no-outer-manifest` exits 0."""
        result = run_kanon("repo", "manifest", "--no-outer-manifest", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --no-outer-manifest exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), f"Expected XML output: {result.stdout[:80]!r}"

    def test_rp_manifest_11_revision_as_tag(self, rp_ro_checkout: pathlib.Path) -> None:
        """RP-manifest-11: `kanon repo manifest --revision-as-tag` exits 0.

        The workspace is untagged so all projects take the warn-and-keep path:
        a warning is emitted to stderr and each project's original revision is
        preserved unchanged in the output.
        """
        result = run_kanon("repo", "manifest", "--revision-as-tag", cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo manifest --revision-as-tag exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.lstrip().startswith("<?xml"), f"Expected XML output: {result.stdout[:80]!r}"
