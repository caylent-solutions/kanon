"""Full lifecycle integration tests for kanon install/clean scenarios (10 tests).

Covers end-to-end kanon lifecycle scenarios:
  - Install -> clean roundtrip (clean state after full cycle)
  - Multi-source installation (repo + marketplace sources)
  - Source collision detection (duplicate project names across sources)
  - Auto-discovery workflow (detect manifests, install, verify)
  - Recovery from partial failure (failed sync mid-install)
  - Re-install over existing installation (idempotency)
  - Filesystem state at each lifecycle stage
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Shared lifecycle helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: Path, content: str) -> Path:
    """Write a .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


def _single_source_content(name: str = "primary") -> str:
    """Return minimal .kanon content for a single source."""
    return (
        f"KANON_SOURCE_{name}_URL=https://example.com/{name}.git\n"
        f"KANON_SOURCE_{name}_REVISION=main\n"
        f"KANON_SOURCE_{name}_PATH=meta.xml\n"
    )


def _two_source_content() -> str:
    """Return .kanon content for two independent sources."""
    return (
        "KANON_SOURCE_repo_URL=https://example.com/repo.git\n"
        "KANON_SOURCE_repo_REVISION=main\n"
        "KANON_SOURCE_repo_PATH=meta.xml\n"
        "KANON_SOURCE_marketplace_URL=https://example.com/marketplace.git\n"
        "KANON_SOURCE_marketplace_REVISION=main\n"
        "KANON_SOURCE_marketplace_PATH=marketplace.xml\n"
    )


def _install_with_synced_packages(kanonenv: Path, packages_by_source: dict[str, list[str]]) -> None:
    """Run install() with a fake repo_sync that creates .packages/ entries.

    Args:
        kanonenv: Path to the .kanon configuration file.
        packages_by_source: Mapping of source name to list of package names to create.
    """

    def fake_repo_sync(repo_dir: str, **kwargs) -> None:
        repo_path = Path(repo_dir)
        pkg_dir = repo_path / ".packages"
        # Determine source name from repo_dir path: .kanon-data/sources/<name>
        source_name = repo_path.name
        for pkg_name in packages_by_source.get(source_name, []):
            tool_dir = pkg_dir / pkg_name
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / f"{pkg_name}.sh").write_text(f"#!/bin/sh\necho {pkg_name}\n")

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
    ):
        install(kanonenv)


# ---------------------------------------------------------------------------
# AC-FUNC-003: Install -> clean roundtrip (clean state after full cycle)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallCleanRoundtripLifecycle:
    """Verify that a full install -> clean roundtrip restores the project to a clean state."""

    def test_roundtrip_filesystem_state_is_clean_after_cycle(self, tmp_path: Path) -> None:
        """After install and clean, no repo-managed artifacts remain on disk.

        Filesystem state after roundtrip:
          - .kanon: present (config file, not managed by repo)
          - .packages/: absent
          - .kanon-data/: absent
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        _install_with_synced_packages(kanonenv, {"primary": ["tool-x"]})

        # After install: managed artifacts exist
        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after install"
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist after install"
        )

        clean(kanonenv)

        # After clean: all managed artifacts removed, config preserved
        assert not (tmp_path / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (tmp_path / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"
        assert kanonenv.is_file(), ".kanon config file must survive the full roundtrip"

    def test_roundtrip_gitignore_survives_clean(self, tmp_path: Path) -> None:
        """The .gitignore written by install is preserved through clean.

        install() creates .gitignore with managed entries; clean() must not remove it.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert (tmp_path / ".gitignore").is_file(), ".gitignore must exist after install"

        clean(kanonenv)

        assert (tmp_path / ".gitignore").is_file(), ".gitignore must survive clean"
        gitignore_content = (tmp_path / ".gitignore").read_text()
        assert ".packages/" in gitignore_content
        assert ".kanon-data/" in gitignore_content


# ---------------------------------------------------------------------------
# AC-FUNC-004: Multi-source installation (repo + marketplace sources)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMultiSourceInstallLifecycle:
    """Verify that install handles multiple sources producing disjoint package sets."""

    def test_multi_source_creates_separate_source_dirs(self, tmp_path: Path) -> None:
        """Each source gets its own isolated directory under .kanon-data/sources/.

        Verifies both directories are created and non-overlapping.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert (tmp_path / ".kanon-data" / "sources" / "marketplace").is_dir(), (
            ".kanon-data/sources/marketplace/ must be created for the marketplace source"
        )
        assert (tmp_path / ".kanon-data" / "sources" / "repo").is_dir(), (
            ".kanon-data/sources/repo/ must be created for the repo source"
        )

    def test_multi_source_repo_init_called_once_per_source(self, tmp_path: Path) -> None:
        """repo_init is invoked exactly once for each declared source.

        With two sources (marketplace, repo), repo_init must be called twice.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content())

        with (
            patch("kanon_cli.repo.repo_init") as mock_init,
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert mock_init.call_count == 2, (
            f"repo_init must be called once per source (2 sources), but was called {mock_init.call_count} times"
        )

    def test_multi_source_packages_aggregated_into_packages_dir(self, tmp_path: Path) -> None:
        """Packages from all sources are symlinked into the top-level .packages/.

        Each source contributes a unique package; both appear in .packages/.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content())

        _install_with_synced_packages(
            kanonenv,
            {"marketplace": ["plugin-a"], "repo": ["tool-b"]},
        )

        assert (tmp_path / ".packages" / "plugin-a").is_symlink(), (
            "plugin-a from marketplace source must be symlinked in .packages/"
        )
        assert (tmp_path / ".packages" / "tool-b").is_symlink(), (
            "tool-b from repo source must be symlinked in .packages/"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-005: Source collision detection
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSourceCollisionDetection:
    """Verify that install exits non-zero when two sources produce the same package name."""

    def test_collision_exits_nonzero_with_error(self, tmp_path: Path) -> None:
        """When two sources declare a package with the same name, install must exit(1).

        Filesystem state at exit: source dirs created, .packages/ partially populated.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content())

        # Both sources produce a package named "shared-tool" -- this is a collision
        def fake_repo_sync_collision(repo_dir: str, **kwargs) -> None:
            pkg_dir = Path(repo_dir) / ".packages" / "shared-tool"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "tool.sh").write_text("#!/bin/sh\necho shared\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync_collision),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install(kanonenv)

        assert exc_info.value.code != 0, "install() must exit with a non-zero code when a package collision is detected"


# ---------------------------------------------------------------------------
# AC-FUNC-006: Auto-discovery workflow
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAutoDiscoveryWorkflow:
    """Verify the auto-discovery -> install -> verify workflow."""

    def test_auto_discovery_finds_kanonenv_and_install_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discover .kanon via find_kanonenv, pass it to install(), verify artifacts.

        Workflow:
          1. Write .kanon in tmp_path
          2. Set cwd to a subdirectory
          3. find_kanonenv() resolves to the parent's .kanon
          4. install() creates .kanon-data/ and .gitignore in the .kanon parent
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())
        subdir = tmp_path / "workspace" / "project"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        discovered = find_kanonenv(start_dir=subdir)

        assert discovered == kanonenv.resolve(), (
            f"find_kanonenv must discover {kanonenv.resolve()}, but found {discovered}"
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(discovered)

        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            "install() must create .kanon-data/sources/primary/ relative to .kanon parent"
        )
        assert (tmp_path / ".gitignore").is_file(), "install() must create .gitignore relative to .kanon parent"


# ---------------------------------------------------------------------------
# AC-FUNC-007: Recovery from partial failure (failed sync mid-install)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartialFailureRecovery:
    """Verify that a failed sync mid-install produces a non-zero exit and clean is re-runnable."""

    def test_failed_sync_exits_nonzero(self, tmp_path: Path) -> None:
        """When repo_sync raises RepoCommandError, install exits non-zero immediately.

        The first source's directory is created before sync fails.
        """
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=RepoCommandError("sync failed: network error")),
        ):
            with pytest.raises(SystemExit) as exc_info:
                install(kanonenv)

        assert exc_info.value.code != 0, "install() must exit non-zero when repo_sync fails"

    def test_clean_succeeds_after_partial_install(self, tmp_path: Path) -> None:
        """clean() can remove partial install artifacts left by a failed install.

        After a failed install, source dirs may exist but packages may be incomplete.
        clean() must not raise and must remove all managed dirs.
        """
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=RepoCommandError("sync failed: timeout")),
        ):
            with pytest.raises(SystemExit):
                install(kanonenv)

        # Source dir was created by create_source_dirs before sync failed
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            "Source dir must exist after partial install (created before failed sync)"
        )

        # clean() must succeed even on partial artifacts
        clean(kanonenv)

        assert not (tmp_path / ".kanon-data").exists(), "clean() must remove .kanon-data/ even after a partial install"
        assert not (tmp_path / ".packages").exists(), "clean() must remove .packages/ even after a partial install"


# ---------------------------------------------------------------------------
# AC-FUNC-008: Re-install over existing installation (idempotency)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReinstallIdempotency:
    """Verify that running install twice produces the same final state as running it once."""

    def test_reinstall_over_existing_does_not_duplicate_packages(self, tmp_path: Path) -> None:
        """Running install twice over an existing installation must not duplicate symlinks.

        After the second install, .packages/ must contain exactly the same entries
        as after the first install -- no duplicates.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        _install_with_synced_packages(kanonenv, {"primary": ["tool-alpha", "tool-beta"]})
        first_pkg_names = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        _install_with_synced_packages(kanonenv, {"primary": ["tool-alpha", "tool-beta"]})
        second_pkg_names = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        assert first_pkg_names == second_pkg_names, (
            f"Re-installing must not change .packages/ contents: first={first_pkg_names}, second={second_pkg_names}"
        )

    def test_reinstall_gitignore_not_duplicated(self, tmp_path: Path) -> None:
        """Running install twice must not duplicate .gitignore entries.

        The .gitignore file must contain each managed entry exactly once,
        regardless of how many times install is run.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)
            install(kanonenv)

        gitignore_content = (tmp_path / ".gitignore").read_text()
        assert gitignore_content.count(".packages/") == 1, (
            ".packages/ must appear exactly once in .gitignore after two installs"
        )
        assert gitignore_content.count(".kanon-data/") == 1, (
            ".kanon-data/ must appear exactly once in .gitignore after two installs"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-009: Filesystem state at each lifecycle stage
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFilesystemStateAtLifecycleStages:
    """Verify the exact filesystem state at each kanon lifecycle stage."""

    def test_filesystem_state_after_install_stage(self, tmp_path: Path) -> None:
        """After install completes, the expected filesystem artifacts must be present.

        Required artifacts:
          - .kanon: config file (pre-existing, untouched)
          - .kanon-data/sources/<name>/: source workspace directories
          - .packages/: aggregated package symlinks directory
          - .gitignore: contains .packages/ and .kanon-data/ entries
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())

        _install_with_synced_packages(kanonenv, {"primary": ["some-tool"]})

        assert kanonenv.is_file(), ".kanon config must still exist after install"
        source_dir = tmp_path / ".kanon-data" / "sources" / "primary"
        assert source_dir.is_dir(), ".kanon-data/sources/primary/ must exist after install"
        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after install"
        assert (tmp_path / ".gitignore").is_file(), ".gitignore must exist after install"
        assert (tmp_path / ".packages" / "some-tool").is_symlink(), (
            ".packages/some-tool must be a symlink after install"
        )

    def test_filesystem_state_during_multi_source_install(self, tmp_path: Path) -> None:
        """After multi-source install, both source workspaces and all packages are present.

        With sources 'marketplace' and 'repo', each producing one package:
          - .kanon-data/sources/marketplace/ exists
          - .kanon-data/sources/repo/ exists
          - .packages/plugin-mp is a symlink from marketplace
          - .packages/tool-repo is a symlink from repo
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content())

        _install_with_synced_packages(
            kanonenv,
            {"marketplace": ["plugin-mp"], "repo": ["tool-repo"]},
        )

        assert (tmp_path / ".kanon-data" / "sources" / "marketplace").is_dir()
        assert (tmp_path / ".kanon-data" / "sources" / "repo").is_dir()
        assert (tmp_path / ".packages" / "plugin-mp").is_symlink()
        assert (tmp_path / ".packages" / "tool-repo").is_symlink()

    def test_filesystem_state_after_clean_stage(self, tmp_path: Path) -> None:
        """After clean completes, repo-managed artifacts are absent; config is preserved.

        Expected post-clean state:
          - .kanon: present
          - .packages/: absent
          - .kanon-data/: absent
          - .gitignore: present (written by install, not managed by clean)
          - user-created files: present and unmodified
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content())
        user_script = tmp_path / "build.sh"
        user_script.write_text("#!/bin/sh\necho build\n")

        _install_with_synced_packages(kanonenv, {"primary": ["some-tool"]})
        clean(kanonenv)

        assert kanonenv.is_file(), ".kanon must survive clean"
        assert not (tmp_path / ".packages").exists(), ".packages/ must be absent after clean"
        assert not (tmp_path / ".kanon-data").exists(), ".kanon-data/ must be absent after clean"
        assert (tmp_path / ".gitignore").is_file(), ".gitignore must survive clean"
        assert user_script.is_file(), "user files must survive clean unmodified"
        assert user_script.read_text() == "#!/bin/sh\necho build\n"
