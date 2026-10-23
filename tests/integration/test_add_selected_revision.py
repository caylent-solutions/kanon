"""Resolve manifest coordinates and settings from the selected Git revision."""

import pathlib
import subprocess

import pytest

from tests.integration.test_add_core import (
    _MARKETPLACE_XML_TEMPLATE,
    _clone_as_bare,
    _git,
    _init_git_work_dir,
    _run_kanon,
)


def _write_entry(root: pathlib.Path, relative_path: str, name: str, variable: str, entry_type: str) -> None:
    """Write a catalog entry whose settings identify its revision."""
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = _MARKETPLACE_XML_TEMPLATE.format(name=name).replace("<type>plugin</type>", f"<type>{entry_type}</type>")
    manifest = manifest.replace("</manifest>", '<include name="vars.xml"/>\n</manifest>')
    destination.write_text(manifest, encoding="utf-8")
    (root / "vars.xml").write_text(
        f'<manifest><remote name="origin" fetch="${{{variable}}}/repositories"/>'
        '<default remote="origin" revision="main"/><project name="content" path="content"/></manifest>',
        encoding="utf-8",
    )


@pytest.fixture
def revision_catalog(tmp_path: pathlib.Path) -> dict[str, str | pathlib.Path]:
    """Publish an old release, a newer release branch, and moved main entries."""
    work = tmp_path / "catalog-work"
    work.mkdir()
    _init_git_work_dir(work)
    name = work.name
    old_path = f"repo-specs/old/{name}.xml"
    main_path = f"repo-specs/main/{name}.xml"
    release_path = f"repo-specs/release/{name}.xml"
    _write_entry(work, old_path, name, "OLD_SOURCE", "plugin")
    _git(["add", "."], work)
    _git(["commit", "-m", "Old release"], work)
    _git(["tag", "1.0.0"], work)
    _git(["checkout", "-b", "release"], work)
    (work / old_path).unlink()
    _write_entry(work, release_path, name, "RELEASE_SOURCE", "claude-marketplace")
    _git(["add", "-A"], work)
    _git(["commit", "-m", "Moved release entry"], work)
    _git(["tag", "2.0.0"], work)
    _git(["checkout", "main"], work)
    (work / old_path).unlink()
    _write_entry(work, main_path, name, "MAIN_SOURCE", "plugin")
    _write_entry(work, "repo-specs/main-only.xml", "main-only", "MAIN_SOURCE", "plugin")
    _git(["add", "-A"], work)
    _git(["commit", "-m", "Move main after old release"], work)
    bare = _clone_as_bare(work, tmp_path / "catalog.git")
    workspace = tmp_path / "consumer"
    workspace.mkdir()
    return {
        "bare": bare,
        "workspace": workspace,
        "name": name,
        "alias": name.replace("-", "_"),
        "old_path": old_path,
        "main_path": main_path,
        "release_path": release_path,
    }


def _add(catalog: dict[str, str | pathlib.Path], *entries: str) -> subprocess.CompletedProcess[str]:
    """Run the real CLI against the local catalog."""
    workspace = pathlib.Path(catalog["workspace"])
    return _run_kanon(
        [
            "add",
            *entries,
            "--catalog-source",
            f"{pathlib.Path(catalog['bare']).as_uri()}@main",
            "--kanon-file",
            str(workspace / ".kanon"),
        ],
        cwd=workspace,
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("spec", "path_key", "variable", "marketplace"),
    [("", "release_path", "RELEASE_SOURCE", True), ("@==1.0.0", "old_path", "OLD_SOURCE", False)],
)
def test_add_uses_selected_manifest_and_includes(
    revision_catalog: dict[str, str | pathlib.Path], spec: str, path_key: str, variable: str, marketplace: bool
) -> None:
    """Both a release ahead of main and a release before a move retain valid coordinates."""
    result = _add(revision_catalog, f"{revision_catalog['name']}{spec}")
    assert result.returncode == 0, result.stderr
    content = (pathlib.Path(revision_catalog["workspace"]) / ".kanon").read_text()
    prefix = f"KANON_SOURCE_{revision_catalog['alias']}"
    assert f"{prefix}_PATH={revision_catalog[path_key]}" in content
    assert f"{prefix}_{variable}=" in content
    assert f"{prefix}_MAIN_SOURCE=" not in content
    assert (f"{prefix}_MARKETPLACE=true" in content) is marketplace


@pytest.mark.integration
@pytest.mark.parametrize("existing", [False, True])
def test_missing_entry_at_selected_ref_leaves_all_outputs_unchanged(
    revision_catalog: dict[str, str | pathlib.Path], existing: bool
) -> None:
    """A later entry failing resolution cannot partially write the first entry or lock."""
    workspace = pathlib.Path(revision_catalog["workspace"])
    kanon_file = workspace / ".kanon"
    lock_file = workspace / ".kanon.lock"
    before = b"CUSTOM_VALUE=preserve-this\n"
    if existing:
        kanon_file.write_bytes(before)
        lock_file.write_bytes(before)
    result = _add(revision_catalog, str(revision_catalog["name"]), "main-only")
    assert result.returncode != 0
    assert "main-only" in result.stderr
    assert "refs/tags/2.0.0" in result.stderr
    for path in (kanon_file, lock_file):
        assert path.read_bytes() == before if existing else not path.exists()


@pytest.mark.integration
def test_multiple_entries_resolve_independent_revisions(revision_catalog: dict[str, str | pathlib.Path]) -> None:
    """Changing the temporary checkout never reuses a different entry's manifest data."""
    result = _add(revision_catalog, str(revision_catalog["name"]), "main-only@main")
    assert result.returncode == 0, result.stderr
    content = (pathlib.Path(revision_catalog["workspace"]) / ".kanon").read_text()
    assert f"KANON_SOURCE_{revision_catalog['alias']}_PATH={revision_catalog['release_path']}" in content
    assert "KANON_SOURCE_main_only_PATH=repo-specs/main-only.xml" in content
    assert "KANON_SOURCE_main_only_MAIN_SOURCE=" in content


@pytest.mark.integration
def test_unavailable_selected_ref_names_entry_and_preserves_config(
    revision_catalog: dict[str, str | pathlib.Path],
) -> None:
    """A failed Git fetch reports the selected coordinates and does not write configuration."""
    result = _add(revision_catalog, f"{revision_catalog['name']}@missing-branch")
    assert result.returncode != 0
    assert str(revision_catalog["name"]) in result.stderr
    assert "missing-branch" in result.stderr
    assert not (pathlib.Path(revision_catalog["workspace"]) / ".kanon").exists()
