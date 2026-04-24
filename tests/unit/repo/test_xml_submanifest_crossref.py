"""Unit tests for <submanifest> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <submanifest> are validated
               (e.g. remote name resolution -- a <submanifest remote="...">
               attribute must reference a declared <remote> element; an
               undeclared remote name raises at Load() time; a submanifest
               path that conflicts with a project path raises ManifestParseError;
               a valid remote reference resolves without error)
  AC-TEST-002  Duplicate-element rules for <submanifest> surface clear errors
               (two <submanifest> elements with the same name but different
               attributes raise ManifestParseError naming the submanifest;
               two <submanifest> elements with the same name and identical
               attributes are accepted idempotently)
  AC-TEST-003  <submanifest> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <submanifest> child is
               processed; within a valid <manifest> root, an unknown sibling
               element is silently ignored without affecting <submanifest>)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <submanifest> at parse/load time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  exceptions, not stdout writes; valid parses produce no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The cross-element rules for <submanifest>:
- The <submanifest> remote attribute is resolved against the declared
  <remote> elements; an undeclared remote name raises at Load() time.
- Duplicate <submanifest> elements with the same name and the same
  attributes are idempotent (accepted silently).
- Duplicate <submanifest> elements with the same name but different
  attributes raise ManifestParseError. The error message names the
  submanifest.
- A project whose relpath starts with a submanifest relpath raises
  ManifestParseError (path conflict).
- <submanifest> is processed only when it appears inside a valid
  <manifest> root element. A file whose root is not <manifest> is
  rejected before any children are examined.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_*_crossref.py files
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.

    Returns:
        Absolute path to the .repo directory.
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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content to a manifest file and load it.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation for <submanifest>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <submanifest> are validated.

    The <submanifest> remote attribute is resolved against the set of declared
    <remote> elements during Load(). An undeclared remote name raises at that
    time. A valid remote reference resolves without error and the submanifest
    is registered in manifest.submanifests.

    A project path that starts with a submanifest relpath raises
    ManifestParseError with a message identifying the conflict.
    """

    def test_submanifest_with_declared_remote_resolves_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<submanifest remote="..."> referencing a declared <remote> parses without error.

        After parsing, the submanifest is registered in manifest.submanifests
        and its remote attribute matches the declared remote name.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" project="platform/manifest" path="sub" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-001: expected 'platform/sub' in manifest.submanifests when remote='origin' "
            "references a declared <remote> but not found"
        )
        sm = manifest.submanifests["platform/sub"]
        assert sm.remote == "origin", f"AC-TEST-001: expected submanifest.remote='origin' but got: {sm.remote!r}"

    def test_submanifest_with_undeclared_remote_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<submanifest remote="..."> naming an undeclared remote raises at Load() time.

        During Load(), ToSubmanifestSpec() resolves the remote name against
        manifest.remotes. When the name is not declared, an error is raised.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="no-such-remote" '
            'project="platform/manifest" path="sub" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises((ManifestParseError, KeyError)):
            m.Load()

    @pytest.mark.parametrize(
        "undeclared_remote",
        [
            "missing-remote",
            "phantom-origin",
            "does-not-exist",
        ],
    )
    def test_various_undeclared_submanifest_remotes_raise_at_load_time(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote: str,
    ) -> None:
        """Parameterized: each undeclared remote name in <submanifest> raises at Load() time.

        The error is raised during remote name resolution inside Load(), not
        deferred to later access of manifest.submanifests.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <submanifest name="platform/sub" remote="{undeclared_remote}" '
            f'project="platform/manifest" path="sub" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises((ManifestParseError, KeyError)):
            m.Load()

    def test_submanifest_without_remote_uses_default_remote_resolves_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> without a remote attribute uses the <default> remote.

        When no remote is given, ToSubmanifestSpec() falls back to
        self.parent.default.remote.name, which must be a declared remote.
        The manifest must parse without error in this case.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-001: expected 'platform/sub' in manifest.submanifests when using default remote but not found"
        )

    def test_submanifest_path_conflict_with_project_path_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project whose relpath starts with a <submanifest> relpath raises ManifestParseError.

        When a project path begins with the submanifest relpath, the parser
        raises ManifestParseError identifying the conflict. This is the
        cross-element constraint between <submanifest> and <project>.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            '  <project name="platform/core" path="sub/core" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for "
            "project path conflicting with submanifest path but got an empty string"
        )
        assert "sub" in error_message, (
            f"AC-TEST-001: expected conflict path 'sub' in error message but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "submanifest_relpath,project_path",
        [
            ("checkout", "checkout/module"),
            ("vendor", "vendor/lib"),
        ],
    )
    def test_various_submanifest_project_path_conflicts_raise(
        self,
        tmp_path: pathlib.Path,
        submanifest_relpath: str,
        project_path: str,
    ) -> None:
        """Parameterized: various project paths that conflict with a submanifest path raise.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <submanifest name="platform/sub" path="{submanifest_relpath}" />\n'
            f'  <project name="platform/proj" path="{project_path}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected a non-empty ManifestParseError for project "
            f"path '{project_path}' conflicting with submanifest path '{submanifest_relpath}' "
            "but got an empty string"
        )

    def test_submanifest_and_project_with_non_overlapping_paths_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project and submanifest with non-overlapping paths parse without error.

        This positive control confirms that the path conflict check is only
        triggered when paths overlap.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub-checkout" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-001: expected 'platform/sub' in manifest.submanifests when "
            "project path does not conflict with submanifest path but not found"
        )
        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects but got: {project_names!r}"
        )

    def test_multiple_submanifests_each_with_declared_remotes_resolve(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <submanifest> elements each referencing declared remotes all resolve.

        A manifest with two remotes and two submanifests each referencing a
        different remote must parse without error, and both submanifests must
        appear in manifest.submanifests.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" project="p/manifest" path="sub1" />\n'
            '  <submanifest name="vendor/lib" remote="upstream" project="v/manifest" path="sub2" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-001: expected 'platform/sub' in manifest.submanifests but not found"
        )
        assert "vendor/lib" in manifest.submanifests, (
            "AC-TEST-001: expected 'vendor/lib' in manifest.submanifests but not found"
        )
        assert manifest.submanifests["platform/sub"].remote == "origin", (
            f"AC-TEST-001: expected platform/sub remote='origin' but got: "
            f"{manifest.submanifests['platform/sub'].remote!r}"
        )
        assert manifest.submanifests["vendor/lib"].remote == "upstream", (
            f"AC-TEST-001: expected vendor/lib remote='upstream' but got: "
            f"{manifest.submanifests['vendor/lib'].remote!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <submanifest> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <submanifest> surface clear errors.

    The parser enforces:
    - Two <submanifest> elements with the same name and identical attributes are
      idempotent (accepted silently); only one entry appears in submanifests.
    - Two <submanifest> elements with the same name but different attributes raise
      ManifestParseError. The error message must name the submanifest.
    - The error must be raised at parse time (during Load()), not deferred.
    """

    def test_duplicate_submanifest_identical_attributes_is_idempotent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <submanifest> elements with the same name and identical attributes are accepted.

        After parsing, the manifest contains exactly one submanifest entry for
        that name. The duplicate is silently ignored.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-002: expected 'platform/sub' in manifest.submanifests after idempotent duplicate but not found"
        )
        assert len(manifest.submanifests) == 1, (
            f"AC-TEST-002: expected exactly 1 submanifest after idempotent duplicate "
            f"but got: {len(manifest.submanifests)}"
        )

    def test_duplicate_submanifest_different_path_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <submanifest> elements with the same name but different path attributes raise.

        The error message must contain the submanifest name so the developer
        knows which submanifest is conflicting.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub1" />\n'
            '  <submanifest name="platform/sub" path="sub2" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for "
            "conflicting duplicate submanifest but got an empty string"
        )
        assert "platform/sub" in error_message, (
            f"AC-TEST-002: expected 'platform/sub' in error message for "
            f"conflicting duplicate submanifest but got: {error_message!r}"
        )

    def test_duplicate_submanifest_different_revision_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <submanifest> elements with same name but different revision raise.

        Any attribute difference (not just path) triggers the conflict.
        The error message must name the submanifest.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" revision="main" />\n'
            '  <submanifest name="platform/sub" path="sub" revision="stable" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for "
            "duplicate submanifest with different revision but got an empty string"
        )
        assert "platform/sub" in error_message, (
            f"AC-TEST-002: expected 'platform/sub' in error message but got: {error_message!r}"
        )

    def test_duplicate_submanifest_error_message_is_non_empty(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError raised for duplicate <submanifest> has a non-empty message.

        An empty error message is not actionable; the message must identify
        both the element and the name.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="vendor/sdk" path="sdk1" />\n'
            '  <submanifest name="vendor/sdk" path="sdk2" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected a non-empty error message for "
            "duplicate <submanifest> elements but got an empty string"
        )

    def test_single_submanifest_does_not_trigger_duplicate_rule(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <submanifest> element does not trigger the duplicate rule.

        This positive control confirms the duplicate check only fires when a
        second element with the same name appears.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected single <submanifest> element to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-002: expected 'platform/sub' in manifest.submanifests "
            "after single <submanifest> parse but not found"
        )

    @pytest.mark.parametrize(
        "submanifest_name",
        [
            "platform/sub",
            "vendor/sdk",
            "tools/build-manifest",
        ],
    )
    def test_duplicate_submanifest_various_names_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        submanifest_name: str,
    ) -> None:
        """Parameterized: duplicate <submanifest> raises for any name when attributes differ.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <submanifest name="{submanifest_name}" path="sub-a" />\n'
            f'  <submanifest name="{submanifest_name}" path="sub-b" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-002: expected non-empty ManifestParseError for "
            f"duplicate submanifest='{submanifest_name}' but got empty string"
        )
        assert submanifest_name in error_message, (
            f"AC-TEST-002: expected submanifest name '{submanifest_name}' in error message but got: {error_message!r}"
        )

    def test_different_submanifest_names_do_not_trigger_duplicate_rule(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <submanifest> elements with different names do not trigger the duplicate rule.

        Each submanifest is independent; the duplicate check is keyed on name.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub1" />\n'
            '  <submanifest name="vendor/sdk" path="sub2" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two <submanifest> elements with different names to "
                f"parse without ManifestParseError but got: {exc!r}"
            )

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-002: expected 'platform/sub' in manifest.submanifests but not found"
        )
        assert "vendor/sdk" in manifest.submanifests, (
            "AC-TEST-002: expected 'vendor/sdk' in manifest.submanifests but not found"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <submanifest> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestUnexpectedParent:
    """AC-TEST-003: <submanifest> in an unexpected parent raises or is ignored per spec.

    The parser processes <submanifest> only when it appears as a child of a
    valid <manifest> root element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <submanifest>) are
      examined. The error message mentions 'manifest'.
    - An unknown element sibling to <submanifest> inside a valid <manifest>
      root is silently ignored; the <submanifest> element is still processed.
    - A valid <manifest> root with a <submanifest> and unknown siblings parses
      correctly and registers the submanifest in manifest.submanifests.
    """

    def test_submanifest_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <submanifest> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</repository>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected 'manifest' in error message for non-manifest root but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "non_manifest_root",
        [
            "repository",
            "config",
            "root",
            "repo",
        ],
    )
    def test_submanifest_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <submanifest> under any non-manifest root causes ManifestParseError.

        The error must be non-empty because the parser rejects the file
        at root-element validation before any <submanifest> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <submanifest name="platform/sub" path="sub" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <submanifest> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_submanifest(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <submanifest> inside <manifest> is silently ignored.

        Unknown elements inside a valid <manifest> root are skipped by the
        parser loop. The <submanifest> element must still be processed and must
        appear in manifest.submanifests after loading.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <unknown-element attr="ignored-value" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-003: expected 'platform/sub' in manifest.submanifests when "
            "unknown sibling element is present alongside <submanifest> but not found"
        )

    def test_submanifest_valid_in_manifest_root_registers_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <submanifest> inside a valid <manifest> root registers in manifest.submanifests.

        This positive test confirms that when the parent IS <manifest>,
        everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            '  <submanifest name="infra/tools" path="tools" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "infra/tools" in manifest.submanifests, (
            "AC-TEST-003: expected 'infra/tools' in manifest.submanifests for valid "
            "<submanifest> inside proper <manifest> parent but not found"
        )
        sm = manifest.submanifests["infra/tools"]
        assert sm.name == "infra/tools", f"AC-TEST-003: expected submanifest.name='infra/tools' but got: {sm.name!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces all cross-element and uniqueness rules at load time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at load time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.submanifests. Tests confirm that errors fire during Load()
    and that the manifest state is consistent after a successful parse.
    """

    def test_undeclared_submanifest_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote reference in <submanifest> raises during Load().

        The error must be raised inside XmlManifest.Load() before any caller
        accesses manifest.submanifests.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="absent-remote" '
            'project="platform/manifest" path="sub" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises((ManifestParseError, KeyError)):
            m.Load()

    def test_duplicate_submanifest_with_different_attrs_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate <submanifest> elements with different attributes raise during Load().

        The error must be raised by XmlManifest.Load(), not deferred.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub-first" />\n'
            '  <submanifest name="platform/sub" path="sub-second" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_project_path_conflict_with_submanifest_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project path that conflicts with a submanifest relpath raises during Load().

        The conflict check between submanifest relpaths and project relpaths
        fires at parse/load time, not deferred to first access.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            '  <project name="platform/core" path="sub/nested" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_submanifest_cross_references_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid <submanifest> cross-element references are fully resolved by Load().

        After Load(), manifest.submanifests is populated with all declared
        submanifests. No deferred resolution occurs.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <submanifest name="platform/child" path="child" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "platform/child" in manifest.submanifests, (
            "AC-FUNC-001: expected 'platform/child' in manifest.submanifests immediately after Load() but not found"
        )
        assert len(manifest.projects) == 1, (
            f"AC-FUNC-001: expected 1 project after Load() but got: {len(manifest.projects)}"
        )
        assert "origin" in manifest.remotes, (
            "AC-FUNC-001: expected 'origin' in manifest.remotes immediately after Load() but not found"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_duplicate_submanifest_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <submanifest> with conflicting attributes raises ManifestParseError, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub-first" />\n'
            '  <submanifest name="platform/sub" path="sub-second" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate submanifest error but got: {captured.out!r}"
        )

    def test_path_conflict_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A project path conflicting with a submanifest path raises an exception, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            '  <project name="platform/core" path="sub/core" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for path conflict error but got: {captured.out!r}"

    def test_non_manifest_root_with_submanifest_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <submanifest> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</config>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for non-manifest root error but got: {captured.out!r}"
        )

    def test_valid_submanifest_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid <submanifest> cross-element references does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" project="p/manifest" path="sub1" />\n'
            '  <submanifest name="vendor/lib" remote="upstream" project="v/manifest" path="sub2" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except (ManifestParseError, KeyError) as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <submanifest> cross-reference to parse without error but got: {exc!r}"
            )

        assert "platform/sub" in manifest.submanifests, (
            "AC-CHANNEL-001: expected 'platform/sub' in manifest.submanifests after valid parse but not found"
        )
        assert "vendor/lib" in manifest.submanifests, (
            "AC-CHANNEL-001: expected 'vendor/lib' in manifest.submanifests after valid parse but not found"
        )

    def test_valid_submanifest_parse_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A valid <submanifest> parse produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid submanifest crossref parse but got: {captured.out!r}"
        )
