"""Regression coverage for adding dependencies to an already installed project."""

import pathlib
from dataclasses import replace

import pytest

from kanon_cli.core.lockfile import read_lockfile, write_lockfile
from tests.scenarios.conftest import make_bare_repo_with_tags, make_plain_repo, run_git, run_kanon


def _setup(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str], str]:
    project = tmp_path / "project"
    project.mkdir()
    files = {}
    for name in ("alpha", "beta"):
        make_bare_repo_with_tags(tmp_path, name, ["1.0.0"])
        files[f"repo-specs/{name}.xml"] = (
            "<manifest><catalog-metadata>"
            f"<name>{name}</name><display-name>{name}</display-name>"
            "<description>Install cycle fixture</description><version>1.0.0</version>"
            "<type>library</type></catalog-metadata>"
            f'<remote name="local" fetch="{tmp_path.as_uri()}/"/>'
            '<default remote="local" revision="main"/>'
            f'<project name="{name}.git" path=".packages/{name}"/>'
            "</manifest>"
        )
    catalog = make_plain_repo(tmp_path, "catalog", files).as_uri() + "@main"
    env = {"KANON_HOME": str(tmp_path / "home"), "KANON_ALLOW_INSECURE_REMOTES": "1"}
    for args in (("add", "alpha@main", "--catalog-source", catalog), ("install",)):
        result = run_kanon(*args, cwd=project, extra_env=env)
        assert result.returncode == 0, result.stderr
    return project, env, catalog


@pytest.mark.scenario
def test_add_install_preserves_existing_pins_and_delivered_bytes(tmp_path: pathlib.Path) -> None:
    project, env, catalog = _setup(tmp_path)
    lock_path = project / ".kanon.lock"
    original = read_lockfile(lock_path).sources[0]
    content = tmp_path / "alpha.work"
    (content / "version.txt").write_text("upstream changed")
    run_git(["add", "version.txt"], content)
    run_git(["commit", "-m", "advance alpha"], content)
    run_git(["push", str(tmp_path / "alpha.git"), "main"], content)
    catalog_work = tmp_path / "catalog.work"
    (catalog_work / "README.md").write_text("Catalog branch advanced after the first install")
    run_git(["add", "README.md"], catalog_work)
    run_git(["commit", "-m", "advance catalog"], catalog_work)
    run_git(["push", str(tmp_path / "catalog.git"), "main"], catalog_work)

    added = run_kanon("add", "beta@main", "--catalog-source", catalog, cwd=project, extra_env=env)
    assert added.returncode == 0, added.stderr
    lock_before = lock_path.read_bytes()
    strict = run_kanon("install", "--strict-drift", cwd=project, extra_env=env)
    assert strict.returncode != 0
    assert "branch drift" in strict.stderr.lower()
    assert lock_path.read_bytes() == lock_before
    installed = run_kanon("install", cwd=project, extra_env=env)
    assert installed.returncode == 0, installed.stderr
    sources = {source.alias: source for source in read_lockfile(lock_path).sources}
    assert set(sources) == {"alpha", "beta"}
    assert sources["alpha"] == original
    for name in sources:
        assert (project / ".packages" / name / "version.txt").read_text() == "1.0.0"
    lock_bytes = lock_path.read_bytes()
    replay = run_kanon("install", cwd=project, extra_env=env)
    assert replay.returncode == 0, replay.stderr
    assert lock_path.read_bytes() == lock_bytes


@pytest.mark.scenario
@pytest.mark.parametrize("change", ["strict", "url", "path", "ref", "failed-addition", "lock-ref"])
def test_addition_does_not_bypass_drift_or_rewrite_lock_on_failure(tmp_path: pathlib.Path, change: str) -> None:
    project, env, catalog = _setup(tmp_path)
    lock_path = project / ".kanon.lock"
    original = lock_path.read_bytes()
    added = run_kanon("add", "beta@main", "--catalog-source", catalog, cwd=project, extra_env=env)
    assert added.returncode == 0, added.stderr
    kanon = project / ".kanon"
    if change in {"url", "path", "ref"}:
        prefix = f"KANON_SOURCE_alpha_{change.upper()}="
        lines = [line + "-changed" if line.startswith(prefix) else line for line in kanon.read_text().splitlines()]
        kanon.write_text("\n".join(lines) + "\n")
    elif change == "failed-addition":
        kanon.write_text(kanon.read_text().replace("KANON_SOURCE_beta_REF=main", "KANON_SOURCE_beta_REF=missing"))
    elif change == "lock-ref":
        lockfile = read_lockfile(lock_path)
        lockfile.sources[0] = replace(lockfile.sources[0], ref_spec="altered")
        write_lockfile(lockfile, lock_path)
        original = lock_path.read_bytes()
    flags = ["--strict-lock"] if change == "strict" else []
    installed = run_kanon("install", *flags, cwd=project, extra_env=env)
    assert installed.returncode != 0
    assert "Traceback" not in installed.stderr
    assert lock_path.read_bytes() == original
