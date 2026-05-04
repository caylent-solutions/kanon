# Copyright (C) 2026 The Android Open Source Project
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

"""Deep unit tests for manifest_xml.py to increase coverage."""

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import manifest_xml


@pytest.mark.unit
class TestXmlRemote:
    """Test _XmlRemote class methods."""

    def test_remote_to_remote_spec(self):
        """Test _XmlRemote.ToRemoteSpec() method."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        spec = remote.ToRemoteSpec("myproject")

        assert spec.url == "https://example.com/myproject"
        assert spec.orig_name == "origin"
        assert spec.name == "origin"

    def test_remote_to_remote_spec_with_alias(self):
        """Test _XmlRemote.ToRemoteSpec() with alias."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            alias="upstream",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        spec = remote.ToRemoteSpec("myproject")

        assert spec.name == "upstream"
        assert spec.orig_name == "origin"

    def test_remote_add_annotation(self):
        """Test _XmlRemote.AddAnnotation()."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        remote.AddAnnotation("key", "value", "true")

        assert len(remote.annotations) == 1
        assert remote.annotations[0].name == "key"
        assert remote.annotations[0].value == "value"
        assert remote.annotations[0].keep == "true"

    def test_remote_equality(self):
        """Test _XmlRemote __eq__ method."""
        remote1 = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )
        remote2 = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        assert remote1 == remote2

    def test_remote_inequality_name(self):
        """Test _XmlRemote __eq__ with different names."""
        remote1 = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )
        remote2 = manifest_xml._XmlRemote(
            name="other",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        assert remote1 != remote2

    def test_remote_inequality_wrong_type(self):
        """Test _XmlRemote __eq__ with wrong type."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )

        assert remote != "not a remote"
        assert remote != 123

    def test_remote_resolve_fetch_url_relative(self):
        """Test _XmlRemote URL resolution with relative fetch."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch="../other",
            manifestUrl="https://example.com/manifest",
        )

        assert "other" in remote.resolvedFetchUrl

    def test_remote_resolve_fetch_url_absolute(self):
        """Test _XmlRemote URL resolution with absolute fetch."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch="https://absolute.com/",
            manifestUrl="https://example.com/manifest",
        )

        assert remote.resolvedFetchUrl == "https://absolute.com"

    def test_remote_resolve_fetch_url_none(self):
        """Test _XmlRemote URL resolution with None fetch."""
        remote = manifest_xml._XmlRemote(
            name="origin",
            fetch=None,
            manifestUrl="https://example.com/manifest",
        )

        assert remote.resolvedFetchUrl == ""


@pytest.mark.unit
class TestDefault:
    """Test _Default class methods."""

    def test_default_equality(self):
        """Test _Default __eq__ method."""
        default1 = manifest_xml._Default()
        default1.revisionExpr = "main"
        default1.sync_j = 4

        default2 = manifest_xml._Default()
        default2.revisionExpr = "main"
        default2.sync_j = 4

        assert default1 == default2

    def test_default_inequality(self):
        """Test _Default __ne__ method."""
        default1 = manifest_xml._Default()
        default1.revisionExpr = "main"

        default2 = manifest_xml._Default()
        default2.revisionExpr = "develop"

        assert default1 != default2

    def test_default_inequality_wrong_type(self):
        """Test _Default __ne__ with wrong type."""
        default = manifest_xml._Default()

        assert default != "not a default"
        assert default != 123


@pytest.mark.unit
class TestXmlManifestParsing:
    """Test XmlManifest parsing methods."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_parse_notice_element(self, tmp_path):
        """Test parsing notice element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <notice>This is a notice message</notice>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.notice == "This is a notice message"

    def test_parse_contact_info_bugurl(self, tmp_path):
        """Test parsing contactinfo with bugurl."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <contactinfo bugurl="https://bugs.example.com/"/>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.contactinfo.bugurl == "https://bugs.example.com/"

    def test_parse_manifest_server(self, tmp_path):
        """Test parsing manifest-server element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <manifest-server url="https://manifest-server.example.com/"/>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.manifest_server == "https://manifest-server.example.com/"

    def test_parse_remove_project_by_name(self, tmp_path):
        """Test parsing remove-project by name."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test"/>
            <remove-project name="test-project"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert not any(p.name == "test-project" for p in m.projects)

    def test_parse_remove_project_by_path(self, tmp_path):
        """Test parsing remove-project by path."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test/path"/>
            <remove-project path="test/path"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert not any(p.name == "test-project" for p in m.projects)

    def test_parse_remove_project_optional(self, tmp_path):
        """Test parsing remove-project with optional=true."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <remove-project name="nonexistent" optional="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        # Should not raise
        m = manifest_xml.XmlManifest(repodir, manifest_file)
        assert m is not None

    def test_parse_include_with_groups(self, tmp_path):
        """Test parsing include element with groups."""
        include_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <project name="included-project" path="included"/>
        </manifest>
        """

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <include name="include.xml" groups="group1,group2"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        manifest_dir = tmp_path / ".repo" / "manifests"
        include_file = manifest_dir / "include.xml"
        include_file.write_text(include_xml)

        m = manifest_xml.XmlManifest(repodir, manifest_file)

        # Included project should have groups
        projects = [p for p in m.projects if p.name == "included-project"]
        assert len(projects) > 0
        assert "group1" in projects[0].groups

    def test_parse_project_with_upstream(self, tmp_path):
        """Test parsing project with upstream attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" upstream="refs/heads/upstream"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].upstream == "refs/heads/upstream"

    def test_parse_project_with_dest_branch(self, tmp_path):
        """Test parsing project with dest-branch attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" dest-branch="custom-branch"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].dest_branch == "custom-branch"

    def test_parse_project_with_clone_depth(self, tmp_path):
        """Test parsing project with clone-depth attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" clone-depth="5"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].clone_depth == 5

    def test_parse_project_with_sync_c(self, tmp_path):
        """Test parsing project with sync-c attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" sync-c="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].sync_c is True

    def test_parse_project_with_sync_s(self, tmp_path):
        """Test parsing project with sync-s attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" sync-s="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].sync_s is True

    def test_parse_project_with_sync_tags_false(self, tmp_path):
        """Test parsing project with sync-tags=false."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" sync-tags="false"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].sync_tags is False

    def test_parse_project_with_copyfile(self, tmp_path):
        """Test parsing project with copyfile element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test">
                <copyfile src="src.txt" dest="dest.txt"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert len(projects[0].copyfiles) == 1
        assert projects[0].copyfiles[0].src == "src.txt"
        assert projects[0].copyfiles[0].dest == "dest.txt"

    def test_parse_project_with_linkfile(self, tmp_path):
        """Test parsing project with linkfile element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test">
                <linkfile src="src.txt" dest="link.txt"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert len(projects[0].linkfiles) == 1
        assert projects[0].linkfiles[0].src == "src.txt"
        assert projects[0].linkfiles[0].dest == "link.txt"

    def test_parse_project_with_annotation(self, tmp_path):
        """Test parsing project with annotation element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test">
                <annotation name="key" value="value"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert len(projects[0].annotations) == 1
        assert projects[0].annotations[0].name == "key"
        assert projects[0].annotations[0].value == "value"

    def test_parse_project_with_annotation_keep_true(self, tmp_path):
        """Test parsing project with annotation keep=true."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test">
                <annotation name="key" value="value" keep="true"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].annotations[0].keep == "true"

    def test_parse_repo_hooks(self, tmp_path):
        """Test parsing repo-hooks element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="hooks-project" path="hooks"/>
            <repo-hooks in-project="hooks-project" enabled-list="pre-commit"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.repo_hooks_project is not None
        assert m.repo_hooks_project.name == "hooks-project"
        assert "pre-commit" in m.repo_hooks_project.enabled_repo_hooks

    def test_parse_superproject(self, tmp_path):
        """Test parsing superproject element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <superproject name="superproject"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.superproject is not None
        assert m.superproject.name == "superproject"

    def test_parse_superproject_with_remote(self, tmp_path):
        """Test parsing superproject with remote attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <remote name="super" fetch="https://super.example.com/"/>
            <default remote="origin" revision="main"/>
            <superproject name="superproject" remote="super"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.superproject.remote.name == "super"


class TestXmlManifestSerialization:
    """Test XmlManifest serialization methods."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_to_xml_basic(self, tmp_path):
        """Test ToXml() with basic manifest."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()

        assert doc is not None
        assert doc.documentElement.nodeName == "manifest"

    def test_to_dict_basic(self, tmp_path):
        """Test ToDict() method."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        result = m.ToDict()

        assert isinstance(result, dict)
        assert len(result) > 0


class TestXmlManifestEdgeCases:
    """Test edge cases in XmlManifest."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_project_with_multiple_groups(self, tmp_path):
        """Test project with multiple groups."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" groups="group1,group2,group3"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert "group1" in projects[0].groups
        assert "group2" in projects[0].groups
        assert "group3" in projects[0].groups

    def test_extend_project_adds_groups(self, tmp_path):
        """Test extend-project adding groups."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" groups="group1"/>
            <extend-project name="test-project" groups="group2"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert "group1" in projects[0].groups
        assert "group2" in projects[0].groups

    def test_extend_project_with_revision(self, tmp_path):
        """Test extend-project changing revision."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" revision="main"/>
            <extend-project name="test-project" revision="develop"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].revisionExpr == "develop"

    def test_project_without_path_uses_name(self, tmp_path):
        """Test project without explicit path uses name as path."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].relpath == "test-project"


class TestXmlManifestRemoteAttributes:
    """Test remote attribute variations."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_remote_with_all_attributes(self, tmp_path):
        """Test remote with all possible attributes."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin"
                    alias="upstream"
                    fetch="https://example.com/"
                    pushurl="https://push.example.com/"
                    review="https://review.example.com/"
                    revision="refs/heads/main"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        remote = m.remotes["origin"]
        assert remote.name == "origin"
        assert remote.remoteAlias == "upstream"
        assert remote.fetchUrl == "https://example.com/"
        assert remote.pushUrl == "https://push.example.com/"
        assert remote.reviewUrl == "https://review.example.com/"
        assert remote.revision == "refs/heads/main"

    def test_project_with_custom_remote(self, tmp_path):
        """Test project using non-default remote."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <remote name="custom" fetch="https://custom.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test-project" path="test" remote="custom"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test-project"]
        assert len(projects) == 1
        assert projects[0].remote.name == "custom"

    def test_default_with_sync_settings(self, tmp_path):
        """Test default with all sync settings."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin"
                     revision="main"
                     dest-branch="target"
                     upstream="refs/heads/upstream"
                     sync-j="4"
                     sync-c="true"
                     sync-s="true"
                     sync-tags="false"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.default.revisionExpr == "main"
        assert m.default.destBranchExpr == "target"
        assert m.default.upstreamExpr == "refs/heads/upstream"
        assert m.default.sync_j == 4
        assert m.default.sync_c is True
        assert m.default.sync_s is True
        assert m.default.sync_tags is False


@pytest.mark.unit
class TestUtilityFunctions:
    """Test utility functions in manifest_xml."""

    def test_xml_bool_true_values(self):
        """Test XmlBool with true values."""
        import xml.dom.minidom

        xml_str = '<node attr="true"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild

        assert manifest_xml.XmlBool(node, "attr") is True

        xml_str = '<node attr="yes"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr") is True

        xml_str = '<node attr="1"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr") is True

    def test_xml_bool_false_values(self):
        """Test XmlBool with false values."""
        import xml.dom.minidom

        xml_str = '<node attr="false"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr") is False

        xml_str = '<node attr="no"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr") is False

        xml_str = '<node attr="0"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr") is False

    def test_xml_bool_empty_string(self):
        """Test XmlBool with empty string returns default."""
        import xml.dom.minidom

        xml_str = '<node attr=""/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr", "default") == "default"

    def test_xml_bool_invalid_value(self):
        """Test XmlBool with invalid value returns default."""
        import xml.dom.minidom

        xml_str = '<node attr="invalid"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlBool(node, "attr", "default") == "default"

    def test_xml_int_valid(self):
        """Test XmlInt with valid integer."""
        import xml.dom.minidom

        xml_str = '<node attr="42"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlInt(node, "attr") == 42

    def test_xml_int_empty(self):
        """Test XmlInt with empty string returns default."""
        import xml.dom.minidom

        xml_str = '<node attr=""/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild
        assert manifest_xml.XmlInt(node, "attr", 100) == 100

    def test_xml_int_invalid(self):
        """Test XmlInt with invalid value raises error."""
        import xml.dom.minidom

        xml_str = '<node attr="notanumber"/>'
        node = xml.dom.minidom.parseString(xml_str).firstChild

        with pytest.raises(error.ManifestParseError, match="invalid.*integer"):
            manifest_xml.XmlInt(node, "attr")

    def test_normalize_url_trailing_slash(self):
        """Test normalize_url removes trailing slashes."""
        result = manifest_xml.normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

        result = manifest_xml.normalize_url("https://example.com///")
        assert result == "https://example.com"

    def test_normalize_url_scp_syntax(self):
        """Test normalize_url converts SCP syntax to SSH URL."""
        result = manifest_xml.normalize_url("git@github.com:user/repo")
        assert result == "ssh://git@github.com/user/repo"

    def test_normalize_url_normal_url(self):
        """Test normalize_url doesn't modify normal URLs."""
        result = manifest_xml.normalize_url("https://example.com/path")
        assert result == "https://example.com/path"

        result = manifest_xml.normalize_url("ssh://git@example.com/path")
        assert result == "ssh://git@example.com/path"


@pytest.mark.unit
class TestManifestToXmlBranches:
    """Test ToXml branches for different manifest elements."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_to_xml_with_notice(self, tmp_path):
        """Test ToXml includes notice element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <notice>Important notice</notice>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "Important notice" in xml_str

    def test_to_xml_with_superproject(self, tmp_path):
        """Test ToXml includes superproject."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <superproject name="superproject"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "superproject" in xml_str

    def test_to_xml_with_contactinfo(self, tmp_path):
        """Test ToXml includes contactinfo."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <contactinfo bugurl="https://bugs.example.com/"/>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "bugs.example.com" in xml_str

    def test_to_xml_project_with_groups(self, tmp_path):
        """Test ToXml exports project groups."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" groups="group1,group2"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "group1" in xml_str or "group2" in xml_str

    def test_to_xml_project_with_annotations(self, tmp_path):
        """Test ToXml exports project annotations."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test">
                <annotation name="key" value="val"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "annotation" in xml_str


@pytest.mark.unit
class TestManifestProjectParsing:
    """Test various project parsing branches."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_parse_project_with_force_path(self, tmp_path):
        """Test project with force-path attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" force-path="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1

    def test_parse_remote_with_annotation(self, tmp_path):
        """Test remote with annotation."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/">
                <annotation name="key" value="value"/>
            </remote>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        remote = m.remotes["origin"]
        assert len(remote.annotations) == 1
        assert remote.annotations[0].name == "key"

    def test_parse_project_with_rebase(self, tmp_path):
        """Test project with rebase attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" rebase="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].rebase is True

    def test_parse_project_with_rebase_false(self, tmp_path):
        """Test project with rebase=false."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" rebase="false"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].rebase is False

    def test_parse_default_with_dest_branch(self, tmp_path):
        """Test default with dest-branch."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main" dest-branch="custom"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.default.destBranchExpr == "custom"

    def test_parse_extend_project_with_dest_branch(self, tmp_path):
        """Test extend-project with dest-branch."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" dest-branch="main"/>
            <extend-project name="test" dest-branch="develop"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].dest_branch == "develop"

    def test_parse_extend_project_with_upstream(self, tmp_path):
        """Test extend-project with upstream."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test"/>
            <extend-project name="test" upstream="refs/heads/upstream"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].upstream == "refs/heads/upstream"

    def test_parse_extend_project_with_remote(self, tmp_path):
        """Test extend-project with remote."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <remote name="other" fetch="https://other.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" remote="origin"/>
            <extend-project name="test" remote="other"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].remote.name == "other"


class TestManifestDiffMethod:
    """Test manifest Diff method."""

    def _make_temp_manifest(self, tmp_path, xml_content, name="manifest.xml"):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        if not repodir.exists():
            repodir.mkdir()
        manifest_dir = repodir / "manifests"
        if not manifest_dir.exists():
            manifest_dir.mkdir()
        manifest_file = repodir / name
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        if not gitdir.exists():
            gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)


class TestManifestMiscMethods:
    """Test miscellaneous manifest methods."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        # Create git config for manifests.git
        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_default_sync_c_value(self, tmp_path):
        """Test default sync_c value from default element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main" sync-c="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.default.sync_c is True

    def test_default_sync_j_value(self, tmp_path):
        """Test default sync_j value from default element."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main" sync-j="8"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.default.sync_j == 8

    def test_paths_property(self, tmp_path):
        """Test paths property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test/path"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert "test/path" in m.paths

    def test_remotes_property(self, tmp_path):
        """Test remotes property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <remote name="other" fetch="https://other.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert "origin" in m.remotes
        assert "other" in m.remotes
        assert len(m.remotes) == 2


@pytest.mark.unit
class TestManifestMoreParsing:
    """Additional parsing tests."""

    def _make_temp_manifest(self, tmp_path, xml_content):
        """Helper to create a temporary manifest structure."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_dir = repodir / "manifests"
        manifest_dir.mkdir()
        manifest_file = repodir / "manifest.xml"
        manifest_file.write_text(xml_content)

        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        config_file = gitdir / "config"
        config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')

        return str(repodir), str(manifest_file)

    def test_project_get_remote(self, tmp_path):
        """Test project GetRemote method."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        remote = projects[0].remote
        assert remote.name == "origin"

    def test_multiple_projects_same_name_different_paths(self, tmp_path):
        """Test multiple projects with same name but different paths."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="path1"/>
            <project name="test" path="path2"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 2

    def test_project_with_partial_clone(self, tmp_path):
        """Test project with partial-clone attribute."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" partial-clone="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1

    def test_remove_project_by_name_and_path(self, tmp_path):
        """Test remove-project with both name and path."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test/path"/>
            <remove-project name="test" path="test/path"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert not any(p.name == "test" for p in m.projects)

    def test_repo_hooks_multiple_hooks(self, tmp_path):
        """Test repo-hooks with multiple enabled hooks."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="hooks" path="hooks"/>
            <repo-hooks in-project="hooks" enabled-list="pre-commit,pre-push"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.repo_hooks_project is not None
        assert "pre-commit" in m.repo_hooks_project.enabled_repo_hooks
        assert "pre-push" in m.repo_hooks_project.enabled_repo_hooks

    def test_default_sync_tags_true(self, tmp_path):
        """Test default with sync-tags=true (explicit)."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main" sync-tags="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.default.sync_tags is True

    def test_project_sync_tags_true(self, tmp_path):
        """Test project with sync-tags=true."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test" sync-tags="true"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert projects[0].sync_tags is True

    def test_remote_with_alias_resolution(self, tmp_path):
        """Test remote with alias is used in project."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" alias="main" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1

    def test_project_multiple_copyfiles(self, tmp_path):
        """Test project with multiple copyfiles."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test">
                <copyfile src="src1.txt" dest="dest1.txt"/>
                <copyfile src="src2.txt" dest="dest2.txt"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert len(projects[0].copyfiles) == 2

    def test_project_multiple_linkfiles(self, tmp_path):
        """Test project with multiple linkfiles."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test">
                <linkfile src="src1.txt" dest="link1.txt"/>
                <linkfile src="src2.txt" dest="link2.txt"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert len(projects[0].linkfiles) == 2

    def test_project_multiple_annotations(self, tmp_path):
        """Test project with multiple annotations."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test">
                <annotation name="key1" value="val1"/>
                <annotation name="key2" value="val2"/>
            </project>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        projects = [p for p in m.projects if p.name == "test"]
        assert len(projects) == 1
        assert len(projects[0].annotations) == 2

    def test_to_dict_with_projects(self, tmp_path):
        """Test ToDict includes projects."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
            <project name="test" path="test"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        result = m.ToDict()

        assert isinstance(result, dict)

    def test_manifest_project_exists(self, tmp_path):
        """Test that manifestProject exists."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.manifestProject is not None

    def test_repo_project_exists(self, tmp_path):
        """Test that repoProject exists."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.repoProject is not None

    def test_topdir_property(self, tmp_path):
        """Test topdir property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.topdir is not None
        assert isinstance(m.topdir, str)

    def test_path_prefix_property(self, tmp_path):
        """Test path_prefix property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.path_prefix == ""

    def test_is_submanifest_property(self, tmp_path):
        """Test is_submanifest property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.is_submanifest is False

    def test_contact_info_property(self, tmp_path):
        """Test contactinfo property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <contactinfo bugurl="https://bugs.example.com/"/>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.contactinfo is not None
        assert m.contactinfo.bugurl == "https://bugs.example.com/"

    def test_notice_property(self, tmp_path):
        """Test notice property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <notice>Test notice</notice>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert m.notice == "Test notice"

    def test_submanifest_property(self, tmp_path):
        """Test _submanifests property."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>
            <remote name="origin" fetch="https://example.com/"/>
            <default remote="origin" revision="main"/>
        </manifest>
        """

        repodir, manifest_file = self._make_temp_manifest(tmp_path, xml)
        m = manifest_xml.XmlManifest(repodir, manifest_file)

        assert isinstance(m._submanifests, dict)
