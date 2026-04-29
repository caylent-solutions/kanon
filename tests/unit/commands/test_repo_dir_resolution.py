"""Unit tests for resolve_repo_dir helper in kanon_cli.commands.repo.

Covers all three documented precedence cases for the repo-dir resolution:

1. Flag-only: flag value used when no KANON_REPO_DIR env var is present.
2. Env-only: KANON_REPO_DIR env var used when no flag is provided (None).
3. Flag-wins: flag value used even when KANON_REPO_DIR env var is present.
4. Neither: falls back to KANONENV_REPO_DIR_DEFAULT when neither is set.

Tests are decorated with @pytest.mark.unit.
"""

import pytest

from kanon_cli.constants import KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT


@pytest.mark.unit
class TestResolveDirFlagOnly:
    """Flag value is used when the env dict does not contain KANON_REPO_DIR."""

    def test_flag_only_returns_flag_value(self) -> None:
        """resolve_repo_dir returns the flag value when env is empty."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value="/tmp/flag-only", env={})
        assert result == "/tmp/flag-only"

    def test_flag_only_ignores_default(self) -> None:
        """resolve_repo_dir does not substitute the default when flag is set."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value="/custom/path", env={})
        assert result != KANONENV_REPO_DIR_DEFAULT
        assert result == "/custom/path"

    @pytest.mark.parametrize(
        "flag_path",
        [
            "/absolute/path",
            "relative/path",
            "/tmp/deep/nested/dir",
            "/single",
        ],
    )
    def test_flag_paths_returned_verbatim(self, flag_path: str) -> None:
        """resolve_repo_dir returns the flag path unchanged for any string."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=flag_path, env={})
        assert result == flag_path


@pytest.mark.unit
class TestResolveDirEnvOnly:
    """KANON_REPO_DIR env var is used when flag_value is None."""

    def test_env_only_returns_env_value(self) -> None:
        """resolve_repo_dir returns the env var value when flag is None."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: "/tmp/env-only"}
        result = resolve_repo_dir(flag_value=None, env=env)
        assert result == "/tmp/env-only"

    @pytest.mark.parametrize(
        "env_path",
        [
            "/absolute/env/path",
            "relative/env/path",
            "/very/deeply/nested/env/path",
        ],
    )
    def test_env_paths_returned_verbatim(self, env_path: str) -> None:
        """resolve_repo_dir returns the env var path unchanged."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: env_path}
        result = resolve_repo_dir(flag_value=None, env=env)
        assert result == env_path


@pytest.mark.unit
class TestResolveDirFlagWins:
    """Flag value wins over KANON_REPO_DIR when both are present."""

    def test_flag_wins_over_env(self) -> None:
        """resolve_repo_dir returns the flag value even when env is also set."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: "/tmp/env-A"}
        result = resolve_repo_dir(flag_value="/tmp/flag-B", env=env)
        assert result == "/tmp/flag-B"
        assert result != "/tmp/env-A"

    @pytest.mark.parametrize(
        "flag_path,env_path",
        [
            ("/flag/wins", "/env/loses"),
            ("/tmp/flag-B", "/tmp/env-A"),
            ("/override", "/default-env"),
        ],
    )
    def test_flag_always_wins_over_env(self, flag_path: str, env_path: str) -> None:
        """Flag path is always preferred over env path when both are provided."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: env_path}
        result = resolve_repo_dir(flag_value=flag_path, env=env)
        assert result == flag_path
        assert result != env_path


@pytest.mark.unit
class TestResolveDirNeitherSet:
    """When neither flag nor env is set, the documented default is returned."""

    def test_neither_set_returns_default(self) -> None:
        """resolve_repo_dir returns KANONENV_REPO_DIR_DEFAULT when nothing is set."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})
        assert result == KANONENV_REPO_DIR_DEFAULT

    def test_default_is_not_empty(self) -> None:
        """The fallback default must be a non-empty string."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})
        assert isinstance(result, str)
        assert len(result) > 0
