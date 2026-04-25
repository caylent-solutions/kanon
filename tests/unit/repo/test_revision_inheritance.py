"""Unit tests for the revision inheritance chain.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

The revision for a <project> element is resolved in this order:
  1. The project's own ``revision`` attribute (highest priority)
  2. The ``revision`` attribute of the project's <remote> element
  3. The ``revision`` attribute of the <default> element
  4. If none of the above yields a revision, ManifestParseError is raised.

This order is codified in manifest_xml._ParseProject (lines 1752-1756):

    revisionExpr = node.getAttribute("revision") or remote.revision
    if not revisionExpr:
        revisionExpr = self._default.revisionExpr
    if not revisionExpr:
        raise ManifestParseError("no revision for project ...")

All tests use real manifest XML written to tmp_path via shared helpers that
mirror the conventions in test_xml_project_happy.py and test_xml_remote_happy.py.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every item
collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/    (the include_root / worktree)
    - <tmp>/.repo/manifests.git/config  (remote origin URL for GitConfig)

    Args:
        tmp_path: Pytest tmp_path for isolation.

    Returns:
        The absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file path and return it.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML content for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate and load an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _get_project(m: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from the loaded manifest.

    Args:
        m: A loaded XmlManifest instance.
        project_name: The name of the project to retrieve.

    Returns:
        The Project object with the given name.

    Raises:
        KeyError: If the project is not found.
    """
    projects_by_name = {p.name: p for p in m.projects}
    return projects_by_name[project_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: project with no revision inherits from remote.revision
#
# When a <project> element has no revision attribute but its <remote> element
# carries a revision attribute, the project's revisionExpr must equal the
# remote's revision.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectInheritsFromRemoteRevision:
    """Verify that a project without a revision attribute inherits remote.revision.

    AC-TEST-001, AC-FUNC-001
    """

    @pytest.mark.parametrize(
        "remote_revision",
        [
            "refs/heads/main",
            "refs/heads/release/1.0",
            "refs/tags/v2.0.0",
        ],
    )
    def test_project_inherits_remote_revision_when_no_project_revision(
        self,
        tmp_path: pathlib.Path,
        remote_revision: str,
    ) -> None:
        """A project without revision inherits the remote's revision attribute.

        The <remote revision="..."> attribute takes precedence over the
        <default revision="..."> attribute when the project has no explicit
        revision.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="myremote" fetch="https://example.com" revision="{remote_revision}" />\n'
            '  <default revision="refs/heads/default-branch" remote="myremote" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        proj = _get_project(m, "platform/core")

        assert proj.revisionExpr == remote_revision, (
            f"expected revisionExpr={remote_revision!r} from remote, got {proj.revisionExpr!r}"
        )

    def test_remote_revision_takes_precedence_over_default_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The remote's revision overrides the default element's revision.

        When both <remote revision="..."> and <default revision="..."> are
        present, a project without an explicit revision must use the remote's
        revision, not the default's.

        AC-TEST-001, AC-FUNC-001
        """
        remote_revision = "refs/heads/from-remote"
        default_revision = "refs/heads/from-default"

        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="myremote" fetch="https://example.com" revision="{remote_revision}" />\n'
            f'  <default revision="{default_revision}" remote="myremote" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        proj = _get_project(m, "platform/core")

        assert proj.revisionExpr == remote_revision, (
            f"expected revisionExpr={remote_revision!r} from remote (not {default_revision!r} from default), "
            f"got {proj.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: project with no revision and remote with no revision inherits
#              from default.revision
#
# When neither the <project> element nor the <remote> element carries a
# revision attribute, the project must inherit from the <default> element.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectInheritsFromDefaultRevision:
    """Verify that a project inherits default.revision when remote has no revision.

    AC-TEST-002, AC-FUNC-001
    """

    @pytest.mark.parametrize(
        "default_revision",
        [
            "refs/heads/main",
            "refs/heads/develop",
            "refs/tags/stable",
        ],
    )
    def test_project_inherits_default_revision_when_no_project_or_remote_revision(
        self,
        tmp_path: pathlib.Path,
        default_revision: str,
    ) -> None:
        """A project without revision inherits from <default> when remote has none.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://example.com" />\n'
            f'  <default revision="{default_revision}" remote="myremote" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        proj = _get_project(m, "platform/core")

        assert proj.revisionExpr == default_revision, (
            f"expected revisionExpr={default_revision!r} from default element, got {proj.revisionExpr!r}"
        )

    def test_explicit_project_revision_overrides_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit project revision is used, not the default revision.

        When a <project revision="..."> attribute is set, the project's own
        revision takes precedence over both remote.revision and default.revision.

        AC-TEST-002, AC-FUNC-001
        """
        project_revision = "refs/heads/project-specific"
        default_revision = "refs/heads/from-default"

        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://example.com" />\n'
            f'  <default revision="{default_revision}" remote="myremote" />\n'
            f'  <project name="platform/core" revision="{project_revision}" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        proj = _get_project(m, "platform/core")

        assert proj.revisionExpr == project_revision, (
            f"expected revisionExpr={project_revision!r} from project attribute, got {proj.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: no revision anywhere raises 'no revision for project'
#
# When no revision is available from the project, remote, or default element,
# ManifestParseError must be raised with a message containing "no revision for
# project".
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoRevisionRaisesError:
    """Verify that a missing revision at all levels raises ManifestParseError.

    AC-TEST-003, AC-FUNC-001
    """

    def test_no_revision_anywhere_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ManifestParseError is raised when no revision is present at any level.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://example.com" />\n'
            '  <default remote="myremote" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "no revision for project" in error_message, (
            f"expected 'no revision for project' in error message, got: {error_message!r}"
        )

    def test_no_revision_error_mentions_project_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message includes the project name.

        AC-TEST-003
        """
        project_name = "platform/mylib"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://example.com" />\n'
            '  <default remote="myremote" />\n'
            f'  <project name="{project_name}" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert project_name in error_message, (
            f"expected project name {project_name!r} in error message, got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "toolchain/gcc",
            "kernel/common",
            "device/generic",
        ],
    )
    def test_no_revision_error_for_multiple_project_names(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """The error message names the specific project that lacks a revision.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://example.com" />\n'
            '  <default remote="myremote" />\n'
            f'  <project name="{project_name}" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "no revision for project" in error_message, (
            f"expected 'no revision for project' in error, got: {error_message!r}"
        )
        assert project_name in error_message, f"expected {project_name!r} in error message, got: {error_message!r}"
