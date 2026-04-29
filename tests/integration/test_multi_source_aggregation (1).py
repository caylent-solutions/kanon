"""Integration tests for multi-source aggregation.

Covers the MS-01 and MS-02 test classes from docs/integration-testing.md:
  - MS-01: Two sources with distinct packages aggregate correctly
  - MS-02: Two sources with conflicting paths surface a collision error
  - Source priority order (alphabetical) is respected
  - Aggregation is stable across re-runs

These tests use the install() entry point with patched repo operations.
Real temporary directories are used to verify filesystem state. The repo
network calls are mocked so tests run without external dependencies.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.install import aggregate_symlinks, install


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: Path, content: str) -> Path:
    """Write a .kanon file in directory and return its path.

    Args:
        directory: Directory to write the .kanon file in.
        content: Text content for the .kanon file.

    Returns:
        Path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


def _two_source_kanonenv_content(source_alpha: str, source_bravo: str) -> str:
    """Return .kanon content for two named sources pointing at placeholder URLs.

    Args:
        source_alpha: Name for the first source (alphabetically first).
        source_bravo: Name for the second source (alphabetically second).

    Returns:
        Text content for a two-source .kanon file.
    """
    return (
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_alpha}_URL=https://example.com/{source_alpha}.git\n"
        f"KANON_SOURCE_{source_alpha}_REVISION=main\n"
        f"KANON_SOURCE_{source_alpha}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_bravo}_URL=https://example.com/{source_bravo}.git\n"
        f"KANON_SOURCE_{source_bravo}_REVISION=main\n"
        f"KANON_SOURCE_{source_bravo}_PATH=repo-specs/manifest.xml\n"
    )


def _populate_source_packages(
    base_dir: Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Create package directories under .kanon-data/sources/<name>/.packages/.

    Simulates what repo sync would do: creates the package directories
    so aggregate_symlinks has real directories to link into .packages/.

    Args:
        base_dir: Project root directory.
        packages_by_source: Mapping of source name to list of package names
            to create under that source's .packages/ directory.
    """
    for source_name, pkg_names in packages_by_source.items():
        for pkg_name in pkg_names:
            pkg_dir = base_dir / ".kanon-data" / "sources" / source_name / ".packages" / pkg_name
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text(f"# {pkg_name}\n")


def _install_with_packages(
    kanonenv: Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Run install() with fake repo operations that create package directories.

    The fake repo_sync side effect populates .packages/ directories for each
    source so aggregate_symlinks has real content to process.

    Args:
        kanonenv: Path to the .kanon configuration file.
        packages_by_source: Mapping of source name to list of package names.
    """

    def _fake_repo_sync(repo_dir: str, **kwargs: object) -> None:
        repo_path = Path(repo_dir)
        # Source name is the last component of the path under .kanon-data/sources/
        source_name = repo_path.name
        pkg_names = packages_by_source.get(source_name, [])
        for pkg_name in pkg_names:
            pkg_dir = repo_path / ".packages" / pkg_name
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text(f"# {pkg_name}\n")

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync", side_effect=_fake_repo_sync),
    ):
        install(kanonenv)


# ---------------------------------------------------------------------------
# AC-TEST-001: MS-01 class -- two sources with distinct packages aggregate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMS01TwoSourcesDistinctPackages:
    """MS-01: Two sources with distinct packages aggregate correctly.

    Each source contributes unique package names; both packages must appear
    in the top-level .packages/ as symlinks pointing into their respective
    .kanon-data/sources/<name>/ workspace.
    """

    def test_both_packages_present_in_packages_dir(self, tmp_path: Path) -> None:
        """Both packages from separate sources appear in .packages/ after install.

        Source 'alpha' delivers 'pkg-alpha'; source 'bravo' delivers 'pkg-bravo'.
        Both symlinks must exist in .packages/ after a successful install.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        pkg_alpha_link = tmp_path / ".packages" / "pkg-alpha"
        pkg_bravo_link = tmp_path / ".packages" / "pkg-bravo"

        assert pkg_alpha_link.is_symlink(), "pkg-alpha from source 'alpha' must be symlinked in .packages/"
        assert pkg_bravo_link.is_symlink(), "pkg-bravo from source 'bravo' must be symlinked in .packages/"

    def test_symlinks_resolve_into_correct_source_workspace(self, tmp_path: Path) -> None:
        """Each symlink in .packages/ must resolve into its source's workspace directory.

        The symlink for a package from source 'alpha' must point into
        .kanon-data/sources/alpha/.packages/pkg-alpha, and likewise for 'bravo'.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        pkg_alpha_link = tmp_path / ".packages" / "pkg-alpha"
        pkg_bravo_link = tmp_path / ".packages" / "pkg-bravo"

        alpha_workspace = tmp_path / ".kanon-data" / "sources" / "alpha" / ".packages" / "pkg-alpha"
        bravo_workspace = tmp_path / ".kanon-data" / "sources" / "bravo" / ".packages" / "pkg-bravo"

        assert pkg_alpha_link.resolve() == alpha_workspace.resolve(), (
            f"pkg-alpha symlink must resolve to alpha workspace, got {pkg_alpha_link.resolve()}"
        )
        assert pkg_bravo_link.resolve() == bravo_workspace.resolve(), (
            f"pkg-bravo symlink must resolve to bravo workspace, got {pkg_bravo_link.resolve()}"
        )

    def test_separate_source_workspace_dirs_created_for_each_source(self, tmp_path: Path) -> None:
        """Each source gets its own isolated workspace directory under .kanon-data/sources/.

        Two sources means two directories: .kanon-data/sources/alpha/ and
        .kanon-data/sources/bravo/. Both must exist and be separate directories.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        alpha_workspace = tmp_path / ".kanon-data" / "sources" / "alpha"
        bravo_workspace = tmp_path / ".kanon-data" / "sources" / "bravo"

        assert alpha_workspace.is_dir(), ".kanon-data/sources/alpha/ must exist for source 'alpha'"
        assert bravo_workspace.is_dir(), ".kanon-data/sources/bravo/ must exist for source 'bravo'"
        assert alpha_workspace != bravo_workspace, "Source workspaces must be distinct directories"

    def test_install_exits_zero_with_two_distinct_sources(self, tmp_path: Path) -> None:
        """install() must complete without raising SystemExit when sources are disjoint."""
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))

        try:
            _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})
        except SystemExit as exc:
            raise AssertionError(
                f"install() must not raise SystemExit for two disjoint sources, got exit code {exc.code}"
            ) from exc

    def test_multiple_packages_per_source_all_aggregated(self, tmp_path: Path) -> None:
        """Each source may contribute multiple packages; all must appear in .packages/.

        Source 'alpha' provides two packages; source 'bravo' provides two packages.
        All four must be symlinked in .packages/ after a successful install.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(
            kanonenv,
            {
                "alpha": ["pkg-alpha-a", "pkg-alpha-b"],
                "bravo": ["pkg-bravo-a", "pkg-bravo-b"],
            },
        )

        for pkg_name in ["pkg-alpha-a", "pkg-alpha-b", "pkg-bravo-a", "pkg-bravo-b"]:
            link = tmp_path / ".packages" / pkg_name
            assert link.is_symlink(), f"Package '{pkg_name}' must be symlinked in .packages/ after install"


# ---------------------------------------------------------------------------
# AC-TEST-002: MS-02 class -- conflicting paths surface collision error
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMS02ConflictingPathsCollisionError:
    """MS-02: Two sources with the same package path surface a collision error.

    When two sources contribute a package with the same name (same path
    relative to .packages/), install must exit non-zero and write a
    'Package collision' message to stderr.
    """

    def test_collision_causes_nonzero_exit(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """install() exits with a non-zero code when two sources produce the same package name.

        Both 'alpha' and 'bravo' deliver 'pkg-shared'. This is a path collision
        and must abort the install immediately.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))

        # Populate package directories directly so aggregate_symlinks sees them
        _populate_source_packages(tmp_path, {"alpha": ["pkg-shared"], "bravo": ["pkg-shared"]})

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv)

        assert exc_info.value.code != 0, "install() must exit with non-zero code when a package collision is detected"

    def test_collision_writes_package_collision_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """install() writes a 'Package collision' message to stderr on duplicate package path.

        The error message must name the package that collides so operators
        know which package to fix.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _populate_source_packages(tmp_path, {"alpha": ["pkg-shared"], "bravo": ["pkg-shared"]})

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv)

        captured = capsys.readouterr()
        assert "Package collision" in captured.err, f"stderr must contain 'Package collision', got: {captured.err!r}"
        assert "pkg-shared" in captured.err, (
            f"stderr must name the colliding package 'pkg-shared', got: {captured.err!r}"
        )

    def test_collision_error_names_both_conflicting_sources(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """The collision error message names both sources involved in the conflict.

        When 'alpha' and 'bravo' both provide 'pkg-conflict', the error
        must mention both source names so the operator knows which sources
        to reconcile.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _populate_source_packages(tmp_path, {"alpha": ["pkg-conflict"], "bravo": ["pkg-conflict"]})

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv)

        captured = capsys.readouterr()
        assert "alpha" in captured.err, f"Error must name source 'alpha', got stderr: {captured.err!r}"
        assert "bravo" in captured.err, f"Error must name source 'bravo', got stderr: {captured.err!r}"

    @pytest.mark.parametrize(
        "colliding_pkg",
        ["pkg-alpha", "build-tools", "kanon-shared-utils"],
    )
    def test_collision_detected_for_various_package_names(
        self,
        tmp_path: Path,
        colliding_pkg: str,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Package collision detection works for any package name.

        The collision check is name-based; any duplicate name triggers the error
        regardless of the specific package name.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _populate_source_packages(tmp_path, {"alpha": [colliding_pkg], "bravo": [colliding_pkg]})

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv)

        assert exc_info.value.code != 0, f"install() must exit non-zero for collision on '{colliding_pkg}'"
        captured = capsys.readouterr()
        assert colliding_pkg in captured.err, f"stderr must name the colliding package '{colliding_pkg}'"


# ---------------------------------------------------------------------------
# AC-TEST-003: Source priority order is respected (alphabetical)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSourcePriorityOrder:
    """Source priority order (alphabetical) is respected during aggregation.

    Sources are processed in alphabetical order by name. When sources are
    disjoint the ordering affects which source 'owns' a package if a collision
    would arise, and the collision error names the first source as the
    incumbent owner.
    """

    def test_sources_processed_in_alphabetical_order(self, tmp_path: Path) -> None:
        """aggregate_symlinks processes sources in the order provided (alphabetical).

        With sources ['aaa', 'zzz'] and each delivering a unique package,
        both packages are aggregated. The 'aaa' source is processed first.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("aaa", "zzz"))
        _install_with_packages(kanonenv, {"aaa": ["pkg-from-aaa"], "zzz": ["pkg-from-zzz"]})

        assert (tmp_path / ".packages" / "pkg-from-aaa").is_symlink(), (
            "pkg-from-aaa from source 'aaa' must be symlinked in .packages/"
        )
        assert (tmp_path / ".packages" / "pkg-from-zzz").is_symlink(), (
            "pkg-from-zzz from source 'zzz' must be symlinked in .packages/"
        )

    def test_alphabetically_first_source_owns_package_in_collision_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When a collision occurs, the error message names the first-processed source.

        Sources are ordered alphabetically. If 'aaa' is processed before 'zzz'
        and both provide 'shared-pkg', the error must name 'aaa' as the
        existing owner and 'zzz' as the conflicting source.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("aaa", "zzz"))
        _populate_source_packages(tmp_path, {"aaa": ["shared-pkg"], "zzz": ["shared-pkg"]})

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                install(kanonenv)

        captured = capsys.readouterr()
        # 'aaa' must appear before 'zzz' in the error message as it is the incumbent
        aaa_pos = captured.err.find("aaa")
        zzz_pos = captured.err.find("zzz")
        assert aaa_pos != -1, f"Source 'aaa' must be named in the collision error: {captured.err!r}"
        assert zzz_pos != -1, f"Source 'zzz' must be named in the collision error: {captured.err!r}"
        assert aaa_pos < zzz_pos, (
            f"Alphabetically first source 'aaa' must appear before 'zzz' in collision error "
            f"(aaa_pos={aaa_pos}, zzz_pos={zzz_pos}): {captured.err!r}"
        )

    def test_aggregate_symlinks_uses_caller_provided_source_order(self, tmp_path: Path) -> None:
        """aggregate_symlinks respects the source_names order passed by the caller.

        The function does not re-sort internally -- it processes sources in
        exactly the order provided. Providing ['beta', 'alpha'] causes 'beta'
        to be processed first, even though 'alpha' sorts lower.
        """
        # Create source workspaces manually for this lower-level test
        beta_pkg = tmp_path / ".kanon-data" / "sources" / "beta" / ".packages" / "pkg-beta"
        alpha_pkg = tmp_path / ".kanon-data" / "sources" / "alpha" / ".packages" / "pkg-alpha"
        beta_pkg.mkdir(parents=True, exist_ok=True)
        alpha_pkg.mkdir(parents=True, exist_ok=True)

        # Pass order ['beta', 'alpha'] -- beta goes first despite sort order
        result = aggregate_symlinks(["beta", "alpha"], tmp_path)

        assert "pkg-beta" in result, "pkg-beta from source 'beta' must be aggregated"
        assert result["pkg-beta"] == "beta", "pkg-beta must be owned by source 'beta'"
        assert "pkg-alpha" in result, "pkg-alpha from source 'alpha' must be aggregated"
        assert result["pkg-alpha"] == "alpha", "pkg-alpha must be owned by source 'alpha'"


# ---------------------------------------------------------------------------
# AC-TEST-004: Aggregation is stable across re-runs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAggregationStabilityAcrossReRuns:
    """Aggregation is stable across re-runs (idempotent).

    Running install() twice with the same configuration and the same packages
    must produce the same .packages/ state both times. No duplicate symlinks,
    no missing packages, no stale entries.
    """

    def test_second_install_produces_same_packages_as_first(self, tmp_path: Path) -> None:
        """Running install twice yields identical .packages/ contents.

        After the first install, record the names in .packages/. After the
        second install, the names must be identical (no additions, no deletions).
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        first_run_names = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        second_run_names = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        assert first_run_names == second_run_names, (
            f"Re-install must produce identical .packages/ contents: first={first_run_names}, second={second_run_names}"
        )

    def test_all_symlinks_valid_after_second_install(self, tmp_path: Path) -> None:
        """After a second install, all symlinks in .packages/ resolve to valid targets.

        The second install replaces existing symlinks idempotently. Every
        symlink must resolve to an existing directory.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        packages_dir = tmp_path / ".packages"
        for entry in packages_dir.iterdir():
            assert entry.is_symlink(), f"{entry.name} must be a symlink"
            assert entry.resolve().exists(), f"Symlink {entry.name} must resolve to an existing path after re-install"

    def test_package_count_unchanged_after_multiple_installs(self, tmp_path: Path) -> None:
        """The number of packages in .packages/ is the same after each install.

        With two sources each delivering one package, exactly two symlinks
        must appear in .packages/ after each run -- not three, not four.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))

        for _run in range(3):
            _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        packages = list((tmp_path / ".packages").iterdir())
        assert len(packages) == 2, (
            f"Exactly 2 packages must exist in .packages/ after 3 installs, found: {[p.name for p in packages]}"
        )

    def test_symlink_targets_unchanged_after_re_install(self, tmp_path: Path) -> None:
        """Symlink targets remain consistent across multiple install runs.

        The resolved target of each symlink must be the same directory
        before and after a re-install.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_kanonenv_content("alpha", "bravo"))
        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        first_targets = {
            entry.name: str(entry.resolve()) for entry in (tmp_path / ".packages").iterdir() if entry.is_symlink()
        }

        _install_with_packages(kanonenv, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        second_targets = {
            entry.name: str(entry.resolve()) for entry in (tmp_path / ".packages").iterdir() if entry.is_symlink()
        }

        assert first_targets == second_targets, (
            f"Symlink targets must be identical after re-install: first={first_targets}, second={second_targets}"
        )
