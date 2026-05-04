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

"""Unit tests for event_log.py coverage."""

import json
from unittest import mock

import pytest

from kanon_cli.repo.event_log import EventLog, TASK_COMMAND, TASK_SYNC_NETWORK, TASK_SYNC_LOCAL


@pytest.mark.unit
def test_init():
    """Test EventLog initialization."""
    log = EventLog()
    assert log._log == []
    assert log._parent is None


@pytest.mark.unit
def test_add_basic():
    """Test Add method with basic event."""
    log = EventLog()
    event = log.Add("test-name", TASK_COMMAND, start=100)

    assert event["name"] == "test-name"
    assert event["task_name"] == TASK_COMMAND
    assert event["start_time"] == 100
    assert event["try"] == 1
    assert "id" in event
    assert len(log._log) == 1


@pytest.mark.unit
def test_add_with_finish():
    """Test Add method with finish time."""
    log = EventLog()
    event = log.Add("test-name", TASK_COMMAND, start=100, finish=200)

    assert event["finish_time"] == 200
    assert "status" in event


@pytest.mark.unit
def test_add_with_success():
    """Test Add method with success flag."""
    log = EventLog()
    event = log.Add("test-name", TASK_COMMAND, start=100, finish=200, success=True)

    assert event["status"] == "pass"


@pytest.mark.unit
def test_add_with_failure():
    """Test Add method with success=False."""
    log = EventLog()
    event = log.Add("test-name", TASK_COMMAND, start=100, finish=200, success=False)

    assert event["status"] == "fail"


@pytest.mark.unit
def test_add_with_try_count():
    """Test Add method with custom try_count."""
    log = EventLog()
    event = log.Add("test-name", TASK_COMMAND, start=100, try_count=3)

    assert event["try"] == 3


@pytest.mark.unit
def test_add_with_parent():
    """Test Add method with parent event."""
    log = EventLog()
    parent_event = log.Add("parent", TASK_COMMAND, start=100)
    log.SetParent(parent_event)
    child_event = log.Add("child", TASK_SYNC_NETWORK, start=110)

    assert "parent" in child_event
    assert child_event["parent"] == parent_event["id"]


@pytest.mark.unit
def test_add_sync():
    """Test AddSync method."""
    log = EventLog()
    project = mock.MagicMock()
    project.relpath = "path/to/project"
    project.name = "myproject"
    project.revisionExpr = "refs/heads/main"
    project.remote.url = "https://example.com/repo.git"
    project.remote.fetchUrl = "https://fetch.example.com/repo.git"
    project.GetCommitRevisionId.return_value = "abc123"

    event = log.AddSync(project, TASK_SYNC_NETWORK, start=100, finish=200, success=True)

    assert event["name"] == "path/to/project"
    assert event["project"] == "myproject"
    assert event["revision"] == "refs/heads/main"
    assert event["project_url"] == "https://example.com/repo.git"
    assert event["remote_url"] == "https://fetch.example.com/repo.git"
    assert event["git_hash"] == "abc123"


@pytest.mark.unit
def test_add_sync_without_revision():
    """Test AddSync when project has no revisionExpr."""
    log = EventLog()
    project = mock.MagicMock()
    project.relpath = "path/to/project"
    project.name = "myproject"
    project.revisionExpr = None
    project.remote.url = "https://example.com/repo.git"
    project.remote.fetchUrl = None
    project.GetCommitRevisionId.return_value = "abc123"

    event = log.AddSync(project, TASK_SYNC_LOCAL, start=100, finish=200, success=False)

    assert "revision" not in event
    assert "remote_url" not in event


@pytest.mark.unit
def test_add_sync_git_hash_exception():
    """Test AddSync handles exception from GetCommitRevisionId."""
    log = EventLog()
    project = mock.MagicMock()
    project.relpath = "path/to/project"
    project.name = "myproject"
    project.revisionExpr = "main"
    project.remote.url = "https://example.com/repo.git"
    project.remote.fetchUrl = "https://fetch.example.com/repo.git"
    project.GetCommitRevisionId.side_effect = Exception("git error")

    event = log.AddSync(project, TASK_SYNC_NETWORK, start=100, finish=200, success=True)

    # Should not have git_hash if exception occurred
    assert "git_hash" not in event


@pytest.mark.unit
def test_get_status_string_pass():
    """Test GetStatusString with success=True."""
    log = EventLog()
    assert log.GetStatusString(True) == "pass"


@pytest.mark.unit
def test_get_status_string_fail():
    """Test GetStatusString with success=False."""
    log = EventLog()
    assert log.GetStatusString(False) == "fail"


@pytest.mark.unit
def test_finish_event():
    """Test FinishEvent method."""
    log = EventLog()
    event = log.Add("test", TASK_COMMAND, start=100)

    log.FinishEvent(event, finish=200, success=True)

    assert event["finish_time"] == 200
    assert event["status"] == "pass"


@pytest.mark.unit
def test_set_parent():
    """Test SetParent method."""
    log = EventLog()
    parent = log.Add("parent", TASK_COMMAND, start=100)

    log.SetParent(parent)

    assert log._parent == parent


@pytest.mark.unit
def test_write():
    """Test Write method."""
    log = EventLog()
    log.Add("event1", TASK_COMMAND, start=100, finish=200, success=True)
    log.Add("event2", TASK_SYNC_NETWORK, start=150, finish=250, success=False)

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        log.Write("/tmp/event.log")

        mock_file.assert_called_once_with("/tmp/event.log", "w+")
        handle = mock_file()
        # Should write two lines (one per event)
        assert handle.write.call_count >= 2


@pytest.mark.unit
def test_write_json_format():
    """Test Write creates valid JSON."""
    log = EventLog()
    log.Add("event1", TASK_COMMAND, start=100, finish=200, success=True)

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        log.Write("/tmp/event.log")

        handle = mock_file()
        # Get all write calls
        writes = [call[0][0] for call in handle.write.call_args_list]
        json_line = "".join(writes).split("\n")[0]

        # Should be valid JSON
        parsed = json.loads(json_line)
        assert "name" in parsed
        assert "task_name" in parsed


@pytest.mark.unit
def test_add_custom_kind():
    """Test Add with custom kind parameter."""
    log = EventLog()
    event = log.Add("test", TASK_COMMAND, start=100, kind="CustomKind")

    assert event["id"][0] == "CustomKind"


@pytest.mark.unit
def test_multiple_events():
    """Test multiple events are logged."""
    log = EventLog()
    log.Add("event1", TASK_COMMAND, start=100)
    log.Add("event2", TASK_SYNC_NETWORK, start=200)
    log.Add("event3", TASK_SYNC_LOCAL, start=300)

    assert len(log._log) == 3


@pytest.mark.unit
def test_task_constants():
    """Test task name constants."""
    assert TASK_COMMAND == "command"
    assert TASK_SYNC_NETWORK == "sync-network"
    assert TASK_SYNC_LOCAL == "sync-local"


@pytest.mark.unit
def test_event_id_unique():
    """Test event IDs are unique."""
    log = EventLog()
    event1 = log.Add("test1", TASK_COMMAND, start=100)
    event2 = log.Add("test2", TASK_COMMAND, start=200)

    # IDs should be different
    assert event1["id"] != event2["id"]
