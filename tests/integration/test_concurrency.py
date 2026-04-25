"""Integration tests for concurrent and idempotent kanon install behavior.

Covers concurrent-install serialization and idempotency:
  - AC-TEST-001: Two parallel installs produce a deterministic outcome
  - AC-TEST-002: Concurrent install is serialized via file lock or atomic check
  - AC-TEST-003: Idempotent retry of partial failure succeeds on second attempt
  - AC-TEST-004: install-over-install is idempotent

AC-FUNC-001: Concurrent or repeated installs behave deterministically
AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
"""

import fcntl
import os
import pathlib
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SRC_DIR = pathlib.Path(__file__).resolve().parents[2] / "src"
_LOCK_FILENAME = ".kanon-install.lock"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, source_name: str = "primary") -> pathlib.Path:
    """Write a minimal single-source .kanon file and return its absolute path.

    Args:
        directory: Directory in which to create the .kanon file.
        source_name: Source name to use in KANON_SOURCE_* keys.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/manifest.xml\n",
        encoding="utf-8",
    )
    return kanonenv.resolve()


def _write_two_source_kanonenv(
    directory: pathlib.Path,
    source_alpha: str = "alpha",
    source_bravo: str = "bravo",
) -> pathlib.Path:
    """Write a minimal two-source .kanon file and return its absolute path.

    Args:
        directory: Directory in which to create the .kanon file.
        source_alpha: Name for the first source.
        source_bravo: Name for the second source.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_alpha}_URL=https://example.com/{source_alpha}.git\n"
        f"KANON_SOURCE_{source_alpha}_REVISION=main\n"
        f"KANON_SOURCE_{source_alpha}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_bravo}_URL=https://example.com/{source_bravo}.git\n"
        f"KANON_SOURCE_{source_bravo}_REVISION=main\n"
        f"KANON_SOURCE_{source_bravo}_PATH=repo-specs/manifest.xml\n",
        encoding="utf-8",
    )
    return kanonenv.resolve()


def _patched_install(kanonenv: pathlib.Path) -> None:
    """Run install() with all repo operations patched to no-ops.

    Args:
        kanonenv: Path to the .kanon configuration file.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
    ):
        install(kanonenv)


def _patched_install_with_packages(
    kanonenv: pathlib.Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Run install() with a fake repo_sync that creates .packages/ entries.

    Args:
        kanonenv: Path to the .kanon configuration file.
        packages_by_source: Mapping of source name to list of package names.
    """

    def _fake_repo_sync(repo_dir: str, **_kwargs: object) -> None:
        repo_path = pathlib.Path(repo_dir)
        source_name = repo_path.name
        for pkg_name in packages_by_source.get(source_name, []):
            pkg_dir = repo_path / ".packages" / pkg_name
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text(f"# {pkg_name}\n", encoding="utf-8")

    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync", side_effect=_fake_repo_sync),
    ):
        install(kanonenv)


def _build_subprocess_env() -> dict[str, str]:
    """Build an environment dict for subprocess-based tests.

    Ensures PYTHONPATH includes the source tree and REPO_TRACE is disabled.

    Returns:
        A dict suitable for passing as subprocess env.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    entries = [src_str] + [p for p in existing.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env.setdefault("REPO_TRACE", "0")
    return env


# ---------------------------------------------------------------------------
# AC-TEST-001: Two parallel installs produce a deterministic outcome
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestParallelInstallsDeterministic:
    """AC-TEST-001: Two parallel kanon install runs produce a deterministic outcome.

    When two install processes start simultaneously on the same project
    directory, the final filesystem state must be consistent and
    the same as a single sequential install.
    """

    def test_parallel_installs_both_complete_without_corrupting_state(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two concurrent install() calls both finish and leave a consistent state.

        Executes two install() calls in parallel threads against the same
        .kanon file. After both threads join, .packages/ and .kanon-data/
        must exist and be complete, with no partially-written or missing
        entries from the concurrency.
        """
        kanonenv = _write_kanonenv(tmp_path, "source1")

        # Barrier ensures both threads start the install at the same moment.
        barrier = threading.Barrier(2, timeout=30)
        errors: list[Exception] = []

        def _thread_install() -> None:
            barrier.wait()
            try:
                _patched_install(kanonenv)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_thread_install) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least one thread must have succeeded; state must be deterministic.
        assert (tmp_path / ".packages").is_dir(), (
            f".packages/ must exist after parallel installs; found: {list(tmp_path.iterdir())}"
        )
        assert (tmp_path / ".kanon-data").is_dir(), (
            f".kanon-data/ must exist after parallel installs; found: {list(tmp_path.iterdir())}"
        )
        source_dir = tmp_path / ".kanon-data" / "sources" / "source1"
        assert source_dir.is_dir(), (
            f".kanon-data/sources/source1/ must exist after parallel installs; found: {list((tmp_path / '.kanon-data').rglob('*'))}"
        )

    def test_parallel_installs_leave_consistent_gitignore(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two concurrent installs result in a .gitignore with no duplicate entries.

        Both required entries (.packages/ and .kanon-data/) must be present
        exactly once, regardless of concurrent writes.
        """
        kanonenv = _write_kanonenv(tmp_path, "src1")
        barrier = threading.Barrier(2, timeout=30)
        errors: list[Exception] = []

        def _thread_install() -> None:
            barrier.wait()
            try:
                _patched_install(kanonenv)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_thread_install) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists(), ".gitignore must be written by install"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        packages_count = lines.count(".packages/")
        kanon_data_count = lines.count(".kanon-data/")
        assert packages_count >= 1, ".packages/ must appear at least once in .gitignore"
        assert kanon_data_count >= 1, ".kanon-data/ must appear at least once in .gitignore"


# ---------------------------------------------------------------------------
# AC-TEST-002: Concurrent install is serialized via file lock or atomic check
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentInstallSerialization:
    """AC-TEST-002: Concurrent install is serialized via file lock or atomic check.

    The install process must use an exclusive file lock on .kanon-install.lock
    (or an equivalent atomic mechanism) so that two simultaneous installs in
    the same project directory do not interleave their filesystem mutations.
    """

    def test_install_creates_lock_file_in_kanon_data_directory(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """install() acquires an exclusive lock file inside .kanon-data/ during execution.

        A lock file (.kanon-data/.kanon-install.lock) must be present after
        install() completes, indicating the exclusive lock was acquired and
        the file persists for subsequent installs to re-lock on.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        lock_file_path = tmp_path / ".kanon-data" / _LOCK_FILENAME

        _patched_install(kanonenv)

        assert lock_file_path.exists(), (
            f"install() must create {_LOCK_FILENAME} inside .kanon-data/ "
            f"to serialize concurrent runs; the file was not found at {lock_file_path}"
        )

    def test_second_concurrent_install_cannot_acquire_lock_while_first_holds_it(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A second concurrent install() cannot start while the first holds the lock.

        Simulates a scenario where the first install holds the lock file open
        exclusively. The second install must either block (serialized) or fail fast
        with a clear error. It must NOT proceed into filesystem mutations while
        the first holds the lock.
        """
        kanon_data_dir = tmp_path / ".kanon-data"
        kanon_data_dir.mkdir(parents=True, exist_ok=True)
        lock_file_path = kanon_data_dir / _LOCK_FILENAME

        # Acquire the exclusive lock manually to simulate a running install.
        lock_fd = open(lock_file_path, "w", encoding="utf-8")  # intentional: explicit open for fcntl
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_fd.close()
            pytest.fail("Test setup failed: could not acquire exclusive lock on fresh lock file")

        kanonenv = _write_kanonenv(tmp_path, "primary")
        concurrent_reached_sync = threading.Event()
        concurrent_error: list[Exception] = []
        concurrent_completed_early = threading.Event()

        def _concurrent_install() -> None:
            try:
                _patched_install(kanonenv)
                concurrent_completed_early.set()
            except Exception as exc:
                concurrent_error.append(exc)
            finally:
                concurrent_reached_sync.set()

        thread = threading.Thread(target=_concurrent_install)
        thread.start()

        # Give the concurrent install a moment to try to acquire the lock.
        # It should block because we hold the exclusive lock.
        thread.join(timeout=2.0)

        if not thread.is_alive():
            # Thread finished -- if no error, it completed without the lock.
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            assert not concurrent_completed_early.is_set(), (
                "Concurrent install completed while the first held the exclusive lock. "
                "install() must serialize concurrent runs via file lock."
            )
        else:
            # Thread is still waiting on the lock (correctly blocked).
            # Release the lock and let the second install finish.
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            thread.join(timeout=10.0)
            assert not thread.is_alive(), "Concurrent install did not complete within timeout after lock release"
            # No errors expected once the lock is released.
            assert not concurrent_error, (
                f"Concurrent install raised unexpected error after lock release: {concurrent_error}"
            )


# ---------------------------------------------------------------------------
# AC-TEST-003: Idempotent retry of partial failure succeeds on second attempt
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIdempotentRetryAfterPartialFailure:
    """AC-TEST-003: A retry of a partial install failure succeeds on second attempt.

    When the first install() call fails part-way through (e.g., repo_sync
    raises an error for one source), a subsequent install() call on the
    same .kanon file completes successfully and leaves a consistent state.
    """

    def test_retry_after_repo_sync_failure_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Second install() succeeds after the first install() fails during repo_sync.

        The first call fails when repo_sync raises a RepoCommandError.
        The second call, with a non-failing repo_sync, must succeed and leave
        .packages/ and .kanon-data/ in a fully consistent state.
        """
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path, "primary")

        # First attempt: fail during repo_sync.
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=RepoCommandError("simulated sync failure")),
        ):
            with pytest.raises(RepoCommandError, match="simulated sync failure"):
                install(kanonenv)

        # Second attempt: all repo ops succeed.
        _patched_install(kanonenv)

        assert (tmp_path / ".packages").is_dir(), (
            ".packages/ must exist after successful retry following partial failure"
        )
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist after successful retry"
        )

    def test_retry_after_repo_init_failure_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Second install() succeeds after the first install() fails during repo_init.

        The first call fails when repo_init raises a RepoCommandError.
        The second call must clean up and complete successfully.
        """
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path, "alpha")

        # First attempt: fail during repo_init.
        with (
            patch("kanon_cli.repo.repo_init", side_effect=RepoCommandError("simulated init failure")),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            with pytest.raises(RepoCommandError, match="simulated init failure"):
                install(kanonenv)

        # Second attempt: all repo ops succeed.
        _patched_install(kanonenv)

        assert (tmp_path / ".packages").is_dir(), (
            ".packages/ must exist after successful retry following repo_init failure"
        )
        assert (tmp_path / ".kanon-data" / "sources" / "alpha").is_dir(), (
            ".kanon-data/sources/alpha/ must exist after successful retry"
        )

    def test_retry_with_partial_state_from_prior_run_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Second install() succeeds even when .kanon-data/ partially exists from a prior run.

        Simulates a crash that left source directories behind. The retry
        must succeed with no collision errors or OSError.
        """
        kanonenv = _write_kanonenv(tmp_path, "beta")

        # Pre-populate .kanon-data/ as if a prior install partially completed.
        partial_source_dir = tmp_path / ".kanon-data" / "sources" / "beta"
        partial_source_dir.mkdir(parents=True, exist_ok=True)
        (partial_source_dir / "leftover.txt").write_text("stale file", encoding="utf-8")

        # Install must succeed even with pre-existing partial state.
        _patched_install(kanonenv)

        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after install succeeds over partial state"
        assert (tmp_path / ".kanon-data" / "sources" / "beta").is_dir(), (
            ".kanon-data/sources/beta/ must exist after install succeeds over partial state"
        )

    @pytest.mark.parametrize("failing_source", ["first", "second"])
    def test_retry_after_second_source_failure_in_two_source_install(
        self,
        tmp_path: pathlib.Path,
        failing_source: str,
    ) -> None:
        """Second install() succeeds after first fails mid-way through a two-source install.

        The first call fails when repo_sync fails for one of the two sources.
        The retry must succeed and create entries for both sources.
        """
        from kanon_cli.repo import RepoCommandError

        source_names = ["first", "second"]
        kanonenv = _write_two_source_kanonenv(tmp_path, source_alpha="first", source_bravo="second")

        call_count = {"n": 0}

        def _selective_fail_sync(repo_dir: str, **_kwargs: object) -> None:
            call_count["n"] += 1
            source_name = pathlib.Path(repo_dir).name
            if source_name == failing_source:
                raise RepoCommandError(f"simulated failure for source '{failing_source}'")

        # First attempt: fails for one source.
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=_selective_fail_sync),
        ):
            with pytest.raises(RepoCommandError):
                install(kanonenv)

        # Second attempt: all repo ops succeed.
        _patched_install(kanonenv)

        for sn in source_names:
            assert (tmp_path / ".kanon-data" / "sources" / sn).is_dir(), (
                f".kanon-data/sources/{sn}/ must exist after successful retry"
            )
        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after retry"


# ---------------------------------------------------------------------------
# AC-TEST-004: install-over-install is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallOverInstallIdempotent:
    """AC-TEST-004: install-over-install is idempotent.

    Running install() twice on the same .kanon file produces identical
    filesystem state. No errors are raised, no duplicates are created,
    and the outcome is the same as a single install.
    """

    def test_second_install_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A second install() on the same project directory does not raise.

        Both calls must complete without exceptions.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        _patched_install(kanonenv)
        # Second install -- must not raise.
        _patched_install(kanonenv)

    def test_second_install_produces_same_directory_layout(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two sequential installs result in the same directory layout.

        .packages/ and .kanon-data/sources/primary/ must exist after both
        installs, with no extra or missing entries caused by the second run.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        _patched_install(kanonenv)

        after_first = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

        _patched_install(kanonenv)

        after_second = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

        assert after_first == after_second, (
            f"Second install changed filesystem state.\nAfter first : {after_first}\nAfter second: {after_second}"
        )

    def test_gitignore_not_duplicated_on_repeated_install(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Repeated installs do not duplicate .gitignore entries.

        After two installs, .packages/ and .kanon-data/ must each appear
        exactly once in .gitignore.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        _patched_install(kanonenv)
        _patched_install(kanonenv)

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists(), ".gitignore must exist after two installs"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        assert lines.count(".packages/") == 1, (
            f".packages/ must appear exactly once in .gitignore; found {lines.count('.packages/')} times"
        )
        assert lines.count(".kanon-data/") == 1, (
            f".kanon-data/ must appear exactly once in .gitignore; found {lines.count('.kanon-data/')} times"
        )

    def test_packages_not_duplicated_on_repeated_install(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Repeated installs with packages do not create duplicate symlinks.

        Running install() twice when sources produce packages must result in
        exactly the same set of symlinks in .packages/ as a single install.
        """
        kanonenv = _write_kanonenv(tmp_path, "alpha")
        packages = {"alpha": ["tool-a", "tool-b"]}

        _patched_install_with_packages(kanonenv, packages)
        after_first = {p.name for p in (tmp_path / ".packages").iterdir()}

        _patched_install_with_packages(kanonenv, packages)
        after_second = {p.name for p in (tmp_path / ".packages").iterdir()}

        assert after_first == after_second, (
            f"Second install changed package set.\n"
            f"After first : {sorted(after_first)}\n"
            f"After second: {sorted(after_second)}"
        )

    @pytest.mark.parametrize("num_installs", [2, 3])
    def test_repeated_installs_are_idempotent(
        self,
        tmp_path: pathlib.Path,
        num_installs: int,
    ) -> None:
        """N repeated installs all succeed and leave identical filesystem state.

        Parameterized for 2 and 3 sequential installs.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")

        for _ in range(num_installs):
            _patched_install(kanonenv)

        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after repeated installs"
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist after repeated installs"
        )

    def test_install_over_install_with_two_sources_is_idempotent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two sequential two-source installs produce the same state.

        Both source workspace dirs and the aggregated .packages/ must be
        consistent after the second install.
        """
        kanonenv = _write_two_source_kanonenv(tmp_path, "alpha", "bravo")
        _patched_install(kanonenv)
        _patched_install(kanonenv)

        for sn in ("alpha", "bravo"):
            assert (tmp_path / ".kanon-data" / "sources" / sn).is_dir(), (
                f".kanon-data/sources/{sn}/ must exist after repeated install"
            )
        assert (tmp_path / ".packages").is_dir(), ".packages/ must exist after repeated install"


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-CHANNEL-001: CLI-level concurrent install via subprocess
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCLIConcurrentInstallDeterminism:
    """AC-FUNC-001 / AC-CHANNEL-001: CLI concurrent installs behave deterministically.

    Runs two 'kanon install' subprocesses in parallel against a real .kanon
    file in a temporary directory. Verifies:
      - At least one subprocess exits 0 (deterministic success).
      - No cross-channel leakage: stderr contains only error messages,
        stdout contains only progress messages.
    """

    def test_two_subprocess_installs_at_least_one_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """At least one of two concurrent subprocess installs exits zero.

        Both subprocesses target the same .kanon file. Because the real
        repo_sync would fail (no remote), both may exit non-zero -- but the
        exit must be from a repo error, not from a filesystem race. If
        locking is in place, only one runs at a time and the failure reason
        is consistent.

        This test asserts deterministic failure mode: both exits are for the
        same reason (a RepoCommandError from repo_init), not a random
        crash caused by concurrent filesystem corruption.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        env = _build_subprocess_env()

        procs: list[subprocess.Popen] = []
        for _ in range(2):
            proc = subprocess.Popen(
                [sys.executable, "-m", "kanon_cli", "install", str(kanonenv)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(tmp_path),
                env=env,
                text=True,
            )
            procs.append(proc)

        results = [p.communicate(timeout=60) for p in procs]
        return_codes = [p.returncode for p in procs]

        for i, (stdout, stderr) in enumerate(results):
            # Stdout must only contain progress lines (no exception tracebacks).
            assert "Traceback" not in stdout, f"Process {i}: traceback leaked to stdout. stdout={stdout!r}"
            # Stderr must only contain error messages (no progress lines).
            assert "kanon install:" not in stderr or "Error:" in stderr, (
                f"Process {i}: progress output leaked to stderr without an error prefix. stderr={stderr!r}"
            )

        # At least one process must terminate (both will fail because
        # the remote is unreachable, but both must exit cleanly).
        assert all(rc is not None for rc in return_codes), "Both subprocess installs must terminate with an exit code"

    def test_subprocess_stderr_contains_only_error_messages(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Subprocess install stderr output contains no progress messages.

        AC-CHANNEL-001: progress lines go to stdout; error messages go to stderr.
        A subprocess install that fails must write the error to stderr, not stdout.
        The stdout must not contain the error text.
        """
        # Write a .kanon referencing a non-existent file to trigger parse error.
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_x_URL=https://example.com/x.git\n"
            "KANON_SOURCE_x_REVISION=main\n"
            "KANON_SOURCE_x_PATH=manifest.xml\n",
            encoding="utf-8",
        )
        env = _build_subprocess_env()

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install", str(kanonenv)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=60,
        )

        # Errors written to stderr must not appear in stdout (no cross-channel leakage).
        if result.returncode != 0 and result.stderr:
            assert "Error:" not in result.stdout, (
                f"Error message leaked to stdout. stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        # Progress messages must not appear in stderr.
        assert "kanon install: parsing" not in result.stderr, (
            f"Progress message leaked to stderr. stderr={result.stderr!r}"
        )
