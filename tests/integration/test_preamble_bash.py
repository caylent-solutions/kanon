"""Integration tests for the bash preamble shell helper functions.

Sources the bash preamble under a real bash shell and verifies:
- Each helper function is defined (via ``declare -F``).
- With ``KANON_COMPLETION_ENABLED=0``, helpers return an empty COMPREPLY
  without invoking the kanon subprocess (verified via a stub shim).
- With ``KANON_COMPLETION_ENABLED=1`` and a stub kanon that prints candidates,
  COMPREPLY is populated correctly (AC-CYCLE-001).
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap

import pytest

from kanon_cli.completions.preamble import PREAMBLE


_REQUIRED_HELPERS = [
    "_kanon_complete_catalog_entries",
    "_kanon_complete_source_names_in_kanon",
    "_kanon_complete_names_in_lockfile",
    "_kanon_complete_catalog_versions",
    "_kanon_complete_project_versions",
    "_kanon_complete_cached_catalogs",
    "_kanon_complete_add_arg",
]


def _write_preamble_file(tmp_path, content: str) -> str:
    """Write preamble content to a temp file and return its path."""
    preamble_file = tmp_path / "preamble.bash"
    preamble_file.write_text(content, encoding="utf-8")
    return str(preamble_file)


def _run_bash(script: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a bash script and return the completed process."""
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=merged_env,
    )


@pytest.mark.integration
def test_bash_preamble_syntax_check(tmp_path) -> None:
    """The bash preamble must be valid bash syntax (bash -n)."""
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["bash"])
    result = _run_bash(f"bash -n {preamble_file}")
    assert result.returncode == 0, f"bash -n failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


@pytest.mark.integration
@pytest.mark.parametrize("helper_name", _REQUIRED_HELPERS)
def test_bash_helper_is_defined_after_source(tmp_path, helper_name: str) -> None:
    """Each helper function must be defined after sourcing the bash preamble."""
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["bash"])
    script = f"source {preamble_file} && declare -F {helper_name}"
    result = _run_bash(script)
    assert result.returncode == 0, (
        f"declare -F {helper_name} failed after sourcing preamble.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert helper_name in result.stdout, f"Expected '{helper_name}' in declare -F output, got: {result.stdout!r}"


def _write_stub_kanon(tmp_path, outputs: dict[str, str] | None = None) -> str:
    """Write a stub kanon script that records calls and returns configured outputs.

    Args:
        tmp_path: Temporary directory for the stub.
        outputs: Mapping from ``__complete_*`` subcommand name to stdout output.
                 Defaults to empty output for all subcommands.

    Returns:
        Path to a directory containing the stub ``kanon`` script.
    """
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir()
    call_log = tmp_path / "kanon_calls.log"

    output_cases = ""
    if outputs:
        for subcmd, out in outputs.items():
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
def test_bash_helper_disabled_returns_empty_compreply(tmp_path, helper_name: str) -> None:
    """With KANON_COMPLETION_ENABLED=0, helpers return empty COMPREPLY and do not call kanon."""
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["bash"])
    stub_dir, call_log = _write_stub_kanon(tmp_path)

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=0
        source {preamble_file}
        COMPREPLY=()
        cur=""
        {helper_name} "$cur"
        echo "COMPREPLY_COUNT=${{#COMPREPLY[@]}}"
        """)
    result = _run_bash(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "COMPREPLY_COUNT=0" in result.stdout, (
        f"Expected empty COMPREPLY when KANON_COMPLETION_ENABLED=0, got: {result.stdout!r}"
    )

    import pathlib

    call_log_path = pathlib.Path(call_log)
    if call_log_path.exists():
        calls = call_log_path.read_text(encoding="utf-8").strip()
        assert calls == "", (
            f"Expected no kanon subprocess calls when KANON_COMPLETION_ENABLED=0, but got calls: {calls!r}"
        )


@pytest.mark.integration
def test_bash_helper_enabled_populates_compreply(tmp_path) -> None:
    """AC-CYCLE-001: With KANON_COMPLETION_ENABLED=1 and a stub kanon that prints foo/bar,
    COMPREPLY is populated with (foo bar)."""
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["bash"])
    stub_dir, _call_log = _write_stub_kanon(
        tmp_path,
        outputs={"__complete_catalog_entries": "foo\nbar\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        COMPREPLY=()
        cur=""
        _kanon_complete_catalog_entries "$cur"
        echo "COMPREPLY_COUNT=${{#COMPREPLY[@]}}"
        for item in "${{COMPREPLY[@]}}"; do
            echo "ITEM:$item"
        done
        """)
    result = _run_bash(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "COMPREPLY_COUNT=2" in result.stdout, f"Expected COMPREPLY with 2 items, got: {result.stdout!r}"
    assert "ITEM:foo" in result.stdout, f"Expected 'foo' in COMPREPLY: {result.stdout!r}"
    assert "ITEM:bar" in result.stdout, f"Expected 'bar' in COMPREPLY: {result.stdout!r}"
