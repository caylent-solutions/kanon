"""Scenario tests: npm-like ``kanon install`` reconcile (RC family).

Mirrors ``docs/integration-testing.md`` family ``RC-NN``.  Exercises the operator
path -- subprocess ``kanon install`` against local ``file://`` fixtures (no
network) -- for the reconcile contract introduced to fix the
``install-orphan-rescue-crash-and-lock-corruption`` bug:

- RC-01: ``remove A + add B`` then a plain ``kanon install`` reconciles npm-style
  (lock = the new source set, the install succeeds with no internal ``BUG:`` and
  no traceback) and a second plain install is idempotent (CONSISTENT replay, lock
  byte-stable).
- RC-02: ``kanon install --strict-lock`` (npm ci) errors cleanly on drift WITHOUT
  mutating the lockfile (read the lock bytes before/after; assert equal).

Fixture builders are reused from ``test_lockfile_lifecycle`` (single source of
truth).  ``KANON_ALLOW_INSECURE_REMOTES=1`` is set per-run for ``file://`` URLs.
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.test_lockfile_lifecycle import (
    _build_catalog_bare,
    _build_manifest_repo_with_tags,
    _run_install,
)
from tests.scenarios.conftest import make_bare_repo_with_tags


def _write_kanon_two_optional(
    project_dir: pathlib.Path,
    sources: list[tuple[str, str, str]],
) -> pathlib.Path:
    """Write a ``.kanon`` declaring the given ``(name, manifest_url, revision)`` sources.

    Args:
        project_dir: Directory where ``.kanon`` is written.
        sources: List of ``(source_name, manifest_url, revision_spec)`` tuples.

    Returns:
        Path to the written ``.kanon`` file.
    """
    lines = [
        "GITBASE=https://unused.example.com",
        "CLAUDE_MARKETPLACES_DIR=/tmp/kanon-test-mktplc",
        "KANON_MARKETPLACE_INSTALL=false",
    ]
    for name, url, revision in sources:
        lines.append(f"KANON_SOURCE_{name}_URL={url}")
        lines.append(f"KANON_SOURCE_{name}_REVISION={revision}")
        lines.append(f"KANON_SOURCE_{name}_PATH=manifest.xml")
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text("\n".join(lines) + "\n")
    kanon_path.chmod(0o600)
    return kanon_path


def _build_source(fixtures: pathlib.Path, label: str) -> str:
    """Build a content+manifest fixture for ``label`` and return its manifest ``file://`` URL."""
    content_dir = fixtures / f"{label}-content"
    content_dir.mkdir()
    make_bare_repo_with_tags(content_dir, f"{label}-content", ["1.0.0"])
    manifest_bare, _content_fetch_url = _build_manifest_repo_with_tags(
        fixtures,
        label,
        ["1.0.0"],
        content_dir,
    )
    return manifest_bare.as_uri()


@pytest.mark.scenario
class TestRcReconcile:
    """RC family: npm-like reconcile and strict-lock-on-drift scenarios."""

    def test_rc_01_remove_add_reconciles_and_is_idempotent(self, tmp_path: pathlib.Path) -> None:
        """RC-01: remove A + add B + plain install reconciles to B; second install is idempotent.

        Reproduces the wedged-workspace bug scenario at the operator boundary:
        the lockfile has A (an orphan after removal) while ``.kanon`` declares only
        B (a new source).  Plain ``kanon install`` must prune A, resolve B fresh,
        write a valid lock = {B}, and never emit an internal ``BUG:`` or a
        traceback.  A second plain install must be idempotent (CONSISTENT replay,
        byte-stable lockfile).
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        url_a = _build_source(fixtures, "alpha")
        url_b = _build_source(fixtures, "beta")
        catalog_bare = _build_catalog_bare(fixtures / "catalog")
        catalog_uri = f"{catalog_bare.as_uri()}@main"
        lock_path = project / ".kanon.lock"

        # Install A only -> lock = {ALPHA}.
        _write_kanon_two_optional(project, [("ALPHA", url_a, "==1.0.0")])
        r1 = _run_install(project, catalog_uri)
        assert r1.returncode == 0, f"initial install failed:\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        assert sorted(e.name for e in read_lockfile(lock_path).sources) == ["ALPHA"]

        # Remove A, add B (orphan + addition).
        _write_kanon_two_optional(project, [("BETA", url_b, "==1.0.0")])
        r2 = _run_install(project, catalog_uri)
        assert r2.returncode == 0, (
            f"reconcile install must succeed (no BUG/traceback):\nstdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        assert "BUG:" not in r2.stdout and "BUG:" not in r2.stderr, (
            f"reconcile must never emit an internal BUG: line.\nstdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        )
        assert "Traceback" not in r2.stderr, f"reconcile must not raise a traceback.\nstderr={r2.stderr!r}"
        assert sorted(e.name for e in read_lockfile(lock_path).sources) == ["BETA"], (
            "reconcile must drop the orphaned ALPHA entry and add the new BETA entry"
        )
        lock_after_reconcile = lock_path.read_bytes()

        # Second plain install: CONSISTENT, byte-stable lockfile.
        r3 = _run_install(project, catalog_uri)
        assert r3.returncode == 0, f"second install failed:\nstdout={r3.stdout!r}\nstderr={r3.stderr!r}"
        assert lock_path.read_bytes() == lock_after_reconcile, (
            "second plain install must be idempotent (CONSISTENT replay); lockfile must not change"
        )

    def test_rc_02_strict_lock_errors_on_drift_without_mutating(self, tmp_path: pathlib.Path) -> None:
        """RC-02: --strict-lock errors on drift and leaves the lockfile byte-for-byte unchanged.

        Builds a lock = {ALPHA}, then drifts ``.kanon`` to remove ALPHA and add BETA
        (orphan + addition).  ``kanon install --strict-lock`` must exit non-zero with
        a clean error (no internal ``BUG:``/no traceback) and the lockfile on disk
        must be identical before and after.
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        project = tmp_path / "project"
        project.mkdir()

        url_a = _build_source(fixtures, "alpha")
        url_b = _build_source(fixtures, "beta")
        catalog_bare = _build_catalog_bare(fixtures / "catalog")
        catalog_uri = f"{catalog_bare.as_uri()}@main"
        lock_path = project / ".kanon.lock"

        _write_kanon_two_optional(project, [("ALPHA", url_a, "==1.0.0")])
        r1 = _run_install(project, catalog_uri)
        assert r1.returncode == 0, f"initial install failed:\nstdout={r1.stdout!r}\nstderr={r1.stderr!r}"
        lock_before = lock_path.read_bytes()

        # Drift: remove ALPHA, add BETA.
        _write_kanon_two_optional(project, [("BETA", url_b, "==1.0.0")])

        r2 = _run_install(project, catalog_uri, strict_lock=True)
        assert r2.returncode != 0, f"--strict-lock must error on drift.\nstdout={r2.stdout!r}\nstderr={r2.stderr!r}"
        combined = r2.stdout + r2.stderr
        assert "BUG:" not in combined, f"--strict-lock must not emit an internal BUG: line.\n{combined!r}"
        assert "Traceback" not in r2.stderr, f"--strict-lock must not raise a traceback.\nstderr={r2.stderr!r}"
        assert lock_path.read_bytes() == lock_before, "--strict-lock must NEVER mutate the lockfile on drift"
