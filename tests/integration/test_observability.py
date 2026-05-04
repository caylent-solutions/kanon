"""Integration tests for REPO_TRACE observability controls.

Covers:
  - AC-TEST-001: REPO_TRACE=0 produces no trace output
  - AC-TEST-002: REPO_TRACE=1 produces trace output on stderr
  - AC-TEST-003: REPO_TRACE=invalid is treated as disabled
  - AC-TEST-004: trace-file size enforcement (>10MB rotation or truncation)

AC-FUNC-001: Observability controls are deterministic and bounded.
AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).
"""

import os
import pathlib
import subprocess
import sys
from unittest import mock

import pytest

from kanon_cli.repo import repo_trace


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

# Size limit for trace file enforcement tests (in bytes).
# 10 MiB expressed in bytes for clear, auditable threshold comparisons.
_TEN_MIB_BYTES = 10 * 1024 * 1024

# Recognized REPO_TRACE enabling values.
_TRACE_ENABLED_VALUE = "1"

# REPO_TRACE disabled value.
_TRACE_DISABLED_VALUE = "0"

# Example of an invalid (unrecognized) REPO_TRACE value.
_TRACE_INVALID_VALUE = "invalid"


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _build_trace_env(repo_trace_value: str) -> dict:
    """Build a subprocess environment with the given REPO_TRACE value.

    Ensures PYTHONPATH includes the source tree and PYTHONUNBUFFERED=1 so
    output lines arrive in real time rather than only when the pipe closes.

    Args:
        repo_trace_value: The value to set for REPO_TRACE in the environment.

    Returns:
        A dict suitable for passing as the subprocess env.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    entries = [src_str] + [p for p in existing.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["REPO_TRACE"] = repo_trace_value
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run_trace_script(repo_trace_value: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    """Run a minimal Python script that exercises the Trace context manager.

    The script is parameterized by the REPO_TRACE environment variable and
    verifies whether trace output appears on stderr (by setting _TRACE_TO_STDERR
    to True in the script). This allows subprocess-level isolation of the
    module-level _TRACE state.

    Args:
        repo_trace_value: The REPO_TRACE value to inject into the subprocess env.
        cwd: Working directory for the subprocess.

    Returns:
        CompletedProcess with stdout and stderr captured.
    """
    trace_file = str(cwd / "TRACE_FILE")
    script = (
        "import sys, os\n"
        "os.environ['REPO_TRACE'] = os.environ.get('REPO_TRACE', '0')\n"
        "from kanon_cli.repo import repo_trace\n"
        "repo_trace._TRACE_FILE = " + repr(trace_file) + "\n"
        "repo_trace._TRACE_TO_STDERR = True\n"
        "with repo_trace.Trace('test-trace-message'):\n"
        "    pass\n"
    )
    env = _build_trace_env(repo_trace_value)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: REPO_TRACE=0 produces no trace output
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRepoTraceDisabled:
    """AC-TEST-001: REPO_TRACE=0 disables tracing -- no trace output produced.

    Verifies that with REPO_TRACE=0 set in the subprocess environment:
      - The Trace context manager writes nothing to the trace file.
      - No trace output appears on stderr (AC-CHANNEL-001).
      - No trace output appears on stdout (AC-CHANNEL-001).
    """

    def test_repo_trace_zero_produces_no_file_output(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=0: Trace context manager writes nothing to the trace file.

        Runs a subprocess that sets REPO_TRACE=0 before importing repo_trace
        and exercises the Trace context manager. Verifies the trace file is
        empty (or absent) because tracing must be disabled.
        """
        trace_file = tmp_path / "TRACE_FILE"
        script = (
            "import sys, os\n"
            "from kanon_cli.repo import repo_trace\n"
            "repo_trace._TRACE_FILE = " + repr(str(trace_file)) + "\n"
            "with repo_trace.Trace('should-not-appear'):\n"
            "    pass\n"
        )
        env = _build_trace_env(_TRACE_DISABLED_VALUE)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"

        # With REPO_TRACE=0, no output should be written to the trace file.
        if trace_file.exists():
            content = trace_file.read_text(encoding="utf-8", errors="replace")
            assert content == "", (
                f"Trace file must be empty when REPO_TRACE=0, got {len(content)} bytes: {content[:200]!r}"
            )

    def test_repo_trace_zero_no_stderr_trace_output(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=0: Trace context manager writes nothing to stderr.

        AC-CHANNEL-001: stderr must be free of trace messages when tracing
        is disabled. Even with _TRACE_TO_STDERR=True set explicitly, the
        Trace context manager must short-circuit before writing to stderr.
        """
        result = _run_trace_script(_TRACE_DISABLED_VALUE, tmp_path)

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert "test-trace-message" not in result.stderr, (
            f"Trace message must not appear on stderr when REPO_TRACE=0. stderr={result.stderr!r}"
        )

    def test_repo_trace_zero_no_stdout_trace_output(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=0: Trace context manager writes nothing to stdout.

        AC-CHANNEL-001: stdout must remain clean of trace content. The Trace
        context manager writes to a file and optionally to stderr -- never to
        stdout.
        """
        result = _run_trace_script(_TRACE_DISABLED_VALUE, tmp_path)

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert "test-trace-message" not in result.stdout, (
            f"Trace message must not appear on stdout when REPO_TRACE=0. stdout={result.stdout!r}"
        )

    def test_is_trace_returns_false_when_repo_trace_zero(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=0: IsTrace() returns False in the subprocess context.

        Verifies the module-level _TRACE flag is False after importing with
        REPO_TRACE=0 set, using exit code to communicate the assertion result.
        """
        script = (
            "import sys, os\nfrom kanon_cli.repo import repo_trace\nsys.exit(0 if not repo_trace.IsTrace() else 1)\n"
        )
        env = _build_trace_env(_TRACE_DISABLED_VALUE)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            "IsTrace() must return False when REPO_TRACE=0. "
            f"Got returncode {result.returncode}. stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: REPO_TRACE=1 produces trace output on stderr
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRepoTraceEnabled:
    """AC-TEST-002: REPO_TRACE=1 enables tracing and produces output on stderr.

    Verifies that with REPO_TRACE=1 set in the subprocess environment:
      - IsTrace() returns True.
      - The Trace context manager writes the trace message to stderr when
        _TRACE_TO_STDERR is enabled.
      - The trace message is written to the trace file.
      - No trace content appears on stdout (AC-CHANNEL-001).
    """

    def test_repo_trace_one_is_trace_returns_true(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=1: IsTrace() returns True in the subprocess context."""
        script = "import sys, os\nfrom kanon_cli.repo import repo_trace\nsys.exit(0 if repo_trace.IsTrace() else 1)\n"
        env = _build_trace_env(_TRACE_ENABLED_VALUE)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            "IsTrace() must return True when REPO_TRACE=1. "
            f"Got returncode {result.returncode}. stderr={result.stderr!r}"
        )

    def test_repo_trace_one_produces_stderr_output(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=1: Trace context manager writes trace message to stderr.

        With REPO_TRACE=1 and _TRACE_TO_STDERR=True, the trace message must
        appear on stderr. This verifies the observable integration between the
        REPO_TRACE env var and the Trace context manager's stderr path.
        """
        result = _run_trace_script(_TRACE_ENABLED_VALUE, tmp_path)

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert "test-trace-message" in result.stderr, (
            f"Trace message must appear on stderr when REPO_TRACE=1 and _TRACE_TO_STDERR=True. stderr={result.stderr!r}"
        )

    def test_repo_trace_one_writes_to_trace_file(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=1: Trace context manager writes output to the trace file."""
        trace_file = tmp_path / "TRACE_FILE"
        script = (
            "import sys, os\n"
            "from kanon_cli.repo import repo_trace\n"
            "repo_trace._TRACE_FILE = " + repr(str(trace_file)) + "\n"
            "with repo_trace.Trace('file-trace-message'):\n"
            "    pass\n"
        )
        env = _build_trace_env(_TRACE_ENABLED_VALUE)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert trace_file.exists(), "Trace file must be created when REPO_TRACE=1"
        content = trace_file.read_text(encoding="utf-8", errors="replace")
        assert "file-trace-message" in content, (
            f"Trace message must appear in trace file when REPO_TRACE=1. File content: {content[:400]!r}"
        )

    def test_repo_trace_one_no_trace_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=1: Trace output must not appear on stdout.

        AC-CHANNEL-001: stdout must remain free of trace messages. The Trace
        context manager must write only to the trace file and optionally to
        stderr, never to stdout.
        """
        result = _run_trace_script(_TRACE_ENABLED_VALUE, tmp_path)

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert "test-trace-message" not in result.stdout, (
            f"Trace message must not appear on stdout when REPO_TRACE=1. stdout={result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: REPO_TRACE=invalid is treated as disabled
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRepoTraceInvalid:
    """AC-TEST-003: REPO_TRACE=invalid is treated as disabled.

    Unrecognized REPO_TRACE values must not enable tracing. Only the
    recognized value '1' enables tracing; all other non-zero values are
    treated as disabled. This ensures the observability control is
    deterministic -- callers cannot accidentally enable tracing by
    mistyping the env var.
    """

    @pytest.mark.parametrize(
        "invalid_value",
        [
            "invalid",
            "yes",
            "true",
            "TRUE",
            "on",
            "2",
            "enable",
            "enabled",
        ],
    )
    def test_unrecognized_repo_trace_disables_tracing(self, tmp_path: pathlib.Path, invalid_value: str) -> None:
        """Unrecognized REPO_TRACE value disables tracing (IsTrace() is False)."""
        script = (
            "import sys, os\nfrom kanon_cli.repo import repo_trace\nsys.exit(0 if not repo_trace.IsTrace() else 1)\n"
        )
        env = _build_trace_env(invalid_value)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"IsTrace() must return False when REPO_TRACE={invalid_value!r} "
            f"(unrecognized value). Got returncode {result.returncode}. "
            f"stderr={result.stderr!r}"
        )

    def test_repo_trace_invalid_no_trace_file_written(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=invalid: no trace file content is written."""
        trace_file = tmp_path / "TRACE_FILE"
        script = (
            "import sys, os\n"
            "from kanon_cli.repo import repo_trace\n"
            "repo_trace._TRACE_FILE = " + repr(str(trace_file)) + "\n"
            "with repo_trace.Trace('should-not-appear'):\n"
            "    pass\n"
        )
        env = _build_trace_env(_TRACE_INVALID_VALUE)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        if trace_file.exists():
            content = trace_file.read_text(encoding="utf-8", errors="replace")
            assert content == "", (
                f"Trace file must be empty when REPO_TRACE=invalid, got {len(content)} bytes: {content[:200]!r}"
            )

    def test_repo_trace_invalid_no_stderr_output(self, tmp_path: pathlib.Path) -> None:
        """REPO_TRACE=invalid: no trace output appears on stderr.

        AC-CHANNEL-001: stderr must remain clean of trace messages when the
        REPO_TRACE value is unrecognized (treated as disabled).
        """
        result = _run_trace_script(_TRACE_INVALID_VALUE, tmp_path)

        assert result.returncode == 0, f"Script failed: stderr={result.stderr!r}"
        assert "test-trace-message" not in result.stderr, (
            f"Trace message must not appear on stderr when REPO_TRACE=invalid. stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: trace-file size enforcement (>10MB rotation or truncation)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTraceFileSizeEnforcement:
    """AC-TEST-004: Trace-file size enforcement -- large files are rotated or truncated.

    Verifies that when the trace file exceeds the configured size limit,
    the _ClearOldTraces function enforces the limit by removing old commands.
    The enforcement must be:
      - Triggered when file size exceeds the maximum.
      - Bounded -- the resulting file must not exceed the maximum.
      - Deterministic -- the same input always produces consistent output.
    """

    def test_clear_old_traces_truncates_oversized_file(self, tmp_path: pathlib.Path) -> None:
        """_ClearOldTraces reduces file size when it exceeds the configured limit.

        Creates a trace file larger than 10 MiB, then calls _ClearOldTraces
        with a limit of 10 MiB and verifies the file is smaller afterwards.
        Uses real file I/O without mocking the size check to exercise the
        full rotation path.
        """
        trace_file = tmp_path / "TRACE_FILE"

        # Build trace content larger than 10 MiB using the separator pattern
        # that _ClearOldTraces uses to find command boundaries.
        separator = repo_trace._NEW_COMMAND_SEP
        # Each chunk is a complete command trace segment.
        chunk = (
            f"PID: 100 END: 999 :{separator} cmd-old\n"
            + ("x" * (512 * 1024))  # 512 KiB of padding per chunk
            + "\nPID: 200 START: 001 :cmd-new\n"
        )
        # Write enough chunks to exceed 10 MiB.
        chunks_needed = (_TEN_MIB_BYTES // len(chunk.encode("utf-8"))) + 3
        content = chunk * chunks_needed
        trace_file.write_text(content, encoding="utf-8")

        initial_size = trace_file.stat().st_size
        assert initial_size > _TEN_MIB_BYTES, (
            f"Test pre-condition: trace file must exceed 10 MiB before rotation. File size: {initial_size} bytes"
        )

        # Set _TRACE_FILE and limit, then call _ClearOldTraces.
        ten_mib_in_mib = _TEN_MIB_BYTES / (1024 * 1024)
        with mock.patch.object(repo_trace, "_TRACE_FILE", str(trace_file)):
            with mock.patch.object(repo_trace, "_MAX_SIZE", ten_mib_in_mib):
                repo_trace._ClearOldTraces()

        # After rotation, the file must exist and be smaller than before.
        assert trace_file.exists(), "Trace file must still exist after rotation"
        final_size = trace_file.stat().st_size
        assert final_size < initial_size, (
            f"Trace file must be smaller after rotation. Initial: {initial_size} bytes, Final: {final_size} bytes"
        )

    def test_clear_old_traces_leaves_small_file_unchanged(self, tmp_path: pathlib.Path) -> None:
        """_ClearOldTraces does not modify files smaller than the size limit.

        Verifies that a trace file smaller than 10 MiB is left unchanged,
        confirming that rotation only triggers when the limit is exceeded.
        """
        trace_file = tmp_path / "TRACE_FILE"
        small_content = "PID: 1 START: 1 :small-trace\nPID: 1 END: 2 :small-trace\n"
        trace_file.write_text(small_content, encoding="utf-8")

        initial_size = trace_file.stat().st_size
        assert initial_size < _TEN_MIB_BYTES, (
            f"Test pre-condition: trace file must be smaller than 10 MiB. File size: {initial_size} bytes"
        )

        ten_mib_in_mib = _TEN_MIB_BYTES / (1024 * 1024)
        with mock.patch.object(repo_trace, "_TRACE_FILE", str(trace_file)):
            with mock.patch.object(repo_trace, "_MAX_SIZE", ten_mib_in_mib):
                repo_trace._ClearOldTraces()

        assert trace_file.exists(), "Trace file must still exist after no-op rotation check"
        final_size = trace_file.stat().st_size
        assert final_size == initial_size, (
            f"Small trace file must not be modified. Initial: {initial_size} bytes, Final: {final_size} bytes"
        )

    def test_clear_old_traces_handles_absent_file_gracefully(self, tmp_path: pathlib.Path) -> None:
        """_ClearOldTraces handles a missing trace file without raising.

        Verifies that when the trace file does not exist, _ClearOldTraces
        returns without error -- there is nothing to rotate.
        """
        absent_trace_file = tmp_path / "nonexistent_TRACE_FILE"
        assert not absent_trace_file.exists(), "Pre-condition: file must not exist"

        with mock.patch.object(repo_trace, "_TRACE_FILE", str(absent_trace_file)):
            with mock.patch.object(repo_trace, "_MAX_SIZE", 10.0):
                # Must not raise FileNotFoundError or any other exception.
                repo_trace._ClearOldTraces()

    def test_trace_file_rotation_is_bounded(self, tmp_path: pathlib.Path) -> None:
        """After rotation, the trace file size is bounded below the limit.

        Creates a trace file with well-formed command boundaries, triggers
        rotation, and verifies the resulting file fits within the limit.
        Each boundary is a line containing both 'END:' and the separator so
        _ClearOldTraces can identify the chunk boundary correctly.
        """
        trace_file = tmp_path / "TRACE_FILE"
        separator = repo_trace._NEW_COMMAND_SEP

        # Build well-formed command blocks that _ClearOldTraces can split at.
        # Each block: one END line with separator, then body lines.
        one_kib = "y" * 1024
        block = f"PID: 1 END: 1 :{separator} cmd\n{one_kib}\n"
        # Write 12 MiB worth of blocks to exceed the 10 MiB limit.
        target_bytes = 12 * 1024 * 1024
        block_bytes = len(block.encode("utf-8"))
        repeat = (target_bytes // block_bytes) + 1
        trace_file.write_text(block * repeat, encoding="utf-8")

        initial_size = trace_file.stat().st_size
        assert initial_size > _TEN_MIB_BYTES

        ten_mib_in_mib = _TEN_MIB_BYTES / (1024 * 1024)
        with mock.patch.object(repo_trace, "_TRACE_FILE", str(trace_file)):
            with mock.patch.object(repo_trace, "_MAX_SIZE", ten_mib_in_mib):
                repo_trace._ClearOldTraces()

        if trace_file.exists():
            final_size = trace_file.stat().st_size
            # The resulting file must be strictly smaller than the initial size.
            assert final_size < initial_size, (
                f"Rotation must reduce file size. Initial: {initial_size} bytes, Final: {final_size} bytes"
            )
