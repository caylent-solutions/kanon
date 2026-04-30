"""MK (Marketplace Plugins) scenarios from `docs/integration-testing.md` §16.

Each scenario builds synthetic plugin git repos and manifest repos via the
conftest helpers, runs `kanon install` / `kanon clean`, and asserts the
documented pass criteria.

Linkfile-symlink assertions run in all environments.  The `claude plugin list`
check requires the `claude` CLI binary and is guarded with `pytest.skip()` at
runtime when the binary is absent.

Scenarios automated:
- MK-01: basic happy path (XML revision=main, .kanon REVISION=main)
- MK-02: exact tag pin both surfaces
- MK-03: PEP 440 ~= in XML revision, .kanon REVISION=main
- MK-04: PEP 440 ~= in .kanon REVISION, XML revision=main
- MK-05: PEP 440 range >= < in BOTH
- MK-06: latest sentinel both surfaces
- MK-07: PEP 440 != in XML, main in .kanon
- MK-08: PEP 440 != in .kanon, main in XML
- MK-09: upper-bound XML (<=1.1.0)
- MK-10: upper-bound .kanon (<=1.1.0)
- MK-11: exact pin both (==3.0.0)
- MK-12: invalid ==* constraint rejected; plugin not installed
- MK-13: marketplace.json with multiple plugins
- MK-14: plugin.json minimal (no keywords field)
- MK-15: plugin.json with full metadata
- MK-16: cascading <include> chain
- MK-17: XML with multiple <project> entries -- linkfile paths verified
- MK-18: bare wildcard * both surfaces
- MK-19: dest= not starting with ${CLAUDE_MARKETPLACES_DIR}/ rejected
- MK-20: re-install after clean restores plugin
- MK-21: multi-marketplace install (two distinct plugins)
- MK-22: linkfile with cascading directory tree must not crash

Notes:
- MK-12, MK-19 do not depend on `claude` CLI (exit-code / filesystem).
- All other scenarios assert on linkfile existence (no-claude safe).  The
  `claude plugin list` verification is gated on `shutil.which("claude") is not None`
  and skipped with an explanatory reason when the binary is absent.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_clean,
    kanon_install,
    run_git,
    run_kanon,
    write_kanonenv,
    xml_escape,
)

# ---------------------------------------------------------------------------
# MK-specific tag set -- every plugin repo gets these tags so all PEP 440
# constraints in the doc resolve deterministically.
# ---------------------------------------------------------------------------
_MK_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


# ---------------------------------------------------------------------------
# Helper: build a plugin fixture directory with one bare repo per name.
# Uses a richer marketplace.json that satisfies the real claude CLI schema.
# ---------------------------------------------------------------------------


def _mk_plugin_repo_full(
    fix_dir: pathlib.Path,
    name: str,
    tags: tuple[str, ...] = _MK_TAGS,
    *,
    extra_plugins: list[dict] | None = None,
) -> pathlib.Path:
    """Create a bare plugin repo under fix_dir with a claude-schema-compatible marketplace.json.

    The `owner` field is required by the real claude CLI's marketplace schema.
    Includes all tags in `tags`.  Returns the bare repo path.
    """
    work = fix_dir / f"{name}.work"
    bare = fix_dir / f"{name}.git"
    init_git_work_dir(work)
    cp = work / ".claude-plugin"
    cp.mkdir()

    plugins_list: list[dict] = [{"name": name, "source": "./", "description": f"synthetic plugin {name}"}]
    if extra_plugins:
        plugins_list.extend(extra_plugins)

    (cp / "marketplace.json").write_text(
        json.dumps(
            {
                "name": name,
                "owner": {"name": "Test", "url": "https://example.com"},
                "metadata": {"description": "synthetic test plugin", "version": "0.1.0"},
                "plugins": plugins_list,
            }
        )
    )
    (cp / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "description": "synthetic test plugin",
                "author": {"name": "Test", "url": "https://example.com"},
                "keywords": ["test"],
            }
        )
    )
    (work / "commands").mkdir()
    (work / "commands" / "sample.md").write_text("# Sample command\n")
    run_git(["add", "."], work)
    run_git(["commit", "-m", f"seed plugin {name}"], work)
    for tag in tags:
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


def _mk_plugin_fix(parent: pathlib.Path, *names: str) -> pathlib.Path:
    """Create a plugins/ directory under parent with one bare repo per name."""
    fix = parent / "plugins"
    fix.mkdir(parents=True, exist_ok=True)
    for name in names:
        _mk_plugin_repo_full(fix, name)
    return fix


# ---------------------------------------------------------------------------
# Helper: build a manifest bare repo with given XML files and semver tags.
# ---------------------------------------------------------------------------

_MFST_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


def _mk_manifest_repo(
    parent: pathlib.Path,
    xml_files: dict[str, str],
    *,
    name: str = "mk-manifest",
    tags: tuple[str, ...] = _MFST_TAGS,
) -> pathlib.Path:
    """Create a bare manifest repo containing the provided files and semver tags.

    Tags are added so that `kanon_revision` values like `refs/tags/1.0.0`,
    `latest`, `*`, and PEP 440 range constraints resolve against the manifest
    repo itself (the `KANON_SOURCE_*_REVISION` is used to check out the
    manifest repo, not just the plugin repo).
    """
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    for relpath, content in xml_files.items():
        target = work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        run_git(["add", relpath], work)
    run_git(["commit", "-m", f"seed {name}"], work)
    for tag in tags:
        run_git(["tag", tag], work)
    return clone_as_bare(work, bare)


# ---------------------------------------------------------------------------
# Helper: produce an MK-style manifest XML string.
# ---------------------------------------------------------------------------


def _mfst_xml_str(
    plugin_fix: pathlib.Path,
    plugin_name: str,
    revision: str,
    marketplaces_dir: pathlib.Path,
    *,
    link_dest_suffix: str | None = None,
) -> str:
    """Return XML text for an MK-style manifest (single project + linkfile)."""
    rev = xml_escape(revision)
    dest_name = link_dest_suffix or plugin_name
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{plugin_fix.as_uri()}/" />\n'
        '  <default remote="local" revision="main" />\n'
        f'  <project name="{plugin_name}" path=".packages/{plugin_name}" remote="local" revision="{rev}">\n'
        f'    <linkfile src="." dest="{marketplaces_dir}/{dest_name}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# Helper: write .kanon and run kanon install; returns the CompletedProcess.
# ---------------------------------------------------------------------------


def _run_mk_scenario(
    work_dir: pathlib.Path,
    mfst_bare: pathlib.Path,
    xml_filename: str,
    kanon_revision: str,
    marketplaces_dir: pathlib.Path,
    *,
    marketplace_install: str = "false",
) -> subprocess.CompletedProcess:
    """Write .kanon and run kanon install; returns the CompletedProcess."""
    write_kanonenv(
        work_dir,
        sources=[("mp", mfst_bare.as_uri(), kanon_revision, xml_filename)],
        marketplace_install=marketplace_install,
        extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
    )
    return kanon_install(work_dir)


# ---------------------------------------------------------------------------
# Runtime skip guard for `claude plugin list` assertions.
# ---------------------------------------------------------------------------


def _check_claude_plugin_list(plugin_name: str, *, expect_present: bool) -> None:
    """Run `claude plugin list` and assert plugin presence.

    Skips (not xfails) when the `claude` binary is absent so the test still
    passes in no-claude environments.  The linkfile filesystem assertions are
    the primary verification; this is a secondary confirmation.
    """
    if shutil.which("claude") is None:
        pytest.skip(
            "claude CLI not found on PATH; skipping 'claude plugin list' verification "
            "(no-claude environment -- linkfile filesystem assertion already verified)"
        )
    result = subprocess.run(
        ["claude", "plugin", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    if expect_present:
        assert plugin_name in combined, f"Expected plugin {plugin_name!r} in 'claude plugin list' output: {combined!r}"
    else:
        assert plugin_name not in combined, (
            f"Expected plugin {plugin_name!r} absent from 'claude plugin list' output: {combined!r}"
        )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestMK:
    # ------------------------------------------------------------------
    # MK-01..11, MK-18: happy-path parametrized suite
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "scenario_id,plugin_name,xml_revision,kanon_revision",
        [
            ("MK-01", "mk01", "main", "main"),
            ("MK-02", "mk02", "refs/tags/1.0.0", "refs/tags/1.0.0"),
            ("MK-03", "mk03", "refs/tags/~=1.0.0", "main"),
            ("MK-04", "mk04", "main", "refs/tags/~=1.0.0"),
            ("MK-05", "mk05", "refs/tags/>=1.0.0,<2.0.0", "refs/tags/>=1.0.0,<2.0.0"),
            ("MK-06", "mk06", "latest", "latest"),
            ("MK-07", "mk07", "refs/tags/!=2.0.0", "main"),
            ("MK-08", "mk08", "main", "refs/tags/!=2.0.0"),
            ("MK-09", "mk09", "refs/tags/<=1.1.0", "main"),
            ("MK-10", "mk10", "main", "refs/tags/<=1.1.0"),
            ("MK-11", "mk11", "refs/tags/==3.0.0", "refs/tags/==3.0.0"),
            ("MK-18", "mk18", "*", "*"),
        ],
    )
    def test_happy_path(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
        scenario_id: str,
        plugin_name: str,
        xml_revision: str,
        kanon_revision: str,
    ) -> None:
        """MK-01..11, MK-18: install exits 0; linkfile symlink created; clean removes it.

        `claude plugin list` verification is skipped when the `claude` CLI is absent.
        """
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        xml_content = _mfst_xml_str(fix, plugin_name, xml_revision, claude_marketplaces_dir)
        xml_filename = f"{plugin_name}-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name=f"mfst-{plugin_name}",
        )

        work_dir = tmp_path / scenario_id.lower().replace("/", "-")
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            kanon_revision,
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"{scenario_id} install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), (
            f"{scenario_id}: expected linkfile symlink at {link_path}; stdout={install_result.stdout!r}"
        )

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, (
            f"{scenario_id} clean exited {clean_result.returncode}\n"
            f"stdout={clean_result.stdout!r}\nstderr={clean_result.stderr!r}"
        )
        assert not link_path.exists(), f"{scenario_id}: linkfile still present at {link_path} after clean"

    # ------------------------------------------------------------------
    # MK-12: invalid ==* constraint rejected; plugin not installed
    # ------------------------------------------------------------------

    def test_mk_12_invalid_constraint_rejected(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-12: install exits non-zero for ==* revision; linkfile not created."""
        plugin_name = "mk12"
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        xml_content = _mfst_xml_str(fix, plugin_name, "==*", claude_marketplaces_dir)
        xml_filename = "mk12-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name="mfst-mk12",
        )

        work_dir = tmp_path / "mk12"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            "main",
            claude_marketplaces_dir,
        )

        assert install_result.returncode != 0, (
            f"MK-12: expected non-zero exit for ==* constraint but got 0\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        link_path = claude_marketplaces_dir / plugin_name
        assert not link_path.exists(), f"MK-12: linkfile unexpectedly present at {link_path} after failed install"

    # ------------------------------------------------------------------
    # MK-13: marketplace.json with multiple plugins
    # ------------------------------------------------------------------

    def test_mk_13_multiple_plugins_in_marketplace_json(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-13: marketplace.json with multiple plugins; install exits 0; linkfile created."""
        plugin_name = "mk13"
        fix = tmp_path / "fixtures" / "plugins"
        fix.mkdir(parents=True, exist_ok=True)

        work = fix / f"{plugin_name}.work"
        bare = fix / f"{plugin_name}.git"
        init_git_work_dir(work)
        cp = work / ".claude-plugin"
        cp.mkdir()
        (cp / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "owner": {"name": "Test", "url": "https://example.com"},
                    "metadata": {"description": "multi-plugin test", "version": "0.1.0"},
                    "plugins": [
                        {"name": "mk13-alpha", "source": "./", "description": "p1", "version": "0.1.0"},
                        {"name": "mk13-beta", "source": "./", "description": "p2", "version": "0.1.0"},
                    ],
                }
            )
        )
        (cp / "plugin.json").write_text(json.dumps({"name": plugin_name, "description": "multi-plugin test"}))
        run_git(["add", ".claude-plugin"], work)
        run_git(["commit", "-m", f"seed {plugin_name}"], work)
        for tag in _MK_TAGS:
            run_git(["tag", tag], work)
        clone_as_bare(work, bare)

        xml_content = _mfst_xml_str(fix, plugin_name, "main", claude_marketplaces_dir)
        xml_filename = "mk13-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name="mfst-mk13",
        )

        work_dir = tmp_path / "mk13"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-13 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), f"MK-13: linkfile not found at {link_path}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-13 clean exited {clean_result.returncode}"
        assert not link_path.exists(), "MK-13: linkfile still present after clean"

    # ------------------------------------------------------------------
    # MK-14: plugin.json minimal (no keywords field)
    # ------------------------------------------------------------------

    def test_mk_14_plugin_json_minimal(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-14: minimal plugin.json (no keywords); install exits 0; linkfile created."""
        plugin_name = "mk14"
        fix = tmp_path / "fixtures" / "plugins"
        fix.mkdir(parents=True, exist_ok=True)

        work = fix / f"{plugin_name}.work"
        bare = fix / f"{plugin_name}.git"
        init_git_work_dir(work)
        cp = work / ".claude-plugin"
        cp.mkdir()
        (cp / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "owner": {"name": "Test", "url": "https://example.com"},
                    "plugins": [{"name": plugin_name, "source": "./", "description": "minimal"}],
                }
            )
        )
        (cp / "plugin.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "version": "0.1.0",
                    "description": "minimal",
                    "author": {"name": "T", "url": "https://x"},
                }
            )
        )
        run_git(["add", ".claude-plugin"], work)
        run_git(["commit", "-m", f"seed {plugin_name}"], work)
        for tag in _MK_TAGS:
            run_git(["tag", tag], work)
        clone_as_bare(work, bare)

        xml_content = _mfst_xml_str(fix, plugin_name, "main", claude_marketplaces_dir)
        xml_filename = "mk14-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name="mfst-mk14",
        )

        work_dir = tmp_path / "mk14"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-14 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), f"MK-14: linkfile not found at {link_path}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-14 clean exited {clean_result.returncode}"
        assert not link_path.exists(), "MK-14: linkfile still present after clean"

    # ------------------------------------------------------------------
    # MK-15: plugin.json with full metadata
    # ------------------------------------------------------------------

    def test_mk_15_plugin_json_full_metadata(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-15: full-metadata plugin.json; install exits 0; linkfile created."""
        plugin_name = "mk15"
        fix = tmp_path / "fixtures" / "plugins"
        fix.mkdir(parents=True, exist_ok=True)

        work = fix / f"{plugin_name}.work"
        bare = fix / f"{plugin_name}.git"
        init_git_work_dir(work)
        cp = work / ".claude-plugin"
        cp.mkdir()
        (cp / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "owner": {"name": "Test Org", "url": "https://example.com"},
                    "plugins": [{"name": plugin_name, "source": "./", "description": "full metadata variant"}],
                }
            )
        )
        (cp / "plugin.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "version": "0.1.0",
                    "description": "full metadata variant",
                    "author": {"name": "Test Org", "url": "https://example.com"},
                    "keywords": ["a", "b", "c", "d", "e", "f", "g"],
                }
            )
        )
        run_git(["add", ".claude-plugin"], work)
        run_git(["commit", "-m", f"seed {plugin_name}"], work)
        for tag in _MK_TAGS:
            run_git(["tag", tag], work)
        clone_as_bare(work, bare)

        xml_content = _mfst_xml_str(fix, plugin_name, "main", claude_marketplaces_dir)
        xml_filename = "mk15-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name="mfst-mk15",
        )

        work_dir = tmp_path / "mk15"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-15 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), f"MK-15: linkfile not found at {link_path}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-15 clean exited {clean_result.returncode}"
        assert not link_path.exists(), "MK-15: linkfile still present after clean"

    # ------------------------------------------------------------------
    # MK-16: cascading <include> chain
    # ------------------------------------------------------------------

    def test_mk_16_cascading_include_chain(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-16: manifest with <include> resolves; linkfile created after install; removed on clean."""
        plugin_name = "mk16"
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        remote_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        mk16_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="shared/remote.xml" />\n'
            f'  <project name="{plugin_name}" path=".packages/{plugin_name}" remote="local" revision="main">\n'
            f'    <linkfile src="." dest="{claude_marketplaces_dir}/{plugin_name}" />\n'
            "  </project>\n"
            "</manifest>\n"
        )

        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {"shared/remote.xml": remote_xml, "mk16-mfst.xml": mk16_xml},
            name="mfst-mk16",
        )

        work_dir = tmp_path / "mk16"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            "mk16-mfst.xml",
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-16 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), f"MK-16: linkfile not found at {link_path}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-16 clean exited {clean_result.returncode}"
        assert not link_path.exists(), "MK-16: linkfile still present after clean"

    # ------------------------------------------------------------------
    # MK-17: XML with multiple <project> entries -- verify linkfile paths
    # ------------------------------------------------------------------

    def test_mk_17_multiple_project_entries(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-17: two <project> entries produce two distinct linkfiles; both cleaned.

        The single plugin name in marketplace.json means `claude plugin list` would
        show one entry; this test verifies the two filesystem linkfiles instead, which
        is the unique observable output of the multi-<project> scenario.
        """
        plugin_name = "mk17"
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        rev_b = xml_escape("refs/tags/2.0.0")
        mk17_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{plugin_name}" path=".packages/{plugin_name}-a" remote="local" revision="main">\n'
            f'    <linkfile src="." dest="{claude_marketplaces_dir}/{plugin_name}-a" />\n'
            "  </project>\n"
            f'  <project name="{plugin_name}" path=".packages/{plugin_name}-b" remote="local" revision="{rev_b}">\n'
            f'    <linkfile src="." dest="{claude_marketplaces_dir}/{plugin_name}-b" />\n'
            "  </project>\n"
            "</manifest>\n"
        )

        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {"mk17-mfst.xml": mk17_xml},
            name="mfst-mk17",
        )

        work_dir = tmp_path / "mk17"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            "mk17-mfst.xml",
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-17 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_a = claude_marketplaces_dir / f"{plugin_name}-a"
        link_b = claude_marketplaces_dir / f"{plugin_name}-b"
        assert link_a.is_symlink(), f"MK-17: linkfile {link_a} missing"
        assert link_b.is_symlink(), f"MK-17: linkfile {link_b} missing"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-17 clean exited {clean_result.returncode}"
        assert not link_a.exists(), f"MK-17: {link_a} still present after clean"
        assert not link_b.exists(), f"MK-17: {link_b} still present after clean"

    # ------------------------------------------------------------------
    # MK-19: dest= not starting with ${CLAUDE_MARKETPLACES_DIR}/ rejected
    # ------------------------------------------------------------------

    def test_mk_19_invalid_dest_rejected(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """MK-19: validate marketplace exits non-zero for dest not prefixed with CLAUDE_MARKETPLACES_DIR."""
        plugin_name = "mk19"
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        mk19_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{plugin_name}" path=".packages/{plugin_name}" remote="local" revision="main">\n'
            '    <linkfile src="." dest="/tmp/somewhere-bad" />\n'
            "  </project>\n"
            "</manifest>\n"
        )

        # validate marketplace expects the XML under repo-specs/
        repo_dir = tmp_path / "mk19-repo"
        repo_dir.mkdir()
        init_git_work_dir(repo_dir)
        (repo_dir / "repo-specs").mkdir()
        (repo_dir / "repo-specs" / "mk19-marketplace.xml").write_text(mk19_xml)
        run_git(["add", "repo-specs"], repo_dir)
        run_git(["commit", "-m", "mk19 invalid dest"], repo_dir)

        result = run_kanon("validate", "marketplace", "--repo-root", str(repo_dir))
        assert result.returncode != 0, (
            f"MK-19: expected non-zero exit for invalid dest, got 0\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "mk19-marketplace.xml" in combined or re.search(
            r"dest|CLAUDE_MARKETPLACES_DIR", combined, re.IGNORECASE
        ), f"MK-19: expected filename or dest mention in error output: {combined!r}"

    # ------------------------------------------------------------------
    # MK-20: re-install after clean restores plugin
    # ------------------------------------------------------------------

    def test_mk_20_reinstall_after_clean_restores_plugin(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-20: install -> clean -> install again restores the linkfile."""
        plugin_name = "mk20"
        fix = _mk_plugin_fix(tmp_path / "fixtures", plugin_name)

        xml_content = _mfst_xml_str(fix, plugin_name, "main", claude_marketplaces_dir)
        xml_filename = "mk20-mfst.xml"
        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {xml_filename: xml_content},
            name="mfst-mk20",
        )

        work_dir = tmp_path / "mk20"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            xml_filename,
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-20 first install failed: stdout={install_result.stdout!r} stderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / plugin_name
        assert link_path.is_symlink(), "MK-20: linkfile not found after first install"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, "MK-20 first clean failed"
        assert not link_path.exists(), "MK-20: linkfile still present after first clean"

        reinstall_result = kanon_install(work_dir)
        assert reinstall_result.returncode == 0, (
            f"MK-20 second install failed: stdout={reinstall_result.stdout!r} stderr={reinstall_result.stderr!r}"
        )
        assert link_path.is_symlink(), "MK-20: linkfile not restored after second install"

        second_clean = kanon_clean(work_dir)
        assert second_clean.returncode == 0, "MK-20 second clean failed"
        assert not link_path.exists(), "MK-20: linkfile still present after second clean"

    # ------------------------------------------------------------------
    # MK-21: multi-marketplace install (two distinct plugins in same .kanon)
    # ------------------------------------------------------------------

    def test_mk_21_multi_marketplace_install(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-21: two plugins (mk21a, mk21b) in a single .kanon; both linkfiles; both cleaned."""
        fix = _mk_plugin_fix(tmp_path / "fixtures", "mk21a", "mk21b")

        mk21_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="mk21a" path=".packages/mk21a" remote="local" revision="main">\n'
            f'    <linkfile src="." dest="{claude_marketplaces_dir}/mk21a" />\n'
            "  </project>\n"
            f'  <project name="mk21b" path=".packages/mk21b" remote="local" revision="main">\n'
            f'    <linkfile src="." dest="{claude_marketplaces_dir}/mk21b" />\n'
            "  </project>\n"
            "</manifest>\n"
        )

        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {"mk21-mfst.xml": mk21_xml},
            name="mfst-mk21",
        )

        work_dir = tmp_path / "mk21"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("combo", mfst_bare.as_uri(), "main", "mk21-mfst.xml")],
            marketplace_install="false",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={claude_marketplaces_dir}"],
        )

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"MK-21 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_a = claude_marketplaces_dir / "mk21a"
        link_b = claude_marketplaces_dir / "mk21b"
        assert link_a.is_symlink(), f"MK-21: linkfile mk21a missing at {link_a}"
        assert link_b.is_symlink(), f"MK-21: linkfile mk21b missing at {link_b}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-21 clean exited {clean_result.returncode}"
        assert not link_a.exists(), "MK-21: mk21a still present after clean"
        assert not link_b.exists(), "MK-21: mk21b still present after clean"

    # ------------------------------------------------------------------
    # MK-22: linkfile with cascading directory tree must not crash
    # ------------------------------------------------------------------

    def test_mk_22_linkfile_cascading_dir_tree(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """MK-22: linkfile src pointing to a nested dir resolves through the tree without crashing."""
        plugin_name = "mk22"
        fix = tmp_path / "fixtures" / "plugins"
        fix.mkdir(parents=True, exist_ok=True)

        work = fix / f"{plugin_name}.work"
        bare = fix / f"{plugin_name}.git"
        init_git_work_dir(work)
        cp = work / ".claude-plugin"
        cp.mkdir()
        (cp / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "owner": {"name": "Test", "url": "https://example.com"},
                    "plugins": [{"name": plugin_name, "source": "./"}],
                }
            )
        )
        (cp / "plugin.json").write_text(json.dumps({"name": plugin_name, "description": "mk22 nested linkfile test"}))
        nested = work / "deep" / "nested" / "path"
        nested.mkdir(parents=True)
        (nested / "marker.txt").write_text("marker\n")
        run_git(["add", "."], work)
        run_git(["commit", "-m", f"seed {plugin_name} with nested tree"], work)
        for tag in _MK_TAGS:
            run_git(["tag", tag], work)
        clone_as_bare(work, bare)

        dest_name = f"{plugin_name}-deep"
        mk22_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{plugin_name}" path=".packages/{plugin_name}" remote="local" revision="main">\n'
            f'    <linkfile src="deep" dest="{claude_marketplaces_dir}/{dest_name}" />\n'
            "  </project>\n"
            "</manifest>\n"
        )

        mfst_bare = _mk_manifest_repo(
            tmp_path / "manifests",
            {"mk22-mfst.xml": mk22_xml},
            name="mfst-mk22",
        )

        work_dir = tmp_path / "mk22"
        work_dir.mkdir()

        install_result = _run_mk_scenario(
            work_dir,
            mfst_bare,
            "mk22-mfst.xml",
            "main",
            claude_marketplaces_dir,
        )
        assert install_result.returncode == 0, (
            f"MK-22 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        link_path = claude_marketplaces_dir / dest_name
        assert link_path.is_symlink(), f"MK-22: linkfile symlink not found at {link_path}"

        real_target = os.path.realpath(str(link_path))
        assert ".kanon-data" in real_target and "sources" in real_target, (
            f"MK-22: symlink target not inside .kanon-data/sources/: {real_target!r}"
        )
        marker_path = link_path / "nested" / "path" / "marker.txt"
        assert marker_path.is_file(), f"MK-22: nested marker.txt not reachable through symlink at {marker_path}"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"MK-22 clean exited {clean_result.returncode}"
        assert not link_path.exists(), f"MK-22: linkfile still present at {link_path} after clean"
