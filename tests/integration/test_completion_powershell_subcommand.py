"""Integration tests for the powershell completion target and the cmd gap.

Invokes the installed CLI via subprocess (installed-CLI surface) and the
committed completion docs, asserting the item-27 behaviors:

  - ``kanon completion cmd`` exits non-zero and names ``powershell`` (the new
    supported value) in stderr.
  - ``kanon completion powershell`` exits 0 with non-empty stdout and empty
    stderr, mirroring the bash/zsh cases.
  - ``kanon completion bash`` and ``kanon completion zsh`` stdout still match
    their committed golden snapshots byte-for-byte (no shtab regression). The
    golden comparison runs ``kanon`` only -- it never invokes a real bash/zsh
    interpreter -- so it does not depend on those shells being installed.
  - ``docs/shell-completion.md`` documents BOTH the cmd.exe no-tab-completion
    gap and the PowerShell install one-liner.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest


_REPO_ROOT: pathlib.Path = pathlib.Path(__file__).parent.parent.parent
_FIXTURES_DIR: pathlib.Path = _REPO_ROOT / "tests" / "fixtures" / "completion"
_SHELL_COMPLETION_DOC: pathlib.Path = _REPO_ROOT / "docs" / "shell-completion.md"

_CMD_NO_TAB_COMPLETION_SENTENCE: str = (
    "The legacy Windows Command Prompt (`cmd.exe`) has **no programmable\ntab-completion mechanism**"
)

_POWERSHELL_INSTALL_ONE_LINER: str = "kanon completion powershell | Out-String | Invoke-Expression"


def _run_kanon(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run the installed kanon CLI via the current interpreter's entry point."""
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        check=False,
    )


def _decode_stderr(result: subprocess.CompletedProcess[bytes]) -> str:
    """Decode captured stderr bytes as UTF-8 for substring assertions."""
    return result.stderr.decode("utf-8", errors="replace")


@pytest.mark.integration
def test_completion_cmd_exits_nonzero() -> None:
    """``kanon completion cmd`` exits non-zero (unsupported shell choice)."""
    result = _run_kanon("completion", "cmd")
    assert result.returncode != 0, (
        f"Expected non-zero exit for unsupported shell 'cmd', got {result.returncode}. "
        f"stderr: {_decode_stderr(result)!r}"
    )


@pytest.mark.integration
def test_completion_cmd_stderr_names_powershell() -> None:
    """``kanon completion cmd`` stderr names the new supported value 'powershell'.

    The argparse choice error must advertise the extended supported set so a
    user typing the unsupported 'cmd' target is pointed at 'powershell'.
    """
    result = _run_kanon("completion", "cmd")
    stderr_text = _decode_stderr(result)
    assert "powershell" in stderr_text, f"Expected 'powershell' in the cmd choice-error stderr, got: {stderr_text!r}"


@pytest.mark.integration
def test_completion_powershell_exit_zero() -> None:
    """``kanon completion powershell`` exits 0."""
    result = _run_kanon("completion", "powershell")
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {_decode_stderr(result)!r}"


@pytest.mark.integration
def test_completion_powershell_stdout_non_empty() -> None:
    """``kanon completion powershell`` writes a non-empty script to stdout."""
    result = _run_kanon("completion", "powershell")
    assert result.stdout.strip(), "stdout must not be empty for powershell completion"


@pytest.mark.integration
def test_completion_powershell_stderr_empty() -> None:
    """``kanon completion powershell`` writes nothing to stderr on success."""
    result = _run_kanon("completion", "powershell")
    assert result.stderr == b"", f"stderr must be empty, got: {result.stderr!r}"


@pytest.mark.integration
def test_completion_powershell_registers_argument_completer() -> None:
    """The emitted powershell script registers a native argument completer for kanon.

    A non-empty stdout is necessary but not sufficient; the script must be a
    real PowerShell completer, so it must contain ``Register-ArgumentCompleter``
    and reference the ``kanon`` command name.
    """
    result = _run_kanon("completion", "powershell")
    script = result.stdout.decode("utf-8")
    assert "Register-ArgumentCompleter" in script, (
        f"powershell script must register an argument completer, got: {script!r}"
    )
    assert "kanon" in script, f"powershell script must reference the kanon command, got: {script!r}"


_GOLDEN_SNAPSHOT_CASES: list[tuple[str, str]] = [
    ("bash", "expected-bash.sh"),
    ("zsh", "expected-zsh.sh"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "shell,fixture_name",
    _GOLDEN_SNAPSHOT_CASES,
    ids=[row[0] for row in _GOLDEN_SNAPSHOT_CASES],
)
def test_completion_stdout_matches_committed_golden(shell: str, fixture_name: str) -> None:
    """``kanon completion <shell>`` stdout matches its committed golden byte-for-byte.

    Guards against a shtab regression in the bash/zsh emission. The captured
    stdout from the installed CLI is compared byte-for-byte against the
    committed fixture under ``tests/fixtures/completion/``.
    """
    fixture_path = _FIXTURES_DIR / fixture_name
    expected_bytes = fixture_path.read_bytes()
    assert expected_bytes, f"Committed golden fixture {fixture_path} must not be empty"

    result = _run_kanon("completion", shell)
    assert result.returncode == 0, (
        f"[{shell}] 'kanon completion {shell}' exited {result.returncode}. stderr: {_decode_stderr(result)!r}"
    )
    assert result.stdout == expected_bytes, (
        f"[{shell}] stdout does not match committed golden '{fixture_path}'.\n"
        f"  fixture bytes  : {len(expected_bytes)}\n"
        f"  captured bytes : {len(result.stdout)}\n"
        f"  A mismatch indicates a shtab regression in the {shell} completion emission."
    )


@pytest.mark.integration
def test_shell_completion_doc_documents_cmd_gap_and_powershell_install() -> None:
    """``docs/shell-completion.md`` documents the cmd.exe gap and the pwsh install line.

    Item 27 makes both a documentation DoD: the doc must contain the cmd.exe
    no-tab-completion gap sentence AND the PowerShell install one-liner.
    """
    assert _SHELL_COMPLETION_DOC.is_file(), f"Expected documentation file at {_SHELL_COMPLETION_DOC}"
    doc_text = _SHELL_COMPLETION_DOC.read_text(encoding="utf-8")

    assert _CMD_NO_TAB_COMPLETION_SENTENCE in doc_text, (
        "docs/shell-completion.md must contain the cmd.exe no-tab-completion gap sentence "
        f"({_CMD_NO_TAB_COMPLETION_SENTENCE!r})."
    )
    assert _POWERSHELL_INSTALL_ONE_LINER in doc_text, (
        f"docs/shell-completion.md must contain the PowerShell install one-liner ({_POWERSHELL_INSTALL_ONE_LINER!r})."
    )
