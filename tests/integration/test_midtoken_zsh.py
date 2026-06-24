"""Integration tests for the mid-token splitter in the zsh preamble.

Sources the zsh preamble under a real zsh shell and verifies routing
behaviour for all cases defined in spec Section 11.5 (same routing table
as the bash counterpart):

- ``foo``           (no @)      -> routes to _kanon_complete_catalog_entries
- ``foo@``          (empty spec) -> calls __resolve_entry_to_repo_url, routes
                                    to _kanon_complete_project_versions
- ``foo@1``         (spec)       -> routes to _kanon_complete_project_versions
- ``foo@bar@baz``   (multiple @) -> LAST-@ split: name = foo@bar, spec = baz
- ``@1.0.0``        (leading @)  -> empty name; empty output
- KANON_COMPLETION_ENABLED=0    -> returns immediately, does NOT shell out

AC-CYCLE-001 (zsh): source preamble; stub kanon responds to
__resolve_entry_to_repo_url and __complete_project_versions; invoke
_kanon_complete_add_arg "foo@" using compadd capture; assert completions
include 1.0.0 and 2.0.0.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from kanon_cli.completions.preamble import PREAMBLE

# linux_only: the suite shells out to a real zsh, a POSIX-only shell with no
# Windows equivalent, so it is deselected on the Windows CI leg. The skipif is
# retained so the suite also self-skips on any POSIX host that lacks zsh.
pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.skipif(
        shutil.which("zsh") is None,
        reason="zsh is not installed (e.g. Windows runners); zsh completion is validated on POSIX runners",
    ),
]


def _has_zsh() -> bool:
    """Return True if zsh is available on PATH."""
    result = subprocess.run(["which", "zsh"], capture_output=True, text=True)
    return result.returncode == 0


def _write_preamble_file(tmp_path: Path, content: str) -> str:
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


def _write_stub_kanon(
    tmp_path: Path,
    resolve_responses: dict[str, str] | None = None,
    complete_project_responses: dict[str, str] | None = None,
    complete_catalog_responses: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Write a stub kanon script for zsh tests that records calls and returns outputs.

    The stub handles the same three interaction modes as the bash version.

    Args:
        tmp_path: Temporary directory for the stub.
        resolve_responses: Mapping from entry name to repo URL string.
        complete_project_responses: Mapping from repo URL to newline-delimited
            version list.
        complete_catalog_responses: Mapping from prefix string to newline-
            delimited entry list.

    Returns:
        Tuple of (stub_bin_dir, call_log_path).
    """
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir()
    call_log = tmp_path / "kanon_calls.log"

    resolve_cases = ""
    if resolve_responses:
        for entry_name, repo_url in resolve_responses.items():
            out_file = tmp_path / f"resolve_{entry_name}.txt"
            out_file.write_text(repo_url + "\n", encoding="utf-8")
            resolve_cases += f'            "{entry_name}") cat {out_file} ;;\n'

    project_cases = ""
    if complete_project_responses:
        for repo_url, versions in complete_project_responses.items():
            out_file = tmp_path / f"versions_{abs(hash(repo_url))}.txt"
            out_file.write_text(versions, encoding="utf-8")
            project_cases += f'            "{repo_url}") cat {out_file} ;;\n'

    catalog_cases = ""
    if complete_catalog_responses:
        for prefix, entries in complete_catalog_responses.items():
            out_file = tmp_path / f"catalog_{abs(hash(prefix))}.txt"
            out_file.write_text(entries, encoding="utf-8")
            catalog_cases += f'            "{prefix}") cat {out_file} ;;\n'

    stub_content = textwrap.dedent(f"""\
        #!/bin/bash
        # Stub kanon recording all invocations and returning configured outputs.
        echo "$@" >> {call_log}
        subcommand="${{1:-}}"
        case "$subcommand" in
            "__resolve_entry_to_repo_url")
                entry_name="${{2:-}}"
                case "$entry_name" in
        {resolve_cases}
                    *) ;;
                esac
                ;;
            "__complete_project_versions")
                repo_url="${{2:-}}"
                case "$repo_url" in
        {project_cases}
                    *) ;;
                esac
                ;;
            "__complete_catalog_entries")
                prefix="${{2:-}}"
                case "$prefix" in
        {catalog_cases}
                    *) ;;
                esac
                ;;
            *) ;;
        esac
        """)
    stub_path = stub_dir / "kanon"
    stub_path.write_text(stub_content, encoding="utf-8")
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(stub_dir), str(call_log)


# ---------------------------------------------------------------------------
# AC-FUNC-001: no-@ routes to _kanon_complete_catalog_entries
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_no_at_routes_to_catalog_entries(tmp_path: Path) -> None:
    """AC-FUNC-001 (zsh): 'foo' (no @) routes to _kanon_complete_catalog_entries."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(
        tmp_path,
        complete_catalog_responses={"foo": "foo-entry\nfoo-tool\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    call_log_content = Path(call_log).read_text(encoding="utf-8")
    assert "__complete_catalog_entries" in call_log_content, (
        f"Expected __complete_catalog_entries call, got: {call_log_content!r}"
    )
    assert "__resolve_entry_to_repo_url" not in call_log_content, (
        "Must not call __resolve_entry_to_repo_url for no-@ token"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-002: foo@ routes to project versions with empty spec
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_at_empty_spec_routes_to_project_versions(tmp_path: Path) -> None:
    """AC-FUNC-002 (zsh): 'foo@' routes to _kanon_complete_project_versions."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    repo_url = "https://example.com/foo.git"
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(
        tmp_path,
        resolve_responses={"foo": repo_url},
        complete_project_responses={repo_url: "1.0.0\n2.0.0\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo@"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        for item in "${{_captured_completions[@]}}"; do
            echo "ITEM:$item"
        done
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    call_log_content = Path(call_log).read_text(encoding="utf-8")
    assert "__resolve_entry_to_repo_url" in call_log_content, (
        f"Expected __resolve_entry_to_repo_url call, got: {call_log_content!r}"
    )
    assert "__complete_project_versions" in call_log_content, (
        f"Expected __complete_project_versions call, got: {call_log_content!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-003: foo@1 routes to project versions with spec = "1"
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_at_spec_routes_to_project_versions_with_spec(tmp_path: Path) -> None:
    """AC-FUNC-003 (zsh): 'foo@1' routes to _kanon_complete_project_versions."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    repo_url = "https://example.com/foo.git"
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(
        tmp_path,
        resolve_responses={"foo": repo_url},
        complete_project_responses={repo_url: "1.0.0\n1.2.0\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo@1"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    call_log_content = Path(call_log).read_text(encoding="utf-8")
    assert "__resolve_entry_to_repo_url" in call_log_content, (
        f"Expected __resolve_entry_to_repo_url call, got: {call_log_content!r}"
    )
    assert "__complete_project_versions" in call_log_content, (
        f"Expected __complete_project_versions call, got: {call_log_content!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-004: multiple @ -- LAST-@ split
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_multiple_at_splits_on_last(tmp_path: Path) -> None:
    """AC-FUNC-004 (zsh): 'foo@bar@baz' splits on LAST @: name='foo@bar'."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(tmp_path)

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo@bar@baz"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    call_log_content = Path(call_log).read_text(encoding="utf-8") if Path(call_log).exists() else ""
    if "__resolve_entry_to_repo_url" in call_log_content:
        assert "foo@bar" in call_log_content, (
            f"Expected LAST-@ split: name='foo@bar', got call log: {call_log_content!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-005: leading @ -- empty name -> empty output
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_leading_at_empty_name_produces_no_completions(tmp_path: Path) -> None:
    """AC-FUNC-005 (zsh): '@1.0.0' (leading @, empty name) produces no completions."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, _call_log = _write_stub_kanon(tmp_path)

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="@1.0.0"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "CAPTURED_COUNT=0" in result.stdout, f"Expected empty completions for '@1.0.0', got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-007: KANON_COMPLETION_ENABLED=0 -- no subprocess call
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_disabled_skips_subprocess(tmp_path: Path) -> None:
    """AC-FUNC-007 (zsh): KANON_COMPLETION_ENABLED=0 suppresses all subprocess calls."""
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, call_log = _write_stub_kanon(tmp_path)

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=0
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo@"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "CAPTURED_COUNT=0" in result.stdout, (
        f"Expected empty completions when KANON_COMPLETION_ENABLED=0, got: {result.stdout!r}"
    )
    call_log_path = Path(call_log)
    if call_log_path.exists():
        calls = call_log_path.read_text(encoding="utf-8").strip()
        assert calls == "", f"Expected no kanon subprocess calls when KANON_COMPLETION_ENABLED=0, got: {calls!r}"


# ---------------------------------------------------------------------------
# AC-CYCLE-001 (zsh): end-to-end cycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_zsh_cycle_001_foo_at_produces_versions(tmp_path: Path) -> None:
    """AC-CYCLE-001 (zsh): 'foo@' produces completions 1.0.0 and 2.0.0.

    Steps:
    1. Source the zsh preamble.
    2. Install a stub kanon that maps 'foo' to 'https://example.com/foo.git'
       and returns '1.0.0\\n2.0.0\\n' for __complete_project_versions.
    3. Override compadd to capture candidates.
    4. Invoke _kanon_complete_add_arg "foo@".
    5. Assert captured completions contain 1.0.0 and 2.0.0.
    """
    if not _has_zsh():
        pytest.fail("zsh is not available on PATH -- cannot run zsh integration tests")
    repo_url = "https://example.com/foo.git"
    preamble_file = _write_preamble_file(tmp_path, PREAMBLE["zsh"])
    stub_dir, _call_log = _write_stub_kanon(
        tmp_path,
        resolve_responses={"foo": repo_url},
        complete_project_responses={repo_url: "1.0.0\n2.0.0\n"},
    )

    script = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export KANON_COMPLETION_ENABLED=1
        source {preamble_file}
        _captured_completions=()
        compadd() {{
            for arg in "$@"; do
                case "$arg" in -*) ;; *) _captured_completions+=("$arg") ;; esac
            done
        }}
        cur="foo@"
        _kanon_complete_add_arg "$cur"
        echo "CAPTURED_COUNT=${{#_captured_completions[@]}}"
        for item in "${{_captured_completions[@]}}"; do
            echo "ITEM:$item"
        done
        """)
    result = _run_zsh(script)
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "CAPTURED_COUNT=2" in result.stdout, f"Expected 2 captured completions, got: {result.stdout!r}"
    assert "ITEM:1.0.0" in result.stdout, f"Expected '1.0.0' in completions: {result.stdout!r}"
    assert "ITEM:2.0.0" in result.stdout, f"Expected '2.0.0' in completions: {result.stdout!r}"
