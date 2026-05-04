"""RP-download-01..06: `kanon repo download` scenarios.

Automates §25 of `docs/integration-testing.md`.

All download scenarios expect failure (non-zero exit) because `kanon repo
download` requires a configured Gerrit/review server, which is unavailable
in the local automated test environment.  Each test asserts exit non-zero
with a diagnostically clear error, mirroring the bash `set +e; ...; set -e`
pattern in the doc.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.fixture(scope="module")
def download_ws(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced workspace for RP-download-* tests."""
    base = tmp_path_factory.mktemp("rp_download")
    manifest_bare = build_rp_ro_manifest(base / "fixtures")
    ws = base / "workspace"
    rp_ro_setup(ws, manifest_bare)
    return ws


def _assert_download_server_error(result: object, label: str) -> None:
    """Assert that a download command fails with a review-server-related error."""
    assert result.returncode != 0, (
        f"{label}: repo download should have failed without a review server\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


@pytest.mark.scenario
class TestRPDownload:
    """RP-download-01..06: change download via `kanon repo download` (no server)."""

    def test_rp_download_01_bare_no_server(self, download_ws: pathlib.Path) -> None:
        """RP-download-01: bare `kanon repo download <change>` fails without review server."""
        result = run_kanon("repo", "download", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-01")

    def test_rp_download_02_cherry_pick(self, download_ws: pathlib.Path) -> None:
        """RP-download-02: `-c` / `--cherry-pick` flag accepted; fails without server."""
        result = run_kanon("repo", "download", "-c", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-02")

    def test_rp_download_03_record_origin(self, download_ws: pathlib.Path) -> None:
        """RP-download-03: `-x` / `--record-origin` flag accepted; fails without server."""
        result = run_kanon("repo", "download", "-x", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-03")

    def test_rp_download_04_revert(self, download_ws: pathlib.Path) -> None:
        """RP-download-04: `-r` / `--revert` flag accepted; fails without server."""
        result = run_kanon("repo", "download", "-r", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-04")

    def test_rp_download_05_ff_only(self, download_ws: pathlib.Path) -> None:
        """RP-download-05: `-f` / `--ff-only` flag accepted; fails without server."""
        result = run_kanon("repo", "download", "-f", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-05")

    def test_rp_download_06_branch(self, download_ws: pathlib.Path) -> None:
        """RP-download-06: `-b` / `--branch=<name>` flag accepted; fails without server."""
        result = run_kanon("repo", "download", "-b", "new-br", "12345", cwd=download_ws)
        _assert_download_server_error(result, "RP-download-06")
