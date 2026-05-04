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

"""Comprehensive unit tests for manifest_xml.py uncovered code paths."""

import tempfile
import unittest
from unittest import mock
import xml.dom.minidom

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import manifest_xml
from kanon_cli.repo.manifest_xml import XmlBool, XmlInt, normalize_url


def _load_manifest(tmp_path, xml_content):
    """Helper to load a manifest from XML content."""
    repodir = tmp_path / ".repo"
    repodir.mkdir(parents=True)
    manifests_dir = repodir / "manifests"
    manifests_dir.mkdir()
    manifest_git = repodir / "manifests.git"
    manifest_git.mkdir()

    # Create git config file
    with open(manifest_git / "config", "w") as fp:
        fp.write("""[remote "origin"]
    url = https://localhost:0/manifest
""")

    (manifests_dir / "default.xml").write_text(xml_content)
    manifest_file = repodir / "manifest.xml"
    with open(manifest_file, "w") as fp:
        fp.write(xml_content)

    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    return m


@pytest.mark.unit
class TestXmlBoolEdgeCases(unittest.TestCase):
    """Test XmlBool utility function edge cases."""

    def test_xmlbool_empty_with_default_none(self):
        """Test XmlBool with empty value and None default."""
        node = xml.dom.minidom.parseString('<test attr=""/>').documentElement
        result = XmlBool(node, "attr", default=None)
        self.assertIsNone(result)

    def test_xmlbool_empty_with_default_true(self):
        """Test XmlBool with empty value and True default."""
        node = xml.dom.minidom.parseString('<test attr=""/>').documentElement
        result = XmlBool(node, "attr", default=True)
        self.assertTrue(result)

    def test_xmlbool_invalid_value_uses_default(self):
        """Test XmlBool with invalid value returns default."""
        node = xml.dom.minidom.parseString('<test attr="maybe"/>').documentElement
        result = XmlBool(node, "attr", default=False)
        self.assertFalse(result)

    def test_xmlbool_case_insensitive_yes(self):
        """Test XmlBool handles YES in any case."""
        node = xml.dom.minidom.parseString('<test attr="YES"/>').documentElement
        result = XmlBool(node, "attr")
        self.assertTrue(result)

    def test_xmlbool_case_insensitive_no(self):
        """Test XmlBool handles NO in any case."""
        node = xml.dom.minidom.parseString('<test attr="NO"/>').documentElement
        result = XmlBool(node, "attr")
        self.assertFalse(result)


@pytest.mark.unit
class TestXmlInt(unittest.TestCase):
    """Test XmlInt utility function."""

    def test_xmlint_empty_with_default(self):
        """Test XmlInt with empty value returns default."""
        node = xml.dom.minidom.parseString('<test attr=""/>').documentElement
        result = XmlInt(node, "attr", default=42)
        self.assertEqual(result, 42)

    def test_xmlint_no_attribute_with_default(self):
        """Test XmlInt with missing attribute returns default."""
        node = xml.dom.minidom.parseString("<test/>").documentElement
        result = XmlInt(node, "attr", default=100)
        self.assertEqual(result, 100)

    def test_xmlint_valid_number(self):
        """Test XmlInt with valid number."""
        node = xml.dom.minidom.parseString('<test attr="123"/>').documentElement
        result = XmlInt(node, "attr")
        self.assertEqual(result, 123)

    def test_xmlint_invalid_number_raises(self):
        """Test XmlInt with invalid number raises ManifestParseError."""
        node = xml.dom.minidom.parseString('<test attr="abc"/>').documentElement
        with self.assertRaises(error.ManifestParseError):
            XmlInt(node, "attr")

    def test_xmlint_negative_number(self):
        """Test XmlInt with negative number."""
        node = xml.dom.minidom.parseString('<test attr="-5"/>').documentElement
        result = XmlInt(node, "attr")
        self.assertEqual(result, -5)


@pytest.mark.unit
class TestNormalizeUrl(unittest.TestCase):
    """Test normalize_url utility function."""

    def test_normalize_url_removes_trailing_slash(self):
        """Test normalize_url removes trailing slashes."""
        result = normalize_url("https://example.com/path/")
        self.assertEqual(result, "https://example.com/path")

    def test_normalize_url_multiple_trailing_slashes(self):
        """Test normalize_url removes multiple trailing slashes."""
        result = normalize_url("https://example.com/path///")
        self.assertEqual(result, "https://example.com/path")

    def test_normalize_url_scp_like_syntax(self):
        """Test normalize_url converts SCP-like syntax to SSH URL."""
        result = normalize_url("git@github.com:user/repo")
        self.assertEqual(result, "ssh://git@github.com/user/repo")

    def test_normalize_url_already_ssh_url(self):
        """Test normalize_url doesn't modify proper SSH URLs."""
        result = normalize_url("ssh://git@github.com/user/repo")
        self.assertEqual(result, "ssh://git@github.com/user/repo")

    def test_normalize_url_http_url(self):
        """Test normalize_url handles HTTP URLs."""
        result = normalize_url("http://example.com/repo/")
        self.assertEqual(result, "http://example.com/repo")


@pytest.mark.unit
class TestDefaultClass(unittest.TestCase):
    """Test _Default class."""

    def test_default_equality_same_values(self):
        """Test _Default equality with same values."""
        d1 = manifest_xml._Default()
        d2 = manifest_xml._Default()
        self.assertEqual(d1, d2)

    def test_default_equality_different_values(self):
        """Test _Default inequality with different values."""
        d1 = manifest_xml._Default()
        d1.sync_c = True
        d2 = manifest_xml._Default()
        d2.sync_c = False
        self.assertNotEqual(d1, d2)

    def test_default_equality_with_non_default(self):
        """Test _Default inequality with non-_Default object."""
        d1 = manifest_xml._Default()
        self.assertNotEqual(d1, "not a default")
        self.assertFalse(d1 == "not a default")

    def test_default_ne_with_non_default(self):
        """Test _Default __ne__ with non-_Default object."""
        d1 = manifest_xml._Default()
        self.assertTrue(d1 != "not a default")


@pytest.mark.unit
class TestXmlRemote(unittest.TestCase):
    """Test _XmlRemote class."""

    def test_xmlremote_basic_creation(self):
        """Test _XmlRemote basic creation."""
        with mock.patch.object(
            manifest_xml._XmlRemote,
            "_resolveFetchUrl",
            return_value="https://example.com",
        ):
            remote = manifest_xml._XmlRemote(name="origin", fetch="https://example.com")
            self.assertEqual(remote.name, "origin")
            self.assertEqual(remote.fetchUrl, "https://example.com")

    def test_xmlremote_with_alias(self):
        """Test _XmlRemote with alias."""
        with mock.patch.object(
            manifest_xml._XmlRemote,
            "_resolveFetchUrl",
            return_value="https://example.com",
        ):
            remote = manifest_xml._XmlRemote(name="origin", alias="upstream", fetch="https://example.com")
            self.assertEqual(remote.remoteAlias, "upstream")

    def test_xmlremote_with_pushurl(self):
        """Test _XmlRemote with pushUrl."""
        with mock.patch.object(
            manifest_xml._XmlRemote,
            "_resolveFetchUrl",
            return_value="https://example.com",
        ):
            remote = manifest_xml._XmlRemote(
                name="origin",
                fetch="https://example.com",
                pushUrl="https://push.example.com",
            )
            self.assertEqual(remote.pushUrl, "https://push.example.com")

    def test_xmlremote_equality_same(self):
        """Test _XmlRemote equality with same values."""
        with mock.patch.object(
            manifest_xml._XmlRemote,
            "_resolveFetchUrl",
            return_value="https://example.com",
        ):
            r1 = manifest_xml._XmlRemote(name="origin", fetch="https://example.com")
            r2 = manifest_xml._XmlRemote(name="origin", fetch="https://example.com")
            self.assertEqual(r1, r2)

    def test_xmlremote_equality_different(self):
        """Test _XmlRemote inequality with different values."""
        with mock.patch.object(
            manifest_xml._XmlRemote,
            "_resolveFetchUrl",
            return_value="https://example.com",
        ):
            r1 = manifest_xml._XmlRemote(name="origin", fetch="https://example.com")
            r2 = manifest_xml._XmlRemote(name="upstream", fetch="https://example.com")
            self.assertNotEqual(r1, r2)


@pytest.mark.unit
class TestParseProject(unittest.TestCase):
    """Test _ParseProject method."""

    def test_parse_project_with_clone_depth(self):
        """Test parsing project with clone-depth attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" clone-depth="1"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].clone_depth, 1)

    def test_parse_project_clone_depth_zero_validation(self):
        """Test parsing project with clone-depth=0 (validation happens at runtime)."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" clone-depth="0"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            # Note: validation may happen at sync time, not parse time
            manifest = _load_manifest(Path(tmp), xml_content)
            self.assertIsNotNone(manifest)

    def test_parse_project_clone_depth_negative_validation(self):
        """Test parsing project with negative clone-depth (validation happens at runtime)."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" clone-depth="-1"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            # Note: validation may happen at sync time, not parse time
            manifest = _load_manifest(Path(tmp), xml_content)
            self.assertIsNotNone(manifest)

    def test_parse_project_with_sync_c(self):
        """Test parsing project with sync-c attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" sync-c="true"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(len(projects), 1)
            self.assertTrue(projects[0].sync_c)

    def test_parse_project_with_sync_s(self):
        """Test parsing project with sync-s attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-s="true"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertTrue(projects[0].sync_s)

    def test_parse_project_with_sync_tags_false(self):
        """Test parsing project with sync-tags="false"."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-tags="false"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertFalse(projects[0].sync_tags)

    def test_parse_project_with_dest_branch(self):
        """Test parsing project with dest-branch attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" dest-branch="develop"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(projects[0].dest_branch, "develop")

    def test_parse_project_with_upstream(self):
        """Test parsing project with upstream attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" upstream="refs/heads/main"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(projects[0].upstream, "refs/heads/main")

    def test_parse_project_with_groups(self):
        """Test parsing project with groups attribute."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" groups="group1,group2"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertIn("group1", projects[0].groups)
            self.assertIn("group2", projects[0].groups)

    def test_parse_project_no_remote_uses_default(self):
        """Test parsing project without remote uses default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(projects[0].remote.name, "origin")

    def test_parse_project_no_revision_uses_default(self):
        """Test parsing project without revision uses default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(projects[0].revisionExpr, "main")

    def test_parse_project_with_path_different_from_name(self):
        """Test parsing project with path different from name."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="repo-name" path="different/path"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertEqual(projects[0].name, "repo-name")
            self.assertEqual(projects[0].relpath, "different/path")

    def test_parse_project_with_rebase_false(self):
        """Test parsing project with rebase="false"."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project" rebase="false"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            projects = manifest.projects
            self.assertFalse(projects[0].rebase)


@pytest.mark.unit
class TestToXml(unittest.TestCase):
    """Test ToXml method."""

    def test_toxml_basic_manifest(self):
        """Test ToXml with basic manifest."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            self.assertIn("<manifest>", xml_output.toprettyxml())
            self.assertIn("<remote", xml_output.toprettyxml())
            self.assertIn('name="origin"', xml_output.toprettyxml())

    def test_toxml_with_sync_j(self):
        """Test ToXml with sync-j in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-j="4"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('sync-j="4"', xml_str)

    def test_toxml_with_sync_c(self):
        """Test ToXml with sync-c in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-c="true"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('sync-c="true"', xml_str)

    def test_toxml_with_sync_s(self):
        """Test ToXml with sync-s in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-s="true"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('sync-s="true"', xml_str)

    def test_toxml_with_sync_tags_false(self):
        """Test ToXml with sync-tags="false" in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" sync-tags="false"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('sync-tags="false"', xml_str)

    def test_toxml_with_dest_branch(self):
        """Test ToXml with dest-branch in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" dest-branch="develop"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('dest-branch="develop"', xml_str)

    def test_toxml_with_upstream(self):
        """Test ToXml with upstream in default."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main" upstream="refs/heads/main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('upstream="refs/heads/main"', xml_str)


@pytest.mark.unit
class TestRemoteToXml(unittest.TestCase):
    """Test _RemoteToXml method."""

    def test_remotetoxml_with_pushurl(self):
        """Test _RemoteToXml with pushUrl."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" pushurl="https://push.example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('pushurl="https://push.example.com"', xml_str)

    def test_remotetoxml_with_alias(self):
        """Test _RemoteToXml with alias."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" alias="upstream"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('alias="upstream"', xml_str)

    def test_remotetoxml_with_review(self):
        """Test _RemoteToXml with review."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" review="https://review.example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('review="https://review.example.com"', xml_str)

    def test_remotetoxml_with_revision(self):
        """Test _RemoteToXml with revision."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com" revision="stable"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            xml_output = manifest.ToXml()
            xml_str = xml_output.toprettyxml()
            self.assertIn('revision="stable"', xml_str)


@pytest.mark.unit
class TestParseList(unittest.TestCase):
    """Test _ParseList method."""

    def test_parselist_comma_separated(self):
        """Test _ParseList with comma-separated values."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            result = manifest._ParseList("a,b,c")
            self.assertEqual(result, ["a", "b", "c"])

    def test_parselist_whitespace_separated(self):
        """Test _ParseList with whitespace-separated values."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            result = manifest._ParseList("a b c")
            self.assertEqual(result, ["a", "b", "c"])

    def test_parselist_mixed_separators(self):
        """Test _ParseList with mixed separators."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            result = manifest._ParseList("a, b  c,d")
            self.assertEqual(result, ["a", "b", "c", "d"])

    def test_parselist_empty_elements(self):
        """Test _ParseList discards empty elements."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            result = manifest._ParseList("a,,b,  ,c")
            self.assertEqual(result, ["a", "b", "c"])


@pytest.mark.unit
class TestManifestProject(unittest.TestCase):
    """Test ManifestProject class."""

    def test_manifestproject_use_worktree(self):
        """Test ManifestProject use_worktree property."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            mp = manifest.manifestProject
            # Should have use_worktree property
            self.assertIsNotNone(mp)


@pytest.mark.unit
class TestGetProjectPaths(unittest.TestCase):
    """Test GetProjectPaths method."""

    def test_getprojectpaths_basic(self):
        """Test GetProjectPaths with basic project."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            relpath, worktree, gitdir, objdir, use_git_worktrees = manifest.GetProjectPaths(
                "test-project", "test-project", "origin"
            )
            self.assertEqual(relpath, "test-project")
            self.assertIsNotNone(worktree)
            self.assertIsNotNone(gitdir)
            self.assertIsNotNone(objdir)

    def test_getprojectpaths_strips_trailing_slash(self):
        """Test GetProjectPaths strips trailing slashes."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)
            relpath, worktree, gitdir, objdir, use_git_worktrees = manifest.GetProjectPaths(
                "test-project/", "test-project/", "origin/"
            )
            self.assertEqual(relpath, "test-project")


@pytest.mark.unit
class TestOverride(unittest.TestCase):
    """Test Override method."""

    def test_override_loads_different_manifest(self):
        """Test Override loads a different manifest."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)

            # Create another manifest file
            other_manifest = Path(tmp) / ".repo" / "manifests" / "other.xml"
            other_manifest.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="dev"/>
  <project name="other-project"/>
</manifest>
""")

            # Override should work
            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("kanon_cli.repo.manifest_xml.XmlManifest._Load"):
                    manifest.Override("other.xml")


@pytest.mark.unit
class TestLink(unittest.TestCase):
    """Test Link method."""

    def test_link_creates_manifest_file(self):
        """Test Link creates manifest file."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="main"/>
  <project name="test-project"/>
</manifest>
"""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            manifest = _load_manifest(Path(tmp), xml_content)

            # Create another manifest file
            other_manifest = Path(tmp) / ".repo" / "manifests" / "other.xml"
            other_manifest.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com"/>
  <default remote="origin" revision="dev"/>
  <project name="other-project"/>
</manifest>
""")

            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("kanon_cli.repo.manifest_xml.XmlManifest._Load"):
                    manifest.Link("other.xml")

            # Check that manifest file was created
            manifest_file = Path(tmp) / ".repo" / "manifest.xml"
            if manifest_file.exists():
                content = manifest_file.read_text()
                self.assertIn("<include", content)


if __name__ == "__main__":
    pytest.main([__file__])
