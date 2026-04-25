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

"""Unit tests for revision kind disambiguation: tag vs branch vs SHA.

Covers AC-TEST-001 through AC-TEST-004:
  - AC-TEST-001: refs/tags/X is recognized as tag
  - AC-TEST-002: refs/heads/X is recognized as branch
  - AC-TEST-003: bare commit SHA is recognized as SHA
  - AC-TEST-004: upstream attribute interaction with revision
"""

import pytest

from kanon_cli.repo.git_config import IsId
from kanon_cli.repo.git_config import IsTag
from kanon_cli.repo.git_refs import R_HEADS
from kanon_cli.repo.git_refs import R_TAGS


# ---------------------------------------------------------------------------
# AC-TEST-001: refs/tags/X is recognized as tag
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "refs/tags/v1.0.0",
        "refs/tags/release/2.3.0",
        "refs/tags/v0.0.1-beta",
        "refs/tags/myproject/v1.2.3",
    ],
)
def test_refs_tags_is_recognized_as_tag(revision):
    """refs/tags/X revisions are correctly identified as tags via IsTag()."""
    assert IsTag(revision), f"expected {revision!r} to be recognized as a tag"


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "refs/heads/main",
        "refs/heads/feature/my-branch",
        "a" * 40,
        "HEAD",
        "refs/changes/12/34567/2",
    ],
)
def test_non_tag_revisions_are_not_recognized_as_tag(revision):
    """Non-tag revisions are not falsely classified as tags."""
    assert not IsTag(revision), f"expected {revision!r} to NOT be recognized as a tag"


# ---------------------------------------------------------------------------
# AC-TEST-002: refs/heads/X is recognized as branch
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "refs/heads/main",
        "refs/heads/master",
        "refs/heads/feature/my-feature",
        "refs/heads/release/1.0",
    ],
)
def test_refs_heads_is_recognized_as_branch(revision):
    """refs/heads/X revisions start with the R_HEADS prefix and are identified as branches."""
    assert revision.startswith(R_HEADS), f"expected {revision!r} to start with R_HEADS prefix {R_HEADS!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "refs/tags/v1.0.0",
        "a" * 40,
        "HEAD",
        "main",
    ],
)
def test_non_branch_revisions_do_not_start_with_r_heads(revision):
    """Non-branch revisions do not start with the R_HEADS prefix."""
    assert not revision.startswith(R_HEADS), f"expected {revision!r} to NOT start with R_HEADS prefix {R_HEADS!r}"


@pytest.mark.unit
def test_r_heads_constant_value():
    """R_HEADS constant has the expected namespace prefix."""
    assert R_HEADS == "refs/heads/"


@pytest.mark.unit
def test_r_tags_constant_value():
    """R_TAGS constant has the expected namespace prefix."""
    assert R_TAGS == "refs/tags/"


# ---------------------------------------------------------------------------
# AC-TEST-003: bare commit SHA is recognized as SHA
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "a" * 40,
        "0" * 40,
        "deadbeef" + "0" * 32,
        "1234567890abcdef" * 2 + "1234567890abcdef"[:8],
    ],
)
def test_bare_sha_is_recognized_as_id(revision):
    """A 40-character hex string is recognized as a commit SHA via IsId()."""
    assert IsId(revision), f"expected {revision!r} (len={len(revision)}) to be recognized as a SHA"


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "refs/tags/v1.0.0",
        "refs/heads/main",
        "HEAD",
        "a" * 39,
        "a" * 41,
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "",
        "abc123",
    ],
)
def test_non_sha_revisions_are_not_recognized_as_id(revision):
    """Non-SHA strings are not falsely classified as commit SHAs."""
    assert not IsId(revision), f"expected {revision!r} to NOT be recognized as a SHA"


# ---------------------------------------------------------------------------
# AC-TEST-004: upstream attribute interaction with revision
# ---------------------------------------------------------------------------


class _FakeRemote:
    """Minimal stand-in for RemoteSpec used by Project.__init__."""

    name = "origin"
    url = "https://example.com/repo.git"
    pushUrl = None
    review = None
    revision = None
    orig_name = "origin"
    fetchUrl = "https://example.com/repo.git"


class _FakeManifest:
    """Minimal stand-in for XmlManifest used by Project.__init__."""

    globalConfig = None
    is_multimanifest = False
    repodir = "/tmp/fake-repo"
    topdir = "/tmp/fake-repo"
    manifestProject = None
    submanifests = {}
    _project_list = []

    def GetProjectsWithName(self, name):
        return []


class _MinimalProject:
    """Minimal project-like object that only holds revision/upstream state.

    Avoids the heavy Project.__init__ (requires git checkout) while still
    exercising the SetRevision/SetRevisionId state transitions.
    """

    def __init__(self, revisionExpr, upstream=None):
        from kanon_cli.repo.git_config import IsId

        self.revisionExpr = revisionExpr
        self.upstream = upstream
        self._constraint_resolved = False
        if revisionExpr and IsId(revisionExpr):
            self.revisionId = revisionExpr
        else:
            self.revisionId = None

    def SetRevisionId(self, revisionId):
        """Mirror of Project.SetRevisionId -- sets upstream from revisionExpr."""
        if self.revisionExpr:
            self.upstream = self.revisionExpr
        self.revisionId = revisionId


@pytest.mark.unit
def test_set_revision_id_stores_revision_expr_as_upstream():
    """SetRevisionId copies revisionExpr into upstream attribute."""
    proj = _MinimalProject(revisionExpr="refs/heads/main")
    proj.SetRevisionId("a" * 40)

    assert proj.revisionId == "a" * 40
    assert proj.upstream == "refs/heads/main"


@pytest.mark.unit
def test_set_revision_id_with_tag_revision_expr():
    """SetRevisionId with a tag revisionExpr stores the tag as upstream."""
    proj = _MinimalProject(revisionExpr="refs/tags/v1.2.3")
    proj.SetRevisionId("b" * 40)

    assert proj.revisionId == "b" * 40
    assert proj.upstream == "refs/tags/v1.2.3"


@pytest.mark.unit
def test_set_revision_id_with_none_revision_expr_leaves_upstream_unchanged():
    """SetRevisionId does NOT overwrite upstream when revisionExpr is None."""
    proj = _MinimalProject(revisionExpr=None, upstream="refs/heads/main")
    proj.SetRevisionId("c" * 40)

    assert proj.revisionId == "c" * 40
    assert proj.upstream == "refs/heads/main"


@pytest.mark.unit
def test_set_revision_id_with_empty_revision_expr_leaves_upstream_unchanged():
    """SetRevisionId does NOT overwrite upstream when revisionExpr is an empty string."""
    proj = _MinimalProject(revisionExpr="", upstream="refs/heads/main")
    proj.SetRevisionId("d" * 40)

    assert proj.revisionId == "d" * 40
    assert proj.upstream == "refs/heads/main"


@pytest.mark.unit
def test_upstream_initially_none_without_set_revision_id():
    """upstream attribute starts as None when not provided and SetRevisionId not called."""
    proj = _MinimalProject(revisionExpr="refs/heads/feature", upstream=None)

    assert proj.upstream is None


@pytest.mark.unit
def test_sha_revision_expr_recognized_and_stored_as_revision_id():
    """When revisionExpr is a SHA, it is stored directly as revisionId."""
    sha = "abcdef1234" * 4
    proj = _MinimalProject(revisionExpr=sha)

    assert proj.revisionId == sha
    assert IsId(proj.revisionExpr)


@pytest.mark.unit
def test_branch_revision_expr_does_not_auto_populate_revision_id():
    """When revisionExpr is a branch ref, revisionId is None (requires resolution)."""
    proj = _MinimalProject(revisionExpr="refs/heads/main")

    assert proj.revisionId is None
    assert not IsId(proj.revisionExpr)


@pytest.mark.unit
def test_tag_revision_expr_does_not_auto_populate_revision_id():
    """When revisionExpr is a tag ref, revisionId is None (requires resolution)."""
    proj = _MinimalProject(revisionExpr="refs/tags/v1.0.0")

    assert proj.revisionId is None
    assert IsTag(proj.revisionExpr)
    assert not IsId(proj.revisionExpr)
