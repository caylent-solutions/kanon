"""Tests for the shared CLI argument factory in kanon_cli.core.cli_args.

All tests use a real argparse.ArgumentParser -- no mocks over argparse
internals.
"""

import argparse
import logging
import pathlib

import pytest

from kanon_cli.constants import CATALOG_SOURCES_ENV_VAR

_CLI_ARGS_PY = pathlib.Path(__file__).parent.parent.parent / "src" / "kanon_cli" / "core" / "cli_args.py"


def _make_parser() -> argparse.ArgumentParser:
    """Return a fresh ArgumentParser for each test."""
    return argparse.ArgumentParser()


@pytest.mark.unit
class TestAddCatalogSourceArgDest:
    """add_catalog_source_arg registers an argument with dest='catalog_source'."""

    def test_dest_is_catalog_source(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert hasattr(args, "catalog_source")

    def test_dest_name_exactly_catalog_source(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@main"])
        assert args.catalog_source == "https://h/r.git@main"


@pytest.mark.unit
class TestAddCatalogSourceArgMetavar:
    """add_catalog_source_arg registers the correct metavar."""

    def test_metavar_is_git_url_at_ref(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        # Retrieve the action registered for --catalog-source.
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        assert action.metavar == "<git-url>@<ref>"


@pytest.mark.unit
class TestAddCatalogSourceArgDefault:
    """add_catalog_source_arg carries a LAZY default=None (no env read at build time).

    The env var read at parser-build time was removed (E3-F1-S4-T1): a multi-source
    KANON_CATALOG_SOURCES would otherwise raise MultipleCatalogSourcesError while
    *building* the parser, crashing every command. The env is now resolved inside
    each command handler instead.
    """

    def test_default_none_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(CATALOG_SOURCES_ENV_VAR, raising=False)
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_default_none_even_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The parser default is None regardless of the env var (lazy resolution)."""
        monkeypatch.setenv(CATALOG_SOURCES_ENV_VAR, "https://h/r.git@v1")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_no_crash_when_env_lists_multiple_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Building the parser with a multi-source env var must NOT raise.

        This is the regression the lazy default fixes: a >1-source
        KANON_CATALOG_SOURCES previously raised MultipleCatalogSourcesError at
        parser-build time, making the whole CLI uninvokable.
        """
        monkeypatch.setenv(CATALOG_SOURCES_ENV_VAR, "https://h/a.git@main\nhttps://h/b.git@main")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)  # must not raise
        args = parser.parse_args([])
        assert args.catalog_source is None


@pytest.mark.unit
class TestAddCatalogSourceArgPrecedence:
    """The flag value parses verbatim; env resolution is deferred to the handler."""

    def test_cli_flag_value_parses_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_SOURCES_ENV_VAR, "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@cli-ref"])
        assert args.catalog_source == "https://h/r.git@cli-ref"

    def test_none_when_flag_absent_regardless_of_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_SOURCES_ENV_VAR, "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_none_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(CATALOG_SOURCES_ENV_VAR, raising=False)
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None


@pytest.mark.unit
class TestAddCatalogSourceArgMultiple:
    """allow_multiple=True registers a repeatable (append) --catalog-source flag."""

    def test_repeated_flags_append_into_list(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser, allow_multiple=True)
        args = parser.parse_args(
            ["--catalog-source", "https://h/a.git@main", "--catalog-source", "https://h/b.git@main"]
        )
        assert args.catalog_source == ["https://h/a.git@main", "https://h/b.git@main"]

    def test_absent_flag_is_none(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser, allow_multiple=True)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_single_flag_is_one_element_list(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser, allow_multiple=True)
        args = parser.parse_args(["--catalog-source", "https://h/a.git@main"])
        assert args.catalog_source == ["https://h/a.git@main"]


@pytest.mark.unit
class TestAddCatalogSourceArgHelpText:
    """The canonical --catalog-source help text lives in cli_args.py (single source of truth)."""

    def test_help_text_matches_canonical(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        # The canonical help text lives in cli_args.py and is the single source
        # of truth for every command that resolves a manifest repo.
        parser = _make_parser()
        add_catalog_source_arg(parser)
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        # The canonical help text defined in cli_args.py (the single source of truth):
        expected_help = (
            "Remote catalog source as '<git_url>@<ref>' where ref is a branch, "
            "tag, or 'latest'. Overrides the KANON_CATALOG_SOURCES env var. "
            "Required when KANON_CATALOG_SOURCES configures no single source."
        )
        assert action.help == expected_help

    def test_help_text_mentions_git_url_at_ref_format(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        assert "<git_url>@<ref>" in action.help

    def test_help_text_mentions_env_var(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        assert "KANON_CATALOG_SOURCES" in action.help


@pytest.mark.unit
class TestCycleEndToEnd:
    """End-to-end cycle: real argparse parser with CLI flag and env var (AC-CYCLE-001)."""

    def test_cycle_cli_flag_value(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@main"])
        assert args.catalog_source == "https://h/r.git@main"

    def test_cycle_env_var_not_read_at_build_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The env var is NOT read at parser-build time -> default stays None.

        Env resolution is deferred to the command handler (lazy default), so the
        parsed namespace carries None when the flag is absent even with the env set.
        """
        monkeypatch.setenv(CATALOG_SOURCES_ENV_VAR, "https://h/r.git@v1")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None


# ---------------------------------------------------------------------------
# Tests for add_global_flags (AC-FUNC-001 through AC-FUNC-004, AC-TEST-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddGlobalFlagsRegistration:
    """add_global_flags registers exactly --quiet, --verbose, --no-color."""

    def test_quiet_dest_registered(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert hasattr(args, "quiet")

    def test_verbose_dest_registered(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert hasattr(args, "verbose")

    def test_no_color_dest_registered(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert hasattr(args, "no_color")

    def test_defaults_are_all_false(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert args.quiet is False
        assert args.verbose is False
        assert args.no_color is False


@pytest.mark.unit
class TestAddGlobalFlagsMutualExclusion:
    """--quiet and --verbose are mutually exclusive (AC-FUNC-002)."""

    def test_quiet_and_verbose_together_exits_nonzero(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--quiet", "--verbose"])
        assert exc_info.value.code != 0

    def test_quiet_and_verbose_error_mentions_not_allowed(self, capsys: pytest.CaptureFixture[str]) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["--quiet", "--verbose"])
        captured = capsys.readouterr()
        assert "not allowed with" in captured.err


@pytest.mark.unit
class TestAddGlobalFlagsSingleFlags:
    """Single-flag paths set the correct attribute (AC-FUNC-003, AC-FUNC-004)."""

    def test_quiet_sets_quiet_true_verbose_false(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--quiet"])
        assert args.quiet is True
        assert args.verbose is False

    def test_verbose_sets_verbose_true_quiet_false(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True
        assert args.quiet is False

    def test_no_color_sets_no_color_true(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--no-color"])
        assert args.no_color is True

    def test_no_color_not_in_mutex_group_accepts_with_quiet(self) -> None:
        """--no-color is independent of the quiet/verbose mutex group (AC-FUNC-003)."""
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--quiet", "--no-color"])
        assert args.quiet is True
        assert args.no_color is True

    def test_no_color_not_in_mutex_group_accepts_with_verbose(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--verbose", "--no-color"])
        assert args.verbose is True
        assert args.no_color is True


# ---------------------------------------------------------------------------
# Tests for _apply_global_flags (AC-FUNC-005 through AC-FUNC-008, AC-TEST-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyGlobalFlagsLoggerLevel:
    """_apply_global_flags sets root logger level correctly (AC-FUNC-005)."""

    @pytest.mark.parametrize(
        ("quiet", "verbose", "expected_level"),
        [
            (True, False, logging.WARNING),
            (False, True, logging.DEBUG),
            (False, False, logging.INFO),
        ],
        ids=["quiet->WARNING", "verbose->DEBUG", "neither->INFO"],
    )
    def test_logger_level_mapping(self, quiet: bool, verbose: bool, expected_level: int) -> None:
        from kanon_cli.core.cli_args import _apply_global_flags

        args = argparse.Namespace(quiet=quiet, verbose=verbose, no_color=False)
        _apply_global_flags(args)
        assert logging.getLogger().level == expected_level


@pytest.mark.unit
class TestApplyGlobalFlagsColorPrecedence:
    """_apply_global_flags sets _NO_COLOR_ACTIVE with correct precedence (AC-FUNC-006)."""

    def test_no_color_flag_sets_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.setenv("NO_COLOR", "")
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)
        args = argparse.Namespace(quiet=False, verbose=False, no_color=True)
        _apply_global_flags(args)
        assert constants._NO_COLOR_ACTIVE is True

    def test_env_no_color_sets_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)
        args = argparse.Namespace(quiet=False, verbose=False, no_color=False)
        _apply_global_flags(args)
        assert constants._NO_COLOR_ACTIVE is True

    def test_no_color_false_env_empty_inactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.setenv("NO_COLOR", "")
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", True)
        args = argparse.Namespace(quiet=False, verbose=False, no_color=False)
        _apply_global_flags(args)
        assert constants._NO_COLOR_ACTIVE is False

    def test_no_color_env_unset_inactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", True)
        args = argparse.Namespace(quiet=False, verbose=False, no_color=False)
        _apply_global_flags(args)
        assert constants._NO_COLOR_ACTIVE is False

    def test_flag_wins_over_empty_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--no-color flag wins even when NO_COLOR env var is empty (AC-FUNC-006)."""
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.setenv("NO_COLOR", "")
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)
        args = argparse.Namespace(quiet=False, verbose=False, no_color=True)
        _apply_global_flags(args)
        assert constants._NO_COLOR_ACTIVE is True


@pytest.mark.unit
class TestApplyGlobalFlagsIdempotency:
    """_apply_global_flags is idempotent (AC-FUNC-007)."""

    def test_idempotent_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)
        args = argparse.Namespace(quiet=True, verbose=False, no_color=False)
        _apply_global_flags(args)
        level_after_first = logging.getLogger().level
        color_after_first = constants._NO_COLOR_ACTIVE
        _apply_global_flags(args)
        assert logging.getLogger().level == level_after_first
        assert constants._NO_COLOR_ACTIVE == color_after_first

    def test_idempotent_verbose_with_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kanon_cli.constants as constants
        from kanon_cli.core.cli_args import _apply_global_flags

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)
        args = argparse.Namespace(quiet=False, verbose=True, no_color=True)
        _apply_global_flags(args)
        level_after_first = logging.getLogger().level
        color_after_first = constants._NO_COLOR_ACTIVE
        _apply_global_flags(args)
        assert logging.getLogger().level == level_after_first
        assert constants._NO_COLOR_ACTIVE == color_after_first


@pytest.mark.unit
class TestApplyGlobalFlagsDefenceInDepth:
    """_apply_global_flags raises ValueError if both quiet and verbose are True (AC-FUNC-008)."""

    def test_both_flags_raises_value_error(self) -> None:
        from kanon_cli.core.cli_args import _apply_global_flags

        args = argparse.Namespace(quiet=True, verbose=True, no_color=False)
        with pytest.raises(ValueError, match="quiet") as exc_info:
            _apply_global_flags(args)
        assert "verbose" in str(exc_info.value)

    def test_error_message_names_both_flags(self) -> None:
        from kanon_cli.core.cli_args import _apply_global_flags

        args = argparse.Namespace(quiet=True, verbose=True, no_color=False)
        with pytest.raises(ValueError) as exc_info:
            _apply_global_flags(args)
        msg = str(exc_info.value)
        assert "--quiet" in msg
        assert "--verbose" in msg


# ---------------------------------------------------------------------------
# Tests for the --no-update-check global flag (spec Section 7.1 / FR-29 / AC-28)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoUpdateCheckGlobalFlag:
    """add_global_flags registers the --no-update-check global flag."""

    def test_no_update_check_dest_registered(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert hasattr(args, "no_update_check")

    def test_no_update_check_defaults_false(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args([])
        assert args.no_update_check is False

    def test_no_update_check_sets_true(self) -> None:
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--no-update-check"])
        assert args.no_update_check is True

    def test_no_update_check_independent_of_other_flags(self) -> None:
        """--no-update-check composes with --quiet and --no-color (not in any mutex group)."""
        from kanon_cli.core.cli_args import add_global_flags

        parser = _make_parser()
        add_global_flags(parser)
        args = parser.parse_args(["--quiet", "--no-color", "--no-update-check"])
        assert args.quiet is True
        assert args.no_color is True
        assert args.no_update_check is True

    def test_apply_global_flags_tolerates_namespace_without_no_update_check(self) -> None:
        """_apply_global_flags does not read no_update_check (consumed by the cli hook)."""
        from kanon_cli.core.cli_args import _apply_global_flags

        # A namespace lacking no_update_check still applies cleanly: the flag is
        # read by the update-check hook in cli.main, not by _apply_global_flags.
        args = argparse.Namespace(quiet=False, verbose=False, no_color=False)
        _apply_global_flags(args)  # must not raise AttributeError
