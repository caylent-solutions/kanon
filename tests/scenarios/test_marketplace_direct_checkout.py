"""Scenario tests: marketplace registration for direct-checkout catalog entries (BUG-3).

Documents and locks the fix from spec S.0 / E51-F3:

  A ``kanon install`` with ``KANON_MARKETPLACE_INSTALL=true`` MUST register a
  claude marketplace for a direct ``path=`` checkout entry whose manifest carries
  a ``.claude-plugin/marketplace.json`` with NO ``<linkfile>`` elements.

Prior to the fix, ``_process_manifest_linkfiles`` only processed ``<linkfile>``
elements.  A project that carries ``.claude-plugin/marketplace.json`` but has NO
``<linkfile>`` fell through and registered nothing, leaving the marketplace
absent from the ``CLAUDE_MARKETPLACES_DIR``.

After the fix, ``register_direct_checkout_marketplaces`` (in
``src/kanon_cli/core/marketplace.py``) is called alongside
``_process_manifest_linkfiles`` and creates a symlink in ``CLAUDE_MARKETPLACES_DIR``
pointing at the checked-out project directory so ``install_marketplace_plugins``
can register it.

These are subprocess (operator-path) tests: each test invokes real ``kanon``
subprocesses against on-disk fixture git repos.  The claude CLI mock pattern
from ``tests/integration/test_marketplace_lifecycle.py`` is NOT needed here
because we test at the filesystem level: we assert that the marketplace entry
appears in ``CLAUDE_MARKETPLACES_DIR`` after install.  The ``claude`` binary is
not required by these tests (no ``claude plugin marketplace list`` call).

AC-TEST-001: test_marketplace_registered_for_direct_checkout_entry added here.
AC-TEST-002: RED->GREEN transition recorded in the TDD Cycle Log.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_install,
    run_git,
    write_kanonenv,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_direct_checkout_plugin_repo(
    parent: pathlib.Path,
    name: str,
    *,
    plugin_names: list[str] | None = None,
) -> pathlib.Path:
    """Create a bare git repo for a direct-checkout marketplace entry.

    The repo carries a ``.claude-plugin/marketplace.json`` (with the given
    ``plugin_names`` in the ``plugins`` array) but NO ``<linkfile>`` in the
    manifest XML.  Returns the bare repo path.

    Args:
        parent: Directory under which to create the work and bare repos.
        name: Repository and marketplace name.
        plugin_names: Names of plugins to declare in marketplace.json.
            Defaults to ``[name]``.

    Returns:
        Resolved path to the bare repo.
    """
    plugins = plugin_names if plugin_names is not None else [name]
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    cp = work / ".claude-plugin"
    cp.mkdir()
    manifest_data = {
        "name": name,
        "owner": {"name": "Test", "url": "https://example.com"},
        "metadata": {"description": "synthetic direct-checkout marketplace", "version": "0.1.0"},
        "plugins": [{"name": p, "source": "./", "description": f"plugin {p}"} for p in plugins],
    }
    (cp / "marketplace.json").write_text(json.dumps(manifest_data))
    (cp / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "description": "synthetic direct-checkout marketplace",
                "author": {"name": "Test", "url": "https://example.com"},
            }
        )
    )
    (work / "commands").mkdir()
    (work / "commands" / "sample.md").write_text("# Sample command\n")
    run_git(["add", "."], work)
    run_git(["commit", "-m", f"seed direct-checkout plugin {name}"], work)
    run_git(["tag", "1.0.0"], work)
    return clone_as_bare(work, bare)


def _make_manifest_repo_no_linkfile(
    parent: pathlib.Path,
    plugin_bare: pathlib.Path,
    plugin_name: str,
    *,
    manifest_filename: str,
) -> pathlib.Path:
    """Create a bare manifest repo whose XML has NO ``<linkfile>`` element.

    The project is a direct ``path=`` checkout entry: the XML declares a
    ``<project>`` that checks out ``plugin_name`` into ``.packages/<plugin_name>``
    with no ``<linkfile>`` child.

    Args:
        parent: Directory under which to create the work and bare repos.
        plugin_bare: Path to the bare plugin git repo.
        plugin_name: Name of the plugin project.
        manifest_filename: Filename for the manifest XML (e.g. ``foo.xml``).

    Returns:
        Resolved path to the bare manifest repo.
    """
    work = parent / "mfst-direct.work"
    bare = parent / "mfst-direct.git"
    init_git_work_dir(work)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{plugin_bare.parent.as_uri()}/" />\n'
        '  <default remote="local" revision="main" />\n'
        f'  <project name="{plugin_bare.name}" path=".packages/{plugin_name}" remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    (work / manifest_filename).write_text(xml)
    run_git(["add", manifest_filename], work)
    run_git(["commit", "-m", f"seed manifest for {plugin_name} (no linkfile)"], work)
    run_git(["tag", "1.0.0"], work)
    return clone_as_bare(work, bare)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestMarketplaceDirectCheckout:
    def test_marketplace_registered_for_direct_checkout_entry(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """BUG-3 regression: a direct path= checkout entry with .claude-plugin/marketplace.json
        and NO <linkfile> MUST produce a marketplace entry in CLAUDE_MARKETPLACES_DIR.

        Build a synthetic catalog where the manifest XML for ``builders-plugins`` has
        a direct ``path=`` checkout (no ``<linkfile>``), run ``kanon install`` with
        ``KANON_MARKETPLACE_INSTALL=true``, and assert the marketplace directory entry
        appears in ``CLAUDE_MARKETPLACES_DIR``.

        Today (before the fix): nothing is created in CLAUDE_MARKETPLACES_DIR.
        After the fix: a symlink pointing at the checked-out project root appears.
        """
        fix = tmp_path / "fixtures"
        fix.mkdir()

        plugin_name = "builders-plugins"
        plugin_bare = _make_direct_checkout_plugin_repo(fix, plugin_name)

        manifest_filename = f"{plugin_name}.xml"
        mfst_bare = _make_manifest_repo_no_linkfile(
            fix,
            plugin_bare,
            plugin_name,
            manifest_filename=manifest_filename,
        )

        marketplaces_dir = tmp_path / "claude-marketplaces"
        marketplaces_dir.mkdir()

        work_dir = tmp_path / "workspace"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("bp", mfst_bare.as_uri(), "main", manifest_filename)],
            marketplace_install="true",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"kanon install failed (exit {result.returncode})\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

        # The marketplace entry must exist in CLAUDE_MARKETPLACES_DIR.
        # The entry name is derived from the marketplace.json "name" field.
        marketplace_entry = marketplaces_dir / plugin_name
        assert marketplace_entry.exists(), (
            f"Expected marketplace entry at {marketplace_entry} after install.\n"
            f"CLAUDE_MARKETPLACES_DIR contents: {list(marketplaces_dir.iterdir())}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # The entry must point at a directory containing .claude-plugin/marketplace.json.
        manifest_json = marketplace_entry / ".claude-plugin" / "marketplace.json"
        assert manifest_json.is_file(), (
            f"marketplace.json not found at {manifest_json} -- entry does not point at a marketplace root"
        )

    def test_no_marketplace_entry_without_flag(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Without KANON_MARKETPLACE_INSTALL=true, no marketplace entry is created.

        Edge case from AC-FUNC-003: default false / explicit false registers nothing.
        """
        fix = tmp_path / "fixtures"
        fix.mkdir()

        plugin_name = "bp-no-flag"
        plugin_bare = _make_direct_checkout_plugin_repo(fix, plugin_name)

        manifest_filename = f"{plugin_name}.xml"
        mfst_bare = _make_manifest_repo_no_linkfile(
            fix,
            plugin_bare,
            plugin_name,
            manifest_filename=manifest_filename,
        )

        marketplaces_dir = tmp_path / "claude-marketplaces"
        marketplaces_dir.mkdir()

        work_dir = tmp_path / "workspace"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("bp", mfst_bare.as_uri(), "main", manifest_filename)],
            marketplace_install="false",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"kanon install failed (exit {result.returncode})\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Marketplace dir should be empty -- no entries registered.
        mp_entries = list(marketplaces_dir.iterdir())
        assert mp_entries == [], f"Expected empty CLAUDE_MARKETPLACES_DIR but found: {mp_entries}"

    def test_entry_with_neither_linkfile_nor_marketplace_json_is_silent_noop(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An entry with neither a linkfile nor a .claude-plugin/marketplace.json
        registers nothing and is NOT an error (AC-FUNC-003).
        """
        fix = tmp_path / "fixtures"
        fix.mkdir()

        # A plain repo with no .claude-plugin/ at all.
        plain_name = "plain-package"
        plain_work = fix / f"{plain_name}.work"
        plain_bare = fix / f"{plain_name}.git"
        init_git_work_dir(plain_work)
        (plain_work / "README.md").write_text("# plain package\n")
        run_git(["add", "README.md"], plain_work)
        run_git(["commit", "-m", f"seed {plain_name}"], plain_work)
        run_git(["tag", "1.0.0"], plain_work)
        clone_as_bare(plain_work, plain_bare)

        mfst_work = fix / "mfst-plain.work"
        mfst_bare = fix / "mfst-plain.git"
        init_git_work_dir(mfst_work)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{fix.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            f'  <project name="{plain_bare.name}" path=".packages/{plain_name}" remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        (mfst_work / "plain.xml").write_text(xml)
        run_git(["add", "plain.xml"], mfst_work)
        run_git(["commit", "-m", "seed manifest for plain package"], mfst_work)
        clone_as_bare(mfst_work, mfst_bare)

        marketplaces_dir = tmp_path / "claude-marketplaces"
        marketplaces_dir.mkdir()

        work_dir = tmp_path / "workspace"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("plain", mfst_bare.as_uri(), "main", "plain.xml")],
            marketplace_install="true",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"kanon install should exit 0 for a plain (no marketplace) entry; "
            f"got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # No entries should be created in CLAUDE_MARKETPLACES_DIR.
        mp_entries = list(marketplaces_dir.iterdir())
        assert mp_entries == [], f"Expected empty CLAUDE_MARKETPLACES_DIR for plain entry but found: {mp_entries}"

    @pytest.mark.parametrize(
        "scenario_id,plugin_name,revision",
        [
            ("DC-01", "dc-01-plugin", "main"),
            ("DC-02", "dc-02-plugin", "refs/tags/1.0.0"),
        ],
    )
    def test_direct_checkout_registers_parametrized(
        self,
        tmp_path: pathlib.Path,
        scenario_id: str,
        plugin_name: str,
        revision: str,
    ) -> None:
        """Parametrized: direct-checkout entries register under various revision specs."""
        fix = tmp_path / "fixtures"
        fix.mkdir()

        plugin_bare = _make_direct_checkout_plugin_repo(fix, plugin_name)

        manifest_filename = f"{plugin_name}.xml"
        mfst_bare = _make_manifest_repo_no_linkfile(
            fix,
            plugin_bare,
            plugin_name,
            manifest_filename=manifest_filename,
        )

        marketplaces_dir = tmp_path / "claude-marketplaces"
        marketplaces_dir.mkdir()

        work_dir = tmp_path / scenario_id.lower()
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("src", mfst_bare.as_uri(), revision, manifest_filename)],
            marketplace_install="true",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"{scenario_id}: kanon install failed (exit {result.returncode})\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

        marketplace_entry = marketplaces_dir / plugin_name
        assert marketplace_entry.exists(), (
            f"{scenario_id}: expected marketplace entry at {marketplace_entry}.\n"
            f"CLAUDE_MARKETPLACES_DIR contents: {list(marketplaces_dir.iterdir())}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        manifest_json = marketplace_entry / ".claude-plugin" / "marketplace.json"
        assert manifest_json.is_file(), f"{scenario_id}: marketplace.json not found at {manifest_json}"
