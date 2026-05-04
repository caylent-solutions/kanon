"""BS (Bootstrap) scenarios from `docs/integration-testing.md` §3.

Each scenario invokes `kanon bootstrap` and asserts the documented Pass
criteria (exit code + stdout/stderr substrings). Local tmp dirs stand in for
KANON_TEST_ROOT; no network access is required.

Scenarios automated:
- BS-01: List bundled packages
- BS-02: Bootstrap kanon package (default output dir)
- BS-03: Bootstrap kanon package with --output-dir
- BS-04: Conflict -- bootstrap into dir with existing .kanon
- BS-05: Unknown package name
- BS-06: Blocker file at output path
- BS-07: Missing parent directory for --output-dir
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestBS:
    def test_bs_01_list_bundled_packages(self) -> None:
        result = run_kanon("bootstrap", "list")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "kanon" in result.stdout, f"stdout does not contain 'kanon': {result.stdout!r}"

    def test_bs_02_bootstrap_kanon_default_output_dir(self, tmp_path: pathlib.Path) -> None:
        ws = tmp_path / "bs02"
        ws.mkdir()
        result = run_kanon("bootstrap", "kanon", cwd=ws)
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert (ws / ".kanon").exists(), ".kanon was not created in the current directory"
        assert (ws / "kanon-readme.md").exists(), "kanon-readme.md was not created in the current directory"
        assert "kanon install .kanon" in result.stdout, (
            f"stdout does not contain 'kanon install .kanon': {result.stdout!r}"
        )

    def test_bs_03_bootstrap_kanon_with_output_dir(self, tmp_path: pathlib.Path) -> None:
        output_dir = tmp_path / "bs03-output"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert (output_dir / ".kanon").exists(), f".kanon was not created in {output_dir}"
        assert (output_dir / "kanon-readme.md").exists(), f"kanon-readme.md was not created in {output_dir}"

    def test_bs_04_conflict_existing_kanon_file(self, tmp_path: pathlib.Path) -> None:
        existing_dir = tmp_path / "bs04"
        existing_dir.mkdir()
        (existing_dir / ".kanon").write_text("existing\n")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(existing_dir))
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "already exist" in result.stderr, f"stderr does not contain 'already exist': {result.stderr!r}"

    def test_bs_05_unknown_package_name(self) -> None:
        result = run_kanon("bootstrap", "nonexistent")
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "Unknown package 'nonexistent'" in result.stderr, (
            f"stderr does not contain expected message: {result.stderr!r}"
        )

    def test_bs_06_blocker_file_at_output_path(self, tmp_path: pathlib.Path) -> None:
        blocker = tmp_path / "bs06-blocker"
        blocker.write_text("")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(blocker))
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "Cannot create output directory" in result.stderr, (
            f"stderr does not contain 'Cannot create output directory': {result.stderr!r}"
        )
        assert "\n" not in result.stderr.rstrip("\n"), (
            f"traceback detected -- expected single error line, got: {result.stderr!r}"
        )

    def test_bs_07_missing_parent_directory(self, tmp_path: pathlib.Path) -> None:
        missing_parent = tmp_path / "nonexistent-parent" / "child"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "parent directory" in result.stderr, f"stderr does not contain 'parent directory': {result.stderr!r}"
        expected_parent = str(tmp_path / "nonexistent-parent")
        assert expected_parent in result.stderr, (
            f"stderr does not contain missing parent path {expected_parent!r}: {result.stderr!r}"
        )
        assert "\n" not in result.stderr.rstrip("\n"), (
            f"traceback detected -- expected single error line, got: {result.stderr!r}"
        )
