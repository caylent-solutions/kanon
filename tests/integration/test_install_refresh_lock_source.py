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

E25-DEFECT-010: TestRefreshLockSourceCounters verifies that the summary line
emitted by install(refresh_lock_source=<name>) correctly reflects the number
of refreshed vs preserved top-level sources. Before the fix, the line always
reads (0 projects refreshed; 0 projects preserved) because the counter reads
SourceEntry.projects (sub-project XML includes) rather than the count of
top-level source entries.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import (
    UnknownSourceError,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash
from kanon_cli.core.lockfile import read_lockfile
from tests.integration.test_add_core import _create_manifest_repo_with_tags


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
    """Write a .kanon file pointing at two sources: alpha and beta.

    Bare filesystem paths are coerced to ``file://`` URLs so the URL parser
    introduced by E1-F2-S1-T1 accepts them; the autouse
    ``_default_allow_insecure_remotes`` fixture in conftest then permits the
    non-HTTPS/SSH scheme through ``_enforce_remote_url_policy``.
    """
    if alpha_url.startswith("/"):
        alpha_url = f"file://{alpha_url}"
    if beta_url.startswith("/"):
        beta_url = f"file://{beta_url}"
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"GITBASE=https://unused.example.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mktplc\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={alpha_url}\n"
        f"KANON_SOURCE_alpha_REF={alpha_revision}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        f"KANON_SOURCE_alpha_NAME=alpha\n"
        f"KANON_SOURCE_alpha_GITBASE=https://example.com\n"
        f"KANON_SOURCE_beta_URL={beta_url}\n"
        f"KANON_SOURCE_beta_REF={beta_revision}\n"
        f"KANON_SOURCE_beta_PATH=manifest.xml\n"
        f"KANON_SOURCE_beta_NAME=beta\n"
        f"KANON_SOURCE_beta_GITBASE=https://example.com\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _run_install_with_real_sources(
    kanon_path: pathlib.Path,
    refresh_lock: bool = False,
    refresh_lock_source: str | None = None,
) -> None:
    """Call install() with repo tool calls mocked out, but real git ls-remote for sources.

    install() is hermetic (schema v4, spec Section 5.2 / FR-7): it resolves no
    catalog source, so ``catalog_source`` is always None here and the real
    ``_resolve_ref_to_sha`` runs against the local fixture source repos so their
    SHA values from the fixture git repos are recorded in the lockfile.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
    ):
        install(
            kanon_path,
            lock_file_path=kanon_path.parent / ".kanon.lock",
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
        assert beta_after.ref_spec == beta_baseline.ref_spec
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


# ===========================================================================
# E25-DEFECT-010: --refresh-lock-source summary line counters
# ===========================================================================


def _advance_bare_repo_tip(bare_path: pathlib.Path, new_tag: str, work_root: pathlib.Path) -> str:
    """Clone a bare repo, add a new commit tagged with new_tag, and push back.

    Args:
        bare_path: Absolute path to the bare repo directory.
        new_tag: PEP 440-valid tag name to apply on the new commit.
        work_root: Parent directory under which the temporary clone is created.

    Returns:
        The resolved SHA for the new tag in the bare repo.
    """
    clone_dir = work_root / f"clone-for-{new_tag}"
    clone_dir.mkdir(parents=True, exist_ok=True)
    _git(
        "clone",
        str(bare_path),
        str(clone_dir),
        cwd=work_root,
    )
    _git("config", "user.name", "Test", cwd=clone_dir)
    _git("config", "user.email", "t@t.com", cwd=clone_dir)
    version_file = clone_dir / "VERSION"
    version_file.write_text(f"{new_tag}\n")
    _git("add", "VERSION", cwd=clone_dir)
    _git("commit", "-m", f"release {new_tag}", cwd=clone_dir)
    _git("tag", "-a", new_tag, "-m", f"Release {new_tag}", cwd=clone_dir)
    _git("push", "origin", "HEAD:main", "--tags", cwd=clone_dir)
    return _sha_for_ref(clone_dir, f"refs/tags/{new_tag}")


def _write_two_source_kanon_for_bare(
    project_dir: pathlib.Path,
    srca_url: str,
    srcb_url: str,
    srca_revision: str = "==1.0.0",
    srcb_revision: str = "==1.0.0",
) -> pathlib.Path:
    """Write a .kanon file pointing at two bare-repo sources: srca and srcb.

    Bare filesystem paths are coerced to ``file://`` URLs so the URL parser
    accepts them; the autouse ``_default_allow_insecure_remotes`` fixture in
    conftest permits the non-HTTPS/SSH scheme through ``_enforce_remote_url_policy``.

    Args:
        project_dir: Directory in which to write the .kanon file.
        srca_url: URL (or bare path) for the first source.
        srcb_url: URL (or bare path) for the second source.
        srca_revision: Revision spec for the first source (default ==1.0.0).
        srcb_revision: Revision spec for the second source (default ==1.0.0).

    Returns:
        Path to the written .kanon file.
    """
    if srca_url.startswith("/"):
        srca_url = f"file://{srca_url}"
    if srcb_url.startswith("/"):
        srcb_url = f"file://{srcb_url}"
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"GITBASE=https://unused.example.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mktplc\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_srca_URL={srca_url}\n"
        f"KANON_SOURCE_srca_REF={srca_revision}\n"
        f"KANON_SOURCE_srca_PATH=manifest.xml\n"
        f"KANON_SOURCE_srca_NAME=srca\n"
        f"KANON_SOURCE_srca_GITBASE=https://example.com\n"
        f"KANON_SOURCE_srcb_URL={srcb_url}\n"
        f"KANON_SOURCE_srcb_REF={srcb_revision}\n"
        f"KANON_SOURCE_srcb_PATH=manifest.xml\n"
        f"KANON_SOURCE_srcb_NAME=srcb\n"
        f"KANON_SOURCE_srcb_GITBASE=https://example.com\n"
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _run_install_capturing_stdout(
    kanon_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
    refresh_lock_source: str | None = None,
) -> str:
    """Call install() with real-source patches and return captured stdout.

    Wraps ``_run_install_with_real_sources`` and captures the stdout emitted
    by install() using pytest's capsys fixture.  install() is hermetic, so no
    catalog source is passed.

    Args:
        kanon_path: Path to the .kanon configuration file.
        capsys: The pytest capture fixture for the calling test.
        refresh_lock_source: Optional --refresh-lock-source value.

    Returns:
        The stdout text printed by install() during this invocation.
    """
    _run_install_with_real_sources(
        kanon_path,
        refresh_lock_source=refresh_lock_source,
    )
    captured = capsys.readouterr()
    return captured.out


@pytest.mark.integration
class TestRefreshLockSourceCounters:
    """E25-DEFECT-010: --refresh-lock-source summary counter accuracy.

    Verifies that the summary line emitted by install(refresh_lock_source=<name>)
    reports the correct number of refreshed and preserved top-level sources,
    and that the zero-source edge case does not emit a counter line.
    """

    def test_counters_reflect_actual_refresh_and_preserve_counts(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-FUNC-002: summary reports (1 project refreshed; 1 project preserved).

        Builds two synthetic sources A and B via _create_manifest_repo_with_tags,
        installs both, advances source A's tip with a new tag, then runs
        install(refresh_lock_source="srca") and asserts the summary line on stdout
        reads exactly "(1 project refreshed; 1 project preserved)".

        This test FAILS against the unfixed code because the counter reads
        SourceEntry.projects (sub-project XML includes, always empty for these
        synthetic fixture repos) instead of counting top-level source entries.
        The resulting broken output is "(0 projects refreshed; 0 projects preserved)".
        """
        # Build two synthetic bare repos: catA and catB.
        cat_a_bare = _create_manifest_repo_with_tags(
            tmp_path / "catA",
            entry_names=["A"],
            tags=["1.0.0"],
        )
        cat_b_bare = _create_manifest_repo_with_tags(
            tmp_path / "catB",
            entry_names=["B"],
            tags=["1.0.0"],
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon_for_bare(
            project_dir,
            srca_url=str(cat_a_bare),
            srcb_url=str(cat_b_bare),
        )

        # Baseline install -- writes the lockfile with both 1.0.0 SHAs.
        capsys.readouterr()  # discard any earlier output
        _run_install_with_real_sources(kanon_path)
        capsys.readouterr()  # discard baseline output

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "Baseline install must write a lockfile; lockfile absent after install()"

        # Advance catA's bare repo: new commit tagged 1.1.0.
        _advance_bare_repo_tip(
            bare_path=cat_a_bare,
            new_tag="1.1.0",
            work_root=tmp_path / "advance-work",
        )

        # Rewrite .kanon to point srca at 1.1.0 so kanon_hash changes.
        kanon_path = _write_two_source_kanon_for_bare(
            project_dir,
            srca_url=str(cat_a_bare),
            srcb_url=str(cat_b_bare),
            srca_revision="==1.1.0",
            srcb_revision="==1.0.0",
        )

        # Run --refresh-lock-source srca and capture stdout.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="srca")
        captured = capsys.readouterr()
        stdout = captured.out

        # Assert the exact counter substring -- must match (1 ... 1 ...), not (0 ... 0 ...).
        expected_counter = "(1 project refreshed; 1 project preserved)"
        assert expected_counter in stdout, f"Expected stdout to contain {expected_counter!r}; got stdout={stdout!r}"

    def test_zero_source_workspace_omits_counter_line(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-FUNC-005: zero-source workspace does not emit a counter line.

        Builds a workspace with no KANON_SOURCE_* declarations and invokes
        install(refresh_lock_source="nonexistent"). The call must raise an
        error before reaching the summary-line code path, and stdout must NOT
        contain the substring "projects refreshed", confirming the counter
        line is never emitted when no sources are present.

        The error raised is ValueError from kanonenv parsing (no sources
        declared) which is the actual short-circuit that prevents the
        counter line from being emitted on empty workspaces.
        """
        project_dir = tmp_path / "empty-project"
        project_dir.mkdir()

        # Write a minimal .kanon with no KANON_SOURCE_* entries.
        kanon_path = project_dir / ".kanon"
        kanon_path.write_text(
            "GITBASE=https://unused.example.com\nCLAUDE_MARKETPLACES_DIR=/tmp/mktplc\nKANON_MARKETPLACE_INSTALL=false\n"
        )
        kanon_path.chmod(0o600)

        capsys.readouterr()  # discard any earlier output

        # Zero-source .kanon raises ValueError from kanonenv parsing
        # (no KANON_SOURCE_* entries) before reaching the summary-line code.
        with pytest.raises(ValueError, match="No sources found"):
            _run_install_with_real_sources(kanon_path, refresh_lock_source="nonexistent")

        captured = capsys.readouterr()
        stdout = captured.out

        assert "projects refreshed" not in stdout, (
            f"Counter line must not appear when workspace has zero sources; got stdout={stdout!r}"
        )


# ===========================================================================
# AC-FUNC-003 (E49-F6-S1-T1): both-direction assertions -- exact stays, range advances
# ===========================================================================


@pytest.mark.integration
class TestRefreshLockSourceExactVsRange:
    """AC-FUNC-003 (E49-F6-S1-T1): both-direction refresh-lock-source semantics.

    Fast inner-loop coverage for Section 13 D3:
    - A range-spec source (``>=1.0.0``) resolves to a new SHA when a higher
      tag is published and --refresh-lock-source is run (range advances).
    - An exact-pin source (``==1.0.0``) stays at its original SHA after
      --refresh-lock-source even when a higher tag is published (pin stays).
    """

    def test_range_spec_source_advances_on_refresh(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Range-spec (>=1.0.0) resolved SHA changes after a new tag + --refresh-lock-source.

        Builds two fixture repos: ``rangesrc`` (range spec ``>=1.0.0``) and
        ``exactsrc`` (exact pin ``==1.0.0``).  After a tag bump to 1.1.0, runs
        --refresh-lock-source rangesrc and asserts:
        - rangesrc SHA advanced to the 1.1.0 commit (range resolved to newest tag).
        - exactsrc SHA is unchanged (was the preserved, non-target source).
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        rangesrc_repo, rangesrc_sha_v1 = _build_fixture_repo(fixture_dir, "rangesrc")
        exactsrc_repo, exactsrc_sha_v1 = _build_fixture_repo(fixture_dir, "exactsrc")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(rangesrc_repo),
            str(exactsrc_repo),
            alpha_revision=">=1.0.0",
            beta_revision="==1.0.0",
        )

        # Baseline install using range spec -- resolves to 1.0.0 (only tag available).
        _run_install_with_real_sources(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "baseline install must write a lockfile"
        lf_baseline = read_lockfile(lock_path)

        rangesrc_baseline = next(e for e in lf_baseline.sources if e.name == "alpha")
        exactsrc_baseline = next(e for e in lf_baseline.sources if e.name == "beta")
        assert rangesrc_baseline.resolved_sha == rangesrc_sha_v1, (
            f"Baseline rangesrc SHA mismatch: expected {rangesrc_sha_v1!r}, got {rangesrc_baseline.resolved_sha!r}"
        )
        assert exactsrc_baseline.resolved_sha == exactsrc_sha_v1

        # Publish 1.1.0 on both repos.
        rangesrc_sha_v2 = _add_tag(rangesrc_repo, "1.1.0")
        _add_tag(exactsrc_repo, "1.1.0")

        # Run --refresh-lock-source alpha (the range-spec source).
        # The .kanon still has >=1.0.0 for alpha -- no spec change needed.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="alpha")

        lf_after = read_lockfile(lock_path)
        rangesrc_after = next(e for e in lf_after.sources if e.name == "alpha")
        exactsrc_after = next(e for e in lf_after.sources if e.name == "beta")

        # Range-spec source must have advanced to the new 1.1.0 SHA.
        assert rangesrc_after.resolved_sha != rangesrc_sha_v1, (
            f"ERROR: range-spec source 'alpha' (>=1.0.0) did NOT advance SHA after "
            f"--refresh-lock-source + new tag 1.1.0. "
            f"SHA before: {rangesrc_sha_v1!r}, SHA after: {rangesrc_after.resolved_sha!r}"
        )
        assert rangesrc_after.resolved_sha == rangesrc_sha_v2, (
            f"ERROR: rangesrc SHA after refresh is {rangesrc_after.resolved_sha!r}; "
            f"expected {rangesrc_sha_v2!r} (the 1.1.0 tag commit SHA)"
        )

        # Exact-pin source was the preserved (non-target) source -- its SHA must be unchanged.
        assert exactsrc_after.resolved_sha == exactsrc_sha_v1, (
            f"ERROR: exactsrc (non-target, preserved) SHA changed unexpectedly: "
            f"before={exactsrc_sha_v1!r}, after={exactsrc_after.resolved_sha!r}"
        )

    def test_exact_pin_source_stays_on_refresh(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Exact-pin (==1.0.0) resolved SHA is unchanged after --refresh-lock-source.

        Documents Section 13 D3: an exact pin is a pin.  The resolver maps
        ``==1.0.0`` deterministically to the 1.0.0 tag commit SHA regardless of
        whether higher tags have been published.

        Builds two fixture repos: ``exactsrc`` (exact pin ``==1.0.0``) and
        ``other`` (range ``>=1.0.0``).  Publishes tag 1.1.0 on both.  Runs
        --refresh-lock-source exactsrc (the exact-pin source) and asserts its
        SHA is unchanged.
        """
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        exactsrc_repo, exactsrc_sha_v1 = _build_fixture_repo(fixture_dir, "exactsrc")
        other_repo, _ = _build_fixture_repo(fixture_dir, "other")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        kanon_path = _write_two_source_kanon(
            project_dir,
            str(exactsrc_repo),
            str(other_repo),
            alpha_revision="==1.0.0",
            beta_revision=">=1.0.0",
        )

        # Baseline install.
        _run_install_with_real_sources(kanon_path)

        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "baseline install must write a lockfile"
        lf_baseline = read_lockfile(lock_path)

        exactsrc_baseline = next(e for e in lf_baseline.sources if e.name == "alpha")
        assert exactsrc_baseline.resolved_sha == exactsrc_sha_v1, (
            f"Baseline exactsrc SHA mismatch: expected {exactsrc_sha_v1!r}, got {exactsrc_baseline.resolved_sha!r}"
        )

        # Publish 1.1.0 on both repos.
        _add_tag(exactsrc_repo, "1.1.0")
        _add_tag(other_repo, "1.1.0")

        # Run --refresh-lock-source alpha (the exact-pin source).
        # The .kanon still has ==1.0.0 for alpha.
        _run_install_with_real_sources(kanon_path, refresh_lock_source="alpha")

        lf_after = read_lockfile(lock_path)
        exactsrc_after = next(e for e in lf_after.sources if e.name == "alpha")

        # Exact-pin source must stay at the original SHA.
        assert exactsrc_after.resolved_sha == exactsrc_sha_v1, (
            f"ERROR: exact-pin source 'alpha' (==1.0.0) changed SHA after "
            f"--refresh-lock-source -- a pin must stay pinned. "
            f"SHA before: {exactsrc_sha_v1!r}, SHA after: {exactsrc_after.resolved_sha!r}"
        )
