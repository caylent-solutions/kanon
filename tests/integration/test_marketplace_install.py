"""Integration tests for the marketplace install state matrix.

Verifies the four AC-TEST-* acceptance criteria for the install/clean
marketplace lifecycle, plus the FUNC and CHANNEL gate criteria.

AC-TEST-001: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR set
             -- marketplace installed (install_marketplace_plugins called)
AC-TEST-002: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR unset
             -- fails fast with actionable error naming both env vars
AC-TEST-003: KANON_MARKETPLACE_INSTALL=false (or omitted)
             -- marketplace path skipped (install_marketplace_plugins NOT called)
AC-TEST-004: marketplace install is cleaned up by kanon clean

AC-FUNC-001: Marketplace path gated by both env vars; missing required
             combination fails fast
AC-CHANNEL-001: CLI-path stderr vs stdout discipline verified (no cross-channel
                leakage)

CLI-boundary behavior is exercised via _install_run() (raises SystemExit).
Library-boundary behavior is exercised via install() (raises ValueError /
RepoCommandError only -- never SystemExit).
"""

import json
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.commands.install import _run as _install_run
from kanon_cli.core.clean import clean
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file with given content in directory and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        content: Full file content to write.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv.resolve()


def _minimal_source_block(name: str = "primary") -> str:
    """Return a minimal valid KANON_SOURCE_* block for a .kanon file.

    Args:
        name: Source name to use in variable keys.

    Returns:
        A string with the three required KANON_SOURCE_* variable lines.
    """
    return (
        f"KANON_SOURCE_{name}_URL=https://example.com/repo.git\n"
        f"KANON_SOURCE_{name}_REVISION=main\n"
        f"KANON_SOURCE_{name}_PATH=repo-specs/manifest.xml\n"
    )


def _create_marketplace_fixture(marketplace_dir: pathlib.Path, name: str = "test-market") -> pathlib.Path:
    """Create a minimal marketplace directory structure for install tests.

    Creates CLAUDE_MARKETPLACES_DIR with a single marketplace entry that
    contains a .claude-plugin/marketplace.json manifest.

    Args:
        marketplace_dir: Root marketplace directory path (CLAUDE_MARKETPLACES_DIR).
        name: Marketplace entry name.

    Returns:
        Path to the created marketplace entry directory.
    """
    marketplace_dir.mkdir(parents=True, exist_ok=True)
    entry = marketplace_dir / name
    entry.mkdir()
    plugin_meta = entry / ".claude-plugin"
    plugin_meta.mkdir()
    (plugin_meta / "marketplace.json").write_text(json.dumps({"name": name}))
    return entry


# ---------------------------------------------------------------------------
# AC-TEST-001: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR set
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallTrue:
    """AC-TEST-001: Marketplace install path is exercised when both env vars set.

    When KANON_MARKETPLACE_INSTALL=true and CLAUDE_MARKETPLACES_DIR is defined
    in the .kanon file, install_marketplace_plugins must be called.
    """

    def test_marketplace_plugins_called_when_flag_and_dir_set(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() calls install_marketplace_plugins when both env vars are configured."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
            patch("kanon_cli.core.install.prepare_marketplace_dir"),
        ):
            install(kanonenv)

        assert mock_mp.called, (
            "install_marketplace_plugins must be called when KANON_MARKETPLACE_INSTALL=true "
            "and CLAUDE_MARKETPLACES_DIR is set"
        )

    def test_marketplace_plugins_called_with_correct_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() passes the correct marketplace_dir path to install_marketplace_plugins."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        marketplace_dir = tmp_path / "my-marketplaces"
        marketplace_dir.mkdir()
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
            patch("kanon_cli.core.install.prepare_marketplace_dir"),
        ):
            install(kanonenv)

        call_args = mock_mp.call_args
        assert call_args is not None, "install_marketplace_plugins was not called"
        passed_dir = call_args[0][0]
        assert str(passed_dir) == str(marketplace_dir), (
            f"install_marketplace_plugins called with wrong dir: expected {marketplace_dir!r}, got {passed_dir!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: KANON_MARKETPLACE_INSTALL=true + CLAUDE_MARKETPLACES_DIR unset
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallMissingDir:
    """AC-TEST-002 / AC-FUNC-001: Fails fast when marketplace dir is missing.

    When KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is absent,
    install() must raise ValueError and the CLI handler must convert it to a
    SystemExit with exit code != 0 and an actionable error message on stderr.
    """

    def test_install_raises_value_error_when_marketplace_dir_unset(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() raises ValueError (not SystemExit) when dir is absent.

        Library boundary must not call sys.exit(); it raises ValueError so
        the CLI handler at the boundary can format and route the error.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(ValueError) as exc_info:
            install(kanonenv)

        assert "CLAUDE_MARKETPLACES_DIR" in str(exc_info.value), (
            f"ValueError message must name CLAUDE_MARKETPLACES_DIR; got: {exc_info.value!r}"
        )

    def test_cli_converts_value_error_to_system_exit_on_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        make_install_args,
    ) -> None:
        """_install_run() catches ValueError from install() and calls sys.exit(1).

        The CLI boundary must catch the ValueError raised by the library,
        write the error to stderr, and exit with a non-zero code.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )
        args = make_install_args(kanonenv)

        with pytest.raises(SystemExit) as exc_info:
            _install_run(args)

        assert exc_info.value.code != 0, f"CLI handler must exit with non-zero code; got {exc_info.value.code}"
        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, (
            f"Error message must name CLAUDE_MARKETPLACES_DIR on stderr; got stderr={captured.err!r}"
        )

    def test_install_error_on_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        make_install_args,
    ) -> None:
        """AC-CHANNEL-001: error about missing CLAUDE_MARKETPLACES_DIR appears on stderr only.

        No error text about missing CLAUDE_MARKETPLACES_DIR must leak to stdout.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )
        args = make_install_args(kanonenv)

        with pytest.raises(SystemExit):
            _install_run(args)

        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, f"Error must appear on stderr; got stderr={captured.err!r}"
        assert "CLAUDE_MARKETPLACES_DIR" not in captured.out, (
            f"Error must NOT appear on stdout; got stdout={captured.out!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: KANON_MARKETPLACE_INSTALL=false or omitted
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallFalse:
    """AC-TEST-003: Marketplace path is skipped when flag is false or absent.

    When KANON_MARKETPLACE_INSTALL=false (or the key is absent entirely),
    install_marketplace_plugins must never be called.
    """

    @pytest.mark.parametrize(
        "flag_line,scenario",
        [
            ("KANON_MARKETPLACE_INSTALL=false\n", "explicit_false"),
            ("", "omitted"),
        ],
    )
    def test_marketplace_plugins_not_called(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        flag_line: str,
        scenario: str,
    ) -> None:
        """install() does not call install_marketplace_plugins when flag is false/absent."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            flag_line + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv)

        assert not mock_mp.called, (
            f"install_marketplace_plugins must NOT be called when KANON_MARKETPLACE_INSTALL "
            f"is {scenario}; was called with {mock_mp.call_args_list}"
        )

    def test_marketplace_install_skipped_when_env_overrides_to_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() skips marketplace when env var KANON_MARKETPLACE_INSTALL=false overrides file."""
        monkeypatch.setenv("KANON_MARKETPLACE_INSTALL", "false")
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv)

        assert not mock_mp.called, (
            "install_marketplace_plugins must NOT be called when env KANON_MARKETPLACE_INSTALL=false "
            "overrides file value of true"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Marketplace install is cleaned up by kanon clean
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceCleanup:
    """AC-TEST-004: kanon clean uninstalls marketplace plugins and removes the dir.

    clean() must call uninstall_marketplace_plugins and then remove
    CLAUDE_MARKETPLACES_DIR when KANON_MARKETPLACE_INSTALL=true.
    """

    def test_clean_calls_uninstall_marketplace_plugins(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """clean() calls uninstall_marketplace_plugins when flag=true and dir is set."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)

        assert mock_uninstall.called, "uninstall_marketplace_plugins must be called when KANON_MARKETPLACE_INSTALL=true"

    def test_clean_removes_marketplace_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """clean() removes CLAUDE_MARKETPLACES_DIR when KANON_MARKETPLACE_INSTALL=true."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        marketplace_dir = tmp_path / "marketplaces"
        _create_marketplace_fixture(marketplace_dir)
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not marketplace_dir.exists(), (
            f"CLAUDE_MARKETPLACES_DIR must be removed by clean(); directory still exists at {marketplace_dir}"
        )

    def test_clean_skips_marketplace_when_flag_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """clean() does not call uninstall_marketplace_plugins when flag=false."""
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=false\n" + _minimal_source_block(),
        )

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)

        assert not mock_uninstall.called, (
            "uninstall_marketplace_plugins must NOT be called when KANON_MARKETPLACE_INSTALL=false"
        )

    def test_install_clean_roundtrip(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full roundtrip: install creates marketplace dir; clean removes it.

        Uses prepare_marketplace_dir for real filesystem operations to verify
        the directory state transitions: directory exists after install setup,
        directory absent after clean.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        marketplace_dir = tmp_path / "roundtrip-marketplaces"
        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        # -- install phase: real prepare_marketplace_dir creates the directory
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins"),
        ):
            install(kanonenv)

        assert marketplace_dir.exists(), f"Marketplace dir must exist after install; not found at {marketplace_dir}"

        # -- clean phase: uninstall_marketplace_plugins mocked; dir removal is real
        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not marketplace_dir.exists(), (
            f"Marketplace dir must be absent after clean; still exists at {marketplace_dir}"
        )
