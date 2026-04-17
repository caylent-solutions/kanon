# Copyright (C) 2021 The Android Open Source Project
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

"""Unittests for the git_superproject.py module."""

import json
import os
import platform
import tempfile
import unittest
from unittest import mock

import pytest
from test_manifest_xml import sort_attributes

from kanon_cli.repo import git_superproject
from kanon_cli.repo import git_trace2_event_log
from kanon_cli.repo import manifest_xml


class SuperprojectTestCase(unittest.TestCase):
    """TestCase for the Superproject module."""

    PARENT_SID_KEY = "GIT_TRACE2_PARENT_SID"
    PARENT_SID_VALUE = "parent_sid"
    SELF_SID_REGEX = r"repo-\d+T\d+Z-.*"
    FULL_SID_REGEX = rf"^{PARENT_SID_VALUE}/{SELF_SID_REGEX}"

    def setUp(self):
        """Set up superproject every time."""
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.tempdir = self.tempdirobj.name
        self.repodir = os.path.join(self.tempdir, ".repo")
        self.manifest_file = os.path.join(self.repodir, manifest_xml.MANIFEST_FILE_NAME)
        os.mkdir(self.repodir)
        self.platform = platform.system().lower()

        # By default we initialize with the expected case where
        # repo launches us (so GIT_TRACE2_PARENT_SID is set).
        env = {
            self.PARENT_SID_KEY: self.PARENT_SID_VALUE,
        }
        self.git_event_log = git_trace2_event_log.EventLog(env=env)

        # The manifest parsing really wants a git repo currently.
        gitdir = os.path.join(self.repodir, "manifests.git")
        os.mkdir(gitdir)
        with open(os.path.join(gitdir, "config"), "w") as fp:
            fp.write(
                """[remote "origin"]
        url = https://localhost:0/manifest
"""
            )

        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <project path="art" name="platform/art" groups="notdefault,platform-"""
            + self.platform
            + """
  " /></manifest>
"""
        )
        self._superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("default-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )

    def tearDown(self):
        """Tear down superproject every time."""
        self.tempdirobj.cleanup()

    def getXmlManifest(self, data):
        """Helper to initialize a manifest for testing."""
        with open(self.manifest_file, "w") as fp:
            fp.write(data)
        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    def verifyCommonKeys(self, log_entry, expected_event_name, full_sid=True):
        """Helper function to verify common event log keys."""
        self.assertIn("event", log_entry)
        self.assertIn("sid", log_entry)
        self.assertIn("thread", log_entry)
        self.assertIn("time", log_entry)

        # Do basic data format validation.
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

    def verifyErrorEvent(self):
        """Helper to verify that error event is written."""

        with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
            log_path = self.git_event_log.Write(path=tempdir)
            self.log_data = self.readLog(log_path)

        self.assertEqual(len(self.log_data), 2)
        error_event = self.log_data[1]
        self.verifyCommonKeys(self.log_data[0], expected_event_name="version")
        self.verifyCommonKeys(error_event, expected_event_name="error")
        # Check for 'error' event specific fields.
        self.assertIn("msg", error_event)
        self.assertIn("fmt", error_event)

    def test_superproject_get_superproject_no_superproject(self):
        """Test with no url."""
        manifest = self.getXmlManifest(
            """
<manifest>
</manifest>
"""
        )
        self.assertIsNone(manifest.superproject)

    def test_superproject_get_superproject_invalid_url(self):
        """Test with an invalid url."""
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="test-remote" fetch="localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
"""
        )
        superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("test-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )
        sync_result = superproject.Sync(self.git_event_log)
        self.assertFalse(sync_result.success)
        self.assertTrue(sync_result.fatal)

    def test_superproject_get_superproject_invalid_branch(self):
        """Test with an invalid branch."""
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="test-remote" fetch="localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
"""
        )
        self._superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("test-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )
        with mock.patch.object(self._superproject, "_branch", "junk"):
            sync_result = self._superproject.Sync(self.git_event_log)
            self.assertFalse(sync_result.success)
            self.assertTrue(sync_result.fatal)
            self.verifyErrorEvent()

    def test_superproject_get_superproject_mock_init(self):
        """Test with _Init failing."""
        with mock.patch.object(self._superproject, "_Init", return_value=False):
            sync_result = self._superproject.Sync(self.git_event_log)
            self.assertFalse(sync_result.success)
            self.assertTrue(sync_result.fatal)

    def test_superproject_get_superproject_mock_fetch(self):
        """Test with _Fetch failing."""
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            os.mkdir(self._superproject._superproject_path)
            with mock.patch.object(self._superproject, "_Fetch", return_value=False):
                sync_result = self._superproject.Sync(self.git_event_log)
                self.assertFalse(sync_result.success)
                self.assertTrue(sync_result.fatal)

    def test_superproject_get_all_project_commit_ids_mock_ls_tree(self):
        """Test with LsTree being a mock."""
        data = (
            "120000 blob 158258bdf146f159218e2b90f8b699c4d85b5804\tAndroid.bp\x00"
            "160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00"
            "160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00"
            "120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00"
            "160000 commit ade9b7a0d874e25fff4bf2552488825c6f111928\tbuild/bazel\x00"
        )
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            with mock.patch.object(self._superproject, "_Fetch", return_value=True):
                with mock.patch.object(self._superproject, "_LsTree", return_value=data):
                    commit_ids_result = self._superproject._GetAllProjectsCommitIds()
                    self.assertEqual(
                        commit_ids_result.commit_ids,
                        {
                            "art": "2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea",
                            "bootable/recovery": "e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06",
                            "build/bazel": "ade9b7a0d874e25fff4bf2552488825c6f111928",
                        },
                    )
                    self.assertFalse(commit_ids_result.fatal)

    def test_superproject_write_manifest_file(self):
        """Test with writing manifest to a file after setting revisionId."""
        self.assertEqual(len(self._superproject._manifest.projects), 1)
        project = self._superproject._manifest.projects[0]
        project.SetRevisionId("ABCDEF")
        # Create temporary directory so that it can write the file.
        os.mkdir(self._superproject._superproject_path)
        manifest_path = self._superproject._WriteManifestFile()
        self.assertIsNotNone(manifest_path)
        with open(manifest_path) as fp:
            manifest_xml_data = fp.read()
        self.assertEqual(
            sort_attributes(manifest_xml_data),
            '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project groups="notdefault,platform-' + self.platform + '" '
            'name="platform/art" path="art" revision="ABCDEF" upstream="refs/heads/main"/>'
            '<superproject name="superproject"/>'
            "</manifest>",
        )

    def test_superproject_update_project_revision_id(self):
        """Test with LsTree being a mock."""
        self.assertEqual(len(self._superproject._manifest.projects), 1)
        projects = self._superproject._manifest.projects
        data = (
            "160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00"
            "160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00"
        )
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            with mock.patch.object(self._superproject, "_Fetch", return_value=True):
                with mock.patch.object(self._superproject, "_LsTree", return_value=data):
                    # Create temporary directory so that it can write the file.
                    os.mkdir(self._superproject._superproject_path)
                    update_result = self._superproject.UpdateProjectsRevisionId(projects, self.git_event_log)
                    self.assertIsNotNone(update_result.manifest_path)
                    self.assertFalse(update_result.fatal)
                    with open(update_result.manifest_path) as fp:
                        manifest_xml_data = fp.read()
                    self.assertEqual(
                        sort_attributes(manifest_xml_data),
                        '<?xml version="1.0" ?><manifest>'
                        '<remote fetch="http://localhost" name="default-remote"/>'
                        '<default remote="default-remote" revision="refs/heads/main"/>'
                        '<project groups="notdefault,platform-' + self.platform + '" '
                        'name="platform/art" path="art" '
                        'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea" upstream="refs/heads/main"/>'
                        '<superproject name="superproject"/>'
                        "</manifest>",
                    )

    def test_superproject_update_project_revision_id_no_superproject_tag(self):
        """Test update of commit ids of a manifest without superproject tag."""
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="test-name"/>
</manifest>
"""
        )
        self.maxDiff = None
        self.assertIsNone(manifest.superproject)
        self.assertEqual(
            sort_attributes(manifest.ToXml().toxml()),
            '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="test-name"/>'
            "</manifest>",
        )

    def test_superproject_update_project_revision_id_from_local_manifest_group(
        self,
    ):
        """Test update of commit ids of a manifest that have local manifest no superproject group."""
        local_group = manifest_xml.LOCAL_MANIFEST_GROUP_PREFIX + ":local"
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <remote name="goog" fetch="http://localhost2" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <project path="vendor/x" name="platform/vendor/x" remote="goog"
           groups=\""""
            + local_group
            + """
         " revision="master-with-vendor" clone-depth="1" />
  <project path="art" name="platform/art" groups="notdefault,platform-"""
            + self.platform
            + """
  " /></manifest>
"""
        )
        self.maxDiff = None
        self._superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("default-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )
        self.assertEqual(len(self._superproject._manifest.projects), 2)
        projects = self._superproject._manifest.projects
        data = "160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00"
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            with mock.patch.object(self._superproject, "_Fetch", return_value=True):
                with mock.patch.object(self._superproject, "_LsTree", return_value=data):
                    # Create temporary directory so that it can write the file.
                    os.mkdir(self._superproject._superproject_path)
                    update_result = self._superproject.UpdateProjectsRevisionId(projects, self.git_event_log)
                    self.assertIsNotNone(update_result.manifest_path)
                    self.assertFalse(update_result.fatal)
                    with open(update_result.manifest_path) as fp:
                        manifest_xml_data = fp.read()
                    # Verify platform/vendor/x's project revision hasn't
                    # changed.
                    self.assertEqual(
                        sort_attributes(manifest_xml_data),
                        '<?xml version="1.0" ?><manifest>'
                        '<remote fetch="http://localhost" name="default-remote"/>'
                        '<remote fetch="http://localhost2" name="goog"/>'
                        '<default remote="default-remote" revision="refs/heads/main"/>'
                        '<project groups="notdefault,platform-' + self.platform + '" '
                        'name="platform/art" path="art" '
                        'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea" upstream="refs/heads/main"/>'
                        '<superproject name="superproject"/>'
                        "</manifest>",
                    )

    def test_superproject_update_project_revision_id_with_pinned_manifest(self):
        """Test update of commit ids of a pinned manifest."""
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <project path="vendor/x" name="platform/vendor/x" revision="" />
  <project path="vendor/y" name="platform/vendor/y"
           revision="52d3c9f7c107839ece2319d077de0cd922aa9d8f" />
  <project path="art" name="platform/art" groups="notdefault,platform-"""
            + self.platform
            + """
  " /></manifest>
"""
        )
        self.maxDiff = None
        self._superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("default-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )
        self.assertEqual(len(self._superproject._manifest.projects), 3)
        projects = self._superproject._manifest.projects
        data = (
            "160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00"
            "160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tvendor/x\x00"
        )
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            with mock.patch.object(self._superproject, "_Fetch", return_value=True):
                with mock.patch.object(self._superproject, "_LsTree", return_value=data):
                    # Create temporary directory so that it can write the file.
                    os.mkdir(self._superproject._superproject_path)
                    update_result = self._superproject.UpdateProjectsRevisionId(projects, self.git_event_log)
                    self.assertIsNotNone(update_result.manifest_path)
                    self.assertFalse(update_result.fatal)
                    with open(update_result.manifest_path) as fp:
                        manifest_xml_data = fp.read()
                    # Verify platform/vendor/x's project revision hasn't
                    # changed.
                    self.assertEqual(
                        sort_attributes(manifest_xml_data),
                        '<?xml version="1.0" ?><manifest>'
                        '<remote fetch="http://localhost" name="default-remote"/>'
                        '<default remote="default-remote" revision="refs/heads/main"/>'
                        '<project groups="notdefault,platform-' + self.platform + '" '
                        'name="platform/art" path="art" '
                        'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea" upstream="refs/heads/main"/>'
                        '<project name="platform/vendor/x" path="vendor/x" '
                        'revision="e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06" upstream="refs/heads/main"/>'
                        '<project name="platform/vendor/y" path="vendor/y" '
                        'revision="52d3c9f7c107839ece2319d077de0cd922aa9d8f"/>'
                        '<superproject name="superproject"/>'
                        "</manifest>",
                    )

    def test_Fetch(self):
        manifest = self.getXmlManifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  " /></manifest>
"""
        )
        self.maxDiff = None
        self._superproject = git_superproject.Superproject(
            manifest,
            name="superproject",
            remote=manifest.remotes.get("default-remote").ToRemoteSpec("superproject"),
            revision="refs/heads/main",
        )
        os.mkdir(self._superproject._superproject_path)
        os.mkdir(self._superproject._work_git)
        with mock.patch.object(self._superproject, "_Init", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.GitCommand", autospec=True) as mock_git_command:
                with mock.patch("kanon_cli.repo.git_superproject.GitRefs.get", autospec=True) as mock_git_refs:
                    instance = mock_git_command.return_value
                    instance.Wait.return_value = 0
                    mock_git_refs.side_effect = ["", "1234"]

                    self.assertTrue(self._superproject._Fetch())
                    self.assertEqual(
                        # TODO: Once we require Python 3.8+,
                        #  use 'mock_git_command.call_args.args'.
                        mock_git_command.call_args[0],
                        (
                            None,
                            [
                                "fetch",
                                "http://localhost/superproject",
                                "--depth",
                                "1",
                                "--force",
                                "--no-tags",
                                "--filter",
                                "blob:none",
                                "refs/heads/main:refs/heads/main",
                            ],
                        ),
                    )

                    # If branch for revision exists, set as --negotiation-tip.
                    self.assertTrue(self._superproject._Fetch())
                    self.assertEqual(
                        # TODO: Once we require Python 3.8+,
                        #  use 'mock_git_command.call_args.args'.
                        mock_git_command.call_args[0],
                        (
                            None,
                            [
                                "fetch",
                                "http://localhost/superproject",
                                "--depth",
                                "1",
                                "--force",
                                "--no-tags",
                                "--filter",
                                "blob:none",
                                "--negotiation-tip",
                                "1234",
                                "refs/heads/main:refs/heads/main",
                            ],
                        ),
                    )


# Additional comprehensive tests below


@pytest.mark.unit
class TestSuperprojectExtended(unittest.TestCase):
    """Extended tests for Superproject class."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.tempdir = self.tempdirobj.name
        self.repodir = os.path.join(self.tempdir, ".repo")
        self.manifest_file = os.path.join(self.repodir, manifest_xml.MANIFEST_FILE_NAME)
        os.mkdir(self.repodir)

        env = {"GIT_TRACE2_PARENT_SID": "parent_sid"}
        self.git_event_log = git_trace2_event_log.EventLog(env=env)

        gitdir = os.path.join(self.repodir, "manifests.git")
        os.mkdir(gitdir)
        with open(os.path.join(gitdir, "config"), "w") as fp:
            fp.write('[remote "origin"]\nurl = https://localhost:0/manifest\n')

    def tearDown(self):
        """Clean up test fixtures."""
        self.tempdirobj.cleanup()

    def getXmlManifest(self, data):
        """Helper to initialize a manifest for testing."""
        with open(self.manifest_file, "w") as fp:
            fp.write(data)
        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    def test_init_sets_attributes(self):
        """Test __init__ sets all expected attributes."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")

        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        self.assertEqual(superproject.name, "super")
        self.assertEqual(superproject.remote, remote)
        self.assertEqual(superproject.revision, "refs/heads/main")
        self.assertIsNone(superproject._project_commit_ids)

    def test_SetQuiet(self):
        """Test SetQuiet() sets _quiet attribute."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        superproject.SetQuiet(True)
        self.assertTrue(superproject._quiet)

        superproject.SetQuiet(False)
        self.assertFalse(superproject._quiet)

    def test_SetPrintMessages(self):
        """Test SetPrintMessages() sets _print_messages attribute."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        superproject.SetPrintMessages(True)
        self.assertTrue(superproject._print_messages)

        superproject.SetPrintMessages(False)
        self.assertFalse(superproject._print_messages)

    def test_project_commit_ids_property(self):
        """Test project_commit_ids property returns stored value."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        test_ids = {"project1": "abc123", "project2": "def456"}
        superproject._project_commit_ids = test_ids

        self.assertEqual(superproject.project_commit_ids, test_ids)

    def test_manifest_path_property_exists(self):
        """Test manifest_path property when file exists."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        # Create the manifest file
        os.makedirs(superproject._superproject_path, exist_ok=True)
        with open(superproject._manifest_path, "w") as f:
            f.write("<manifest></manifest>")

        self.assertEqual(superproject.manifest_path, superproject._manifest_path)

    def test_manifest_path_property_not_exists(self):
        """Test manifest_path property when file doesn't exist."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        self.assertIsNone(superproject.manifest_path)

    def test_SkipUpdatingProjectRevisionId_no_path(self):
        """Test _SkipUpdatingProjectRevisionId with no path."""
        manifest = self.getXmlManifest(
            '<manifest><remote name="origin" fetch="http://localhost"/>'
            '<default remote="origin" revision="main"/>'
            '<superproject name="super"/></manifest>'
        )
        remote = manifest.remotes.get("origin").ToRemoteSpec("super")
        superproject = git_superproject.Superproject(manifest, "super", remote, "refs/heads/main")

        project = mock.MagicMock()
        project.relpath = None

        self.assertTrue(superproject._SkipUpdatingProjectRevisionId(project))


@pytest.mark.unit
class TestSuperprojectHelperFunctions(unittest.TestCase):
    """Tests for helper functions in git_superproject module."""

    def test_PrintMessages_with_use_superproject_set(self):
        """Test PrintMessages() when use_superproject is set."""
        manifest = mock.MagicMock()
        manifest.superproject = None

        self.assertTrue(git_superproject.PrintMessages(True, manifest))
        self.assertTrue(git_superproject.PrintMessages(False, manifest))

    def test_PrintMessages_with_manifest_superproject(self):
        """Test PrintMessages() when manifest has superproject."""
        manifest = mock.MagicMock()
        manifest.superproject = "superproject"

        self.assertTrue(git_superproject.PrintMessages(None, manifest))

    def test_PrintMessages_neither_set(self):
        """Test PrintMessages() when neither is set."""
        manifest = mock.MagicMock()
        manifest.superproject = None

        self.assertFalse(git_superproject.PrintMessages(None, manifest))

    def test_UseSuperproject_no_manifest_superproject(self):
        """Test UseSuperproject() with no manifest superproject."""
        manifest = mock.MagicMock()
        manifest.superproject = None

        self.assertFalse(git_superproject.UseSuperproject(None, manifest))
        self.assertFalse(git_superproject.UseSuperproject(True, manifest))
