"""Unit tests for the bootstrap deprecation shim.

Verifies that:
- `kanon bootstrap list` prints the verbatim WARN text and exits with code 3.
- `kanon bootstrap <name>` prints the verbatim WARN text and exits with code 3.
- Neither path calls into `kanon_cli.core.catalog.resolve_catalog_dir`.
- `kanon_cli.core.bootstrap` is deleted (import raises ImportError).
- The private helper `_format_deprecated_warn` constructs the correct text.
"""

import argparse
import importlib

import pytest

from kanon_cli.commands.bootstrap import _format_deprecated_warn, _run, register
from kanon_cli.constants import EXIT_CODE_DEPRECATED


@pytest.mark.unit
class TestExitCodeDeprecated:
    """Verify EXIT_CODE_DEPRECATED is defined and equals 3."""

    def test_exit_code_deprecated_is_3(self) -> None:
        assert EXIT_CODE_DEPRECATED == 3

    def test_exit_code_deprecated_is_int(self) -> None:
        assert isinstance(EXIT_CODE_DEPRECATED, int)


@pytest.mark.unit
class TestCoreBootstrapModuleDeleted:
    """Verify kanon_cli.core.bootstrap no longer exists."""

    def test_import_core_bootstrap_raises_import_error(self) -> None:
        with pytest.raises(ImportError):
            importlib.import_module("kanon_cli.core.bootstrap")


@pytest.mark.unit
class TestFormatDeprecatedWarn:
    """Unit tests for the _format_deprecated_warn helper."""

    def test_list_invocation_produces_correct_warn_text(self) -> None:
        result = _format_deprecated_warn("kanon bootstrap list", "kanon list")
        assert "WARN: 'kanon bootstrap list' is deprecated. Run instead:" in result
        assert "kanon list" in result
        assert "See docs/migration-bootstrap-to-add.md." in result

    def test_name_invocation_produces_correct_warn_text(self) -> None:
        result = _format_deprecated_warn("kanon bootstrap kanon", "kanon add kanon")
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in result
        assert "kanon add kanon" in result
        assert "See docs/migration-bootstrap-to-add.md." in result

    def test_replacement_tail_is_indented(self) -> None:
        result = _format_deprecated_warn("kanon bootstrap kanon", "kanon add kanon")
        lines = result.splitlines()
        # The replacement line should be indented with spaces
        replacement_line = next(
            (ln for ln in lines if "kanon add kanon" in ln),
            None,
        )
        assert replacement_line is not None
        assert replacement_line.startswith("    "), (
            f"Expected replacement line to be indented with 4 spaces, got: {replacement_line!r}"
        )

    def test_empty_tail_still_produces_see_line(self) -> None:
        result = _format_deprecated_warn("kanon bootstrap kanon", "")
        assert "See docs/migration-bootstrap-to-add.md." in result

    @pytest.mark.parametrize(
        "invocation,tail",
        [
            ("kanon bootstrap list", "kanon list"),
            ("kanon bootstrap list", "kanon list --filter foo"),
            ("kanon bootstrap mypackage", "kanon add mypackage"),
            ("kanon bootstrap mypackage", "kanon add mypackage --catalog-source https://x.git@main"),
        ],
    )
    def test_format_warn_parametrized(self, invocation: str, tail: str) -> None:
        result = _format_deprecated_warn(invocation, tail)
        assert f"WARN: '{invocation}' is deprecated. Run instead:" in result
        assert tail in result
        assert "See docs/migration-bootstrap-to-add.md." in result


@pytest.mark.unit
class TestRunBootstrapList:
    """Verify _run for `kanon bootstrap list` raises SystemExit(3) with WARN to stderr."""

    def test_list_exits_3(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit) as exc_info:
            _run(args)
        assert exc_info.value.code == 3

    def test_list_warn_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "WARN: 'kanon bootstrap list' is deprecated. Run instead:" in captured.err

    def test_list_replacement_command_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "kanon list" in captured.err

    def test_list_see_docs_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "See docs/migration-bootstrap-to-add.md." in captured.err

    def test_list_nothing_on_stdout(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert captured.out == "", f"Expected empty stdout, got: {captured.out!r}"

    def test_list_does_not_call_resolve_catalog_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel_called = []

        def _sentinel_resolve_catalog_dir(*args, **kwargs):
            sentinel_called.append(True)
            raise AssertionError("resolve_catalog_dir must not be called by the shim")

        monkeypatch.setattr(
            "kanon_cli.core.catalog.resolve_catalog_dir",
            _sentinel_resolve_catalog_dir,
        )
        args = argparse.Namespace(package="list", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        assert sentinel_called == [], "resolve_catalog_dir was called unexpectedly"


@pytest.mark.unit
class TestRunBootstrapPackageName:
    """Verify _run for `kanon bootstrap <name>` raises SystemExit(3) with WARN to stderr."""

    def test_package_name_exits_3(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit) as exc_info:
            _run(args)
        assert exc_info.value.code == 3

    def test_package_name_warn_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in captured.err

    def test_package_name_in_replacement_command_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "kanon add kanon" in captured.err

    def test_package_name_see_docs_on_stderr(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert "See docs/migration-bootstrap-to-add.md." in captured.err

    def test_package_name_nothing_on_stdout(self, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        captured = capsys.readouterr()
        assert captured.out == "", f"Expected empty stdout, got: {captured.out!r}"

    def test_package_name_does_not_call_resolve_catalog_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel_called = []

        def _sentinel_resolve_catalog_dir(*args, **kwargs):
            sentinel_called.append(True)
            raise AssertionError("resolve_catalog_dir must not be called by the shim")

        monkeypatch.setattr(
            "kanon_cli.core.catalog.resolve_catalog_dir",
            _sentinel_resolve_catalog_dir,
        )
        args = argparse.Namespace(package="kanon", output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit):
            _run(args)
        assert sentinel_called == [], "resolve_catalog_dir was called unexpectedly"

    @pytest.mark.parametrize("package_name", ["kanon", "my-package", "acme-tools"])
    def test_various_package_names_produce_correct_warn(self, package_name: str, capsys: pytest.CaptureFixture) -> None:
        args = argparse.Namespace(package=package_name, output_dir=None, catalog_source=None)
        with pytest.raises(SystemExit) as exc_info:
            _run(args)
        assert exc_info.value.code == 3
        captured = capsys.readouterr()
        assert f"WARN: 'kanon bootstrap {package_name}' is deprecated. Run instead:" in captured.err
        assert f"kanon add {package_name}" in captured.err
        assert "See docs/migration-bootstrap-to-add.md." in captured.err


@pytest.mark.unit
class TestRegisterBootstrapParser:
    """Verify register() wires the argparse subcommand correctly (AC-FUNC-007)."""

    def test_register_adds_bootstrap_subcommand(self) -> None:
        """register() must add a 'bootstrap' subparser."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        # Verify the subparser was registered (bootstrap is in the choices dict)
        assert "bootstrap" in subparsers.choices

    def test_register_wires_run_as_default_func(self) -> None:
        """register() must set _run as the default func for the bootstrap subcommand."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        args = root.parse_args(["bootstrap", "kanon"])
        assert args.func is _run

    def test_register_parser_has_package_argument(self) -> None:
        """register() must declare the 'package' positional argument (AC-FUNC-007)."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        args = root.parse_args(["bootstrap", "mypackage"])
        assert args.package == "mypackage"

    def test_register_parser_has_output_dir_argument(self) -> None:
        """register() must declare --output-dir argument (AC-FUNC-007)."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        import pathlib

        args = root.parse_args(["bootstrap", "kanon", "--output-dir", "/tmp/test"])
        assert args.output_dir == pathlib.Path("/tmp/test")

    def test_register_parser_has_catalog_source_argument(self) -> None:
        """register() must declare --catalog-source argument (AC-FUNC-007)."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        args = root.parse_args(["bootstrap", "kanon", "--catalog-source", "https://x.git@main"])
        assert args.catalog_source == "https://x.git@main"

    def test_register_parser_description_mentions_deprecated(self) -> None:
        """The parser description must include the DEPRECATED marker."""
        root = argparse.ArgumentParser()
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        # Access the bootstrap subparser to inspect its description
        bootstrap_parser = subparsers.choices["bootstrap"]
        assert "DEPRECATED" in bootstrap_parser.description
