"""Unit tests for <remote> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <remote> are validated
               (e.g. remote name resolution -- a <default remote="...">
               attribute must reference a declared <remote> element; an
               undeclared remote name raises ManifestParseError; when
               a <project> references an undeclared remote name the parser
               raises; the alias attribute controls the git remote name
               returned by ToRemoteSpec)
  AC-TEST-002  Duplicate-element rules for <remote> surface clear errors
               (two <remote> elements with the same name but different
               attributes raise ManifestParseError naming the remote;
               two <remote> elements with the same name and identical
               attributes are accepted idempotently)
  AC-TEST-003  <remote> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <remote> child is
               processed; within a valid <manifest> root an unknown sibling
               element is silently ignored without affecting <remote>)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <remote> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses
                  produce no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The cross-element rules for <remote>:
- The <remote> name attribute is referenced by <default remote="...">,
  <project remote="...">, and other elements; an undeclared name raises
  ManifestParseError.
- Duplicate <remote> elements with the same name and the same attributes
  are idempotent (accepted silently).
- Duplicate <remote> elements with the same name but different attributes
  raise ManifestParseError. The error message contains the remote name.
- The alias attribute, when present, overrides the git remote name returned
  by ToRemoteSpec; the original name is still used as the key in
  manifest.remotes.
- <remote> is processed only when it appears as a child of a valid
  <manifest> root element. A file whose root is not <manifest> is rejected
  before any children are examined.
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
# AC-TEST-001: Cross-element reference validation for <remote>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <remote> are validated.

    The <remote> name attribute is referenced by <default remote="...">,
    <project remote="...">, and similar elements. The parser must raise
    ManifestParseError when any such reference names a remote that has not
    been declared by a <remote> element in the manifest.

    Additionally, the alias attribute is a cross-element concern: it controls
    the git remote name that ToRemoteSpec returns, which is the name used in
    per-project .git/config entries.
    """

    def test_default_element_references_declared_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<default remote="..."> referencing a declared <remote> parses without error.

        After parsing, manifest.remotes contains the remote declared by
        the <remote> element, and the default remote resolves to it.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            "AC-TEST-001: expected 'origin' in manifest.remotes after valid cross-reference but not found"
        )
        assert manifest.remotes["origin"].name == "origin", (
            f"AC-TEST-001: expected remote.name='origin' but got: {manifest.remotes['origin'].name!r}"
        )

    def test_default_element_referencing_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<default remote="..."> naming an undeclared remote raises ManifestParseError.

        The error message must identify the undeclared remote name.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="no-such-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for undeclared default remote but got an empty string"
        )
        assert "no-such-remote" in error_message or "not defined" in error_message, (
            f"AC-TEST-001: expected error message to name the undeclared remote or contain "
            f"'not defined' but got: {error_message!r}"
        )

    def test_project_element_referencing_declared_remote_resolves(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<project remote="..."> naming a declared <remote> resolves the project remote.

        After parsing, the project's remote attribute is set and its name
        matches the declared remote.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert len(manifest.projects) == 1, f"AC-TEST-001: expected 1 project but got: {len(manifest.projects)}"
        project = manifest.projects[0]
        assert project.remote is not None, (
            "AC-TEST-001: expected project.remote to be set when remote='upstream' references a declared remote "
            "but got None"
        )
        assert project.remote.name == "upstream", (
            f"AC-TEST-001: expected project.remote.name='upstream' but got: {project.remote.name!r}"
        )
        assert project.remote.fetchUrl == "https://upstream.example.com", (
            f"AC-TEST-001: expected project.remote.fetchUrl='https://upstream.example.com' but got: "
            f"{project.remote.fetchUrl!r}"
        )

    def test_project_element_referencing_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<project remote="..."> naming an undeclared remote raises ManifestParseError.

        The error message must name the undeclared remote so the developer
        knows what to fix.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="ghost-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for undeclared project remote but got an empty string"
        )
        assert "ghost-remote" in error_message or "not defined" in error_message, (
            f"AC-TEST-001: expected error to name 'ghost-remote' or contain 'not defined' but got: {error_message!r}"
        )

    def test_alias_attribute_controls_git_remote_name_in_to_remote_spec(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The alias attribute overrides the git remote name returned by ToRemoteSpec.

        When alias is set, ToRemoteSpec.name returns the alias value while
        the original name is still used as the key in manifest.remotes.
        This is the cross-element relationship: other elements reference the
        remote by its name attribute, but the on-disk git config uses the alias.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" alias="upstream" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            "AC-TEST-001: expected 'origin' (not 'upstream') to be the key in manifest.remotes "
            "when alias='upstream' is set but 'origin' was not found"
        )
        remote = manifest.remotes["origin"]
        spec = remote.ToRemoteSpec("some/project")
        assert spec.name == "upstream", (
            f"AC-TEST-001: expected ToRemoteSpec.name='upstream' (the alias) but got: {spec.name!r}"
        )
        assert spec.orig_name == "origin", (
            f"AC-TEST-001: expected ToRemoteSpec.orig_name='origin' (the original name) but got: {spec.orig_name!r}"
        )

    def test_alias_absent_uses_name_in_to_remote_spec(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When alias is absent, ToRemoteSpec.name equals the remote name attribute.

        This is the baseline cross-element behavior: the git remote name
        matches the manifest remote name when no alias is declared.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        remote = manifest.remotes["origin"]
        spec = remote.ToRemoteSpec("some/project")
        assert spec.name == "origin", (
            f"AC-TEST-001: expected ToRemoteSpec.name='origin' when alias absent but got: {spec.name!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote_name",
        [
            "missing-remote",
            "does-not-exist",
            "phantom-remote",
        ],
    )
    def test_various_undeclared_default_remotes_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote_name: str,
    ) -> None:
        """Parameterized: each undeclared remote name in <default> raises ManifestParseError.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="main" remote="{undeclared_remote_name}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected non-empty ManifestParseError for undeclared "
            f"default remote='{undeclared_remote_name}' but got empty string"
        )

    def test_multiple_remotes_all_resolve_cross_element_references(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple declared remotes each resolve correctly from cross-element references.

        A manifest with two remotes and two projects each referencing a
        different remote must parse without error, and each project's remote
        must match the declared remote.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="origin" />\n'
            '  <project name="vendor/lib" path="lib" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, "AC-TEST-001: expected 'platform/core' in manifest.projects but not found"
        assert "vendor/lib" in projects, "AC-TEST-001: expected 'vendor/lib' in manifest.projects but not found"
        assert projects["platform/core"].remote.name == "origin", (
            f"AC-TEST-001: expected 'platform/core' remote='origin' but got: {projects['platform/core'].remote.name!r}"
        )
        assert projects["vendor/lib"].remote.name == "upstream", (
            f"AC-TEST-001: expected 'vendor/lib' remote='upstream' but got: {projects['vendor/lib'].remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <remote> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <remote> surface clear errors.

    The parser enforces:
    - Two <remote> elements with the same name and identical attributes are
      idempotent (accepted silently).
    - Two <remote> elements with the same name but different attributes raise
      ManifestParseError. The error message must contain the remote name.
    - The error must be raised at parse time (during Load()), not deferred.
    """

    def test_duplicate_remote_identical_attributes_is_idempotent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with the same name and identical attributes are accepted.

        After parsing, the manifest contains exactly one remote entry for that
        name, and its attributes match the declared values.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            "AC-TEST-002: expected 'origin' in manifest.remotes after idempotent duplicate but not found"
        )
        assert manifest.remotes["origin"].fetchUrl == "https://example.com", (
            f"AC-TEST-002: expected fetchUrl='https://example.com' after idempotent duplicate but got: "
            f"{manifest.remotes['origin'].fetchUrl!r}"
        )

    def test_duplicate_remote_different_fetch_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with the same name but different fetch URLs raise ManifestParseError.

        The error message must contain the remote name so the developer can
        identify which remote is conflicting.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for conflicting remote but got an empty string"
        )
        assert "origin" in error_message, (
            f"AC-TEST-002: expected 'origin' in error message for conflicting remote but got: {error_message!r}"
        )

    def test_duplicate_remote_error_message_is_non_empty(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError raised for duplicate <remote> elements has a non-empty message.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://first.example.com" />\n'
            '  <remote name="upstream" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected a non-empty error message for duplicate <remote> elements but got an empty string"
        )

    def test_duplicate_remote_different_alias_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with same name but different alias attributes raise ManifestParseError.

        Any attribute difference (not just fetch URL) triggers the conflict.
        The error message must contain the remote name.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" alias="first-alias" />\n'
            '  <remote name="origin" fetch="https://example.com" alias="second-alias" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for remote with different "
            "alias values but got an empty string"
        )
        assert "origin" in error_message, (
            f"AC-TEST-002: expected 'origin' in error message for conflicting alias but got: {error_message!r}"
        )

    def test_single_remote_does_not_trigger_duplicate_rule(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <remote> element does not trigger the duplicate rule.

        This positive control confirms the duplicate rule only fires when a
        second element with the same name appears.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected single <remote> element to parse without ManifestParseError but got: {exc!r}"
            )

        assert "origin" in manifest.remotes, (
            "AC-TEST-002: expected 'origin' in manifest.remotes after single <remote> parse but not found"
        )

    @pytest.mark.parametrize(
        "remote_name",
        [
            "origin",
            "upstream",
            "caylent-remote",
        ],
    )
    def test_duplicate_remote_various_names_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
    ) -> None:
        """Parameterized: duplicate <remote> raises for any remote name when attributes differ.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="{remote_name}" fetch="https://first.example.com" />\n'
            f'  <remote name="{remote_name}" fetch="https://second.example.com" />\n'
            f'  <default revision="main" remote="{remote_name}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-002: expected non-empty ManifestParseError for duplicate "
            f"remote='{remote_name}' but got empty string"
        )
        assert remote_name in error_message, (
            f"AC-TEST-002: expected remote name '{remote_name}' in error message but got: {error_message!r}"
        )

    def test_different_remote_names_do_not_trigger_duplicate_rule(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with different names do not trigger the duplicate rule.

        Each remote must be independent; the duplicate check is keyed on name.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two <remote> elements with different names to parse without "
                f"ManifestParseError but got: {exc!r}"
            )

        assert "origin" in manifest.remotes, "AC-TEST-002: expected 'origin' in manifest.remotes but not found"
        assert "upstream" in manifest.remotes, "AC-TEST-002: expected 'upstream' in manifest.remotes but not found"


# ---------------------------------------------------------------------------
# AC-TEST-003: <remote> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteUnexpectedParent:
    """AC-TEST-003: <remote> in an unexpected parent raises or is ignored per spec.

    The parser processes <remote> only when it appears as a child of a valid
    <manifest> root element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <remote>) are examined.
      The error message mentions 'manifest'.
    - An unknown element sibling to <remote> inside a valid <manifest> root
      is silently ignored; the <remote> element is still processed.
    - A valid <manifest> root with a <remote> and unknown siblings parses
      correctly and registers the remote in manifest.remotes.
    """

    def test_remote_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <remote> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
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
    def test_remote_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <remote> under any non-manifest root causes ManifestParseError.

        The error must be non-empty because the parser rejects the file
        at root-element validation before any <remote> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <remote> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <remote> inside <manifest> is silently ignored.

        Unknown elements inside a valid <manifest> root are skipped by the
        parser loop. The <remote> element must still be processed and must
        appear in manifest.remotes after loading.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <unknown-element attr="ignored-value" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert "origin" in manifest.remotes, (
            "AC-TEST-003: expected 'origin' in manifest.remotes when unknown sibling "
            "element is present alongside <remote> but not found"
        )
        assert manifest.remotes["origin"].fetchUrl == "https://example.com", (
            f"AC-TEST-003: expected remote.fetchUrl='https://example.com' but got: "
            f"{manifest.remotes['origin'].fetchUrl!r}"
        )

    def test_remote_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> inside a valid <manifest> root registers in manifest.remotes.

        This positive test confirms that when the parent IS <manifest>,
        everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "infra" in manifest.remotes, (
            "AC-TEST-003: expected 'infra' in manifest.remotes for valid <remote> inside "
            "proper <manifest> parent but not found"
        )
        assert manifest.remotes["infra"].fetchUrl == "https://infra.example.com", (
            f"AC-TEST-003: expected remote.fetchUrl='https://infra.example.com' but got: "
            f"{manifest.remotes['infra'].fetchUrl!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.remotes or manifest.projects. Tests confirm that errors fire
    during Load() and that the manifest state is consistent after a successful
    parse.
    """

    def test_undeclared_default_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote reference in <default> raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before
        any caller accesses manifest.remotes.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="absent-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_remote_with_different_attrs_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate <remote> elements with different attributes raise during Load().

        The error must be raised by XmlManifest.Load(), not deferred.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_undeclared_project_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote reference in <project> raises during Load().

        The cross-element validation for project remotes must fire during
        Load(), not lazily when the project is later accessed.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="phantom-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_remote_cross_references_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid <remote> cross-element references are fully resolved by the time Load() returns.

        After Load(), manifest.remotes is populated with all declared remotes,
        and projects that reference those remotes have their remote attribute
        set. No deferred resolution occurs.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            "AC-FUNC-001: expected 'origin' in manifest.remotes immediately after Load() but not found"
        )
        assert len(manifest.projects) == 1, (
            f"AC-FUNC-001: expected 1 project after Load() but got: {len(manifest.projects)}"
        )
        project = manifest.projects[0]
        assert project.remote is not None, "AC-FUNC-001: expected project.remote to be set after Load() but got None"
        assert project.remote.name == "origin", (
            f"AC-FUNC-001: expected project.remote.name='origin' after Load() but got: {project.remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_undeclared_default_remote_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undeclared remote reference in <default> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="phantom-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undeclared default remote error but got: {captured.out!r}"
        )

    def test_duplicate_remote_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <remote> with conflicting attributes raises ManifestParseError, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate remote error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_remote_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <remote> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
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

    def test_valid_remote_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid <remote> cross-element references does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="upstream" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <remote> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert "origin" in manifest.remotes, (
            "AC-CHANNEL-001: expected 'origin' in manifest.remotes after valid parse but not found"
        )
        assert "upstream" in manifest.remotes, (
            "AC-CHANNEL-001: expected 'upstream' in manifest.remotes after valid parse but not found"
        )
