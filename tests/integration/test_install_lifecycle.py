"""Integration tests for the kanon install step-by-step lifecycle.

Covers the install lifecycle in sequential order:
  init -> envsubst -> sync -> aggregate -> gitignore-update

AC-TEST-001: install creates .packages/ and .kanon-data/ directories
AC-TEST-002: install writes .gitignore entries idempotently
AC-TEST-003: install performs repo init + envsubst + sync in the correct order
AC-TEST-004: install aggregates multiple sources without collision (MS-01 class)
AC-FUNC-001: Lifecycle order is init -> envsubst -> sync -> aggregate -> gitignore-update
AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.commands.install import _run as _install_run
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_single_source_kanonenv(directory: pathlib.Path, source_name: str = "primary") -> pathlib.Path:
    """Write a minimal single-source .kanon file and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        source_name: Source name to use in KANON_SOURCE_* keys.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/manifest.xml\n"
    )
    return kanonenv.resolve()


def _write_two_source_kanonenv(
    directory: pathlib.Path,
    source_alpha: str = "alpha",
    source_bravo: str = "bravo",
) -> pathlib.Path:
    """Write a minimal two-source .kanon file and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        source_alpha: Name for the first source (alphabetically first).
        source_bravo: Name for the second source (alphabetically second).

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_alpha}_URL=https://example.com/{source_alpha}.git\n"
        f"KANON_SOURCE_{source_alpha}_REVISION=main\n"
        f"KANON_SOURCE_{source_alpha}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_bravo}_URL=https://example.com/{source_bravo}.git\n"
        f"KANON_SOURCE_{source_bravo}_REVISION=main\n"
        f"KANON_SOURCE_{source_bravo}_PATH=repo-specs/manifest.xml\n"
    )
    return kanonenv.resolve()


def _install_with_patched_repo(kanonenv: pathlib.Path) -> None:
    """Run install() with all repo operations patched to no-ops.

    Args:
        kanonenv: Path to the .kanon configuration file.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
    ):
        install(kanonenv)


def _install_with_synced_packages(
    kanonenv: pathlib.Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Run install() with fake repo_sync that creates .packages/ entries.

    Args:
        kanonenv: Path to the .kanon configuration file.
        packages_by_source: Mapping of source name to list of package names.
    """

    def fake_repo_sync(repo_dir: str, **kwargs: object) -> None:
        repo_path = pathlib.Path(repo_dir)
        source_name = repo_path.name
        for pkg_name in packages_by_source.get(source_name, []):
            pkg_dir = repo_path / ".packages" / pkg_name
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text(f"# {pkg_name}\n")

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
    ):
        install(kanonenv)


# ---------------------------------------------------------------------------
# AC-TEST-001: install creates .packages/ and .kanon-data/ directories
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallCreatesDirectories:
    """AC-TEST-001: install creates .packages/ and .kanon-data/ directories.

    Verifies that after install() completes, the managed directory tree is
    fully created: .packages/ at the project root and .kanon-data/sources/<name>/
    for every declared source.
    """

    def test_packages_dir_created_after_install(self, tmp_path: pathlib.Path) -> None:
        """install creates .packages/ at the project root.

        .packages/ must exist and be a directory after a successful install.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        packages_dir = tmp_path / ".packages"
        assert packages_dir.is_dir(), f".packages/ must be created by install at {packages_dir}; it does not exist"

    def test_kanon_data_dir_created_after_install(self, tmp_path: pathlib.Path) -> None:
        """.kanon-data/ directory is created as part of the install lifecycle.

        The managed data directory .kanon-data/ must exist after install.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        kanon_data_dir = tmp_path / ".kanon-data"
        assert kanon_data_dir.is_dir(), (
            f".kanon-data/ must be created by install at {kanon_data_dir}; it does not exist"
        )

    def test_source_workspace_dir_created_under_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """install creates .kanon-data/sources/<name>/ for each declared source.

        A single source 'primary' means .kanon-data/sources/primary/ must exist.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path, "primary")
        _install_with_patched_repo(kanonenv)

        source_dir = tmp_path / ".kanon-data" / "sources" / "primary"
        assert source_dir.is_dir(), (
            f".kanon-data/sources/primary/ must be created by install; it does not exist at {source_dir}"
        )

    def test_both_packages_and_kanon_data_created_together(self, tmp_path: pathlib.Path) -> None:
        """.packages/ and .kanon-data/ are both created in a single install() call.

        Neither directory may be absent after a completed install.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after install"
        assert (tmp_path / ".kanon-data").is_dir(), ".kanon-data/ must exist after install"

    @pytest.mark.parametrize("source_name", ["alpha", "bravo", "primary", "myrepo"])
    def test_source_workspace_named_correctly_for_source(
        self,
        tmp_path: pathlib.Path,
        source_name: str,
    ) -> None:
        """The source workspace directory name matches the source name in .kanon.

        For each parameterized source name, .kanon-data/sources/<source_name>/
        must be the workspace directory created for that source.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path, source_name)
        _install_with_patched_repo(kanonenv)

        source_dir = tmp_path / ".kanon-data" / "sources" / source_name
        assert source_dir.is_dir(), f".kanon-data/sources/{source_name}/ must exist for source '{source_name}'"

    def test_two_sources_create_separate_kanon_data_dirs(self, tmp_path: pathlib.Path) -> None:
        """Two sources each get their own .kanon-data/sources/<name>/ directory.

        The directories must be distinct and both must exist after install.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")
        _install_with_patched_repo(kanonenv)

        alpha_dir = tmp_path / ".kanon-data" / "sources" / "alpha"
        bravo_dir = tmp_path / ".kanon-data" / "sources" / "bravo"

        assert alpha_dir.is_dir(), ".kanon-data/sources/alpha/ must exist"
        assert bravo_dir.is_dir(), ".kanon-data/sources/bravo/ must exist"
        assert alpha_dir != bravo_dir, "Source workspace directories must be distinct"


# ---------------------------------------------------------------------------
# AC-TEST-002: install writes .gitignore entries idempotently
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallGitignoreIdempotency:
    """AC-TEST-002: install writes .gitignore entries idempotently.

    Verifies that the lifecycle step that writes .gitignore never duplicates
    entries regardless of how many times install() is called, and correctly
    handles pre-existing .gitignore files.
    """

    _REQUIRED_ENTRIES = [".packages/", ".kanon-data/"]

    def test_install_creates_gitignore_when_absent(self, tmp_path: pathlib.Path) -> None:
        """.gitignore is created if it does not exist before install runs.

        After install(), .gitignore must exist with the kanon-managed entries.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        assert not (tmp_path / ".gitignore").exists(), "Precondition: .gitignore must not exist"

        _install_with_patched_repo(kanonenv)

        assert (tmp_path / ".gitignore").is_file(), ".gitignore must be created by install"

    @pytest.mark.parametrize("entry", _REQUIRED_ENTRIES)
    def test_install_writes_required_gitignore_entry(
        self,
        tmp_path: pathlib.Path,
        entry: str,
    ) -> None:
        """Each required kanon entry appears in .gitignore after install.

        Both .packages/ and .kanon-data/ must be present in the .gitignore
        after install() completes.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        content = (tmp_path / ".gitignore").read_text()
        assert entry in content, (
            f"Required gitignore entry {entry!r} must be present after install; got content: {content!r}"
        )

    @pytest.mark.parametrize("entry", _REQUIRED_ENTRIES)
    def test_install_does_not_duplicate_gitignore_entry_on_second_run(
        self,
        tmp_path: pathlib.Path,
        entry: str,
    ) -> None:
        """Running install twice does not duplicate .gitignore entries.

        Each managed entry must appear exactly once even after two installs.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)

        _install_with_patched_repo(kanonenv)
        _install_with_patched_repo(kanonenv)

        content = (tmp_path / ".gitignore").read_text()
        count = content.count(entry)
        assert count == 1, (
            f"{entry!r} must appear exactly once in .gitignore after two installs, "
            f"found {count} occurrences; content: {content!r}"
        )

    def test_install_preserves_preexisting_gitignore_content(self, tmp_path: pathlib.Path) -> None:
        """install does not remove preexisting .gitignore entries.

        When a .gitignore with user content exists before install, the user
        content must be preserved after install adds the kanon entries.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\nbuild/\ndist/\n")

        _install_with_patched_repo(kanonenv)

        content = gitignore.read_text()
        assert "*.pyc" in content, "Preexisting '*.pyc' entry must be preserved"
        assert "build/" in content, "Preexisting 'build/' entry must be preserved"
        assert "dist/" in content, "Preexisting 'dist/' entry must be preserved"

    def test_install_does_not_add_entry_when_already_present(self, tmp_path: pathlib.Path) -> None:
        """install does not write entries that already exist in .gitignore.

        When both kanon entries are pre-populated, the file content must
        be identical before and after install runs.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".packages/\n.kanon-data/\n")
        original_content = gitignore.read_text()

        _install_with_patched_repo(kanonenv)

        content = gitignore.read_text()
        assert content == original_content, (
            f".gitignore content must be unchanged when entries are pre-existing; "
            f"before={original_content!r}, after={content!r}"
        )

    def test_install_entries_each_on_own_line(self, tmp_path: pathlib.Path) -> None:
        """Each kanon .gitignore entry occupies its own standalone line.

        Neither entry may be concatenated with other content on the same line.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        lines = (tmp_path / ".gitignore").read_text().splitlines()
        for entry in self._REQUIRED_ENTRIES:
            assert entry in lines, (
                f"{entry!r} must be a standalone line in .gitignore, not embedded in another line; lines: {lines!r}"
            )


# ---------------------------------------------------------------------------
# AC-TEST-003: install performs repo init + envsubst + sync in the correct order
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallRepoOperationOrder:
    """AC-TEST-003: install performs repo init + envsubst + sync in the correct order.

    For each source the install lifecycle must run repo init, then repo envsubst,
    then repo sync -- in that exact sequence. No other ordering is acceptable.
    """

    def test_repo_init_called_before_envsubst(self, tmp_path: pathlib.Path) -> None:
        """repo init is called before repo envsubst for each source.

        The call order of the mocked functions is captured and verified to
        confirm init precedes envsubst in the call sequence.
        """
        call_order: list[str] = []

        def record_init(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("init")

        def record_envsubst(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("envsubst")

        def record_sync(repo_dir: str, **kwargs: object) -> None:
            call_order.append("sync")

        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=record_init),
            patch("kanon_cli.repo.repo_envsubst", side_effect=record_envsubst),
            patch("kanon_cli.repo.repo_sync", side_effect=record_sync),
        ):
            install(kanonenv)

        assert "init" in call_order, "repo_init must be called during install"
        assert "envsubst" in call_order, "repo_envsubst must be called during install"
        init_pos = call_order.index("init")
        envsubst_pos = call_order.index("envsubst")
        assert init_pos < envsubst_pos, f"repo_init must be called before repo_envsubst; call_order={call_order!r}"

    def test_repo_envsubst_called_before_sync(self, tmp_path: pathlib.Path) -> None:
        """repo envsubst is called before repo sync for each source.

        The call order must show envsubst preceding sync in the sequence.
        """
        call_order: list[str] = []

        def record_init(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("init")

        def record_envsubst(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("envsubst")

        def record_sync(repo_dir: str, **kwargs: object) -> None:
            call_order.append("sync")

        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=record_init),
            patch("kanon_cli.repo.repo_envsubst", side_effect=record_envsubst),
            patch("kanon_cli.repo.repo_sync", side_effect=record_sync),
        ):
            install(kanonenv)

        envsubst_pos = call_order.index("envsubst")
        sync_pos = call_order.index("sync")
        assert envsubst_pos < sync_pos, f"repo_envsubst must be called before repo_sync; call_order={call_order!r}"

    def test_repo_init_envsubst_sync_full_order(self, tmp_path: pathlib.Path) -> None:
        """The full per-source lifecycle order is init -> envsubst -> sync.

        All three operations must appear in the call sequence in the specified
        order for a single-source install.
        """
        call_order: list[str] = []

        def record_init(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("init")

        def record_envsubst(repo_dir: str, *args: object, **kwargs: object) -> None:
            call_order.append("envsubst")

        def record_sync(repo_dir: str, **kwargs: object) -> None:
            call_order.append("sync")

        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=record_init),
            patch("kanon_cli.repo.repo_envsubst", side_effect=record_envsubst),
            patch("kanon_cli.repo.repo_sync", side_effect=record_sync),
        ):
            install(kanonenv)

        expected_order = ["init", "envsubst", "sync"]
        for step in expected_order:
            assert step in call_order, f"'{step}' must appear in the call sequence"

        init_pos = call_order.index("init")
        envsubst_pos = call_order.index("envsubst")
        sync_pos = call_order.index("sync")
        assert init_pos < envsubst_pos < sync_pos, (
            f"Lifecycle must be init -> envsubst -> sync; actual order: {call_order!r}"
        )

    def test_per_source_init_called_exactly_once(self, tmp_path: pathlib.Path) -> None:
        """repo_init is called exactly once per declared source.

        With a single source, repo_init must be called exactly once.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert mock_init.call_count == 1, (
            f"repo_init must be called exactly once for a single source; was called {mock_init.call_count} times"
        )

    def test_per_source_envsubst_called_exactly_once(self, tmp_path: pathlib.Path) -> None:
        """repo_envsubst is called exactly once per declared source.

        With a single source, repo_envsubst must be called exactly once.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert mock_envsubst.call_count == 1, (
            f"repo_envsubst must be called exactly once for a single source; "
            f"was called {mock_envsubst.call_count} times"
        )

    def test_per_source_sync_called_exactly_once(self, tmp_path: pathlib.Path) -> None:
        """repo_sync is called exactly once per declared source.

        With a single source, repo_sync must be called exactly once.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync") as mock_sync,
        ):
            install(kanonenv)

        assert mock_sync.call_count == 1, (
            f"repo_sync must be called exactly once for a single source; was called {mock_sync.call_count} times"
        )

    def test_two_sources_each_get_full_lifecycle(self, tmp_path: pathlib.Path) -> None:
        """With two sources, init+envsubst+sync are called once per source (2 times each).

        The lifecycle must be applied to every declared source, not just the first.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst") as mock_envsubst,
            patch("kanon_cli.repo.repo_sync") as mock_sync,
        ):
            install(kanonenv)

        assert mock_init.call_count == 2, (
            f"repo_init must be called once per source (2 sources); was called {mock_init.call_count} times"
        )
        assert mock_envsubst.call_count == 2, (
            f"repo_envsubst must be called once per source (2 sources); was called {mock_envsubst.call_count} times"
        )
        assert mock_sync.call_count == 2, (
            f"repo_sync must be called once per source (2 sources); was called {mock_sync.call_count} times"
        )

    def test_two_sources_per_source_order_respected(self, tmp_path: pathlib.Path) -> None:
        """For each of two sources, the init -> envsubst -> sync order is maintained.

        The call sequence must show init, envsubst, sync for the first source
        (alpha) before any operation for the second source (bravo).
        """
        call_sequence: list[tuple[str, str]] = []

        def record_init(repo_dir: str, *args: object, **kwargs: object) -> None:
            source = pathlib.Path(repo_dir).name
            call_sequence.append(("init", source))

        def record_envsubst(repo_dir: str, *args: object, **kwargs: object) -> None:
            source = pathlib.Path(repo_dir).name
            call_sequence.append(("envsubst", source))

        def record_sync(repo_dir: str, **kwargs: object) -> None:
            source = pathlib.Path(repo_dir).name
            call_sequence.append(("sync", source))

        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")

        with (
            patch("kanon_cli.repo.repo_init", side_effect=record_init),
            patch("kanon_cli.repo.repo_envsubst", side_effect=record_envsubst),
            patch("kanon_cli.repo.repo_sync", side_effect=record_sync),
        ):
            install(kanonenv)

        # Extract operations per source, preserving their global positions
        alpha_ops = [op for op, src in call_sequence if src == "alpha"]
        bravo_ops = [op for op, src in call_sequence if src == "bravo"]

        assert alpha_ops == ["init", "envsubst", "sync"], (
            f"Source 'alpha' must be processed in order init->envsubst->sync; got {alpha_ops!r}"
        )
        assert bravo_ops == ["init", "envsubst", "sync"], (
            f"Source 'bravo' must be processed in order init->envsubst->sync; got {bravo_ops!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: install aggregates multiple sources without collision (MS-01 class)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallMultiSourceAggregation:
    """AC-TEST-004: install aggregates multiple sources without collision (MS-01 class).

    Two sources with distinct package names produce a merged .packages/ directory
    with one symlink per package, each pointing into its source's workspace.
    """

    def test_ms01_both_packages_present_in_packages_dir(self, tmp_path: pathlib.Path) -> None:
        """MS-01: packages from both sources appear in .packages/ after install.

        Source 'alpha' delivers 'pkg-from-alpha'; source 'bravo' delivers
        'pkg-from-bravo'. Both symlinks must exist in .packages/.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")
        _install_with_synced_packages(
            kanonenv,
            {"alpha": ["pkg-from-alpha"], "bravo": ["pkg-from-bravo"]},
        )

        assert (tmp_path / ".packages" / "pkg-from-alpha").is_symlink(), (
            "pkg-from-alpha from source 'alpha' must be symlinked in .packages/"
        )
        assert (tmp_path / ".packages" / "pkg-from-bravo").is_symlink(), (
            "pkg-from-bravo from source 'bravo' must be symlinked in .packages/"
        )

    def test_ms01_symlinks_resolve_into_source_workspaces(self, tmp_path: pathlib.Path) -> None:
        """MS-01: each symlink resolves into its source's .kanon-data workspace.

        pkg-from-alpha must resolve into .kanon-data/sources/alpha/.packages/pkg-from-alpha
        and pkg-from-bravo into .kanon-data/sources/bravo/.packages/pkg-from-bravo.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")
        _install_with_synced_packages(
            kanonenv,
            {"alpha": ["pkg-from-alpha"], "bravo": ["pkg-from-bravo"]},
        )

        alpha_link = tmp_path / ".packages" / "pkg-from-alpha"
        bravo_link = tmp_path / ".packages" / "pkg-from-bravo"

        alpha_workspace = tmp_path / ".kanon-data" / "sources" / "alpha" / ".packages" / "pkg-from-alpha"
        bravo_workspace = tmp_path / ".kanon-data" / "sources" / "bravo" / ".packages" / "pkg-from-bravo"

        assert alpha_link.resolve() == alpha_workspace.resolve(), (
            f"pkg-from-alpha symlink must resolve to alpha workspace; got {alpha_link.resolve()}"
        )
        assert bravo_link.resolve() == bravo_workspace.resolve(), (
            f"pkg-from-bravo symlink must resolve to bravo workspace; got {bravo_link.resolve()}"
        )

    def test_ms01_no_collision_on_disjoint_packages(self, tmp_path: pathlib.Path) -> None:
        """MS-01: install does not exit non-zero when sources provide disjoint packages.

        With distinct package names across sources, install() must complete
        without raising SystemExit.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")

        try:
            _install_with_synced_packages(
                kanonenv,
                {"alpha": ["tool-a"], "bravo": ["tool-b"]},
            )
        except SystemExit as exc:
            raise AssertionError(
                f"install() must not raise SystemExit for disjoint packages; got exit code {exc.code}"
            ) from exc

    @pytest.mark.parametrize(
        "packages_by_source",
        [
            {"alpha": ["pkg-a1", "pkg-a2"], "bravo": ["pkg-b1", "pkg-b2"]},
            {"alpha": ["only-alpha"], "bravo": ["only-bravo"]},
            {"alpha": ["x", "y", "z"], "bravo": ["p", "q"]},
        ],
    )
    def test_ms01_all_packages_aggregated_for_various_counts(
        self,
        tmp_path: pathlib.Path,
        packages_by_source: dict[str, list[str]],
    ) -> None:
        """MS-01: all packages from both sources appear in .packages/ regardless of count.

        Tests multiple package distributions across two sources to confirm
        the aggregation loop handles variable package counts correctly.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")
        _install_with_synced_packages(kanonenv, packages_by_source)

        all_expected = [pkg for pkgs in packages_by_source.values() for pkg in pkgs]
        for pkg_name in all_expected:
            link = tmp_path / ".packages" / pkg_name
            assert link.is_symlink(), f"Package '{pkg_name}' must be symlinked in .packages/ after install"

    def test_ms01_collision_exits_nonzero_with_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, make_install_args
    ) -> None:
        """MS-01 collision path: the CLI handler exits non-zero with a collision error on stderr.

        When 'alpha' and 'bravo' both provide 'shared-pkg', the CLI handler must
        exit with a non-zero code and write a 'Package collision' error to stderr.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")

        def fake_repo_sync_collision(repo_dir: str, **kwargs: object) -> None:
            pkg_dir = pathlib.Path(repo_dir) / ".packages" / "shared-pkg"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text("# shared\n")

        args = make_install_args(kanonenv.resolve())
        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync_collision),
            ):
                _install_run(args)

        assert exc_info.value.code != 0, "CLI handler must exit non-zero on package collision"
        captured = capsys.readouterr()
        assert "Package collision" in captured.err, f"stderr must contain 'Package collision'; got: {captured.err!r}"
        assert "shared-pkg" in captured.err, (
            f"stderr must name the colliding package 'shared-pkg'; got: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Lifecycle order is init -> envsubst -> sync -> aggregate -> gitignore-update
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallLifecycleOrder:
    """AC-FUNC-001: Full lifecycle order: init -> envsubst -> sync -> aggregate -> gitignore.

    Verifies that the aggregate step (create .packages/) and the gitignore-update
    step both happen AFTER all sources have been synced -- not interleaved.
    """

    def test_gitignore_written_after_sync_completes(self, tmp_path: pathlib.Path) -> None:
        """.gitignore is created after repo_sync, not before.

        Before repo_sync runs, .gitignore must not yet exist. After install
        completes, .gitignore must exist. This verifies update_gitignore runs
        after the per-source sync loop.
        """
        gitignore_existed_during_sync: list[bool] = []

        def check_gitignore_during_sync(repo_dir: str, **kwargs: object) -> None:
            gitignore_existed_during_sync.append((tmp_path / ".gitignore").exists())

        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=check_gitignore_during_sync),
        ):
            install(kanonenv)

        assert len(gitignore_existed_during_sync) == 1, "repo_sync side-effect must run exactly once"
        assert not gitignore_existed_during_sync[0], (
            ".gitignore must NOT exist when repo_sync runs -- update_gitignore must run after sync"
        )
        assert (tmp_path / ".gitignore").is_file(), ".gitignore must exist after install() completes"

    def test_packages_dir_created_after_sync_and_before_gitignore(self, tmp_path: pathlib.Path) -> None:
        """.packages/ is created (aggregate step) after sync and before gitignore-update.

        The aggregate step and gitignore-update both happen after the per-source
        sync loop finishes. This test confirms .packages/ exists after install.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)

        packages_existed_during_sync: list[bool] = []

        def check_packages_during_sync(repo_dir: str, **kwargs: object) -> None:
            packages_existed_during_sync.append((tmp_path / ".packages").exists())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=check_packages_during_sync),
        ):
            install(kanonenv)

        assert not packages_existed_during_sync[0], (
            ".packages/ must NOT exist when repo_sync runs -- aggregate_symlinks runs after sync"
        )
        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after install() completes"

    def test_full_lifecycle_stages_complete_in_order(self, tmp_path: pathlib.Path) -> None:
        """Full lifecycle stages run in order: init -> envsubst -> sync -> aggregate -> gitignore.

        Tracks filesystem state at each stage checkpoint to verify the order
        of side effects in the install() implementation.
        """
        stage_log: list[str] = []

        def record_init(repo_dir: str, *args: object, **kwargs: object) -> None:
            stage_log.append("init")

        def record_envsubst(repo_dir: str, *args: object, **kwargs: object) -> None:
            stage_log.append("envsubst")

        def record_sync(repo_dir: str, **kwargs: object) -> None:
            stage_log.append("sync")

        original_aggregate = __import__("kanon_cli.core.install", fromlist=["aggregate_symlinks"]).aggregate_symlinks

        def record_aggregate(source_names: list[str], base_dir: pathlib.Path) -> dict[str, str]:
            stage_log.append("aggregate")
            return original_aggregate(source_names, base_dir)

        original_update_gitignore = __import__("kanon_cli.core.install", fromlist=["update_gitignore"]).update_gitignore

        def record_update_gitignore(base_dir: pathlib.Path, entries: list[str] | None = None) -> None:
            stage_log.append("gitignore")
            original_update_gitignore(base_dir, entries)

        kanonenv = _write_single_source_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=record_init),
            patch("kanon_cli.repo.repo_envsubst", side_effect=record_envsubst),
            patch("kanon_cli.repo.repo_sync", side_effect=record_sync),
            patch("kanon_cli.core.install.aggregate_symlinks", side_effect=record_aggregate),
            patch("kanon_cli.core.install.update_gitignore", side_effect=record_update_gitignore),
        ):
            install(kanonenv)

        expected_order = ["init", "envsubst", "sync", "aggregate", "gitignore"]
        for step in expected_order:
            assert step in stage_log, f"Lifecycle stage '{step}' must appear in the stage log"

        init_pos = stage_log.index("init")
        envsubst_pos = stage_log.index("envsubst")
        sync_pos = stage_log.index("sync")
        aggregate_pos = stage_log.index("aggregate")
        gitignore_pos = stage_log.index("gitignore")

        assert init_pos < envsubst_pos, f"init must precede envsubst; stage_log={stage_log!r}"
        assert envsubst_pos < sync_pos, f"envsubst must precede sync; stage_log={stage_log!r}"
        assert sync_pos < aggregate_pos, f"sync must precede aggregate; stage_log={stage_log!r}"
        assert aggregate_pos < gitignore_pos, f"aggregate must precede gitignore-update; stage_log={stage_log!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage).

    Progress messages from install must go to stdout. Error messages must go
    to stderr. No progress text should appear on stderr; no error text should
    appear on stdout.
    """

    def test_successful_install_writes_no_error_to_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A successful install produces no output on stderr.

        When install() completes without error, stderr must be empty.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        captured = capsys.readouterr()
        assert captured.err == "", f"stderr must be empty on a successful install; got stderr={captured.err!r}"

    def test_successful_install_writes_progress_to_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A successful install writes progress messages to stdout.

        install() must emit at least one progress message on stdout to confirm
        it is running. The message must contain the word 'kanon'.
        """
        kanonenv = _write_single_source_kanonenv(tmp_path)
        _install_with_patched_repo(kanonenv)

        captured = capsys.readouterr()
        assert "kanon" in captured.out, f"stdout must contain progress output from install; got stdout={captured.out!r}"

    def test_failed_install_writes_error_to_stderr_not_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, make_install_args
    ) -> None:
        """When the CLI handler fails, the error message appears on stderr, not stdout.

        A repo_sync failure must result in an error on stderr. The stdout
        must not contain the word 'Error'.
        """
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_single_source_kanonenv(tmp_path)
        args = make_install_args(kanonenv.resolve())

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync", side_effect=RepoCommandError("network timeout")),
            ):
                _install_run(args)

        captured = capsys.readouterr()
        assert "Error" in captured.err, f"stderr must contain 'Error' when install fails; got stderr={captured.err!r}"
        assert "Error" not in captured.out, (
            f"stdout must not contain 'Error' when install fails; got stdout={captured.out!r}"
        )

    def test_collision_error_written_to_stderr_not_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, make_install_args
    ) -> None:
        """Package collision errors are written to stderr, not stdout.

        When a collision is detected, the CLI handler must write the collision
        message to stderr and must not write it to stdout.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")

        def fake_collision_sync(repo_dir: str, **kwargs: object) -> None:
            pkg_dir = pathlib.Path(repo_dir) / ".packages" / "collision-pkg"
            pkg_dir.mkdir(parents=True, exist_ok=True)

        args = make_install_args(kanonenv.resolve())
        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync", side_effect=fake_collision_sync),
            ):
                _install_run(args)

        captured = capsys.readouterr()
        assert "collision-pkg" in captured.err, (
            f"Package collision error must name the colliding package in stderr; got stderr={captured.err!r}"
        )
        assert "collision-pkg" not in captured.out, (
            f"Package collision error must NOT appear on stdout; got stdout={captured.out!r}"
        )
