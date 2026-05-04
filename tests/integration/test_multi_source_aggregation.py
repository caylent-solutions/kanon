"""Integration tests for multi-source symlink aggregation in kanon.

Covers the MS-01 multi-source scenario from Category 5 of docs/integration-testing.md
and the CD-01/CD-02 collision detection scenarios from Category 6.

The aggregate_symlinks() function at kanon_cli.core.install:
- Accepts an ordered list of source names and a base directory.
- Creates symlinks in .packages/ pointing into
  .kanon-data/sources/<name>/.packages/<pkg>/ for each package.
- Returns a dict mapping package name to source name.
- Raises ValueError (not SystemExit) on collision when two sources
  produce the same package name.

The repo network calls (repo_init, repo_envsubst, repo_sync) are out of scope
for these tests since they require real git remote servers. All filesystem
state is exercised directly via aggregate_symlinks() against real tmp_path
directories.
"""

import pathlib

import pytest

from kanon_cli.core.install import aggregate_symlinks

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_NUM_STABILITY_RUNS = 3


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_source_package(base_dir: pathlib.Path, source_name: str, pkg_name: str) -> pathlib.Path:
    """Create a fake package directory inside .kanon-data/sources/<source>/.packages/<pkg>.

    Args:
        base_dir: Project root (tmp_path).
        source_name: Name of the source directory to create the package under.
        pkg_name: Package name to create.

    Returns:
        Path to the created package directory.
    """
    pkg_dir = base_dir / ".kanon-data" / "sources" / source_name / ".packages" / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "README.md").write_text(f"# {pkg_name}\n")
    return pkg_dir


def _make_source_packages(
    base_dir: pathlib.Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Create multiple fake package directories for multiple sources.

    Args:
        base_dir: Project root (tmp_path).
        packages_by_source: Mapping of source name to list of package names.
    """
    for source_name, pkg_names in packages_by_source.items():
        for pkg_name in pkg_names:
            _make_source_package(base_dir, source_name, pkg_name)


# ---------------------------------------------------------------------------
# AC-TEST-001: MS-01 class -- two sources with distinct packages aggregate correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMS01TwoSourcesDistinctPackages:
    """AC-TEST-001: MS-01 -- two sources with distinct packages aggregate correctly.

    Verifies that aggregate_symlinks() correctly handles two sources whose
    package sets are completely disjoint: all packages from both sources are
    present in .packages/ as symlinks, return dict covers all packages, and
    no ValueError is raised.
    """

    def test_symlinks_created_for_both_sources(self, tmp_path: pathlib.Path) -> None:
        """Both alpha and bravo packages appear as symlinks in .packages/.

        After aggregate_symlinks() with disjoint sources, every declared
        package from both sources must have a symlink under .packages/.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        aggregate_symlinks(["alpha", "bravo"], tmp_path)

        alpha_link = tmp_path / ".packages" / "pkg-alpha"
        bravo_link = tmp_path / ".packages" / "pkg-bravo"
        assert alpha_link.is_symlink(), f"pkg-alpha must be a symlink in .packages/ at {alpha_link}; it does not exist"
        assert bravo_link.is_symlink(), f"pkg-bravo must be a symlink in .packages/ at {bravo_link}; it does not exist"

    def test_symlink_resolves_to_correct_source_workspace(self, tmp_path: pathlib.Path) -> None:
        """Each symlink resolves to the package directory inside its source workspace.

        The symlink for pkg-alpha must point into
        .kanon-data/sources/alpha/.packages/pkg-alpha, not into bravo's workspace.
        """
        alpha_pkg = _make_source_package(tmp_path, "alpha", "pkg-alpha")
        _make_source_package(tmp_path, "bravo", "pkg-bravo")

        aggregate_symlinks(["alpha", "bravo"], tmp_path)

        alpha_link = tmp_path / ".packages" / "pkg-alpha"
        assert alpha_link.resolve() == alpha_pkg.resolve(), (
            f"pkg-alpha symlink must resolve to alpha workspace; "
            f"expected {alpha_pkg.resolve()}, got {alpha_link.resolve()}"
        )

    def test_return_dict_maps_each_package_to_its_source(self, tmp_path: pathlib.Path) -> None:
        """aggregate_symlinks returns a dict mapping each package to its owning source.

        For disjoint sources, each package key maps to exactly the source that
        declares it.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        owners = aggregate_symlinks(["alpha", "bravo"], tmp_path)

        assert owners.get("pkg-alpha") == "alpha", (
            f"pkg-alpha must be owned by 'alpha'; got {owners.get('pkg-alpha')!r}"
        )
        assert owners.get("pkg-bravo") == "bravo", (
            f"pkg-bravo must be owned by 'bravo'; got {owners.get('pkg-bravo')!r}"
        )

    def test_return_dict_covers_all_packages(self, tmp_path: pathlib.Path) -> None:
        """The return dict contains exactly one entry per package across all sources.

        With 2 packages total (1 per source), the return dict must have length 2.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        owners = aggregate_symlinks(["alpha", "bravo"], tmp_path)

        assert len(owners) == 2, f"Return dict must have exactly 2 entries for 2 packages; got {len(owners)}: {owners}"

    @pytest.mark.parametrize(
        "source_alpha,source_bravo",
        [
            ("alpha", "bravo"),
            ("primary", "secondary"),
            ("aaa", "zzz"),
        ],
    )
    def test_distinct_package_sets_do_not_raise(
        self,
        tmp_path: pathlib.Path,
        source_alpha: str,
        source_bravo: str,
    ) -> None:
        """aggregate_symlinks does not raise when two sources have distinct package sets.

        No ValueError must be raised for disjoint package sets regardless of the
        source names used.
        """
        _make_source_packages(
            tmp_path,
            {source_alpha: [f"pkg-{source_alpha}"], source_bravo: [f"pkg-{source_bravo}"]},
        )

        # Must not raise
        owners = aggregate_symlinks([source_alpha, source_bravo], tmp_path)

        assert len(owners) == 2, f"Both packages must be registered; got {len(owners)} entries: {owners}"


# ---------------------------------------------------------------------------
# AC-TEST-002: CD-01/CD-02 class -- colliding paths raise ValueError
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCD01CD02ConflictingPathsCollisionError:
    """AC-TEST-002: CD-01/CD-02 -- conflicting package paths raise ValueError.

    Verifies that aggregate_symlinks() raises ValueError (not SystemExit)
    when two sources declare the same package name, and that the error
    message contains the package name and both contributing source names.
    """

    def test_collision_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        """Two sources with the same package name raise ValueError.

        aggregate_symlinks() must raise ValueError, not SystemExit or any
        other exception type.
        """
        _make_source_packages(
            tmp_path,
            {"primary": ["pkg-alpha"], "secondary": ["pkg-alpha"]},
        )

        with pytest.raises(ValueError, match="pkg-alpha"):
            aggregate_symlinks(["primary", "secondary"], tmp_path)

    def test_collision_error_names_the_colliding_package(self, tmp_path: pathlib.Path) -> None:
        """The ValueError message names the colliding package.

        The error message must contain the name of the package that caused
        the collision so the user knows which package to investigate.
        """
        _make_source_packages(
            tmp_path,
            {"primary": ["pkg-alpha"], "secondary": ["pkg-alpha"]},
        )

        with pytest.raises(ValueError) as exc_info:
            aggregate_symlinks(["primary", "secondary"], tmp_path)

        error_text = str(exc_info.value)
        assert "pkg-alpha" in error_text, (
            f"ValueError message must name the colliding package 'pkg-alpha'; got: {error_text!r}"
        )

    def test_collision_error_names_both_contributing_sources(self, tmp_path: pathlib.Path) -> None:
        """The ValueError message names both sources involved in the collision.

        Both the first-to-register source and the colliding source must appear
        in the error message for clear diagnosis.
        """
        _make_source_packages(
            tmp_path,
            {"primary": ["pkg-alpha"], "secondary": ["pkg-alpha"]},
        )

        with pytest.raises(ValueError) as exc_info:
            aggregate_symlinks(["primary", "secondary"], tmp_path)

        error_text = str(exc_info.value)
        assert "primary" in error_text, f"ValueError message must name first source 'primary'; got: {error_text!r}"
        assert "secondary" in error_text, (
            f"ValueError message must name colliding source 'secondary'; got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "colliding_pkg",
        ["pkg-alpha", "pkg-bravo", "my-custom-package"],
    )
    def test_collision_detected_for_various_package_names(
        self,
        tmp_path: pathlib.Path,
        colliding_pkg: str,
    ) -> None:
        """Collision detection works regardless of the colliding package name.

        Any package name shared between two sources triggers ValueError with
        the package name in the message.
        """
        _make_source_packages(
            tmp_path,
            {"aaa": [colliding_pkg], "bbb": [colliding_pkg]},
        )

        with pytest.raises(ValueError) as exc_info:
            aggregate_symlinks(["aaa", "bbb"], tmp_path)

        error_text = str(exc_info.value)
        assert colliding_pkg in error_text, (
            f"ValueError must name the colliding package {colliding_pkg!r}; got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: source priority order is respected
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSourcePriorityOrder:
    """AC-TEST-003: source priority order is respected.

    Verifies that aggregate_symlinks() processes sources in the order they
    are provided in the source_names list. The first source to declare a
    package name wins; a second source with the same name raises ValueError.
    """

    def test_first_source_in_list_is_processed_first(self, tmp_path: pathlib.Path) -> None:
        """Sources are processed in the order given to aggregate_symlinks.

        When source_names=['alpha','bravo'], alpha packages are registered
        first. The return dict maps the package to 'alpha'.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-only-alpha"], "bravo": ["pkg-only-bravo"]})

        owners = aggregate_symlinks(["alpha", "bravo"], tmp_path)

        assert owners.get("pkg-only-alpha") == "alpha", (
            f"pkg-only-alpha must be owned by 'alpha'; got {owners.get('pkg-only-alpha')!r}"
        )

    def test_collision_attribution_matches_input_order(self, tmp_path: pathlib.Path) -> None:
        """The first source in the list is named as the original owner in the collision error.

        When alpha comes before bravo and both have pkg-alpha, the error message
        must name alpha as the first owner and bravo as the collider.
        """
        _make_source_packages(
            tmp_path,
            {"alpha": ["pkg-alpha"], "bravo": ["pkg-alpha"]},
        )

        with pytest.raises(ValueError) as exc_info:
            aggregate_symlinks(["alpha", "bravo"], tmp_path)

        error_text = str(exc_info.value)
        assert "alpha" in error_text, f"Error must mention 'alpha' as original owner; got: {error_text!r}"
        assert "bravo" in error_text, f"Error must mention 'bravo' as the collider; got: {error_text!r}"
        owners_section = error_text[error_text.index("provided by both ") :]
        assert owners_section.index("alpha") < owners_section.index("bravo"), (
            f"'alpha' must appear before 'bravo' in owners section (alpha is first owner); got: {error_text!r}"
        )

    def test_reverse_order_flips_collision_attribution(self, tmp_path: pathlib.Path) -> None:
        """Reversing the source order flips which source is named first in the error.

        When bravo comes before alpha and both have pkg-alpha, the error message
        must name bravo as original owner (registered first) and alpha as collider.
        """
        _make_source_packages(
            tmp_path,
            {"alpha": ["pkg-alpha"], "bravo": ["pkg-alpha"]},
        )

        with pytest.raises(ValueError) as exc_info:
            aggregate_symlinks(["bravo", "alpha"], tmp_path)

        error_text = str(exc_info.value)
        assert "bravo" in error_text, f"Error must mention 'bravo' as original owner; got: {error_text!r}"
        assert "alpha" in error_text, f"Error must mention 'alpha' as the collider; got: {error_text!r}"
        owners_section = error_text[error_text.index("provided by both ") :]
        assert owners_section.index("bravo") < owners_section.index("alpha"), (
            f"'bravo' must appear before 'alpha' in owners section (bravo is first owner); got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: aggregation is stable across re-runs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAggregationStabilityAcrossReRuns:
    """AC-TEST-004: aggregation is stable across re-runs.

    Verifies that calling aggregate_symlinks() multiple times on the same
    directory is idempotent: symlinks are recreated correctly, the package
    count does not change, and no errors are raised on repeated runs.
    """

    def test_second_run_recreates_symlinks_without_error(self, tmp_path: pathlib.Path) -> None:
        """Running aggregate_symlinks() twice does not raise on the second run.

        The second call must succeed even though the symlinks from the first
        call already exist in .packages/.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        aggregate_symlinks(["alpha", "bravo"], tmp_path)
        # Second run must not raise
        aggregate_symlinks(["alpha", "bravo"], tmp_path)

    def test_symlinks_are_valid_after_second_run(self, tmp_path: pathlib.Path) -> None:
        """Symlinks created by the second run resolve to valid targets.

        After two calls to aggregate_symlinks(), all symlinks in .packages/
        must still resolve to existing package directories.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        aggregate_symlinks(["alpha", "bravo"], tmp_path)
        aggregate_symlinks(["alpha", "bravo"], tmp_path)

        for pkg_name in ("pkg-alpha", "pkg-bravo"):
            link = tmp_path / ".packages" / pkg_name
            assert link.is_symlink(), f"{pkg_name} must remain a symlink after second run; found at {link}"
            assert link.resolve().exists(), f"{pkg_name} symlink must resolve to an existing path; got {link.resolve()}"

    def test_package_count_unchanged_after_multiple_installs(self, tmp_path: pathlib.Path) -> None:
        """Running aggregate_symlinks() multiple times does not change the package count.

        After _NUM_STABILITY_RUNS calls, the return dict must still contain
        exactly as many entries as there are packages across all sources.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-a1", "pkg-a2"], "bravo": ["pkg-b1"]})

        owners: dict[str, str] = {}
        for _ in range(_NUM_STABILITY_RUNS):
            owners = aggregate_symlinks(["alpha", "bravo"], tmp_path)

        assert len(owners) == 3, (
            f"Package count must remain 3 after {_NUM_STABILITY_RUNS} runs; got {len(owners)}: {owners}"
        )

    def test_return_dict_is_consistent_across_runs(self, tmp_path: pathlib.Path) -> None:
        """aggregate_symlinks returns the same dict mapping on every call.

        The package-to-source mapping must be deterministic and identical
        across repeated invocations.
        """
        _make_source_packages(tmp_path, {"alpha": ["pkg-alpha"], "bravo": ["pkg-bravo"]})

        first = aggregate_symlinks(["alpha", "bravo"], tmp_path)
        second = aggregate_symlinks(["alpha", "bravo"], tmp_path)

        assert first == second, (
            f"aggregate_symlinks must return identical dict on every run; first={first}, second={second}"
        )
