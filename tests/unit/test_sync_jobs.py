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

from kanon_cli.constants import KANON_SYNC_JOBS_ENV, resolve_sync_jobs
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
        """The resolved job count reaches repo_sync as the jobs keyword."""
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        monkeypatch.setenv(KANON_SYNC_JOBS_ENV, "1")
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            run_repo_sync(source_dir)
        mock_sync.assert_called_once_with(str(source_dir), jobs=1)

    def test_forwards_none_when_unset(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the variable unset, repo_sync receives jobs=None and keeps its default."""
        source_dir = tmp_path / ".kanon-data" / "sources" / "build"
        source_dir.mkdir(parents=True)
        monkeypatch.delenv(KANON_SYNC_JOBS_ENV, raising=False)
        with patch("kanon_cli.repo.repo_sync") as mock_sync:
            run_repo_sync(source_dir)
        mock_sync.assert_called_once_with(str(source_dir), jobs=None)

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
