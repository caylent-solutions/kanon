"""Integration tests for marketplace install state matrix (4 tests).

Exercises the KANON_MARKETPLACE_INSTALL env-var gate in both install and clean
lifecycles.  All subprocess calls to the claude binary are mocked so tests run
without the claude CLI installed.

AC-TEST-001: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR set
             -> marketplace installed
AC-TEST-002: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR unset
             -> fails with actionable error
AC-TEST-003: KANON_MARKETPLACE_INSTALL=false -> marketplace skipped
AC-TEST-004: marketplace install is cleaned up by kanon clean
"""

import json
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


def _minimal_source_block(name: str = "primary") -> str:
    """Return a minimal source block for use in .kanon content."""
    return (
        f"KANON_SOURCE_{name}_URL=https://example.com/repo.git\n"
        f"KANON_SOURCE_{name}_REVISION=main\n"
        f"KANON_SOURCE_{name}_PATH=meta.xml\n"
    )


def _create_marketplace_fixture(marketplace_dir: pathlib.Path, mp_name: str, plugin_name: str) -> None:
    """Create a marketplace directory structure with one plugin.

    Args:
        marketplace_dir: Parent directory for the marketplace (CLAUDE_MARKETPLACES_DIR).
        mp_name: Marketplace directory name (also used in marketplace.json).
        plugin_name: Plugin directory name (also used in plugin.json).
    """
    mp_path = marketplace_dir / mp_name
    mp_path.mkdir(parents=True, exist_ok=True)
    claude_plugin = mp_path / ".claude-plugin"
    claude_plugin.mkdir(exist_ok=True)
    (claude_plugin / "marketplace.json").write_text(json.dumps({"name": mp_name}))
    plugin_dir = mp_path / plugin_name / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": plugin_name}))


# ---------------------------------------------------------------------------
# AC-TEST-001: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR set
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallTrue:
    """AC-TEST-001: KANON_MARKETPLACE_INSTALL=true with CLAUDE_MARKETPLACES_DIR -> installs marketplace."""

    def test_marketplace_installed_when_flag_true_and_dir_set(self, tmp_path: pathlib.Path) -> None:
        """When KANON_MARKETPLACE_INSTALL=true and CLAUDE_MARKETPLACES_DIR is set,
        install() must invoke install_marketplace_plugins with the configured directory.
        """
        marketplace_dir = tmp_path / "my-marketplaces"
        marketplace_dir.mkdir()
        _create_marketplace_fixture(marketplace_dir, "test-marketplace", "test-plugin")

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_install_mp,
        ):
            install(kanonenv)

        mock_install_mp.assert_called_once_with(marketplace_dir)

    def test_marketplace_dir_passed_as_path_object(self, tmp_path: pathlib.Path) -> None:
        """install_marketplace_plugins receives a pathlib.Path, not a string."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        received_paths: list[pathlib.Path] = []

        def capture_dir(d: pathlib.Path) -> None:
            received_paths.append(d)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins", side_effect=capture_dir),
        ):
            install(kanonenv)

        assert len(received_paths) == 1
        assert isinstance(received_paths[0], pathlib.Path), (
            f"Expected install_marketplace_plugins to receive a pathlib.Path, got {type(received_paths[0])!r}"
        )
        assert received_paths[0] == marketplace_dir


# ---------------------------------------------------------------------------
# AC-TEST-002: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR unset
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallMissingDir:
    """AC-TEST-002: KANON_MARKETPLACE_INSTALL=true with no CLAUDE_MARKETPLACES_DIR -> actionable error."""

    def test_install_fails_fast_when_marketplace_dir_unset(self, tmp_path: pathlib.Path) -> None:
        """When KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is absent
        from .kanon, install() must exit non-zero with a clear error message.
        """
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit) as exc_info:
            install(kanonenv)

        assert exc_info.value.code != 0, (
            "install() must exit non-zero when KANON_MARKETPLACE_INSTALL=true and CLAUDE_MARKETPLACES_DIR is unset"
        )

    def test_install_error_message_is_actionable(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Error message must name both KANON_MARKETPLACE_INSTALL and CLAUDE_MARKETPLACES_DIR."""
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit):
            install(kanonenv)

        captured = capsys.readouterr()
        assert "KANON_MARKETPLACE_INSTALL" in captured.err, (
            f"Error message must mention KANON_MARKETPLACE_INSTALL, got stderr={captured.err!r}"
        )
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, (
            f"Error message must mention CLAUDE_MARKETPLACES_DIR, got stderr={captured.err!r}"
        )

    def test_install_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Error output must be on stderr, not stdout (AC-CHANNEL-001)."""
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit):
            install(kanonenv)

        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" not in captured.out, (
            f"Error about missing CLAUDE_MARKETPLACES_DIR must not appear on stdout, got stdout={captured.out!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: KANON_MARKETPLACE_INSTALL=false -> marketplace skipped
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallFalse:
    """AC-TEST-003: KANON_MARKETPLACE_INSTALL=false -> marketplace install is skipped."""

    @pytest.mark.parametrize(
        "kanon_content_suffix",
        [
            "KANON_MARKETPLACE_INSTALL=false\n",
            "",  # omitted entirely -- defaults to false
        ],
        ids=["explicit_false", "omitted"],
    )
    def test_marketplace_not_invoked_when_flag_false(self, tmp_path: pathlib.Path, kanon_content_suffix: str) -> None:
        """install_marketplace_plugins must not be called when marketplace install is disabled."""
        kanonenv = _write_kanonenv(
            tmp_path,
            kanon_content_suffix + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_install_mp,
        ):
            install(kanonenv)

        mock_install_mp.assert_not_called()

    def test_prepare_marketplace_dir_not_called_when_flag_false(self, tmp_path: pathlib.Path) -> None:
        """prepare_marketplace_dir must not be called when marketplace install is disabled."""
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=false\n" + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.prepare_marketplace_dir") as mock_prepare,
        ):
            install(kanonenv)

        mock_prepare.assert_not_called()


# ---------------------------------------------------------------------------
# AC-TEST-004: marketplace install is cleaned up by kanon clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceCleanup:
    """AC-TEST-004: Marketplace directory is removed by kanon clean."""

    def test_clean_removes_marketplace_dir_when_flag_true(self, tmp_path: pathlib.Path) -> None:
        """When KANON_MARKETPLACE_INSTALL=true, clean() must remove CLAUDE_MARKETPLACES_DIR."""
        marketplace_dir = tmp_path / "my-marketplaces"
        marketplace_dir.mkdir()
        (marketplace_dir / "some-file.txt").write_text("marketplace data")

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not marketplace_dir.exists(), (
            f"clean() must remove CLAUDE_MARKETPLACES_DIR ({marketplace_dir}) when KANON_MARKETPLACE_INSTALL=true"
        )

    def test_clean_invokes_marketplace_uninstall_when_flag_true(self, tmp_path: pathlib.Path) -> None:
        """clean() must invoke uninstall_marketplace_plugins with the marketplace dir path."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)

        mock_uninstall.assert_called_once_with(marketplace_dir)

    def test_clean_skips_marketplace_when_flag_false(self, tmp_path: pathlib.Path) -> None:
        """When KANON_MARKETPLACE_INSTALL=false, clean() must not invoke marketplace uninstall."""
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=false\n" + _minimal_source_block(),
        )
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)

        mock_uninstall.assert_not_called()

    def test_full_install_then_clean_roundtrip_with_marketplace(self, tmp_path: pathlib.Path) -> None:
        """Full roundtrip: install with marketplace enabled, then clean removes everything.

        Verifies that after install + clean, both .packages/, .kanon-data/, and
        CLAUDE_MARKETPLACES_DIR are all absent.
        """
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        _create_marketplace_fixture(marketplace_dir, "acme-market", "acme-plugin")

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins"),
        ):
            install(kanonenv)

        assert marketplace_dir.exists(), "marketplace_dir should still exist after install (not yet cleaned)"

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not marketplace_dir.exists(), (
            "clean() must remove CLAUDE_MARKETPLACES_DIR in the install -> clean roundtrip"
        )
        assert not (tmp_path / ".packages").exists(), "clean() must remove .packages/ in the install -> clean roundtrip"
        assert not (tmp_path / ".kanon-data").exists(), (
            "clean() must remove .kanon-data/ in the install -> clean roundtrip"
        )
        assert kanonenv.is_file(), "clean() must not remove the .kanon configuration file"
