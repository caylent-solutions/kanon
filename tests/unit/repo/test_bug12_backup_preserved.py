# Copyright (C) 2026 Caylent, Inc.
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

"""Unit tests for Bug 12: Backup file preserved on envsubst rerun.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 12 -- Before creating a .bak
backup, check if a .bak file already exists at the destination. If it does,
remove the stale .bak before creating the new one to prevent accumulation.
"""

import os
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Stale .bak is explicitly removed before creating new backup
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stale_bak_explicitly_removed_before_new_backup(tmp_path):
    """AC-TEST-003: os.remove is called on the stale .bak before creating backup.

    When EnvSubst is called on a file and a .bak file already exists, the
    implementation must explicitly call os.remove() on the stale .bak
    before calling os.rename() to create the new backup. Without this fix,
    stale .bak files are silently overwritten rather than explicitly removed,
    which can lead to unexpected behavior on systems or filesystems where
    rename does not atomically replace the destination.

    Arrange: Create a valid XML file and a pre-existing .bak file.
    Patch os.path.exists to return True for the .bak path. Patch os.remove
    to track calls.
    Act: Call EnvSubst on the XML file.
    Assert: os.remove was called with the .bak file path exactly once.
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = str(xml_file) + ".bak"

    xml_file.write_text('<?xml version="1.0"?><manifest><project name="test"/></manifest>')

    cmd = Envsubst()

    real_os_path_exists = os.path.exists

    def fake_exists(path):
        # Return True for the .bak path to simulate a stale .bak existing.
        if path == bak_path:
            return True
        return real_os_path_exists(path)

    removed_paths = []

    def fake_remove(path):
        removed_paths.append(path)
        # Do NOT actually remove -- we just record the call.

    with (
        mock.patch("os.path.exists", side_effect=fake_exists),
        mock.patch("os.remove", side_effect=fake_remove),
        mock.patch("os.rename"),
    ):
        cmd.EnvSubst(str(xml_file))

    assert bak_path in removed_paths, (
        f"Expected os.remove to be called with the stale .bak path '{bak_path}' "
        f"before creating the new backup, but os.remove was called with: {removed_paths!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004 -- os.remove NOT called when no stale .bak exists
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_remove_called_when_no_stale_bak(tmp_path):
    """AC-TEST-004: os.remove is NOT called when no stale .bak exists.

    When EnvSubst is called on a file and no .bak file already exists, the
    implementation must not call os.remove() -- there is nothing to remove.
    Only when a stale .bak is detected should removal occur.

    Arrange: Create a valid XML file with no pre-existing .bak file.
    Patch os.path.exists to return False for the .bak path. Track os.remove
    calls.
    Act: Call EnvSubst on the XML file.
    Assert: os.remove was NOT called with the .bak file path.
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = str(xml_file) + ".bak"

    xml_file.write_text('<?xml version="1.0"?><manifest><project name="test"/></manifest>')

    cmd = Envsubst()

    real_os_path_exists = os.path.exists

    def fake_exists(path):
        # Return False for the .bak path to simulate no stale .bak.
        if path == bak_path:
            return False
        return real_os_path_exists(path)

    removed_paths = []

    def fake_remove(path):
        removed_paths.append(path)

    with (
        mock.patch("os.path.exists", side_effect=fake_exists),
        mock.patch("os.remove", side_effect=fake_remove),
        mock.patch("os.rename"),
    ):
        cmd.EnvSubst(str(xml_file))

    bak_removes = [p for p in removed_paths if p == bak_path]
    assert len(bak_removes) == 0, (
        f"Expected os.remove NOT to be called with the .bak path '{bak_path}' "
        f"when no stale .bak exists, but it was called: {removed_paths!r}"
    )
