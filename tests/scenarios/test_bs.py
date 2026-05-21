"""BS (Bootstrap) scenarios from `docs/integration-testing.md` §3.

Each scenario invokes `kanon bootstrap` and asserts the documented deprecation
pass criteria (exit code 3 + WARN text on stderr). The bootstrap command is a
deprecation shim on the feat/kanon-deps-work-2026-05 branch -- it exits 3 and
prints a WARN message for any non-help invocation, per spec section 4.0 /
R352-R368.

Scenarios automated:
- BS-01: List bundled packages -- exits 3 (shim)
- BS-02: Bootstrap kanon package (default output dir) -- exits 3 (shim)
- BS-03: Bootstrap kanon package with --output-dir -- exits 3 (shim)
- BS-04: Conflict -- bootstrap into dir with existing .kanon -- exits 3 (shim)
- BS-05: Unknown package name -- exits 3 (shim)
- BS-06: Blocker file at output path -- exits 3 (shim)
- BS-07: Missing parent directory for --output-dir -- exits 3 (shim)
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestBS:
    def test_bs_01_list_bundled_packages(self) -> None:
        result = run_kanon("bootstrap", "list")
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"

    def test_bs_02_bootstrap_kanon_default_output_dir(self, tmp_path: pathlib.Path) -> None:
        ws = tmp_path / "bs02"
        ws.mkdir()
        result = run_kanon("bootstrap", "kanon", cwd=ws)
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"
        assert not (ws / ".kanon").exists(), ".kanon must NOT be created (shim must not delegate)"
        assert not (ws / "kanon-readme.md").exists(), "kanon-readme.md must NOT be created (shim)"

    def test_bs_03_bootstrap_kanon_with_output_dir(self, tmp_path: pathlib.Path) -> None:
        output_dir = tmp_path / "bs03-output"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"
        assert not output_dir.exists(), f"output_dir must NOT be created (shim): {output_dir}"

    def test_bs_04_conflict_existing_kanon_file(self, tmp_path: pathlib.Path) -> None:
        existing_dir = tmp_path / "bs04"
        existing_dir.mkdir()
        (existing_dir / ".kanon").write_text("existing\n")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(existing_dir))
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"

    def test_bs_05_unknown_package_name(self) -> None:
        result = run_kanon("bootstrap", "nonexistent")
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"

    def test_bs_06_blocker_file_at_output_path(self, tmp_path: pathlib.Path) -> None:
        blocker = tmp_path / "bs06-blocker"
        blocker.write_text("")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(blocker))
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"

    def test_bs_07_missing_parent_directory(self, tmp_path: pathlib.Path) -> None:
        missing_parent = tmp_path / "nonexistent-parent" / "child"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 3, (
            f"Expected exit 3 (bootstrap shim), got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert "WARN:" in result.stderr, f"Expected WARN on stderr: {result.stderr!r}"
