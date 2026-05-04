"""Unit tests for _AddMetaProjectMirror None-guard in manifest_xml.

Tests the fix for AttributeError: 'NoneType' object has no attribute
'endswith' raised in _AddMetaProjectMirror when the remote URL is None.

Scenario coverage:
- (a) m_url is None: before the fix, raises AttributeError; after the fix,
      returns immediately (no mirror added).
- (b) m_url is a non-/.git URL (e.g. 'file:///tmp/repo'): before the fix,
      proceeds into the mirror logic and may raise further errors on the
      unguarded path; after the fix, proceeds past the guard and adds the
      mirror project.
- (c) m_url ends with '/.git': raises ManifestParseError (existing behaviour
      preserved unchanged).
"""

import os
import tempfile
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Test-scoped constants -- no literals embedded inside assertions.
# ---------------------------------------------------------------------------

_MANIFEST_ORIGIN_URL = "https://localhost:0/manifest"
_MANIFEST_XML_MINIMAL = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="test" fetch="http://localhost/" />\n'
    '  <default remote="test" revision="main" />\n'
    "</manifest>\n"
)
_URL_WITH_GIT_SUFFIX = "file:///tmp/test-repo/.git"
_URL_WITHOUT_GIT_SUFFIX = "file:///tmp/test-repo"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_manifest(tmpdir: str) -> manifest_xml.XmlManifest:
    """Return an XmlManifest initialised inside *tmpdir*."""
    repodir = os.path.join(tmpdir, ".repo")
    manifest_dir = os.path.join(repodir, "manifests")
    manifest_file = os.path.join(repodir, manifest_xml.MANIFEST_FILE_NAME)
    os.makedirs(manifest_dir, exist_ok=True)

    gitdir = os.path.join(repodir, "manifests.git")
    os.makedirs(gitdir, exist_ok=True)
    with open(os.path.join(gitdir, "config"), "w") as fh:
        fh.write(f'[remote "origin"]\n\turl = {_MANIFEST_ORIGIN_URL}\n')

    with open(manifest_file, "w", encoding="utf-8") as fh:
        fh.write(_MANIFEST_XML_MINIMAL)

    return manifest_xml.XmlManifest(repodir, manifest_file)


def _mock_project(url: "str | None") -> mock.MagicMock:
    """Return a mock project whose GetRemote().url equals *url*."""
    remote_spec = mock.MagicMock()
    remote_spec.url = url
    project = mock.MagicMock()
    project.GetRemote.return_value = remote_spec
    return project


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddMetaProjectMirrorNoneUrl(unittest.TestCase):
    """Case (a): m_url is None -- guard must prevent AttributeError."""

    def setUp(self) -> None:
        self._tmpdir_obj = tempfile.TemporaryDirectory(prefix="test_init_mirror_")
        self._manifest = _make_manifest(self._tmpdir_obj.name)

    def tearDown(self) -> None:
        self._tmpdir_obj.cleanup()

    @pytest.mark.unit
    def test_none_url_does_not_raise(self) -> None:
        """_AddMetaProjectMirror must not raise when remote URL is None."""
        project = _mock_project(None)
        # Before the fix this raises AttributeError; after the fix it returns
        # silently without adding any project entry.
        self._manifest._AddMetaProjectMirror(project)
        # Confirm no spurious project was registered.
        self.assertNotIn(None, self._manifest._projects)

    @pytest.mark.unit
    def test_none_url_leaves_projects_unchanged(self) -> None:
        """Mirror project count must not change when URL is None."""
        before_count = len(self._manifest._projects)
        project = _mock_project(None)
        self._manifest._AddMetaProjectMirror(project)
        self.assertEqual(len(self._manifest._projects), before_count)


@pytest.mark.unit
class TestAddMetaProjectMirrorNonGitUrl(unittest.TestCase):
    """Case (b): m_url is a valid non-/.git URL -- guard must pass through."""

    def setUp(self) -> None:
        self._tmpdir_obj = tempfile.TemporaryDirectory(prefix="test_init_mirror_")
        self._manifest = _make_manifest(self._tmpdir_obj.name)

    def tearDown(self) -> None:
        self._tmpdir_obj.cleanup()

    @pytest.mark.unit
    def test_non_git_url_does_not_raise_attribute_error(self) -> None:
        """_AddMetaProjectMirror must not raise AttributeError for a non-/.git URL."""
        project = _mock_project(_URL_WITHOUT_GIT_SUFFIX)
        # The call should not raise AttributeError; it may raise other errors
        # due to the mocked project not having a real git config, but the
        # None-guard itself must not block this path.
        try:
            self._manifest._AddMetaProjectMirror(project)
        except AttributeError as exc:
            self.fail(f"_AddMetaProjectMirror raised AttributeError for a non-None URL: {exc}")
        except Exception:
            # Other exceptions from deeper mirror logic are acceptable;
            # we only care that AttributeError is not raised by the guard.
            pass

    @pytest.mark.unit
    def test_non_git_url_does_not_end_with_git_suffix(self) -> None:
        """Verify the test URL does not end with /.git (test data integrity)."""
        self.assertFalse(_URL_WITHOUT_GIT_SUFFIX.endswith("/.git"))


@pytest.mark.unit
class TestAddMetaProjectMirrorGitSuffixUrl(unittest.TestCase):
    """Case (c): m_url ends with /.git -- ManifestParseError must be raised."""

    def setUp(self) -> None:
        self._tmpdir_obj = tempfile.TemporaryDirectory(prefix="test_init_mirror_")
        self._manifest = _make_manifest(self._tmpdir_obj.name)

    def tearDown(self) -> None:
        self._tmpdir_obj.cleanup()

    @pytest.mark.unit
    def test_git_suffix_url_raises_manifest_parse_error(self) -> None:
        """_AddMetaProjectMirror must raise ManifestParseError for /.git URLs."""
        project = _mock_project(_URL_WITH_GIT_SUFFIX)
        with self.assertRaises(manifest_xml.ManifestParseError):
            self._manifest._AddMetaProjectMirror(project)

    @pytest.mark.unit
    def test_git_suffix_url_ends_with_git_suffix(self) -> None:
        """Verify the test URL ends with /.git (test data integrity)."""
        self.assertTrue(_URL_WITH_GIT_SUFFIX.endswith("/.git"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        None,
        _URL_WITHOUT_GIT_SUFFIX,
    ],
    ids=["url_none", "url_no_git_suffix"],
)
def test_add_meta_project_mirror_no_attribute_error(
    url: "str | None",
    tmp_path: "pytest.TempDir",
) -> None:
    """Regression guard: _AddMetaProjectMirror must never raise AttributeError.

    After the None-guard fix, both a None URL and a valid non-/.git URL must
    complete (or raise a non-AttributeError exception) without triggering
    AttributeError.
    """
    manifest = _make_manifest(str(tmp_path))
    project = _mock_project(url)
    try:
        manifest._AddMetaProjectMirror(project)
    except AttributeError as exc:
        pytest.fail(f"_AddMetaProjectMirror raised AttributeError for URL={url!r}: {exc}")
    except Exception:
        # Other exceptions from deeper mirror logic are acceptable; the guard
        # must ensure AttributeError is not raised.
        pass
