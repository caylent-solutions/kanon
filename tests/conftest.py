"""Shared fixtures for kanon-cli tests."""

from __future__ import annotations

import ast
import contextlib
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Generator

import pytest

from kanon_cli.constants import KANON_PERMITTED_ABS_ROOTS_ENV, KANON_SYNC_JOBS_ENV


_TMP_ROOT_ENV = "KANON_TEST_TMP_ROOT"
_TMP_ROOT_DEFAULT = "/var/tmp/kanon-test-runs"
_KEEP_TMP_ENV = "KANON_TEST_KEEP_TMP"
_XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"
_TEMP_VARS = ("TMPDIR", "TMP", "TEMP")

_SYNC_JOBS_DEFAULT = "1"

_TEST_TIMEOUT_ENV = "KANON_TEST_TIMEOUT"
_TEST_TIMEOUT_DEFAULT = "600"
_PYTEST_TIMEOUT_ENV = "PYTEST_TIMEOUT"
_TIMEOUT_PLUGIN_NAME = "timeout"

_SUBPROCESS_TIMEOUT_ENV = "KANON_TEST_SUBPROCESS_TIMEOUT"
_SUBPROCESS_TIMEOUT_DEFAULT = "300"

_PROCESS_LEAK_EXIT_CODE = 70
"""Session exit status when a spawned process outlived the tests.

Outside pytest's reserved 0-5 range: 4 is pytest's own USAGE_ERROR, so CI could
not tell "processes leaked" from "the command line was wrong".
"""

_PROCESS_KILL_GRACE_ENV = "KANON_TEST_PROCESS_KILL_GRACE"
_PROCESS_KILL_GRACE_DEFAULT = "5"
_PROCESS_KILL_POLL_SECONDS = 0.05
_PROCESS_SCAN_TIMEOUT_SECONDS = 30.0
_PS_SCAN_COMMAND = ("ps", "-ww", "-eo", "pid=,pgid=,command=")


def _reap_dead_run_roots(parent: pathlib.Path) -> None:
    """Remove managed ``run-<pid>-*`` roots whose owning process is no longer alive.

    Recovers space leaked by a previously interrupted or killed run without ever
    touching a concurrently live run (its pid still exists), so it is safe to call
    while another test session is in progress.
    """
    if not parent.is_dir():
        return
    for child in parent.glob("run-*"):
        pid = next((int(part) for part in child.name.split("-") if part.isdigit()), None)
        if pid is None:
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(child, ignore_errors=True)
        except PermissionError:
            continue


def _positive_int_env(var: str, default: str) -> int:
    """Return *var* from the environment as a positive integer, falling back to *default*.

    Raises:
        RuntimeError: When the variable is present but is not a positive integer.
    """
    raw = os.environ.get(var, default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{var} must be a positive integer number of seconds, got: {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{var} must be a positive integer number of seconds, got: {value}")
    return value


def subprocess_timeout() -> int:
    """Return the deadline, in seconds, for a single ``kanon`` subprocess under test.

    Every shared subprocess helper passes this to ``subprocess.run(timeout=...)`` so
    a wedged child is killed and surfaced as a ``TimeoutExpired`` naming the command,
    instead of blocking its pytest worker forever. Tuned with
    ``KANON_TEST_SUBPROCESS_TIMEOUT``; it must stay below ``KANON_TEST_TIMEOUT`` so the
    subprocess deadline (which reports the child's command line) fires before the
    coarser per-test backstop kills the whole worker.

    Raises:
        RuntimeError: When ``KANON_TEST_SUBPROCESS_TIMEOUT`` is not a positive integer.
    """
    return _positive_int_env(_SUBPROCESS_TIMEOUT_ENV, _SUBPROCESS_TIMEOUT_DEFAULT)


_SPAWNED_PROCESS_GROUPS: set[int] = set()
"""Process groups this suite created, so the leak scan only judges its own work.

Scanning by *this* process's group flagged anything sharing it, and matching on
argv alone flagged any command line that merely mentions a kanon invocation --
including the shell running the test command. Both produced false positives on a
real session. Recording what the suite actually started removes the guesswork.
"""


def register_spawned_process_group(pgid: int) -> None:
    """Record a process group the suite created.

    Args:
        pgid: The group id, which equals the child's pid when it was spawned with
            ``start_new_session=True``.
    """
    _SPAWNED_PROCESS_GROUPS.add(pgid)


def run_owned_subprocess(argv: "list[str]", **kwargs: object) -> "subprocess.CompletedProcess":
    """Run *argv* in its own process group and register it for leak detection.

    ``subprocess.run(timeout=...)`` kills only the direct child. The processes this
    suite actually leaks are its grandchildren -- ``repo sync`` pool workers parked
    in ``sem_wait()`` -- which survive their parent and are never reaped. Putting
    the child in a new process group makes the whole subtree addressable, so a
    timeout can signal all of it and the leak scan can recognise it as ours.

    Args:
        argv: The command to run.
        **kwargs: Passed through to :func:`subprocess.run`.

    Returns:
        The completed process.

    Raises:
        subprocess.TimeoutExpired: When the child exceeds its deadline. The whole
            process group is signalled before this propagates.
    """
    kwargs.setdefault("start_new_session", True)
    timeout = kwargs.pop("timeout", None)
    kwargs.pop("check", None)
    if kwargs.pop("capture_output", False):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    with subprocess.Popen(argv, **kwargs) as child:
        register_spawned_process_group(child.pid)
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_group(child.pid)
            child.kill()
            stdout, stderr = child.communicate()
            raise
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)


def _terminate_process_group(pgid: int) -> None:
    """Signal a whole process group, escalating only if it does not go quietly.

    Args:
        pgid: The group to signal.
    """
    deadline = _positive_int_env(_PROCESS_KILL_GRACE_ENV, _PROCESS_KILL_GRACE_DEFAULT)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGTERM)
    waited = 0.0
    while waited < deadline:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(_PROCESS_KILL_POLL_SECONDS)
        waited += _PROCESS_KILL_POLL_SECONDS
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def _leaked_kanon_processes(pgid: int) -> list[tuple[int, str]]:
    """Return every surviving ``kanon`` process in process group *pgid*.

    A ``kanon install`` that deadlocks -- or whose pytest worker died before it
    could be reaped -- keeps running after the session ends, reparented to init but
    still carrying the process group it was spawned into.

    *pgid* must be a group this suite created and registered, never the running
    process's own group. Scanning the latter judged every process that happened to
    share it: under a non-interactive shell, ``make``, or a CI step, no new groups
    are created, so that is everything. Combined with argv matching -- which is
    satisfied by any command line merely *mentioning* a kanon invocation, including
    the shell running the test command -- it flagged and killed processes the suite
    never started. That is not hypothetical; it happened while this branch was
    being developed.

    ``-ww`` is required, not cosmetic. procps truncates the command column to the
    terminal width -- 80 when stdout is not a tty, as in CI -- which silently cut
    the trailing ``-m kanon_cli`` off every candidate on Linux and made this scan
    report a clean session for a machine full of leaked processes. BSD ``ps`` does
    not truncate a non-tty, so the defect was invisible on macOS.

    That failure mode is the reason for the self-check below: a scan that cannot
    see must say so rather than return an empty list, which is indistinguishable
    from success. If this process is missing from ``ps``'s own output then the
    listing is not what this parser assumes, and reporting "no leaks" would be a
    guess.

    Args:
        pgid: The process group to scan.

    Returns:
        ``(pid, command)`` pairs for each surviving process, in ``ps`` order.

    Raises:
        RuntimeError: When ``ps`` is unavailable, exits non-zero, or returns a
            listing this parser cannot make sense of -- so the check fails loudly
            rather than silently reporting a clean session.
    """
    try:
        listing = subprocess.run(
            _PS_SCAN_COMMAND,
            capture_output=True,
            text=True,
            check=True,
            timeout=_PROCESS_SCAN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Unable to scan for leaked kanon processes: {exc}") from exc

    own_pid = os.getpid()
    seen_own_pid = False
    leaked: list[tuple[int, str]] = []
    for line in listing.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 3:
            continue
        pid_text, pgid_text, command = fields
        if not pid_text.isdigit() or not pgid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == own_pid:
            seen_own_pid = True
            continue
        if int(pgid_text) != pgid:
            continue
        if _is_kanon_command(command):
            leaked.append((pid, command))

    if not seen_own_pid:
        raise RuntimeError(
            f"Scanning for leaked kanon processes did not find this process "
            f"(pid {own_pid}) in the output of {' '.join(_PS_SCAN_COMMAND)!r}. The listing "
            f"is not in the expected 'pid pgid command' form, so an empty result would "
            f"mean 'cannot see' rather than 'nothing leaked'."
        )
    return leaked


def _is_kanon_command(command: str) -> bool:
    """Return True when *command* is a ``kanon`` CLI invocation rather than a test runner."""
    argv = command.split()
    if not argv:
        return False
    if pathlib.Path(argv[0]).name == "kanon":
        return True
    return any(argv[index] == "-m" and argv[index + 1] == "kanon_cli" for index in range(len(argv) - 1))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the session when a ``kanon`` subprocess outlived the tests that spawned it.

    A leaked child is the observable signature of the deadlock this suite guards
    against: the CLI's ``repo sync`` pool blocks in ``sem_wait()`` while its parent
    blocks in ``waitpid()``, so both sit at 0% CPU indefinitely and accumulate across
    runs. Detecting it here turns a silent resource leak into a red build.

    Only the process groups this suite registered are scanned, so a developer's
    unrelated ``kanon``, a second concurrent pytest session, or the shell running
    the tests cannot be mistaken for a leak.

    Survivors are signalled with SIGTERM and then SIGKILL, so a process with a
    handler gets the chance to exit cleanly. A kill that *fails* is reported rather
    than suppressed: claiming processes "were killed" while they are still running
    is the silent failure this check exists to prevent.

    Only the xdist controller runs the scan -- workers would otherwise flag each
    other's still-running children.
    """
    if os.environ.get(_XDIST_WORKER_ENV):
        return
    leaked: list[tuple[int, str]] = []
    for spawned_pgid in sorted(_SPAWNED_PROCESS_GROUPS):
        leaked.extend(_leaked_kanon_processes(spawned_pgid))
    if not leaked:
        return

    survivors: list[tuple[int, str, str]] = []
    for pid, command in leaked:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            survivors.append((pid, command, str(exc)))

    for pid, command in leaked:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)

    detail = "\n".join(f"  pid {pid}: {command}" for pid, command in leaked)
    message = (
        f"\nERROR: {len(leaked)} kanon subprocess(es) outlived the test session:\n"
        f"{detail}\n"
        f"A test spawned a kanon process that never exited. Check that the spawning helper "
        f"passes timeout= and that {KANON_SYNC_JOBS_ENV} is set, then re-run."
    )
    if survivors:
        unkilled = "\n".join(f"  pid {pid}: {reason}" for pid, _command, reason in survivors)
        message += (
            f"\n{len(survivors)} of them could NOT be killed and are still running:\n{unkilled}\n"
            f"Reap them by hand; the machine is dirtier than this session found it."
        )
    print(message, file=sys.stderr)

    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = _PROCESS_LEAK_EXIT_CODE


def pytest_configure(config: pytest.Config) -> None:
    """Point every test temp at a managed, real-filesystem run root.

    The kanon store and the vendored repo tool rely on gitlinks plus atomic
    renames that do not work on the orbstack workspace mount (fuseblk), and the
    default ``/tmp`` is a small tmpfs. So pytest's basetemp, ``tmp_path``,
    ``tmp_path_factory``, the OS tempdir that source ``tempfile.mkdtemp`` and git
    use, and any ``python -m kanon_cli`` subprocess are all redirected to a per-run
    directory under ``KANON_TEST_TMP_ROOT`` (default ``/var/tmp/kanon-test-runs``,
    an env-overridable real filesystem). The whole run root is removed in
    :func:`pytest_unconfigure`, so nothing accumulates across runs and ``/tmp`` is
    never touched. Stale roots from a crashed prior run are reaped on startup by
    dead-pid detection. Under xdist only the controller creates the root; workers
    inherit ``TMPDIR`` and ``--basetemp`` from it.

    Also refuses to run without ``pytest-timeout``. The per-test deadline is the only
    thing standing between a deadlocked ``kanon`` subprocess and a worker that hangs
    until the CI job's own limit expires, so a toolchain that resolved the plugin away
    must fail loudly at startup rather than run unprotected.
    """
    if not config.pluginmanager.hasplugin(_TIMEOUT_PLUGIN_NAME):
        raise pytest.UsageError(
            "pytest-timeout is not installed, so tests would run without a per-test deadline. "
            "Install the dev dependencies (`make install-dev`, or `uv sync`) and re-run."
        )
    if os.environ.get(_XDIST_WORKER_ENV):
        return
    parent = pathlib.Path(os.environ.get(_TMP_ROOT_ENV, _TMP_ROOT_DEFAULT))
    parent.mkdir(parents=True, exist_ok=True)
    _reap_dead_run_roots(parent)
    run_root = parent / f"run-{os.getpid()}-{os.urandom(4).hex()}"
    run_root.mkdir(parents=True, exist_ok=True)
    for var in _TEMP_VARS:
        os.environ[var] = str(run_root)
    tempfile.tempdir = None
    if getattr(config.option, "basetemp", None) is None:
        config.option.basetemp = str(run_root / "pytest")
    config._kanon_run_root = str(run_root)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the managed run root at session end unless ``KANON_TEST_KEEP_TMP`` is set."""
    if os.environ.get(_KEEP_TMP_ENV) or os.environ.get(_XDIST_WORKER_ENV):
        return
    root = getattr(config, "_kanon_run_root", None)
    if root:
        shutil.rmtree(root, ignore_errors=True)


def _isolation_env() -> dict[str, str]:
    """Return the mandatory temp and home env floor for kanon/git subprocesses.

    A caller that passes a full replacement environment to a subprocess would
    otherwise drop ``TMPDIR``/``KANON_HOME``/``CLAUDE_CONFIG_DIR`` and let the
    child's ``tempfile.mkdtemp``, the real ``~/.kanon-home`` store, and the real
    ``~/.claude`` config escape the per-test isolation. Subprocess helpers overlay
    this floor so the isolation cannot be bypassed.
    """
    floor: dict[str, str] = {}
    for var in (*_TEMP_VARS, "KANON_HOME", "CLAUDE_CONFIG_DIR", _TMP_ROOT_ENV, KANON_SYNC_JOBS_ENV):
        value = os.environ.get(var)
        if value is not None:
            floor[var] = value
    return floor


_SUBPROCESS_COVERAGE_ENV_VARS: tuple[str, ...] = (
    "COV_CORE_SOURCE",
    "COV_CORE_CONFIG",
    "COV_CORE_DATAFILE",
    "COV_CORE_CONTEXT",
    "COVERAGE_PROCESS_START",
    "COVERAGE_PROCESS_CONFIG",
)


def strip_subprocess_coverage_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of *env* with coverage subprocess-measurement triggers removed.

    Under ``pytest --cov`` (e.g. ``make test``) pytest-cov and coverage export
    ``COV_CORE_*`` / ``COVERAGE_PROCESS_*`` so that spawned subprocesses auto-start
    coverage. A measured ``kanon`` subprocess then writes a ``.coverage-data``
    directory into its working directory -- resolved relative to the child's CWD
    on some filesystems -- which behavioural tests that inspect the child's
    filesystem (``kanon repo status --orphans``) or parse its stderr
    (``--telemetry-debug`` JSON) then trip over, non-deterministically across
    OS / filesystem. These behavioural subprocess tests do not need coverage of
    the child (the coverage gate is measured in-process on the unit tier), so the
    functional and scenario subprocess runners overlay this on the child's
    environment to keep the child deterministic without disturbing the parent
    worker's already-started in-process coverage.

    Args:
        env: The environment mapping destined for ``subprocess.run``.

    Returns:
        A shallow copy of *env* with the coverage subprocess variables removed.
    """
    cleaned = dict(env)
    for name in _SUBPROCESS_COVERAGE_ENV_VARS:
        cleaned.pop(name, None)
    return cleaned


@contextlib.contextmanager
def managed_repo_dir(tmp_path_factory: pytest.TempPathFactory, name: str) -> Generator[pathlib.Path, None, None]:
    """Yield a fresh ``tmp_path_factory`` dir and remove it on teardown.

    Session and module scoped fixtures that build real git repositories use this
    so the inode-heavy git objects are reaped promptly instead of persisting for
    the whole session inside the run root.
    """
    base = tmp_path_factory.mktemp(name)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


_TEXT_IO_METHODS = ("read_text", "write_text")


def bare_text_io_calls(source_path: pathlib.Path) -> list[tuple[int, str]]:
    """Return every bare ``.read_text()`` / ``.write_text()`` callsite in a source file.

    Parses the Python source at ``source_path`` and walks its AST for calls to
    the ``read_text`` / ``write_text`` ``pathlib.Path`` methods that do NOT pass
    an explicit ``encoding=`` keyword argument. Those bare callsites adopt the
    platform default encoding and so behave differently on Windows, which the
    utf-8 encoding sweep (AC-12 / FR-38) forbids for kanon's own source under
    ``src/kanon_cli/`` (the vendored ``repo/`` tree is out of scope).

    This is the single shared source of truth for the encoding-sweep unit tests
    (``test_add.py``, ``test_cache.py``, ``test_cached_catalogs.py``,
    ``test_install.py``); each test imports this helper rather than inlining its
    own AST walker (DRY).

    Args:
        source_path: Path to the Python source file to scan.

    Returns:
        A list of ``(lineno, method_name)`` tuples, one per bare callsite, in
        source order. ``method_name`` is ``"read_text"`` or ``"write_text"``.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    bare: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _TEXT_IO_METHODS:
            continue
        has_encoding = any(kw.arg == "encoding" for kw in node.keywords)
        if not has_encoding:
            bare.append((node.lineno, func.attr))
    return bare


MINIMAL_KANONENV = (
    "KANON_SOURCE_s_URL=https://example.com/s.git\n"
    "KANON_SOURCE_s_REF=main\n"
    "KANON_SOURCE_s_PATH=m.xml\n"
    "KANON_SOURCE_s_NAME=s\n"
    "KANON_SOURCE_s_GITBASE=https://example.com\n"
)


DEFAULT_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"


def write_kanonenv(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(MINIMAL_KANONENV)
    return kanonenv


def write_manifest_for_sync(directory: pathlib.Path, sub_path: str = "repo-specs/manifest.xml") -> pathlib.Path:
    """Write a minimal valid XML manifest at the repo-tool layout path inside directory.

    After ``repo init`` + ``repo sync``, manifest files live under
    ``directory/.repo/manifests/<sub_path>``.  This helper creates that directory
    structure and writes the smallest well-formed manifest that satisfies the XML
    include-walker, avoiding per-test duplication of the mkdir + write_text pattern.

    Tests that mock ``repo_init`` or ``repo_sync`` must call this helper so that
    ``install()``'s include-walker can find the manifest at the expected location.

    Args:
        directory: The source workspace directory (the path passed by install() to
            repo_init / repo_sync as ``repo_dir``).
        sub_path: Manifest path relative to the manifests repo root, matching the
            ``KANON_SOURCE_<name>_PATH`` value in the ``.kanon`` file.  Defaults
            to ``"repo-specs/manifest.xml"``.

    Returns:
        Absolute path to the written manifest file.

    Example::

        def fake_repo_init(repo_dir: str, url: str, revision: str,
                           manifest_path: str, repo_rev: str = "") -> None:
            write_manifest_for_sync(pathlib.Path(repo_dir), sub_path=manifest_path)
    """
    manifest = directory / ".repo" / "manifests" / sub_path
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<manifest></manifest>\n')
    return manifest


def materialize_linkfiles_for_sync(repo_dir: pathlib.Path) -> None:
    """Perform the ``<linkfile>`` step of ``repo sync`` for a mocked sync.

    ``repo sync`` materializes every ``<linkfile>`` in the manifest as a symlink
    at ``dest`` targeting ``src``.  A test that replaces ``repo_sync`` with a
    no-op therefore leaves a workspace that a real sync would never produce, and
    any assertion about what reached a ``dest`` path is then an assertion about
    the double rather than about ``kanon``.

    Use this as the ``side_effect`` of a patched ``kanon_cli.repo.repo_sync``
    whenever the test asserts on a linkfile destination::

        patch(
            "kanon_cli.repo.repo_sync",
            side_effect=lambda repo_dir, **kwargs: materialize_linkfiles_for_sync(
                pathlib.Path(repo_dir)
            ),
        )

    Linking is delegated to the production :class:`kanon_cli.repo.project._LinkFile`
    so the double cannot drift from what ``repo`` actually does.

    Args:
        repo_dir: The source workspace directory that ``install()`` passes to
            ``repo_sync``; manifests are read from ``repo_dir/.repo/manifests``
            and project checkouts are resolved relative to ``repo_dir``.

    Raises:
        xml.etree.ElementTree.ParseError: If a manifest XML is malformed.
        OSError: If a symlink cannot be created.
    """
    from kanon_cli.repo.project import _LinkFile

    for manifest in sorted((repo_dir / ".repo" / "manifests").rglob("*.xml")):
        for project_el in ET.parse(str(manifest)).getroot().findall("project"):
            project_path = project_el.get("path") or project_el.get("name", "")
            if not project_path:
                continue
            worktree = repo_dir / project_path

            for linkfile_el in project_el.findall("linkfile"):
                src = linkfile_el.get("src", "")
                dest = linkfile_el.get("dest", "")
                if not src or not dest:
                    continue
                _LinkFile(
                    str(worktree),
                    src,
                    str(repo_dir),
                    dest,
                    exclude=linkfile_el.get("exclude"),
                )._Link()


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"


def _install_process_env_floor() -> None:
    """Apply the session-wide environment floor, at import, before any hook runs.

    ``REPO_TRACE`` silences the vendored repo tool's trace output.

    ``KANON_SYNC_JOBS`` pins ``repo sync`` to a single process. Left at its default
    every ``kanon install`` fans out to ``min(cpu_count, 8)`` pool workers, and a
    ``pytest-xdist`` run multiplies that by the worker count until a hundred-odd
    processes contend for the same POSIX semaphores; the pool then blocks in
    ``sem_wait()`` while its parent blocks in ``waitpid()`` and neither ever wakes.
    Pinning to ``1`` takes the single-process short-circuit in ``repo.command``, so
    no pool is built and the deadlock has nothing to form around.

    ``PYTEST_TIMEOUT`` is pytest-timeout's own variable and is derived from
    ``KANON_TEST_TIMEOUT``, keeping every tunable in this suite under one prefix.
    It is set here rather than in :func:`pytest_configure` because pytest-timeout
    reads the environment from its own ``pytest_configure``, and hook ordering
    between two plugins is not something to depend on.

    Every entry uses ``setdefault``, so an operator who exports any of these keeps
    their value.
    """
    os.environ.setdefault("REPO_TRACE", "0")
    os.environ.setdefault(KANON_SYNC_JOBS_ENV, _SYNC_JOBS_DEFAULT)
    os.environ.setdefault(_PYTEST_TIMEOUT_ENV, str(_positive_int_env(_TEST_TIMEOUT_ENV, _TEST_TIMEOUT_DEFAULT)))


_install_process_env_floor()


@pytest.fixture(scope="session", autouse=True)
def _subprocess_pythonpath_points_at_source_tree() -> None:
    """Ensure subprocesses spawned by tests import kanon_cli from the current source tree.

    Several test helpers invoke the CLI in a subprocess via
    ``[sys.executable, "-m", "kanon_cli", ...]``. The child Python resolves
    ``import kanon_cli`` against its own site-packages, which in some
    development environments contains a stale ``kanon_cli`` version. Prepending
    the source tree to ``PYTHONPATH`` makes ``import kanon_cli`` in the child
    resolve to the current source regardless of which venv pytest runs in.

    The fixture is session-scoped and autouse so every spawned subprocess
    inherits the modified environment without per-test opt-in.
    """
    existing = os.environ.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    entries = [src_str] + [p for p in existing.split(os.pathsep) if p and p != src_str]
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)


@pytest.fixture()
def sample_kanonenv(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a sample two-source .kanon file."""
    kanonenv = tmp_path / ".kanon"
    kanonenv.write_text(
        "REPO_URL=https://example.com/org/repo-tool.git\n"
        "REPO_REV=v2.0.0\n"
        "GITBASE=https://example.com/org/\n"
        "CLAUDE_MARKETPLACES_DIR=.claude-marketplaces\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        "KANON_SOURCE_build_URL=https://example.com/org/build-repo.git\n"
        "KANON_SOURCE_build_REF=main\n"
        "KANON_SOURCE_build_PATH=repo-specs/common/meta.xml\n"
        "KANON_SOURCE_build_NAME=build\n"
        "KANON_SOURCE_build_GITBASE=https://example.com/org\n"
        "KANON_SOURCE_marketplaces_URL=https://example.com/org/mp-repo.git\n"
        "KANON_SOURCE_marketplaces_REF=main\n"
        "KANON_SOURCE_marketplaces_PATH=repo-specs/common/marketplaces.xml\n"
        "KANON_SOURCE_marketplaces_NAME=marketplaces\n"
        "KANON_SOURCE_marketplaces_GITBASE=https://example.com/org\n"
    )
    return kanonenv


@pytest.fixture()
def mock_git_ls_remote_output() -> str:
    """Sample git ls-remote --tags output."""
    return (
        "abc123\trefs/tags/1.0.0\n"
        "def456\trefs/tags/1.0.1\n"
        "ghi789\trefs/tags/1.1.0\n"
        "jkl012\trefs/tags/2.0.0\n"
        "mno345\trefs/tags/2.0.0^{}\n"
    )


def _make_minimal_kanon_file(tmp_path: pathlib.Path, source_name: str = "FOO") -> pathlib.Path:
    """Write a minimal .kanon file with a single source and return its path.

    Shared by unit tests (test_why_ambiguity.py) and integration tests
    (test_why_ambiguous.py) to avoid cross-layer imports.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(
        f"GITBASE=https://github.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mkts\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://github.com/org/catalog\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=./foo\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://github.com/org\n"
    )
    kanon_file.chmod(0o644)
    return kanon_file


def _write_lockfile(
    tmp_path: pathlib.Path, source_name: str, project_url: str, include_path: str | None = None
) -> pathlib.Path:
    """Write a minimal lockfile with one source, one project, and optionally one include.

    Shared by unit tests (test_why_ambiguity.py) and integration tests
    (test_why_ambiguous.py) to avoid cross-layer imports.
    """
    from kanon_cli.core.lockfile import (
        CURRENT_SCHEMA_VERSION,
        IncludeEntry,
        Lockfile,
        ProjectEntry,
        SourceEntry,
        write_lockfile,
    )
    from kanon_cli.core.url import canonicalize_repo_url

    includes = []
    if include_path:
        includes = [
            IncludeEntry(
                name="inc",
                path_in_repo=include_path,
                url="https://github.com/org/catalog",
                resolved_sha="c" * 40,
                includes=[],
            )
        ]

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        sources=[
            SourceEntry(
                alias=source_name,
                name=source_name,
                url="https://github.com/org/catalog",
                ref_spec="main",
                resolved_ref="main",
                resolved_sha="a" * 40,
                path="./foo",
                includes=includes,
                projects=[
                    ProjectEntry(
                        name="proj",
                        url=project_url,
                        canonical_url=canonicalize_repo_url(project_url),
                        ref_spec="main",
                        resolved_ref="main",
                        resolved_sha="b" * 40,
                    )
                ],
            )
        ],
    )

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


DOCTOR_MINIMAL_KANON_CONTENT = (
    "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
    "KANON_SOURCE_src_REF=main\n"
    "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
    "KANON_SOURCE_src_NAME=src\n"
    "KANON_SOURCE_src_GITBASE=https://example.com/org\n"
    "KANON_MARKETPLACE_INSTALL=false\n"
)


def write_kanon_doctor_unit(
    tmp_path: pathlib.Path,
    content: str = DOCTOR_MINIMAL_KANON_CONTENT,
) -> pathlib.Path:
    """Write a .kanon file for doctor unit tests and chmod 0o644.

    Used by tests/unit/test_doctor_consistency.py to build minimal workspaces
    for subcheck unit tests. The content parameter lets callers supply custom
    source definitions (e.g. SHA-pinned sources for dangling-SHA checks).

    Args:
        tmp_path: Directory in which to create the .kanon file.
        content: Full text of the .kanon file.

    Returns:
        Path to the written .kanon file.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(content, encoding="utf-8")
    kanon_file.chmod(0o644)
    return kanon_file


def write_lockfile_doctor_unit(
    tmp_path: pathlib.Path,
    kanon_hash_val: str = "sha256:" + "a" * 64,
    source_names: list[str] | None = None,
    revision_specs: dict[str, str] | None = None,
    resolved_shas: dict[str, str] | None = None,
    urls: dict[str, str] | None = None,
) -> pathlib.Path:
    """Write a minimal .kanon.lock for doctor unit tests.

    Used by tests/unit/test_doctor_consistency.py. Supports multiple sources
    via the source_names, revision_specs, resolved_shas, and urls parameters.
    Defaults build a single source named 'src' with a branch-pinned revision
    (main) and a fake SHA.

    Args:
        tmp_path: Directory in which to write .kanon.lock.
        kanon_hash_val: Value to embed in the lockfile's kanon_hash field.
        source_names: Names of the sources to include. Defaults to ["src"].
        revision_specs: Per-source revision strings. Defaults to "main" for all.
        resolved_shas: Per-source resolved SHA. Defaults to "a" * 40 for all.
        urls: Per-source URL. Defaults to "https://example.com/org/repo.git" for all.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CURRENT_SCHEMA_VERSION,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    if source_names is None:
        source_names = ["src"]
    if revision_specs is None:
        revision_specs = {name: "main" for name in source_names}
    if resolved_shas is None:
        resolved_shas = {name: "a" * 40 for name in source_names}
    if urls is None:
        urls = {name: "https://example.com/org/repo.git" for name in source_names}

    sources = [
        SourceEntry(
            alias=name,
            name=name,
            url=urls[name],
            ref_spec=revision_specs[name],
            resolved_ref=revision_specs[name],
            resolved_sha=resolved_shas[name],
            path="repo-specs/meta.xml",
        )
        for name in source_names
    ]

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        sources=sources,
    )

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


def write_kanon_doctor_integration(
    directory: pathlib.Path,
    source_name: str,
    url: str,
    revision: str = "main",
) -> pathlib.Path:
    """Write a .kanon file for doctor integration tests.

    Used by tests/integration/test_doctor_consistency.py. Writes a single-source
    .kanon file suitable for subprocess-driven CLI tests.

    Args:
        directory: Directory in which to create the .kanon file.
        source_name: Name of the source (used in KANON_SOURCE_<name>_* keys).
        url: Git URL for the source.
        revision: Revision spec (branch name or SHA). Defaults to "main".

    Returns:
        Path to the written .kanon file.
    """
    kanon_file = directory / ".kanon"
    kanon_file.write_text(
        f"KANON_SOURCE_{source_name}_URL={url}\n"
        f"KANON_SOURCE_{source_name}_REF={revision}\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/meta.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com/org\n"
        "KANON_MARKETPLACE_INSTALL=false\n",
        encoding="utf-8",
    )
    kanon_file.chmod(0o644)
    return kanon_file


def write_lockfile_doctor_integration_multi_source(
    directory: pathlib.Path,
    kanon_hash_val: str,
    sources: list[dict],
) -> pathlib.Path:
    """Write a minimal .kanon.lock file for multiple sources (doctor integration tests).

    Shared helper used by tests/integration/test_doctor_consistency.py for test
    cases that require more than one source entry (e.g. orphan lock detection).

    Args:
        directory: Directory in which to write .kanon.lock.
        kanon_hash_val: The kanon_hash to embed in the lockfile.
        sources: List of dicts, each with keys: name, url, revision_spec, resolved_sha.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CURRENT_SCHEMA_VERSION,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    source_entries = [
        SourceEntry(
            alias=s["name"],
            name=s["name"],
            url=s["url"],
            ref_spec=s["revision_spec"],
            resolved_ref=s["revision_spec"],
            resolved_sha=s["resolved_sha"],
            path="repo-specs/meta.xml",
        )
        for s in sources
    ]

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        sources=source_entries,
    )
    lock_path = directory / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


def write_lockfile_doctor_integration(
    directory: pathlib.Path,
    kanon_hash_val: str,
    source_name: str,
    url: str,
    revision_spec: str,
    resolved_sha: str,
) -> pathlib.Path:
    """Write a minimal .kanon.lock for doctor integration tests.

    Used by tests/integration/test_doctor_consistency.py. Writes a single-source
    lockfile suitable for subprocess-driven CLI tests.

    Args:
        directory: Directory in which to write .kanon.lock.
        kanon_hash_val: Value to embed in the lockfile's kanon_hash field.
        source_name: Name of the single source entry.
        url: Git URL for the source.
        revision_spec: Revision spec string (branch name or SHA).
        resolved_sha: The resolved SHA to record for the source.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CURRENT_SCHEMA_VERSION,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        sources=[
            SourceEntry(
                alias=source_name,
                name=source_name,
                url=url,
                ref_spec=revision_spec,
                resolved_ref=revision_spec,
                resolved_sha=resolved_sha,
                path="repo-specs/meta.xml",
            )
        ],
    )
    lock_path = directory / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


@pytest.fixture(autouse=True)
def _scrub_catalog_source_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Clear KANON_CATALOG_SOURCES after every test function.

    Belt-and-suspenders teardown that unconditionally deletes
    KANON_CATALOG_SOURCES from os.environ after every test, regardless of
    whether the test or any of its fixtures set it. Prevents env-var leaks
    between tests when a fixture or test directly mutates os.environ without
    using monkeypatch (which would otherwise undo changes automatically).

    The fixture is function-scoped (the default) and autouse so it runs for
    every test in the suite without per-test opt-in.
    """
    yield
    monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)


@pytest.fixture(autouse=True)
def _isolate_kanon_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point KANON_HOME at a per-test temp dir so tests never touch the real ~/.kanon-home.

    The shared KANON_HOME store (spec Section 7.1 / Section 8 / FR-15) defaults to
    ``~/.kanon-home`` when KANON_HOME is unset. ``resolve_workspace_base_dir()`` (the
    artifact store, ``<KANON_HOME>/store``) and ``cache_dir()`` (the completion /
    catalog-audit cache, ``<KANON_HOME>/cache``) both resolve under it. Without
    isolation, every test that drives ``install`` / ``clean`` / completion caching
    would share a single real-home store and leak state between tests -- e.g. an
    end-to-end scenario reusing a prior test's repo checkout under
    ``~/.kanon-home/store/.kanon-data/sources/...``.

    This autouse fixture sets KANON_HOME to a fresh per-test temporary directory
    via ``monkeypatch.setenv`` (so it is reverted on teardown AND is inherited by
    any ``python -m kanon_cli`` subprocess the test spawns). Tests that need a
    specific KANON_HOME override it with their own ``monkeypatch.setenv`` /
    ``extra_env`` (which runs after this fixture and therefore wins); tests
    asserting the unset-default behaviour ``monkeypatch.delenv("KANON_HOME", ...)``
    likewise override it.
    """
    monkeypatch.setenv("KANON_HOME", str(tmp_path_factory.mktemp("kanon_home")))


@pytest.fixture(autouse=True)
def _isolate_claude_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point CLAUDE_CONFIG_DIR at a per-test temp dir so the real ~/.claude is never touched.

    A ``claude-marketplace`` install shells out to the real ``claude`` binary
    (``claude plugin marketplace add`` / ``plugin install`` in
    ``core/marketplace.py``); that subprocess inherits ``os.environ`` and reads
    its config from ``CLAUDE_CONFIG_DIR`` (falling back to ``~/.claude`` when
    unset). Without isolation a test that drives a real marketplace install would
    register marketplaces and plugins into the developer's real ``~/.claude``,
    each pointing at the test's temporary marketplace directory; once that temp
    directory is reaped the registrations dangle and surface as
    ``failed to load: cache-miss`` errors in Claude Code.

    This autouse fixture sets ``CLAUDE_CONFIG_DIR`` to a fresh per-test temporary
    directory (reverted on teardown via ``monkeypatch`` and inherited by every
    spawned ``claude`` and ``python -m kanon_cli`` subprocess), so marketplace
    registration is fully isolated. Tests that need a specific config override it
    with their own ``monkeypatch.setenv``.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("claude_config")))


@pytest.fixture()
def make_install_args():
    """Factory fixture that returns a MagicMock suitable for the install CLI handler.

    Returns a callable that accepts a kanonenv path and returns a MagicMock
    suitable for passing to the install CLI handler _run(args). This allows
    integration and functional tests to invoke the CLI boundary without
    duplicating the argparse namespace setup inline.

    ``kanon install`` is hermetic (spec Section 4.3 / FR-14): it is driven solely
    by the committed ``.kanon`` (+ ``.kanon.lock``), accepts no catalog source, and
    ignores ``KANON_CATALOG_SOURCES``.  The factory therefore sets only the
    attributes the install handler actually reads (path, lock file, and the
    refresh / strict flags).

    Args: (none -- use the returned factory)

    Returns:
        A factory function that accepts kanonenv_path (Path) and returns a
        MagicMock with kanonenv_path, lock_file, and the install flags set.

    Example::

        def test_something(tmp_path, make_install_args):
            from kanon_cli.commands.install import _run
            kanonenv = tmp_path / ".kanon"
            kanonenv.write_text("...")
            args = make_install_args(kanonenv.resolve())
            with pytest.raises(SystemExit) as exc_info:
                _run(args)
            assert exc_info.value.code == 1
    """
    from unittest.mock import MagicMock

    def _factory(kanonenv_path: pathlib.Path) -> MagicMock:
        args = MagicMock()
        args.kanonenv_path = kanonenv_path
        args.lock_file = None
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        return args

    return _factory


@pytest.fixture()
def _set_default_catalog_source(monkeypatch: pytest.MonkeyPatch) -> str:
    """Opt-in fixture: sets KANON_CATALOG_SOURCES to DEFAULT_CATALOG_SOURCE for one test.

    This fixture is opt-in (no ``autouse=True``).  Tests that invoke code paths
    which read ``KANON_CATALOG_SOURCES`` from the environment (e.g. subprocess-
    based tests, or tests that call ``install()`` without passing the
    ``catalog_source`` keyword argument) can request this fixture by name to
    inject the standard test value (a single source) for the duration of that test.

    The autouse ``_scrub_catalog_source_env`` fixture clears ``KANON_CATALOG_SOURCES``
    after every test; this fixture sets it fresh via ``monkeypatch.setenv`` so it
    is automatically reverted by pytest's monkeypatch teardown in addition to
    the scrubber's ``delenv`` -- belt-and-suspenders isolation.

    Returns:
        The catalog source string that was set (``DEFAULT_CATALOG_SOURCE``), so
        callers can assert against the expected value if needed.

    Example::

        def test_install_via_env(tmp_path, _set_default_catalog_source):
            from kanon_cli.core.install import install
            kanonenv = tmp_path / ".kanon"
            kanonenv.write_text("KANON_SOURCE_s_URL=https://example.com/s.git\\n...")
            # KANON_CATALOG_SOURCES is already set by the fixture
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")
    """
    monkeypatch.setenv("KANON_CATALOG_SOURCES", DEFAULT_CATALOG_SOURCE)
    return DEFAULT_CATALOG_SOURCE


@pytest.fixture()
def permit_abs_roots(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that permits absolute manifest destinations under given roots.

    An absolute ``<linkfile>``/``<copyfile>`` dest is confined to the roots kanon
    publishes in ``KANON_PERMITTED_ABS_ROOTS``; outside a real install that variable
    is unset, so the vendored resolver fails closed. A test that exercises an
    absolute dest calls this with the root its destination lives under, which also
    documents that the containment boundary is what makes the destination legal.

    Example::

        def test_absolute_dest(tmp_path, permit_abs_roots):
            permit_abs_roots(tmp_path)

    Args:
        monkeypatch: pytest's environment patcher, so the value is undone per test.

    Returns:
        A callable taking one or more roots (``str`` or ``Path``).
    """

    def _permit(*roots: object) -> str:
        value = os.pathsep.join(str(root) for root in roots)
        monkeypatch.setenv(KANON_PERMITTED_ABS_ROOTS_ENV, value)
        return value

    return _permit
