"""Tests for the shared CLI argument factory in kanon_cli.core.cli_args.

All tests use a real argparse.ArgumentParser -- no mocks over argparse
internals.
"""

import argparse
import logging
import pathlib

import pytest

from kanon_cli.constants import CATALOG_ENV_VAR

# Source file paths for import-from-source assertions (AC-TEST-003).
_BOOTSTRAP_PY = pathlib.Path(__file__).parent.parent.parent / "src" / "kanon_cli" / "commands" / "bootstrap.py"

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
    """add_catalog_source_arg reads the default from KANON_CATALOG_SOURCE at parser-build time."""

    def test_default_none_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(CATALOG_ENV_VAR, raising=False)
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_default_from_env_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_ENV_VAR, "https://h/r.git@v1")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        # Re-import to pick up env at parser-build time.
        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source == "https://h/r.git@v1"


@pytest.mark.unit
class TestAddCatalogSourceArgPrecedence:
    """CLI flag wins over KANON_CATALOG_SOURCE env var (spec Section 4 header)."""

    def test_cli_flag_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_ENV_VAR, "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@cli-ref"])
        assert args.catalog_source == "https://h/r.git@cli-ref"

    def test_env_used_when_flag_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_ENV_VAR, "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source == "https://h/r.git@env-ref"

    def test_none_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(CATALOG_ENV_VAR, raising=False)
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None


@pytest.mark.unit
class TestAddCatalogSourceArgHelpText:
    """The help text is byte-identical to the current bootstrap.py inline definition (AC-FUNC-003)."""

    def test_help_text_matches_bootstrap_inline(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        # After the refactor, the canonical help text lives in cli_args.py.
        # Load bootstrap.py source and extract the help text passed to
        # add_catalog_source_arg -- since bootstrap.py now delegates to the
        # factory, the factory's action.help IS the canonical text.
        # We verify byte-identity by reading both definitions from source.
        parser = _make_parser()
        add_catalog_source_arg(parser)
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        # The canonical help text defined in cli_args.py (the single source of truth):
        expected_help = (
            "Remote catalog source as '<git_url>@<ref>' where ref is a branch, "
            "tag, or 'latest'. Overrides KANON_CATALOG_SOURCE env var. "
            "Default: bundled catalog."
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
        assert "KANON_CATALOG_SOURCE" in action.help


@pytest.mark.unit
class TestBootstrapImportsFactory:
    """bootstrap.py imports add_catalog_source_arg from kanon_cli.core.cli_args (AC-TEST-003)."""

    def test_bootstrap_imports_add_catalog_source_arg(self) -> None:
        source = _BOOTSTRAP_PY.read_text()
        assert "from kanon_cli.core.cli_args import add_catalog_source_arg" in source

    def test_bootstrap_does_not_have_inline_add_argument_for_catalog_source(self) -> None:
        source = _BOOTSTRAP_PY.read_text()
        # The inline add_argument call should no longer be present.
        # We check that "--catalog-source" does not appear as a string
        # argument to add_argument.
        assert 'add_argument(\n        "--catalog-source"' not in source
        assert 'add_argument("--catalog-source"' not in source


@pytest.mark.unit
class TestCycleEndToEnd:
    """End-to-end cycle: real argparse parser with CLI flag and env var (AC-CYCLE-001)."""

    def test_cycle_cli_flag_value(self) -> None:
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@main"])
        assert args.catalog_source == "https://h/r.git@main"

    def test_cycle_env_var_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CATALOG_ENV_VAR, "https://h/r.git@v1")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source == "https://h/r.git@v1"


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
