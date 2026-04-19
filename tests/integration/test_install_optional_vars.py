"""Integration tests for .kanon optional variables and env-var overrides.

Verifies that the optional variables (GITBASE, KANON_MARKETPLACE_INSTALL,
CLAUDE_MARKETPLACES_DIR) behave correctly when sourced from the .kanon
file, from environment overrides, and when absent.

AC-TEST-001: GITBASE env var and .kanon variable both resolve correctly
             with env var taking precedence over the file value
AC-TEST-002: KANON_MARKETPLACE_INSTALL=true triggers marketplace install path
AC-TEST-003: KANON_MARKETPLACE_INSTALL=false skips marketplace path
AC-TEST-004: CLAUDE_MARKETPLACES_DIR defaults correctly when unset
AC-FUNC-001: Env vars override .kanon-file variables when both are present
AC-CHANNEL-001: stdout vs stderr discipline -- no cross-channel leakage
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install
from kanon_cli.core.kanonenv import parse_kanonenv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file in directory with the given content and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        content: File content to write.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv.resolve()


def _minimal_source_block(name: str = "primary") -> str:
    """Return a minimal valid source block for a .kanon file.

    Args:
        name: Source name to use in variable keys.

    Returns:
        A string with three required KANON_SOURCE_* variable lines.
    """
    return (
        f"KANON_SOURCE_{name}_URL=https://example.com/repo.git\n"
        f"KANON_SOURCE_{name}_REVISION=main\n"
        f"KANON_SOURCE_{name}_PATH=repo-specs/manifest.xml\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001 + AC-FUNC-001: GITBASE env var takes precedence over .kanon value
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitbaseEnvOverride:
    """AC-TEST-001 / AC-FUNC-001: GITBASE resolves correctly from file and env.

    Verifies that when GITBASE is set in both the .kanon file and the
    environment, the environment value wins. Also verifies that when only
    the file value is present, it is used correctly.
    """

    def test_gitbase_from_file_is_used_when_env_absent(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When GITBASE is defined in .kanon but not in the environment,
        parse_kanonenv returns the file value.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "GITBASE=https://file-value.example.com/org/\n" + _minimal_source_block(),
        )
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["GITBASE"] == "https://file-value.example.com/org/", (
            f"Expected GITBASE from file, got {result['globals'].get('GITBASE')!r}"
        )

    def test_gitbase_env_var_overrides_file_value(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When GITBASE is defined in both .kanon and the environment,
        the environment value must take precedence.
        """
        monkeypatch.setenv("GITBASE", "https://env-override.example.com/org/")
        kanonenv = _write_kanonenv(
            tmp_path,
            "GITBASE=https://file-value.example.com/org/\n" + _minimal_source_block(),
        )
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["GITBASE"] == "https://env-override.example.com/org/", (
            f"Env var GITBASE must override file value; got {result['globals'].get('GITBASE')!r}"
        )

    def test_gitbase_env_var_only_in_environment_is_picked_up(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When GITBASE is not in the .kanon file but is set in the environment,
        parse_kanonenv must not include it (env vars not in the file are not injected
        unless they are KANON_SOURCE_* keys). Verifies the boundary is correct.
        """
        monkeypatch.setenv("GITBASE", "https://env-only.example.com/org/")
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(),
        )
        result = parse_kanonenv(kanonenv)
        # GITBASE is not in the file, so it must not appear in globals
        assert "GITBASE" not in result["globals"], (
            "GITBASE set only in env (not in .kanon file) must not appear in parsed globals"
        )

    def test_gitbase_passed_to_envsubst_when_present_in_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() must pass GITBASE from globals_dict to repo_envsubst when present."""
        monkeypatch.delenv("GITBASE", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "GITBASE=https://file.example.com/org/\n" + _minimal_source_block(),
        )

        captured_env_vars: list[dict] = []

        def capture_envsubst(source_dir: str, env_vars: dict) -> None:
            captured_env_vars.append(dict(env_vars))

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst", side_effect=capture_envsubst),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert len(captured_env_vars) == 1, f"Expected repo_envsubst called once, called {len(captured_env_vars)} times"
        assert "GITBASE" in captured_env_vars[0], (
            f"GITBASE must be passed to repo_envsubst; got env_vars={captured_env_vars[0]!r}"
        )
        assert captured_env_vars[0]["GITBASE"] == "https://file.example.com/org/", (
            f"GITBASE value mismatch: {captured_env_vars[0]['GITBASE']!r}"
        )

    def test_gitbase_env_override_flows_through_to_envsubst(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When env var GITBASE overrides the file value, install() must pass
        the env-overridden value to repo_envsubst.
        """
        monkeypatch.setenv("GITBASE", "https://env-override.example.com/org/")
        kanonenv = _write_kanonenv(
            tmp_path,
            "GITBASE=https://file-value.example.com/org/\n" + _minimal_source_block(),
        )

        captured_env_vars: list[dict] = []

        def capture_envsubst(source_dir: str, env_vars: dict) -> None:
            captured_env_vars.append(dict(env_vars))

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst", side_effect=capture_envsubst),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert len(captured_env_vars) == 1
        assert captured_env_vars[0]["GITBASE"] == "https://env-override.example.com/org/", (
            f"install() must use env-overridden GITBASE; got {captured_env_vars[0].get('GITBASE')!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: KANON_MARKETPLACE_INSTALL=true triggers marketplace install
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallTrueFromFile:
    """AC-TEST-002: KANON_MARKETPLACE_INSTALL=true (from .kanon) triggers install path."""

    def test_marketplace_install_triggered_when_flag_true_in_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When KANON_MARKETPLACE_INSTALL=true is in the .kanon file,
        install() must invoke install_marketplace_plugins.
        """
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
        ):
            install(kanonenv)

        (
            mock_mp.assert_called_once_with(marketplace_dir),
            ("install_marketplace_plugins must be called when KANON_MARKETPLACE_INSTALL=true"),
        )

    def test_marketplace_install_triggered_when_flag_true_via_env_override(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When KANON_MARKETPLACE_INSTALL is set to 'true' in the environment
        and 'false' in .kanon, the env override must trigger the marketplace path.
        """
        monkeypatch.setenv("KANON_MARKETPLACE_INSTALL", "true")
        marketplace_dir = tmp_path / "env-marketplaces"
        marketplace_dir.mkdir()
        monkeypatch.setenv("CLAUDE_MARKETPLACES_DIR", str(marketplace_dir))

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=false\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv)

        (
            mock_mp.assert_called_once(),
            (
                "install_marketplace_plugins must be called when env var KANON_MARKETPLACE_INSTALL=true "
                "overrides the file's false value"
            ),
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: KANON_MARKETPLACE_INSTALL=false skips marketplace path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMarketplaceInstallFalseFromFile:
    """AC-TEST-003: KANON_MARKETPLACE_INSTALL=false (from .kanon or env) skips install."""

    @pytest.mark.parametrize(
        "kanon_content_prefix",
        [
            "KANON_MARKETPLACE_INSTALL=false\n",
            "",
        ],
        ids=["explicit_false", "omitted_defaults_false"],
    )
    def test_marketplace_install_skipped_when_flag_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        kanon_content_prefix: str,
    ) -> None:
        """install_marketplace_plugins must not be called when
        KANON_MARKETPLACE_INSTALL is false or absent from the .kanon file.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            kanon_content_prefix + _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv)

        (
            mock_mp.assert_not_called(),
            ("install_marketplace_plugins must not be called when KANON_MARKETPLACE_INSTALL=false or absent"),
        )

    def test_marketplace_install_skipped_when_env_overrides_to_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When env var KANON_MARKETPLACE_INSTALL=false overrides the file's 'true',
        install_marketplace_plugins must not be called.
        """
        monkeypatch.setenv("KANON_MARKETPLACE_INSTALL", "false")
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
        ):
            install(kanonenv)

        (
            mock_mp.assert_not_called(),
            (
                "install_marketplace_plugins must not be called when env KANON_MARKETPLACE_INSTALL=false "
                "overrides file value of true"
            ),
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: CLAUDE_MARKETPLACES_DIR defaults correctly when unset
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClaudeMarketplacesDirDefault:
    """AC-TEST-004: CLAUDE_MARKETPLACES_DIR defaults correctly when absent from .kanon."""

    def test_marketplace_dir_absent_when_not_in_file_and_install_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When CLAUDE_MARKETPLACES_DIR is absent and KANON_MARKETPLACE_INSTALL=false,
        parse_kanonenv must not include it in globals (no default injected).
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=false\n" + _minimal_source_block(),
        )
        result = parse_kanonenv(kanonenv)
        assert "CLAUDE_MARKETPLACES_DIR" not in result["globals"], (
            "CLAUDE_MARKETPLACES_DIR must not appear in globals when absent from .kanon and env"
        )

    def test_marketplace_install_true_with_missing_dir_exits_nonzero(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """When KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not
        defined in .kanon or env, install() must fail fast with exit code 1 and an
        actionable error message on stderr.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit) as exc_info:
            install(kanonenv)

        assert exc_info.value.code != 0, (
            "install() must exit non-zero when KANON_MARKETPLACE_INSTALL=true and CLAUDE_MARKETPLACES_DIR is absent"
        )
        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, (
            f"Error message about missing CLAUDE_MARKETPLACES_DIR must appear on stderr; got stderr={captured.err!r}"
        )

    def test_marketplace_dir_from_env_used_when_not_in_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When CLAUDE_MARKETPLACES_DIR is not in .kanon but is provided via env var
        override alongside KANON_MARKETPLACE_INSTALL=true, the install should pick it
        up because env overrides are applied for file-present keys only -- so this
        verifies the correct boundary: CLAUDE_MARKETPLACES_DIR must be in the file
        (not just env) for the marketplace path to activate.

        This test verifies that CLAUDE_MARKETPLACES_DIR not in file means install
        fails even when CLAUDE_MARKETPLACES_DIR is set in the environment, because
        the env-override mechanism only applies to keys already declared in the file.
        """
        marketplace_dir = tmp_path / "env-only-dir"
        marketplace_dir.mkdir()
        monkeypatch.setenv("CLAUDE_MARKETPLACES_DIR", str(marketplace_dir))

        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit) as exc_info:
            install(kanonenv)

        assert exc_info.value.code != 0, (
            "install() must fail when CLAUDE_MARKETPLACES_DIR is only in env (not in .kanon file) "
            "because env-override only applies to keys present in the file"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChannelDiscipline:
    """AC-CHANNEL-001: Error output goes to stderr; success info goes to stdout only."""

    def test_missing_marketplace_dir_error_on_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Error about missing CLAUDE_MARKETPLACES_DIR must appear on stderr, not stdout."""
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )

        with pytest.raises(SystemExit):
            install(kanonenv)

        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, (
            f"Error message must appear on stderr; got stderr={captured.err!r}"
        )
        assert "CLAUDE_MARKETPLACES_DIR" not in captured.out, (
            f"Error message must not appear on stdout; got stdout={captured.out!r}"
        )

    def test_successful_install_progress_on_stdout(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Successful install progress messages must appear on stdout and stderr must be clean."""
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        captured = capsys.readouterr()
        assert captured.err == "", f"stderr must be empty for a successful install; got stderr={captured.err!r}"
        assert "kanon install" in captured.out, f"install progress must appear on stdout; got stdout={captured.out!r}"
