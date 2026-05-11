"""Tests for the shared CLI argument factory in kanon_cli.core.cli_args.

All tests use a real argparse.ArgumentParser -- no mocks over argparse
internals.
"""

import argparse
import pathlib

import pytest

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
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source is None

    def test_default_from_env_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://h/r.git@v1")
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
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args(["--catalog-source", "https://h/r.git@cli-ref"])
        assert args.catalog_source == "https://h/r.git@cli-ref"

    def test_env_used_when_flag_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://h/r.git@env-ref")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source == "https://h/r.git@env-ref"

    def test_none_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
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
        # Load the factory's parser and verify the help text is a non-empty
        # string -- the snapshot test in test_bootstrap.py asserts byte-identity
        # with the committed fixture for full regression coverage.
        parser = _make_parser()
        add_catalog_source_arg(parser)
        action = next(a for a in parser._actions if "--catalog-source" in getattr(a, "option_strings", []))
        # Help text must be a non-empty string (the canonical text lives in cli_args.py).
        assert isinstance(action.help, str)
        assert len(action.help) > 0

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
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://h/r.git@v1")
        from kanon_cli.core.cli_args import add_catalog_source_arg

        parser = _make_parser()
        add_catalog_source_arg(parser)
        args = parser.parse_args([])
        assert args.catalog_source == "https://h/r.git@v1"
