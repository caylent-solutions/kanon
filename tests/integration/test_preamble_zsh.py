"""Integration tests for the zsh preamble shell helper functions.

Sources the zsh preamble under a real zsh shell and verifies:
- Each helper function is defined (via ``typeset -f``).
- With ``KANON_COMPLETION_ENABLED=0``, helpers do not invoke the kanon
  subprocess (verified via a stub shim).
- With ``KANON_COMPLETION_ENABLED=1`` and a stub kanon that prints candidates,
  compadd is called with the correct candidates (AC-CYCLE-001).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap

import pytest

from kanon_cli.completions.preamble import PREAMBLE

pytestmark = pytest.mark.skipif(
    shutil.which("zsh") is None,
    reason="zsh is not installed (e.g. Windows runners); zsh completion is validated on POSIX runners",
)

_REQUIRED_HELPERS = [
    "_kanon_complete_catalog_entries",
    "_kanon_complete_source_names_in_kanon",
    "_kanon_complete_names_in_lockfile",
    "_kanon_complete_catalog_versions",
    "_kanon_complete_project_versions",
    "_kanon_complete_cached_catalogs",
    "_kanon_complete_add_arg",
]


def _has_zsh() -> bool:
    """Return True if zsh is available on PATH."""
    result = subprocess.run(["which", "zsh"], capture_output=True, text=True)
    return result.returncode == 0


def _write_preamble_file(tmp_path, content: str) -> str:
    """Write preamble content to a temp file and return its path."""
    preamble_file = tmp_path / "preamble.zsh"
    preamble_file.write_text(content, encoding="utf-8")
    return str(preamble_file)


def _run_zsh(script: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a zsh script and return the completed process."""
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["zsh", "-c", script],
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _write_stub_kanon(tmp_path, outputs: dict[str, str] | None = None) -> tuple[str, str]:
    """Write a stub kanon script that records calls and returns configured outputs.

    Args:
        tmp_path: Temporary directory for the stub.
        outputs: Mapping from ``__complete_*`` subcommand name to stdout output.

    Returns:
        Tuple of (stub_bin_dir, call_log_path).
    """
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir()
    call_log = tmp_path / "kanon_calls.log"

    output_cases = ""
    if outputs:
        for subcmd, out in outputs.items():
            # Write output to a temp file so the stub can cat it,
            # avoiding any shell quoting issues with embedded newlines.
            out_file = tmp_path / f"out_{subcmd.lstrip('_')}.txt"
            out_file.write_text(out, encoding="utf-8")
            output_cases += f'        "{subcmd}") cat {out_file} ;;\n'

    stub_content = textwrap.dedent(f"""\
        #!/bin/bash
        # Stub kanon that logs invocations and returns configured outputs.
        echo "$@" >> {call_log}
        subcommand="${{1:-}}"
        case "$subcommand" in
        {output_cases}
            *) ;;
        esac
        """)
    stub_path = stub_dir / "kanon"
    stub_path.write_text(stub_content, encoding="utf-8")
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(stub_dir), str(call_log)


@pytest.mark.integration
def test_zsh_preamble_syntax_check(tmp_path) -> None:
    """The zsh preamble must be valid zsh syntax (zsh -n)."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    result = _run_zsh(f"zsh -n {preamble_file}")
    assert result.returncode == 0, f"zsh -n failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


@pytest.mark.integration
@pytest.mark.parametrize("helper_name", _REQUIRED_HELPERS)
def test_zsh_helper_is_defined_after_source(tmp_path, helper_name: str) -> None:
    """Each helper function must be defined after sourcing the zsh preamble."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    script = f'source {preamble_file} && typeset -f {helper_name} > /dev/null 2>&1 && echo "DEFINED:{helper_name}"'
    result = _run_zsh(script)
    assert result.returncode == 0, (
        f"typeset -f {helper_name} failed after sourcing preamble.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert f"DEFINED:{helper_name}" in result.stdout, (
        f"Expected '{helper_name}' to be defined, stdout: {result.stdout!r}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "helper_name",
    [
        "_kanon_complete_catalog_entries",
        "_kanon_complete_source_names_in_kanon",
        "_kanon_complete_names_in_lockfile",
        "_kanon_complete_catalog_versions",
        "_kanon_complete_cached_catalogs",
    ],
)
def test_zsh_helper_disabled_returns_empty_no_subprocess(tmp_path, helper_name: str) -> None:
    """With KANON_COMPLETION_ENABLED=0, helpers do not call kanon subprocess."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(tmp_path)

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=0
        source {preamble_file}
        # Override compadd to capture calls without invoking real zsh completion.
        _captured_completions=()
        compadd() {{ _captured_completions+=("$@") }}
        cur=""
        {helper_name} "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    # Verify the stub was NOT called.
    import pathlib

    call_log_path = pathlib.Path(call_log)
    if call_log_path.exists():
        calls = call_log_path.read_text(encoding="utf-8").strip()
        assert calls == "", (
            f"Expected no kanon subprocess calls when KANON_COMPLETION_ENABLED=0, but got calls: {calls!r}"
        )


@pytest.mark.integration
def test_zsh_helper_enabled_calls_compadd(tmp_path) -> None:
    """AC-CYCLE-001 (zsh): With KANON_COMPLETION_ENABLED=1 and a stub kanon that prints
    foo/bar, compadd is called with those candidates."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, _call_log = _write_stub_kanon(
        tmp_path,
        outputs={"__complete_catalog_entries": "foo\nbar\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            # Collect non-flag arguments as candidates.
            for arg in "$@"; do
                case "$arg" in
                    -*) ;;
                    *) _captured_completions+=("$arg") ;;
                esac
            done
        }}
        cur=""
        _kanon_complete_catalog_entries "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        for item in "${{_captured_completions[@]}}"; do
            echo "ITEM:$item"
        done
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "CAPTURED_COUNT=2" in result.stdout, f"Expected 2 captured completions, got: {result.stdout!r}"
    assert "ITEM:foo" in result.stdout, f"Expected 'foo' in completions: {result.stdout!r}"
    assert "ITEM:bar" in result.stdout, f"Expected 'bar' in completions: {result.stdout!r}"
