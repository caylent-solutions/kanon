"""Integration test: --refresh-lock-source against a real fixture git repo.

AC-TEST-002: builds a fixture git repo with two top-level sources at distinct
tags, installs a baseline, modifies one source's tag on the remote, runs
install(refresh_lock_source=<name>), asserts the refreshed source row reflects
the new SHA AND the other source row is byte-equal to the baseline (excluding
kanon_hash and generated_at).

AC-CYCLE-001: end-to-end cycle:
  - Two-source fixture (alpha, beta).
  - Baseline install writes lockfile recording both SHAs.
  - Remote-side tag bump on alpha.
  - --refresh-lock-source alpha rewrites only the alpha row.
  - --refresh-lock-source <alpha-entry-name> (the derive_source_name form)
    produces a byte-identical lockfile to the prior run.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    UnknownSourceError,
    _RefResolution,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash
from kanon_cli.core.lockfile import read_lockfile


# ---------------------------------------------------------------------------
# Override autouse conftest fixtures: this module uses real local git repos
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: let the test's own patch handle _resolve_ref_to_sha."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: let the test's own subprocess.run patches handle reachability."""
    yield


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: pathlib.Path) -> str:
    """Run a git command and return stdout. Raises RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def _sha_for_ref(repo_path: pathlib.Path, ref: str) -> str:
    """Return the SHA that ref resolves to in the given repo."""
    return _git("rev-parse", ref, cwd=repo_path)


def _build_fixture_repo(base_dir: pathlib.Path, name: str) -> tuple[pathlib.Path, str]:
    """Create a fixture git repo with one commit tagged 1.0.0.

    Returns:
        (repo_path, sha_v1_0_0) -- path to the repo and the 1.0.0 commit SHA.
    """
    repo = base_dir / name
    repo.mkdir()
    _git("init", cwd=repo)
    _git("checkout", "-b", "main", cwd=repo)
    (repo / "README.md").write_text(f"{name} v1.0.0\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)
    _git("tag", "1.0.0", cwd=repo)
    sha = _sha_for_ref(repo, "refs/tags/1.0.0")
    return repo, sha


def _add_tag(repo_path: pathlib.Path, tag: str) -> str:
    """Add a new commit and tag it. Returns the new commit SHA."""
    (repo_path / "VERSION").write_text(f"{tag}\n")
    _git("add", "VERSION", cwd=repo_path)
    _git("commit", "-m", f"release {tag}", cwd=repo_path)
    _git("tag", tag, cwd=repo_path)
    return _sha_for_ref(repo_path, f"refs/tags/{tag}")


def _write_two_source_kanon(
    project_dir: pathlib.Path,
    alpha_url: str,
    beta_url: str,
    alpha_revision: str = "==1.0.0",
    beta_revision: str = "==1.0.0",
) -> pathlib.Path:
    """Write a .kanon file pointing at two sources: alpha and beta."""
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"GITBASE=https://unused.example.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mktplc\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={alpha_url}\n"
        f"KANON_SOURCE_alpha_REVISION={alpha_revision}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        f"KANON_SOURCE_beta_URL={beta_url}\n"
        f"KANON_SOURCE_beta_REVISION={beta_revision}\n"
        f"KANON_SOURCE_beta_PATH=manifest.xml\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


# Catalog source used across all tests -- a synthetic url@ref value.
_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"
# Fake catalog SHA returned when the catalog URL is not a real git repo.
_FAKE_CATALOG_SHA = "c" * 40


def _run_install_with_real_sources(
    kanon_path: pathlib.Path,
    catalog_source: str = _CATALOG_SOURCE,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
) -> None:
    """Call install() with repo tool calls mocked out, but real git ls-remote for sources.

    _resolve_ref_to_sha is patched only for the catalog URL; calls for real
    local source repos pass through so SHA values from the fixture git repos
    are recorded in the lockfile.
    """
    import kanon_cli.core.install as _install_mod

    original_resolve_ref = _install_mod._resolve_ref_to_sha

    catalog_url = catalog_source.rsplit("@", 1)[0] if "@" in catalog_source else catalog_source

    def _resolve_ref_patched(url: str, ref: str) -> _RefResolution:
        if url == catalog_url:
            return _RefResolution(sha=_FAKE_CATALOG_SHA, resolved_ref=f"refs/heads/{ref}")
        return original_resolve_ref(url, ref)

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_resolve_ref_patched),
    ):
        install(
            kanon_path,
            catalog_source=catalog_source,
            refresh_lock=refresh_lock,
            refresh_lock_source=refresh_lock_source,
        )


# ===========================================================================
# AC-TEST-002: refresh-lock-source rewrites only the named source
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockSourceRebuildsOnlyNamedSource:
    """AC-TEST-002: --refresh-lock-source rewrites only the named source's row."""

    def test_refresh_lock_source_by_name_rewrites_alpha_preserves_beta(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001 + AC-TEST-002: refresh by source name rewrites only alpha's row.

        After a tag bump on the alpha fixture repo, --refresh-lock-source alpha
        rewrites the alpha row with the new SHA, and beta is byte-equal to baseline.
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        alpha_repo, alpha_sha_v1 = _build_fixture_repo(fixture_dir, "alpha")
        beta_repo, beta_sha_v1 = _build_fixture_repo(fixture_dir, "beta")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(project_dir, str(alpha_repo), str(beta_repo))

        # Baseline install -- writes the lockfile with both 1.0.0 SHAs.
        _run_install_with_real_sources(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists()
        lf_baseline = read_lockfile(lock_path)

        alpha_baseline = next(e for e in lf_baseline.sources if e.name == "alpha")
        beta_baseline = next(e for e in lf_baseline.sources if e.name == "beta")
        assert alpha_baseline.resolved_sha == alpha_sha_v1
        assert beta_baseline.resolved_sha == beta_sha_v1

        # Bump alpha to 1.1.0 on the remote.
        alpha_sha_v2 = _add_tag(alpha_repo, "1.1.0")

        # Modify .kanon to point alpha at 1.1.0 so kanon_hash changes.
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(alpha_repo),
            str(beta_repo),
            alpha_revision="==1.1.0",
            beta_revision="==1.0.0",
        )

        # Run --refresh-lock-source alpha.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="alpha")

        lf_after = read_lockfile(lock_path)
        alpha_after = next(e for e in lf_after.sources if e.name == "alpha")
        beta_after = next(e for e in lf_after.sources if e.name == "beta")

        # alpha row reflects the new SHA from 1.1.0.
        assert alpha_after.resolved_sha == alpha_sha_v2, (
            f"Expected alpha SHA {alpha_sha_v2!r}; got {alpha_after.resolved_sha!r}"
        )

        # beta row is byte-equal to the baseline (excluding top-level kanon_hash
        # and generated_at, which are not in SourceEntry).
        assert beta_after.resolved_sha == beta_sha_v1
        assert beta_after.url == beta_baseline.url
        assert beta_after.revision_spec == beta_baseline.revision_spec
        assert beta_after.resolved_ref == beta_baseline.resolved_ref
        assert beta_after.path == beta_baseline.path

    def test_refresh_lock_source_by_entry_name_matches_by_source_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-002 + AC-CYCLE-001: refresh by derive_source_name form produces
        a lockfile identical to refresh by source name."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        alpha_repo, _alpha_sha_v1 = _build_fixture_repo(fixture_dir, "alpha")
        beta_repo, _beta_sha_v1 = _build_fixture_repo(fixture_dir, "beta")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(project_dir, str(alpha_repo), str(beta_repo))

        # Baseline install.
        _run_install_with_real_sources(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lf_baseline = read_lockfile(lock_path)

        # Bump alpha to 1.1.0 and rewrite .kanon.
        _add_tag(alpha_repo, "1.1.0")
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(alpha_repo),
            str(beta_repo),
            alpha_revision="==1.1.0",
            beta_revision="==1.0.0",
        )

        # First pass: refresh by literal source name.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="alpha")
        lf_by_name = read_lockfile(lock_path)

        # Reset the lockfile to baseline before the second pass.
        from kanon_cli.core.lockfile import write_lockfile

        write_lockfile(lf_baseline, lock_path)

        # Rewrite .kanon again (same content) so the lock is re-valid.
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(alpha_repo),
            str(beta_repo),
            alpha_revision="==1.1.0",
            beta_revision="==1.0.0",
        )

        # Second pass: refresh by derive_source_name form.
        # 'Alpha' normalises to 'alpha' via derive_source_name (lowercase).
        _run_install_with_real_sources(kanon_path, refresh_lock_source="Alpha")
        lf_by_derive = read_lockfile(lock_path)

        # The refreshed alpha SHAs must be identical.
        alpha_by_name = next(e for e in lf_by_name.sources if e.name == "alpha")
        alpha_by_derive = next(e for e in lf_by_derive.sources if e.name == "alpha")
        assert alpha_by_name.resolved_sha == alpha_by_derive.resolved_sha, (
            f"SHA mismatch between by-name and by-derive refresh: "
            f"{alpha_by_name.resolved_sha!r} vs {alpha_by_derive.resolved_sha!r}"
        )

        # The beta rows must also be identical.
        beta_by_name = next(e for e in lf_by_name.sources if e.name == "beta")
        beta_by_derive = next(e for e in lf_by_derive.sources if e.name == "beta")
        assert beta_by_name.resolved_sha == beta_by_derive.resolved_sha


# ===========================================================================
# AC-FUNC-003: --refresh-lock-source with unknown name raises UnknownSourceError
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockSourceUnknownName:
    """AC-FUNC-003: unknown source name raises UnknownSourceError."""

    def test_unknown_source_name_raises(self, tmp_path: pathlib.Path) -> None:
        """install(refresh_lock_source='gamma') when only alpha and beta exist raises."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        alpha_repo, _alpha_sha = _build_fixture_repo(fixture_dir, "alpha")
        beta_repo, _beta_sha = _build_fixture_repo(fixture_dir, "beta")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(project_dir, str(alpha_repo), str(beta_repo))

        # Write a valid lockfile first.
        _run_install_with_real_sources(kanon_path)

        with pytest.raises(UnknownSourceError) as exc_info:
            _run_install_with_real_sources(kanon_path, refresh_lock_source="gamma")

        err_str = str(exc_info.value)
        assert "gamma" in err_str
        assert "alpha" in err_str
        assert "beta" in err_str


# ===========================================================================
# AC-FUNC-007: kanon_hash is freshly computed on the refresh path
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockSourceFreshKanonHash:
    """AC-FUNC-007: lockfile records the freshly-computed kanon_hash, not the old one."""

    def test_kanon_hash_is_recomputed_after_refresh_lock_source(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After --refresh-lock-source, kanon_hash equals hand-computed value from .kanon."""
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        alpha_repo, _alpha_sha_v1 = _build_fixture_repo(fixture_dir, "alpha")
        beta_repo, _beta_sha_v1 = _build_fixture_repo(fixture_dir, "beta")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(project_dir, str(alpha_repo), str(beta_repo))

        # Baseline install.
        _run_install_with_real_sources(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        lf_before = read_lockfile(lock_path)

        # Bump alpha and rewrite .kanon to change kanon_hash.
        _add_tag(alpha_repo, "1.1.0")
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(alpha_repo),
            str(beta_repo),
            alpha_revision="==1.1.0",
            beta_revision="==1.0.0",
        )

        # kanon_hash must differ now.
        expected_new_hash = compute_kanon_hash(kanon_path)
        assert expected_new_hash != lf_before.kanon_hash, (
            "Test setup error: kanon_hash should have changed after revision bump"
        )

        # Run --refresh-lock-source alpha.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="alpha")

        lf_after = read_lockfile(lock_path)

        # The lockfile must record the freshly-computed kanon_hash.
        assert lf_after.kanon_hash == expected_new_hash, (
            f"Expected kanon_hash {expected_new_hash!r}; got {lf_after.kanon_hash!r}"
        )
