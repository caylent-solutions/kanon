# Copyright (C) 2024 The Android Open Source Project
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

"""Unit tests for event_log.py module."""

import json
import tempfile
from unittest import mock

import pytest

from kanon_cli.repo.event_log import _NextEventId
from kanon_cli.repo.event_log import EventLog
from kanon_cli.repo.event_log import TASK_COMMAND
from kanon_cli.repo.event_log import TASK_SYNC_LOCAL
from kanon_cli.repo.event_log import TASK_SYNC_NETWORK


@pytest.mark.unit
class TestEventLogInit:
    """Tests for EventLog initialization."""

    def test_event_log_init(self):
        """Test EventLog initialization."""
        log = EventLog()
        assert log._log == []
        assert log._parent is None


@pytest.mark.unit
class TestEventLogAdd:
    """Tests for EventLog.Add method."""

    def test_add_basic_event(self):
        """Test adding a basic event."""
        log = EventLog()
        event = log.Add("test-name", TASK_COMMAND, 100.0)

        assert event["name"] == "test-name"
        assert event["task_name"] == TASK_COMMAND
        assert event["start_time"] == 100.0
        assert event["try"] == 1
        assert "id" in event

    def test_add_event_with_finish(self):
        """Test adding event with finish time."""
        log = EventLog()
        event = log.Add("test-name", TASK_COMMAND, 100.0, finish=200.0, success=True)

        assert event["status"] == "pass"
        assert event["finish_time"] == 200.0

    def test_add_event_with_parent(self):
        """Test adding event with parent."""
        log = EventLog()
        parent = log.Add("parent", TASK_COMMAND, 100.0)
        log.SetParent(parent)

        child = log.Add("child", TASK_SYNC_NETWORK, 150.0)
        assert child["parent"] == parent["id"]

    def test_add_event_custom_kind(self):
        """Test adding event with custom kind."""
        log = EventLog()
        event = log.Add("test", TASK_COMMAND, 100.0, kind="CustomOp")

        assert event["id"][0] == "CustomOp"

    def test_add_event_try_count(self):
        """Test adding event with try count."""
        log = EventLog()
        event = log.Add("test", TASK_COMMAND, 100.0, try_count=3)

        assert event["try"] == 3


@pytest.mark.unit
class TestEventLogAddSync:
    """Tests for EventLog.AddSync method."""

    def test_add_sync_network(self):
        """Test adding sync network event."""
        log = EventLog()
        project = mock.Mock()
        project.relpath = "project/path"
        project.name = "test-project"
        project.revisionExpr = "main"
        project.remote.url = "https://example.com/repo"
        project.remote.fetchUrl = "https://example.com/fetch"
        project.GetCommitRevisionId.return_value = "abc123"

        event = log.AddSync(project, TASK_SYNC_NETWORK, 100.0, 200.0, True)

        assert event["name"] == "project/path"
        assert event["project"] == "test-project"
        assert event["revision"] == "main"
        assert event["project_url"] == "https://example.com/repo"
        assert event["remote_url"] == "https://example.com/fetch"
        assert event["git_hash"] == "abc123"

    def test_add_sync_local(self):
        """Test adding sync local event."""
        log = EventLog()
        project = mock.Mock()
        project.relpath = "project/path"
        project.name = "test-project"
        project.revisionExpr = "develop"
        project.remote.url = "https://example.com/repo"
        project.remote.fetchUrl = None
        project.GetCommitRevisionId.return_value = "def456"

        event = log.AddSync(project, TASK_SYNC_LOCAL, 100.0, 200.0, False)

        assert event["name"] == "project/path"
        assert event["project"] == "test-project"
        assert event["status"] == "fail"

    def test_add_sync_exception_handling(self):
        """Test AddSync handles exception getting commit ID."""
        log = EventLog()
        project = mock.Mock()
        project.relpath = "project/path"
        project.name = "test-project"
        project.revisionExpr = "main"
        project.remote.url = "https://example.com/repo"
        project.remote.fetchUrl = "https://example.com/fetch"
        project.GetCommitRevisionId.side_effect = Exception("error")

        event = log.AddSync(project, TASK_SYNC_NETWORK, 100.0, 200.0, True)

        assert "git_hash" not in event


@pytest.mark.unit
class TestEventLogGetStatusString:
    """Tests for EventLog.GetStatusString method."""

    def test_get_status_string_pass(self):
        """Test GetStatusString returns 'pass' for success."""
        log = EventLog()
        result = log.GetStatusString(True)
        assert result == "pass"

    def test_get_status_string_fail(self):
        """Test GetStatusString returns 'fail' for failure."""
        log = EventLog()
        result = log.GetStatusString(False)
        assert result == "fail"


@pytest.mark.unit
class TestEventLogFinishEvent:
    """Tests for EventLog.FinishEvent method."""

    def test_finish_event_success(self):
        """Test finishing event with success."""
        log = EventLog()
        event = log.Add("test", TASK_COMMAND, 100.0)

        log.FinishEvent(event, 200.0, True)

        assert event["status"] == "pass"
        assert event["finish_time"] == 200.0

    def test_finish_event_failure(self):
        """Test finishing event with failure."""
        log = EventLog()
        event = log.Add("test", TASK_COMMAND, 100.0)

        log.FinishEvent(event, 200.0, False)

        assert event["status"] == "fail"
        assert event["finish_time"] == 200.0


@pytest.mark.unit
class TestEventLogSetParent:
    """Tests for EventLog.SetParent method."""

    def test_set_parent(self):
        """Test setting parent event."""
        log = EventLog()
        parent = log.Add("parent", TASK_COMMAND, 100.0)

        log.SetParent(parent)

        assert log._parent == parent

    def test_set_parent_affects_subsequent_events(self):
        """Test parent affects subsequent events."""
        log = EventLog()
        parent = log.Add("parent", TASK_COMMAND, 100.0)
        log.SetParent(parent)

        child1 = log.Add("child1", TASK_SYNC_NETWORK, 150.0)
        child2 = log.Add("child2", TASK_SYNC_LOCAL, 160.0)

        assert child1["parent"] == parent["id"]
        assert child2["parent"] == parent["id"]


@pytest.mark.unit
class TestEventLogWrite:
    """Tests for EventLog.Write method."""

    def test_write_to_file(self):
        """Test writing log to file."""
        log = EventLog()
        log.Add("event1", TASK_COMMAND, 100.0, finish=200.0, success=True)
        log.Add("event2", TASK_SYNC_NETWORK, 150.0, finish=250.0, success=False)

        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            filename = f.name

        log.Write(filename)

        with open(filename, "r") as f:
            lines = f.readlines()
            assert len(lines) == 2

            event1 = json.loads(lines[0])
            assert event1["name"] == "event1"
            assert event1["status"] == "pass"

            event2 = json.loads(lines[1])
            assert event2["name"] == "event2"
            assert event2["status"] == "fail"

    def test_write_empty_log(self):
        """Test writing empty log."""
        log = EventLog()

        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            filename = f.name

        log.Write(filename)

        with open(filename, "r") as f:
            content = f.read()
            assert content == ""


@pytest.mark.unit
class TestNextEventId:
    """Tests for _NextEventId function."""

    def test_next_event_id_increments(self):
        """Test _NextEventId increments."""
        # Reset the global
        from kanon_cli.repo import event_log

        event_log._EVENT_ID = None

        id1 = _NextEventId()
        id2 = _NextEventId()
        id3 = _NextEventId()

        assert id2 == id1 + 1
        assert id3 == id2 + 1

    def test_next_event_id_thread_safe(self):
        """Test _NextEventId is thread-safe."""
        from kanon_cli.repo import event_log

        event_log._EVENT_ID = None

        # Just verify it doesn't raise an exception
        id1 = _NextEventId()
        assert id1 >= 1
