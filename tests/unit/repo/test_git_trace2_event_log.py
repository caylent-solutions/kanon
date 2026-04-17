# Copyright (C) 2020 The Android Open Source Project
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

"""Unittests for the git_trace2_event_log.py module."""

import json
import os
import socket
import tempfile
import threading
import unittest

import pytest
from unittest import mock

from kanon_cli.repo import git_trace2_event_log
from kanon_cli.repo import platform_utils


def serverLoggingThread(socket_path, server_ready, received_traces):
    """Helper function to receive logs over a Unix domain socket.

    Appends received messages on the provided socket and appends to
    received_traces.

    Args:
        socket_path: path to a Unix domain socket on which to listen for traces
        server_ready: a threading.Condition used to signal to the caller that
            this thread is ready to accept connections
        received_traces: a list to which received traces will be appended (after
            decoding to a utf-8 string).
    """
    platform_utils.remove(socket_path, missing_ok=True)
    data = b""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(socket_path)
        sock.listen(0)
        with server_ready:
            server_ready.notify()
        with sock.accept()[0] as conn:
            while True:
                recved = conn.recv(4096)
                if not recved:
                    break
                data += recved
    received_traces.extend(data.decode("utf-8").splitlines())


class EventLogTestCase(unittest.TestCase):
    """TestCase for the EventLog module."""

    PARENT_SID_KEY = "GIT_TRACE2_PARENT_SID"
    PARENT_SID_VALUE = "parent_sid"
    SELF_SID_REGEX = r"repo-\d+T\d+Z-.*"
    FULL_SID_REGEX = rf"^{PARENT_SID_VALUE}/{SELF_SID_REGEX}"

    def setUp(self):
        """Load the event_log module every time."""
        self._event_log_module = None
        # By default we initialize with the expected case where
        # repo launches us (so GIT_TRACE2_PARENT_SID is set).
        env = {
            self.PARENT_SID_KEY: self.PARENT_SID_VALUE,
        }
        self._event_log_module = git_trace2_event_log.EventLog(env=env)
        self._log_data = None

    def verifyCommonKeys(self, log_entry, expected_event_name=None, full_sid=True):
        """Helper function to verify common event log keys."""
        self.assertIn("event", log_entry)
        self.assertIn("sid", log_entry)
        self.assertIn("thread", log_entry)
        self.assertIn("time", log_entry)

        # Do basic data format validation.
        if expected_event_name:
            self.assertEqual(expected_event_name, log_entry["event"])
        if full_sid:
            self.assertRegex(log_entry["sid"], self.FULL_SID_REGEX)
        else:
            self.assertRegex(log_entry["sid"], self.SELF_SID_REGEX)
        self.assertRegex(log_entry["time"], r"^\d+-\d+-\d+T\d+:\d+:\d+\.\d+\+00:00$")

    def readLog(self, log_path):
        """Helper function to read log data into a list."""
        log_data = []
        with open(log_path, mode="rb") as f:
            for line in f:
                log_data.append(json.loads(line))
        return log_data

    def remove_prefix(self, s, prefix):
        """Return a copy string after removing |prefix| from |s|, if present or
        the original string."""
        if s.startswith(prefix):
            return s[len(prefix) :]
        else:
            return s

    def test_initial_state_with_parent_sid(self):
        """Test initial state when 'GIT_TRACE2_PARENT_SID' is set by parent."""
        self.assertRegex(self._event_log_module.full_sid, self.FULL_SID_REGEX)

    def test_initial_state_no_parent_sid(self):
        """Test initial state when 'GIT_TRACE2_PARENT_SID' is not set."""
        # Setup an empty environment dict (no parent sid).
        self._event_log_module = git_trace2_event_log.EventLog(env={})
        self.assertRegex(self._event_log_module.full_sid, self.SELF_SID_REGEX)

    def test_version_event(self):
        """Test 'version' event data is valid.

        Verify that the 'version' event is written even when no other
        events are addded.

        Expected event log:
        <version event>
        """
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        # A log with no added events should only have the version entry.
        self.assertEqual(len(self._log_data), 1)
        version_event = self._log_data[0]
        self.verifyCommonKeys(version_event, expected_event_name="version")
        # Check for 'version' event specific fields.
        self.assertIn("evt", version_event)
        self.assertIn("exe", version_event)
        # Verify "evt" version field is a string.
        self.assertIsInstance(version_event["evt"], str)

    def test_start_event(self):
        """Test and validate 'start' event data is valid.

        Expected event log:
        <version event>
        <start event>
        """
        self._event_log_module.StartEvent([])
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 2)
        start_event = self._log_data[1]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")
        self.verifyCommonKeys(start_event, expected_event_name="start")
        # Check for 'start' event specific fields.
        self.assertIn("argv", start_event)
        self.assertTrue(isinstance(start_event["argv"], list))

    def test_exit_event_result_none(self):
        """Test 'exit' event data is valid when result is None.

        We expect None result to be converted to 0 in the exit event data.

        Expected event log:
        <version event>
        <exit event>
        """
        self._event_log_module.ExitEvent(None)
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 2)
        exit_event = self._log_data[1]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")
        self.verifyCommonKeys(exit_event, expected_event_name="exit")
        # Check for 'exit' event specific fields.
        self.assertIn("code", exit_event)
        # 'None' result should convert to 0 (successful) return code.
        self.assertEqual(exit_event["code"], 0)

    def test_exit_event_result_integer(self):
        """Test 'exit' event data is valid when result is an integer.

        Expected event log:
        <version event>
        <exit event>
        """
        self._event_log_module.ExitEvent(2)
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 2)
        exit_event = self._log_data[1]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")
        self.verifyCommonKeys(exit_event, expected_event_name="exit")
        # Check for 'exit' event specific fields.
        self.assertIn("code", exit_event)
        self.assertEqual(exit_event["code"], 2)

    def test_command_event(self):
        """Test and validate 'command' event data is valid.

        Expected event log:
        <version event>
        <command event>
        """
        self._event_log_module.CommandEvent(name="repo", subcommands=["init", "this"])
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 2)
        command_event = self._log_data[1]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")
        self.verifyCommonKeys(command_event, expected_event_name="cmd_name")
        # Check for 'command' event specific fields.
        self.assertIn("name", command_event)
        self.assertEqual(command_event["name"], "repo-init-this")

    def test_def_params_event_repo_config(self):
        """Test 'def_params' event data outputs only repo config keys.

        Expected event log:
        <version event>
        <def_param event>
        <def_param event>
        """
        config = {
            "git.foo": "bar",
            "repo.partialclone": "true",
            "repo.partialclonefilter": "blob:none",
        }
        self._event_log_module.DefParamRepoEvents(config)

        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 3)
        def_param_events = self._log_data[1:]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")

        for event in def_param_events:
            self.verifyCommonKeys(event, expected_event_name="def_param")
            # Check for 'def_param' event specific fields.
            self.assertIn("param", event)
            self.assertIn("value", event)
            self.assertTrue(event["param"].startswith("repo."))

    def test_def_params_event_no_repo_config(self):
        """Test 'def_params' event data won't output non-repo config keys.

        Expected event log:
        <version event>
        """
        config = {
            "git.foo": "bar",
            "git.core.foo2": "baz",
        }
        self._event_log_module.DefParamRepoEvents(config)

        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 1)
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")

    def test_data_event_config(self):
        """Test 'data' event data outputs all config keys.

        Expected event log:
        <version event>
        <data event>
        <data event>
        """
        config = {
            "git.foo": "bar",
            "repo.partialclone": "false",
            "repo.syncstate.superproject.hassuperprojecttag": "true",
            "repo.syncstate.superproject.sys.argv": ["--", "sync", "protobuf"],
        }
        prefix_value = "prefix"
        self._event_log_module.LogDataConfigEvents(config, prefix_value)

        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 5)
        data_events = self._log_data[1:]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")

        for event in data_events:
            self.verifyCommonKeys(event)
            # Check for 'data' event specific fields.
            self.assertIn("key", event)
            self.assertIn("value", event)
            key = event["key"]
            key = self.remove_prefix(key, f"{prefix_value}/")
            value = event["value"]
            self.assertEqual(self._event_log_module.GetDataEventName(value), event["event"])
            self.assertTrue(key in config and value == config[key])

    def test_error_event(self):
        """Test and validate 'error' event data is valid.

        Expected event log:
        <version event>
        <error event>
        """
        msg = "invalid option: --cahced"
        fmt = "invalid option: %s"
        self._event_log_module.ErrorEvent(msg, fmt)
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self._event_log_module.Write(path=tempdir)
            self._log_data = self.readLog(log_path)

        self.assertEqual(len(self._log_data), 2)
        error_event = self._log_data[1]
        self.verifyCommonKeys(self._log_data[0], expected_event_name="version")
        self.verifyCommonKeys(error_event, expected_event_name="error")
        # Check for 'error' event specific fields.
        self.assertIn("msg", error_event)
        self.assertIn("fmt", error_event)
        self.assertEqual(error_event["msg"], f"RepoErrorEvent:{msg}")
        self.assertEqual(error_event["fmt"], f"RepoErrorEvent:{fmt}")

    def test_write_with_filename(self):
        """Test Write() with a path to a file exits with None."""
        self.assertIsNone(self._event_log_module.Write(path="path/to/file"))

    def test_write_with_git_config(self):
        """Test Write() uses the git config path when 'git config' call
        succeeds."""
        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            with mock.patch.object(
                self._event_log_module,
                "_GetEventTargetPath",
                return_value=tempdir,
            ):
                self.assertEqual(os.path.dirname(self._event_log_module.Write()), tempdir)

    def test_write_no_git_config(self):
        """Test Write() with no git config variable present exits with None."""
        with mock.patch.object(self._event_log_module, "_GetEventTargetPath", return_value=None):
            self.assertIsNone(self._event_log_module.Write())

    def test_write_non_string(self):
        """Test Write() with non-string type for |path| throws TypeError."""
        with self.assertRaises(TypeError):
            self._event_log_module.Write(path=1234)

    def test_write_socket(self):
        """Test Write() with Unix domain socket for |path| and validate received
        traces."""
        received_traces = []
        with tempfile.TemporaryDirectory(prefix="test_server_sockets") as tempdir:
            socket_path = os.path.join(tempdir, "server.sock")
            server_ready = threading.Condition()
            # Start "server" listening on Unix domain socket at socket_path.
            server_thread = threading.Thread(
                target=serverLoggingThread,
                args=(socket_path, server_ready, received_traces),
            )
            try:
                server_thread.start()

                with server_ready:
                    server_ready.wait(timeout=5)

                self._event_log_module.StartEvent([])
                path = self._event_log_module.Write(path=f"af_unix:{socket_path}")
            finally:
                server_thread.join(timeout=2)
                if server_thread.is_alive():
                    # Force cleanup if thread is still hanging
                    pass

        self.assertEqual(path, f"af_unix:stream:{socket_path}")
        self.assertEqual(len(received_traces), 2)
        version_event = json.loads(received_traces[0])
        start_event = json.loads(received_traces[1])
        self.verifyCommonKeys(version_event, expected_event_name="version")
        self.verifyCommonKeys(start_event, expected_event_name="start")
        # Check for 'start' event specific fields.
        self.assertIn("argv", start_event)
        self.assertIsInstance(start_event["argv"], list)


# Additional comprehensive tests below


@pytest.mark.unit
class TestBaseEventLogExtended(unittest.TestCase):
    """Extended tests for BaseEventLog class."""

    def setUp(self):
        """Set up test fixtures."""
        self.env = {"GIT_TRACE2_PARENT_SID": "parent_sid"}
        self.event_log = git_trace2_event_log.BaseEventLog(env=self.env)

    def test_init_without_env(self):
        """Test __init__ without env parameter."""
        event_log = git_trace2_event_log.BaseEventLog()
        self.assertIsNotNone(event_log._full_sid)

    def test_init_with_repo_source_version(self):
        """Test __init__ with repo_source_version."""
        event_log = git_trace2_event_log.BaseEventLog(repo_source_version="1.2.3")
        # Should have version event at the start
        self.assertEqual(len(event_log._log), 1)
        self.assertEqual(event_log._log[0]["event"], "version")
        self.assertEqual(event_log._log[0]["exe"], "1.2.3")

    def test_init_with_add_init_count(self):
        """Test __init__ with add_init_count=True."""
        event_log1 = git_trace2_event_log.BaseEventLog(add_init_count=True)
        event_log2 = git_trace2_event_log.BaseEventLog(add_init_count=True)
        # SIDs should be different due to init count
        self.assertNotEqual(event_log1._sid, event_log2._sid)

    def test_full_sid_property(self):
        """Test full_sid property."""
        self.assertIn("parent_sid", self.event_log.full_sid)
        self.assertIn("repo-", self.event_log.full_sid)

    def test_CreateEventDict_creates_dict_with_common_fields(self):
        """Test _CreateEventDict() creates dict with common fields."""
        event_dict = self.event_log._CreateEventDict("test_event")
        self.assertIn("event", event_dict)
        self.assertIn("sid", event_dict)
        self.assertIn("thread", event_dict)
        self.assertIn("time", event_dict)
        self.assertEqual(event_dict["event"], "test_event")

    def test_StartEvent_appends_to_log(self):
        """Test StartEvent() appends start event to log."""
        self.event_log.StartEvent(["repo", "sync"])
        self.assertEqual(len(self.event_log._log), 1)
        self.assertEqual(self.event_log._log[0]["event"], "start")
        self.assertEqual(self.event_log._log[0]["argv"], ["repo", "sync"])

    def test_ExitEvent_with_zero_result(self):
        """Test ExitEvent() with result=0."""
        self.event_log.ExitEvent(0)
        self.assertEqual(len(self.event_log._log), 1)
        self.assertEqual(self.event_log._log[0]["event"], "exit")
        self.assertEqual(self.event_log._log[0]["code"], 0)

    def test_ExitEvent_with_nonzero_result(self):
        """Test ExitEvent() with non-zero result."""
        self.event_log.ExitEvent(1)
        exit_event = self.event_log._log[0]
        self.assertEqual(exit_event["code"], 1)

    def test_ExitEvent_includes_t_abs(self):
        """Test ExitEvent() includes t_abs field."""
        self.event_log.ExitEvent(0)
        exit_event = self.event_log._log[0]
        self.assertIn("t_abs", exit_event)
        self.assertIsInstance(exit_event["t_abs"], float)

    def test_CommandEvent_appends_to_log(self):
        """Test CommandEvent() appends command event to log."""
        self.event_log.CommandEvent("repo", ["sync", "project"])
        self.assertEqual(len(self.event_log._log), 1)
        cmd_event = self.event_log._log[0]
        self.assertEqual(cmd_event["event"], "cmd_name")
        self.assertEqual(cmd_event["name"], "repo-sync-project")
        self.assertEqual(cmd_event["hierarchy"], "repo-sync-project")

    def test_LogConfigEvents(self):
        """Test LogConfigEvents() logs multiple config entries."""
        config = {
            "key1": "value1",
            "key2": "value2",
        }
        self.event_log.LogConfigEvents(config, "test_event")
        self.assertEqual(len(self.event_log._log), 2)
        for event in self.event_log._log:
            self.assertEqual(event["event"], "test_event")
            self.assertIn("param", event)
            self.assertIn("value", event)

    def test_DefParamRepoEvents_filters_repo_keys(self):
        """Test DefParamRepoEvents() only logs repo.* keys."""
        config = {
            "repo.key1": "value1",
            "git.key2": "value2",
            "repo.key3": "value3",
        }
        self.event_log.DefParamRepoEvents(config)
        # Should only log 2 entries (repo.* keys)
        self.assertEqual(len(self.event_log._log), 2)
        for event in self.event_log._log:
            self.assertTrue(event["param"].startswith("repo."))

    def test_GetDataEventName_with_array(self):
        """Test GetDataEventName() returns 'data-json' for arrays."""
        result = self.event_log.GetDataEventName('["item1", "item2"]')
        self.assertEqual(result, "data-json")

    def test_GetDataEventName_with_string(self):
        """Test GetDataEventName() returns 'data' for non-arrays."""
        result = self.event_log.GetDataEventName("simple string")
        self.assertEqual(result, "data")

    def test_LogDataConfigEvents(self):
        """Test LogDataConfigEvents() logs data events with prefix."""
        config = {"key1": "value1", "key2": '["item1"]'}
        self.event_log.LogDataConfigEvents(config, "prefix")
        self.assertEqual(len(self.event_log._log), 2)
        for event in self.event_log._log:
            self.assertIn(event["event"], ["data", "data-json"])
            self.assertTrue(event["key"].startswith("prefix/"))

    def test_ErrorEvent_appends_to_log(self):
        """Test ErrorEvent() appends error event to log."""
        self.event_log.ErrorEvent("error occurred")
        self.assertEqual(len(self.event_log._log), 1)
        error_event = self.event_log._log[0]
        self.assertEqual(error_event["event"], "error")
        self.assertIn("RepoErrorEvent:", error_event["msg"])
        self.assertIn("RepoErrorEvent:", error_event["fmt"])

    def test_ErrorEvent_with_fmt(self):
        """Test ErrorEvent() with custom fmt parameter."""
        self.event_log.ErrorEvent("error %s", fmt="error format")
        error_event = self.event_log._log[0]
        self.assertIn("error %s", error_event["msg"])
        self.assertIn("error format", error_event["fmt"])

    def test_Write_with_none_path(self):
        """Test Write() returns None when path is None."""
        result = self.event_log.Write(path=None)
        self.assertIsNone(result)

    def test_Write_with_non_directory_path(self):
        """Test Write() returns None when path is not a directory."""
        result = self.event_log.Write(path="/nonexistent/file.txt")
        self.assertIsNone(result)

    def test_Write_with_invalid_type(self):
        """Test Write() raises TypeError with invalid path type."""
        with self.assertRaises(TypeError):
            self.event_log.Write(path=123)

    def test_Write_with_directory(self):
        """Test Write() writes to directory."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = self.event_log.Write(path=tmpdir)
            self.assertIsNotNone(log_path)
            self.assertTrue(os.path.exists(log_path))

    def test_WriteLog_writes_json_lines(self):
        """Test _WriteLog() writes JSON lines."""
        self.event_log.StartEvent(["test"])
        output = []

        def write_fn(data):
            output.append(data)

        self.event_log._WriteLog(write_fn)
        self.assertGreater(len(output), 0)
        # Each line should be valid JSON
        import json

        for line in output:
            json.loads(line.decode("utf-8"))


@pytest.mark.unit
class TestBaseEventLogSocketWrite(unittest.TestCase):
    """Tests for BaseEventLog socket writing."""

    def setUp(self):
        """Set up test fixtures."""
        self.event_log = git_trace2_event_log.BaseEventLog()

    def test_Write_with_af_unix_stream_prefix(self):
        """Test Write() with af_unix:stream: prefix."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "test.sock")

            # Create a server thread
            received = []
            server_ready = threading.Condition()

            def server():
                platform_utils.remove(sock_path, missing_ok=True)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.bind(sock_path)
                    s.listen(1)
                    with server_ready:
                        server_ready.notify()
                    conn, _ = s.accept()
                    with conn:
                        data = conn.recv(4096)
                        received.append(data)

            server_thread = threading.Thread(target=server)
            server_thread.start()

            try:
                with server_ready:
                    server_ready.wait(timeout=5)

                self.event_log.StartEvent(["test"])
                result = self.event_log.Write(path=f"af_unix:stream:{sock_path}")
                self.assertEqual(result, f"af_unix:stream:{sock_path}")
            finally:
                server_thread.join(timeout=2)

            self.assertGreater(len(received), 0)

    def test_Write_with_af_unix_dgram_prefix(self):
        """Test Write() with af_unix:dgram: prefix."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "test.sock")

            # Create a datagram server
            received = []

            def server():
                platform_utils.remove(sock_path, missing_ok=True)
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
                    s.bind(sock_path)
                    s.settimeout(2)
                    try:
                        while True:
                            data, _ = s.recvfrom(4096)
                            if data:
                                received.append(data)
                            else:
                                break
                    except socket.timeout:
                        pass

            server_thread = threading.Thread(target=server)
            server_thread.start()

            try:
                # Give server time to start
                import time

                time.sleep(0.1)

                self.event_log.StartEvent(["test"])
                result = self.event_log.Write(path=f"af_unix:dgram:{sock_path}")
                if result:
                    self.assertEqual(result, f"af_unix:dgram:{sock_path}")
            finally:
                server_thread.join(timeout=3)


@pytest.mark.unit
class TestBaseEventLogEdgeCases(unittest.TestCase):
    """Edge case tests for BaseEventLog."""

    def test_AddVersionEvent_prepends_to_log(self):
        """Test _AddVersionEvent() prepends version event."""
        event_log = git_trace2_event_log.BaseEventLog()
        event_log.StartEvent(["test"])
        event_log._AddVersionEvent("2.0.0")
        # Version event should be first
        self.assertEqual(event_log._log[0]["event"], "version")
        self.assertEqual(event_log._log[0]["exe"], "2.0.0")
        self.assertEqual(event_log._log[0]["evt"], "2")

    def test_CommandEvent_with_empty_subcommands(self):
        """Test CommandEvent() with empty subcommands list."""
        event_log = git_trace2_event_log.BaseEventLog()
        event_log.CommandEvent("repo", [])
        cmd_event = event_log._log[0]
        self.assertEqual(cmd_event["name"], "repo-")

    def test_CommandEvent_with_multiple_subcommands(self):
        """Test CommandEvent() with multiple subcommands."""
        event_log = git_trace2_event_log.BaseEventLog()
        event_log.CommandEvent("repo", ["sync", "--force", "project"])
        cmd_event = event_log._log[0]
        self.assertEqual(cmd_event["name"], "repo-sync---force-project")

    def test_multiple_events_in_sequence(self):
        """Test adding multiple events in sequence."""
        event_log = git_trace2_event_log.BaseEventLog()
        event_log.StartEvent(["test"])
        event_log.CommandEvent("repo", ["sync"])
        event_log.ErrorEvent("test error")
        event_log.ExitEvent(1)

        self.assertEqual(len(event_log._log), 4)
        self.assertEqual(event_log._log[0]["event"], "start")
        self.assertEqual(event_log._log[1]["event"], "cmd_name")
        self.assertEqual(event_log._log[2]["event"], "error")
        self.assertEqual(event_log._log[3]["event"], "exit")

    def test_LogConfigEvents_empty_config(self):
        """Test LogConfigEvents() with empty config."""
        event_log = git_trace2_event_log.BaseEventLog()
        event_log.LogConfigEvents({}, "test")
        self.assertEqual(len(event_log._log), 0)

    def test_DefParamRepoEvents_no_repo_keys(self):
        """Test DefParamRepoEvents() with no repo.* keys."""
        event_log = git_trace2_event_log.BaseEventLog()
        config = {"git.key": "value", "other.key": "value"}
        event_log.DefParamRepoEvents(config)
        self.assertEqual(len(event_log._log), 0)

    def test_LogDataConfigEvents_empty_prefix(self):
        """Test LogDataConfigEvents() with empty prefix."""
        event_log = git_trace2_event_log.BaseEventLog()
        config = {"key": "value"}
        event_log.LogDataConfigEvents(config, "")
        data_event = event_log._log[0]
        self.assertEqual(data_event["key"], "/key")

    def test_GetDataEventName_edge_cases(self):
        """Test GetDataEventName() with edge cases."""
        event_log = git_trace2_event_log.BaseEventLog()

        # Just brackets
        self.assertEqual(event_log.GetDataEventName("[]"), "data-json")

        # Bracket in middle
        self.assertEqual(event_log.GetDataEventName("a[b]c"), "data")

        # Start with bracket but not end
        self.assertEqual(event_log.GetDataEventName("[abc"), "data")

        # Normal array value
        self.assertEqual(event_log.GetDataEventName("[1,2,3]"), "data-json")

    def test_Write_creates_unique_filenames(self):
        """Test Write() creates unique filenames."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            event_log1 = git_trace2_event_log.BaseEventLog()
            event_log2 = git_trace2_event_log.BaseEventLog()

            path1 = event_log1.Write(path=tmpdir)
            path2 = event_log2.Write(path=tmpdir)

            self.assertNotEqual(path1, path2)
            self.assertTrue(os.path.exists(path1))
            self.assertTrue(os.path.exists(path2))
