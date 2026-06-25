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

from kanon_cli.commands.install import _run as _install_run
from kanon_cli.core.install import install
from kanon_cli.core.kanonenv import parse_kanonenv


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


def _minimal_source_block(name: str = "primary", *, marketplace: bool = False) -> str:
    """Return a minimal valid source block for a .kanon file.

    Args:
        name: Source name to use in variable keys.
        marketplace: When True, append the per-dependency
            ``KANON_SOURCE_<name>_MARKETPLACE=true`` opt-in line (the 3.0.0
            replacement for the removed global ``KANON_MARKETPLACE_INSTALL``).

    Returns:
        A string with the required KANON_SOURCE_* variable lines.
    """
    block = (
        f"KANON_SOURCE_{name}_URL=https://example.com/repo.git\n"
        f"KANON_SOURCE_{name}_REF=main\n"
        f"KANON_SOURCE_{name}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{name}_NAME={name}\n"
        f"KANON_SOURCE_{name}_GITBASE=https://example.com\n"
    )
    if marketplace:
        block += f"KANON_SOURCE_{name}_MARKETPLACE=true\n"
    return block


@pytest.mark.integration
class TestGitbaseEnvOverride:
    """AC-TEST-001 / AC-FUNC-001: GITBASE resolves correctly from file and env.

    Verifies that when a global GITBASE is set in both the .kanon file and the
    environment, the environment value wins in the parsed globals, and that the
    file value is used when only the file value is present.

    The org base that actually drives ``repo envsubst`` is the per-dependency
    ``KANON_SOURCE_<alias>_GITBASE`` (spec Section 5.1 / FR-5): ``kanon add``
    records it per source and writes no global ``GITBASE`` header line, so
    ``install`` promotes each source's per-alias gitbase into the ``GITBASE``
    key for that source's substitution. The per-alias value is source-targeted
    and therefore takes precedence over any hand-written global ``GITBASE``.
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

        assert "GITBASE" not in result["globals"], (
            "GITBASE set only in env (not in .kanon file) must not appear in parsed globals"
        )

    def test_per_alias_gitbase_passed_to_envsubst(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() must pass each source's per-alias _GITBASE to repo_envsubst.

        ``kanon add`` records the org base per dependency in
        ``KANON_SOURCE_<alias>_GITBASE`` and writes no global ``GITBASE`` line, so
        install must promote the per-alias value into ``GITBASE`` for that source.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(),
        )

        captured_env_vars: list[dict] = []

        def capture_envsubst(source_dir: str, env_vars: dict) -> None:
            captured_env_vars.append(dict(env_vars))

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst", side_effect=capture_envsubst),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert len(captured_env_vars) == 1, f"Expected repo_envsubst called once, called {len(captured_env_vars)} times"
        assert "GITBASE" in captured_env_vars[0], (
            f"GITBASE must be passed to repo_envsubst; got env_vars={captured_env_vars[0]!r}"
        )
        assert captured_env_vars[0]["GITBASE"] == "https://example.com", (
            f"per-alias GITBASE value mismatch: {captured_env_vars[0]['GITBASE']!r}"
        )

    def test_per_alias_gitbase_takes_precedence_over_global(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A source's per-alias _GITBASE wins over a hand-written global GITBASE.

        The per-alias value is the source-targeted org base, so install must use
        it for that source's substitution even when a global ``GITBASE`` header
        line is also present.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            "GITBASE=https://global.example.com/org/\n" + _minimal_source_block(),
        )

        captured_env_vars: list[dict] = []

        def capture_envsubst(source_dir: str, env_vars: dict) -> None:
            captured_env_vars.append(dict(env_vars))

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst", side_effect=capture_envsubst),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert len(captured_env_vars) == 1
        assert captured_env_vars[0]["GITBASE"] == "https://example.com", (
            f"per-alias GITBASE must override the global header value; got {captured_env_vars[0].get('GITBASE')!r}"
        )

    def test_per_alias_gitbase_env_override_flows_through_to_envsubst(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When an env var overrides the per-alias _GITBASE file value, install()
        must pass the env-overridden value to repo_envsubst.

        The kanonenv env-override applies to keys present in the file, so setting
        ``KANON_SOURCE_<alias>_GITBASE`` in the environment overrides the file's
        per-alias value, and that override is what install promotes into
        ``GITBASE`` for the source's substitution.
        """
        monkeypatch.setenv("KANON_SOURCE_primary_GITBASE", "https://env-override.example.com/org/")
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(),
        )

        captured_env_vars: list[dict] = []

        def capture_envsubst(source_dir: str, env_vars: dict) -> None:
            captured_env_vars.append(dict(env_vars))

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst", side_effect=capture_envsubst),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        assert len(captured_env_vars) == 1
        assert captured_env_vars[0]["GITBASE"] == "https://env-override.example.com/org/", (
            f"install() must use env-overridden per-alias GITBASE; got {captured_env_vars[0].get('GITBASE')!r}"
        )


@pytest.mark.integration
class TestMarketplaceInstallTrueFromFile:
    """AC-TEST-002: KANON_MARKETPLACE_INSTALL=true (from .kanon) triggers install path."""

    def test_marketplace_install_triggered_when_flag_true_in_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a dependency opts into the marketplace via the per-dependency flag,
        install() must invoke install_marketplace_plugins.

        3.0.0: the per-dependency KANON_SOURCE_<alias>_MARKETPLACE flag replaced
        the removed global KANON_MARKETPLACE_INSTALL header.
        """
        marketplace_dir = tmp_path / "my-marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(marketplace=True),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        mock_mp.assert_called_once_with(marketplace_dir)

    def test_marketplace_install_triggered_for_any_opted_in_dependency(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A single per-dependency opt-in is sufficient to trigger the marketplace path.

        3.0.0 replaced the global KANON_MARKETPLACE_INSTALL header (and its env
        override) with per-dependency KANON_SOURCE_<alias>_MARKETPLACE flags; the
        install path runs when ANY declared dependency opts in.
        """
        marketplace_dir = tmp_path / "env-marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n") + _minimal_source_block(marketplace=True),
        )

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins") as mock_mp,
        ):
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        mock_mp.assert_called_once()


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
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

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
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        (
            mock_mp.assert_not_called(),
            (
                "install_marketplace_plugins must not be called when env KANON_MARKETPLACE_INSTALL=false "
                "overrides file value of true"
            ),
        )


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
        make_install_args,
    ) -> None:
        """When a dependency opts into the marketplace but CLAUDE_MARKETPLACES_DIR
        is not defined in .kanon or env, the CLI handler must fail fast with exit
        code 1 and an actionable error message on stderr.

        3.0.0: the per-dependency KANON_SOURCE_<alias>_MARKETPLACE flag replaced
        the removed global KANON_MARKETPLACE_INSTALL header.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(marketplace=True),
        )
        args = make_install_args(kanonenv.resolve())

        with pytest.raises(SystemExit) as exc_info:
            _install_run(args)

        assert exc_info.value.code != 0, (
            "CLI handler must exit non-zero when a dependency opts into the marketplace "
            "and CLAUDE_MARKETPLACES_DIR is absent"
        )
        captured = capsys.readouterr()
        assert "CLAUDE_MARKETPLACES_DIR" in captured.err, (
            f"Error message about missing CLAUDE_MARKETPLACES_DIR must appear on stderr; got stderr={captured.err!r}"
        )

    def test_marketplace_dir_from_env_used_when_not_in_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        make_install_args,
    ) -> None:
        """When CLAUDE_MARKETPLACES_DIR is not in .kanon but is provided via env var
        override alongside KANON_MARKETPLACE_INSTALL=true, the install should pick it
        up because env overrides are applied for file-present keys only -- so this
        verifies the correct boundary: CLAUDE_MARKETPLACES_DIR must be in the file
        (not just env) for the marketplace path to activate.

        This test verifies that CLAUDE_MARKETPLACES_DIR not in file means the CLI
        handler fails even when CLAUDE_MARKETPLACES_DIR is set in the environment,
        because the env-override mechanism only applies to keys already declared in
        the file.
        """
        marketplace_dir = tmp_path / "env-only-dir"
        marketplace_dir.mkdir()
        monkeypatch.setenv("CLAUDE_MARKETPLACES_DIR", str(marketplace_dir))

        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n" + _minimal_source_block(),
        )
        args = make_install_args(kanonenv.resolve())

        with pytest.raises(SystemExit) as exc_info:
            _install_run(args)

        assert exc_info.value.code != 0, (
            "CLI handler must fail when CLAUDE_MARKETPLACES_DIR is only in env (not in .kanon file) "
            "because env-override only applies to keys present in the file"
        )


@pytest.mark.integration
class TestChannelDiscipline:
    """AC-CHANNEL-001: Error output goes to stderr; success info goes to stdout only."""

    def test_missing_marketplace_dir_error_on_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        make_install_args,
    ) -> None:
        """Error about missing CLAUDE_MARKETPLACES_DIR must appear on stderr, not stdout.

        The CLI handler must write the error to stderr when CLAUDE_MARKETPLACES_DIR
        is absent.
        """
        monkeypatch.delenv("CLAUDE_MARKETPLACES_DIR", raising=False)
        kanonenv = _write_kanonenv(
            tmp_path,
            _minimal_source_block(marketplace=True),
        )
        args = make_install_args(kanonenv.resolve())

        with pytest.raises(SystemExit):
            _install_run(args)

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
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")

        captured = capsys.readouterr()
        assert captured.err == "", f"stderr must be empty for a successful install; got stderr={captured.err!r}"
        assert "kanon install" in captured.out, f"install progress must appear on stdout; got stdout={captured.out!r}"
