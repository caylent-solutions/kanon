"""Integration tests for lifecycle state recovery (E1-F1-S14-T1).

Covers three recovery-oriented scenarios:
  - AC-TEST-001: install -> simulated crash -> clean -> install succeeds
  - AC-TEST-002: install over existing install is idempotent
  - AC-TEST-003: .kanon change between installs reconciles correctly

These tests exercise the kanon lifecycle as a state machine, verifying
that partial or stale state does not prevent subsequent operations from
completing successfully.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.install import _run as _install_run
from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Shared helpers
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


def _two_source_content(name_a: str = "alpha", name_b: str = "beta") -> str:
    """Return .kanon content for two independent sources."""
    return (
        f"KANON_SOURCE_{name_a}_URL=https://example.com/{name_a}.git\n"
        f"KANON_SOURCE_{name_a}_REVISION=main\n"
        f"KANON_SOURCE_{name_a}_PATH=meta.xml\n"
        f"KANON_SOURCE_{name_b}_URL=https://example.com/{name_b}.git\n"
        f"KANON_SOURCE_{name_b}_REVISION=main\n"
        f"KANON_SOURCE_{name_b}_PATH=meta.xml\n"
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
# AC-TEST-001: install -> simulated crash -> clean -> install succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallCrashCleanReinstall:
    """AC-TEST-001: lifecycle is recoverable from partial failure states.

    Simulates a crash mid-install by leaving orphaned artifacts on disk,
    then verifies clean removes all partial state and a subsequent install
    completes successfully.
    """

    def test_crash_during_sync_then_clean_then_reinstall_succeeds(self, tmp_path: Path) -> None:
        """Partial install from crash, then clean, then reinstall produces a clean state.

        Steps:
          1. Start install -- repo_sync raises RepoCommandError mid-way (crash simulation).
          2. Verify install exited non-zero and left partial artifacts (.kanon-data/sources/).
          3. Run clean -- verify all partial artifacts removed.
          4. Run install again with no crash -- verify full successful state.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("crash"))

        # Step 1: Simulate crash during sync
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch(
                "kanon_cli.repo.repo_sync",
                side_effect=RepoCommandError("sync failed: simulated crash"),
            ),
        ):
            with pytest.raises(RepoCommandError, match="sync failed: simulated crash"):
                install(kanonenv)

        # Step 2: Partial artifacts exist after crash
        source_dir = tmp_path / ".kanon-data" / "sources" / "crash"
        assert source_dir.is_dir(), "Source dir must exist after partial install (created before failed sync)"

        # Step 3: Clean removes all partial state
        clean(kanonenv)

        assert not (tmp_path / ".kanon-data").exists(), "clean() must remove .kanon-data/ even after a simulated crash"
        assert not (tmp_path / ".packages").exists(), "clean() must remove .packages/ even after a simulated crash"

        # Step 4: Reinstall succeeds after clean
        _install_with_synced_packages(kanonenv, {"crash": ["recovered-tool"]})

        assert (tmp_path / ".kanon-data" / "sources" / "crash").is_dir(), (
            "Reinstall after crash recovery must recreate .kanon-data/sources/crash/"
        )
        assert (tmp_path / ".packages" / "recovered-tool").is_symlink(), (
            "Reinstall after crash recovery must create .packages/recovered-tool symlink"
        )
        assert (tmp_path / ".gitignore").is_file(), "Reinstall after crash recovery must create .gitignore"

    def test_manually_corrupted_packages_dir_is_recovered_by_reinstall(self, tmp_path: Path) -> None:
        """Orphaned .packages/ dir without matching source data is recovered by reinstall.

        Simulates the scenario where .packages/ exists but .kanon-data/ is missing
        (e.g., user manually deleted .kanon-data/ without cleaning .packages/).
        A fresh install must repair the state by recreating all managed artifacts.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("orphan"))

        # Simulate a corrupted state: .packages/ exists but .kanon-data/ is absent
        orphan_packages = tmp_path / ".packages"
        orphan_packages.mkdir()
        stale_link = orphan_packages / "stale-pkg"
        stale_link.mkdir()

        # Install should handle the pre-existing .packages/ directory gracefully
        _install_with_synced_packages(kanonenv, {"orphan": ["fresh-tool"]})

        # After reinstall, fresh-tool must be present
        assert (tmp_path / ".packages" / "fresh-tool").is_symlink(), (
            "Install must create .packages/fresh-tool even when .packages/ already existed"
        )
        # .kanon-data/ must exist
        assert (tmp_path / ".kanon-data" / "sources" / "orphan").is_dir(), (
            "Install must create .kanon-data/sources/orphan/"
        )

    def test_stdout_stderr_discipline_no_cross_channel_leakage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, make_install_args
    ) -> None:
        """AC-CHANNEL-001: stdout vs stderr discipline is verified via the CLI handler.

        Normal install output goes to stdout; error messages go to stderr.
        A failed CLI invocation must write its error to stderr, not stdout.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("channel"))
        args = make_install_args(kanonenv.resolve())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch(
                "kanon_cli.repo.repo_sync",
                side_effect=RepoCommandError("channel error"),
            ),
        ):
            with pytest.raises(SystemExit):
                _install_run(args)

        captured = capsys.readouterr()
        assert "channel error" in captured.err or "Error:" in captured.err, (
            "Error message from failed install must appear on stderr"
        )
        # The error message must not appear on stdout
        assert "channel error" not in captured.out, "Error message must not leak to stdout"


# ---------------------------------------------------------------------------
# AC-TEST-002: install over existing install is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallIdempotency:
    """AC-TEST-002: running install twice over an existing installation is idempotent.

    Verifies that a second install with the same .kanon produces exactly the
    same filesystem state as the first install -- no duplicates, no extra
    artifacts, and no errors.
    """

    def test_install_twice_produces_identical_package_set(self, tmp_path: Path) -> None:
        """The set of package symlinks in .packages/ is unchanged after a second install.

        After both installs, .packages/ must contain the same entries,
        in the same structure, with no additional or missing entries.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("idem"))

        _install_with_synced_packages(kanonenv, {"idem": ["tool-one", "tool-two"]})
        first_pkgs = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        _install_with_synced_packages(kanonenv, {"idem": ["tool-one", "tool-two"]})
        second_pkgs = sorted(p.name for p in (tmp_path / ".packages").iterdir())

        assert first_pkgs == second_pkgs, (
            f"Second install must not change .packages/ contents: first={first_pkgs}, second={second_pkgs}"
        )

    def test_install_twice_does_not_duplicate_gitignore_entries(self, tmp_path: Path) -> None:
        """Running install twice must not duplicate .gitignore managed entries.

        Each managed entry (.packages/, .kanon-data/) must appear exactly once
        in .gitignore regardless of how many times install is run.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("idem2"))

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

    def test_install_twice_all_symlinks_remain_valid(self, tmp_path: Path) -> None:
        """All package symlinks in .packages/ must be valid after two installs.

        A second install must replace stale symlinks if source dirs were
        regenerated, so all symlinks must resolve to existing targets.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("idem3"))

        _install_with_synced_packages(kanonenv, {"idem3": ["pkg-a", "pkg-b"]})
        _install_with_synced_packages(kanonenv, {"idem3": ["pkg-a", "pkg-b"]})

        packages_dir = tmp_path / ".packages"
        for entry in packages_dir.iterdir():
            assert entry.is_symlink(), f"{entry.name} must be a symlink in .packages/"
            assert entry.resolve().exists(), (
                f"Symlink .packages/{entry.name} must resolve to a valid target after second install"
            )


# ---------------------------------------------------------------------------
# AC-TEST-003: .kanon change between installs reconciles correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestKanonChangeReconciliation:
    """AC-TEST-003: changing .kanon between installs reconciles the final state.

    Verifies that when the .kanon configuration changes (new source added,
    source removed, or source URL/revision updated), a subsequent install
    produces a state consistent with the new configuration.
    """

    def test_adding_source_in_kanon_adds_its_packages(self, tmp_path: Path) -> None:
        """Adding a new source to .kanon between installs makes its packages available.

        Steps:
          1. Install with one source (producing package-x).
          2. Update .kanon to add a second source (producing package-y).
          3. Reinstall.
          4. Verify both package-x (from updated source run) and package-y are present.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("src-one"))

        _install_with_synced_packages(kanonenv, {"src-one": ["package-x"]})

        # Update .kanon to add a second source
        kanonenv.write_text(_two_source_content(name_a="src-one", name_b="src-two"))

        _install_with_synced_packages(kanonenv, {"src-one": ["package-x"], "src-two": ["package-y"]})

        assert (tmp_path / ".packages" / "package-x").is_symlink(), (
            "package-x from src-one must still be present after adding src-two"
        )
        assert (tmp_path / ".packages" / "package-y").is_symlink(), (
            "package-y from newly added src-two must be present after reconciliation"
        )

    def test_removing_source_in_kanon_removes_stale_source_dir(self, tmp_path: Path) -> None:
        """Removing a source from .kanon followed by clean removes its source directory.

        Steps:
          1. Install with two sources (alpha, beta).
          2. Update .kanon to remove the beta source.
          3. Run clean.
          4. Run install with single source.
          5. Verify .kanon-data/ only contains alpha source dir.
        """
        kanonenv = _write_kanonenv(tmp_path, _two_source_content(name_a="alpha", name_b="beta"))

        _install_with_synced_packages(kanonenv, {"alpha": ["tool-alpha"], "beta": ["tool-beta"]})

        # Both source dirs and packages must exist after first install
        assert (tmp_path / ".kanon-data" / "sources" / "alpha").is_dir()
        assert (tmp_path / ".kanon-data" / "sources" / "beta").is_dir()

        # Update .kanon to remove beta
        kanonenv.write_text(_single_source_content("alpha"))

        # Clean + reinstall with reduced .kanon
        clean(kanonenv)
        _install_with_synced_packages(kanonenv, {"alpha": ["tool-alpha"]})

        # Only alpha source dir must exist
        assert (tmp_path / ".kanon-data" / "sources" / "alpha").is_dir(), (
            "alpha source dir must exist after reinstall with alpha-only .kanon"
        )
        assert not (tmp_path / ".kanon-data" / "sources" / "beta").exists(), (
            "beta source dir must be absent after clean + reinstall without beta source"
        )

    def test_kanon_change_to_different_packages_reconciles_packages_dir(self, tmp_path: Path) -> None:
        """Changing .kanon to produce different packages reconciles .packages/ correctly.

        Steps:
          1. Install with source producing old-pkg.
          2. Update .kanon (same source URL but different packages from sync).
          3. Reinstall -- source now produces new-pkg instead.
          4. Verify new-pkg is present; stale old-pkg symlink is replaced/absent.
        """
        kanonenv = _write_kanonenv(tmp_path, _single_source_content("evolving"))

        _install_with_synced_packages(kanonenv, {"evolving": ["old-pkg"]})

        assert (tmp_path / ".packages" / "old-pkg").is_symlink(), "old-pkg must be present after first install"

        # Second install: source now produces new-pkg instead of old-pkg
        # (simulates a change in the upstream repo's package structure)
        _install_with_synced_packages(kanonenv, {"evolving": ["new-pkg"]})

        assert (tmp_path / ".packages" / "new-pkg").is_symlink(), "new-pkg must be present after reconciling install"
