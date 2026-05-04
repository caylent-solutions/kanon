"""TC-bootstrap scenarios from `docs/integration-testing.md` §27.

Each scenario exercises top-level `kanon bootstrap` surface area not
previously covered by the BS-* scenario category.

Scenarios automated:
- TC-bootstrap-01: --output-dir=<path> bootstrap
- TC-bootstrap-02: --catalog-source flag form
- TC-bootstrap-03: KANON_CATALOG_SOURCE env form
- TC-bootstrap-04: flag overrides env
- TC-bootstrap-05: bootstrap into nonexistent parent path errors
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    init_git_work_dir,
    run_git,
    run_kanon,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_catalog_repo(parent: pathlib.Path, entry_name: str) -> pathlib.Path:
    """Build a local bare catalog repo with a catalog/<entry_name>/ directory.

    Tags 1.0.0..3.0.0 are applied as successive commits so that ``latest``
    and PEP 440 constraint expressions resolve to a real tag.  Returns the
    bare repo path.
    """
    work = parent / "catalog-work"
    bare = parent / "catalog.git"
    init_git_work_dir(work)

    tags = ("1.0.0", "2.0.0", "3.0.0")
    for tag in tags:
        pkg_dir = work / "catalog" / entry_name
        pkg_dir.mkdir(parents=True, exist_ok=True)
        readme = pkg_dir / f"{entry_name}-readme.md"
        readme.write_text(f"# {entry_name} {tag}\n")
        run_git(["add", "."], work)
        run_git(["commit", "-m", f"release {tag}"], work)
        run_git(["tag", tag], work)

    run_git(["clone", "--bare", str(work), str(bare)], work.parent)
    return bare.resolve()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestTCBootstrap:
    # ------------------------------------------------------------------
    # TC-bootstrap-01: --output-dir=<path>
    # ------------------------------------------------------------------

    def test_tc_bootstrap_01_output_dir(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-01: kanon bootstrap kanon --output-dir creates .kanon at named path."""
        output_dir = tmp_path / "tc-bs-01"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))

        assert result.returncode == 0, (
            f"bootstrap exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert (output_dir / ".kanon").exists(), f".kanon not found at {output_dir}"

    # ------------------------------------------------------------------
    # TC-bootstrap-02: --catalog-source flag form
    # ------------------------------------------------------------------

    def test_tc_bootstrap_02_catalog_source_flag(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-02: bootstrap list --catalog-source flag uses the supplied catalog."""
        catalog_bare = _build_catalog_repo(tmp_path / "fixtures", "test-entry")
        catalog_source = f"{catalog_bare.as_uri()}@latest"

        result = run_kanon("bootstrap", "list", "--catalog-source", catalog_source)

        assert result.returncode == 0, (
            f"bootstrap list exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "test-entry" in result.stdout, f"Expected 'test-entry' in stdout: {result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-03: KANON_CATALOG_SOURCE env form
    # ------------------------------------------------------------------

    def test_tc_bootstrap_03_catalog_source_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-03: bootstrap list reads KANON_CATALOG_SOURCE from the environment."""
        catalog_bare = _build_catalog_repo(tmp_path / "fixtures", "test-entry")
        catalog_source = f"{catalog_bare.as_uri()}@latest"

        env = dict(os.environ)
        env["KANON_CATALOG_SOURCE"] = catalog_source

        result = run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0, (
            f"bootstrap list exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "test-entry" in result.stdout, f"Expected 'test-entry' in stdout: {result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-04: flag overrides env
    # ------------------------------------------------------------------

    def test_tc_bootstrap_04_flag_overrides_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-04: --catalog-source flag takes precedence over KANON_CATALOG_SOURCE env."""
        catalog_bare = _build_catalog_repo(tmp_path / "fixtures", "test-entry")
        catalog_source = f"{catalog_bare.as_uri()}@latest"

        env = dict(os.environ)
        # Set env to a non-existent path; flag supplies the real catalog.
        env["KANON_CATALOG_SOURCE"] = "file:///nonexistent-catalog.git@1.0.0"

        result = run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            catalog_source,
            env=env,
        )

        assert result.returncode == 0, (
            f"bootstrap list exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "test-entry" in result.stdout, (
            f"Expected 'test-entry' in stdout (flag must win over env): {result.stdout!r}"
        )

    # ------------------------------------------------------------------
    # TC-bootstrap-05: bootstrap into nonexistent parent path errors
    # ------------------------------------------------------------------

    def test_tc_bootstrap_05_nonexistent_parent_errors(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-05: bootstrap with --output-dir whose parent does not exist exits non-zero."""
        missing_parent = tmp_path / "no" / "such" / "parent" / "dir"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))

        assert result.returncode != 0, (
            f"Expected non-zero exit for missing parent, got 0\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined.strip(), "Expected a non-empty diagnostic message in stdout or stderr"
