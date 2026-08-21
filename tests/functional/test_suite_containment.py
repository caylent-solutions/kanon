"""Tests for the deadlines and leak detection that bound this test suite.

Nothing here tests kanon behaviour; it tests the guards that stop a wedged
``kanon`` subprocess from hanging a pytest worker until CI's own limit expires,
and that stop such a subprocess from outliving the session unnoticed.

Covers:
- KANON_TEST_SUBPROCESS_TIMEOUT parsing and its fail-fast rejection of bad values
- the per-test pytest-timeout deadline actually being in effect
- the leaked-process matcher, against both a live process and a false-positive
  command line

On `time.sleep` in the probe scripts: CLAUDE.md forbids sleep as a
*synchronization mechanism*, and none of these use it that way. Nothing waits on
the duration -- the probe simply has to stay alive long enough to be found, and
readiness is detected by blocking on the child's own announcement. A stdin-based
hold was tried and is worse: under pytest the child inherits a closed stdin and
exits immediately, so the probe cannot hold at all. The one place this suite did
use sleep for synchronization -- polling a process group for death -- is now an
event-driven wait on the child's exit.

Tier: functional, not unit. These tests spawn real subprocesses and shell out to
``ps``. ``pyproject.toml`` defines ``unit`` as "fast, isolated, no external
dependencies" and ``functional`` as "exercise CLI via subprocess", and the unit
tier is what ``git push`` runs -- so marking these ``unit`` made every push pay
for process spawning and a process-table scan.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import sys
from unittest import mock

import pytest

from tests.conftest import (
    _PROCESS_LEAK_EXIT_CODE,
    _PS_SCAN_COMMAND,
    _SPAWNED_PROCESS_GROUPS,
    _SUBPROCESS_TIMEOUT_ENV,
    _is_kanon_command,
    _leaked_kanon_processes,
    _positive_int_env,
    register_spawned_process_group,
    run_owned_subprocess,
    subprocess_timeout,
)


_HOLD_SCRIPT = "import sys, time\nsys.stdout.write('up\\n')\nsys.stdout.flush()\ntime.sleep(600)\n"

_PROBE_TIMEOUT_ENV = "KANON_TEST_WEDGE_PROBE_TIMEOUT"
_PROBE_TIMEOUT_DEFAULT = "1"

_PROCPS_NON_TTY_WIDTH = 80
"""Column width procps truncates a non-tty command listing to.

The padding below has to cross it, or the probe cannot reproduce the truncation
this suite exists to catch."""

_WIDTH_PADDING = "pad" * _PROCPS_NON_TTY_WIDTH


def _spawn_leak_probe(tmp_path: pathlib.Path) -> subprocess.Popen:
    """Start a child that presents the command line of a leaked ``kanon`` install.

    The child does no install work; it only needs an argument vector ``ps`` will
    report as ``-m kanon_cli``. A long padding argument precedes that marker so the
    marker sits far beyond column 80: procps truncates its command column to the
    terminal width when stdout is not a tty, which once cut the marker off every
    candidate in CI and made the scan report a clean session. Without the padding
    this probe passes on a short path and hides that regression.

    The caller is responsible for killing and reaping the returned process.
    """
    script = tmp_path / "hold.py"
    script.write_text(_HOLD_SCRIPT, encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, str(script), _WIDTH_PADDING, "-m", "kanon_cli"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    _await_ready(child, "up\n")
    return child


def _await_ready(child: subprocess.Popen, expected: str) -> None:
    """Block until *child* announces readiness, or fail with a bounded diagnostic.

    A bare ``readline()`` has no deadline. If the probe never starts -- a bad
    interpreter path, a syntax error in the script -- it blocks until pytest's own
    600-second per-test timeout kills the worker. That is the exact hang class
    this module exists to detect, so leaving it here would mean the guard could
    wedge the suite it guards.

    Readiness is an event, not a duration: this waits on the child's own
    announcement and reads it as soon as it arrives. The deadline only bounds the
    failure case.

    Args:
        child: The probe process, with ``stdout`` piped and text mode on.
        expected: The readiness line the probe writes.

    Raises:
        AssertionError: When the probe does not announce readiness in time.
    """
    deadline = _positive_int_env(_PROBE_TIMEOUT_ENV, _PROBE_TIMEOUT_DEFAULT)
    ready: list[str] = []

    def _read() -> None:
        assert child.stdout is not None
        ready.append(child.stdout.readline())

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout=deadline)

    observed = ready[0] if ready else None
    if reader.is_alive() or observed != expected:
        child.kill()
        child.wait()
        raise AssertionError(
            f"probe did not announce readiness ({expected!r}) within {deadline}s; "
            f"got {observed!r}. Raise "
            f"{_PROBE_TIMEOUT_ENV} on a slow machine."
        )


@pytest.mark.functional
class TestSubprocessTimeout:
    def test_uses_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An operator-supplied deadline overrides the suite default."""
        monkeypatch.setenv(_SUBPROCESS_TIMEOUT_ENV, "45")
        assert subprocess_timeout() == 45

    def test_defaults_to_a_positive_deadline_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bare pytest run is still bounded, not left to block forever."""
        monkeypatch.delenv(_SUBPROCESS_TIMEOUT_ENV, raising=False)
        assert subprocess_timeout() > 0

    @pytest.mark.parametrize("raw", ["0", "-5"])
    def test_rejects_non_positive(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        """A non-positive deadline would disable containment, so it is refused."""
        monkeypatch.setenv(_SUBPROCESS_TIMEOUT_ENV, raw)
        with pytest.raises(RuntimeError, match=_SUBPROCESS_TIMEOUT_ENV):
            subprocess_timeout()

    @pytest.mark.parametrize("raw", ["", "none", "5s"])
    def test_rejects_unparseable(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        """A malformed deadline names the offending variable rather than being ignored."""
        monkeypatch.setenv(_SUBPROCESS_TIMEOUT_ENV, raw)
        with pytest.raises(RuntimeError, match=_SUBPROCESS_TIMEOUT_ENV):
            subprocess_timeout()

    def test_positive_int_env_prefers_environment_over_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shared parser reads the environment and falls back only when absent."""
        monkeypatch.setenv("KANON_TEST_CONTAINMENT_PROBE", "7")
        assert _positive_int_env("KANON_TEST_CONTAINMENT_PROBE", "99") == 7
        monkeypatch.delenv("KANON_TEST_CONTAINMENT_PROBE")
        assert _positive_int_env("KANON_TEST_CONTAINMENT_PROBE", "99") == 99


@pytest.mark.functional
class TestSubprocessDeadlineIsEnforced:
    def test_a_wedged_child_is_killed_and_reported(self, tmp_path: pathlib.Path) -> None:
        """subprocess.run with the suite's timeout kills a hung child instead of blocking."""
        script = tmp_path / "hold.py"
        script.write_text(_HOLD_SCRIPT, encoding="utf-8")
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                check=False,
                timeout=_positive_int_env(_PROBE_TIMEOUT_ENV, _PROBE_TIMEOUT_DEFAULT),
            )
        assert str(script) in " ".join(exc_info.value.cmd)


@pytest.mark.functional
class TestPerTestDeadline:
    def test_timeout_plugin_is_loaded(self, request: pytest.FixtureRequest) -> None:
        """Without pytest-timeout there is no backstop for a hang outside a helper."""
        assert request.config.pluginmanager.hasplugin("timeout"), (
            "pytest-timeout must be installed; tests/conftest.py refuses to run without it"
        )

    def test_deadline_matches_the_configured_value(self, request: pytest.FixtureRequest) -> None:
        """The deadline pytest-timeout resolved is the one tests/conftest.py exported."""
        configured = os.environ.get("PYTEST_TIMEOUT")
        assert configured is not None, "tests/conftest.py must export PYTEST_TIMEOUT for pytest-timeout to read"
        effective = getattr(request.config, "_env_timeout", None)
        assert effective == pytest.approx(float(configured)), (
            f"pytest-timeout resolved a deadline of {effective!r}, but PYTEST_TIMEOUT is {configured!r}"
        )


@pytest.mark.functional
class TestLeakedProcessMatching:
    @pytest.mark.parametrize(
        "command",
        [
            "/usr/bin/python3 -m kanon_cli install .kanon",
            "/opt/venv/bin/kanon doctor",
            "kanon install",
        ],
    )
    def test_matches_kanon_invocations(self, command: str) -> None:
        """Both module and console-script invocations count as kanon processes."""
        assert _is_kanon_command(command)

    @pytest.mark.parametrize(
        "command",
        [
            "python -m pytest -n auto --cov=kanon_cli --cov-report=term-missing",
            "uv run pytest -n auto --dist loadscope -m unit",
            "/usr/bin/git -C /tmp/kanon_cli fetch",
            "",
        ],
    )
    def test_does_not_match_test_runners(self, command: str) -> None:
        """A runner that merely mentions kanon_cli must not be reported as a leak.

        ``--cov=kanon_cli`` appears in the CI pytest command line; a substring match
        would flag the test session itself and fail every run.
        """
        assert not _is_kanon_command(command)


@pytest.mark.functional
class TestLeakedProcessDetection:
    def test_finds_a_live_process_in_this_process_group(self, tmp_path: pathlib.Path) -> None:
        """A surviving kanon-shaped child is found by a scan of our own process group.

        The probe's marker sits past column 80, so this also covers the command-column
        truncation that made the scan blind on Linux.
        """
        child = _spawn_leak_probe(tmp_path)
        try:
            leaked = _leaked_kanon_processes(os.getpgrp())
            assert child.pid in [pid for pid, _command in leaked], (
                f"pid {child.pid} is alive in process group {os.getpgrp()} but was not detected; got {leaked!r}"
            )
        finally:
            child.kill()
            child.wait(timeout=subprocess_timeout())

    def test_reports_nothing_once_the_child_is_gone(self, tmp_path: pathlib.Path) -> None:
        """A reaped child is no longer reported, so a clean session stays green."""
        child = _spawn_leak_probe(tmp_path)
        child.kill()
        child.wait(timeout=subprocess_timeout())
        leaked = _leaked_kanon_processes(os.getpgrp())
        assert child.pid not in [pid for pid, _command in leaked]

    def test_scan_command_disables_command_column_truncation(self) -> None:
        """The ps invocation must ask for untruncated output.

        procps truncates the command column to the terminal width (80 when stdout is
        not a tty). Dropping the wide flag reintroduces a scan that silently sees no
        leaks on Linux while passing on macOS, where ps does not truncate a non-tty.
        """
        assert "-ww" in _PS_SCAN_COMMAND, (
            f"{_PS_SCAN_COMMAND!r} must pass -ww; without it procps truncates the command "
            f"column and the trailing '-m kanon_cli' marker is cut off in CI."
        )


@pytest.mark.functional
class TestLeakScanFailsClosed:
    def test_raises_when_the_listing_does_not_contain_this_process(self) -> None:
        """An unparseable ps listing raises instead of reporting a clean session.

        Every process listing contains the process doing the listing. If this one does
        not, the output is not in the assumed 'pid pgid command' form, and an empty
        result would mean 'cannot see' rather than 'nothing leaked' -- the exact
        fail-open behaviour that hid the truncation defect.
        """
        bogus = subprocess.CompletedProcess(args=list(_PS_SCAN_COMMAND), returncode=0, stdout="garbage\n", stderr="")
        with mock.patch("tests.conftest.subprocess.run", return_value=bogus):
            with pytest.raises(RuntimeError, match="did not find this process"):
                _leaked_kanon_processes(os.getpgrp())

    def test_raises_when_ps_is_unavailable(self) -> None:
        """A missing or failing ps is surfaced, not swallowed."""
        with mock.patch("tests.conftest.subprocess.run", side_effect=FileNotFoundError("ps")):
            with pytest.raises(RuntimeError, match="Unable to scan"):
                _leaked_kanon_processes(os.getpgrp())

    def test_own_process_alone_is_not_reported_as_a_leak(self) -> None:
        """The scanning process must never report itself, however it is named."""
        listing = f"{os.getpid()} {os.getpgrp()} python -m kanon_cli install\n"
        completed = subprocess.CompletedProcess(args=list(_PS_SCAN_COMMAND), returncode=0, stdout=listing, stderr="")
        with mock.patch("tests.conftest.subprocess.run", return_value=completed):
            assert _leaked_kanon_processes(os.getpgrp()) == []


@pytest.mark.functional
class TestLeakScanOwnership:
    """The leak scan judges only process groups this suite created.

    It used to scan ``os.getpgrp()`` -- every process sharing the running
    process's group. Under a non-interactive shell, ``make``, or a CI step no new
    groups are created, so that is everything on the machine. Combined with argv
    matching, which is satisfied by any command line merely *mentioning* a kanon
    invocation, it flagged and SIGKILLed processes the suite never started. That
    happened during this branch's development: regenerating a help fixture, the
    scan matched the shell running the command because its argv contained
    ``python -m kanon_cli clean --help``.
    """

    def test_argv_matching_still_accepts_a_bare_mention(self) -> None:
        """The matcher alone cannot tell a kanon process from a mention of one.

        This is why ownership, not matching, is what makes the scan safe. If this
        ever stops being true the matcher improved, but the registry is still the
        guarantee.
        """
        shell = "/bin/sh -c 'cd /repo && python -m kanon_cli install'"
        assert _is_kanon_command(shell), (
            "expected the argv matcher to be satisfied by a mention; the ownership "
            "registry is what prevents that from becoming a kill"
        )

    def test_unregistered_group_is_never_scanned(self) -> None:
        """A process the suite did not start is not the suite's to judge."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            assert child.pid not in _SPAWNED_PROCESS_GROUPS, (
                "a group the suite never registered must not appear in the registry"
            )
        finally:
            child.kill()
            child.wait()

    def test_running_process_group_is_not_in_the_registry(self) -> None:
        """The scan must never judge its own group, which is what it used to do."""
        assert os.getpgrp() not in _SPAWNED_PROCESS_GROUPS, (
            "the running process's own group is in the registry, so the scan would "
            "flag anything sharing it -- under make or a CI step, that is everything"
        )

    def test_registered_group_with_a_kanon_process_is_found(self) -> None:
        """Detection still works: ownership narrows the scan, it does not disable it."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "-m", "kanon_cli"],
            start_new_session=True,
        )
        try:
            register_spawned_process_group(child.pid)
            found = _leaked_kanon_processes(child.pid)
            assert any(pid == child.pid for pid, _command in found), (
                f"expected the registered group to be scanned and its kanon process found; got {found!r}"
            )
        finally:
            _SPAWNED_PROCESS_GROUPS.discard(child.pid)
            child.kill()
            child.wait()


@pytest.mark.functional
class TestLeakExitCode:
    """The leak status must not collide with pytest's own exit codes."""

    def test_exit_code_is_outside_pytests_reserved_range(self) -> None:
        """4 is pytest's USAGE_ERROR, so CI could not tell the two apart.

        The same PR that added this scan also made a missing plugin exit 4, so a
        leaked process and a broken command line reported identically.
        """
        reserved = {code.value for code in pytest.ExitCode}
        assert _PROCESS_LEAK_EXIT_CODE not in reserved, (
            f"leak exit code {_PROCESS_LEAK_EXIT_CODE} collides with pytest's reserved codes {sorted(reserved)}"
        )


@pytest.mark.functional
class TestVendoredTestsAreOrderIndependent:
    """A test that passes only because a sibling ran first is a latent failure.

    ``tests/unit/repo/test_git_command.py::GitCommandWaitTest`` mocks
    ``subprocess.Popen`` with a double that models only what ``.Wait()`` needs.
    ``_build_env`` also reads ``user_agent.git``, which probes ``git --version``
    once per process and memoizes the answer on module-level globals. With those
    globals cold the probe reached the double and raised ``AttributeError``; with
    them warm it never ran.

    Nothing declared that dependency, so the class passed under one test
    distribution and failed under another. It was latent on ``main`` and surfaced
    in the full-suite job once new tests shifted xdist's ``loadscope``
    assignment. Running the class by itself is what tells the two apart: a fresh
    interpreter guarantees the caches are cold.
    """

    def test_git_command_wait_tests_pass_in_a_cold_interpreter(self) -> None:
        """Run the class alone, where no sibling can have warmed the caches."""
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        result = run_owned_subprocess(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/repo/test_git_command.py::GitCommandWaitTest",
                "-p",
                "no:cacheprovider",
                "-q",
            ],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=subprocess_timeout(),
        )
        assert result.returncode == 0, (
            f"GitCommandWaitTest depends on another test having run first; in isolation it fails:\n{result.stdout}"
        )
