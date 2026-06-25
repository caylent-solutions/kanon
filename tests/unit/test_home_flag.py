"""Unit tests for the global ``--home`` / ``--store-dir`` flag and its threading.

Covers item 12 (shared ``KANON_HOME`` store) precedence at the resolution and
CLI-plumbing layers:

- ``constants.resolve_kanon_home(override=...)`` honors precedence
  override (flag) > ``KANON_HOME`` env > ``~/.kanon`` default.
- ``cli_args.add_global_flags`` registers ``--home`` with the ``--store-dir``
  alias, both mapping to ``dest='home'`` as a ``pathlib.Path``.
- ``cli_args._apply_global_flags`` threads the parsed flag into the process
  ``KANON_HOME`` env var so every downstream ``resolve_kanon_home()`` reader
  observes the flag value, and leaves the env untouched when the flag is absent.

These are real falsifiable assertions: each test fails if the precedence is
inverted, the alias is dropped, or the threading no longer injects the env var.
"""

import argparse
import os
import pathlib

import pytest

from kanon_cli.constants import (
    KANON_HOME_DIR_NAME,
    KANON_HOME_ENV_VAR,
    resolve_kanon_home,
)
from kanon_cli.core.cli_args import _apply_global_flags, add_global_flags


def _make_parser() -> argparse.ArgumentParser:
    """Return a fresh parser carrying only the global flags under test."""
    parser = argparse.ArgumentParser(add_help=False)
    add_global_flags(parser)
    return parser


@pytest.mark.unit
class TestResolveKanonHomePrecedence:
    """resolve_kanon_home honors override (flag) > KANON_HOME env > default."""

    def test_override_wins_over_env(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit override beats a set KANON_HOME env value (precedence step 0)."""
        flag_home = tmp_path / "flag_home"
        env_home = tmp_path / "env_home"
        monkeypatch.setenv(KANON_HOME_ENV_VAR, str(env_home))

        resolved = resolve_kanon_home(override=flag_home)

        assert resolved == flag_home
        assert resolved != env_home

    def test_override_wins_over_default(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit override beats the ~/.kanon default when no env var is set."""
        monkeypatch.delenv(KANON_HOME_ENV_VAR, raising=False)
        flag_home = tmp_path / "flag_home"

        resolved = resolve_kanon_home(override=flag_home)

        assert resolved == flag_home
        assert resolved != pathlib.Path.home() / KANON_HOME_DIR_NAME

    def test_env_used_when_no_override(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With override=None, a set KANON_HOME env value is honored (precedence step 1)."""
        env_home = tmp_path / "env_home"
        monkeypatch.setenv(KANON_HOME_ENV_VAR, str(env_home))

        assert resolve_kanon_home(override=None) == env_home

    def test_default_used_when_no_override_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no override and no env value, the ~/.kanon default is returned (step 2)."""
        monkeypatch.delenv(KANON_HOME_ENV_VAR, raising=False)

        assert resolve_kanon_home(override=None) == pathlib.Path.home() / KANON_HOME_DIR_NAME

    def test_default_argument_is_none(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling with no argument is equivalent to override=None (backward compatible)."""
        env_home = tmp_path / "env_home"
        monkeypatch.setenv(KANON_HOME_ENV_VAR, str(env_home))

        assert resolve_kanon_home() == env_home


@pytest.mark.unit
class TestHomeFlagRegistration:
    """add_global_flags registers --home with the --store-dir alias as a Path."""

    def test_home_flag_parses_to_path(self, tmp_path: pathlib.Path) -> None:
        """--home <path> populates args.home as a pathlib.Path."""
        parser = _make_parser()

        args = parser.parse_args(["--home", str(tmp_path)])

        assert args.home == tmp_path
        assert isinstance(args.home, pathlib.Path)

    def test_store_dir_alias_maps_to_home(self, tmp_path: pathlib.Path) -> None:
        """--store-dir is an accepted alias mapping to the same dest as --home."""
        parser = _make_parser()

        args = parser.parse_args(["--store-dir", str(tmp_path)])

        assert args.home == tmp_path

    def test_home_defaults_to_none(self) -> None:
        """With neither flag given, args.home defaults to None (no override)."""
        parser = _make_parser()

        args = parser.parse_args([])

        assert args.home is None


@pytest.mark.unit
class TestApplyGlobalFlagsThreadsHome:
    """_apply_global_flags injects the --home flag into the process KANON_HOME env."""

    def test_flag_injected_into_env_over_existing(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A supplied --home overwrites a pre-existing KANON_HOME for the invocation."""
        flag_home = tmp_path / "flag_home"
        env_home = tmp_path / "env_home"
        monkeypatch.setenv(KANON_HOME_ENV_VAR, str(env_home))

        parser = _make_parser()
        args = parser.parse_args(["--home", str(flag_home)])
        _apply_global_flags(args)

        assert pathlib.Path(os.environ[KANON_HOME_ENV_VAR]) == flag_home
        assert resolve_kanon_home() == flag_home

    def test_no_flag_leaves_env_untouched(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without --home, a pre-existing KANON_HOME is left exactly as inherited."""
        env_home = tmp_path / "env_home"
        monkeypatch.setenv(KANON_HOME_ENV_VAR, str(env_home))

        parser = _make_parser()
        args = parser.parse_args([])
        _apply_global_flags(args)

        assert os.environ[KANON_HOME_ENV_VAR] == str(env_home)
        assert resolve_kanon_home() == env_home

    def test_no_flag_no_env_does_not_set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without --home and without a pre-existing KANON_HOME, the env var stays unset."""
        monkeypatch.delenv(KANON_HOME_ENV_VAR, raising=False)

        parser = _make_parser()
        args = parser.parse_args([])
        _apply_global_flags(args)

        assert KANON_HOME_ENV_VAR not in os.environ
