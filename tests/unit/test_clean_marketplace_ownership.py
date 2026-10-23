"""Cleanup uses recorded marketplace owners, including explicit empty ledgers."""

import json
import pathlib
import shutil

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import compute_project_address, source_workspace_dir
from kanon_cli.core.lockfile import read_lockfile, write_lockfile
from tests.unit.test_clean import _make_source, _write_kanon_sources, _write_lock


pytestmark = pytest.mark.unit


def _setup(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, delivery: str):
    home = tmp_path / "home"
    monkeypatch.setenv("KANON_HOME", str(home))
    marketplaces = tmp_path / "marketplaces"
    marketplaces.mkdir()
    kanon = _write_kanon_sources(tmp_path, marketplaces, ["alpha", "beta"])
    lock = _write_lock(
        tmp_path,
        marketplace_dir=marketplaces,
        sources=[
            _make_source("alpha", registered_marketplaces=["shared"]),
            _make_source("beta", registered_marketplaces=[]),
        ],
    )
    source_dirs = {}
    for name in ("alpha", "beta"):
        source = source_workspace_dir(home / "store", compute_project_address(kanon), name)
        source_dirs[name] = source
        metadata = source / "content" / ".claude-plugin" / "marketplace.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({"name": "shared", "plugins": [{"name": name}]}), encoding="utf-8")
        entry = marketplaces / name
        if delivery == "copy":
            destination = entry / ".claude-plugin" / "marketplace.json"
            destination.parent.mkdir(parents=True)
            shutil.copyfile(metadata, destination)
            (source / ".repo").mkdir()
            (source / ".repo" / "copy-link-files.json").write_text(
                json.dumps({"copyfile": [str(destination)]}), encoding="utf-8"
            )
        else:
            entry.symlink_to(metadata.parent.parent, target_is_directory=True)
    calls = []
    monkeypatch.setattr("kanon_cli.core.marketplace.locate_claude_binary", lambda: "claude-test")
    monkeypatch.setattr(
        "kanon_cli.core.marketplace.uninstall_plugin",
        lambda _cli, plugin, marketplace: calls.append(("uninstall", plugin, marketplace)) or True,
    )
    monkeypatch.setattr(
        "kanon_cli.core.marketplace.remove_marketplace",
        lambda _cli, marketplace: calls.append(("remove", marketplace)) or True,
    )
    return kanon, lock, marketplaces, source_dirs, calls


@pytest.mark.parametrize("delivery", ["link", "copy"])
def test_last_installed_ownership_wins_over_current_flags(tmp_path: pathlib.Path, monkeypatch, delivery: str) -> None:
    kanon, _lock, marketplaces, _sources, calls = _setup(tmp_path, monkeypatch, delivery)
    kanon.write_text(
        kanon.read_text().replace("KANON_SOURCE_alpha_MARKETPLACE=true", "KANON_SOURCE_alpha_MARKETPLACE=false")
    )
    clean(kanon)
    assert calls == [("uninstall", "alpha", "shared"), ("remove", "shared")]
    assert not marketplaces.exists()


@pytest.mark.parametrize("delivery", ["link", "copy"])
def test_missing_attribution_retains_legacy_directory_teardown(
    tmp_path: pathlib.Path, monkeypatch, delivery: str
) -> None:
    kanon, lock, marketplaces, _sources, calls = _setup(tmp_path, monkeypatch, delivery)
    lock.write_text(
        "\n".join(line for line in lock.read_text().splitlines() if not line.startswith("registered_marketplaces ="))
        + "\n"
    )
    clean(kanon)
    assert {call[1] for call in calls if call[0] == "uninstall"} == {"alpha", "beta"}
    assert not marketplaces.exists()


def test_explicit_empty_ledgers_do_not_fall_back_to_new_flags(tmp_path: pathlib.Path, monkeypatch) -> None:
    kanon, lock_path, _marketplaces, _sources, calls = _setup(tmp_path, monkeypatch, "link")
    lock = read_lockfile(lock_path)
    for source in lock.sources:
        source.registered_marketplaces = []
    lock.marketplace_registered = False
    lock.marketplace_dir = ""
    write_lockfile(lock, lock_path)
    clean(kanon)
    assert calls == []


def test_missing_workspace_does_not_uninstall_disabled_provider(tmp_path: pathlib.Path, monkeypatch) -> None:
    kanon, _lock, marketplaces, sources, calls = _setup(tmp_path, monkeypatch, "link")
    shutil.rmtree(sources["alpha"])
    clean(kanon)
    assert calls == []
    assert not marketplaces.exists()


def test_copy_owner_uses_all_delivery_ledgers_in_install_order(tmp_path: pathlib.Path, monkeypatch) -> None:
    kanon, _lock, marketplaces, sources, calls = _setup(tmp_path, monkeypatch, "copy")
    destination = marketplaces / "alpha" / ".claude-plugin" / "marketplace.json"
    destination.write_text(json.dumps({"name": "shared", "plugins": [{"name": "beta"}]}), encoding="utf-8")
    (sources["beta"] / ".repo" / "copy-link-files.json").write_text(
        json.dumps({"copyfile": [str(destination)]}), encoding="utf-8"
    )
    clean(kanon)
    assert calls == []
