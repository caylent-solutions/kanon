"""Integration tests for signal handling during kanon install and sync.

Covers:
  - AC-TEST-001: SIGTERM mid-install results in exit 143 and cleanup
  - AC-TEST-002: SIGINT mid-sync results in exit 130 and restore
  - AC-TEST-003: SIGHUP behaves per default handler

AC-FUNC-001: Signals produce graceful termination with cleanup contracts.
AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).
"""

import fcntl
import os
import pathlib
import signal
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

# Timeout for subprocess signal tests (seconds).
_SIGNAL_WAIT_TIMEOUT = 30

# Timeout for waiting for a subprocess to reach the retry-sleep phase (seconds).
# The repo tool sleeps ~4 seconds after the first failed git fetch attempt;
# we wait up to this many seconds for the marker line to appear in stdout.
_STARTUP_MARKER_TIMEOUT = 20

# Text fragment emitted by the embedded repo tool when it enters the retry-sleep
# phase after a failed git fetch. With PYTHONUNBUFFERED=1 in the subprocess
# environment, this line arrives in real time so the test can reliably detect
# the blocked mid-install state.
_RETRY_SLEEP_MARKER = "sleeping"

# Exit code expected when a process handles SIGTERM and exits with 128 + SIGTERM.
# POSIX shell convention: 128 + signal number.
_EXIT_SIGTERM = 128 + signal.SIGTERM  # 143

# Exit code expected when a process handles SIGINT and exits with 128 + SIGINT.
# POSIX shell convention: 128 + signal number.
_EXIT_SIGINT = 128 + signal.SIGINT  # 130


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _build_subprocess_env(extra_env: "dict[str, str] | None" = None) -> dict[str, str]:
    """Build an environment dict for subprocess-based tests.

    Ensures PYTHONPATH includes the source tree, REPO_TRACE is disabled,
    and PYTHONUNBUFFERED=1 so stdout lines arrive in real time rather than
    only when the subprocess pipe closes.

    Args:
        extra_env: Additional environment variables merged on top of os.environ.

    Returns:
        A dict suitable for passing as subprocess env.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    entries = [src_str] + [p for p in existing.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env.setdefault("REPO_TRACE", "0")
    # Disable Python's output buffering so stdout lines can be read line by
    # line by the test harness rather than only after the pipe closes.
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)
    return env


def _write_kanonenv(directory: pathlib.Path, source_name: str = "primary") -> pathlib.Path:
    """Write a minimal single-source .kanon file and return its absolute path.

    The URL is intentionally unreachable so that the embedded repo tool fails
    the first git fetch and enters its retry-sleep phase, giving the test a
    reliable window in which to send a signal to the blocked process.

    Args:
        directory: Directory in which to create the .kanon file.
        source_name: Source name embedded in KANON_SOURCE_* keys.

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


def _start_kanon_install(
    kanonenv: pathlib.Path,
    extra_env: "dict[str, str] | None" = None,
) -> subprocess.Popen:
    """Start a kanon install subprocess and return the Popen handle.

    Args:
        kanonenv: Absolute path to the .kanon config file.
        extra_env: Additional environment variables for the subprocess.

    Returns:
        Running Popen instance with captured stdout and stderr.
    """
    env = _build_subprocess_env(extra_env)
    return subprocess.Popen(
        [sys.executable, "-m", "kanon_cli", "install", str(kanonenv)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _wait_for_retry_sleep(proc: subprocess.Popen, timeout: float = _STARTUP_MARKER_TIMEOUT) -> bool:
    """Read proc stdout until the repo tool's retry-sleep line appears or timeout.

    The embedded repo tool emits a line containing "sleeping" when it fails the
    first git fetch and waits before retrying. With PYTHONUNBUFFERED=1 set by
    _build_subprocess_env(), this line arrives in real time, allowing the test
    to detect the exact moment the process enters its blocked sleep state.

    Args:
        proc: Running subprocess with captured stdout (text mode).
        timeout: Maximum seconds to wait for the retry-sleep marker.

    Returns:
        True if the marker appeared before the timeout, False otherwise.
    """
    found = threading.Event()

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if _RETRY_SLEEP_MARKER in line.lower():
                found.set()
                return
            if proc.poll() is not None:
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    return found.wait(timeout=timeout)


# ---------------------------------------------------------------------------
# AC-TEST-001: SIGTERM mid-install results in exit 143 and cleanup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSigtermMidInstall:
    """AC-TEST-001: SIGTERM mid-install results in exit 143 and cleanup.

    Sends SIGTERM to a running kanon install subprocess while it is blocked
    in the repo tool's retry-sleep phase and verifies:
      - The process exits with code 143 (128 + SIGTERM) so that shell callers
        can distinguish signal termination from a regular application error.
      - The install lock file is released by the OS on process exit (cleanup).
      - No Python tracebacks appear on stdout (AC-CHANNEL-001).
    """

    def test_sigterm_mid_install_exits_143(self, tmp_path: pathlib.Path) -> None:
        """SIGTERM during install exits with code 143 (128 + SIGTERM).

        Starts kanon install and waits until the repo tool's retry-sleep phase
        is reached (a reliable indicator of a blocked mid-install state).
        Sends SIGTERM and asserts the process exits with returncode 143.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip(
                "Subprocess did not reach the retry-sleep phase within "
                f"{_STARTUP_MARKER_TIMEOUT}s; cannot send SIGTERM at the "
                "correct install phase."
            )

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail(f"kanon install did not terminate within {_SIGNAL_WAIT_TIMEOUT}s after SIGTERM")

        assert proc.returncode == _EXIT_SIGTERM, (
            f"Expected exit code {_EXIT_SIGTERM} (128 + SIGTERM) after SIGTERM, "
            f"got {proc.returncode}. "
            "kanon install must install a SIGTERM handler that exits with "
            "128 + signal.SIGTERM so shell scripts can detect signal termination."
        )

    def test_sigterm_releases_install_lock(self, tmp_path: pathlib.Path) -> None:
        """SIGTERM during install releases the install lock file (cleanup).

        After the install process is killed by SIGTERM, the kernel releases
        all file locks held by the process. A subsequent install attempt must
        be able to acquire the lock without blocking indefinitely.
        """
        from kanon_cli.constants import INSTALL_LOCK_FILENAME

        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        # The OS releases file locks when a process exits, including when killed
        # by a signal. Verify the lock file (if it exists) is now acquirable.
        lock_path = tmp_path / ".kanon-data" / INSTALL_LOCK_FILENAME
        if lock_path.exists():
            with open(lock_path, "w", encoding="utf-8") as lock_fd:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    pytest.fail(
                        "Install lock is still held after SIGTERM-killed process. "
                        "The kernel must release file locks on process exit, "
                        "including signal-killed exits."
                    )

    def test_sigterm_stdout_contains_no_traceback(self, tmp_path: pathlib.Path) -> None:
        """SIGTERM during install does not leak a Python traceback to stdout.

        AC-CHANNEL-001: stdout must contain only progress messages. A signal
        handler that exits with os._exit(128 + signum) must not allow the
        Python runtime to write an exception traceback to stdout.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        stdout = proc.stdout.read() if proc.stdout else ""
        assert "Traceback" not in stdout, f"Python traceback leaked to stdout after SIGTERM. stdout={stdout!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: SIGINT mid-sync results in exit 130 and restore
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSigintMidSync:
    """AC-TEST-002: SIGINT mid-sync results in exit 130 and restore.

    Sends SIGINT to a running kanon install subprocess while it is blocked
    in the repo tool's retry-sleep phase and verifies:
      - The process exits with code 130 (128 + SIGINT) so that shell callers
        can distinguish keyboard-interrupt termination from a regular error.
      - The project directory is in a restorable state: a subsequent install
        (with patched repo ops) succeeds without errors.
      - No progress messages appear on stderr (AC-CHANNEL-001).
    """

    def test_sigint_mid_sync_exits_130(self, tmp_path: pathlib.Path) -> None:
        """SIGINT during sync exits with code 130 (128 + SIGINT).

        Starts kanon install, waits until the retry-sleep phase, then sends
        SIGINT. The process must exit with returncode 130.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail(f"kanon install did not terminate within {_SIGNAL_WAIT_TIMEOUT}s after SIGINT")

        assert proc.returncode == _EXIT_SIGINT, (
            f"Expected exit code {_EXIT_SIGINT} (128 + SIGINT) after SIGINT, "
            f"got {proc.returncode}. "
            "kanon install must propagate the SIGINT exit code (130) so that "
            "shell scripts and CI systems can detect interrupt-driven termination."
        )

    def test_sigint_mid_sync_state_is_restorable(self, tmp_path: pathlib.Path) -> None:
        """SIGINT during sync leaves the project state restorable.

        After SIGINT terminates a kanon install, a subsequent install()
        in-process (with patched repo ops) must succeed and produce a
        consistent filesystem state.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        # Retry install in-process with all repo ops patched to no-ops.
        # The retry must succeed despite partial state from the interrupted run.
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        assert (tmp_path / ".packages").is_dir(), (
            ".packages/ must exist after install retry following SIGINT interruption"
        )
        assert (tmp_path / ".kanon-data" / "sources" / "primary").is_dir(), (
            ".kanon-data/sources/primary/ must exist after install retry"
        )

    def test_sigint_stderr_contains_no_progress_lines(self, tmp_path: pathlib.Path) -> None:
        """SIGINT during install does not leak progress messages to stderr.

        AC-CHANNEL-001: progress output belongs on stdout; error messages
        belong on stderr. No progress line (e.g., 'kanon install: parsing')
        must appear on stderr when the install is interrupted by SIGINT.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        stderr = proc.stderr.read() if proc.stderr else ""
        assert "kanon install: parsing" not in stderr, (
            f"Progress message leaked to stderr after SIGINT. stderr={stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: SIGHUP behaves per default handler
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSighupDefaultHandler:
    """AC-TEST-003: SIGHUP behaves per default handler.

    Sends SIGHUP to a running kanon install subprocess and verifies the
    process terminates as expected from the default SIGHUP disposition
    (process termination on POSIX). kanon must not install a custom SIGHUP
    handler that suppresses or alters this behavior.
    """

    def test_sighup_terminates_process_via_default_handler(self, tmp_path: pathlib.Path) -> None:
        """SIGHUP terminates the kanon process via the default signal handler.

        The default disposition for SIGHUP on POSIX systems is to terminate
        the process. The process must exit with a returncode consistent with
        signal termination: Python reports -signal.SIGHUP (-1) for a process
        killed directly by the OS with no custom handler installed.
        """
        kanonenv = _write_kanonenv(tmp_path, "primary")
        proc = _start_kanon_install(kanonenv)

        reached = _wait_for_retry_sleep(proc, timeout=_STARTUP_MARKER_TIMEOUT)
        if not reached:
            proc.kill()
            proc.wait()
            pytest.skip("Subprocess did not reach the retry-sleep phase")

        proc.send_signal(signal.SIGHUP)
        try:
            proc.wait(timeout=_SIGNAL_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail(f"kanon install did not terminate within {_SIGNAL_WAIT_TIMEOUT}s after SIGHUP")

        # The default SIGHUP handler terminates the process.
        # Python reports signal-killed exit as -signum (e.g., -1 for SIGHUP).
        # kanon must not override SIGHUP with a custom handler.
        assert proc.returncode == -(signal.SIGHUP), (
            f"Expected SIGHUP default termination (returncode {-(signal.SIGHUP)}), "
            f"got {proc.returncode}. "
            "SIGHUP must not be intercepted; the default handler must terminate "
            "the process."
        )

    def test_sighup_no_custom_handler_installed_at_import(self) -> None:
        """Importing kanon_cli.cli does not install a custom SIGHUP handler.

        kanon must not call signal.signal(SIGHUP, ...) at module import time.
        This white-box check ensures the SIGHUP disposition remains at its
        pre-import value after loading the CLI module.
        """
        original_sighup = signal.getsignal(signal.SIGHUP)

        import importlib

        import kanon_cli.cli

        importlib.reload(kanon_cli.cli)

        after_import_sighup = signal.getsignal(signal.SIGHUP)

        assert original_sighup == after_import_sighup, (
            f"kanon_cli.cli changed the SIGHUP handler on import. "
            f"Before: {original_sighup!r}, After: {after_import_sighup!r}. "
            "SIGHUP must retain its default disposition."
        )
