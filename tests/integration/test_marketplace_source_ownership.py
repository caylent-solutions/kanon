"""Real repo sync keeps marketplace opt-in and ownership aligned."""

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from kanon_cli.commands.marketplace import run_disable, run_enable
from kanon_cli.core.install import install
from kanon_cli.core.lockfile import read_lockfile
from kanon_cli.core.marketplace import copied_marketplace_json_paths, read_marketplace_name
from kanon_cli.repo.main import RepoCommandError
from tests.scenarios.conftest import make_plain_repo, run_git


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Resolve actual commits from the local Git fixtures."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Check the real local repositories during lockfile replay."""
    yield


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delivery: str,
    *,
    shared_name: bool = False,
    shared_destination: bool = False,
    beta_delivery: str | None = None,
) -> tuple[Path, Path, list[tuple[str, str]]]:
    monkeypatch.setenv("KANON_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
    workspace = tmp_path / "consumer"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    marketplace_dir = tmp_path / "marketplaces"
    manifests = {}
    for name in ("alpha", "beta"):
        kind = beta_delivery if name == "beta" and beta_delivery is not None else delivery
        marketplace_name = "shared" if shared_name else name
        make_plain_repo(
            tmp_path,
            name,
            {
                ".claude-plugin/marketplace.json": json.dumps({"name": marketplace_name, "plugins": [{"name": name}]}),
                "README.md": name,
            },
        )
        destination = "same-destination" if shared_destination else f"entry-{name}"
        if kind == "root":
            action = f'<linkfile src="." dest="${{CLAUDE_MARKETPLACES_DIR}}/{destination}"/>'
        elif kind in ("json", "copy"):
            tag = "copyfile" if kind == "copy" else "linkfile"
            action = (
                f'<{tag} src=".claude-plugin/marketplace.json" '
                f'dest="${{CLAUDE_MARKETPLACES_DIR}}/{destination}/.claude-plugin/marketplace.json"/>'
            )
        else:
            action = ""
        manifests[f"{name}.xml"] = (
            f'<manifest><remote name="local" fetch="{tmp_path.as_uri()}/"/>'
            '<default remote="local" revision="main"/>'
            f'<project name="{name}.git" path=".packages/{name}">{action}</project></manifest>'
        )
    catalog = make_plain_repo(tmp_path, "catalog", manifests)
    kanon = workspace / ".kanon"
    kanon.write_text(
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"
        + "".join(
            f"KANON_SOURCE_{name}_URL={catalog.as_uri()}\n"
            f"KANON_SOURCE_{name}_REF=main\n"
            f"KANON_SOURCE_{name}_PATH={name}.xml\n"
            f"KANON_SOURCE_{name}_NAME={name}\n"
            f"KANON_SOURCE_{name}_MARKETPLACE=true\n"
            for name in ("alpha", "beta")
        )
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("kanon_cli.core.marketplace.locate_claude_binary", lambda: "claude-test")
    monkeypatch.setattr("kanon_cli.core.install.locate_claude_binary", lambda: "claude-test")

    def register(_claude: str, path: Path) -> bool:
        calls.append(("register", read_marketplace_name(path)))
        calls.append(("path", str(path)))
        return True

    monkeypatch.setattr("kanon_cli.core.marketplace.register_marketplace", register)
    monkeypatch.setattr(
        "kanon_cli.core.marketplace.install_plugin",
        lambda _claude, plugin, _marketplace: calls.append(("plugin", plugin)) or True,
    )
    monkeypatch.setattr(
        "kanon_cli.core.install.remove_marketplace",
        lambda _claude, marketplace: calls.append(("remove", marketplace)) or True,
    )
    return kanon, marketplace_dir, calls


def _disable(kanon: Path, name: str, *, absent: bool = False) -> None:
    setting = f"KANON_SOURCE_{name}_MARKETPLACE=true"
    kanon.write_text(kanon.read_text().replace(setting, "" if absent else setting.replace("true", "false")))


@pytest.mark.parametrize("delivery", ["root", "json", "copy", "direct"])
@pytest.mark.parametrize("disabled", ["alpha", "beta"])
def test_only_enabled_sources_register_and_all_sources_deliver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str, disabled: str
) -> None:
    kanon, marketplace_dir, calls = _setup(tmp_path, monkeypatch, delivery)
    _disable(kanon, disabled, absent=disabled == "alpha")
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    enabled = "beta" if disabled == "alpha" else "alpha"
    assert {name for action, name in calls if action == "register"} == {enabled}
    assert {name for action, name in calls if action == "plugin"} == {enabled}
    if delivery == "copy":
        assert ("path", str(marketplace_dir / f"entry-{enabled}")) in calls
    for name in ("alpha", "beta"):
        assert (kanon.parent / ".packages" / name / "README.md").read_text() == name
    lock = read_lockfile(lock_path)
    assert {s.name: s.registered_marketplaces for s in lock.sources} == {enabled: [enabled], disabled: []}
    before = lock_path.read_bytes()
    calls.clear()
    install(kanon, lock_path)
    assert lock_path.read_bytes() == before
    assert not any(action == "remove" for action, _name in calls)


@pytest.mark.parametrize("delivery", ["root", "json", "copy"])
def test_disable_prunes_once_and_updates_consistent_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str
) -> None:
    kanon, _marketplace_dir, calls = _setup(tmp_path, monkeypatch, delivery)
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    original = read_lockfile(lock_path)
    _disable(kanon, "beta")
    calls.clear()
    install(kanon, lock_path)
    assert ("remove", "beta") in calls
    assert ("register", "beta") not in calls
    current = read_lockfile(lock_path)
    assert current.kanon_hash == original.kanon_hash
    assert {s.name: s.content_pins for s in current.sources} == {s.name: s.content_pins for s in original.sources}
    assert {s.name: s.registered_marketplaces for s in current.sources} == {"alpha": ["alpha"], "beta": []}
    before = lock_path.read_bytes()
    calls.clear()
    install(kanon, lock_path)
    assert lock_path.read_bytes() == before
    assert ("remove", "beta") not in calls


def test_shared_name_remains_owned_by_enabled_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kanon, _marketplace_dir, calls = _setup(tmp_path, monkeypatch, "json", shared_name=True)
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    assert all(s.registered_marketplaces == ["shared"] for s in read_lockfile(lock_path).sources)
    _disable(kanon, "alpha")
    calls.clear()
    install(kanon, lock_path)
    assert ("remove", "shared") not in calls
    assert ("register", "shared") in calls
    assert {s.name: s.registered_marketplaces for s in read_lockfile(lock_path).sources} == {
        "alpha": [],
        "beta": ["shared"],
    }


def test_last_source_disable_and_reenable_persist_marketplace_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kanon, original_dir, calls = _setup(tmp_path, monkeypatch, "json")
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    marketplace_dir = user_home / ".claude-marketplaces"
    kanon.write_text(kanon.read_text().replace(str(original_dir), "${HOME}/.claude-marketplaces"))
    assert run_disable(argparse.Namespace(alias="alpha", kanon_file=str(kanon))) == 0
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    original = read_lockfile(lock_path)
    assert run_disable(argparse.Namespace(alias="beta", kanon_file=str(kanon))) == 0
    assert "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces" in kanon.read_text()
    calls.clear()
    install(kanon, lock_path)
    disabled = read_lockfile(lock_path)
    assert disabled.marketplace_registered is False
    assert disabled.marketplace_dir == ""
    assert all(not source.registered_marketplaces for source in disabled.sources)
    assert calls == [("remove", "beta")]
    assert (marketplace_dir / "entry-beta" / ".claude-plugin" / "marketplace.json").is_file()
    before = lock_path.read_bytes()
    calls.clear()
    install(kanon, lock_path)
    assert calls == []
    assert lock_path.read_bytes() == before
    assert run_enable(argparse.Namespace(alias="beta", kanon_file=str(kanon))) == 0
    calls.clear()
    install(kanon, lock_path)
    enabled = read_lockfile(lock_path)
    assert enabled.marketplace_registered is True
    assert enabled.marketplace_dir == str(marketplace_dir)
    assert enabled.kanon_hash == original.kanon_hash
    assert {source.name: source.content_pins for source in enabled.sources} == {
        source.name: source.content_pins for source in original.sources
    }
    assert {source.name: source.registered_marketplaces for source in enabled.sources} == {
        "alpha": [],
        "beta": ["beta"],
    }
    assert ("register", "beta") in calls
    assert not any(action == "remove" for action, _name in calls)


@pytest.mark.parametrize("delivery", ["root", "json", "copy"])
def test_disabled_source_cannot_replace_enabled_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str
) -> None:
    kanon, _marketplace_dir, calls = _setup(tmp_path, monkeypatch, delivery, shared_destination=True)
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    before = lock_path.read_bytes()
    _disable(kanon, "beta")
    calls.clear()
    with pytest.raises(ValueError, match="Use distinct marketplace"):
        install(kanon, lock_path)
    assert lock_path.read_bytes() == before
    assert calls == []


def test_partial_refresh_persists_marketplace_directory_and_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kanon, marketplace_dir, calls = _setup(tmp_path, monkeypatch, "json")
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    _disable(kanon, "beta")
    moved = marketplace_dir.with_name("other-marketplaces")
    kanon.write_text(kanon.read_text().replace(str(marketplace_dir), str(moved)))
    calls.clear()
    install(kanon, lock_path, refresh_lock_source="alpha")
    lock = read_lockfile(lock_path)
    assert lock.marketplace_registered is True
    assert lock.marketplace_dir == str(moved)
    assert {s.name: s.registered_marketplaces for s in lock.sources} == {"alpha": ["alpha"], "beta": []}
    assert ("remove", "beta") in calls


def test_copyfile_cannot_traverse_enabled_marketplace_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kanon, marketplace_dir, calls = _setup(tmp_path, monkeypatch, "root", shared_destination=True, beta_delivery="copy")
    _disable(kanon, "beta")
    lock_path = kanon.with_name(".kanon.lock")
    with pytest.raises(RepoCommandError):
        install(kanon, lock_path)
    assert not lock_path.exists()
    assert calls == []
    assert read_marketplace_name(marketplace_dir / "same-destination") == "alpha"


@pytest.mark.parametrize("delivery", ["json", "copy"])
def test_later_source_cleanup_cannot_delete_enabled_marketplace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str
) -> None:
    kanon, _marketplace_dir, calls = _setup(tmp_path, monkeypatch, delivery, shared_destination=True)
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    before = lock_path.read_bytes()
    _disable(kanon, "beta")
    catalog_work = tmp_path / "catalog.work"
    xml_path = catalog_work / "beta.xml"
    tree = ET.parse(xml_path)
    project = tree.getroot().find("project")
    assert project is not None
    for element in list(project):
        project.remove(element)
    tree.write(xml_path)
    run_git(["add", "beta.xml"], catalog_work)
    run_git(["commit", "-m", "remove beta delivery"], catalog_work)
    run_git(["push", str(tmp_path / "catalog.git"), "main"], catalog_work)
    calls.clear()
    with pytest.raises(ValueError, match="Use distinct marketplace"):
        install(kanon, lock_path, refresh_lock_source="beta")
    assert calls == []
    assert lock_path.read_bytes() == before


def test_failed_unregister_preserves_ledger_for_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kanon, _marketplace_dir, calls = _setup(tmp_path, monkeypatch, "json")
    lock_path = kanon.with_name(".kanon.lock")
    install(kanon, lock_path)
    before = lock_path.read_bytes()
    _disable(kanon, "beta")
    monkeypatch.setattr("kanon_cli.core.install.remove_marketplace", lambda _claude, _name: False)
    with pytest.raises(ValueError, match="Failed to unregister marketplace 'beta'"):
        install(kanon, lock_path)
    assert lock_path.read_bytes() == before
    calls.clear()
    monkeypatch.setattr(
        "kanon_cli.core.install.remove_marketplace",
        lambda _claude, name: calls.append(("remove", name)) or True,
    )
    install(kanon, lock_path)
    assert ("remove", "beta") in calls
    assert next(s for s in read_lockfile(lock_path).sources if s.name == "beta").registered_marketplaces == []


def test_copyfile_ownership_only_reads_exact_json_destinations_under_marketplace_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / ".repo").mkdir(parents=True)
    marketplaces = tmp_path / "marketplaces"
    owned = marketplaces / "entry" / ".claude-plugin" / "marketplace.json"
    (source / ".repo" / "copy-link-files.json").write_text(
        json.dumps(
            {
                "copyfile": [
                    str(owned),
                    str(tmp_path / "marketplaces-other" / "entry" / ".claude-plugin" / "marketplace.json"),
                    str(marketplaces / "nested" / "entry" / ".claude-plugin" / "marketplace.json"),
                    str(marketplaces / "entry" / "README.md"),
                ]
            }
        )
    )
    assert copied_marketplace_json_paths(source, marketplaces) == [owned]
