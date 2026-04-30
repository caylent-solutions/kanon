"""RP-diffmanifests-01..05: `kanon repo diffmanifests` scenario tests.

Covers §25 of `docs/integration-testing.md`.

All five scenarios share a module-scoped synced checkout.  Each test that
needs a manifest file generates it via `kanon repo manifest --output=<file>`.
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
    """Module-scoped synced repo checkout shared across RP-diffmanifests-* tests."""
    base = tmp_path_factory.mktemp("rp_diffmanifests")
    return _build_rp_ro_repo(base)


def _dump_manifest(checkout: pathlib.Path, out_file: pathlib.Path) -> None:
    """Run `kanon repo manifest --output=<out_file>` and assert success."""
    result = run_kanon("repo", "manifest", f"--output={out_file}", cwd=checkout)
    assert result.returncode == 0, f"repo manifest --output failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    assert out_file.exists(), f"Expected manifest at {out_file}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRPDiffManifests:
    """RP-diffmanifests-01..05: kanon repo diffmanifests subcommand."""

    def test_rp_diffmanifests_01_one_arg(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-diffmanifests-01: `kanon repo diffmanifests <file>` exits 0."""
        m1 = tmp_path / "m1.xml"
        _dump_manifest(rp_ro_checkout, m1)

        result = run_kanon("repo", "diffmanifests", str(m1), cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo diffmanifests (one-arg) exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_diffmanifests_02_two_arg(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-diffmanifests-02: `kanon repo diffmanifests <f1> <f2>` exits 0; empty diff."""
        m1 = tmp_path / "m1.xml"
        m2 = tmp_path / "m2.xml"
        _dump_manifest(rp_ro_checkout, m1)
        _dump_manifest(rp_ro_checkout, m2)

        result = run_kanon("repo", "diffmanifests", str(m1), str(m2), cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo diffmanifests (two-arg) exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_diffmanifests_03_raw(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-diffmanifests-03: `kanon repo diffmanifests --raw <file>` exits 0."""
        m1 = tmp_path / "m1.xml"
        _dump_manifest(rp_ro_checkout, m1)

        result = run_kanon("repo", "diffmanifests", "--raw", str(m1), cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo diffmanifests --raw exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_diffmanifests_04_no_color(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-diffmanifests-04: `kanon repo diffmanifests --no-color <file>` exits 0."""
        m1 = tmp_path / "m1.xml"
        _dump_manifest(rp_ro_checkout, m1)

        result = run_kanon("repo", "diffmanifests", "--no-color", str(m1), cwd=rp_ro_checkout)
        assert result.returncode == 0, (
            f"repo diffmanifests --no-color exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_diffmanifests_05_pretty_format(self, rp_ro_checkout: pathlib.Path, tmp_path: pathlib.Path) -> None:
        """RP-diffmanifests-05: `kanon repo diffmanifests --pretty-format=oneline <file>` exits 0."""
        m1 = tmp_path / "m1.xml"
        _dump_manifest(rp_ro_checkout, m1)

        result = run_kanon(
            "repo",
            "diffmanifests",
            "--pretty-format=oneline",
            str(m1),
            cwd=rp_ro_checkout,
        )
        assert result.returncode == 0, (
            f"repo diffmanifests --pretty-format exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
