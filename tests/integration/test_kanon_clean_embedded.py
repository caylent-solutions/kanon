"""Integration tests for kanon clean lifecycle using embedded Python API (8 tests).

Verifies that clean removes repo-managed files, preserves non-repo files, and
that the full install -> clean roundtrip works correctly. Also covers error
paths: invalid manifest, corrupt state, and marketplace-enabled vs disabled.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install


def _write_kanonenv(directory: Path, content: str) -> Path:
    """Write a .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


def _minimal_kanonenv_content(name: str = "primary") -> str:
    """Return minimal .kanon content for a single source."""
    return (
        f"KANON_SOURCE_{name}_URL=https://example.com/repo.git\n"
        f"KANON_SOURCE_{name}_REVISION=main\n"
        f"KANON_SOURCE_{name}_PATH=meta.xml\n"
    )


@pytest.mark.integration
class TestCleanRemovesRepoManagedFiles:
    """AC-FUNC-007: Clean removes repo-managed files (.packages/, .kanon-data/)."""

    def test_clean_removes_repo_managed_files(self, tmp_path: Path) -> None:
        """Verify that clean() removes .packages/ and .kanon-data/ directories
        created by install.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())
        (tmp_path / ".packages" / "some-pkg").mkdir(parents=True)
        (tmp_path / ".kanon-data" / "sources" / "primary").mkdir(parents=True)
        (tmp_path / ".kanon-data" / "sources" / "primary" / "metadata.txt").write_text("data")

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists(), ".packages/ should be removed by clean()"
        assert not (tmp_path / ".kanon-data").exists(), ".kanon-data/ should be removed by clean()"


@pytest.mark.integration
class TestCleanPreservesNonRepoFiles:
    """AC-FUNC-008: Clean preserves files not managed by repo (e.g. user files)."""

    def test_clean_preserves_non_repo_files(self, tmp_path: Path) -> None:
        """Verify that clean() does not remove files that were not created by install:
        - .kanon configuration file
        - .gitignore
        - User source files
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())
        (tmp_path / ".gitignore").write_text(".packages/\n.kanon-data/\n")
        user_file = tmp_path / "src" / "main.py"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("# user code\n")

        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        clean(kanonenv)

        assert kanonenv.is_file(), ".kanon configuration file must survive clean()"
        assert (tmp_path / ".gitignore").is_file(), ".gitignore must survive clean()"
        assert user_file.is_file(), "User source files must survive clean()"


@pytest.mark.integration
class TestInstallCleanRoundtrip:
    """AC-FUNC-009: Full install -> clean roundtrip leaves project in clean state."""

    def test_install_then_clean_roundtrip(self, tmp_path: Path) -> None:
        """Verify the full roundtrip: install creates managed artifacts,
        clean removes them, leaving the project directory in a clean state
        with only the .kanon file remaining.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            pkg_dir = Path(repo_dir) / ".packages" / "tool-a"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "tool-a.sh").write_text("#!/bin/sh\necho hello\n")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv)

        assert (tmp_path / ".packages" / "tool-a").is_symlink(), "install() should create a symlink in .packages/"
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            "install() should create .kanon-data/sources/primary/"
        )

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists(), "clean() should remove .packages/ after install"
        assert not (tmp_path / ".kanon-data").exists(), "clean() should remove .kanon-data/ after install"
        assert kanonenv.is_file(), "clean() must not remove the .kanon configuration file"


@pytest.mark.integration
class TestCleanErrorPaths:
    """AC-FUNC-010: Error paths -- invalid manifest, missing git, corrupt state."""

    def test_clean_invalid_manifest_raises_value_error(self, tmp_path: Path) -> None:
        """Verify that clean() raises ValueError when .kanon has no valid source
        definitions. The CLI command handler converts this to SystemExit(1).
        """
        kanonenv = _write_kanonenv(
            tmp_path,
            "# This .kanon has no sources -- invalid\nREPO_REV=v1.0.0\n",
        )
        with pytest.raises(ValueError, match="No sources found"):
            clean(kanonenv)

    def test_clean_missing_kanonenv_raises_file_not_found(self, tmp_path: Path) -> None:
        """Verify that clean() raises FileNotFoundError when .kanon does not exist."""
        missing = tmp_path / ".kanon"
        with pytest.raises(FileNotFoundError):
            clean(missing)

    def test_clean_corrupt_kanon_data_is_still_removed(self, tmp_path: Path) -> None:
        """Verify that clean() removes .kanon-data/ even when its contents are
        in a corrupt/unexpected state (e.g. unexpected nested files).
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())
        corrupt_dir = tmp_path / ".kanon-data" / "sources" / "primary" / "unexpected-subdir"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "corrupt.bin").write_bytes(b"\x00\xff\xfe")

        clean(kanonenv)

        assert not (tmp_path / ".kanon-data").exists(), (
            "clean() must remove .kanon-data/ even when contents are in unexpected state"
        )

    def test_clean_idempotent_when_already_clean(self, tmp_path: Path) -> None:
        """Verify that clean() succeeds (is idempotent) when .packages/ and
        .kanon-data/ do not exist.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())

        assert not (tmp_path / ".packages").exists()
        assert not (tmp_path / ".kanon-data").exists()

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists()
        assert not (tmp_path / ".kanon-data").exists()


@pytest.mark.integration
class TestCleanMarketplaceBehavior:
    """AC-FUNC-007, AC-FUNC-008: Marketplace clean behaviors."""

    def test_clean_marketplace_false_skips_uninstall(self, tmp_path: Path) -> None:
        """Verify that when KANON_MARKETPLACE_INSTALL is absent (defaults to false),
        the marketplace uninstall function is never invoked.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_content())
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()

        assert not (tmp_path / ".packages").exists(), (
            ".packages/ should still be removed even when marketplace uninstall is skipped"
        )

    def test_clean_marketplace_true_removes_marketplace_dir(self, tmp_path: Path) -> None:
        """Verify that when KANON_MARKETPLACE_INSTALL=true, clean() removes
        the marketplace directory in addition to .packages/ and .kanon-data/.
        """
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        (marketplace_dir / "some-marketplace-file.txt").write_text("marketplace data")

        kanonenv = _write_kanonenv(
            tmp_path,
            (
                "KANON_MARKETPLACE_INSTALL=true\n"
                f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"
                "KANON_SOURCE_primary_URL=https://example.com/repo.git\n"
                "KANON_SOURCE_primary_REVISION=main\n"
                "KANON_SOURCE_primary_PATH=meta.xml\n"
            ),
        )
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not marketplace_dir.exists(), (
            "clean() should remove CLAUDE_MARKETPLACES_DIR when KANON_MARKETPLACE_INSTALL=true"
        )
        assert not (tmp_path / ".packages").exists(), ".packages/ should be removed during clean with marketplace=true"
