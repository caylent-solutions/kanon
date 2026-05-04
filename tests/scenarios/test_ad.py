"""AD (Auto-Discovery) scenarios from `docs/integration-testing.md` §15.

Each scenario exercises `kanon install` / `kanon clean` auto-discovery of the
`.kanon` file by walking up the directory tree when no explicit path is given.
All fixtures are built from local bare git repos via `file://` URLs so no
network access is required.

Scenarios automated:
- AD-01: kanon install (no arg) in directory with .kanon
- AD-02: kanon install in subdirectory, .kanon in parent
- AD-03: kanon install with no .kanon anywhere
- AD-04: kanon install .kanon (explicit) still works
- AD-05: kanon clean (no arg) in directory with .kanon
- AD-06: kanon clean in subdirectory, .kanon in parent
- AD-07: kanon install /explicit/path/.kanon overrides discovery
- AD-08: kanon install prints which .kanon was found
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    make_plain_repo,
    run_kanon,
    write_kanonenv,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_pkg_alpha(fixtures_dir: pathlib.Path) -> pathlib.Path:
    """Create a bare content repo for pkg-alpha under fixtures_dir/content-repos.

    Returns the bare repo path (fixtures_dir/content-repos/pkg-alpha.git).
    """
    content_dir = fixtures_dir / "content-repos"
    content_dir.mkdir(parents=True, exist_ok=True)
    return make_plain_repo(
        content_dir,
        "pkg-alpha",
        {
            "src/main.py": 'print("alpha")\n',
            "README.md": "# Alpha Package\n",
        },
    )


def _build_manifest_primary(
    fixtures_dir: pathlib.Path,
    pkg_alpha_bare: pathlib.Path,
) -> pathlib.Path:
    """Create a bare manifest repo containing repo-specs/remote.xml and alpha-only.xml.

    The remote.xml fetch URL points at the directory that *contains* the pkg-alpha
    bare repo (i.e. `pkg_alpha_bare.parent`) so the repo tool resolves the project
    `name="pkg-alpha"` to `<fetch>/pkg-alpha`.

    Returns the bare manifest repo path.
    """
    manifest_dir = fixtures_dir / "manifest-repos"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    # pkg-alpha bare repo sits at pkg_alpha_bare; its parent is the fetch root.
    content_fetch_url = pkg_alpha_bare.parent.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_url}" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )

    alpha_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha" remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    return make_plain_repo(
        manifest_dir,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
        },
    )


def _build_ad_fixtures(fixtures_dir: pathlib.Path) -> pathlib.Path:
    """Build all fixtures needed by the AD scenarios.

    Returns the bare manifest-primary repo path.
    """
    pkg_alpha_bare = _build_pkg_alpha(fixtures_dir)
    return _build_manifest_primary(fixtures_dir, pkg_alpha_bare)


def _write_ad_kanonenv(work_dir: pathlib.Path, manifest_bare: pathlib.Path) -> pathlib.Path:
    """Write a .kanon referencing the alpha-only.xml manifest into work_dir."""
    return write_kanonenv(
        work_dir,
        [
            (
                "primary",
                manifest_bare.as_uri(),
                "main",
                "repo-specs/alpha-only.xml",
            )
        ],
        marketplace_install="false",
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestAD:
    def test_ad_01_install_no_arg_in_dir_with_kanon(self, tmp_path: pathlib.Path) -> None:
        """AD-01: kanon install (no arg) in directory with .kanon."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        work_dir = tmp_path / "test-ad01"
        work_dir.mkdir()
        _write_ad_kanonenv(work_dir, manifest_bare)

        result = run_kanon("install", cwd=work_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon install: done" in result.stdout, f"stdout={result.stdout!r}"
        assert (work_dir / ".packages" / "pkg-alpha").exists(), f".packages/pkg-alpha not found in {work_dir}"

    def test_ad_02_install_from_subdirectory(self, tmp_path: pathlib.Path) -> None:
        """AD-02: kanon install in subdirectory, .kanon in parent."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        parent_dir = tmp_path / "test-ad02"
        child_dir = parent_dir / "child"
        parent_dir.mkdir()
        child_dir.mkdir()
        _write_ad_kanonenv(parent_dir, manifest_bare)

        result = run_kanon("install", cwd=child_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon install: done" in result.stdout, f"stdout={result.stdout!r}"
        # Packages land next to the .kanon, i.e. in the parent dir.
        assert (parent_dir / ".packages" / "pkg-alpha").exists(), f".packages/pkg-alpha not found in {parent_dir}"

    def test_ad_03_install_with_no_kanon_anywhere(self, tmp_path: pathlib.Path) -> None:
        """AD-03: kanon install with no .kanon anywhere -- must fail with exit 1."""
        work_dir = tmp_path / "test-ad03"
        work_dir.mkdir()
        # Deliberately do NOT create a .kanon file.

        result = run_kanon("install", cwd=work_dir)

        assert result.returncode != 0, "expected non-zero exit when no .kanon exists but got 0"
        combined = result.stderr + result.stdout
        assert ".kanon" in combined, f"expected '.kanon' in stderr/stdout but got: {combined!r}"

    def test_ad_04_install_explicit_kanon_arg(self, tmp_path: pathlib.Path) -> None:
        """AD-04: kanon install .kanon (explicit relative path) still works."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        work_dir = tmp_path / "test-ad04"
        work_dir.mkdir()
        _write_ad_kanonenv(work_dir, manifest_bare)

        result = run_kanon("install", ".kanon", cwd=work_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon install: done" in result.stdout, f"stdout={result.stdout!r}"
        assert (work_dir / ".packages" / "pkg-alpha").exists(), f".packages/pkg-alpha not found in {work_dir}"

    def test_ad_05_clean_no_arg_in_dir_with_kanon(self, tmp_path: pathlib.Path) -> None:
        """AD-05: kanon clean (no arg) in directory with .kanon removes artifacts."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        work_dir = tmp_path / "test-ad05"
        work_dir.mkdir()
        _write_ad_kanonenv(work_dir, manifest_bare)

        # First install with explicit arg, then clean without any arg.
        install_result = run_kanon("install", ".kanon", cwd=work_dir)
        assert install_result.returncode == 0, (
            f"install failed: stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        result = run_kanon("clean", cwd=work_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon clean: done" in result.stdout, f"stdout={result.stdout!r}"
        assert not (work_dir / ".packages").exists(), f".packages/ still exists after clean in {work_dir}"
        assert not (work_dir / ".kanon-data").exists(), f".kanon-data/ still exists after clean in {work_dir}"

    def test_ad_06_clean_from_subdirectory(self, tmp_path: pathlib.Path) -> None:
        """AD-06: kanon clean in subdirectory, .kanon in parent."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        parent_dir = tmp_path / "test-ad06"
        child_dir = parent_dir / "child"
        parent_dir.mkdir()
        child_dir.mkdir()
        _write_ad_kanonenv(parent_dir, manifest_bare)

        install_result = run_kanon("install", ".kanon", cwd=parent_dir)
        assert install_result.returncode == 0, (
            f"install failed: stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        result = run_kanon("clean", cwd=child_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon clean: done" in result.stdout, f"stdout={result.stdout!r}"
        assert not (parent_dir / ".packages").exists(), f".packages/ still exists in parent {parent_dir}"
        assert not (parent_dir / ".kanon-data").exists(), f".kanon-data/ still exists in parent {parent_dir}"

    def test_ad_07_explicit_path_overrides_discovery(self, tmp_path: pathlib.Path) -> None:
        """AD-07: kanon install /explicit/path/.kanon ignores cwd's .kanon."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)

        # cwd dir without a .kanon.
        cwd_dir = tmp_path / "test-ad07-cwd"
        cwd_dir.mkdir()

        # Separate dir with the real .kanon.
        explicit_dir = tmp_path / "test-ad07-explicit"
        explicit_dir.mkdir()
        _write_ad_kanonenv(explicit_dir, manifest_bare)

        result = run_kanon("install", str(explicit_dir / ".kanon"), cwd=cwd_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert "kanon install: done" in result.stdout, f"stdout={result.stdout!r}"
        # Packages must land next to the explicit .kanon, not in cwd.
        assert (explicit_dir / ".packages" / "pkg-alpha").exists(), (
            f".packages/pkg-alpha not found in explicit dir {explicit_dir}"
        )
        assert not (cwd_dir / ".packages").exists(), f".packages/ unexpectedly created in cwd {cwd_dir}"

    def test_ad_08_install_prints_found_kanon_path(self, tmp_path: pathlib.Path) -> None:
        """AD-08: kanon install prints 'found' and the path to the discovered .kanon."""
        fixtures_dir = tmp_path / "fixtures"
        manifest_bare = _build_ad_fixtures(fixtures_dir)
        work_dir = tmp_path / "test-ad08"
        work_dir.mkdir()
        _write_ad_kanonenv(work_dir, manifest_bare)

        result = run_kanon("install", cwd=work_dir)

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        combined = result.stdout + result.stderr
        assert "found" in combined.lower(), f"expected 'found' in combined output but got: {combined!r}"
        assert ".kanon" in combined, f"expected .kanon path in output but got: {combined!r}"
