"""Forced replacement removes marketplace registrations owned by the old manifest."""

import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.commands.add import _repin_lock_entry
from kanon_cli.core.install import _RefResolution, install
from kanon_cli.core.lockfile import read_lockfile
from tests.conftest import materialize_linkfiles_for_sync
from tests.integration.test_add_core import _create_manifest_repo_with_tags
from tests.integration.test_marketplace_orphan_prune import (
    _extract_marketplace_remove_names,
    _make_repo_init_with_linkfiles,
    _write_kanonenv_single_source,
)


@pytest.mark.integration
@pytest.mark.parametrize("marketplace_enabled", [True, False])
def test_force_readd_prunes_replaced_marketplace(tmp_path: pathlib.Path, marketplace_enabled: bool) -> None:
    """Keep the old ownership ledger until install has compared it with fresh attribution."""
    tmp_path = tmp_path.resolve()
    marketplace_dir = tmp_path / "marketplace"
    bare = _create_manifest_repo_with_tags(tmp_path / "catalog", entry_names=["source-alpha"], tags=["1.0.0"])
    workspace = tmp_path / "workspace"
    config = _write_kanonenv_single_source(workspace, marketplace_dir, "source_alpha", bare.as_uri())
    lock_path = workspace / ".kanon.lock"

    def replace_manifest(repo_dir, *args):
        for manifest in (pathlib.Path(repo_dir) / ".repo" / "manifests").rglob("*.xml"):
            manifest.unlink()
        _make_repo_init_with_linkfiles(marketplace_dir)(repo_dir, *args)

    with (
        patch("kanon_cli.repo.repo_init", side_effect=replace_manifest),
        patch("kanon_cli.repo.repo_envsubst"),
        patch(
            "kanon_cli.repo.repo_sync",
            side_effect=lambda repo_dir, **kwargs: materialize_linkfiles_for_sync(pathlib.Path(repo_dir)),
        ),
        patch("kanon_cli.core.marketplace.shutil.which", return_value="/usr/bin/claude"),
        patch(
            "kanon_cli.core.marketplace.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as mock_run,
    ):
        install(config, lock_file_path=lock_path)
        assert read_lockfile(lock_path).sources[0].registered_marketplaces == ["source_alpha"]
        replacement = "repo-specs/source_bravo-marketplace.xml"
        config.write_text(config.read_text().replace("repo-specs/source_alpha-marketplace.xml", replacement))
        if not marketplace_enabled:
            config.write_text(config.read_text().replace("_MARKETPLACE=true", "_MARKETPLACE=false"))
        old_entry = read_lockfile(lock_path).sources[0]
        with patch(
            "kanon_cli.commands.add._resolve_ref_to_sha",
            return_value=_RefResolution(sha=old_entry.resolved_sha, resolved_ref=old_entry.resolved_ref),
        ):
            _repin_lock_entry(config, "source_alpha", bare.as_uri(), "main", replacement)
        assert read_lockfile(lock_path).sources[0].registered_marketplaces == ["source_alpha"]
        mock_run.reset_mock()
        install(config, lock_file_path=lock_path)
    removed = _extract_marketplace_remove_names(mock_run.call_args_list)
    assert removed == ["source_alpha"]
    assert read_lockfile(lock_path).sources[0].registered_marketplaces == (
        ["source_bravo"] if marketplace_enabled else []
    )
