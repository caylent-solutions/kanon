"""Install then clean respects per-source marketplace opt-in after flag edits."""

from pathlib import Path

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from tests.integration.test_marketplace_source_ownership import _disable, _setup


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Use actual local commits for the real install."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Keep actual Git reachability checks enabled."""
    yield


@pytest.mark.parametrize("delivery", ["root", "json", "copy"])
@pytest.mark.parametrize("shared_name", [False, True])
def test_clean_uses_last_install_owners_after_flags_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str, shared_name: bool
) -> None:
    kanon, marketplace_dir, calls = _setup(tmp_path, monkeypatch, delivery, shared_name=shared_name)
    _disable(kanon, "beta")
    install(kanon, kanon.with_name(".kanon.lock"))
    if delivery == "copy":
        for name in ("alpha", "beta"):
            metadata = marketplace_dir / f"entry-{name}" / ".claude-plugin" / "marketplace.json"
            assert metadata.is_file() and not metadata.is_symlink()
    _disable(kanon, "alpha")
    kanon.write_text(
        kanon.read_text().replace("KANON_SOURCE_beta_MARKETPLACE=false", "KANON_SOURCE_beta_MARKETPLACE=true")
    )
    calls.clear()
    monkeypatch.setattr(
        "kanon_cli.core.marketplace.uninstall_plugin",
        lambda _cli, plugin, _marketplace: calls.append(("uninstall", plugin)) or True,
    )
    monkeypatch.setattr(
        "kanon_cli.core.marketplace.remove_marketplace",
        lambda _cli, marketplace: calls.append(("remove", marketplace)) or True,
    )
    clean(kanon)
    assert {name for action, name in calls if action == "uninstall"} == {"alpha"}
    assert {name for action, name in calls if action == "remove"} == {"shared" if shared_name else "alpha"}
    assert not marketplace_dir.exists()
