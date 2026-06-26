"""J7 -- KANON_HOME shared-store journey (spec Section 10.4 / FR-15, FR-16).

Exercises the content-addressed store end to end:

- Two project directories sharing one ``KANON_HOME`` install the same
  ``manifest@SHA`` and dedup to a single content-addressed store entry.
- A publish is concurrency-safe under real contention: two processes publishing
  the same address race for a per-entry lock and the loser observes the winner's
  fully-published entry (readiness via final-path existence, never a sleep).
- A conditional ``.gitignore`` safety net is written into the store only when the
  resolved ``KANON_HOME`` sits inside a git working tree.

All assertions are real and falsifiable; there is no ``skipif`` and no
time-based synchronisation anywhere in this module.
"""

import multiprocessing
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.constants import KANON_HOME_STORE_GITIGNORE_ENTRY
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    compute_store_entry_address,
    install,
    publish_store_entry,
    store_entries_dir,
)


_SOURCE_URL = "https://example.com/build.git"
_SOURCE_SHA = "a" * 40

_KANONENV = (
    f"KANON_SOURCE_build_URL={_SOURCE_URL}\n"
    "KANON_SOURCE_build_REF=main\n"
    "KANON_SOURCE_build_PATH=meta.xml\n"
    "KANON_SOURCE_build_NAME=build\n"
    "KANON_SOURCE_build_GITBASE=https://example.com\n"
)


def _write_kanonenv(project_dir: pathlib.Path) -> pathlib.Path:
    """Create a project dir with a minimal single-source ``.kanon`` and return it."""
    project_dir.mkdir(parents=True, exist_ok=True)
    kanonenv = project_dir / ".kanon"
    kanonenv.write_text(_KANONENV, encoding="utf-8")
    return kanonenv


_PAYLOAD = {"first": "1", "second": "2"}


def _contended_publish_worker(store_str: str, address: str, ready_barrier, error_queue) -> None:
    """Publish ``address`` into the store; run in a separate process for real contention.

    Both worker processes wait on ``ready_barrier`` so they attempt the publish
    at the same instant, forcing genuine cross-process contention on the
    per-entry lock. Each process is its own interpreter, so the per-process
    re-entrance guard and the SIGALRM-based lock timeout (main-thread only) both
    apply correctly. Any exception is reported back through ``error_queue``.
    """
    store = pathlib.Path(store_str)

    def materialize(dest: pathlib.Path) -> None:
        for name, content in _PAYLOAD.items():
            (dest / name).write_text(content, encoding="utf-8")

    try:
        ready_barrier.wait()
        publish_store_entry(store, address, materialize)
    except BaseException as exc:
        error_queue.put(f"{type(exc).__name__}: {exc}")


def _install_project(project_dir: pathlib.Path) -> None:
    """Run ``install`` against ``project_dir`` with the repo sub-commands patched.

    ``repo init/envsubst/sync`` and the ref resolver are patched so the journey
    is deterministic and offline; the store-publish path (atomic rename +
    per-entry lock + conditional .gitignore) runs unpatched against the real
    filesystem.
    """
    from kanon_cli.core.install import _RefResolution

    kanonenv = _write_kanonenv(project_dir)
    lock_path = project_dir / ".kanon.lock"
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch(
            "kanon_cli.core.install._resolve_ref_to_sha",
            return_value=_RefResolution(sha=_SOURCE_SHA, resolved_ref="refs/heads/main"),
        ),
        patch(
            "kanon_cli.core.install._walk_includes",
            return_value=IncludeTree(path=pathlib.Path("meta.xml")),
        ),
    ):
        install(kanonenv, lock_file_path=lock_path)


@pytest.mark.functional
class TestKanonHomeStoreJourney:
    """J7: shared KANON_HOME store dedup, contention safety, conditional .gitignore."""

    def test_two_projects_dedup_to_one_store_entry(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two project dirs sharing one KANON_HOME publish a single store entry (dedup)."""
        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        _install_project(tmp_path / "project-a")
        _install_project(tmp_path / "project-b")

        entries_dir = store_entries_dir(store)
        published = sorted(p.name for p in entries_dir.iterdir() if p.is_dir())
        expected_address = compute_store_entry_address(_SOURCE_URL, _SOURCE_SHA)

        assert published == [expected_address], (
            f"two installs of the same manifest@SHA must dedup to one store entry; got {published}"
        )

    def test_per_entry_lock_and_atomic_publish_under_contention(self, tmp_path: pathlib.Path) -> None:
        """Two processes publish one address concurrently; the loser sees the winner's entry.

        Real cross-process contention: both worker processes wait on a shared
        barrier, then race for the per-entry lock. Readiness is final-path
        existence -- the loser either materializes the entry itself or observes
        the winner's already-published entry. The published entry must be
        complete (the atomic rename means the partial temp dir never becomes the
        final entry). No sleep is used anywhere; the per-entry lock serialises the
        two processes at the kernel level.
        """
        store = tmp_path / "store"
        store.mkdir()
        address = compute_store_entry_address(_SOURCE_URL, _SOURCE_SHA)

        ctx = multiprocessing.get_context("spawn")
        ready_barrier = ctx.Barrier(2)
        error_queue: multiprocessing.Queue = ctx.Queue()
        workers = [
            ctx.Process(
                target=_contended_publish_worker,
                args=(str(store), address, ready_barrier, error_queue),
            )
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        errors = []
        while not error_queue.empty():
            errors.append(error_queue.get())
        assert errors == [], f"no publish process may fail: {errors}"
        assert all(worker.exitcode == 0 for worker in workers), (
            f"both publish processes must exit 0; got {[w.exitcode for w in workers]}"
        )

        final_path = store_entries_dir(store) / address
        assert final_path.is_dir(), "the content-addressed entry must be published exactly once"

        for name, content in _PAYLOAD.items():
            assert (final_path / name).read_text(encoding="utf-8") == content
        published = [p.name for p in store_entries_dir(store).iterdir() if p.is_dir()]
        assert published == [address], f"contention must still yield exactly one entry; got {published}"

        tmp_root = store / ".tmp"
        leftover = list(tmp_root.iterdir()) if tmp_root.exists() else []
        assert leftover == [], f"no partial temp dir may survive a publish: {leftover}"

    def test_conditional_gitignore_written_inside_git_repo(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .gitignore safety net is written into the store only when KANON_HOME is in a git repo."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        kanon_home = repo_root / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        _install_project(tmp_path / "project-in-repo")

        gitignore = store / ".gitignore"
        assert gitignore.is_file(), "a .gitignore must be written when KANON_HOME is inside a git repo"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        assert KANON_HOME_STORE_GITIGNORE_ENTRY in lines, (
            "the whole-store ignore entry must be present when KANON_HOME is inside a git repo"
        )

    def test_no_whole_store_ignore_when_kanon_home_outside_git_repo(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole-store ignore entry is NOT written when KANON_HOME is not inside a git repo."""
        kanon_home = tmp_path / "plain_home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        assert not any((parent / ".git").exists() for parent in [store, *store.parents]), (
            "test setup invariant: the store must not sit inside a git repo"
        )

        _install_project(tmp_path / "project-plain")

        gitignore = store / ".gitignore"
        if gitignore.exists():
            lines = gitignore.read_text(encoding="utf-8").splitlines()
            assert KANON_HOME_STORE_GITIGNORE_ENTRY not in lines, (
                "the whole-store ignore safety net must not be written outside a git repo"
            )
