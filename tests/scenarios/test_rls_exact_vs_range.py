"""Scenario tests: --refresh-lock-source exact-pin vs range-spec semantics.

Documents and locks the operator decision from Section 13 D3:

  - Exact-tag-pinned sources (e.g. ``==1.0.0``) STAY at their resolved SHA
    after ``kanon install --refresh-lock-source``.  An exact pin is a pin.
  - Range/floating sources (e.g. ``>=1.0.0``) ADVANCE to the newest matching
    tag after ``--refresh-lock-source`` when a new tag is published.
  - Branch-ref-pinned sources (e.g. ``main``) are treated as floating and
    ADVANCE to the new branch tip.

These are subprocess (operator-path) tests: each test invokes ``kanon install``
as a real subprocess against on-disk fixture git repos, reads the resulting
``.kanon.lock`` via the Python lockfile reader, and asserts SHA identity or
change.

AC-FUNC-001: test_range_spec_advances_on_refresh (RED guard) and
             test_exact_tag_pin_stays_on_refresh.
AC-FUNC-002: test_branch_ref_floating_spec_advances_to_new_tip (parametrised branch-ref case).
AC-TEST-003: No caylent-private-kanon runtime dependency; fixture is synthetic
             using real local file:// URLs.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import init_git_work_dir, make_plain_repo, run_git


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _git_capturing(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command and return stripped stdout; raise RuntimeError on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} failed in {cwd!r} (exit {result.returncode}):"
            f"\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    return result.stdout.strip()


def _sha_for_ref(repo: pathlib.Path, ref: str) -> str:
    """Resolve a ref to a SHA in the given repo."""
    return _git_capturing(["rev-parse", ref], repo)


def _build_source_fixture(
    base_dir: pathlib.Path,
    name: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Build a source fixture: a content repo and a manifest repo referencing it.

    Creates:
    - ``base_dir/content/<name>-content.git`` -- a plain bare content repo.
    - ``base_dir/manifest/<name>.git`` -- a bare manifest repo whose
      ``manifest.xml`` references the content repo via a ``file://`` URL.

    Both repos are tagged at ``1.0.0`` with an annotated tag.

    Args:
        base_dir: Parent directory for the fixture repos.
        name: Logical name used to label the repo directories.

    Returns:
        ``(content_bare, manifest_bare)`` -- absolute paths to both bare repos.
    """
    content_dir = base_dir / "content"
    manifest_dir = base_dir / "manifest"
    content_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    content_bare = make_plain_repo(content_dir, f"{name}-content", {"README.md": f"# {name}\n"})

    content_fetch_url = content_dir.as_uri() + "/"

    manifest_work = manifest_dir / f"{name}-work"
    manifest_work.mkdir(parents=True)
    init_git_work_dir(manifest_work)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_fetch_url}"/>\n'
        '  <default remote="local" revision="main"/>\n'
        f'  <project name="{name}-content" path=".packages/{name}"/>\n'
        "</manifest>\n"
    )
    (manifest_work / "manifest.xml").write_text(manifest_xml)
    run_git(["add", "manifest.xml"], manifest_work)
    run_git(["commit", "-m", "Add manifest.xml"], manifest_work)
    run_git(["tag", "-a", "1.0.0", "-m", "Release 1.0.0"], manifest_work)

    manifest_bare = manifest_dir / f"{name}.git"
    run_git(["clone", "--bare", str(manifest_work), str(manifest_bare)], manifest_dir)
    return content_bare, manifest_bare.resolve()


def _sha_from_manifest_bare(manifest_bare: pathlib.Path, ref: str) -> str:
    """Return the SHA that ref resolves to in the manifest bare repo."""
    return _git_capturing(["rev-parse", ref], manifest_bare)


def _advance_manifest_bare(work_root: pathlib.Path, manifest_bare: pathlib.Path, new_tag: str) -> str:
    """Add a commit to the manifest repo, tag it, and push; return the new SHA.

    Args:
        work_root: Scratch directory for the temporary clone.
        manifest_bare: Absolute path to the manifest bare repo.
        new_tag: PEP 440-valid tag name for the new commit.

    Returns:
        The SHA of the new tag's commit in the bare repo.
    """
    clone = work_root / f"{manifest_bare.name}-clone-{new_tag}"
    clone.mkdir(parents=True)
    _git_capturing(["clone", str(manifest_bare), str(clone)], work_root)
    _git_capturing(["config", "user.name", "Test"], clone)
    _git_capturing(["config", "user.email", "t@t.com"], clone)
    (clone / "CHANGELOG.md").write_text(f"## {new_tag}\n")
    _git_capturing(["add", "CHANGELOG.md"], clone)
    _git_capturing(["commit", "-m", f"release {new_tag}"], clone)
    _git_capturing(["tag", "-a", new_tag, "-m", f"Release {new_tag}"], clone)
    _git_capturing(["push", "origin", "HEAD:main", "--tags"], clone)
    return _sha_for_ref(clone, f"refs/tags/{new_tag}")


def _advance_manifest_branch(work_root: pathlib.Path, manifest_bare: pathlib.Path) -> str:
    """Add a commit to the manifest repo's main branch and push; return the new tip SHA.

    Args:
        work_root: Scratch directory for the temporary clone.
        manifest_bare: Absolute path to the manifest bare repo.

    Returns:
        The SHA of the new HEAD commit in the clone (= new tip in the bare repo).
    """
    clone = work_root / "manifest-branch-clone"
    clone.mkdir(parents=True)
    _git_capturing(["clone", str(manifest_bare), str(clone)], work_root)
    _git_capturing(["config", "user.name", "Test"], clone)
    _git_capturing(["config", "user.email", "t@t.com"], clone)
    (clone / "ADVANCE.md").write_text("branch advance\n")
    _git_capturing(["add", "ADVANCE.md"], clone)
    _git_capturing(["commit", "-m", "advance branch tip"], clone)
    _git_capturing(["push", "origin", "HEAD:main"], clone)
    return _sha_for_ref(clone, "HEAD")


def _write_kanon(
    project_dir: pathlib.Path,
    sources: list[tuple[str, pathlib.Path, str]],
) -> pathlib.Path:
    """Write a .kanon file declaring the given sources and return its path.

    Args:
        project_dir: Directory where .kanon is written.
        sources: List of ``(name, manifest_bare_path, revision_spec)`` triples.

    Returns:
        Path to the written .kanon file.
    """
    lines: list[str] = [
        "GITBASE=https://unused.example.com",
        f"CLAUDE_MARKETPLACES_DIR={project_dir / 'kanon-test-mktplc'}",
        "KANON_MARKETPLACE_INSTALL=false",
    ]
    for name, manifest_bare, revision in sources:
        url = manifest_bare.as_uri()
        lines.append(f"KANON_SOURCE_{name}_URL={url}")
        lines.append(f"KANON_SOURCE_{name}_REF={revision}")
        lines.append(f"KANON_SOURCE_{name}_PATH=manifest.xml")
        lines.append(f"KANON_SOURCE_{name}_NAME={name}")
        lines.append(f"KANON_SOURCE_{name}_GITBASE={url}")
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text("\n".join(lines) + "\n")
    kanon_path.chmod(0o600)
    return kanon_path


def _run_kanon_install(
    project_dir: pathlib.Path,
    *,
    refresh_lock_source: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke ``kanon install`` as a subprocess and return the result.

    ``kanon install`` is hermetic (schema v4 / FR-7): it installs exactly the
    sources declared in ``.kanon`` and pinned in ``.kanon.lock`` and never resolves
    a remote catalog. The subprocess is therefore run with ``KANON_CATALOG_SOURCE``
    scrubbed and no ``--catalog-source`` flag; supplying either would be rejected
    fail-fast by ``HermeticInstallCatalogSourceError``. The ``--refresh-lock-source``
    path is likewise hermetic and needs no catalog source.

    Args:
        project_dir: Working directory for the kanon invocation.
        refresh_lock_source: When set, passes ``--refresh-lock-source <name>``.

    Returns:
        The completed subprocess result.
    """
    import sys

    cmd = [sys.executable, "-m", "kanon_cli", "install"]
    if refresh_lock_source is not None:
        cmd += ["--refresh-lock-source", refresh_lock_source]
    env = {
        **os.environ,
        "KANON_ALLOW_INSECURE_REMOTES": "1",
    }
    env.pop("KANON_CATALOG_SOURCE", None)
    return subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _assert_install_ok(result: subprocess.CompletedProcess, context: str) -> None:
    """Assert the install subprocess exited 0; raise AssertionError with context on failure."""
    assert result.returncode == 0, (
        f"{context}: kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def _resolved_sha(lock_path: pathlib.Path, source_name: str) -> str:
    """Read the lockfile and return the resolved_sha for the named source.

    Args:
        lock_path: Path to the .kanon.lock file.
        source_name: Name of the source entry to look up.

    Returns:
        The resolved_sha string for the named source.

    Raises:
        KeyError: If no source with that name is present in the lockfile.
    """
    lf = read_lockfile(lock_path)
    for entry in lf.sources:
        if entry.name == source_name:
            return entry.resolved_sha
    known = [e.name for e in lf.sources]
    raise KeyError(f"Source {source_name!r} not found in lockfile; known: {known!r}")


@pytest.mark.scenario
class TestRlsExactVsRange:
    """AC-FUNC-001/AC-FUNC-002: --refresh-lock-source exact-vs-range semantics.

    Validates the operator decision from Section 13 D3:
    - Exact-tag pins stay at their SHA after --refresh-lock-source.
    - Range specs advance to the newest matching tag.
    - Branch-ref floating specs advance to the new branch tip.
    """

    def test_range_spec_advances_on_refresh(self, tmp_path: pathlib.Path) -> None:
        """RED guard: range-spec resolved SHA changes after a new tag + --refresh-lock-source.

        This assertion MUST fail if the range-spec resolution path regresses.
        On a regression, halt and surface the before/after SHAs.

        Scenario:
        1. Build source fixtures: ``rangesrc`` (range spec ``>=1.0.0``) and
           ``exactsrc`` (exact pin ``==1.0.0``).
        2. Baseline install -- records both sources' 1.0.0 SHAs in the lockfile.
        3. Publish tag 1.1.0 on both manifest repos.
        4. Run ``kanon install --refresh-lock-source rangesrc``.
        5. Assert rangesrc's SHA changed to 1.1.0's SHA (range advanced).
        6. Assert exactsrc's SHA is unchanged (not the refresh target; preserved verbatim).
        """
        _, rangesrc_bare = _build_source_fixture(tmp_path / "rangesrc-fix", "rangesrc")
        _, exactsrc_bare = _build_source_fixture(tmp_path / "exactsrc-fix", "exactsrc")

        rangesrc_sha_v1 = _sha_from_manifest_bare(rangesrc_bare, "refs/tags/1.0.0")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_kanon(
            project_dir,
            sources=[
                ("rangesrc", rangesrc_bare, ">=1.0.0"),
                ("exactsrc", exactsrc_bare, "==1.0.0"),
            ],
        )

        baseline = _run_kanon_install(project_dir)
        _assert_install_ok(baseline, "baseline install")
        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "baseline install must write a lockfile"

        sha_rangesrc_before = _resolved_sha(lock_path, "rangesrc")
        sha_exactsrc_before = _resolved_sha(lock_path, "exactsrc")
        assert sha_rangesrc_before == rangesrc_sha_v1, (
            f"Baseline rangesrc SHA mismatch: expected {rangesrc_sha_v1!r}, got {sha_rangesrc_before!r}"
        )

        scratch = tmp_path / "advance-scratch"
        scratch.mkdir()
        rangesrc_sha_v2 = _advance_manifest_bare(scratch, rangesrc_bare, "1.1.0")
        _advance_manifest_bare(scratch, exactsrc_bare, "1.1.0")

        refresh_result = _run_kanon_install(project_dir, refresh_lock_source="rangesrc")
        _assert_install_ok(refresh_result, "--refresh-lock-source rangesrc")

        sha_rangesrc_after = _resolved_sha(lock_path, "rangesrc")
        sha_exactsrc_after = _resolved_sha(lock_path, "exactsrc")

        assert sha_rangesrc_after != sha_rangesrc_before, (
            f"ERROR: range-spec source 'rangesrc' did NOT advance SHA after "
            f"--refresh-lock-source + new tag 1.1.0 -- the resolution path has regressed. "
            f"SHA before: {sha_rangesrc_before!r}, SHA after: {sha_rangesrc_after!r}"
        )
        assert sha_rangesrc_after == rangesrc_sha_v2, (
            f"ERROR: rangesrc SHA after refresh is {sha_rangesrc_after!r}; "
            f"expected {rangesrc_sha_v2!r} (the 1.1.0 tag commit SHA)"
        )

        assert sha_exactsrc_after == sha_exactsrc_before, (
            f"ERROR: exactsrc (not the refresh target) SHA changed unexpectedly: "
            f"before={sha_exactsrc_before!r}, after={sha_exactsrc_after!r}"
        )

    def test_exact_tag_pin_stays_on_refresh(self, tmp_path: pathlib.Path) -> None:
        """Documenting test: exact-tag-pinned source SHA is unchanged after --refresh-lock-source.

        An exact pin is a pin -- the resolver always maps ``==1.0.0`` back to the
        1.0.0 tag commit, so ``--refresh-lock-source`` on an exact-pinned source
        produces the same SHA even after new tags are published.

        If this test fails, it means an exact-pinned source DID change SHA --
        a pin must stay pinned; surface the before/after SHAs rather than
        relaxing the assertion.
        """
        _, exactsrc_bare = _build_source_fixture(tmp_path / "exactsrc-fix", "exactsrc")
        _, other_bare = _build_source_fixture(tmp_path / "other-fix", "other")

        exactsrc_sha_v1 = _sha_from_manifest_bare(exactsrc_bare, "refs/tags/1.0.0")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_kanon(
            project_dir,
            sources=[
                ("exactsrc", exactsrc_bare, "==1.0.0"),
                ("other", other_bare, ">=1.0.0"),
            ],
        )

        baseline = _run_kanon_install(project_dir)
        _assert_install_ok(baseline, "baseline install")
        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "baseline install must write a lockfile"

        sha_exact_before = _resolved_sha(lock_path, "exactsrc")
        assert sha_exact_before == exactsrc_sha_v1, (
            f"Baseline exactsrc SHA mismatch: expected {exactsrc_sha_v1!r}, got {sha_exact_before!r}"
        )

        scratch = tmp_path / "advance-scratch"
        scratch.mkdir()
        _advance_manifest_bare(scratch, exactsrc_bare, "1.1.0")
        _advance_manifest_bare(scratch, other_bare, "1.1.0")

        refresh_result = _run_kanon_install(project_dir, refresh_lock_source="exactsrc")
        _assert_install_ok(refresh_result, "--refresh-lock-source exactsrc")

        sha_exact_after = _resolved_sha(lock_path, "exactsrc")

        assert sha_exact_after == sha_exact_before, (
            f"ERROR: exact-tag-pinned source 'exactsrc' (==1.0.0) changed SHA after "
            f"--refresh-lock-source -- a pin must stay pinned. "
            f"SHA before: {sha_exact_before!r}, SHA after: {sha_exact_after!r}"
        )

    @pytest.mark.parametrize(
        "branch_ref",
        [
            "main",
            "refs/heads/main",
        ],
    )
    def test_branch_ref_floating_spec_advances_to_new_tip(self, tmp_path: pathlib.Path, branch_ref: str) -> None:
        """AC-FUNC-002: branch-ref-pinned source advances to the new branch tip.

        Branch refs (plain branch names and ``refs/heads/...``) are treated as
        floating specs: ``--refresh-lock-source`` advances them to the current
        branch tip.

        Parametrised over:
        - plain branch name ``main``
        - fully-qualified ``refs/heads/main``

        Args:
            tmp_path: pytest-provided temporary directory.
            branch_ref: The revision spec string to use for the branch source.
        """
        _, branchsrc_bare = _build_source_fixture(tmp_path / "branchsrc-fix", "branchsrc")
        _, exact_bare = _build_source_fixture(tmp_path / "exact-fix", "exact")

        sha_branch_v1 = _sha_from_manifest_bare(branchsrc_bare, "HEAD")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_kanon(
            project_dir,
            sources=[
                ("branchsrc", branchsrc_bare, branch_ref),
                ("exact", exact_bare, "==1.0.0"),
            ],
        )

        baseline = _run_kanon_install(project_dir)
        _assert_install_ok(baseline, f"baseline install (branch_ref={branch_ref!r})")
        lock_path = project_dir / ".kanon.lock"
        assert lock_path.exists(), "baseline install must write a lockfile"

        sha_branch_before = _resolved_sha(lock_path, "branchsrc")
        assert sha_branch_before == sha_branch_v1, (
            f"Baseline branchsrc SHA mismatch: expected {sha_branch_v1!r}, got {sha_branch_before!r}"
        )

        scratch = tmp_path / "advance-scratch"
        scratch.mkdir()
        sha_branch_v2 = _advance_manifest_branch(scratch, branchsrc_bare)

        refresh_result = _run_kanon_install(project_dir, refresh_lock_source="branchsrc")
        _assert_install_ok(refresh_result, f"--refresh-lock-source branchsrc (branch_ref={branch_ref!r})")

        sha_branch_after = _resolved_sha(lock_path, "branchsrc")

        assert sha_branch_after != sha_branch_before, (
            f"ERROR: branch-ref-pinned source 'branchsrc' (revision={branch_ref!r}) "
            f"did NOT advance SHA after branch tip moved + --refresh-lock-source. "
            f"SHA before: {sha_branch_before!r}, SHA after: {sha_branch_after!r}"
        )
        assert sha_branch_after == sha_branch_v2, (
            f"ERROR: branchsrc SHA after refresh is {sha_branch_after!r}; expected new tip {sha_branch_v2!r}"
        )
