# Copyright 2022 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unittests for the repo_trace.py module."""

import os
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import repo_trace


class TraceTests(unittest.TestCase):
    """Check Trace behavior."""

    def setUp(self):
        """Enable tracing and point _TRACE_FILE at a fresh per-test temp file.

        The conftest autouse fixture ``disable_repo_trace`` assigns a path to
        ``_TRACE_FILE`` but does not create it; the test suite's default is
        tracing off (``REPO_TRACE=0``). Tests in this class exercise the trace
        file rotation logic itself, so they must temporarily enable tracing
        and start from a known empty trace file.
        """
        import tempfile

        self._saved_trace = repo_trace._TRACE
        self._tmp = tempfile.TemporaryDirectory(prefix="repo_trace_test_")
        self._trace_path = os.path.join(self._tmp.name, "TRACE_FILE")
        # Seed an empty trace file so the rotation logic has something to read.
        open(self._trace_path, "w").close()
        repo_trace._TRACE = True
        repo_trace._TRACE_FILE = self._trace_path

    def tearDown(self):
        """Restore tracing state and clean up the per-test trace file."""
        repo_trace._TRACE = self._saved_trace
        repo_trace._TRACE_FILE = None
        self._tmp.cleanup()

    def testTrace_MaxSizeEnforced(self):
        content = "git chicken"

        with repo_trace.Trace(content, first_trace=True):
            pass
        first_trace_size = os.path.getsize(repo_trace._TRACE_FILE)

        with repo_trace.Trace(content):
            pass
        self.assertGreater(os.path.getsize(repo_trace._TRACE_FILE), first_trace_size)

        # Check we clear everything is the last chunk is larger than _MAX_SIZE.
        with mock.patch("kanon_cli.repo.repo_trace._MAX_SIZE", 0):
            with repo_trace.Trace(content, first_trace=True):
                pass
            self.assertEqual(first_trace_size, os.path.getsize(repo_trace._TRACE_FILE))

            # Check we only clear the chunks we need to.
            repo_trace._MAX_SIZE = (first_trace_size + 1) / (1024 * 1024)
            with repo_trace.Trace(content, first_trace=True):
                pass
            self.assertEqual(first_trace_size * 2, os.path.getsize(repo_trace._TRACE_FILE))

            with repo_trace.Trace(content, first_trace=True):
                pass
            self.assertEqual(first_trace_size * 2, os.path.getsize(repo_trace._TRACE_FILE))


@pytest.mark.unit
class TraceFileLocationTests(unittest.TestCase):
    """Tests for trace file location selection (fork feature)."""

    def test_fallback_to_tempdir_when_repo_dir_not_writable(self):
        """_GetTraceFile falls back to tempfile.gettempdir() when dir is not writable."""
        with mock.patch("os.access", return_value=False):
            with mock.patch("tempfile.gettempdir", return_value="/tmp/fallback"):
                result = repo_trace._GetTraceFile(quiet=True)
                self.assertIn("/tmp/fallback", result)

    def test_uses_repo_dir_when_writable(self):
        """_GetTraceFile uses repo directory when it is writable."""
        with mock.patch("os.access", return_value=True):
            result = repo_trace._GetTraceFile(quiet=True)
            # Should NOT contain tempdir fallback
            self.assertIn(repo_trace._TRACE_FILE_NAME, result)


@pytest.mark.unit
class TraceContextManagerTests(unittest.TestCase):
    """Tests for Trace context manager functionality."""

    def test_trace_enter_returns_self(self):
        """Trace.__enter__ should return self."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                with mock.patch("builtins.open", mock.mock_open()):
                    t = repo_trace.Trace("test")
                    result = t.__enter__()
                    self.assertIs(result, t)

    def test_trace_exit_returns_false(self):
        """Trace.__exit__ should return False."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                with mock.patch("builtins.open", mock.mock_open()):
                    t = repo_trace.Trace("test")
                    t.__enter__()
                    result = t.__exit__(None, None, None)
                    self.assertFalse(result)

    def test_trace_as_decorator(self):
        """Trace can be used as a decorator."""
        call_count = [0]

        @repo_trace.Trace("decorated function")
        def test_func():
            call_count[0] += 1
            return "result"

        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                with mock.patch("builtins.open", mock.mock_open()):
                    result = test_func()
                    self.assertEqual(result, "result")
                    self.assertEqual(call_count[0], 1)

    def test_trace_noop_when_disabled(self):
        """Trace should be no-op when tracing is disabled."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=False):
            with mock.patch("builtins.open") as mock_open:
                with repo_trace.Trace("test"):
                    pass
                mock_open.assert_not_called()


@pytest.mark.unit
class TraceWritingTests(unittest.TestCase):
    """Tests for Trace file writing."""

    def test_trace_writes_start_message(self):
        """Trace should write START message on enter."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                mock_file = mock.mock_open()
                with mock.patch("builtins.open", mock_file):
                    with repo_trace.Trace("test message"):
                        pass
                    # Check that file was written to
                    handle = mock_file()
                    calls = [call[0][0] for call in handle.write.call_args_list]
                    start_calls = [c for c in calls if "START:" in c]
                    self.assertGreater(len(start_calls), 0)

    def test_trace_writes_end_message(self):
        """Trace should write END message on exit."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                mock_file = mock.mock_open()
                with mock.patch("builtins.open", mock_file):
                    with repo_trace.Trace("test message"):
                        pass
                    handle = mock_file()
                    calls = [call[0][0] for call in handle.write.call_args_list]
                    end_calls = [c for c in calls if "END:" in c]
                    self.assertGreater(len(end_calls), 0)

    def test_trace_includes_pid(self):
        """Trace messages should include PID."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                mock_file = mock.mock_open()
                with mock.patch("builtins.open", mock_file):
                    with mock.patch("os.getpid", return_value=12345):
                        with repo_trace.Trace("test"):
                            pass
                        handle = mock_file()
                        calls = [call[0][0] for call in handle.write.call_args_list]
                        pid_calls = [c for c in calls if "PID: 12345" in c]
                        self.assertGreater(len(pid_calls), 0)

    def test_trace_formats_message(self):
        """Trace should format message with args."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                mock_file = mock.mock_open()
                with mock.patch("builtins.open", mock_file):
                    with repo_trace.Trace("msg %s %d", "test", 42):
                        pass
                    handle = mock_file()
                    calls = [call[0][0] for call in handle.write.call_args_list]
                    formatted_calls = [c for c in calls if "msg test 42" in c]
                    self.assertGreater(len(formatted_calls), 0)


@pytest.mark.unit
class TraceFirstTraceTests(unittest.TestCase):
    """Tests for first_trace parameter."""

    def test_first_trace_adds_separator(self):
        """first_trace=True should add separator to message."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                mock_file = mock.mock_open()
                with mock.patch("builtins.open", mock_file):
                    with mock.patch("kanon_cli.repo.repo_trace._ClearOldTraces"):
                        with repo_trace.Trace("test", first_trace=True):
                            pass
                        handle = mock_file()
                        calls = [call[0][0] for call in handle.write.call_args_list]
                        sep_calls = [c for c in calls if "NEW COMMAND" in c]
                        self.assertGreater(len(sep_calls), 0)

    def test_first_trace_calls_clear_old_traces(self):
        """first_trace=True should call _ClearOldTraces."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                with mock.patch("builtins.open", mock.mock_open()):
                    with mock.patch("kanon_cli.repo.repo_trace._ClearOldTraces") as mock_clear:
                        with repo_trace.Trace("test", first_trace=True):
                            pass
                        mock_clear.assert_called_once()


@pytest.mark.unit
class TraceToStderrTests(unittest.TestCase):
    """Tests for trace to stderr functionality."""

    def test_trace_writes_to_stderr_when_enabled(self):
        """Trace should write to stderr when _TRACE_TO_STDERR is True."""
        with mock.patch("kanon_cli.repo.repo_trace.IsTrace", return_value=True):
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/tmp/test"):
                with mock.patch("kanon_cli.repo.repo_trace._TRACE_TO_STDERR", True):
                    with mock.patch("builtins.open", mock.mock_open()):
                        with mock.patch("builtins.print") as mock_print:
                            with repo_trace.Trace("test"):
                                pass
                            # Should print to stderr
                            calls = [call for call in mock_print.call_args_list]
                            self.assertGreater(len(calls), 0)


@pytest.mark.unit
class IsTraceTests(unittest.TestCase):
    """Tests for IsTrace function."""

    def test_is_trace_returns_trace_value(self):
        """IsTrace should return _TRACE value."""
        with mock.patch("kanon_cli.repo.repo_trace._TRACE", True):
            self.assertTrue(repo_trace.IsTrace())
        with mock.patch("kanon_cli.repo.repo_trace._TRACE", False):
            self.assertFalse(repo_trace.IsTrace())


@pytest.mark.unit
class IsTraceToStderrTests(unittest.TestCase):
    """Tests for IsTraceToStderr function."""

    def test_is_trace_to_stderr_returns_value(self):
        """IsTraceToStderr should return _TRACE_TO_STDERR value."""
        with mock.patch("kanon_cli.repo.repo_trace._TRACE_TO_STDERR", True):
            self.assertTrue(repo_trace.IsTraceToStderr())
        with mock.patch("kanon_cli.repo.repo_trace._TRACE_TO_STDERR", False):
            self.assertFalse(repo_trace.IsTraceToStderr())


@pytest.mark.unit
class SetTraceToStderrTests(unittest.TestCase):
    """Tests for SetTraceToStderr function."""

    def test_set_trace_to_stderr_enables_stderr_logging(self):
        """SetTraceToStderr should set _TRACE_TO_STDERR to True."""
        repo_trace.SetTraceToStderr()
        self.assertTrue(repo_trace._TRACE_TO_STDERR)


@pytest.mark.unit
class SetTraceTests(unittest.TestCase):
    """Tests for SetTrace function."""

    def test_set_trace_enables_tracing(self):
        """SetTrace should set _TRACE to True."""
        repo_trace.SetTrace()
        self.assertTrue(repo_trace._TRACE)


@pytest.mark.unit
class GetTraceFileTests(unittest.TestCase):
    """Additional tests for _GetTraceFile."""

    def test_prints_location_when_not_quiet(self):
        """_GetTraceFile should print location when quiet=False."""
        with mock.patch("os.access", return_value=True):
            with mock.patch("builtins.print") as mock_print:
                repo_trace._GetTraceFile(quiet=False)
                mock_print.assert_called_once()
                call_args = mock_print.call_args[0][0]
                self.assertIn("Trace outputs", call_args)

    def test_does_not_print_when_quiet(self):
        """_GetTraceFile should not print when quiet=True."""
        with mock.patch("os.access", return_value=True):
            with mock.patch("builtins.print") as mock_print:
                repo_trace._GetTraceFile(quiet=True)
                mock_print.assert_not_called()


@pytest.mark.unit
class ClearOldTracesTests(unittest.TestCase):
    """Tests for _ClearOldTraces function."""

    def test_clear_old_traces_returns_early_if_file_small(self):
        """_ClearOldTraces should return early if file under limit."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("small content\n")
            temp_file = f.name
        try:
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", temp_file):
                with mock.patch("kanon_cli.repo.repo_trace._MAX_SIZE", 1):
                    # Should not raise
                    repo_trace._ClearOldTraces()
        finally:
            os.remove(temp_file)

    def test_clear_old_traces_handles_missing_file(self):
        """_ClearOldTraces should handle missing trace file."""
        with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", "/nonexistent/file"):
            # Should not raise
            repo_trace._ClearOldTraces()

    def test_clear_old_traces_removes_old_commands(self):
        """_ClearOldTraces should remove old commands when file is large."""
        import tempfile

        content = f"PID: 123 END: 456 :{repo_trace._NEW_COMMAND_SEP} old\nPID: 789 START: 012 :new\n"
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            # Write enough to exceed limit
            f.write(content * 1000)
            temp_file = f.name
        try:
            with mock.patch("kanon_cli.repo.repo_trace._TRACE_FILE", temp_file):
                with mock.patch("kanon_cli.repo.repo_trace._MAX_SIZE", 0.001):  # Very small limit
                    with mock.patch("kanon_cli.repo.platform_utils.rename"):
                        repo_trace._ClearOldTraces()
        finally:
            os.remove(temp_file)
