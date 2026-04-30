"""RP-forall-01..10: `kanon repo forall` scenarios.

Automates §23 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest, rp_ro_setup
from tests.scenarios.conftest import run_kanon


@pytest.fixture(scope="module")
def forall_ws(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Module-scoped synced workspace for RP-forall-* tests."""
    base = tmp_path_factory.mktemp("rp_forall")
    manifest_bare = build_rp_ro_manifest(base / "fixtures")
    ws = base / "workspace"
    rp_ro_setup(ws, manifest_bare)
    return ws


@pytest.mark.scenario
class TestRPForall:
    """RP-forall-01..10: `kanon repo forall` command variations."""

    def test_rp_forall_01_bare_c(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-01: bare `-c` runs a command in every project."""
        result = run_kanon("repo", "forall", "-c", "echo IN_PROJECT", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall -c exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "IN_PROJECT" in result.stdout, f"Expected 'IN_PROJECT' in stdout: {result.stdout!r}"

    def test_rp_forall_02_regex(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-02: `--regex` / `-r` filters projects by regex pattern."""
        result = run_kanon("repo", "forall", "-r", "pkg-", "-c", "echo X", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall -r exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_03_inverse_regex(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-03: `--inverse-regex` / `-i` excludes projects matching pattern."""
        result = run_kanon("repo", "forall", "-i", "collider", "-c", "echo X", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall -i exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_04_groups(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-04: `--groups` / `-g` filters by manifest group."""
        result = run_kanon("repo", "forall", "-g", "default", "-c", "echo X", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall -g default exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_05_abort_on_errors(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-05: `--abort-on-errors` / `-e` halts iteration on first failure."""
        result = run_kanon("repo", "forall", "-e", "-c", "false", cwd=forall_ws)

        assert result.returncode != 0, (
            f"repo forall -e -c false should have exited non-zero\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_06_ignore_missing(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-06: `--ignore-missing` continues when projects are absent."""
        result = run_kanon("repo", "forall", "--ignore-missing", "-c", "echo X", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall --ignore-missing exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_07_project_header(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-07: `--project-header` / `-p` prints a project header line."""
        result = run_kanon("repo", "forall", "-p", "-c", "echo X", cwd=forall_ws)

        assert result.returncode == 0, (
            f"repo forall -p exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "project " in result.stdout, f"Expected 'project ' header in stdout: {result.stdout!r}"

    def test_rp_forall_08_interactive_no_tty(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-08: `--interactive` skips gracefully without a tty."""
        result = run_kanon("repo", "forall", "--interactive", "-c", "echo X", cwd=forall_ws)

        combined = result.stdout + result.stderr
        acceptable = result.returncode == 0 or "no-tty" in combined or "tty" in combined.lower()
        assert acceptable, (
            f"repo forall --interactive exited {result.returncode} unexpectedly\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_rp_forall_09_repo_env_vars(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-09: REPO_PROJECT, REPO_PATH, REPO_REMOTE, REPO_LREV, REPO_RREV are set."""
        result = run_kanon(
            "repo",
            "forall",
            "-c",
            "env | grep -E '^REPO_(PROJECT|PATH|REMOTE|LREV|RREV)='",
            cwd=forall_ws,
        )

        assert result.returncode == 0, (
            f"repo forall env vars exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        for var in ("REPO_PROJECT=", "REPO_PATH=", "REPO_REMOTE=", "REPO_LREV=", "REPO_RREV="):
            assert var in result.stdout, f"Expected {var!r} in forall output: {result.stdout!r}"

    def test_rp_forall_10_repo_count(self, forall_ws: pathlib.Path) -> None:
        """RP-forall-10: REPO_COUNT env var matches the project count from `repo list`."""
        list_result = run_kanon("repo", "list", "-p", cwd=forall_ws)
        assert list_result.returncode == 0, f"repo list -p failed: {list_result.stderr!r}"
        expected_count = str(len(list_result.stdout.strip().splitlines()))

        forall_result = run_kanon(
            "repo",
            "forall",
            "-c",
            "echo $REPO_COUNT",
            cwd=forall_ws,
        )
        assert forall_result.returncode == 0, (
            f"repo forall REPO_COUNT exited {forall_result.returncode}\n"
            f"stdout={forall_result.stdout!r}\nstderr={forall_result.stderr!r}"
        )
        # REPO_COUNT should appear once per project; all occurrences equal expected.
        actual_counts = [line.strip() for line in forall_result.stdout.splitlines() if line.strip().isdigit()]
        assert actual_counts, f"No numeric REPO_COUNT lines found in output: {forall_result.stdout!r}"
        for count in actual_counts:
            assert count == expected_count, f"REPO_COUNT={count!r} does not match project count={expected_count!r}"
