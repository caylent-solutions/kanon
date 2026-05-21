"""Unit tests for the four 'kanon remove --force' scenarios.

Covers AC-FUNC-001 through AC-FUNC-004 from spec/cleanup-2026-05/impl-gaps-spec.md
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
