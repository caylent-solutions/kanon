"""Integration tests for kanon clean lifecycle via CLI entry point (8 tests).

Covers the clean command lifecycle from the CLI boundary:
  - AC-TEST-001: kanon clean removes .packages/ and .kanon-data/
  - AC-TEST-002: kanon clean with KANON_MARKETPLACE_INSTALL=true also removes marketplace directory
  - AC-TEST-003: kanon clean is idempotent (clean of already-clean state succeeds)
  - AC-FUNC-001: clean removes every artifact install created, nothing else
  - AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, extra_lines: str = "") -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        extra_lines: Additional KEY=VALUE lines to append.

    Returns:
        Absolute path to the written .kanon file.
    """
    base = (
        "KANON_SOURCE_primary_URL=https://example.com/primary.git\n"
        "KANON_SOURCE_primary_REVISION=main\n"
        "KANON_SOURCE_primary_PATH=meta.xml\n"
    )
    kanonenv = directory / ".kanon"
    kanonenv.write_text(base + extra_lines)
    return kanonenv.resolve()


def _create_install_artifacts(base_dir: pathlib.Path, packages: list[str]) -> None:
    """Create .packages/ and .kanon-data/ artifacts as install would.

    Args:
        base_dir: Project root directory.
        packages: List of package names to create under .packages/.
    """
    packages_dir = base_dir / ".packages"
    for pkg in packages:
        pkg_dir = packages_dir / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / f"{pkg}.sh").write_text(f"#!/bin/sh\necho {pkg}\n")

    kanon_data = base_dir / ".kanon-data" / "sources" / "primary"
    kanon_data.mkdir(parents=True, exist_ok=True)
    (kanon_data / "metadata.txt").write_text("source=primary\n")


# ---------------------------------------------------------------------------
# AC-TEST-001: kanon clean removes .packages/ and .kanon-data/
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanRemovesArtifacts:
    """AC-TEST-001: kanon clean removes .packages/ and .kanon-data/ via CLI."""

    def test_clean_removes_packages_and_kanon_data(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: invoking 'kanon clean' removes .packages/ and .kanon-data/."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a", "tool-b"])

        assert (tmp_path / ".packages").exists(), "precondition: .packages/ must exist before clean"
        assert (tmp_path / ".kanon-data").exists(), "precondition: .kanon-data/ must exist before clean"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "kanon clean must remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), "kanon clean must remove .kanon-data/"

    def test_clean_removes_nested_packages_content(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: clean removes all nested content inside .packages/."""
        kanonenv = _write_kanonenv(tmp_path)
        nested = tmp_path / ".packages" / "tool-a" / "subdir"
        nested.mkdir(parents=True)
        (nested / "file.txt").write_text("content")
        (tmp_path / ".kanon-data").mkdir()

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "kanon clean must remove .packages/ including nested content"


# ---------------------------------------------------------------------------
# AC-TEST-002: kanon clean with KANON_MARKETPLACE_INSTALL=true removes marketplace dir
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanWithMarketplace:
    """AC-TEST-002: kanon clean with marketplace enabled removes marketplace directory."""

    def test_clean_marketplace_true_removes_marketplace_directory(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: KANON_MARKETPLACE_INSTALL=true causes clean to remove marketplace dir."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        (marketplace_dir / "some-marketplace-plugin.txt").write_text("plugin data")

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"),
        )
        _create_install_artifacts(tmp_path, ["tool-a"])

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            main(["clean", str(kanonenv)])

        assert not marketplace_dir.exists(), (
            "kanon clean with KANON_MARKETPLACE_INSTALL=true must remove CLAUDE_MARKETPLACES_DIR"
        )
        assert not (tmp_path / ".packages").exists(), "kanon clean with marketplace=true must also remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), (
            "kanon clean with marketplace=true must also remove .kanon-data/"
        )

    def test_clean_marketplace_false_does_not_touch_unrelated_dirs(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: clean with marketplace disabled does not remove unrelated directories."""
        other_dir = tmp_path / "other-data"
        other_dir.mkdir()
        (other_dir / "keep.txt").write_text("user data")

        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert other_dir.exists(), "clean must not remove directories it does not own"
        assert (other_dir / "keep.txt").exists(), "clean must not remove user files"


# ---------------------------------------------------------------------------
# AC-TEST-003: kanon clean is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanIdempotent:
    """AC-TEST-003: kanon clean is idempotent when run on an already-clean directory."""

    def test_clean_on_already_clean_dir_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: 'kanon clean' on a directory without artifacts exits zero."""
        kanonenv = _write_kanonenv(tmp_path)

        assert not (tmp_path / ".packages").exists(), "precondition: .packages/ must not exist"
        assert not (tmp_path / ".kanon-data").exists(), "precondition: .kanon-data/ must not exist"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "idempotent clean: .packages/ must remain absent"
        assert not (tmp_path / ".kanon-data").exists(), "idempotent clean: .kanon-data/ must remain absent"

    def test_clean_twice_in_succession_both_succeed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: running 'kanon clean' twice on the same directory succeeds both times."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "first clean must remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), "first clean must remove .kanon-data/"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "second clean must not fail when .packages/ absent"
        assert not (tmp_path / ".kanon-data").exists(), "second clean must not fail when .kanon-data/ absent"


# ---------------------------------------------------------------------------
# AC-FUNC-001 and AC-CHANNEL-001: preservation of non-managed files and channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanPreservesNonManagedFiles:
    """AC-FUNC-001 and AC-CHANNEL-001: clean removes only managed artifacts."""

    def test_clean_preserves_kanonenv_and_user_files(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-FUNC-001: clean does not remove .kanon, .gitignore, or user source files."""
        kanonenv = _write_kanonenv(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".packages/\n.kanon-data/\n")
        user_file = tmp_path / "src" / "app.py"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("# user code\n")

        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert kanonenv.exists(), "AC-FUNC-001: clean must not remove the .kanon file"
        assert gitignore.exists(), "AC-FUNC-001: clean must not remove .gitignore"
        assert user_file.exists(), "AC-FUNC-001: clean must not remove user source files"

    def test_clean_success_output_goes_to_stdout_not_stderr(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: progress messages from clean go to stdout; stderr must be empty on success."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        captured = capsys.readouterr()
        assert captured.err == "", (
            f"AC-CHANNEL-001: no output expected on stderr during clean success; stderr={captured.err!r}"
        )
        assert "clean" in captured.out.lower() or ".packages" in captured.out, (
            f"AC-CHANNEL-001: progress output expected on stdout during clean; stdout={captured.out!r}"
        )
