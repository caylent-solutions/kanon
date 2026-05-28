"""Unit tests for the unresolved-placeholder validator in core/install.py.

Covers:
- _scan_kanonenv_for_unresolved_placeholders: returns list of (line_number, token)
  tuples for every match in env-var values; skips comment and no-equals lines.
- _UNRESOLVED_PLACEHOLDER_PATTERN: compiled regex matches uppercase+underscore+pipe
  tokens in angle brackets but NOT lowercase XML element tags.
- UnresolvedPlaceholderError: exception message format.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E28 Change (b), Section 7 (error-handling), CLAUDE.md Fail-Fast.
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.install import (
    _UNRESOLVED_PLACEHOLDER_PATTERN,
    _scan_kanonenv_for_unresolved_placeholders,
    UnresolvedPlaceholderError,
)


@pytest.mark.unit
class TestUnresolvedPlaceholderPattern:
    """Regex _UNRESOLVED_PLACEHOLDER_PATTERN matches the right tokens."""

    @pytest.mark.parametrize(
        "token",
        [
            "<YOUR_GIT_ORG_BASE_URL>",
            "<GITBASE>",
            "<SOME_UPPER_VALUE>",
            "<A_B_C>",
            "<A|B|C>",
            "<TRUE_OR_FALSE>",
        ],
    )
    def test_matches_uppercase_placeholder(self, token: str) -> None:
        assert _UNRESOLVED_PLACEHOLDER_PATTERN.search(token) is not None, (
            f"Pattern should match placeholder token {token!r} but did not."
        )

    @pytest.mark.parametrize(
        "non_token",
        [
            "<remote>",
            "<default>",
            "<project>",
            "<include>",
            "<manifest>",
            "<true|false>",
            "just text",
            "key=value",
        ],
    )
    def test_does_not_match_lowercase_or_mixed_tokens(self, non_token: str) -> None:
        assert _UNRESOLVED_PLACEHOLDER_PATTERN.search(non_token) is None, (
            f"Pattern should NOT match {non_token!r} but did."
        )


@pytest.mark.unit
class TestScanKanonenvForUnresolvedPlaceholders:
    """_scan_kanonenv_for_unresolved_placeholders returns correct findings."""

    def test_returns_empty_list_when_no_placeholders(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text(
            "GITBASE=https://github.com/my-org\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_foo_URL=https://github.com/my-org/catalog.git@main\n"
        )
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert result == [], f"Expected no findings but got: {result}"

    def test_detects_single_placeholder_on_correct_line(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
        )
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert len(result) == 1, f"Expected 1 finding, got {len(result)}: {result}"
        line_number, token = result[0]
        assert line_number == 1, f"Expected line 1, got {line_number}"
        assert token == "<YOUR_GIT_ORG_BASE_URL>", f"Unexpected token: {token!r}"

    def test_detects_multiple_placeholders_across_lines(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "KANON_EXTRA=<ANOTHER_PLACEHOLDER>\n"
        )
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert len(result) == 2, f"Expected 2 findings, got {len(result)}: {result}"
        assert result[0] == (1, "<YOUR_GIT_ORG_BASE_URL>"), f"Unexpected first finding: {result[0]}"
        assert result[1] == (2, "<ANOTHER_PLACEHOLDER>"), f"Unexpected second finding: {result[1]}"

    def test_skips_comment_lines(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text(
            "# GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "GITBASE=https://github.com/my-org\n"
        )
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert result == [], f"Comment lines should be skipped, got: {result}"

    def test_skips_lines_without_equals(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text(
            "[catalog]\n"
            "GITBASE=https://github.com/my-org\n"
        )
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert result == [], f"Lines without '=' should be skipped, got: {result}"

    def test_multiple_placeholders_on_same_line(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text("COMBINED=<FIRST_VAL>-<SECOND_VAL>\n")
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert len(result) == 2, f"Expected 2 findings on same line, got {len(result)}: {result}"
        assert result[0] == (1, "<FIRST_VAL>"), f"Unexpected first finding: {result[0]}"
        assert result[1] == (1, "<SECOND_VAL>"), f"Unexpected second finding: {result[1]}"

    def test_does_not_match_lowercase_xml_element_in_value(self, tmp_path: pathlib.Path) -> None:
        kanon = tmp_path / ".kanon"
        kanon.write_text("SOME_KEY=<remote>\n")
        result = _scan_kanonenv_for_unresolved_placeholders(kanon)
        assert result == [], f"Lowercase XML tags should not match, got: {result}"


@pytest.mark.unit
class TestUnresolvedPlaceholderError:
    """UnresolvedPlaceholderError carries the correct message format."""

    def test_message_contains_placeholder_and_line(self) -> None:
        exc = UnresolvedPlaceholderError(line_number=3, placeholder="<YOUR_GIT_ORG_BASE_URL>")
        msg = str(exc)
        assert "unresolved placeholder" in msg, f"Message missing 'unresolved placeholder': {msg!r}"
        assert "<YOUR_GIT_ORG_BASE_URL>" in msg, f"Message missing placeholder token: {msg!r}"
        assert "3" in msg, f"Message missing line number 3: {msg!r}"

    def test_message_includes_dotkanon_reference(self) -> None:
        exc = UnresolvedPlaceholderError(line_number=1, placeholder="<GITBASE>")
        msg = str(exc)
        assert ".kanon" in msg, f"Message should reference .kanon file: {msg!r}"

    @pytest.mark.parametrize(
        "line_number,placeholder",
        [
            (1, "<YOUR_GIT_ORG_BASE_URL>"),
            (5, "<TRUE_OR_FALSE>"),
            (10, "<SOME_UPPER_VALUE>"),
        ],
    )
    def test_parametrized_message_format(self, line_number: int, placeholder: str) -> None:
        exc = UnresolvedPlaceholderError(line_number=line_number, placeholder=placeholder)
        msg = str(exc)
        assert placeholder in msg, f"Placeholder {placeholder!r} not in message: {msg!r}"
        assert str(line_number) in msg, f"Line number {line_number} not in message: {msg!r}"

    def test_is_subclass_of_install_error(self) -> None:
        from kanon_cli.core.install import InstallError
        exc = UnresolvedPlaceholderError(line_number=1, placeholder="<X>")
        assert isinstance(exc, InstallError), (
            "UnresolvedPlaceholderError must be a subclass of InstallError"
        )
