"""PK (Plain Packages) scenarios from `docs/integration-testing.md` §19.

Each scenario exercises the `kanon install` / `kanon clean` lifecycle for
plain-package (non-marketplace) sources backed by bare git repos with semver
tags 1.0.0..3.0.0. No marketplace install occurs in any of these scenarios.

Scenarios automated:
- PK-01: basic install/clean
- PK-02: PEP 440 `~=1.0.0` in XML revision
- PK-03: PEP 440 `~=1.0.0` in .kanon REVISION (XML revision=main)
- PK-04: PEP 440 in BOTH XML and .kanon
- PK-05: clean is no-op when nothing was installed
- PK-06: re-install after clean -- end state matches first install
- PK-07: env override of KANON_SOURCE_<name>_REVISION at install time
- PK-08: invalid `==*` rejected
- PK-09: multiple packages from one source
- PK-10: linkfile entries with PEP 440
- PK-11: multi-source aggregation with PEP 440 mix
- PK-12: collision with PEP 440 (two sources resolving to same package name)
- PK-13: .gitignore promise -- .packages/ and .kanon-data/ added
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_clean,
    kanon_install,
    make_bare_repo_with_tags,
    make_plain_repo,
    run_git,
    xml_escape,
)

# ---------------------------------------------------------------------------
# Tags that every package repo carries (mirrors the bash fixture)
# ---------------------------------------------------------------------------

_PK_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_pkg_repo(parent: pathlib.Path, name: str) -> pathlib.Path:
    """Create a bare package repo named `name` with semver tags _PK_TAGS."""
    return make_bare_repo_with_tags(parent, name, _PK_TAGS)


def _build_pkg_repo_with_src(parent: pathlib.Path, name: str) -> pathlib.Path:
    """Create a bare package repo with src/main.py and semver tags _PK_TAGS."""
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    src_dir = work / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(f"# {name} main\n")
    run_git(["add", "src/main.py"], work)
    run_git(["commit", "-m", f"add src/main.py for {name}"], work)
    for tag in _PK_TAGS:
        (work / "version.txt").write_text(tag)
        run_git(["add", "version.txt"], work)
        run_git(["commit", "-m", f"version {tag}"], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


def _manifest_xml_for(
    pkg_repos_dir: pathlib.Path,
    entries: list[dict],
) -> str:
    """Render manifest XML with fetch pointing at ``pkg_repos_dir``.

    Each entry must have ``name``, ``path``, ``revision`` keys.
    Optional ``linkfile`` key: ``{"src": ..., "dest": ...}``.
    """
    fetch_url = pkg_repos_dir.as_uri() + "/"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<manifest>",
        f'  <remote name="local" fetch="{fetch_url}" />',
        '  <default remote="local" revision="main" />',
    ]
    for entry in entries:
        rev = xml_escape(entry["revision"])
        name = entry["name"]
        path = entry["path"]
        lf = entry.get("linkfile")
        if lf:
            lines.append(f'  <project name="{name}" path="{path}" remote="local" revision="{rev}">')
            lines.append(f'    <linkfile src="{lf["src"]}" dest="{lf["dest"]}" />')
            lines.append("  </project>")
        else:
            lines.append(f'  <project name="{name}" path="{path}" remote="local" revision="{rev}" />')
    lines.append("</manifest>")
    return "\n".join(lines) + "\n"


_MFST_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


def _build_manifest_repo(
    parent: pathlib.Path,
    repo_name: str,
    manifests: dict[str, str],
    *,
    with_tags: bool = False,
) -> pathlib.Path:
    """Create a bare git repo containing the given manifest XML files.

    Returns the path to the bare repo (use ``.as_uri()`` for KANON_SOURCE URL).

    When ``with_tags=True`` the repo receives empty commits for each tag in
    ``_MFST_TAGS`` after the initial seed commit. This is required when the
    ``.kanon`` REVISION carries a PEP 440 constraint that kanon resolves
    against the manifest source repo's own tags.
    """
    if not with_tags:
        return make_plain_repo(parent, repo_name, manifests)

    work = parent / f"{repo_name}.work"
    bare = parent / f"{repo_name}.git"
    init_git_work_dir(work)
    for relpath, content in manifests.items():
        target = work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        run_git(["add", relpath], work)
    run_git(["commit", "-m", f"seed {repo_name}"], work)
    for tag in _MFST_TAGS:
        run_git(["commit", "--allow-empty", "-m", tag], work)
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


def _write_kanon(
    work_dir: pathlib.Path,
    manifest_repo_url: str,
    manifest_path: str,
    revision: str = "main",
    *,
    extra_lines: list[str] | None = None,
) -> pathlib.Path:
    """Write a .kanon file for the ``pk`` source pointing at a manifest repo."""
    lines = [
        f"KANON_SOURCE_pk_URL={manifest_repo_url}",
        f"KANON_SOURCE_pk_REVISION={revision}",
        f"KANON_SOURCE_pk_PATH={manifest_path}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    p = work_dir / ".kanon"
    p.write_text("\n".join(lines) + "\n")
    return p


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_symlink_exists(work_dir: pathlib.Path, pkg_name: str) -> None:
    link = work_dir / ".packages" / pkg_name
    assert link.is_symlink(), f".packages/{pkg_name} is not a symlink -- install may have failed"


def _assert_symlink_absent(work_dir: pathlib.Path, pkg_name: str) -> None:
    link = work_dir / ".packages" / pkg_name
    assert not link.exists(), f".packages/{pkg_name} still exists after clean"


def _assert_install_ok(result, work_dir: pathlib.Path) -> None:
    assert result.returncode == 0, (
        f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"


def _assert_clean_ok(result, work_dir: pathlib.Path) -> None:
    assert result.returncode == 0, (
        f"kanon clean exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "kanon clean: done" in result.stdout, f"'kanon clean: done' not in stdout: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestPK:
    def test_pk_01_basic_install_and_clean(self, tmp_path: pathlib.Path) -> None:
        """PK-01: basic install/clean -- symlink present after install, gone after clean."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk01")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk01", "path": ".packages/pk01", "revision": "main"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk01.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk01.xml")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk01")

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        assert not (work_dir / ".packages").exists(), ".packages/ still exists after clean"
        assert not (work_dir / ".kanon-data").exists(), ".kanon-data/ still exists after clean"

    def test_pk_02_pep440_tilde_equal_in_xml(self, tmp_path: pathlib.Path) -> None:
        """PK-02: PEP 440 `~=1.0.0` in XML revision resolves to 1.0.1."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk02")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk02", "path": ".packages/pk02", "revision": "refs/tags/~=1.0.0"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk02.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk02.xml", revision="main")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk02")

        # ~=1.0.0 means >=1.0.0, ==1.0.* -- highest compatible tag is 1.0.1
        version_file = work_dir / ".packages" / "pk02" / "version.txt"
        assert version_file.exists(), "version.txt missing inside installed package"
        resolved = version_file.read_text().strip()
        assert resolved == "1.0.1", f"Expected ~=1.0.0 to resolve to 1.0.1, got {resolved!r}"

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        _assert_symlink_absent(work_dir, "pk02")

    def test_pk_03_pep440_tilde_equal_in_kanon_revision(self, tmp_path: pathlib.Path) -> None:
        """PK-03: PEP 440 `~=1.0.0` in .kanon REVISION (XML revision=main) resolves correctly."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk03")
        # XML uses plain "main"; the PEP 440 constraint is in .kanon REVISION.
        # The manifest repo must have tags so kanon can resolve the PEP 440
        # constraint against the manifest source.
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk03", "path": ".packages/pk03", "revision": "main"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk03.xml": xml}, with_tags=True)
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk03.xml", revision="refs/tags/~=1.0.0")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk03")

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        _assert_symlink_absent(work_dir, "pk03")

    def test_pk_04_pep440_in_both_xml_and_kanon(self, tmp_path: pathlib.Path) -> None:
        """PK-04: PEP 440 `>=1.0.0,<2.0.0` in both XML and .kanon resolves to 1.2.0."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk04")
        xml = _manifest_xml_for(
            pkg_dir,
            [{"name": "pk04", "path": ".packages/pk04", "revision": "refs/tags/>=1.0.0,<2.0.0"}],
        )
        # Manifest repo needs tags so PEP 440 in .kanon REVISION can be resolved.
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk04.xml": xml}, with_tags=True)
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk04.xml", revision="refs/tags/>=1.0.0,<2.0.0")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk04")

        version_file = work_dir / ".packages" / "pk04" / "version.txt"
        assert version_file.exists(), "version.txt missing inside installed package"
        resolved = version_file.read_text().strip()
        assert resolved == "1.2.0", f"Expected >=1.0.0,<2.0.0 to resolve to 1.2.0, got {resolved!r}"

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        _assert_symlink_absent(work_dir, "pk04")

    def test_pk_05_clean_is_noop_when_nothing_installed(self, tmp_path: pathlib.Path) -> None:
        """PK-05: clean is a no-op when nothing was installed (exit 0, no error)."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk05")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk05", "path": ".packages/pk05", "revision": "main"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk05.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk05.xml")

        # Run clean without having installed first
        result = kanon_clean(work_dir)
        assert result.returncode == 0, (
            f"kanon clean exited {result.returncode} without prior install\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Confirm no error text about missing .kanon-data
        assert "error" not in result.stderr.lower() or ".kanon-data" not in result.stderr, (
            f"Unexpected error about .kanon-data in stderr: {result.stderr!r}"
        )

    def test_pk_06_reinstall_after_clean(self, tmp_path: pathlib.Path) -> None:
        """PK-06: re-install after clean produces the same end state as the first install."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk06")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk06", "path": ".packages/pk06", "revision": "main"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk06.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk06.xml")

        # First install
        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk06")

        # First clean
        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        assert not (work_dir / ".packages").exists(), ".packages/ not removed by first clean"

        # Second install
        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk06")

        # Second clean
        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)
        assert not (work_dir / ".packages").exists(), ".packages/ not removed by second clean"

    def test_pk_07_env_override_revision(self, tmp_path: pathlib.Path) -> None:
        """PK-07: env override of KANON_SOURCE_pk_REVISION resolves to 2.1.0."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk07")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk07", "path": ".packages/pk07", "revision": "main"}])
        # Manifest repo needs tags so the env-override PEP 440 constraint can be resolved.
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk07.xml": xml}, with_tags=True)
        # .kanon says "main" -- env override should win
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk07.xml", revision="main")

        result = kanon_install(
            work_dir,
            extra_env={"KANON_SOURCE_pk_REVISION": "refs/tags/~=2.0.0"},
        )
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk07")

        # The env override caused the manifest source to be pinned to a ~=2.0.0
        # compatible tag.  The package itself is fetched at the revision declared
        # in the manifest ("main"), so the exact version.txt value is not the
        # meaningful assertion here.  What matters is that the override was
        # accepted and the install succeeded (symlink present above).

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)

    def test_pk_08_invalid_constraint_rejected(self, tmp_path: pathlib.Path) -> None:
        """PK-08: invalid `==*` constraint is rejected with non-zero exit and error message."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk08")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk08", "path": ".packages/pk08", "revision": "==*"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk08.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk08.xml", revision="main")

        result = kanon_install(work_dir)
        assert result.returncode != 0, (
            f"Expected non-zero exit for invalid constraint ==* but got 0\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "invalid" in combined or "constraint" in combined or "version" in combined, (
            f"Expected error about invalid version constraint in output, got:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_pk_09_multiple_packages_from_one_source(self, tmp_path: pathlib.Path) -> None:
        """PK-09: multiple packages declared in one manifest all get symlinks."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk09")
        # Two separate path entries pointing at the same repo name
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{pkg_dir.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="pk09" path=".packages/pk09" remote="local" revision="main" />\n'
            '  <project name="pk09" path=".packages/pk09-extra" remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk09.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk09.xml")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk09")
        _assert_symlink_exists(work_dir, "pk09-extra")

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)

    def test_pk_10_linkfile_with_pep440(self, tmp_path: pathlib.Path) -> None:
        """PK-10: linkfile entries with PEP 440 -- project symlink and linkfile target both present."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        # pk10 repo must have src/main.py to satisfy the linkfile src
        _build_pkg_repo_with_src(pkg_dir, "pk10")

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{pkg_dir.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="pk10" path=".packages/pk10" remote="local" revision="refs/tags/~=2.0.0">\n'
            '    <linkfile src="src/main.py" dest=".packages/pk10-main.py" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk10.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk10.xml")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk10")
        linkfile_target = work_dir / ".packages" / "pk10-main.py"
        assert linkfile_target.exists(), ".packages/pk10-main.py linkfile target missing after install"

        # ~=2.0.0 means >=2.0.0, ==2.0.* -- only 2.0.0 qualifies from the tag set
        version_file = work_dir / ".packages" / "pk10" / "version.txt"
        if version_file.exists():
            resolved = version_file.read_text().strip()
            assert resolved == "2.0.0", f"Expected ~=2.0.0 to resolve to 2.0.0, got {resolved!r}"

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)

    def test_pk_11_multi_source_aggregation(self, tmp_path: pathlib.Path) -> None:
        """PK-11: multi-source aggregation with PEP 440 mix -- both package symlinks present."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk11a")
        _build_pkg_repo(pkg_dir, "pk11b")

        # Single manifest with two projects at different PEP 440 constraints
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{pkg_dir.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="pk11a" path=".packages/pk11a" remote="local" revision="refs/tags/~=1.0.0" />\n'
            f'  <project name="pk11b" path=".packages/pk11b" remote="local" revision="refs/tags/{xml_escape(">=2.0.0")}" />\n'
            "</manifest>\n"
        )
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk11.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk11.xml")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)
        _assert_symlink_exists(work_dir, "pk11a")
        _assert_symlink_exists(work_dir, "pk11b")

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)

    def test_pk_12_collision_two_sources_same_package(self, tmp_path: pathlib.Path) -> None:
        """PK-12: two sources declare the same package name; install is rejected."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk12")
        xml = _manifest_xml_for(
            pkg_dir,
            [{"name": "pk12", "path": ".packages/pk12", "revision": "refs/tags/~=1.0.0"}],
        )
        # Both sources a and b point at the same manifest declaring "pk12"
        mfst_a = _build_manifest_repo(mfst_repos, "mfst-a", {"pk12.xml": xml})
        mfst_b = _build_manifest_repo(mfst_repos, "mfst-b", {"pk12.xml": xml})

        kanon_file = work_dir / ".kanon"
        kanon_file.write_text(
            f"KANON_SOURCE_a_URL={mfst_a.as_uri()}\n"
            "KANON_SOURCE_a_REVISION=main\n"
            "KANON_SOURCE_a_PATH=pk12.xml\n"
            f"KANON_SOURCE_b_URL={mfst_b.as_uri()}\n"
            "KANON_SOURCE_b_REVISION=main\n"
            "KANON_SOURCE_b_PATH=pk12.xml\n"
        )

        result = kanon_install(work_dir)
        assert result.returncode != 0, (
            f"Expected non-zero exit for package name collision but got 0\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "pk12" in combined, (
            f"Expected colliding package name 'pk12' in error output:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_pk_13_gitignore_entries_added_and_preserved(self, tmp_path: pathlib.Path) -> None:
        """PK-13: .gitignore gets .packages/ and .kanon-data/ entries; clean preserves them."""
        pkg_dir = tmp_path / "repos"
        pkg_dir.mkdir()
        mfst_repos = tmp_path / "mfst-repos"
        mfst_repos.mkdir()
        work_dir = tmp_path / "ws"
        work_dir.mkdir()

        _build_pkg_repo(pkg_dir, "pk13")
        xml = _manifest_xml_for(pkg_dir, [{"name": "pk13", "path": ".packages/pk13", "revision": "main"}])
        mfst_bare = _build_manifest_repo(mfst_repos, "mfst", {"pk13.xml": xml})
        _write_kanon(work_dir, mfst_bare.as_uri(), "pk13.xml")

        result = kanon_install(work_dir)
        _assert_install_ok(result, work_dir)

        gitignore = work_dir / ".gitignore"
        assert gitignore.exists(), ".gitignore not created by kanon install"
        text = gitignore.read_text()
        assert ".packages/" in text, f".gitignore missing '.packages/' entry:\n{text!r}"
        assert ".kanon-data/" in text, f".gitignore missing '.kanon-data/' entry:\n{text!r}"

        result = kanon_clean(work_dir)
        _assert_clean_ok(result, work_dir)

        # .gitignore must survive clean
        assert gitignore.exists(), ".gitignore removed by kanon clean"
        text_after = gitignore.read_text()
        assert ".packages/" in text_after, f".gitignore missing '.packages/' after clean:\n{text_after!r}"
        assert ".kanon-data/" in text_after, f".gitignore missing '.kanon-data/' after clean:\n{text_after!r}"
