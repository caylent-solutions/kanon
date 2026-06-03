"""Unit tests for the four 'kanon remove --force' scenarios.

Covers AC-FUNC-001 through AC-FUNC-004 from the cleanup-2026-05 impl-gaps spec,
section 4.1 (R225 acceptance criteria AC-1.1 through AC-1.5):

- AC-FUNC-001: unknown-only + --force exits 0, file unchanged (spec AC-1.1)
- AC-FUNC-002: known + unknown + --force removes known, exits 0 (spec AC-1.2)
- AC-FUNC-003: unknown without --force exits 1, canonical stderr, file unchanged (spec AC-1.3)
- AC-FUNC-004: unknown + --dry-run + --force exits 0, empty diff, file unchanged (spec AC-1.5)

AC-TEST-001
"""

import argparse
import pathlib

import pytest

from kanon_cli.commands.remove import run_remove


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_args(
    names: list[str],
    kanon_file: str,
    force: bool = False,
    dry_run: bool = False,
) -> argparse.Namespace:
    """Construct a Namespace matching what argparse produces for 'kanon remove'."""
    return argparse.Namespace(
        names=names,
        kanon_file=kanon_file,
        force=force,
        dry_run=dry_run,
        no_color=False,
    )


_KNOWN_A_TRIPLE = (
    "KANON_SOURCE_known_a_URL=https://example.com/known_a.git\n"
    "KANON_SOURCE_known_a_REVISION=refs/tags/1.0.0\n"
    "KANON_SOURCE_known_a_PATH=repo-specs/known_a.xml\n"
)

_KNOWN_B_TRIPLE = (
    "KANON_SOURCE_known_b_URL=https://example.com/known_b.git\n"
    "KANON_SOURCE_known_b_REVISION=refs/tags/2.0.0\n"
    "KANON_SOURCE_known_b_PATH=repo-specs/known_b.xml\n"
)

_HEADER = "GITBASE=https://git.example.com\n"

# Fixture content: header + known_a triple + known_b triple
_TWO_KNOWN_CONTENT = _HEADER + _KNOWN_A_TRIPLE + _KNOWN_B_TRIPLE


# ---------------------------------------------------------------------------
# Parametrized test function for the four AC-FUNC scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "names,force,dry_run,kanon_content,expected_exit_code,expected_stderr_substr,expected_file_matches_original",
    [
        pytest.param(
            ["unknown_source"],
            True,
            False,
            _TWO_KNOWN_CONTENT,
            0,
            "",
            True,
            id="AC-FUNC-001-unknown-only-force-exits-0-file-unchanged",
        ),
        pytest.param(
            ["known_a", "unknown_source"],
            True,
            False,
            _TWO_KNOWN_CONTENT,
            0,
            "",
            False,
            id="AC-FUNC-002-known-and-unknown-force-removes-known-exits-0",
        ),
        pytest.param(
            ["unknown_source"],
            False,
            False,
            _TWO_KNOWN_CONTENT,
            1,
            "not fully present in .kanon",
            True,
            id="AC-FUNC-003-unknown-no-force-exits-1-canonical-error",
        ),
        pytest.param(
            ["unknown_source"],
            True,
            True,
            _TWO_KNOWN_CONTENT,
            0,
            "",
            True,
            id="AC-FUNC-004-unknown-dry-run-force-exits-0-empty-diff-unchanged",
        ),
    ],
)
def test_remove_force_scenarios(
    names: list[str],
    force: bool,
    dry_run: bool,
    kanon_content: str,
    expected_exit_code: int,
    expected_stderr_substr: str,
    expected_file_matches_original: bool,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Parametrized test covering the four --force scenarios from spec section 4.1.

    Each entry asserts on exit code, stderr substring, and post-invocation
    file content -- all three concrete assertions capable of failing.

    Args:
        names: Source names passed to remove.
        force: Whether to set the --force flag.
        dry_run: Whether to set the --dry-run flag.
        kanon_content: Content to write to the fixture .kanon file.
        expected_exit_code: Expected return value from run_remove.
        expected_stderr_substr: Substring expected in stderr (empty string means not checked).
        expected_file_matches_original: Whether the file content should be unchanged after invocation.
        tmp_path: Pytest-provided temporary directory.
        capsys: Pytest capsys fixture for capturing stdout/stderr.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(kanon_content)
    args = _make_args(names, str(kanon_file), force=force, dry_run=dry_run)

    if expected_exit_code != 0:
        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)
        assert exc_info.value.code == expected_exit_code, (
            f"Expected exit code {expected_exit_code}, got {exc_info.value.code}"
        )
    else:
        result = run_remove(args)
        assert result == expected_exit_code, f"Expected exit code {expected_exit_code}, got {result}"

    captured = capsys.readouterr()

    # Assert on stderr substring (when non-empty)
    if expected_stderr_substr:
        assert expected_stderr_substr in captured.err, (
            f"Expected '{expected_stderr_substr}' in stderr, got: {captured.err!r}"
        )
    else:
        # For --force cases: stderr must not contain "ERROR:"
        assert "ERROR:" not in captured.err, f"Expected no ERROR in stderr for force scenario, got: {captured.err!r}"

    # Assert on post-invocation file content
    if expected_file_matches_original:
        assert kanon_file.read_text() == kanon_content, (
            "File content must be byte-for-byte unchanged when no successful removal occurred"
        )
    else:
        # AC-FUNC-002: known_a triple must be removed, file must differ
        after = kanon_file.read_text()
        assert "KANON_SOURCE_known_a_URL" not in after, (
            "known_a triple must be removed when it is fully present and --force is set"
        )
        assert "KANON_SOURCE_known_a_REVISION" not in after
        assert "KANON_SOURCE_known_a_PATH" not in after
        assert "GITBASE=https://git.example.com" in after, "Non-removed header lines must be preserved"

    # AC-FUNC-004 additional assertion: dry-run + force produces no '-' lines in stdout
    if dry_run and force:
        assert not any(line.startswith("-") for line in captured.out.splitlines()), (
            "dry-run + force with unknown-only source must produce no '-' diff lines in stdout"
        )


# ---------------------------------------------------------------------------
# Named test functions required by AC-TEST-001 (test-gaps-spec.md section 4.4)
# Each function covers exactly one of the four row-65 scenarios and asserts
# the full contract from spec section 4.4: setup, invocation, exit code,
# stderr content, and file state.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_force_on_unknown_source_exits_0(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario 1: kanon remove unknown_source --force on a .kanon with no unknown keys.

    Setup: .kanon contains only KANON_SOURCE_known_source_{URL,REVISION,PATH} triples.
    Invocation: kanon remove unknown_source --force
    Assertion: exit code is 0 AND .kanon content is byte-for-byte unchanged.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_TWO_KNOWN_CONTENT)
    original_bytes = kanon_file.read_bytes()

    args = _make_args(["unknown_source"], str(kanon_file), force=True, dry_run=False)
    result = run_remove(args)

    assert result == 0, f"Expected exit code 0, got {result}"
    assert kanon_file.read_bytes() == original_bytes, (
        ".kanon must be byte-for-byte unchanged when unknown source is skipped via --force"
    )
    captured = capsys.readouterr()
    assert "ERROR:" not in captured.err, (
        f"Expected no ERROR in stderr for --force on unknown source, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_force_on_mixed_known_and_unknown_removes_known(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario 2: kanon remove known_source unknown_source --force removes known, skips unknown.

    Setup: .kanon contains KANON_SOURCE_known_a_{URL,REVISION,PATH} triples.
    Invocation: kanon remove known_a unknown_source --force
    Assertion: exit code is 0 AND the three KANON_SOURCE_known_a_* lines are absent
    from the post-write .kanon AND the file write applies the existing line-ending,
    blank-run collapse, and trailing-newline normalisation rules.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_TWO_KNOWN_CONTENT)

    args = _make_args(["known_a", "unknown_source"], str(kanon_file), force=True, dry_run=False)
    result = run_remove(args)

    assert result == 0, f"Expected exit code 0, got {result}"
    after = kanon_file.read_text()
    assert "KANON_SOURCE_known_a_URL" not in after, "KANON_SOURCE_known_a_URL must be absent after removal"
    assert "KANON_SOURCE_known_a_REVISION" not in after, "KANON_SOURCE_known_a_REVISION must be absent after removal"
    assert "KANON_SOURCE_known_a_PATH" not in after, "KANON_SOURCE_known_a_PATH must be absent after removal"
    assert after != _TWO_KNOWN_CONTENT, "File must differ from original after known source removal"
    assert after.endswith("\n"), "File must end with a trailing newline per normalisation rules"
    captured = capsys.readouterr()
    assert "ERROR:" not in captured.err, (
        f"Expected no ERROR in stderr for --force on mixed sources, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_no_force_on_unknown_source_errors(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario 3: kanon remove unknown_source (no --force) errors with R232 message.

    Setup: .kanon contains only KANON_SOURCE_known_source_{URL,REVISION,PATH} triples
    (no KANON_SOURCE_unknown_source_* keys).
    Invocation: kanon remove unknown_source (--force OMITTED)
    Assertion: exit code is 1 AND stderr contains the canonical R232 message AND
    .kanon is unchanged.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_TWO_KNOWN_CONTENT)
    original_bytes = kanon_file.read_bytes()

    args = _make_args(["unknown_source"], str(kanon_file), force=False, dry_run=False)
    with pytest.raises(SystemExit) as exc_info:
        run_remove(args)

    assert exc_info.value.code == 1, f"Expected exit code 1, got {exc_info.value.code}"
    captured = capsys.readouterr()
    assert "not fully present in .kanon" in captured.err, (
        f"Expected canonical R232 message in stderr, got: {captured.err!r}"
    )
    assert "unknown_source" in captured.err or "unknown_source" in captured.err.lower(), (
        f"Expected source name in stderr, got: {captured.err!r}"
    )
    assert kanon_file.read_bytes() == original_bytes, ".kanon must be byte-for-byte unchanged on non-force error exit"


@pytest.mark.unit
def test_force_with_dry_run_no_changes(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario 4: kanon remove unknown_source --dry-run --force produces empty diff.

    Setup: .kanon contains only KANON_SOURCE_known_source_{URL,REVISION,PATH} triples
    (identical to scenario 1 setup).
    Invocation: kanon remove unknown_source --dry-run --force
    Assertion: exit code is 0 AND stdout contains no lines beginning with '-'
    (empty diff) AND .kanon is byte-for-byte unchanged.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_TWO_KNOWN_CONTENT)
    original_bytes = kanon_file.read_bytes()

    args = _make_args(["unknown_source"], str(kanon_file), force=True, dry_run=True)
    result = run_remove(args)

    assert result == 0, f"Expected exit code 0, got {result}"
    captured = capsys.readouterr()
    assert not any(line.startswith("-") for line in captured.out.splitlines()), (
        "dry-run + force with unknown-only source must produce no '-' diff lines in stdout; "
        f"got stdout: {captured.out!r}"
    )
    assert kanon_file.read_bytes() == original_bytes, (
        ".kanon must be byte-for-byte unchanged after --dry-run --force on unknown source"
    )
