"""A forced re-add refreshes delivered content, not just the catalog's lock SHA."""

from pathlib import Path

import pytest

from kanon_cli.core.install import compute_project_address, source_workspace_dir
from kanon_cli.core.lockfile import read_lockfile
from tests.scenarios.conftest import init_git_work_dir, run_git, run_kanon
from tests.scenarios.test_content_pins import _make_content_repo, _advance_main


@pytest.mark.scenario
@pytest.mark.parametrize("move_catalog", [False, True])
def test_force_readd_refreshes_content_and_preserves_other_sources(tmp_path: Path, move_catalog: bool) -> None:
    """Version bumps and catalog moves deliver new bytes while unrelated pins stay frozen."""
    tmp_path = tmp_path.resolve()
    content, bare_content, first_sha = _make_content_repo(tmp_path, "kit")
    second_sha = _advance_main(content, bare_content)
    catalog = tmp_path / "catalog"
    init_git_work_dir(catalog)
    specs = catalog / "repo-specs"
    specs.mkdir()
    for version, sha in [("1.0.0", first_sha), ("2.0.0", second_sha)]:
        (specs / "kit.xml").write_text(
            "<manifest><catalog-metadata><name>kit</name><display-name>Kit</display-name>"
            "<description>Upgrade fixture</description><version>" + version + "</version>"
            "<type>library</type></catalog-metadata>"
            '<remote name="local" fetch="' + tmp_path.as_uri() + '/"/>'
            '<default remote="local" revision="main"/>'
            '<project name="kit.git" path=".packages/kit" revision="' + sha + '"/>'
            "</manifest>",
            encoding="utf-8",
        )
        (specs / "other.xml").write_text(
            (specs / "kit.xml")
            .read_text(encoding="utf-8")
            .replace("<name>kit</name>", "<name>other</name>")
            .replace('path=".packages/kit"', 'path=".packages/other"')
            .replace(sha, first_sha),
            encoding="utf-8",
        )
        run_git(["add", "repo-specs/kit.xml", "repo-specs/other.xml"], catalog)
        run_git(["commit", "-m", version], catalog)
        run_git(["tag", version], catalog)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    home = tmp_path / "home"
    env = {"KANON_HOME": str(home), "KANON_ALLOW_INSECURE_REMOTES": "1"}

    def cli(*args: str) -> None:
        result = run_kanon(*args, cwd=consumer, extra_env=env)
        assert result.returncode == 0, result.stdout + result.stderr

    cli("add", "kit@1.0.0", "--catalog-source", catalog.as_uri() + "@main")
    cli("add", "other@1.0.0", "--catalog-source", catalog.as_uri() + "@main")
    cli("install")
    address = compute_project_address(consumer / ".kanon")
    checkout = source_workspace_dir(home / "store", address, "kit") / ".packages" / "kit" / "file.txt"
    assert checkout.read_text(encoding="utf-8") == "v1"
    original_lock = read_lockfile(consumer / ".kanon.lock")
    assert original_lock.sources[0].content_pins[0].resolved_sha == first_sha

    destination = catalog
    xml_path = "repo-specs/kit.xml"
    if move_catalog:
        destination = tmp_path / "moved-catalog"
        run_git(["clone", str(catalog), str(destination)], tmp_path)
        run_git(["config", "user.name", "Upgrade Fixture"], destination)
        run_git(["config", "user.email", "fixture@example.com"], destination)
        xml_path = "repo-specs/renamed.xml"
        run_git(["mv", "repo-specs/kit.xml", xml_path], destination)
        run_git(["commit", "-m", "Move manifest"], destination)
        requested = "main"
    else:
        requested = "2.0.0"

    cli("add", "kit@" + requested, "--catalog-source", destination.as_uri() + "@main", "--force")
    updated = read_lockfile(consumer / ".kanon.lock").sources[0]
    assert updated.path == xml_path
    assert updated.content_pins == []
    assert updated.projects == []
    assert read_lockfile(consumer / ".kanon.lock").sources[1] == original_lock.sources[1]
    cli("install")
    assert checkout.read_text(encoding="utf-8") == "v2"
    locked = read_lockfile(consumer / ".kanon.lock").sources[0]
    assert locked.content_pins[0].resolved_sha == second_sha
    assert read_lockfile(consumer / ".kanon.lock").sources[1] == original_lock.sources[1]
    cli("install")
    assert checkout.read_text(encoding="utf-8") == "v2"
