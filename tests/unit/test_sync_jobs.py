"""Tests for the KANON_SYNC_JOBS bound on repo-sync parallelism.

``repo sync`` fans out over a ``multiprocessing.Pool`` sized from
``min(cpu_count, 8)``. When many ``kanon`` processes share a machine those pools
contend for the same POSIX semaphores and can wedge -- the pool workers park in
``sem_wait()`` while the parent parks in ``waitpid()``, both at 0% CPU, forever.
``KANON_SYNC_JOBS`` lets a caller bound the fan-out, and ``1`` takes the
single-process short-circuit in ``repo.command`` so no pool is built at all.

Covers:
- resolve_sync_jobs() env parsing and its fail-fast rejection of bad values
- run_repo_sync() forwarding the resolved value to repo_sync(jobs=...)
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.repo.command import DEFAULT_LOCAL_JOBS
from kanon_cli.constants import REPO_DEFAULT_NETWORK_JOBS, KANON_SYNC_JOBS_ENV, resolve_sync_jobs
from kanon_cli.core.install import run_repo_sync


@pytest.mark.unit
class TestResolveSyncJobs:
    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unset variable defers to repo sync's own default rather than imposing one."""
        monkeypatch.delenv(KANON_SYNC_JOBS_ENV, raising=False)
        assert resolve_sync_jobs() is None

    @pytest.mark.parametrize("raw,expected", [("1", 1), ("4", 4), ("16", 16)])
    def test_parses_positive_integer(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
        """A positive integer is returned as an int for the --jobs flag."""
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, raw)
        assert resolve_sync_jobs() == expected

    @pytest.mark.parametrize("raw", ["0", "-1", "-8"])
    def test_rejects_non_positive(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        """Zero or negative exits non-zero instead of silently reaching repo sync."""
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, raw)
        with pytest.raises(SystemExit) as exc_info:
            resolve_sync_jobs()
        assert KANON_SYNC_JOBS_ENV in str(exc_info.value)

    @pytest.mark.parametrize("raw", ["", "auto", "2.5", "eight"])
    def test_rejects_unparseable(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        """A non-integer value fails fast and names the offending variable."""
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, raw)
        with pytest.raises(SystemExit) as exc_info:
            resolve_sync_jobs()
        message = str(exc_info.value)
        assert KANON_SYNC_JOBS_ENV in message
        assert repr(raw) in message


@pytest.mark.unit
class TestRunRepoSyncJobsPassthrough:
    def test_forwards_configured_job_count(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The resolved cap reaches repo_sync as a per-phase bound.

        Not a single ``jobs=`` argument: that sets network and checkout alike, and
        their defaults differ, so one value silently raised network fan-out.
        """
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, "1")
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            run_repo_sync(source_dir)
        mock_sync.assert_called_once_with(str(source_dir), jobs_network=1, jobs_checkout=1)

    def test_forwards_none_when_unset(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the variable unset, repo_sync is called bare and keeps its own defaults."""
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        monkeypatch.delenv(KANON_SYNC_JOBS_ENV, raising=False)
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            run_repo_sync(source_dir)
        mock_sync.assert_called_once_with(str(source_dir))

    def test_rejects_bad_value_before_running_sync(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A malformed value aborts before any repo sync work is started."""
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, "many")
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            with pytest.raises(SystemExit):
                run_repo_sync(source_dir)
        mock_sync.assert_not_called()


@pytest.mark.unit
class TestSuitePinsSyncToSingleProcess:
    def test_test_session_runs_sync_in_one_process(self) -> None:
        """The suite itself must never build a sync pool.

        ``tests/conftest.py`` pins ``KANON_SYNC_JOBS`` for the whole session. If that
        floor is ever removed, an xdist run multiplies pool workers by worker count
        and the deadlock this bound exists to prevent becomes reachable again.
        """
        assert resolve_sync_jobs() == 1, (
            f"The test session must pin {KANON_SYNC_JOBS_ENV} to 1 so repo sync takes the "
            f"single-process short-circuit; got {resolve_sync_jobs()!r}"
        )


@pytest.mark.unit
class TestSyncJobsIsACap:
    """`KANON_SYNC_JOBS` bounds fan-out; it must never raise it.

    `repo sync` resolves two independent job counts with *different* defaults:
    network fetch is 1, local checkout is `min(cpu_count, 8)`. A single
    `--jobs=N` sets both, so passing the requested value straight through took
    network fetch from 1 to N -- increasing the fan-out the variable exists to
    bound, while its own documentation called it a cap.
    """

    def _captured_call(self, monkeypatch: pytest.MonkeyPatch, requested: str) -> dict:
        captured: dict = {}

        def fake_sync(repo_dir, **kwargs):
            captured.update(kwargs)

        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, requested)
        monkeypatch.setattr("kanon_cli.core.install._repo.repo_sync", fake_sync)
        run_repo_sync(pathlib.Path("/tmp/source"))
        return captured

    def test_network_jobs_never_exceed_repos_own_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A large request must not raise network fetch above its default of 1."""
        captured = self._captured_call(monkeypatch, "64")
        assert captured["jobs_network"] == REPO_DEFAULT_NETWORK_JOBS, (
            f"KANON_SYNC_JOBS=64 raised network fetch to {captured['jobs_network']}, above "
            f"repo's own default of {REPO_DEFAULT_NETWORK_JOBS}. The variable is a cap."
        )

    def test_checkout_jobs_never_exceed_repos_own_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._captured_call(monkeypatch, "64")
        assert captured["jobs_checkout"] == DEFAULT_LOCAL_JOBS

    def test_a_smaller_request_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Capping must still allow bounding below the default -- the actual use case."""
        captured = self._captured_call(monkeypatch, "1")
        assert captured["jobs_network"] == 1
        assert captured["jobs_checkout"] == 1

    def test_no_jobs_argument_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset means repo resolves its own defaults, so production is unchanged."""
        captured: dict = {}

        def fake_sync(repo_dir, **kwargs):
            captured.update(kwargs)
            captured["called"] = True

        monkeypatch.delenv(KANON_SYNC_JOBS_ENV, raising=False)
        monkeypatch.setattr("kanon_cli.core.install._repo.repo_sync", fake_sync)
        run_repo_sync(pathlib.Path("/tmp/source"))

        assert captured == {"called": True}, (
            f"With KANON_SYNC_JOBS unset, repo_sync must be called with no job arguments so "
            f"repo resolves its own defaults; got {captured!r}"
        )
