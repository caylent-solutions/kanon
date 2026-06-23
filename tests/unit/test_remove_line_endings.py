"""Unit tests for line-ending sniff, blank-run collapse, trailing-newline
normalisation, and comment preservation rules applied by 'kanon remove'.

Covers:
- Line-ending sniff: LF-dominant, CRLF-dominant, exactly-balanced (CRLF),
  mixed-with-warning (AC-FUNC-004, AC-FUNC-005)
- Blank-run collapse: runs of 1, 2, 3, 4, 5 lines collapse correctly
  (AC-FUNC-006)
- Trailing-newline normalisation: 0, 1, 2, 3 trailing blanks normalise to
  exactly one (AC-FUNC-007)
- Comment preservation: comments adjacent to removed keys are preserved
  byte-for-byte (AC-FUNC-008)

AC-TEST-002
"""

import pathlib

import pytest

from kanon_cli.commands.remove import (
    _apply_file_writing_rules,
    _detect_dominant_line_ending,
    run_remove,
)
import argparse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(
    names: list[str],
    kanon_file: str,
    force: bool = False,
    dry_run: bool = False,
    no_color: bool = False,
) -> argparse.Namespace:
    """Construct a Namespace matching what argparse would produce for 'kanon remove'."""
    return argparse.Namespace(
        names=names,
        kanon_file=kanon_file,
        force=force,
        dry_run=dry_run,
        no_color=no_color,
    )


# ---------------------------------------------------------------------------
# _detect_dominant_line_ending
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectDominantLineEnding:
    """_detect_dominant_line_ending() returns the dominant ending or 'mixed'."""

    @pytest.mark.parametrize(
        "raw_text,expected",
        [
            # LF-only
            ("line1\nline2\nline3\n", "\n"),
            # CRLF-only
            ("line1\r\nline2\r\nline3\r\n", "\r\n"),
            # Mixed: more LF than CRLF
            ("a\nb\nc\nd\r\n", "\n"),
            # Mixed: more CRLF than LF
            ("a\r\nb\r\nc\r\nd\n", "\r\n"),
        ],
        ids=["lf-only", "crlf-only", "mixed-lf-wins", "mixed-crlf-wins"],
    )
    def test_dominant_ending_detection(self, raw_text: str, expected: str) -> None:
        """Correctly identifies the dominant line ending."""
        result = _detect_dominant_line_ending(raw_text)
        assert result == expected

    def test_exactly_balanced_returns_crlf(self) -> None:
        """When counts are equal (tie), CRLF is treated as 'mixed' -> normalise to LF."""
        # Balanced: 2 LF, 2 CRLF -- tie case should return None (mixed)
        raw_text = "a\nb\nc\r\nd\r\n"
        result = _detect_dominant_line_ending(raw_text)
        # With exactly equal counts, neither dominates -- returns None for "mixed"
        assert result is None

    def test_no_newlines_returns_lf(self) -> None:
        """A file with no newlines at all defaults to LF."""
        result = _detect_dominant_line_ending("no newlines here")
        assert result == "\n"

    def test_single_lf_returns_lf(self) -> None:
        """A single LF line ending returns LF."""
        result = _detect_dominant_line_ending("line\n")
        assert result == "\n"

    def test_single_crlf_returns_crlf(self) -> None:
        """A single CRLF line ending returns CRLF."""
        result = _detect_dominant_line_ending("line\r\n")
        assert result == "\r\n"


# ---------------------------------------------------------------------------
# _apply_file_writing_rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyFileWritingRules:
    """_apply_file_writing_rules() applies blank-run collapse and trailing-newline rules."""

    # -- Blank-run collapse --

    @pytest.mark.parametrize(
        "run_length,expected_blank_count",
        [
            (1, 1),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2),
        ],
        ids=["run-1", "run-2", "run-3", "run-4", "run-5"],
    )
    def test_blank_run_collapse(self, run_length: int, expected_blank_count: int) -> None:
        """Runs of N blank lines between non-blank content collapse per spec."""
        blank_lines = "\n" * run_length
        text = "LINE_A=1\n" + blank_lines + "LINE_B=2\n"
        result = _apply_file_writing_rules(text, "\n")
        # Count blank lines between LINE_A and LINE_B
        segments = result.split("LINE_A=1\n", 1)
        assert len(segments) == 2
        tail = segments[1]
        before_b = tail.split("LINE_B=2\n", 1)[0]
        blank_count = before_b.count("\n")
        assert blank_count == expected_blank_count

    def test_blank_run_collapse_does_not_affect_single_blank(self) -> None:
        """A run of exactly one blank line is preserved as-is."""
        text = "A=1\n\nB=2\n"
        result = _apply_file_writing_rules(text, "\n")
        assert "A=1\n\nB=2\n" in result

    def test_blank_run_collapse_does_not_affect_two_blanks(self) -> None:
        """A run of exactly two blank lines is preserved as-is."""
        text = "A=1\n\n\nB=2\n"
        result = _apply_file_writing_rules(text, "\n")
        # Input has 2 blank lines between A and B; they must be preserved unchanged
        idx_a = result.index("A=1\n")
        idx_b = result.index("B=2\n")
        between = result[idx_a + len("A=1\n") : idx_b]
        assert between == "\n\n"

    # -- Trailing-newline normalisation --

    @pytest.mark.parametrize(
        "trailing_blank_count",
        [0, 1, 2, 3],
        ids=["trailing-0", "trailing-1", "trailing-2", "trailing-3"],
    )
    def test_trailing_newline_normalisation_lf(self, trailing_blank_count: int) -> None:
        """File always ends with exactly one LF regardless of trailing blank count."""
        base = "A=1\nB=2\n"
        # Add extra blank lines beyond the one already in base
        text = base + "\n" * trailing_blank_count
        result = _apply_file_writing_rules(text, "\n")
        assert result.endswith("B=2\n")
        # Ensure exactly one newline at the end (no trailing blanks)
        assert not result.endswith("B=2\n\n")

    def test_trailing_newline_added_when_missing_lf(self) -> None:
        """A file with no trailing newline gains exactly one LF."""
        text = "A=1"
        result = _apply_file_writing_rules(text, "\n")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    @pytest.mark.parametrize(
        "trailing_blank_count",
        [0, 1, 2, 3],
        ids=["trailing-0", "trailing-1", "trailing-2", "trailing-3"],
    )
    def test_trailing_newline_normalisation_crlf(self, trailing_blank_count: int) -> None:
        """File ends with exactly one CRLF when CRLF is dominant."""
        base = "A=1\r\nB=2\r\n"
        text = base + "\r\n" * trailing_blank_count
        result = _apply_file_writing_rules(text, "\r\n")
        assert result.endswith("B=2\r\n")
        assert not result.endswith("B=2\r\n\r\n")

    def test_trailing_newline_added_when_missing_crlf(self) -> None:
        """A CRLF file with no trailing newline gains exactly one CRLF."""
        text = "A=1\r\nB=2"
        result = _apply_file_writing_rules(text, "\r\n")
        assert result.endswith("\r\n")
        assert not result.endswith("\r\n\r\n")

    # -- Line-ending rewrite --

    def test_crlf_output_when_dominant_is_crlf(self) -> None:
        """Lines in output use CRLF when dominant is CRLF."""
        text = "A=1\r\nB=2\r\n"
        result = _apply_file_writing_rules(text, "\r\n")
        assert "\r\n" in result
        lines = result.split("\r\n")
        # All non-empty lines should be split correctly by CRLF
        assert "A=1" in lines
        assert "B=2" in lines

    def test_lf_output_when_dominant_is_lf(self) -> None:
        """Lines in output use LF when dominant is LF."""
        text = "A=1\nB=2\n"
        result = _apply_file_writing_rules(text, "\n")
        # No CRLF in output
        assert "\r\n" not in result
        assert "A=1\n" in result
        assert "B=2\n" in result


# ---------------------------------------------------------------------------
# Mixed line-endings warning (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMixedLineEndingsWarning:
    """run_remove() emits a warning to stderr when the file has mixed line endings."""

    def test_mixed_line_endings_emits_warning(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A .kanon file with mixed LF and CRLF triggers a stderr warning."""
        # Balanced mixed: 3 CRLF and 3 LF (tie -> normalise to LF)
        content = (
            "GITBASE=x\r\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\r\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\r\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stderr = capsys.readouterr().err
        assert "mixed line endings" in stderr
        assert str(kanon_file) in stderr

    def test_mixed_line_endings_output_normalised_to_lf(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """After mixed-file removal, the output file uses LF only."""
        # Balanced mixed (tie -> LF)
        content = (
            "GITBASE=x\r\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\r\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\r\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result_bytes = kanon_file.read_bytes()
        assert b"\r\n" not in result_bytes

    def test_warning_message_format(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Warning follows the spec-canonical format: '.kanon file <path> has mixed line endings; normalising to LF'."""
        content = (
            "GITBASE=x\r\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\r\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\r\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stderr = capsys.readouterr().err
        # spec-canonical: ".kanon file <path> has mixed line endings; normalising to LF"
        assert "normalising to LF" in stderr

    def test_lf_only_file_emits_no_warning(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A file with only LF endings emits no mixed-line-ending warning."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stderr = capsys.readouterr().err
        assert "mixed line endings" not in stderr

    def test_crlf_only_file_emits_no_warning(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A file with only CRLF endings emits no mixed-line-ending warning."""
        content = (
            "GITBASE=x\r\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\r\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\r\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\r\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\r\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\r\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stderr = capsys.readouterr().err
        assert "mixed line endings" not in stderr


# ---------------------------------------------------------------------------
# Comment preservation (AC-FUNC-008)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommentPreservation:
    """Comments adjacent to removed keys are preserved byte-for-byte (AC-FUNC-008)."""

    def test_comment_before_removed_key_preserved(self, tmp_path: pathlib.Path) -> None:
        """A comment line immediately before a removed key is preserved."""
        content = (
            "GITBASE=x\n"
            "# This is a comment about foo_bar\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        assert "# This is a comment about foo_bar" in result

    def test_comment_after_removed_key_preserved(self, tmp_path: pathlib.Path) -> None:
        """A comment line immediately after a removed key is preserved."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "# This trailing comment should survive\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        assert "# This trailing comment should survive" in result

    def test_comment_before_and_after_removed_key_both_preserved(self, tmp_path: pathlib.Path) -> None:
        """Comments both before and after the removed block both survive."""
        content = (
            "GITBASE=x\n"
            "# Comment before foo_bar block\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "# Comment after foo_bar block\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        assert "# Comment before foo_bar block" in result
        assert "# Comment after foo_bar block" in result

    def test_only_kanon_source_lines_removed_not_comments(self, tmp_path: pathlib.Path) -> None:
        """Only the five KANON_SOURCE_* lines are removed; all other lines survive."""
        content = (
            "GITBASE=x\n"
            "# Comment 1\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "# Comment 2 (between URL and REF)\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "# Comment 3\n"
            "OTHER_VAR=value\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        # All comments preserved
        assert "# Comment 1" in result
        assert "# Comment 2 (between URL and REF)" in result
        assert "# Comment 3" in result
        # Other var preserved
        assert "OTHER_VAR=value" in result
        # KANON_SOURCE lines removed
        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REF" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result
        assert "KANON_SOURCE_foo_bar_NAME" not in result
        assert "KANON_SOURCE_foo_bar_GITBASE" not in result


# ---------------------------------------------------------------------------
# Line-ending preservation during write (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLineEndingPreservation:
    """The output file preserves the dominant line ending of the source file."""

    def test_lf_file_written_with_lf(self, tmp_path: pathlib.Path) -> None:
        """A LF-dominant .kanon file is written back with LF line endings."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result_bytes = kanon_file.read_bytes()
        # LF present, CRLF absent
        assert b"\r\n" not in result_bytes
        assert b"\n" in result_bytes

    def test_crlf_file_written_with_crlf(self, tmp_path: pathlib.Path) -> None:
        """A CRLF-dominant .kanon file is written back with CRLF line endings."""
        content = (
            "GITBASE=x\r\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\r\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\r\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\r\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\r\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\r\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result_bytes = kanon_file.read_bytes()
        # CRLF present
        assert b"\r\n" in result_bytes
        # No bare LF (every LF should be preceded by CR)
        bare_lf_count = result_bytes.count(b"\n") - result_bytes.count(b"\r\n")
        assert bare_lf_count == 0
