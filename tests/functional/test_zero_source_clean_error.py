"""Functional tests: a zero-source .kanon must produce a clean error, not a crash.

A `.kanon` file that declares no sources (no
``KANON_SOURCE_<name>_{URL,REVISION,PATH}`` triples) is invalid. The parser
(`parse_kanonenv` -> `_discover_source_names`) correctly raises ``ValueError``.
Historically that exception escaped the per-command handlers (e.g. via
`doctor`'s `kanon_hash` recomputation, `outdated`'s top-level
`parse_kanonenv`, and `why`'s live-resolve path) and leaked a raw Python
traceback to stderr with a non-zero exit.

These subprocess tests assert the spec-canonical contract for every entry
command: a non-zero exit code, a clean human-readable error on stderr, and
NO Python traceback / no ``BUG:`` marker on either stream.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.conftest import write_lockfile_doctor_unit
from tests.functional.conftest import _run_kanon


_ZERO_SOURCE_KANON = "# zero-source workspace -- no KANON_SOURCE_* triples\nKANON_MARKETPLACE_INSTALL=false\n"


_FAKE_CATALOG_SOURCE = "file:///does/not/matter@main"


_TRACEBACK_MARKER = "Traceback (most recent call last)"
_BUG_MARKER = "BUG:"


def _write_zero_source_kanon(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write a zero-source .kanon into tmp_path and return its path."""
    kanon = tmp_path / ".kanon"
    kanon.write_text(_ZERO_SOURCE_KANON, encoding="utf-8")
    return kanon


def _assert_clean_error(result, *, command: str) -> None:
    """Assert the subprocess result is a clean, traceback-free error.

    Args:
        result: The CompletedProcess returned by _run_kanon.
        command: The command name, used only in failure diagnostics.
    """
    assert result.returncode != 0, (
        f"'kanon {command}' on a zero-source .kanon must exit non-zero; "
        f"got {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    assert _TRACEBACK_MARKER not in result.stderr, (
        f"'kanon {command}' leaked a Python traceback to stderr:\n{result.stderr}"
    )
    assert _TRACEBACK_MARKER not in result.stdout, (
        f"'kanon {command}' leaked a Python traceback to stdout:\n{result.stdout}"
    )
    assert _BUG_MARKER not in result.stderr, f"'kanon {command}' emitted a BUG: marker:\n{result.stderr}"
    assert _BUG_MARKER not in result.stdout, f"'kanon {command}' emitted a BUG: marker:\n{result.stdout}"
    combined_lower = (result.stderr + result.stdout).lower()
    assert "no sources" in combined_lower or "error" in combined_lower, (
        f"'kanon {command}' produced no recognizable clean error.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )


@pytest.mark.functional
class TestZeroSourceCleanError:
    """Every entry command must fail cleanly on a zero-source .kanon."""

    def test_doctor_zero_source_no_traceback(self, tmp_path: pathlib.Path) -> None:

        kanon = _write_zero_source_kanon(tmp_path)
        write_lockfile_doctor_unit(tmp_path)
        result = _run_kanon("doctor", "--kanon-file", str(kanon))
        _assert_clean_error(result, command="doctor")

        assert "no sources" in result.stderr.lower(), f"stderr={result.stderr!r}"

    def test_install_zero_source_no_traceback(self, tmp_path: pathlib.Path) -> None:
        kanon = _write_zero_source_kanon(tmp_path)
        result = _run_kanon("install", str(kanon))
        _assert_clean_error(result, command="install")

    def test_clean_zero_source_no_traceback(self, tmp_path: pathlib.Path) -> None:
        kanon = _write_zero_source_kanon(tmp_path)
        result = _run_kanon("clean", str(kanon))
        _assert_clean_error(result, command="clean")

    def test_why_zero_source_no_traceback(self, tmp_path: pathlib.Path) -> None:

        kanon = _write_zero_source_kanon(tmp_path)
        result = _run_kanon(
            "why",
            "any-target",
            "--kanon-file",
            str(kanon),
            "--catalog-source",
            _FAKE_CATALOG_SOURCE,
        )
        _assert_clean_error(result, command="why")

    def test_outdated_zero_source_no_traceback(self, tmp_path: pathlib.Path) -> None:
        kanon = _write_zero_source_kanon(tmp_path)
        result = _run_kanon(
            "outdated",
            "--kanon-file",
            str(kanon),
            "--catalog-source",
            _FAKE_CATALOG_SOURCE,
        )
        _assert_clean_error(result, command="outdated")
