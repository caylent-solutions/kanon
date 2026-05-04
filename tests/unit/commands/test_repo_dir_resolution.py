"""Unit tests for resolve_repo_dir helper in kanon_cli.commands.repo.

Covers all three documented precedence cases for the repo-dir resolution:

1. Flag-only: flag value used when no KANON_REPO_DIR env var is present.
2. Env-only: KANON_REPO_DIR env var used when no flag is provided (None).
3. Flag-wins: flag value used even when KANON_REPO_DIR env var is present.
4. Neither: falls back to KANONENV_REPO_DIR_DEFAULT when neither is set.

All paths are returned as absolute paths (via os.path.abspath).

Tests are decorated with @pytest.mark.unit.
"""

import os

import pytest

from kanon_cli.constants import KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT


@pytest.mark.unit
class TestResolveDirFlagOnly:
    """Flag value is used when the env dict does not contain KANON_REPO_DIR."""

    def test_flag_only_returns_flag_value(self) -> None:
        """resolve_repo_dir returns the flag value (as absolute path) when env is empty."""
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
        "flag_path,expected",
        [
            ("/absolute/path", "/absolute/path"),
            ("/tmp/deep/nested/dir", "/tmp/deep/nested/dir"),
            ("/single", "/single"),
        ],
    )
    def test_absolute_flag_paths_returned_unchanged(self, flag_path: str, expected: str) -> None:
        """AC-1: resolve_repo_dir returns an absolute flag path unchanged."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=flag_path, env={})
        assert result == expected

    @pytest.mark.parametrize(
        "flag_path",
        [
            "relative/path",
            "subdir/other",
        ],
    )
    def test_relative_flag_paths_are_made_absolute(self, flag_path: str) -> None:
        """AC-2: resolve_repo_dir converts a relative flag path to an absolute path."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=flag_path, env={})
        assert result == os.path.abspath(flag_path)
        assert os.path.isabs(result)


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
        "env_path,expected",
        [
            ("/absolute/env/path", "/absolute/env/path"),
            ("/very/deeply/nested/env/path", "/very/deeply/nested/env/path"),
        ],
    )
    def test_absolute_env_paths_returned_unchanged(self, env_path: str, expected: str) -> None:
        """AC-3: resolve_repo_dir returns an absolute KANON_REPO_DIR value unchanged."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: env_path}
        result = resolve_repo_dir(flag_value=None, env=env)
        assert result == expected

    @pytest.mark.parametrize(
        "env_path",
        [
            "relative/env/path",
            "local/env/dir",
        ],
    )
    def test_relative_env_path_is_made_absolute(self, env_path: str) -> None:
        """AC-4: resolve_repo_dir converts a relative KANON_REPO_DIR value to an absolute path."""
        from kanon_cli.commands.repo import resolve_repo_dir

        env = {KANON_REPO_DIR_ENV: env_path}
        result = resolve_repo_dir(flag_value=None, env=env)
        assert result == os.path.abspath(env_path)
        assert os.path.isabs(result)


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
    """When neither flag nor env is set, an absolute path is returned."""

    def test_neither_set_returns_absolute_path(self) -> None:
        """AC-5: resolve_repo_dir returns os.path.abspath('.repo') when nothing is set."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})
        assert result == os.path.abspath(".repo")
        assert os.path.isabs(result)

    def test_default_is_not_empty(self) -> None:
        """The fallback default must be a non-empty absolute string."""
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})
        assert isinstance(result, str)
        assert len(result) > 0
        assert os.path.isabs(result)
