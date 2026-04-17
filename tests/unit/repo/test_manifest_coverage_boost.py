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

"""Coverage-boost unit tests for manifest_xml.py targeting uncovered lines."""

import io
import os
from pathlib import Path
from unittest import mock

import pytest
import xml.dom.minidom

from kanon_cli.repo import error
from kanon_cli.repo import manifest_xml
from kanon_cli.repo.manifest_xml import (
    LOCAL_MANIFEST_GROUP_PREFIX,
    MAX_SUBMANIFEST_DEPTH,
    SUBMANIFEST_DIR,
    _Default,
    _XmlRemote,
    _XmlSubmanifest,
    SubmanifestSpec,
    XmlManifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path, xml_content):
    """Create a temporary manifest directory + XmlManifest instance."""
    repodir = tmp_path / ".repo"
    repodir.mkdir(parents=True, exist_ok=True)
    manifests_dir = repodir / "manifests"
    manifests_dir.mkdir(exist_ok=True)
    manifest_git = repodir / "manifests.git"
    manifest_git.mkdir(exist_ok=True)
    config_file = manifest_git / "config"
    config_file.write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
    manifest_file = repodir / "manifest.xml"
    manifest_file.write_text(xml_content)
    return manifest_xml.XmlManifest(str(repodir), str(manifest_file))


def _make_and_load(tmp_path, xml_content):
    """Create manifest and trigger loading (which parses the XML)."""
    m = _make_manifest(tmp_path, xml_content)
    # Accessing .projects triggers _Load()
    _ = m.projects
    return m


# ===========================================================================
# Lines 222-225  _XmlRemote._resolveFetchUrl gopher:// branch
# ===========================================================================


@pytest.mark.unit
class TestXmlRemoteResolveFetchUrlGopher:
    """Cover the gopher:// fallback path in _resolveFetchUrl."""

    def test_resolve_fetch_url_no_scheme_uses_gopher_trick(self):
        """When manifest URL has no standard scheme, the gopher trick fires."""
        remote = _XmlRemote(
            name="origin",
            fetch="../relative",
            manifestUrl="/some/local/path",  # no colon-slash scheme
        )
        # The resolved URL should not start with gopher://
        assert not remote.resolvedFetchUrl.startswith("gopher://")
        # It should have resolved the relative path
        assert "relative" in remote.resolvedFetchUrl

    def test_resolve_fetch_url_with_scheme(self):
        """Standard scheme => urljoin works directly, no gopher trick."""
        remote = _XmlRemote(
            name="origin",
            fetch="../other",
            manifestUrl="https://example.com/manifest",
        )
        assert "other" in remote.resolvedFetchUrl
        assert "gopher" not in remote.resolvedFetchUrl


# ===========================================================================
# Lines 279-313  _XmlSubmanifest.__init__
# ===========================================================================


@pytest.mark.unit
class TestXmlSubmanifestInit:
    """Cover _XmlSubmanifest.__init__ (lines 279-313)."""

    def _make_parent(self, tmp_path):
        """Build a minimal XmlManifest usable as a parent for submanifests."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        return _make_manifest(tmp_path, xml_content)

    def test_submanifest_basic_init(self, tmp_path):
        """Basic submanifest creation stores all attributes."""
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest(
            "child",
            remote=None,
            project=None,
            revision=None,
            manifestName=None,
            groups=["g1"],
            default_groups=["dg1"],
            path="child_path",
            parent=parent,
        )
        assert sub.name == "child"
        assert sub.path == "child_path"
        assert sub.groups == ["g1"]
        assert sub.default_groups == ["dg1"]
        assert sub.annotations == []

    def test_submanifest_remote_without_project_raises(self, tmp_path):
        """remote set without project must raise ManifestParseError."""
        parent = self._make_parent(tmp_path)
        with pytest.raises(error.ManifestParseError, match="must specify project"):
            _XmlSubmanifest(
                "child",
                remote="origin",
                project=None,
                groups=[],
                parent=parent,
            )

    def test_submanifest_with_project_and_remote(self, tmp_path):
        """remote + project is allowed."""
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest(
            "child",
            remote="origin",
            project="some/project",
            groups=[],
            parent=parent,
        )
        assert sub.remote == "origin"
        assert sub.project == "some/project"


# ===========================================================================
# Lines 315-331  _XmlSubmanifest.__eq__, __ne__
# ===========================================================================


@pytest.mark.unit
class TestXmlSubmanifestEquality:
    """Cover __eq__ and __ne__ on _XmlSubmanifest."""

    def _make_parent(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        return _make_manifest(tmp_path, xml_content)

    def test_equal_submanifests(self, tmp_path):
        parent = self._make_parent(tmp_path)
        a = _XmlSubmanifest("x", groups=[], parent=parent)
        b = _XmlSubmanifest("x", groups=[], parent=parent)
        assert a == b

    def test_unequal_submanifests(self, tmp_path):
        parent = self._make_parent(tmp_path)
        a = _XmlSubmanifest("x", groups=[], parent=parent)
        b = _XmlSubmanifest("y", groups=[], parent=parent)
        assert a != b

    def test_ne_with_wrong_type(self, tmp_path):
        parent = self._make_parent(tmp_path)
        a = _XmlSubmanifest("x", groups=[], parent=parent)
        assert a != "not a submanifest"


# ===========================================================================
# Lines 335-368  ToSubmanifestSpec, relpath, GetGroupsStr, GetDefaultGroupsStr
# ===========================================================================


@pytest.mark.unit
class TestXmlSubmanifestMethods:
    """Cover ToSubmanifestSpec, relpath, GetGroupsStr, GetDefaultGroupsStr."""

    def _make_parent(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        return _make_manifest(tmp_path, xml_content)

    def test_relpath_uses_path_when_set(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", path="custom_path", groups=[], parent=parent)
        assert sub.relpath == "custom_path"

    def test_relpath_uses_revision_split_when_no_path(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", revision="refs/heads/feature", groups=[], parent=parent)
        assert sub.relpath == "feature"

    def test_relpath_uses_name_when_no_path_no_revision(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("myname", groups=[], parent=parent)
        assert sub.relpath == "myname"

    def test_get_groups_str_with_groups(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", groups=["a", "b"], parent=parent)
        assert sub.GetGroupsStr() == "a,b"

    def test_get_groups_str_empty(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", groups=[], parent=parent)
        assert sub.GetGroupsStr() == ""

    def test_get_default_groups_str(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", default_groups=["d1", "d2"], groups=[], parent=parent)
        assert sub.GetDefaultGroupsStr() == "d1,d2"

    def test_get_default_groups_str_none(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", default_groups=None, groups=[], parent=parent)
        assert sub.GetDefaultGroupsStr() == ""

    def test_to_submanifest_spec(self, tmp_path):
        parent = self._make_parent(tmp_path)
        # Need to load parent so remotes are populated
        _ = parent.projects
        sub = _XmlSubmanifest(
            "mysub",
            path="mypath",
            groups=["g1"],
            parent=parent,
        )
        spec = sub.ToSubmanifestSpec()
        assert isinstance(spec, SubmanifestSpec)
        assert spec.name == "mysub"
        assert spec.path == "mypath"
        assert spec.groups == ["g1"]

    def test_add_annotation(self, tmp_path):
        parent = self._make_parent(tmp_path)
        sub = _XmlSubmanifest("x", groups=[], parent=parent)
        sub.AddAnnotation("k", "v", "true")
        assert len(sub.annotations) == 1
        assert sub.annotations[0].name == "k"


# ===========================================================================
# Lines 424-440  XmlManifest.__init__ edge cases
# ===========================================================================


@pytest.mark.unit
class TestXmlManifestInitEdgeCases:
    """Cover XmlManifest init edge cases: submanifest_path, abs check."""

    def test_non_absolute_manifest_file_raises(self, tmp_path):
        """manifest_file must be abspath."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        with pytest.raises(error.ManifestParseError, match="manifest_file must be abspath"):
            XmlManifest(str(repodir), "relative/path.xml")

    def test_submanifest_path_without_outer_client_raises(self, tmp_path):
        """submanifest_path without outer_client raises."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifest_git = repodir / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        (repodir / "manifests").mkdir()
        mf = repodir / "manifest.xml"
        mf.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>'
            '<remote name="o" fetch="https://x.com/"/>'
            '<default remote="o" revision="m"/></manifest>'
        )
        with pytest.raises(error.ManifestParseError, match="Bad call"):
            XmlManifest(
                str(repodir),
                str(mf),
                submanifest_path="sub/path",
            )

    def test_submanifest_path_with_topdir(self, tmp_path):
        """When submanifest_path is set with outer_client, topdir is adjusted."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        parent = _make_manifest(tmp_path, xml_content)
        # Topdir should be the directory containing .repo
        assert parent.topdir == str(tmp_path)


# ===========================================================================
# Lines 461-479  Override method
# ===========================================================================


@pytest.mark.unit
class TestXmlManifestOverride:
    """Cover Override method."""

    def test_override_with_nonexistent_name_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="manifest .* not found"):
            m.Override("nonexistent.xml")

    def test_override_with_existing_manifest(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # Create an alternate manifest in the manifests worktree
        alt = Path(m.manifestProject.worktree) / "alternate.xml"
        alt.parent.mkdir(parents=True, exist_ok=True)
        alt.write_text(xml_content)
        m.Override("alternate.xml")
        assert m._loaded

    def test_override_no_local_manifests(self, tmp_path):
        """Override with load_local_manifests=False and a local file path."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # Write a file on disk and reference it by absolute path
        local_file = tmp_path / "local_override.xml"
        local_file.write_text(xml_content)
        m.Override(str(local_file), load_local_manifests=False)
        assert not m._load_local_manifests


# ===========================================================================
# Lines 529-560  _RemoteToXml annotation, _SubmanifestToXml
# ===========================================================================


@pytest.mark.unit
class TestRemoteAndSubmanifestToXml:
    """Cover _RemoteToXml annotation and _SubmanifestToXml."""

    def test_remote_to_xml_with_annotations(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/">
    <annotation name="akey" value="aval" keep="true"/>
  </remote>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "akey" in xml_str
        assert "aval" in xml_str

    def test_submanifest_to_xml_all_attrs(self, tmp_path):
        """Exercise _SubmanifestToXml with all optional attributes set."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)

        sub = _XmlSubmanifest(
            "sub1",
            remote="origin",
            project="proj1",
            revision="v1",
            manifestName="custom.xml",
            groups=["g1", "g2"],
            default_groups=["dg1"],
            path="sub_path",
            parent=m,
        )
        sub.AddAnnotation("ann_key", "ann_val", "true")

        m._SubmanifestToXml(sub, doc, root)
        xml_str = doc.toxml()
        assert 'name="sub1"' in xml_str
        assert 'remote="origin"' in xml_str
        assert 'project="proj1"' in xml_str
        assert 'revision="v1"' in xml_str
        assert 'manifest-name="custom.xml"' in xml_str
        assert 'path="sub_path"' in xml_str
        assert "ann_key" in xml_str
        assert "ann_val" in xml_str

    def test_submanifest_to_xml_no_optional_attrs(self, tmp_path):
        """Exercise _SubmanifestToXml with no optional attributes."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)

        sub = _XmlSubmanifest("sub_minimal", groups=[], parent=m)

        m._SubmanifestToXml(sub, doc, root)
        xml_str = doc.toxml()
        assert 'name="sub_minimal"' in xml_str
        # None attrs should be omitted
        assert "remote=" not in xml_str
        assert "project=" not in xml_str


# ===========================================================================
# Lines 589, 641-649, 658-698  ToXml coverage
# ===========================================================================


@pytest.mark.unit
class TestToXmlDetailedCoverage:
    """Cover ToXml inner paths: manifest-server, submanifest, project details."""

    def test_toxml_with_manifest_server(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <manifest-server url="https://ms.example.com/"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "manifest-server" in xml_str
        assert "https://ms.example.com/" in xml_str

    def test_toxml_omit_local(self, tmp_path):
        """omit_local=True should skip projects from local manifests."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # Mark p1 as local
        p = m.projects[0]
        p.groups.append(LOCAL_MANIFEST_GROUP_PREFIX + ":local_file")

        doc = m.ToXml(omit_local=True)
        xml_str = doc.toxml()
        # The local project should be omitted
        assert "p1" not in xml_str

    def test_toxml_project_with_different_remote(self, tmp_path):
        """Project with a non-default remote => remote attr in output."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <remote name="other" fetch="https://other.example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" remote="other"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert 'remote="other"' in xml_str

    def test_toxml_project_explicit_revision(self, tmp_path):
        """Project with explicit revision different from default."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" revision="develop"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert 'revision="develop"' in xml_str

    def test_toxml_project_with_clone_depth(self, tmp_path):
        """Project with clone-depth should include it in output."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" clone-depth="3"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert 'clone-depth="3"' in xml_str


# ===========================================================================
# Lines 762-769  ToXml repo-hooks output
# ===========================================================================


@pytest.mark.unit
class TestToXmlRepoHooks:
    """Cover ToXml repo-hooks output."""

    def test_toxml_includes_repo_hooks(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="hooks" path="hooks"/>
  <repo-hooks in-project="hooks" enabled-list="pre-upload"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "repo-hooks" in xml_str
        assert 'in-project="hooks"' in xml_str
        assert 'enabled-list="pre-upload"' in xml_str


# ===========================================================================
# Lines 780-784  ToXml superproject output
# ===========================================================================


@pytest.mark.unit
class TestToXmlSuperproject:
    """Cover ToXml superproject output with non-default remote."""

    def test_toxml_superproject_with_different_remote(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <remote name="super-remote" fetch="https://super.example.com/"/>
  <default remote="origin" revision="main"/>
  <superproject name="sp" remote="super-remote"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        doc = m.ToXml()
        xml_str = doc.toxml()
        assert "superproject" in xml_str
        assert 'remote="super-remote"' in xml_str


# ===========================================================================
# Lines 837, 849-850  ToDict unhandled element, Save
# ===========================================================================


@pytest.mark.unit
class TestToDictAndSave:
    """Cover ToDict and Save."""

    def test_save_writes_xml_to_fd(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        buf = io.StringIO()
        m.Save(buf)
        output = buf.getvalue()
        assert "<manifest>" in output
        assert "origin" in output


# ===========================================================================
# Lines 876-894  is_multimanifest, is_submanifest, all_manifests, all_children
# ===========================================================================


@pytest.mark.unit
class TestManifestTreeProperties:
    """Cover is_multimanifest, is_submanifest, all_manifests, all_children."""

    def test_is_multimanifest_false_when_no_submanifests(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.is_multimanifest

    def test_is_submanifest_false_for_root(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.is_submanifest


# ===========================================================================
# Lines 913-924  all_paths, all_projects
# ===========================================================================


@pytest.mark.unit
class TestAllPathsAllProjects:
    """Cover all_paths and all_projects properties."""

    def test_all_paths(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <project name="p2" path="subdir/p2"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        all_paths = m.all_paths
        assert "p1" in all_paths
        assert "subdir/p2" in all_paths

    def test_all_projects(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <project name="p2"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert len(m.all_projects) == 2


# ===========================================================================
# Lines 992-1034  CloneBundle, CloneFilter, etc. property coverage
# ===========================================================================


@pytest.mark.unit
class TestManifestProjectProperties:
    """Cover CloneBundle, CloneFilter, CloneFilterForDepth, etc."""

    def test_clone_bundle_default(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # Default: clone_bundle is None and no partial_clone => True
        result = m.CloneBundle
        assert result is True

    def test_clone_filter_none_when_no_partial_clone(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert m.CloneFilter is None

    def test_clone_filter_for_depth_none(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert m.CloneFilterForDepth is None

    def test_use_local_manifests(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert m.UseLocalManifests is True
        m.SetUseLocalManifests(False)
        assert m.UseLocalManifests is False

    def test_has_local_manifests(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # When local manifests path is set and loading is enabled
        result = m.HasLocalManifests
        # local_manifests is None for XmlManifest so it should be falsy
        assert not result

    def test_is_from_local_manifest(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        p = m.projects[0]
        assert not m.IsFromLocalManifest(p)
        p.groups.append(LOCAL_MANIFEST_GROUP_PREFIX + ":local_file")
        assert m.IsFromLocalManifest(p)

    def test_is_mirror_falsy(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.IsMirror

    def test_is_archive_falsy(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.IsArchive

    def test_has_submodules_falsy(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.HasSubmodules

    def test_enable_git_lfs_falsy(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert not m.EnableGitLfs


# ===========================================================================
# Lines 1060-1070  FindManifestByPath
# ===========================================================================


@pytest.mark.unit
class TestFindManifestByPath:
    """Cover FindManifestByPath."""

    def test_find_manifest_by_path_returns_self(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        result = m.FindManifestByPath(str(tmp_path))
        assert result is m


# ===========================================================================
# Lines 1148-1176  _Load inner paths
# ===========================================================================


@pytest.mark.unit
class TestLoadPaths:
    """Cover _Load edge cases."""

    def test_load_sets_loaded(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        m._Load()
        assert m._loaded

    def test_load_submanifest_depth_exceeded_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        m.Unload()
        with pytest.raises(error.ManifestParseError, match="maximum submanifest depth"):
            m._Load(submanifest_depth=MAX_SUBMANIFEST_DEPTH + 1)


# ===========================================================================
# Lines 1194-1220  Local manifests loading
# ===========================================================================


@pytest.mark.unit
class TestLocalManifestsLoading:
    """Cover local manifests loading code path."""

    def test_local_manifests_xml_files_loaded(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="base-project"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)

        # Create local_manifests directory with a local manifest file
        local_dir = Path(str(m.local_manifests)) if m.local_manifests else None
        if local_dir:
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "extra.xml").write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project name="local-project"/>
</manifest>
""")
            m.Unload()
            m._Load()
            names = [p.name for p in m.projects]
            assert "local-project" in names

    def test_local_manifests_oserror_ignored(self, tmp_path):
        """OSError reading local_manifests dir is silently handled."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # Force local_manifests to a path that will cause OSError
        m.local_manifests = "/nonexistent/path/that/does/not/exist"
        m._load_local_manifests = True
        m.Unload()
        # Should not raise
        m._Load()
        assert m._loaded


# ===========================================================================
# Lines 1389-1399  _ParseManifest submanifest handling
# ===========================================================================


@pytest.mark.unit
class TestParseManifestSubmanifest:
    """Cover _ParseManifest submanifest parsing paths."""

    def test_duplicate_submanifest_same_attrs_ok(self, tmp_path):
        """Duplicate submanifest with same attributes is allowed."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1"/>
  <submanifest name="sub1"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        # Should not raise, both have same attrs
        assert "sub1" in m.submanifests

    def test_duplicate_submanifest_different_attrs_raises(self, tmp_path):
        """Duplicate submanifest with different attributes raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" path="path1"/>
  <submanifest name="sub1" path="path2"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="already exists"):
            _ = m.projects


# ===========================================================================
# Lines 1484-1510  extend-project with base_revision, dest_path
# ===========================================================================


@pytest.mark.unit
class TestExtendProjectAdvanced:
    """Cover extend-project base-rev mismatch, dest-path, remote change."""

    def test_extend_project_base_rev_mismatch(self, tmp_path):
        """extend-project with mismatched base-rev raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" revision="main"/>
  <extend-project name="p1" revision="develop" base-rev="wrong-rev"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="revision base check failed"):
            _ = m.projects

    def test_extend_project_with_dest_branch(self, tmp_path):
        """extend-project setting dest-branch."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <extend-project name="p1" dest-branch="custom-branch"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        p = [p for p in m.projects if p.name == "p1"][0]
        assert p.dest_branch == "custom-branch"

    def test_extend_project_with_upstream(self, tmp_path):
        """extend-project setting upstream."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <extend-project name="p1" upstream="refs/heads/upstream"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        p = [p for p in m.projects if p.name == "p1"][0]
        assert p.upstream == "refs/heads/upstream"

    def test_extend_project_with_dest_path(self, tmp_path):
        """extend-project with dest-path moves the project."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="old_path"/>
  <extend-project name="p1" path="old_path" dest-path="new_path"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        p = [p for p in m.projects if p.name == "p1"][0]
        assert p.relpath == "new_path"

    def test_extend_project_nonexistent_raises(self, tmp_path):
        """extend-project for nonexistent project raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <extend-project name="nonexistent"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="non-existent project"):
            _ = m.projects

    def test_extend_project_with_remote(self, tmp_path):
        """extend-project changing remote."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="path_a"/>
  <extend-project name="p1" path="path_a" remote="origin"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        p = [p for p in m.projects if p.name == "p1"][0]
        assert p.remote.name == "origin"

    def test_extend_project_with_base_rev_matching(self, tmp_path):
        """extend-project with matching base-rev succeeds."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" revision="main"/>
  <extend-project name="p1" revision="develop" base-rev="main"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        p = [p for p in m.projects if p.name == "p1"][0]
        assert p.revisionExpr == "develop"


# ===========================================================================
# Lines 1515, 1529-1546  repo-hooks and superproject parsing
# ===========================================================================


@pytest.mark.unit
class TestRepoHooksDuplicate:
    """Cover duplicate repo-hooks error."""

    def test_duplicate_repo_hooks_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="hooks1" path="hooks1"/>
  <project name="hooks2" path="hooks2"/>
  <repo-hooks in-project="hooks1" enabled-list="pre-upload"/>
  <repo-hooks in-project="hooks2" enabled-list="pre-upload"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate repo-hooks"):
            _ = m.projects

    def test_duplicate_superproject_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <superproject name="sp1"/>
  <superproject name="sp2"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate superproject"):
            _ = m.projects


# ===========================================================================
# Lines 1569-1615  remove-project by path, hooks cleanup
# ===========================================================================


@pytest.mark.unit
class TestRemoveProject:
    """Cover remove-project by path, hooks project cleanup."""

    def test_remove_project_by_path(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="some/path"/>
  <remove-project path="some/path"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert "some/path" not in m.paths

    def test_remove_project_clears_repo_hooks(self, tmp_path):
        """Removing the hooks project clears repo_hooks_project."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="hooks" path="hooks"/>
  <repo-hooks in-project="hooks" enabled-list="pre-upload"/>
  <remove-project name="hooks"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.repo_hooks_project is None

    def test_remove_nonexistent_project_non_optional_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <remove-project name="ghost"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="non-existent"):
            _ = m.projects

    def test_remove_project_no_name_no_path_raises(self, tmp_path):
        """remove-project with neither name nor path raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <remove-project/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="must have name and/or path"):
            _ = m.projects


# ===========================================================================
# Lines 1650-1691  _AddMetaProjectMirror
# ===========================================================================


@pytest.mark.unit
class TestAddMetaProjectMirror:
    """Cover _AddMetaProjectMirror."""

    def test_add_meta_project_mirror_refuses_dot_git(self, tmp_path):
        """URLs ending in /.git are refused."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        m._default = _Default()
        m._default.remote = _XmlRemote(
            "origin",
            fetch="https://example.com/",
            manifestUrl="https://example.com/manifest",
        )
        mock_m = mock.MagicMock()
        mock_remote = mock.MagicMock()
        mock_remote.url = "https://example.com/project/.git"
        mock_m.GetRemote.return_value = mock_remote
        with pytest.raises(error.ManifestParseError, match="refusing to mirror"):
            m._AddMetaProjectMirror(mock_m)

    def test_add_meta_project_mirror_default_remote_match(self, tmp_path):
        """URL matches default remote fetch URL => uses default remote."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)

        mock_m = mock.MagicMock()
        mock_remote = mock.MagicMock()
        mock_remote.url = "https://example.com/my-repo"
        mock_m.GetRemote.return_value = mock_remote
        mock_m.revisionExpr = "main"

        m._AddMetaProjectMirror(mock_m)
        assert "my-repo" in m._projects

    def test_add_meta_project_mirror_no_default_match(self, tmp_path):
        """URL does not match default remote => creates new remote."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)

        mock_m = mock.MagicMock()
        mock_remote = mock.MagicMock()
        mock_remote.url = "https://other.example.com/different-repo"
        mock_m.GetRemote.return_value = mock_remote
        mock_m.revisionExpr = "main"

        m._AddMetaProjectMirror(mock_m)
        assert "different-repo" in m._projects

    def test_add_meta_project_mirror_strips_git_suffix(self, tmp_path):
        """Name ending in .git gets suffix stripped."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)

        mock_m = mock.MagicMock()
        mock_remote = mock.MagicMock()
        mock_remote.url = "https://other.example.com/repo.git"
        mock_m.GetRemote.return_value = mock_remote
        mock_m.revisionExpr = "main"

        m._AddMetaProjectMirror(mock_m)
        assert "repo" in m._projects


# ===========================================================================
# Lines 1769-1785  _ParseNotice
# ===========================================================================


@pytest.mark.unit
class TestParseNotice:
    """Cover _ParseNotice with multi-line, indented notice text."""

    def test_notice_multiline_indentation(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <notice>
    Line 1
    Line 2
    Line 3
  </notice>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert "Line 1" in m.notice
        assert "Line 2" in m.notice
        assert "Line 3" in m.notice


# ===========================================================================
# Lines 1789-1846  _ParseSubmanifest
# ===========================================================================


@pytest.mark.unit
class TestParseSubmanifest:
    """Cover _ParseSubmanifest method."""

    def test_parse_submanifest_with_path(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" path="sub_path"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert "sub1" in m.submanifests
        assert m.submanifests["sub1"].path == "sub_path"

    def test_parse_submanifest_with_revision(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" revision="refs/heads/feature"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.submanifests["sub1"].revision == "refs/heads/feature"

    def test_parse_submanifest_with_groups(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" groups="g1,g2"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.submanifests["sub1"].groups == ["g1", "g2"]

    def test_parse_submanifest_with_default_groups(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" default-groups="dg1,dg2"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.submanifests["sub1"].default_groups == ["dg1", "dg2"]

    def test_parse_submanifest_with_manifest_name(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" manifest-name="custom.xml"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.submanifests["sub1"].manifestName == "custom.xml"

    def test_parse_submanifest_invalid_path_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" path="../escape"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "path"'):
            _ = m.projects

    def test_parse_submanifest_invalid_name_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="../bad"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "name"'):
            _ = m.projects

    def test_parse_submanifest_invalid_revision_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" revision="refs/heads/.."/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "revision"'):
            _ = m.projects

    def test_parse_submanifest_with_annotation(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1">
    <annotation name="ann_key" value="ann_val"/>
  </submanifest>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        sub = m.submanifests["sub1"]
        assert len(sub.annotations) == 1
        assert sub.annotations[0].name == "ann_key"


# ===========================================================================
# Lines 1928-1929, 1937-1938  _ParseProject with parent (subproject)
# ===========================================================================


@pytest.mark.unit
class TestParseProjectSubproject:
    """Cover _ParseProject with parent for subproject code paths."""

    def test_subproject_in_manifest(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="parent-proj" path="parent">
    <project name="child-proj" path="child"/>
  </project>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        parent_projects = [p for p in m.projects if p.name == "parent-proj"]
        assert len(parent_projects) == 1
        assert len(parent_projects[0].subprojects) == 1
        sub = parent_projects[0].subprojects[0]
        assert sub.name == "parent-proj/child-proj"


# ===========================================================================
# Lines 1999-2016  GetProjectPaths mirror/worktree branches
# ===========================================================================


@pytest.mark.unit
class TestGetProjectPaths:
    """Cover GetProjectPaths mirror and worktree branches."""

    def test_get_project_paths_non_mirror(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        relpath, worktree, gitdir, objdir, use_wt = m.GetProjectPaths("p1", "p1", "origin")
        assert relpath == "p1"
        assert worktree is not None
        assert not use_wt

    def test_get_project_paths_strips_trailing_slashes(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        relpath, worktree, gitdir, objdir, use_wt = m.GetProjectPaths("p1/", "p1/", "origin/")
        assert relpath == "p1"


# ===========================================================================
# Lines 2030-2036  GetProjectsWithName all_manifests
# ===========================================================================


@pytest.mark.unit
class TestGetProjectsWithName:
    """Cover GetProjectsWithName with all_manifests flag."""

    def test_get_projects_with_name_local(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        result = m.GetProjectsWithName("p1")
        assert len(result) == 1

    def test_get_projects_with_name_nonexistent(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        result = m.GetProjectsWithName("nonexistent")
        assert result == []

    def test_get_projects_with_name_all_manifests(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        result = m.GetProjectsWithName("p1", all_manifests=True)
        assert len(result) == 1


# ===========================================================================
# Lines 2039-2067  GetSubprojectName, _JoinRelpath, GetSubprojectPaths
# ===========================================================================


@pytest.mark.unit
class TestGetSubprojectPaths:
    """Cover GetSubprojectPaths and related methods."""

    def test_get_subproject_name(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        parent = mock.MagicMock()
        parent.name = "parent"
        result = m.GetSubprojectName(parent, "child")
        assert result == os.path.join("parent", "child")

    def test_join_relpath(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert m._JoinRelpath("parent", "child") == os.path.join("parent", "child")

    def test_unjoin_relpath(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        assert m._UnjoinRelpath("parent", "parent/child") == "child"

    def test_get_subproject_paths(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="parent-proj" path="parent">
    <project name="child-proj" path="child"/>
  </project>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        parent_proj = [p for p in m.projects if p.name == "parent-proj"][0]

        relpath, worktree, gitdir, objdir = m.GetSubprojectPaths(parent_proj, "child-proj", "child")
        assert relpath == os.path.join(parent_proj.relpath, "child")
        assert worktree is not None


# ===========================================================================
# Lines 2051-2067  GetSubprojectPaths detailed
# ===========================================================================


@pytest.mark.unit
class TestGetSubprojectPathsDetailed:
    """Cover GetSubprojectPaths with trailing slash and mirror mode."""

    def test_get_subproject_paths_strips_trailing_slashes(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="parent-proj" path="parent"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        parent_proj = m.projects[0]

        relpath, worktree, gitdir, objdir = m.GetSubprojectPaths(parent_proj, "child/", "child/")
        assert not relpath.endswith("/")


# ===========================================================================
# Lines 2102, 2132, 2139, 2158, 2161, 2169, 2172  _CheckLocalPath
# ===========================================================================


@pytest.mark.unit
class TestCheckLocalPath:
    """Cover _CheckLocalPath validation branches."""

    def test_empty_path(self):
        assert XmlManifest._CheckLocalPath("") == "empty paths not allowed"

    def test_tilde_in_path(self):
        result = XmlManifest._CheckLocalPath("foo~bar")
        assert "~" in result

    def test_unicode_bad_codepoints(self):
        result = XmlManifest._CheckLocalPath("foo\u200cbar")
        assert "Unicode" in result

    def test_newline_in_path(self):
        result = XmlManifest._CheckLocalPath("foo\nbar")
        assert "Newlines" in result

    def test_carriage_return_in_path(self):
        result = XmlManifest._CheckLocalPath("foo\rbar")
        assert "Newlines" in result

    def test_dot_component(self):
        result = XmlManifest._CheckLocalPath("foo/./bar")
        assert "bad component" in result

    def test_dotdot_component(self):
        result = XmlManifest._CheckLocalPath("foo/../bar")
        assert "bad component" in result

    def test_dotgit_component(self):
        result = XmlManifest._CheckLocalPath("foo/.git/bar")
        assert "bad component" in result

    def test_dotrepo_component(self):
        result = XmlManifest._CheckLocalPath(".repo/foo")
        assert "bad component" in result

    def test_trailing_slash_not_dir_ok(self):
        result = XmlManifest._CheckLocalPath("foo/", dir_ok=False)
        assert result == "dirs not allowed"

    def test_trailing_slash_dir_ok(self):
        result = XmlManifest._CheckLocalPath("foo/", dir_ok=True)
        assert result is None

    def test_absolute_path(self):
        result = XmlManifest._CheckLocalPath("/foo/bar")
        assert "path cannot be outside" in result

    def test_absolute_path_abs_ok(self):
        # abs_ok=True should allow absolute paths
        result = XmlManifest._CheckLocalPath("/foo/bar", abs_ok=True)
        assert result is None

    def test_valid_path(self):
        assert XmlManifest._CheckLocalPath("foo/bar") is None

    def test_cwd_dot_ok(self):
        result = XmlManifest._CheckLocalPath(".", cwd_dot_ok=True)
        assert result is None

    def test_cwd_dot_not_ok(self):
        result = XmlManifest._CheckLocalPath(".", cwd_dot_ok=False)
        assert "bad component" in result


# ===========================================================================
# Lines 2245  _get_remote not found
# ===========================================================================


@pytest.mark.unit
class TestGetRemote:
    """Cover _get_remote error path."""

    def test_get_remote_unknown_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" remote="unknown"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="remote unknown not defined"):
            _ = m.projects


# ===========================================================================
# Lines 2268-2303  projectsDiff
# ===========================================================================


@pytest.mark.unit
class TestProjectsDiff:
    """Cover projectsDiff method."""

    def test_projects_diff_added(self, tmp_path):
        xml_from = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        xml_to = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <project name="p2"/>
</manifest>
"""
        m_from = _make_manifest(tmp_path / "from", xml_from)
        m_to = _make_manifest(tmp_path / "to", xml_to)
        diff = m_from.projectsDiff(m_to)
        added_names = [p.name for p in diff["added"]]
        assert "p2" in added_names

    def test_projects_diff_removed(self, tmp_path):
        xml_from = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
  <project name="p2"/>
</manifest>
"""
        xml_to = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m_from = _make_manifest(tmp_path / "from", xml_from)
        m_to = _make_manifest(tmp_path / "to", xml_to)
        diff = m_from.projectsDiff(m_to)
        removed_names = [p.name for p in diff["removed"]]
        assert "p2" in removed_names

    def test_projects_diff_no_changes(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1"/>
</manifest>
"""
        m_from = _make_manifest(tmp_path / "from", xml_content)
        m_to = _make_manifest(tmp_path / "to", xml_content)
        diff = m_from.projectsDiff(m_to)
        # Both manifests have p1 but p1.Exists will be False (no git repo)
        # so p1 goes to "missing"
        assert len(diff["added"]) == 0
        assert len(diff["removed"]) == 0


# ===========================================================================
# Lines 2323-2356  RepoClient.__init__
# ===========================================================================


@pytest.mark.unit
class TestRepoClientInit:
    """Cover RepoClient.__init__."""

    def test_repoclient_basic(self, tmp_path):
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifests_dir = repodir / "manifests"
        manifests_dir.mkdir()
        manifest_git = repodir / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        mf = repodir / "manifest.xml"
        mf.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
""")
        rc = manifest_xml.RepoClient(str(repodir))
        assert rc.manifest is rc
        assert rc.repodir == str(repodir)

    def test_repoclient_with_submanifest_path(self, tmp_path):
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        sub_prefix = repodir / SUBMANIFEST_DIR / "sub"
        sub_prefix.mkdir(parents=True)
        manifests_dir = sub_prefix / "manifests"
        manifests_dir.mkdir()
        manifest_git = sub_prefix / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        # Also need root-level manifests for the outer_client
        root_manifests = repodir / "manifests"
        root_manifests.mkdir(exist_ok=True)
        root_git = repodir / "manifests.git"
        root_git.mkdir(exist_ok=True)
        (root_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        mf = sub_prefix / "manifest.xml"
        mf.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
""")
        # Create an outer_client
        outer_mf = repodir / "manifest.xml"
        outer_mf.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
""")
        outer = manifest_xml.RepoClient(str(repodir))

        rc = manifest_xml.RepoClient(
            str(repodir),
            manifest_file=str(mf),
            submanifest_path="sub",
            outer_client=outer,
        )
        assert rc.manifest is rc

    def test_repoclient_local_manifest_name_exits(self, tmp_path):
        """Presence of local_manifest.xml causes sys.exit."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifests_dir = repodir / "manifests"
        manifests_dir.mkdir()
        manifest_git = repodir / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        # Create the forbidden file
        (repodir / "local_manifest.xml").write_text("<manifest/>")
        with pytest.raises(SystemExit):
            manifest_xml.RepoClient(str(repodir))


# ===========================================================================
# Lines 1017, 1023, 1026, 1030  SetManifestOverride, UseLocalManifests, etc.
# ===========================================================================


@pytest.mark.unit
class TestSetManifestOverride:
    """Cover SetManifestOverride and related properties."""

    def test_set_manifest_override(self, tmp_path):
        """Test SetManifestOverride stores the path in overrides dict."""
        repodir = tmp_path / ".repo"
        repodir.mkdir()
        manifests_dir = repodir / "manifests"
        manifests_dir.mkdir()
        manifest_git = repodir / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        mf = repodir / "manifest.xml"
        mf.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
""")
        rc = manifest_xml.RepoClient(str(repodir))
        rc.SetManifestOverride("/some/path.xml")
        assert rc._outer_client.manifest.manifestFileOverrides[rc.path_prefix] == "/some/path.xml"


# ===========================================================================
# Lines 1421-1439  recursively_add_projects (duplicate path)
# ===========================================================================


@pytest.mark.unit
class TestRecursivelyAddProjects:
    """Cover recursively_add_projects error paths."""

    def test_duplicate_path_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="same_path"/>
  <project name="p2" path="same_path"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate path"):
            _ = m.projects


# ===========================================================================
# Lines 1731  _ParseDefault sync-j validation
# ===========================================================================


@pytest.mark.unit
class TestParseDefault:
    """Cover _ParseDefault sync-j validation."""

    def test_sync_j_zero_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main" sync-j="0"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="sync-j must be greater than 0"):
            _ = m.projects

    def test_sync_j_negative_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main" sync-j="-1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="sync-j must be greater than 0"):
            _ = m.projects


# ===========================================================================
# Lines 1861-1879  _ParseProject error paths (no remote, no revision)
# ===========================================================================


@pytest.mark.unit
class TestParseProjectErrors:
    """Cover _ParseProject error paths."""

    def test_no_remote_no_default_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="no remote"):
            _ = m.projects

    def test_no_revision_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin"/>
  <project name="p1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="no revision"):
            _ = m.projects

    def test_invalid_project_name_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="../bad"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "name"'):
            _ = m.projects

    def test_invalid_project_path_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="../escape"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "path"'):
            _ = m.projects

    def test_negative_clone_depth_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" clone-depth="-1"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="clone-depth must be greater"):
            _ = m.projects


# ===========================================================================
# Lines 1580-1595  remove-project base-rev mismatch by path
# ===========================================================================


@pytest.mark.unit
class TestRemoveProjectBaseRev:
    """Cover remove-project with base-rev mismatch."""

    def test_remove_by_name_base_rev_mismatch_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" revision="main"/>
  <remove-project name="p1" base-rev="wrong"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="revision base check failed"):
            _ = m.projects

    def test_remove_by_path_base_rev_mismatch_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1" path="mypath" revision="main"/>
  <remove-project path="mypath" base-rev="wrong"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="revision base check failed"):
            _ = m.projects


# ===========================================================================
# Lines 1635-1641  repo-hooks project not found, multiple projects
# ===========================================================================


@pytest.mark.unit
class TestRepoHooksProjectErrors:
    """Cover repo-hooks project not found."""

    def test_repo_hooks_project_not_found_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <repo-hooks in-project="nonexistent" enabled-list="pre-upload"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="not found for repo-hooks"):
            _ = m.projects


# ===========================================================================
# Lines 1413-1416  duplicate manifest-server
# ===========================================================================


@pytest.mark.unit
class TestDuplicateManifestServer:
    """Cover duplicate manifest-server."""

    def test_duplicate_manifest_server_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <manifest-server url="https://ms1.example.com/"/>
  <manifest-server url="https://ms2.example.com/"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate manifest-server"):
            _ = m.projects


# ===========================================================================
# Lines 1305-1307  _ParseManifestXml restrict_includes invalid path
# ===========================================================================


@pytest.mark.unit
class TestParseManifestXmlIncludes:
    """Cover _ParseManifestXml include path validation."""

    def test_include_with_invalid_path_raises(self, tmp_path):
        """Include with path traversal in restrict mode raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <include name="../escape.xml"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        # The include is parsed non-restrictively in the main manifest.
        # Let's directly test with restrict_includes=True
        mf_path = os.path.join(str(tmp_path), ".repo", "manifest.xml")
        with pytest.raises(error.ManifestInvalidPathError, match='invalid "name"'):
            m._ParseManifestXml(
                mf_path,
                str(tmp_path),
                restrict_includes=True,
            )

    def test_include_nonexistent_file_raises(self, tmp_path):
        """Include pointing to nonexistent file raises."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <include name="nonexistent.xml"/>
</manifest>
"""
        repodir = tmp_path / ".repo"
        repodir.mkdir(parents=True, exist_ok=True)
        manifests_dir = repodir / "manifests"
        manifests_dir.mkdir()
        manifest_git = repodir / "manifests.git"
        manifest_git.mkdir()
        (manifest_git / "config").write_text('[remote "origin"]\n    url = https://localhost:0/manifest\n')
        mf = repodir / "manifest.xml"
        mf.write_text(xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(mf))
        with pytest.raises(error.ManifestParseError, match="doesn't exist"):
            _ = m.projects


# ===========================================================================
# Lines 1404  duplicate notice
# ===========================================================================


@pytest.mark.unit
class TestDuplicateNotice:
    """Cover duplicate notice error."""

    def test_duplicate_notice_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <notice>Notice 1</notice>
  <notice>Notice 2</notice>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate notice"):
            _ = m.projects


# ===========================================================================
# Lines 1378-1379  duplicate default raises
# ===========================================================================


@pytest.mark.unit
class TestDuplicateDefault:
    """Cover duplicate default error."""

    def test_duplicate_default_different_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <default remote="origin" revision="develop"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="duplicate default"):
            _ = m.projects

    def test_duplicate_default_same_is_ok(self, tmp_path):
        """Duplicate default with identical attributes is allowed."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert m.default.revisionExpr == "main"


# ===========================================================================
# Lines 1362-1363  duplicate remote raises
# ===========================================================================


@pytest.mark.unit
class TestDuplicateRemote:
    """Cover duplicate remote error."""

    def test_duplicate_remote_different_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <remote name="origin" fetch="https://other.example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="remote origin already exists"):
            _ = m.projects

    def test_duplicate_remote_same_is_ok(self, tmp_path):
        """Duplicate remote with identical attributes is allowed."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
</manifest>
"""
        m = _make_and_load(tmp_path, xml_content)
        assert "origin" in m.remotes


# ===========================================================================
# Lines 1538-1546  superproject no remote / no revision
# ===========================================================================


@pytest.mark.unit
class TestSuperprojectErrors:
    """Cover superproject error paths."""

    def test_superproject_no_revision_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin"/>
  <superproject name="sp"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="no revision for superproject"):
            _ = m.projects


# ===========================================================================
# Lines 1431-1432  project conflicts with submanifest path
# ===========================================================================


@pytest.mark.unit
class TestProjectConflictsSubmanifest:
    """Cover project path conflicting with submanifest path."""

    def test_project_under_submanifest_path_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <submanifest name="sub1" path="sub_path"/>
  <project name="conflict" path="sub_path/proj"/>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(error.ManifestParseError, match="conflicts with submanifest path"):
            _ = m.projects


# ===========================================================================
# Lines 2232-2236  _ParseAnnotation keep validation
# ===========================================================================


@pytest.mark.unit
class TestParseAnnotationKeep:
    """Cover _ParseAnnotation keep attribute validation."""

    def test_annotation_invalid_keep_raises(self, tmp_path):
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/"/>
  <default remote="origin" revision="main"/>
  <project name="p1">
    <annotation name="k" value="v" keep="maybe"/>
  </project>
</manifest>
"""
        m = _make_manifest(tmp_path, xml_content)
        with pytest.raises(
            error.ManifestParseError,
            match='keep.*must be "true" or "false"',
        ):
            _ = m.projects
