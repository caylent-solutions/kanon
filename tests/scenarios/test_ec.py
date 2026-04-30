"""EC (Error Cases) scenarios from `docs/integration-testing.md` §9.

Each scenario invokes `kanon` against a deliberately broken `.kanon` (or
missing args / wrong subcommand) and asserts the documented exit code +
stderr substring. No git fixtures are needed -- only on-disk `.kanon`
content and CLI flag combinations.

Scenarios automated:
- EC-01: Missing .kanon file
- EC-02: Empty .kanon file
- EC-03: Undefined shell variable
- EC-04: Missing source URL (REVISION + PATH but no URL)
- EC-05: KANON_SOURCES explicitly set (legacy, no longer supported)
- EC-06: KANON_MARKETPLACE_INSTALL=true without CLAUDE_MARKETPLACES_DIR
- EC-07: No subcommand
- EC-08: Invalid subcommand
- EC-09: Missing required args (validate without target)
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestEC:
    def test_ec_01_missing_kanon_file(self, tmp_path: pathlib.Path) -> None:
        result = run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        combined = result.stderr + result.stdout
        assert ".kanon file not found" in combined or "Error" in combined, (
            f"missing expected error text in: {combined!r}"
        )

    def test_ec_02_empty_kanon_file(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text("")
        result = run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "No sources found" in result.stderr, f"stderr={result.stderr!r}"

    def test_ec_03_undefined_shell_variable(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text(
            "KANON_SOURCE_test_URL=${UNDEFINED_VAR_THAT_DOES_NOT_EXIST}\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=meta.xml\n"
        )
        result = run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "Undefined shell variable" in result.stderr, f"stderr={result.stderr!r}"

    def test_ec_04_missing_source_url(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text("KANON_SOURCE_test_REVISION=main\nKANON_SOURCE_test_PATH=meta.xml\n")
        result = run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "KANON_SOURCE_test_URL is required but not set" in result.stderr, f"stderr={result.stderr!r}"

    def test_ec_05_kanon_sources_legacy_unsupported(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text(
            "KANON_SOURCES=build\n"
            "KANON_SOURCE_build_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
        )
        result = run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "no longer supported" in result.stderr, f"stderr={result.stderr!r}"

    def test_ec_06_marketplace_install_without_marketplaces_dir(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon").write_text(
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_primary_URL=file:///does/not/matter\n"
            "KANON_SOURCE_primary_REVISION=main\n"
            "KANON_SOURCE_primary_PATH=meta.xml\n"
        )
        # Inherit the parent env but strip CLAUDE_MARKETPLACES_DIR so the
        # subprocess hits the documented "not defined" branch.
        env_no_mkt = {k: v for k, v in os.environ.items() if k != "CLAUDE_MARKETPLACES_DIR"}
        result = run_kanon("install", ".kanon", cwd=tmp_path, env=env_no_mkt)
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert "KANON_MARKETPLACE_INSTALL=true but CLAUDE_MARKETPLACES_DIR is not defined" in result.stderr, (
            f"stderr={result.stderr!r}"
        )

    def test_ec_07_no_subcommand(self) -> None:
        result = run_kanon()
        assert result.returncode == 2, f"stderr={result.stderr!r}"
        usage = result.stderr + result.stdout
        assert "usage" in usage.lower() or "Usage" in usage, f"no usage info in: {usage!r}"

    def test_ec_08_invalid_subcommand(self) -> None:
        result = run_kanon("nonexistent")
        assert result.returncode == 2, f"stderr={result.stderr!r}"

    def test_ec_09_validate_without_target(self) -> None:
        result = run_kanon("validate")
        assert result.returncode == 2, f"stderr={result.stderr!r}"
        assert "Must specify a validation target" in result.stderr, f"stderr={result.stderr!r}"
