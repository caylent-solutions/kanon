"""Portable linkfiles keep each consumer's content isolated in a shared home."""

from pathlib import Path
import os

import pytest

from tests.scenarios.conftest import init_git_work_dir, run_git, run_kanon
from tests.scenarios.test_content_pins import _make_content_repo, _advance_main


@pytest.mark.scenario
@pytest.mark.parametrize("cleaned_project", ["clone", "worktree"])
def test_linkfiles_survive_other_project_install_and_clean(tmp_path: Path, cleaned_project: str) -> None:
    """Real clone/worktree installs preserve different versions through reinstall and clean."""
    tmp_path = tmp_path.resolve()
    content, bare_content, first_sha = _make_content_repo(tmp_path, "kit")
    second_sha = _advance_main(content, bare_content)
    catalog = tmp_path / "catalog"
    init_git_work_dir(catalog)
    (catalog / "manifest.xml").write_text(
        '<manifest><remote name="local" fetch="' + tmp_path.as_uri() + '/"/>'
        '<default remote="local" revision="main"/>'
        '<project name="kit.git" path=".packages/kit" revision="${CONTENT_SHA}">'
        '<linkfile src="file.txt" dest="${CONSUMER_ROOT}/rules.txt"/>'
        "</project></manifest>",
        encoding="utf-8",
    )
    run_git(["add", "manifest.xml"], catalog)
    run_git(["commit", "-m", "Manifest fixture"], catalog)
    clone = tmp_path / "consumer"
    init_git_work_dir(clone)
    (clone / "README.md").write_text("Consumer fixture\n", encoding="utf-8")
    run_git(["add", "README.md"], clone)
    run_git(["commit", "-m", "Consumer fixture"], clone)
    worktree = clone / ".worktrees" / "nested" / "branch"
    run_git(["worktree", "add", "--detach", str(worktree), "HEAD"], clone)
    env = {"KANON_HOME": str(tmp_path / "home"), "KANON_ALLOW_INSECURE_REMOTES": "1"}
    for project, sha in [(clone, first_sha), (worktree, second_sha)]:
        (project / ".kanon").write_text(
            f"KANON_SOURCE_kit_NAME=kit\nKANON_SOURCE_kit_REF=main\n"
            f"KANON_SOURCE_kit_URL={catalog.as_uri()}\nKANON_SOURCE_kit_PATH=manifest.xml\n"
            f"KANON_SOURCE_kit_CONTENT_SHA={sha}\nKANON_SOURCE_kit_CONSUMER_ROOT={project}\n",
            encoding="utf-8",
        )
        result = run_kanon("install", cwd=project, extra_env=env)
        assert result.returncode == 0, result.stdout + result.stderr

    assert (clone / "rules.txt").read_text(encoding="utf-8") == "v1"
    assert (worktree / "rules.txt").read_text(encoding="utf-8") == "v2"
    assert os.readlink(clone / "rules.txt") == os.readlink(worktree / "rules.txt") == ".packages/kit/file.txt"

    reinstall = run_kanon("install", cwd=clone, extra_env=env)
    assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
    assert (worktree / "rules.txt").read_text(encoding="utf-8") == "v2"
    removed, survivor, expected = (clone, worktree, "v2") if cleaned_project == "clone" else (worktree, clone, "v1")
    result = run_kanon("clean", cwd=removed, extra_env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (removed / ".packages").is_symlink()
    assert (survivor / "rules.txt").read_text(encoding="utf-8") == expected
