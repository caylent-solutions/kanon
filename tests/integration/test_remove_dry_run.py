"""Integration tests for 'kanon remove --dry-run'.

Invokes 'kanon remove <name> --dry-run' end-to-end against fixture .kanon
files and asserts on captured stdout diff and unchanged file content.

Covers:
- --dry-run prints '-' prefixed lines for removed entries (AC-FUNC-002)
- File content and mtime unchanged after --dry-run (AC-FUNC-003)
- CRLF file with three blank lines: dry-run diff + actual write behaviour
  (AC-CYCLE-001)
- Mixed-line-endings warning (AC-FUNC-005)

AC-TEST-003, AC-CYCLE-001
"""

import hashlib
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the kanon CLI via the current Python interpreter."""
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _file_sha256(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of path's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Helpers for fixture construction
# ---------------------------------------------------------------------------


_STANDARD_HEADER_LF = textwrap.dedent("""\
    GITBASE=https://example.com
    CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=true
""")

_FOO_BAR_TRIPLE_LF = (
    "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
    "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
    "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
)


def _build_crlf_fixture(
    tmp_path: pathlib.Path,
    extra_blanks_between_header_and_triple: int = 3,
) -> pathlib.Path:
    """Build a CRLF .kanon file with N blank lines between header and first source block.

    This is the AC-CYCLE-001 fixture.
    """
    header_crlf = _STANDARD_HEADER_LF.replace("\n", "\r\n")
    blanks_crlf = "\r\n" * extra_blanks_between_header_and_triple
    triple_crlf = _FOO_BAR_TRIPLE_LF.replace("\n", "\r\n")
    content = header_crlf + blanks_crlf + triple_crlf
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_bytes(content.encode("utf-8"))
    return kanon_file


# ---------------------------------------------------------------------------
# Basic dry-run integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveDryRunBasic:
    """'kanon remove <name> --dry-run' end-to-end happy-path tests."""

    def test_dry_run_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """--dry-run exits 0."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF)

        result = _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"

    def test_dry_run_prints_minus_prefixed_lines(self, tmp_path: pathlib.Path) -> None:
        """--dry-run stdout contains '-' prefixed lines for removed keys."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF)

        result = _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0
        assert "-KANON_SOURCE_foo_bar_URL=https://example.com/foo.git" in result.stdout
        assert "-KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0" in result.stdout
        assert "-KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml" in result.stdout

    def test_dry_run_file_content_unchanged(self, tmp_path: pathlib.Path) -> None:
        """File content is identical after --dry-run (byte-for-byte SHA-256 check)."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF)
        sha_before = _file_sha256(kanon_file)

        _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        sha_after = _file_sha256(kanon_file)
        assert sha_before == sha_after, "File must not be modified during --dry-run"

    def test_dry_run_file_mtime_unchanged(self, tmp_path: pathlib.Path) -> None:
        """File mtime is unchanged after --dry-run."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF)
        mtime_before = kanon_file.stat().st_mtime_ns

        _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        mtime_after = kanon_file.stat().st_mtime_ns
        assert mtime_before == mtime_after, "File mtime must not change during --dry-run"

    def test_dry_run_only_shows_removed_lines_not_header(self, tmp_path: pathlib.Path) -> None:
        """--dry-run diff does not include lines that are NOT being removed."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF)

        result = _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        assert "GITBASE" not in result.stdout
        assert "CLAUDE_MARKETPLACES_DIR" not in result.stdout
        assert "KANON_MARKETPLACE_INSTALL" not in result.stdout

    def test_dry_run_multi_source(self, tmp_path: pathlib.Path) -> None:
        """Multi-source --dry-run shows minus lines for all requested sources."""
        content = (
            _STANDARD_HEADER_LF + _FOO_BAR_TRIPLE_LF + "KANON_SOURCE_baz_qux_URL=https://example.com/baz.git\n"
            "KANON_SOURCE_baz_qux_REVISION=refs/tags/2.0.0\n"
            "KANON_SOURCE_baz_qux_PATH=repo-specs/baz-marketplace.xml\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)

        result = _run_kanon(
            [
                "remove",
                "foo_bar",
                "baz_qux",
                "--dry-run",
                "--kanon-file",
                str(kanon_file),
            ]
        )

        assert result.returncode == 0
        assert "-KANON_SOURCE_foo_bar_URL" in result.stdout
        assert "-KANON_SOURCE_baz_qux_URL" in result.stdout


# ---------------------------------------------------------------------------
# AC-CYCLE-001: CRLF fixture with three blank lines
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveDryRunACCycle001:
    """AC-CYCLE-001 end-to-end evidence.

    Fixture: CRLF file with three blank lines between header and source block.
    Verify:
    1. --dry-run shows three '-' lines AND file is unchanged.
    2. Normal remove rewrites with CRLF preserved, three-blank-line run
       collapsed to two, and exactly one trailing CRLF.
    """

    def test_dry_run_shows_three_minus_lines_and_file_unchanged(self, tmp_path: pathlib.Path) -> None:
        """--dry-run on CRLF fixture: three '-' diff lines, file unchanged."""
        kanon_file = _build_crlf_fixture(tmp_path, extra_blanks_between_header_and_triple=3)
        sha_before = _file_sha256(kanon_file)

        result = _run_kanon(["remove", "foo_bar", "--dry-run", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        # Three '-' lines in stdout
        minus_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("-")]
        assert len(minus_lines) == 3
        assert "-KANON_SOURCE_foo_bar_URL" in result.stdout
        assert "-KANON_SOURCE_foo_bar_REVISION" in result.stdout
        assert "-KANON_SOURCE_foo_bar_PATH" in result.stdout
        # File unchanged
        assert _file_sha256(kanon_file) == sha_before

    def test_normal_remove_preserves_crlf_line_endings(self, tmp_path: pathlib.Path) -> None:
        """Normal remove on CRLF fixture writes CRLF line endings back."""
        kanon_file = _build_crlf_fixture(tmp_path, extra_blanks_between_header_and_triple=3)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        result_bytes = kanon_file.read_bytes()
        # CRLF present
        assert b"\r\n" in result_bytes
        # No bare LF
        bare_lf_count = result_bytes.count(b"\n") - result_bytes.count(b"\r\n")
        assert bare_lf_count == 0, "All LF should be CRLF after write"

    def test_normal_remove_collapses_three_blank_run_to_two(self, tmp_path: pathlib.Path) -> None:
        """Normal remove collapses blank-run mid-file; trailing blanks normalise to one.

        Fixture layout (before removal):
          header (3 CRLF lines)
          [blank x3]
          foo_bar triple (3 CRLF lines)

        After removing the triple, we have: header + 3 trailing blank lines.
        The trailing-newline rule collapses all trailing blanks to exactly one
        trailing newline. The three-blank-run collapse applies to mid-file runs;
        a trailing run is handled by the trailing-newline rule.
        """
        kanon_file = _build_crlf_fixture(tmp_path, extra_blanks_between_header_and_triple=3)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        result_bytes = kanon_file.read_bytes()
        # File ends with exactly one CRLF (trailing-newline rule: collapse all trailing)
        assert result_bytes.endswith(b"\r\n"), "File must end with CRLF"
        assert not result_bytes.endswith(b"\r\n\r\n"), "Must not end with double CRLF"
        # Header lines are preserved
        result_text = result_bytes.decode("utf-8")
        assert "GITBASE=https://example.com" in result_text
        assert "KANON_MARKETPLACE_INSTALL=true" in result_text

    def test_normal_remove_mid_file_blank_run_collapses(self, tmp_path: pathlib.Path) -> None:
        """Blank-run collapse applies to mid-file runs of 3+ blank lines.

        This test uses a fixture where the blank lines appear BETWEEN two
        non-blank blocks (not at the end), so the trailing-newline rule
        does not consume them.
        """
        # Build a file where 3 blank lines appear between two kept blocks
        header_crlf = _STANDARD_HEADER_LF.replace("\n", "\r\n")
        foo_bar_triple_crlf = _FOO_BAR_TRIPLE_LF.replace("\n", "\r\n")
        other_block_crlf = "OTHER_VAR=kept\r\n"
        # 3 blank CRLF lines between the two kept blocks
        blanks_crlf = "\r\n" * 3
        content = header_crlf + foo_bar_triple_crlf + blanks_crlf + other_block_crlf
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        result_text = kanon_file.read_bytes().decode("utf-8").replace("\r\n", "\n")
        # The 3-blank run (which was between header and other block after removal)
        # must collapse to 2
        assert "\n\n\n\n" not in result_text, "Three-blank run must collapse"
        # Other block survived
        assert "OTHER_VAR=kept" in result_text

    def test_normal_remove_ends_with_exactly_one_trailing_crlf(self, tmp_path: pathlib.Path) -> None:
        """Normal remove output ends with exactly one CRLF (no extra trailing lines)."""
        kanon_file = _build_crlf_fixture(tmp_path, extra_blanks_between_header_and_triple=3)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        result_bytes = kanon_file.read_bytes()
        # File ends with exactly one CRLF
        assert result_bytes.endswith(b"\r\n"), "File must end with CRLF"
        assert not result_bytes.endswith(b"\r\n\r\n"), "File must not end with double CRLF"


# ---------------------------------------------------------------------------
# AC-CYCLE-001: mixed line-endings fixture warning
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveDryRunMixedLineEndings:
    """AC-CYCLE-001: mixed-line-endings fixture produces stderr warning."""

    def test_mixed_file_emits_warning_and_normalises_to_lf(self, tmp_path: pathlib.Path) -> None:
        """Mixed-line-endings .kanon: warning fires, output normalised to LF.

        Uses a file with exactly 3 CRLF and 3 LF endings (tie) so that
        _detect_dominant_line_ending returns None (tie), triggering the warning
        and LF normalisation.
        """
        # 3 CRLF header lines, 3 LF triple lines => count tie => warning + LF
        content = (
            "GITBASE=https://example.com\r\n"  # CRLF
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\r\n"  # CRLF
            "KANON_MARKETPLACE_INSTALL=true\r\n"  # CRLF
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"  # LF
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"  # LF
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"  # LF
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(content.encode("utf-8"))

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        # Warning on stderr
        assert "mixed line endings" in result.stderr
        assert str(kanon_file) in result.stderr
        # Output normalised to LF
        result_bytes = kanon_file.read_bytes()
        assert b"\r\n" not in result_bytes
