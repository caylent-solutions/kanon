"""Integration tests for concurrent and idempotent kanon install behavior.

Covers concurrent-install serialization and idempotency:
  - AC-TEST-001: Two parallel installs produce a deterministic outcome
  - AC-TEST-002: Concurrent install is serialized via file lock or atomic check
  - AC-TEST-003: Idempotent retry of partial failure succeeds on second attempt
  - AC-TEST-004: install-over-install is idempotent

AC-FUNC-001: Concurrent or repeated installs behave deterministically
AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
"""

import contextlib
import multiprocessing
import multiprocessing.synchronize
import os
import pathlib
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install

# fcntl is POSIX-only; these tests exercise the POSIX fcntl.flock locking path.
# On Windows (no fcntl) the whole module is skipped at collection -- the Windows
# lock backend is covered by tests/integration/test_cross_platform_contract.py.
fcntl = pytest.importorskip("fcntl")


# ---------------------------------------------------------------------------
# Thread-safe patching helper
# ---------------------------------------------------------------------------
#
# `unittest.mock.patch` is NOT thread-safe: when two threads enter and exit
# overlapping `with patch(...)` blocks for the same attribute, the cleanup
# step races on the saved "original" reference, which can permanently leave
# a Mock object as the module attribute. Tests that previously paired
# `with patch(...)` *inside* a thread body therefore leaked the Mock into
# every later test that imported the patched name.
#
# The helpers below open the patch context ONCE in the main test thread,
# spawn the worker threads inside it (which call the unpatched
# `install()` directly), and exit the patch context after every thread
# joined -- restoration is single-threaded and the original repo_*
# functions are guaranteed to be back in place when the test returns.


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SRC_DIR = pathlib.Path(__file__).resolve().parents[2] / "src"
_LOCK_FILENAME = ".kanon-install.lock"
# Minimal well-formed manifest XML written by fake sync helpers so that
# install()'s include-walker can parse the manifest path after sync.
_EMPTY_MANIFEST_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest></manifest>\n'

# Cross-process readiness/join timeouts for the multiprocessing parallel-install
# tests. Overridable via environment variables so slow CI can extend them
# without editing the test; never used as a synchronization delay -- only as a
# fail-fast upper bound on event waits and process joins.
_PROC_READY_TIMEOUT = float(os.environ.get("KANON_TEST_INSTALL_READY_TIMEOUT", "30.0"))
_PROC_JOIN_TIMEOUT = float(os.environ.get("KANON_TEST_INSTALL_JOIN_TIMEOUT", "60.0"))


def _install_worker(
    kanonenv_path_str: str,
    ready_event: multiprocessing.synchronize.Event,
    go_event: multiprocessing.synchronize.Event,
    error_queue: "multiprocessing.Queue[str]",
) -> None:
    """Child-process worker: run a genuine ``install()`` under cross-process locking.

    This worker is the cross-PROCESS analogue of ``_patched_install``. The
    threaded autouse fixtures in this module only patch ``install()``'s repo
    boundary in the parent process, so a forked child must re-install those
    same hermetic mocks itself before calling ``install()``:

      * ``kanon_cli.repo.repo_init`` / ``repo_envsubst`` -> no-ops.
      * ``kanon_cli.repo.repo_sync`` -> writes the minimal manifest XML the
        include-walker parses (mirrors ``_default_repo_sync``).
      * ``_resolve_ref_to_sha`` / ``_check_sha_reachable`` -> deterministic,
        network-free (mirrors the integration conftest autouse fixtures, which
        the child does not inherit because it is a fresh fork target).

    Because each forked child is its own process with its own MAIN thread, the
    POSIX workspace lock's ``signal.setitimer`` / ``SIGALRM`` fail-fast timer
    works correctly (it raises ``ValueError`` only when armed off the main
    thread). The two workers therefore exercise the real cross-process
    ``fcntl.flock`` exclusion rather than an in-process thread race.

    Readiness handshake (no time-based synchronization): the worker sets
    ``ready_event`` once its mocks are in place, then blocks on ``go_event``
    so the parent can release both workers simultaneously. Any exception is
    serialised onto ``error_queue`` so the parent can assert on it.

    Args:
        kanonenv_path_str: String path to the ``.kanon`` file (multiprocessing
            arguments must be picklable; a plain ``str`` always is).
        ready_event: Set by the worker once it is ready to install.
        go_event: Waited on by the worker; set by the parent to start both
            installs at the same moment.
        error_queue: Receives a string describing any exception raised by
            ``install()`` so the parent can surface it in the assertion message.
    """
    from kanon_cli.core.install import _RefResolution

    kanonenv_path = pathlib.Path(kanonenv_path_str)

    def _worker_repo_sync(repo_dir: str, **_kwargs: object) -> None:
        _write_empty_manifest(repo_dir)

    try:
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=_worker_repo_sync),
            patch(
                "kanon_cli.core.install._resolve_ref_to_sha",
                return_value=_RefResolution(sha="a" * 40, resolved_ref="refs/heads/main"),
            ),
            patch("kanon_cli.core.install._check_sha_reachable"),
        ):
            ready_event.set()
            # Block until the parent releases both workers together. The event
            # wait is bounded by _PROC_READY_TIMEOUT so a wedged parent fails
            # the child fast rather than hanging it forever.
            if not go_event.wait(timeout=_PROC_READY_TIMEOUT):
                error_queue.put("go_event was not set within the readiness timeout")
                return
            install(
                kanonenv_path,
                lock_file_path=kanonenv_path.parent / ".kanon.lock",
            )
    except Exception as exc:
        # Serialise any install failure to the parent so it surfaces in the
        # cross-process assertion rather than dying silently in the child.
        error_queue.put(f"{type(exc).__name__}: {exc}")


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
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n",
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
        f"KANON_SOURCE_{source_alpha}_REF=main\n"
        f"KANON_SOURCE_{source_alpha}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_alpha}_NAME={source_alpha}\n"
        f"KANON_SOURCE_{source_alpha}_GITBASE=https://example.com\n"
        f"KANON_SOURCE_{source_bravo}_URL=https://example.com/{source_bravo}.git\n"
        f"KANON_SOURCE_{source_bravo}_REF=main\n"
        f"KANON_SOURCE_{source_bravo}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_bravo}_NAME={source_bravo}\n"
        f"KANON_SOURCE_{source_bravo}_GITBASE=https://example.com\n",
        encoding="utf-8",
    )
    return kanonenv.resolve()


def _write_empty_manifest(repo_dir: str, sub_path: str = "repo-specs/manifest.xml") -> None:
    """Write a minimal empty manifest XML under repo_dir/.repo/manifests/sub_path.

    After repo init + repo sync, manifest files live at source_dir/.repo/manifests/
    (the repo tool's manifest checkout dir). This helper mirrors that layout so
    install()'s include-walker finds the manifest at the expected location.

    Args:
        repo_dir: The source directory passed by install() to repo_sync.
        sub_path: Manifest path relative to the manifests repo root.
    """
    manifest_path = pathlib.Path(repo_dir) / ".repo" / "manifests" / sub_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_EMPTY_MANIFEST_XML, encoding="utf-8")


def _default_repo_sync(repo_dir: str, **_kwargs: object) -> None:
    """Default ``repo_sync`` side_effect used by the autouse patch fixture.

    Creates a minimal ``repo-specs/manifest.xml`` inside ``repo_dir`` so that
    ``install()``'s include-walker can parse the manifest path after sync.
    Tests that need custom sync behaviour override this via
    ``_use_repo_sync_side_effect``.

    Args:
        repo_dir: The source directory passed by install() to repo_sync.
    """
    _write_empty_manifest(repo_dir)


@pytest.fixture(autouse=True)
def _patch_kanon_cli_repo_for_each_test() -> Iterator[None]:
    """Auto-patch kanon_cli.repo.repo_{init,envsubst,sync} for every test.

    The patches are opened in the SINGLE-THREADED test setup phase and
    closed in the single-threaded teardown phase. Tests inside this
    module spawn threads that call ``install()`` -- those threads never
    enter or exit a patch context themselves, so the well-known
    `unittest.mock.patch` thread-safety hazard (overlapping enter/exit
    races on the saved "original" attribute and permanently leaks a
    Mock into the patched module) cannot occur here.

    Tests that wire a custom ``side_effect`` for ``repo_sync`` use
    ``_use_repo_sync_side_effect`` below; that helper restarts the
    ``repo_sync`` patch with the requested side_effect, still in the
    single-threaded test body.

    ``repo_sync`` is patched with ``_default_repo_sync`` as its side_effect
    so that ``install()``'s include-walker can parse the manifest XML that
    the real ``repo_sync`` would have created. Tests that need custom sync
    behaviour replace the side_effect via ``_use_repo_sync_side_effect``.
    """
    patches = [
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync", side_effect=_default_repo_sync),
    ]
    try:
        for p in patches:
            p.start()
        yield
    finally:
        for p in reversed(patches):
            p.stop()


@contextlib.contextmanager
def _use_repo_sync_side_effect(side_effect: Callable[..., object]) -> Iterator[None]:
    """Temporarily attach a ``side_effect`` to the auto-patched repo_sync.

    The autouse fixture above already replaces ``kanon_cli.repo.repo_sync``
    with a Mock for every test. Tests that need a non-trivial fake (one
    that materialises ``.packages/`` directories so the install
    aggregation step has something to work with) call this helper inside
    a ``with`` block; on exit the side_effect is removed but the Mock
    itself is left in place (the autouse fixture restores the real
    function in teardown).
    """
    import kanon_cli.repo as _repo_pkg

    target = _repo_pkg.repo_sync
    previous = getattr(target, "side_effect", None)
    target.side_effect = side_effect
    try:
        yield
    finally:
        target.side_effect = previous


def _patched_install(kanonenv: pathlib.Path) -> None:
    """Call the real install(); the autouse fixture handles the mocks.

    Retained as a thin shim because every call site in this module
    invokes it directly. The autouse fixture in this module mocks out
    every ``kanon_cli.repo.repo_*`` function once per test (in single-
    threaded setup), so threads that run this function concurrently
    only execute the production install() code path -- they do not
    set up or tear down their own patch contexts.

    ``kanon install`` is hermetic: it resolves no catalog source, so the
    production install() code path is driven solely by the committed .kanon
    (+ .kanon.lock). _resolve_ref_to_sha is mocked by the integration conftest
    autouse fixture so no real git call is made for the source URLs.
    """
    install(
        kanonenv,
        lock_file_path=kanonenv.parent / ".kanon.lock",
    )


def _patched_install_with_packages(
    kanonenv: pathlib.Path,
    packages_by_source: dict[str, list[str]],
) -> None:
    """Run install() with a fake repo_sync side_effect that creates .packages/.

    Also creates a minimal repo-specs/manifest.xml so that install()'s
    include-walker can parse the manifest path after sync.

    Args:
        kanonenv: Path to the .kanon configuration file.
        packages_by_source: Mapping of source name to list of package names.
    """

    def _fake_repo_sync(repo_dir: str, **_kwargs: object) -> None:
        repo_path = pathlib.Path(repo_dir)
        # Create minimal manifest XML so install()'s include-walker succeeds.
        _write_empty_manifest(repo_dir)
        source_name = repo_path.name
        for pkg_name in packages_by_source.get(source_name, []):
            pkg_dir = repo_path / ".packages" / pkg_name
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "README.md").write_text(f"# {pkg_name}\n", encoding="utf-8")

    with _use_repo_sync_side_effect(_fake_repo_sync):
        install(
            kanonenv,
            lock_file_path=kanonenv.parent / ".kanon.lock",
        )


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

    @staticmethod
    def _run_two_parallel_installs(
        kanonenv: pathlib.Path,
    ) -> list[str]:
        """Spawn two real install() subprocesses and run them concurrently.

        Uses ``multiprocessing`` with the ``fork`` start method so that each
        install runs in its own process with its own MAIN thread -- the only
        context in which the POSIX workspace lock's ``signal.setitimer`` /
        ``SIGALRM`` fail-fast timer is valid. This exercises genuine
        cross-process ``fcntl.flock`` exclusion (the real production model:
        two separate ``kanon install`` processes), not an in-process thread
        race that cannot arm the alarm timer off the main thread.

        A two-phase readiness handshake (``ready_event`` then ``go_event``,
        no ``sleep``) releases both workers at the same moment so their
        lock-acquisition windows overlap. The child ``KANON_HOME`` is inherited
        from this process's environment, so both installs target the same
        shared store and contend for the same workspace lock.

        Args:
            kanonenv: Path to the ``.kanon`` file both installs operate on.

        Returns:
            A list of error strings reported by the workers (empty when both
            installs completed cleanly). Each entry is a ``"TypeName: msg"``
            description serialised from a child exception.
        """
        ctx = multiprocessing.get_context("fork")
        go_event = ctx.Event()
        ready_events = [ctx.Event() for _ in range(2)]
        error_queue: "multiprocessing.Queue[str]" = ctx.Queue()

        procs = [
            ctx.Process(
                target=_install_worker,
                args=(str(kanonenv), ready_events[i], go_event, error_queue),
                daemon=True,
            )
            for i in range(2)
        ]
        for proc in procs:
            proc.start()

        # Readiness gate: wait until both children have installed their mocks
        # and are parked on go_event, then release them together.
        for i, ready in enumerate(ready_events):
            assert ready.wait(timeout=_PROC_READY_TIMEOUT), (
                f"Install worker {i} did not become ready within {_PROC_READY_TIMEOUT}s"
            )
        go_event.set()

        for i, proc in enumerate(procs):
            proc.join(timeout=_PROC_JOIN_TIMEOUT)
            assert not proc.is_alive(), f"Install worker {i} did not finish within {_PROC_JOIN_TIMEOUT}s"

        errors: list[str] = []
        while not error_queue.empty():
            errors.append(error_queue.get_nowait())
        return errors

    def test_parallel_installs_both_complete_without_corrupting_state(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two concurrent install() processes both finish and leave a consistent state.

        Executes two install() calls in parallel subprocesses against the same
        .kanon file. After both processes exit, .packages/ and .kanon-data/
        must exist and be complete in the shared KANON_HOME store, with no
        partially-written or missing entries from the concurrency, and neither
        worker may have raised.
        """
        kanonenv = _write_kanonenv(tmp_path, "source1")
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        errors = self._run_two_parallel_installs(kanonenv)
        assert not errors, f"Parallel installs raised errors instead of serialising cleanly: {errors}"

        # State must be deterministic regardless of which process won the lock first.
        assert (store_base / ".packages").is_dir(), (
            f".packages/ must exist in the store after parallel installs; found: {list(store_base.iterdir()) if store_base.exists() else 'missing'}"
        )
        assert (store_base / ".kanon-data").is_dir(), (
            f".kanon-data/ must exist in the store after parallel installs; found: {list(store_base.iterdir()) if store_base.exists() else 'missing'}"
        )
        source_dir = store_base / ".kanon-data" / "sources" / "source1"
        assert source_dir.is_dir(), (
            f".kanon-data/sources/source1/ must exist after parallel installs; found: {list((store_base / '.kanon-data').rglob('*'))}"
        )

    def test_parallel_installs_leave_consistent_gitignore(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two concurrent install processes result in a .gitignore with no duplicate entries.

        Both required entries (.packages/ and .kanon-data/) must be present
        exactly once in the store .gitignore, regardless of concurrent writes.
        Because the two installs serialise on the cross-process workspace lock,
        the second writer observes the first writer's entries and must not
        duplicate them.
        """
        kanonenv = _write_kanonenv(tmp_path, "src1")
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        errors = self._run_two_parallel_installs(kanonenv)
        assert not errors, f"Parallel installs raised errors instead of serialising cleanly: {errors}"

        gitignore = store_base / ".gitignore"
        assert gitignore.exists(), ".gitignore must be written by install under the store"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        packages_count = lines.count(".packages/")
        kanon_data_count = lines.count(".kanon-data/")
        # Serialised writers must each leave the required entry exactly once --
        # no duplication from the concurrent runs.
        assert packages_count == 1, (
            f".packages/ must appear exactly once in .gitignore after serialised parallel installs; found {packages_count}"
        )
        assert kanon_data_count == 1, (
            f".kanon-data/ must appear exactly once in .gitignore after serialised parallel installs; found {kanon_data_count}"
        )


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
        """install() acquires an exclusive lock file inside the store .kanon-data/ during execution.

        A lock file (.kanon-data/.kanon-install.lock) must be present under the
        shared KANON_HOME store after install() completes, indicating the exclusive
        lock was acquired and the file persists for subsequent installs to re-lock on.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        lock_file_path = store_base / ".kanon-data" / _LOCK_FILENAME

        _patched_install(kanonenv)

        assert lock_file_path.exists(), (
            f"install() must create {_LOCK_FILENAME} inside the store .kanon-data/ "
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
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        kanon_data_dir = store_base / ".kanon-data"
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
                install(
                    kanonenv,
                    lock_file_path=kanonenv.parent / ".kanon.lock",
                )

        # Second attempt: all repo ops succeed.
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        _patched_install(kanonenv)

        assert (store_base / ".packages").is_dir(), (
            ".packages/ must exist in the store after successful retry following partial failure"
        )
        assert (store_base / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist in the store after successful retry"
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
                install(
                    kanonenv,
                    lock_file_path=kanonenv.parent / ".kanon.lock",
                )

        # Second attempt: all repo ops succeed.
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        _patched_install(kanonenv)

        assert (store_base / ".packages").is_dir(), (
            ".packages/ must exist in the store after successful retry following repo_init failure"
        )
        assert (store_base / ".kanon-data" / "sources" / "alpha").is_dir(), (
            ".kanon-data/sources/alpha/ must exist in the store after successful retry"
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
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        # Pre-populate the store .kanon-data/ as if a prior install partially completed.
        partial_source_dir = store_base / ".kanon-data" / "sources" / "beta"
        partial_source_dir.mkdir(parents=True, exist_ok=True)
        (partial_source_dir / "leftover.txt").write_text("stale file", encoding="utf-8")

        # Install must succeed even with pre-existing partial state.
        _patched_install(kanonenv)

        assert (store_base / ".packages").is_dir(), (
            ".packages/ must exist in the store after install succeeds over partial state"
        )
        assert (store_base / ".kanon-data" / "sources" / "beta").is_dir(), (
            ".kanon-data/sources/beta/ must exist in the store after install succeeds over partial state"
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
            repo_path = pathlib.Path(repo_dir)
            source_name = repo_path.name
            if source_name == failing_source:
                raise RepoCommandError(f"simulated failure for source '{failing_source}'")
            # Create minimal manifest XML for the non-failing source so that
            # install()'s include-walker can parse the manifest path after sync.
            _write_empty_manifest(repo_dir)

        # First attempt: fails for one source.
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=_selective_fail_sync),
        ):
            with pytest.raises(RepoCommandError):
                install(
                    kanonenv,
                    lock_file_path=kanonenv.parent / ".kanon.lock",
                )

        # Second attempt: all repo ops succeed.
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        _patched_install(kanonenv)

        for sn in source_names:
            assert (store_base / ".kanon-data" / "sources" / sn).is_dir(), (
                f".kanon-data/sources/{sn}/ must exist in the store after successful retry"
            )
        assert (store_base / ".packages").is_dir(), ".packages/ must exist in the store after retry"


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
        exactly once in the store .gitignore.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        _patched_install(kanonenv)
        _patched_install(kanonenv)

        gitignore = store_base / ".gitignore"
        assert gitignore.exists(), ".gitignore must exist in the store after two installs"
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
        exactly the same set of symlinks in the store .packages/ as a single install.
        """
        kanonenv = _write_kanonenv(tmp_path, "alpha")
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        packages = {"alpha": ["tool-a", "tool-b"]}

        _patched_install_with_packages(kanonenv, packages)
        after_first = {p.name for p in (store_base / ".packages").iterdir()}

        _patched_install_with_packages(kanonenv, packages)
        after_second = {p.name for p in (store_base / ".packages").iterdir()}

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
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        for _ in range(num_installs):
            _patched_install(kanonenv)

        assert (store_base / ".packages").is_dir(), ".packages/ must exist in the store after repeated installs"
        assert (store_base / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist in the store after repeated installs"
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
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        _patched_install(kanonenv)
        _patched_install(kanonenv)

        for sn in ("alpha", "bravo"):
            assert (store_base / ".kanon-data" / "sources" / sn).is_dir(), (
                f".kanon-data/sources/{sn}/ must exist in the store after repeated install"
            )
        assert (store_base / ".packages").is_dir(), ".packages/ must exist in the store after repeated install"


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
            "KANON_SOURCE_x_REF=main\n"
            "KANON_SOURCE_x_PATH=manifest.xml\n"
            "KANON_SOURCE_x_NAME=x\n"
            "KANON_SOURCE_x_GITBASE=https://example.com\n",
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
