"""Unit tests for the bootstrap flag translation pure function.

Covers every translation case from the flag translation table in
spec Section 4.9 and the work unit AC-FUNC-001 through AC-FUNC-008.
"""

import argparse
import pathlib

import pytest

from kanon_cli.commands.bootstrap import (
    _NOTE_OUTPUT_DIR_ADD,
    _NOTE_OUTPUT_DIR_LIST,
    _translate_bootstrap_argv_tail,
)

_DEFAULT_OUTPUT_DIR = pathlib.Path(".")
_CATALOG_SOURCE_URL = "https://example.com/x.git@main"


def _make_args(
    package: str,
    catalog_source: str | None = None,
    output_dir: pathlib.Path = _DEFAULT_OUTPUT_DIR,
) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for translator tests.

    Args:
        package: The positional package argument value.
        catalog_source: The --catalog-source value, or None if not provided.
        output_dir: The --output-dir value (default: pathlib.Path(".")).

    Returns:
        An argparse.Namespace with the three relevant attributes set.
    """
    return argparse.Namespace(
        package=package,
        catalog_source=catalog_source,
        output_dir=output_dir,
    )


@pytest.mark.unit
class TestTranslateBootstrapArgvTailAddArm:
    """Tests for the 'add' arm (package != 'list')."""

    def test_no_flags_returns_empty_string(self) -> None:
        """AC-FUNC-002: no flags translates to empty string."""
        args = _make_args("kanon")
        result = _translate_bootstrap_argv_tail(args)
        assert result == "", f"Expected empty string, got {result!r}"

    def test_catalog_source_translated_verbatim(self) -> None:
        """AC-FUNC-003: --catalog-source is passed through byte-for-byte."""
        args = _make_args("kanon", catalog_source=_CATALOG_SOURCE_URL)
        result = _translate_bootstrap_argv_tail(args)
        assert result == f"--catalog-source {_CATALOG_SOURCE_URL}", (
            f"Expected '--catalog-source {_CATALOG_SOURCE_URL}', got {result!r}"
        )

    def test_output_dir_non_default_appends_note_add(self) -> None:
        """AC-FUNC-004: non-default --output-dir appends the 'add' arm note."""
        args = _make_args("kanon", output_dir=pathlib.Path("./scratch"))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_ADD in result, f"Expected note {_NOTE_OUTPUT_DIR_ADD!r} in result {result!r}"

    def test_output_dir_default_produces_no_note(self) -> None:
        """Default --output-dir (Path(".")) must not trigger a note line."""
        args = _make_args("kanon", output_dir=pathlib.Path("."))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_ADD not in result
        assert _NOTE_OUTPUT_DIR_LIST not in result

    def test_catalog_source_and_output_dir_combined_add_arm(self) -> None:
        """Both catalog-source and output-dir together for the add arm."""
        args = _make_args(
            "kanon",
            catalog_source=_CATALOG_SOURCE_URL,
            output_dir=pathlib.Path("./scratch"),
        )
        result = _translate_bootstrap_argv_tail(args)
        assert f"--catalog-source {_CATALOG_SOURCE_URL}" in result
        assert _NOTE_OUTPUT_DIR_ADD in result

    def test_output_dir_note_does_not_include_list_note(self) -> None:
        """The add arm must use _NOTE_OUTPUT_DIR_ADD, not _NOTE_OUTPUT_DIR_LIST."""
        args = _make_args("kanon", output_dir=pathlib.Path("./anywhere"))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_LIST not in result

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/x.git@main",
            "git@github.com:org/repo.git@v1.2.3",
            "https://gitlab.example.com/group/project.git@sha1abc",
        ],
    )
    def test_catalog_source_various_urls_verbatim(self, url: str) -> None:
        """AC-FUNC-007: the value is emitted verbatim, no shell quoting."""
        args = _make_args("kanon", catalog_source=url)
        result = _translate_bootstrap_argv_tail(args)
        assert f"--catalog-source {url}" in result


@pytest.mark.unit
class TestTranslateBootstrapArgvTailListArm:
    """Tests for the 'list' arm (package == 'list')."""

    def test_no_flags_returns_empty_string(self) -> None:
        """AC-FUNC-005 (base case): 'list' with no flags returns empty string."""
        args = _make_args("list")
        result = _translate_bootstrap_argv_tail(args)
        assert result == "", f"Expected empty string, got {result!r}"

    def test_catalog_source_translated_verbatim(self) -> None:
        """AC-FUNC-005: --catalog-source passes through for list arm too."""
        args = _make_args("list", catalog_source=_CATALOG_SOURCE_URL)
        result = _translate_bootstrap_argv_tail(args)
        assert result == f"--catalog-source {_CATALOG_SOURCE_URL}", (
            f"Expected '--catalog-source {_CATALOG_SOURCE_URL}', got {result!r}"
        )

    def test_output_dir_non_default_appends_note_list(self) -> None:
        """AC-FUNC-006: non-default --output-dir appends the 'list' arm note."""
        args = _make_args("list", output_dir=pathlib.Path("./scratch"))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_LIST in result, f"Expected note {_NOTE_OUTPUT_DIR_LIST!r} in result {result!r}"

    def test_output_dir_default_produces_no_note(self) -> None:
        """Default --output-dir must not trigger a note line for list arm."""
        args = _make_args("list", output_dir=pathlib.Path("."))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_ADD not in result
        assert _NOTE_OUTPUT_DIR_LIST not in result

    def test_output_dir_note_does_not_include_add_note(self) -> None:
        """The list arm must use _NOTE_OUTPUT_DIR_LIST, not _NOTE_OUTPUT_DIR_ADD."""
        args = _make_args("list", output_dir=pathlib.Path("./anywhere"))
        result = _translate_bootstrap_argv_tail(args)
        assert _NOTE_OUTPUT_DIR_ADD not in result

    def test_catalog_source_and_output_dir_combined_list_arm(self) -> None:
        """Both catalog-source and output-dir together for the list arm."""
        args = _make_args(
            "list",
            catalog_source=_CATALOG_SOURCE_URL,
            output_dir=pathlib.Path("./scratch"),
        )
        result = _translate_bootstrap_argv_tail(args)
        assert f"--catalog-source {_CATALOG_SOURCE_URL}" in result
        assert _NOTE_OUTPUT_DIR_LIST in result


@pytest.mark.unit
class TestTranslateBootstrapArgvTailConstants:
    """Verify the module-level note constants are correctly defined (AC-FUNC-008)."""

    def test_note_output_dir_add_contains_add(self) -> None:
        """_NOTE_OUTPUT_DIR_ADD must mention 'kanon add'."""
        assert "kanon add" in _NOTE_OUTPUT_DIR_ADD

    def test_note_output_dir_add_verbatim_text(self) -> None:
        """AC-FUNC-004 verbatim: the exact Note text for the add arm."""
        expected = (
            "Note: --output-dir has no direct equivalent in 'kanon add'; "
            "the install workspace is the current directory or KANON_WORKSPACE_DIR if set."
        )
        assert _NOTE_OUTPUT_DIR_ADD == expected

    def test_note_output_dir_list_verbatim_text(self) -> None:
        """AC-FUNC-006 verbatim: the exact Note text for the list arm."""
        expected = "Note: --output-dir has no equivalent in 'kanon list'."
        assert _NOTE_OUTPUT_DIR_LIST == expected


@pytest.mark.unit
class TestTranslateBootstrapArgvTailDeterminism:
    """AC-TEST-003: the translator must be deterministic."""

    @pytest.mark.parametrize(
        "package,catalog_source,output_dir",
        [
            ("kanon", None, pathlib.Path(".")),
            ("kanon", _CATALOG_SOURCE_URL, pathlib.Path(".")),
            ("kanon", None, pathlib.Path("./scratch")),
            ("list", None, pathlib.Path(".")),
            ("list", _CATALOG_SOURCE_URL, pathlib.Path(".")),
            ("list", None, pathlib.Path("./scratch")),
        ],
    )
    def test_identical_input_identical_output(
        self,
        package: str,
        catalog_source: str | None,
        output_dir: pathlib.Path,
    ) -> None:
        """Calling the translator twice with identical input must return equal strings."""
        args = _make_args(package, catalog_source=catalog_source, output_dir=output_dir)
        first = _translate_bootstrap_argv_tail(args)
        second = _translate_bootstrap_argv_tail(args)
        assert first == second, f"Non-deterministic: first={first!r}, second={second!r}"
