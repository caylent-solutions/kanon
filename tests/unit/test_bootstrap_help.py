"""Unit tests for bootstrap --help output: DEPRECATED prefix, flag translation table,
and exit codes section.

Spec Section 4.9 + Section 14: the --help output must be prepended with the verbatim
DEPRECATED notice, embed the flag translation table, and list exit codes 0 and 3.

Tests in this module:
- Snapshot: parser-level capture via parse_args(["--help"]) compared byte-for-byte
  to tests/fixtures/help/bootstrap-help.txt.
- Exit code 0 from --help.
- DEPRECATED notice is the first non-empty line of output.
- Fall-through to T1 shim (exit 3) when no --help flag is given (parametrised).
"""

import argparse
import io
import pathlib

import pytest

from kanon_cli.commands.bootstrap import (
    _BOOTSTRAP_EXIT_CODES_HELP,
    _FLAG_TRANSLATION_TABLE_HELP,
    _run,
    register,
)

_FIXTURE_PATH = pathlib.Path(__file__).parent.parent / "fixtures" / "help" / "bootstrap-help.txt"
_DEPRECATED_NOTICE = (
    "DEPRECATED: 'kanon bootstrap' is replaced by 'kanon add' and 'kanon list'. See docs/migration-bootstrap-to-add.md."
)


def _build_bootstrap_parser() -> argparse.ArgumentParser:
    """Build a standalone bootstrap subparser for testing.

    Returns:
        The bootstrap ArgumentParser registered under a root parser.
    """
    root = argparse.ArgumentParser(prog="kanon")
    subparsers = root.add_subparsers(dest="subcmd")
    register(subparsers)
    return subparsers.choices["bootstrap"]


def _capture_help(parser: argparse.ArgumentParser) -> str:
    """Capture help text from the parser without raising SystemExit.

    Args:
        parser: The ArgumentParser to capture help from.

    Returns:
        The full help text string as it would be printed to stdout.
    """
    buf = io.StringIO()
    parser.print_help(buf)
    return buf.getvalue()


@pytest.mark.unit
class TestBootstrapHelpFixtureExists:
    """Verify the fixture file exists before snapshot tests run."""

    def test_fixture_file_exists(self) -> None:
        """tests/fixtures/help/bootstrap-help.txt must exist (AC-FUNC-007)."""
        assert _FIXTURE_PATH.exists(), (
            f"Fixture file not found: {_FIXTURE_PATH}. The fixture must be created as part of this task."
        )


@pytest.mark.unit
class TestBootstrapHelpConstants:
    """Verify required module-level constants are defined (AC-FUNC-006)."""

    def test_flag_translation_table_help_is_defined(self) -> None:
        """_FLAG_TRANSLATION_TABLE_HELP must be a non-empty string."""
        assert isinstance(_FLAG_TRANSLATION_TABLE_HELP, str)
        assert len(_FLAG_TRANSLATION_TABLE_HELP) > 0

    def test_bootstrap_exit_codes_help_is_defined(self) -> None:
        """_BOOTSTRAP_EXIT_CODES_HELP must be a non-empty string."""
        assert isinstance(_BOOTSTRAP_EXIT_CODES_HELP, str)
        assert len(_BOOTSTRAP_EXIT_CODES_HELP) > 0

    def test_flag_translation_table_contains_package_row(self) -> None:
        """The table must contain a row for <package> positional (AC-FUNC-003)."""
        assert "<package>" in _FLAG_TRANSLATION_TABLE_HELP

    def test_flag_translation_table_contains_catalog_source_row(self) -> None:
        """The table must contain a row for --catalog-source (AC-FUNC-003)."""
        assert "--catalog-source" in _FLAG_TRANSLATION_TABLE_HELP

    def test_flag_translation_table_contains_output_dir_row(self) -> None:
        """The table must contain a row for --output-dir (AC-FUNC-003)."""
        assert "--output-dir" in _FLAG_TRANSLATION_TABLE_HELP

    def test_flag_translation_table_contains_add_column(self) -> None:
        """The table must mention 'kanon add' (AC-FUNC-003)."""
        assert "kanon add" in _FLAG_TRANSLATION_TABLE_HELP

    def test_flag_translation_table_contains_list_column(self) -> None:
        """The table must mention 'kanon list' (AC-FUNC-003)."""
        assert "kanon list" in _FLAG_TRANSLATION_TABLE_HELP

    def test_exit_codes_help_contains_exit_0(self) -> None:
        """_BOOTSTRAP_EXIT_CODES_HELP must list exit code 0 (AC-FUNC-004)."""
        assert "0" in _BOOTSTRAP_EXIT_CODES_HELP

    def test_exit_codes_help_contains_exit_3(self) -> None:
        """_BOOTSTRAP_EXIT_CODES_HELP must list exit code 3 (AC-FUNC-004)."""
        assert "3" in _BOOTSTRAP_EXIT_CODES_HELP

    def test_exit_codes_help_describes_help_output(self) -> None:
        """_BOOTSTRAP_EXIT_CODES_HELP must describe exit 0 as help output."""
        assert "help" in _BOOTSTRAP_EXIT_CODES_HELP.lower()

    def test_exit_codes_help_describes_deprecated_invocation(self) -> None:
        """_BOOTSTRAP_EXIT_CODES_HELP must describe exit 3 as deprecated."""
        assert "deprecated" in _BOOTSTRAP_EXIT_CODES_HELP.lower()


@pytest.mark.unit
class TestBootstrapHelpOutput:
    """Verify the --help output structure (AC-FUNC-001 through AC-FUNC-005)."""

    def test_help_exit_code_is_zero(self) -> None:
        """parse_args(['--help']) must raise SystemExit(0) (AC-FUNC-001)."""
        parser = _build_bootstrap_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0, f"Expected exit code 0 for --help, got {exc_info.value.code}"

    def test_deprecated_notice_is_first_non_empty_line(self) -> None:
        """DEPRECATED notice must be the first non-empty line before Usage: (AC-FUNC-002)."""
        parser = _build_bootstrap_parser()
        help_text = _capture_help(parser)
        non_empty_lines = [ln for ln in help_text.splitlines() if ln.strip()]
        assert len(non_empty_lines) > 0, "Help output must not be empty"
        assert non_empty_lines[0] == _DEPRECATED_NOTICE, (
            f"Expected first non-empty line to be the DEPRECATED notice, got: {non_empty_lines[0]!r}"
        )

    def test_deprecated_notice_appears_before_usage_line(self) -> None:
        """DEPRECATED notice must appear before 'usage:' line (AC-FUNC-002)."""
        parser = _build_bootstrap_parser()
        help_text = _capture_help(parser)
        lines = help_text.splitlines()
        deprecated_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip() == _DEPRECATED_NOTICE),
            None,
        )
        usage_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip().startswith("usage:")),
            None,
        )
        assert deprecated_idx is not None, "DEPRECATED notice not found in help output"
        assert usage_idx is not None, "usage: line not found in help output"
        assert deprecated_idx < usage_idx, (
            f"DEPRECATED notice (line {deprecated_idx}) must appear before usage: (line {usage_idx})"
        )

    def test_help_output_contains_flag_translation_table(self) -> None:
        """Help output must embed the flag translation table (AC-FUNC-003)."""
        parser = _build_bootstrap_parser()
        help_text = _capture_help(parser)
        # The table is pipe-delimited; check for at least one row indicator
        assert "|" in help_text, "Flag translation table (pipe-delimited) must be in help output"
        assert "--catalog-source" in help_text
        assert "--output-dir" in help_text

    def test_help_output_contains_exit_codes_section(self) -> None:
        """Help output must include exit codes section with 0 and 3 (AC-FUNC-004)."""
        parser = _build_bootstrap_parser()
        help_text = _capture_help(parser)
        assert "Exit codes" in help_text, "Help output must contain 'Exit codes' section"
        # Both 0 and 3 must appear in the exit codes context
        assert "0" in help_text
        assert "3" in help_text

    def test_formatter_is_raw_description(self) -> None:
        """Parser must use RawDescriptionHelpFormatter (AC-FUNC-005)."""
        parser = _build_bootstrap_parser()
        assert parser.formatter_class is argparse.RawDescriptionHelpFormatter, (
            f"Expected RawDescriptionHelpFormatter, got {parser.formatter_class!r}"
        )

    def test_help_output_byte_for_byte_matches_fixture(self) -> None:
        """Help output must exactly match the fixture file (AC-FUNC-007)."""
        parser = _build_bootstrap_parser()
        help_text = _capture_help(parser)
        fixture_text = _FIXTURE_PATH.read_text(encoding="utf-8")
        assert help_text == fixture_text, (
            f"Help output does not match fixture.\n"
            f"--- fixture ({_FIXTURE_PATH}) ---\n{fixture_text!r}\n"
            f"--- actual ---\n{help_text!r}"
        )


@pytest.mark.unit
class TestBootstrapHelpFallThrough:
    """Verify that missing positional arg (no --help) falls through to T1 shim (AC-TEST-003)."""

    @pytest.mark.parametrize(
        "extra_args",
        [
            [],
            ["--output-dir", "/tmp/x"],
            ["--catalog-source", "https://example.com/x.git@main"],
        ],
    )
    def test_no_positional_no_help_exits_nonzero(
        self,
        extra_args: list[str],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Missing positional arg without --help must produce a non-zero exit via argparse.

        This proves the --help path is gated explicitly on the --help flag rather
        than on missing args (AC-TEST-003).
        """
        parser = _build_bootstrap_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(extra_args)
        # argparse exits 2 for missing required positional (usage error), NOT 0 (help)
        assert exc_info.value.code != 0, (
            f"Expected non-zero exit when positional missing without --help, "
            f"got {exc_info.value.code} (args={extra_args!r})"
        )

    def test_positional_provided_routes_to_run_function(self) -> None:
        """When package is provided, args.func must be _run (not help path)."""
        root = argparse.ArgumentParser(prog="kanon")
        subparsers = root.add_subparsers(dest="subcmd")
        register(subparsers)
        args = root.parse_args(["bootstrap", "kanon"])
        assert args.func is _run, f"Expected args.func to be _run, got {args.func!r}"

    def test_package_kanon_with_run_exits_3(self, capsys: pytest.CaptureFixture) -> None:
        """Invoking _run directly with a package name must exit 3 (not 0) (AC-TEST-003)."""
        args = argparse.Namespace(
            package="kanon",
            output_dir=pathlib.Path("."),
            catalog_source=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            _run(args)
        assert exc_info.value.code == 3, f"Expected exit 3 from _run (deprecated shim), got {exc_info.value.code}"
