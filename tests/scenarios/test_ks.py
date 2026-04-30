"""KS (Kanon-to-Semver mapping) scenarios from `docs/integration-testing.md` §17.

Each scenario exercises PEP 440 constraints in `.kanon` REVISION values and
verifies that `kanon install` resolves to the expected semver tag.  Pass
criteria: `kanon repo manifest --revision-as-tag` emits a line containing
`refs/tags/<expected_tag>`.

Fixture design
--------------
* ``ks_catalog_bare`` -- a content repo with 7 annotated semver tags
  (1.0.0 … 3.0.0 including 1.2.0 and 2.1.0) plus matching branches.
  Annotated tags are required so ``git describe --exact-match HEAD``
  succeeds in the repo tool's primary lookup path.
* ``ks_fix_bare`` -- the KS-fixture manifest repo with the same 7 tags.
  Each tag version carries a ``default.xml`` whose catalog project has
  ``revision="==<same-tag>"``.  This embeds a PEP 440 equality constraint
  so ``kanon repo manifest --revision-as-tag`` resolves via the PEP 440
  fallback path (``git tag --list`` + constraint resolver) and emits
  ``refs/tags/<expected_tag>`` in its output.

Verification: after ``kanon install`` resolves a ``.kanon``
``KANON_SOURCE_pep_REVISION=<constraint>`` to a KS-fixture tag, running
``kanon repo manifest --revision-as-tag`` inside the synced source dir
produces XML with ``revision="refs/tags/<expected_tag>"`` for the catalog
project.

Scenarios automated:
- KS-01: bare `latest`                         → 3.0.0
- KS-02: prefixed `refs/tags/latest`            → 3.0.0
- KS-03: bare wildcard `*`                      → 3.0.0
- KS-04: prefixed `refs/tags/*`                 → 3.0.0
- KS-05: bare plain tag `1.0.0`                 → 1.0.0
- KS-06: bare `~=1.0.0`                         → 1.0.1
- KS-07: prefixed `refs/tags/~=1.0.0`           → 1.0.1
- KS-08: bare `~=2.0`                           → 2.1.0
- KS-09: bare `>=1.2.0`                         → 3.0.0
- KS-10: bare `<2.0.0`                          → 1.2.0
- KS-11: bare `<=1.1.0`                         → 1.1.0
- KS-12: bare `==1.0.1`                         → 1.0.1
- KS-13: bare `!=2.0.0`                         → 3.0.0
- KS-14: bare range `>=1.0.0,<2.0.0`            → 1.2.0
- KS-15: prefixed `refs/tags/>=2.0.0,<3.0.0`    → 2.1.0
- KS-16: prefixed `refs/tags/~=2.0`             → 2.1.0
- KS-17: prefixed `refs/tags/>=1.2.0`           → 3.0.0
- KS-18: prefixed `refs/tags/<2.0.0`            → 1.2.0
- KS-19: prefixed `refs/tags/<=1.1.0`           → 1.1.0
- KS-20: prefixed `refs/tags/==1.0.1`           → 1.0.1
- KS-21: prefixed `refs/tags/!=2.0.0`           → 3.0.0
- KS-22: prefixed `refs/tags/>=1.0.0,<2.0.0`   → 1.2.0
- KS-23: prefixed `refs/tags/==3.0.0`           → 3.0.0
- KS-24: env-var override of REVISION           → 1.0.1
- KS-25: undefined shell var in REVISION errors clearly
- KS-26: invalid `==*` REVISION rejected
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_install,
    run_git,
    run_kanon,
    write_kanonenv,
    xml_escape,
)

# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

# The 7-tag set shared by both the KS-fixture manifest repo and the catalog
# content repo.  Every test resolves its .kanon constraint to one of these.
_KS_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_ks_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Build the KS catalog content repo with annotated tags and matching branches.

    Uses annotated tags so ``git describe --exact-match HEAD`` can find them
    (the repo tool's primary lookup path skips lightweight tags).  Each tag
    also has a branch with the same name so that plain version-string
    revisions like ``1.0.0`` (which repo resolves as ``refs/heads/1.0.0``)
    succeed alongside PEP 440 constraint forms.
    """
    work = parent / "ks-catalog.work"
    bare = parent / "ks-catalog.git"
    init_git_work_dir(work)
    for tag in _KS_TAGS:
        (work / "version.txt").write_text(tag)
        run_git(["add", "version.txt"], work)
        run_git(["commit", "-m", f"version {tag}"], work)
        # Annotated tag: enables ``git describe --exact-match HEAD``.
        run_git(["tag", "-a", "-m", f"release {tag}", tag], work)
        # Branch with the tag name: enables plain ``revision="1.0.0"`` forms.
        run_git(["branch", tag], work)
    return clone_as_bare(work, bare)


def _make_ks_fix_repo(
    parent: pathlib.Path,
    catalog_fetch_url: str,
) -> pathlib.Path:
    """Build the KS-fixture manifest repo with 7 tags.

    Each tag version's ``default.xml`` pins the catalog project with
    ``revision="==<tag>"`` -- an equality PEP 440 constraint.  After
    ``kanon install`` resolves a ``.kanon`` REVISION constraint to a
    particular KS-fixture tag, running ``kanon repo manifest
    --revision-as-tag`` inside the synced source emits
    ``refs/tags/<tag>`` via the PEP 440 fallback resolver.
    """
    work = parent / "ks-fix.work"
    bare = parent / "ks-fix.git"
    init_git_work_dir(work)

    for tag in _KS_TAGS:
        rev_xml = xml_escape(f"=={tag}")
        default_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="origin" fetch="{catalog_fetch_url}" />\n'
            '  <default remote="origin" revision="main" />\n'
            f'  <project name="ks-catalog" path="ks-catalog" revision="{rev_xml}" />\n'
            "</manifest>\n"
        )
        (work / "default.xml").write_text(default_xml)
        run_git(["add", "default.xml"], work)
        run_git(["commit", "-m", f"version {tag}"], work)
        # Annotated tag: enables ``git describe --exact-match HEAD`` on the
        # KS-fixture source itself (used when kanon checks out the manifest).
        run_git(["tag", "-a", "-m", f"release {tag}", tag], work)
        # Branch with tag name: lets plain REVISION strings like ``1.0.0``
        # resolve as ``refs/heads/1.0.0`` in the KS-fixture source.
        run_git(["branch", tag], work)

    return clone_as_bare(work, bare)


def _build_ks_fixtures(base: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Build the KS fixture repos under *base*.

    Returns:
        (ks_fix_bare, ks_catalog_bare) -- both are bare git repo paths.

    ``ks_fix_bare`` is the manifest repo with 7 annotated tags.  Each
    tag's ``default.xml`` pins the catalog project with ``revision="==<tag>"``.

    ``ks_catalog_bare`` is the catalog content repo referenced by the
    manifest.  It has 7 annotated tags and matching branches.
    """
    base.mkdir(parents=True, exist_ok=True)

    content_dir = base / "content"
    manifest_dir = base / "manifest"
    content_dir.mkdir()
    manifest_dir.mkdir()

    catalog_bare = _make_ks_catalog_repo(content_dir)
    # repo appends ``<project-name>.git`` to the fetch URL.
    catalog_fetch_url = content_dir.as_uri()
    ks_fix_bare = _make_ks_fix_repo(manifest_dir, catalog_fetch_url)

    return ks_fix_bare, catalog_bare


# ---------------------------------------------------------------------------
# Core run helper
# ---------------------------------------------------------------------------


def _run_ks(
    work_dir: pathlib.Path,
    ks_fix_bare: pathlib.Path,
    revision: str,
    expected_tag: str,
) -> None:
    """Write .kanon, install, assert resolved tag via ``--revision-as-tag``.

    Writes a ``.kanon`` declaring a single source ``pep`` pointing at
    *ks_fix_bare* with *revision* as the REVISION constraint.  Runs
    ``kanon install``, then ``kanon repo manifest --revision-as-tag``
    inside the synced source dir and asserts that ``refs/tags/<expected_tag>``
    appears in the output.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    write_kanonenv(
        work_dir,
        [("pep", ks_fix_bare.as_uri(), revision, "default.xml")],
    )
    install_result = kanon_install(work_dir)
    assert install_result.returncode == 0, (
        f"kanon install exited {install_result.returncode}\n"
        f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
    )
    source_dir = work_dir / ".kanon-data" / "sources" / "pep"
    assert source_dir.is_dir(), f"source dir missing: {source_dir}"
    manifest_result = run_kanon("repo", "manifest", "--revision-as-tag", cwd=source_dir)
    combined = manifest_result.stdout + manifest_result.stderr
    assert f"refs/tags/{expected_tag}" in combined, (
        f"Expected refs/tags/{expected_tag} in manifest --revision-as-tag output.\n"
        f"returncode={manifest_result.returncode}\n"
        f"stdout={manifest_result.stdout!r}\nstderr={manifest_result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Class-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def ks_repos(tmp_path_factory: pytest.TempPathFactory) -> tuple[pathlib.Path, pathlib.Path]:
    """Class-scoped (ks_fix_bare, catalog_bare) built once for all TestKS methods."""
    base = tmp_path_factory.mktemp("ks_fixtures")
    return _build_ks_fixtures(base)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestKS:
    def test_ks_01_bare_latest(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-01: bare `latest` resolves to highest semver tag (3.0.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks01", ks_fix, "latest", "3.0.0")

    def test_ks_02_prefixed_refs_tags_latest(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-02: prefixed `refs/tags/latest` resolves to 3.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks02", ks_fix, "refs/tags/latest", "3.0.0")

    def test_ks_03_bare_wildcard(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-03: bare wildcard `*` resolves to highest semver tag (3.0.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks03", ks_fix, "*", "3.0.0")

    def test_ks_04_prefixed_refs_tags_wildcard(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-04: prefixed `refs/tags/*` resolves to 3.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks04", ks_fix, "refs/tags/*", "3.0.0")

    def test_ks_05_bare_plain_tag(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-05: bare plain tag `1.0.0` pins to exactly 1.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks05", ks_fix, "1.0.0", "1.0.0")

    def test_ks_06_bare_compatible_release_1_0_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-06: bare `~=1.0.0` resolves to highest 1.0.x (1.0.1)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks06", ks_fix, "~=1.0.0", "1.0.1")

    def test_ks_07_prefixed_compatible_release_1_0_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-07: prefixed `refs/tags/~=1.0.0` resolves to 1.0.1."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks07", ks_fix, "refs/tags/~=1.0.0", "1.0.1")

    def test_ks_08_bare_compatible_release_2_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-08: bare `~=2.0` resolves to highest 2.x (2.1.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks08", ks_fix, "~=2.0", "2.1.0")

    def test_ks_09_bare_ge_1_2_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-09: bare `>=1.2.0` resolves to highest matching tag (3.0.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks09", ks_fix, ">=1.2.0", "3.0.0")

    def test_ks_10_bare_lt_2_0_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-10: bare `<2.0.0` resolves to highest tag below 2.0.0 (1.2.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks10", ks_fix, "<2.0.0", "1.2.0")

    def test_ks_11_bare_le_1_1_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-11: bare `<=1.1.0` resolves to 1.1.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks11", ks_fix, "<=1.1.0", "1.1.0")

    def test_ks_12_bare_eq_1_0_1(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-12: bare `==1.0.1` resolves to exactly 1.0.1."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks12", ks_fix, "==1.0.1", "1.0.1")

    def test_ks_13_bare_ne_2_0_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-13: bare `!=2.0.0` resolves to highest tag != 2.0.0 (3.0.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks13", ks_fix, "!=2.0.0", "3.0.0")

    def test_ks_14_bare_range_ge_1_0_0_lt_2_0_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-14: bare `>=1.0.0,<2.0.0` resolves to highest in [1.0.0, 2.0.0) (1.2.0)."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks14", ks_fix, ">=1.0.0,<2.0.0", "1.2.0")

    def test_ks_15_prefixed_range_ge_2_0_0_lt_3_0_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-15: prefixed `refs/tags/>=2.0.0,<3.0.0` (production form) resolves to 2.1.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks15", ks_fix, "refs/tags/>=2.0.0,<3.0.0", "2.1.0")

    def test_ks_16_prefixed_compatible_release_2_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-16: prefixed `refs/tags/~=2.0` resolves to 2.1.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks16", ks_fix, "refs/tags/~=2.0", "2.1.0")

    def test_ks_17_prefixed_ge_1_2_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-17: prefixed `refs/tags/>=1.2.0` resolves to 3.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks17", ks_fix, "refs/tags/>=1.2.0", "3.0.0")

    def test_ks_18_prefixed_lt_2_0_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-18: prefixed `refs/tags/<2.0.0` resolves to 1.2.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks18", ks_fix, "refs/tags/<2.0.0", "1.2.0")

    def test_ks_19_prefixed_le_1_1_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-19: prefixed `refs/tags/<=1.1.0` resolves to 1.1.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks19", ks_fix, "refs/tags/<=1.1.0", "1.1.0")

    def test_ks_20_prefixed_eq_1_0_1(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-20: prefixed `refs/tags/==1.0.1` resolves to 1.0.1."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks20", ks_fix, "refs/tags/==1.0.1", "1.0.1")

    def test_ks_21_prefixed_ne_2_0_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-21: prefixed `refs/tags/!=2.0.0` resolves to 3.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks21", ks_fix, "refs/tags/!=2.0.0", "3.0.0")

    def test_ks_22_prefixed_range_ge_1_0_0_lt_2_0_0(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-22: prefixed `refs/tags/>=1.0.0,<2.0.0` resolves to 1.2.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks22", ks_fix, "refs/tags/>=1.0.0,<2.0.0", "1.2.0")

    def test_ks_23_prefixed_eq_3_0_0(self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]) -> None:
        """KS-23: prefixed `refs/tags/==3.0.0` resolves to 3.0.0."""
        ks_fix, _ = ks_repos
        _run_ks(tmp_path / "ks23", ks_fix, "refs/tags/==3.0.0", "3.0.0")

    def test_ks_24_env_var_override_revision(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-24: env-var KANON_SOURCE_pep_REVISION overrides the .kanon file value.

        The .kanon declares ``REVISION=main``; the env var supplies
        ``refs/tags/~=1.0.0`` which resolves to 1.0.1.  Pass criteria:
        ``kanon install`` exits 0 and ``--revision-as-tag`` shows
        ``refs/tags/1.0.1``.
        """
        ks_fix, _ = ks_repos
        work_dir = tmp_path / "ks24"
        work_dir.mkdir()
        write_kanonenv(
            work_dir,
            [("pep", ks_fix.as_uri(), "main", "default.xml")],
        )
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_SOURCE_pep_REVISION": "refs/tags/~=1.0.0"},
        )
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        source_dir = work_dir / ".kanon-data" / "sources" / "pep"
        assert source_dir.is_dir(), f"source dir missing: {source_dir}"
        manifest_result = run_kanon("repo", "manifest", "--revision-as-tag", cwd=source_dir)
        combined = manifest_result.stdout + manifest_result.stderr
        assert "refs/tags/1.0.1" in combined, (
            f"Expected refs/tags/1.0.1 (env-var override) in manifest output.\n"
            f"returncode={manifest_result.returncode}\n"
            f"stdout={manifest_result.stdout!r}\nstderr={manifest_result.stderr!r}"
        )

    def test_ks_25_undefined_shell_var_in_revision_errors_clearly(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-25: undefined shell variable in REVISION causes non-zero exit naming the var.

        The .kanon stores ``REVISION=${UNDEFINED_KS_VAR}``.  Pass criteria:
        non-zero exit code; ``UNDEFINED_KS_VAR`` appears in stderr.
        """
        ks_fix, _ = ks_repos
        work_dir = tmp_path / "ks25"
        work_dir.mkdir()
        (work_dir / ".kanon").write_text(
            f"KANON_SOURCE_pep_URL={ks_fix.as_uri()}\n"
            "KANON_SOURCE_pep_REVISION=${UNDEFINED_KS_VAR}\n"
            "KANON_SOURCE_pep_PATH=default.xml\n"
        )
        result = kanon_install(work_dir)
        assert result.returncode != 0, (
            f"Expected non-zero exit for undefined shell var, got 0.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "UNDEFINED_KS_VAR" in result.stderr, (
            f"Expected 'UNDEFINED_KS_VAR' named in stderr.\nstderr={result.stderr!r}"
        )

    def test_ks_26_invalid_eq_star_revision_rejected(
        self, tmp_path: pathlib.Path, ks_repos: tuple[pathlib.Path, pathlib.Path]
    ) -> None:
        """KS-26: invalid `==*` REVISION is rejected with a clear error.

        Pass criteria: non-zero exit code; stderr contains
        ``invalid version constraint``.
        """
        ks_fix, _ = ks_repos
        work_dir = tmp_path / "ks26"
        work_dir.mkdir()
        write_kanonenv(
            work_dir,
            [("pep", ks_fix.as_uri(), "==*", "default.xml")],
        )
        result = kanon_install(work_dir)
        assert result.returncode != 0, (
            f"Expected non-zero exit for invalid ==* constraint, got 0.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "invalid version constraint" in result.stderr.lower(), (
            f"Expected 'invalid version constraint' in stderr.\nstderr={result.stderr!r}"
        )
