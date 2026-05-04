"""HV (Help/Version) scenarios from `docs/integration-testing.md` §2.

Each scenario invokes `kanon` with help/version flags and asserts the
documented Pass criteria (exit code + stdout substring). Mirrors a human
running the doc's bash blocks one-by-one.

Scenarios automated:
- HV-01: Top-level help -- `kanon --help`
- HV-02: Version flag -- `kanon --version`
- HV-03: Install subcommand help -- `kanon install --help`
- HV-04: Clean subcommand help -- `kanon clean --help`
- HV-05: Validate subcommand help -- `kanon validate --help`
- HV-06: Validate xml sub-subcommand help -- `kanon validate xml --help`
- HV-07: Validate marketplace sub-subcommand help -- `kanon validate marketplace --help`
- HV-08: Bootstrap subcommand help -- `kanon bootstrap --help`
"""

from __future__ import annotations

import re

import pytest

from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestHV:
    def test_hv_01_top_level_help(self) -> None:
        result = run_kanon("--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        for token in ("install", "clean", "validate", "bootstrap"):
            assert token in result.stdout, f"missing {token!r} in stdout"

    def test_hv_02_version_flag(self) -> None:
        result = run_kanon("--version")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert re.search(r"kanon \d+\.\d+\.\d+", result.stdout), (
            f"stdout does not match `kanon X.Y.Z`: {result.stdout!r}"
        )

    def test_hv_03_install_help(self) -> None:
        result = run_kanon("install", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "kanonenv_path" in result.stdout

    def test_hv_04_clean_help(self) -> None:
        result = run_kanon("clean", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "kanonenv_path" in result.stdout

    def test_hv_05_validate_help(self) -> None:
        result = run_kanon("validate", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "xml" in result.stdout
        assert "marketplace" in result.stdout

    def test_hv_06_validate_xml_help(self) -> None:
        result = run_kanon("validate", "xml", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "--repo-root" in result.stdout

    def test_hv_07_validate_marketplace_help(self) -> None:
        result = run_kanon("validate", "marketplace", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "--repo-root" in result.stdout

    def test_hv_08_bootstrap_help(self) -> None:
        result = run_kanon("bootstrap", "--help")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "package" in result.stdout
        assert "--output-dir" in result.stdout
