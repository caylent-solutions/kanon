"""Snapshot tests for generated bash and zsh shell completion scripts.

Runs ``kanon completion bash`` and ``kanon completion zsh`` via subprocess,
pre-flight checks the output with the appropriate shell's syntax checker, and
asserts the captured stdout matches the corresponding golden fixture file
byte-for-byte.

Fixture files live under ``tests/fixtures/completion/``:

- ``expected-bash.sh`` -- verbatim stdout of ``kanon completion bash``
- ``expected-zsh.sh``  -- verbatim stdout of ``kanon completion zsh``

To refresh the fixtures after a completion-script change, run::

    make update-completion-snapshots

All tests are decorated with ``@pytest.mark.functional``.
"""

import pathlib
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Directory that holds completion fixture files.  Resolved relative to this
# source file so the harness works regardless of the invocation cwd.
_FIXTURES_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "fixtures" / "completion"

# Makefile command that regenerates both fixture files.
_REFRESH_COMMAND: str = "make update-completion-snapshots"

# Parametrized cases: (shell, fixture_filename)
_COMPLETION_CASES: list[tuple[str, str]] = [
    ("bash", "expected-bash.sh"),
    ("zsh", "expected-zsh.sh"),
]

# Shell binary used for the ``-n`` syntax check per case.
_SYNTAX_CHECK_SHELL: dict[str, str] = {
    "bash": "bash",
    "zsh": "zsh",
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_kanon_completion(shell: str) -> subprocess.CompletedProcess[bytes]:
    """Invoke ``kanon completion <shell>`` via subprocess and return the result.

    Args:
        shell: The target shell name (``"bash"`` or ``"zsh"``).

    Returns:
        The :class:`subprocess.CompletedProcess` object with captured output.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "completion", shell],
        capture_output=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.parametrize(
    "shell,fixture_name",
    _COMPLETION_CASES,
    ids=[row[0] for row in _COMPLETION_CASES],
)
def test_completion_snapshot_syntax_check(shell: str, fixture_name: str) -> None:
    """Pre-flight syntax check: generated script must pass ``<shell> -n``.

    Captures the current ``kanon completion <shell>`` output and verifies
    it is syntactically valid according to the target shell's built-in
    syntax checker before any byte comparison is attempted.

    AC-FUNC-008 / AC-FUNC-009.

    Args:
        shell: Target shell name (``"bash"`` or ``"zsh"``).
        fixture_name: Fixture file name (unused here, kept for parametrize
            alignment with the snapshot test).
    """
    result = _run_kanon_completion(shell)

    assert result.returncode == 0, (
        f"[{shell}] 'kanon completion {shell}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
    )

    shell_binary = _SYNTAX_CHECK_SHELL[shell]
    syntax_result = subprocess.run(
        [shell_binary, "-n"],
        input=result.stdout,
        capture_output=True,
        check=False,
    )

    assert syntax_result.returncode == 0, (
        f"[{shell}] Generated {shell} completion script failed '{shell_binary} -n'.\n"
        f"  syntax-check stderr: {syntax_result.stderr!r}\n"
        f"  To regenerate: {_REFRESH_COMMAND}"
    )


@pytest.mark.functional
@pytest.mark.parametrize(
    "shell,fixture_name",
    _COMPLETION_CASES,
    ids=[row[0] for row in _COMPLETION_CASES],
)
def test_completion_snapshot_matches_fixture(shell: str, fixture_name: str) -> None:
    """Byte-for-byte snapshot assertion: live output must equal the fixture.

    Captures the current ``kanon completion <shell>`` output and compares it
    against the golden fixture file.  On mismatch the assertion message names
    the exact Makefile command to refresh the fixture.

    AC-FUNC-003 / AC-FUNC-004 / AC-FUNC-005.

    Args:
        shell: Target shell name (``"bash"`` or ``"zsh"``).
        fixture_name: File name inside ``_FIXTURES_DIR`` containing the
            expected bytes.
    """
    fixture_path = _FIXTURES_DIR / fixture_name
    expected_bytes = fixture_path.read_bytes()

    result = _run_kanon_completion(shell)

    assert result.returncode == 0, (
        f"[{shell}] 'kanon completion {shell}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
    )

    assert result.stdout == expected_bytes, (
        f"[{shell}] stdout does not match fixture '{fixture_path}'.\n"
        f"  fixture bytes  : {len(expected_bytes)}\n"
        f"  captured bytes : {len(result.stdout)}\n"
        f"  Run '{_REFRESH_COMMAND}' to update the fixture, then commit the result."
    )
