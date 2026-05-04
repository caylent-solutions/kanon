"""Unit tests for <default> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <default> are validated
               (e.g. remote name resolution -- a <default remote="...">
               attribute must reference a declared <remote> element; an
               undeclared remote name raises ManifestParseError naming the
               remote; a <project> that omits remote inherits the default
               remote resolved through <default>)
  AC-TEST-002  Duplicate-element rules for <default> surface clear errors
               (two <default> elements with the same attribute values are
               accepted; two <default> elements with conflicting attribute
               values raise ManifestParseError; two empty <default /> elements
               are accepted idempotently)
  AC-TEST-003  <default> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <default> child is
               processed; unknown element siblings to <default> inside a
               valid <manifest> root are silently ignored and <default> is
               still processed; a valid manifest root correctly applies
               <default> to projects)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <default> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses
                  produce no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

Cross-element rules for <default>:
- The remote attribute on <default> must name a remote declared by a
  <remote> element. An undeclared name raises ManifestParseError naming
  the missing remote.
- A <project> that omits its own remote attribute inherits the remote
  resolved through the <default> element. After Load(), the project's
  remote matches the declared <remote> referenced by <default>.
- Duplicate <default> elements with identical attributes are accepted
  idempotently (the second is a no-op).
- Duplicate <default> elements with differing attributes raise
  ManifestParseError at parse time.
- Two empty <default /> elements are treated as identical and accepted.
- <default> is processed only when its parent is a valid <manifest>
  root. A file whose root element is not <manifest> is rejected before
  any children are examined.
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
# AC-TEST-001: Cross-element reference validation for <default>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <default> are validated.

    The remote attribute on <default> must reference a remote declared by a
    <remote> element. When the named remote is undeclared, ManifestParseError
    is raised and its message must identify the missing name.

    Additionally, a <project> that carries no remote attribute of its own
    inherits the remote resolved through <default>. After Load(), the project
    remote must match the <remote> element that <default> references.
    """

    def test_default_referencing_declared_remote_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<default remote="..."> referencing a declared <remote> parses without error.

        After parsing, manifest.default.remote is set to the declared remote
        object and its name matches the remote element's name attribute.

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

        assert manifest.default.remote is not None, (
            "AC-TEST-001: expected default.remote to be set when remote='origin' "
            "references a declared <remote> but got None"
        )
        assert manifest.default.remote.name == "origin", (
            f"AC-TEST-001: expected default.remote.name='origin' but got: {manifest.default.remote.name!r}"
        )

    def test_default_referencing_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<default remote="..."> naming an undeclared remote raises ManifestParseError.

        The error message must identify the undeclared remote name so the
        developer knows which name to declare or correct.

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
        assert "no-such-remote" in error_message, (
            f"AC-TEST-001: expected 'no-such-remote' in error message but got: {error_message!r}"
        )

    def test_default_with_no_remote_leaves_default_remote_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<default> without a remote attribute leaves manifest.default.remote as None.

        When no remote attribute is given on <default>, the parsed default
        object must have remote=None. This is the documented absence case.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.remote is None, (
            f"AC-TEST-001: expected default.remote=None when remote absent but got: {manifest.default.remote!r}"
        )

    def test_project_inherits_default_remote_when_no_project_remote_set(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> without an explicit remote inherits the remote from <default>.

        After Load(), the project's remote attribute must equal the remote
        declared in <remote> and referenced by <default remote="...">.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert len(manifest.projects) == 1, f"AC-TEST-001: expected 1 project but got: {len(manifest.projects)}"
        project = manifest.projects[0]
        assert project.remote is not None, "AC-TEST-001: expected project.remote to be set via <default> but got None"
        assert project.remote.name == "origin", (
            f"AC-TEST-001: expected project.remote.name='origin' (from default) but got: {project.remote.name!r}"
        )

    def test_project_explicit_remote_overrides_default_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with its own remote attribute uses that remote, not the default.

        The <default> remote is a fallback; an explicit project remote takes
        precedence. After Load(), the project's remote must be the explicitly
        declared one.

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
        assert project.remote is not None, "AC-TEST-001: expected project.remote to be set to 'upstream' but got None"
        assert project.remote.name == "upstream", (
            f"AC-TEST-001: expected project.remote.name='upstream' (explicit override) but got: {project.remote.name!r}"
        )

    def test_default_remote_resolved_before_project_uses_it(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The default remote is resolved from <remote> declarations before projects are parsed.

        After Load(), both manifest.default.remote and the inheriting project's
        remote point to the same _XmlRemote object.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            '  <project name="core/lib" path="lib" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.remote is not None, (
            "AC-TEST-001: expected manifest.default.remote to be set but got None"
        )
        assert manifest.default.remote.name == "infra", (
            f"AC-TEST-001: expected default.remote.name='infra' but got: {manifest.default.remote.name!r}"
        )
        assert len(manifest.projects) == 1, f"AC-TEST-001: expected 1 project but got: {len(manifest.projects)}"
        project = manifest.projects[0]
        assert project.remote is not None, "AC-TEST-001: expected project.remote set via <default> but got None"
        assert project.remote.name == "infra", (
            f"AC-TEST-001: expected project.remote.name='infra' (from default) but got: {project.remote.name!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote_name",
        [
            "missing-remote",
            "phantom",
            "does-not-exist",
        ],
    )
    def test_various_undeclared_default_remote_names_raise(
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

    def test_project_with_no_remote_and_no_default_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with no remote and a <default> with no remote raises ManifestParseError.

        The parser requires every project to resolve a remote, either from the
        project itself or from <default>. When neither provides one, the parser
        raises ManifestParseError naming the project.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError when project has no "
            "remote and <default> has no remote but got an empty string"
        )
        assert "platform/core" in error_message or "remote" in error_message.lower(), (
            f"AC-TEST-001: expected error message to reference the project or 'remote' "
            f"when neither project nor default specifies a remote but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <default> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <default> surface clear errors.

    The parser enforces:
    - Two <default> elements with identical attributes are accepted (idempotent).
    - Two <default> elements with differing attributes raise ManifestParseError.
    - Two empty <default /> elements are accepted (both are empty, so identical).
    - The error must be raised at parse time (during Load()), not deferred.
    """

    def test_duplicate_default_with_same_revision_is_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <default> elements with identical revision are accepted idempotently.

        When both <default> elements carry the same attribute values, the
        second is a no-op and no error is raised.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="main" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two identical <default> elements to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert manifest.default.revisionExpr == "main", (
            f"AC-TEST-002: expected default.revisionExpr='main' after idempotent "
            f"duplicate but got: {manifest.default.revisionExpr!r}"
        )

    def test_duplicate_empty_default_elements_are_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two empty <default /> elements are accepted (both empty means no conflict).

        An empty <default /> carries no attributes. Two empty defaults are
        treated as identical and must not raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "  <default />\n"
            "  <default />\n"
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two empty <default /> elements to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert manifest.default is not None, (
            "AC-TEST-002: expected manifest.default to be set after two empty <default /> elements"
        )

    def test_duplicate_default_with_different_revision_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <default> elements with different revision attributes raise ManifestParseError.

        The first <default> wins; the second with a different value must be
        rejected at parse time.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="stable" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestParseError for duplicate "
            "<default> with different revision but got an empty string"
        )

    def test_duplicate_default_with_different_remote_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <default> elements with different remote attributes raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default remote="origin" />\n'
            '  <default remote="upstream" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestParseError for duplicate "
            "<default> with different remote but got an empty string"
        )

    def test_duplicate_default_with_different_sync_j_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <default> elements with different sync-j attributes raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default sync-j="4" />\n'
            '  <default sync-j="8" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestParseError for duplicate "
            "<default> with different sync-j but got an empty string"
        )

    def test_single_default_does_not_trigger_duplicate_rule(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <default> element does not trigger the duplicate rule.

        This positive control confirms the duplicate check only fires when a
        second conflicting element appears.

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
                f"AC-TEST-002: expected single <default> element to parse without ManifestParseError but got: {exc!r}"
            )

        assert manifest.default.revisionExpr == "main", (
            f"AC-TEST-002: expected default.revisionExpr='main' for single <default> "
            f"but got: {manifest.default.revisionExpr!r}"
        )

    @pytest.mark.parametrize(
        "first_revision,second_revision",
        [
            ("main", "stable"),
            ("refs/heads/main", "refs/heads/develop"),
            ("v1.0", "v2.0"),
        ],
    )
    def test_duplicate_default_various_conflicting_revisions_raise(
        self,
        tmp_path: pathlib.Path,
        first_revision: str,
        second_revision: str,
    ) -> None:
        """Parameterized: various conflicting revision values in duplicate <default> raise.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="{first_revision}" />\n'
            f'  <default revision="{second_revision}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            f"AC-TEST-002: expected non-empty ManifestParseError for conflicting "
            f"revisions '{first_revision}' vs '{second_revision}' but got empty string"
        )

    def test_duplicate_default_error_raised_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate conflicting <default> elements raise ManifestParseError during Load().

        The error must not be deferred; it must fire when m.Load() is called.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="develop" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()


# ---------------------------------------------------------------------------
# AC-TEST-003: <default> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultUnexpectedParent:
    """AC-TEST-003: <default> in an unexpected parent raises or is ignored per spec.

    The parser processes <default> only when it appears as a child of a valid
    <manifest> root element:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <default>) are examined.
      The error message mentions 'manifest'.
    - An unknown element sibling to <default> inside a valid <manifest> root
      is silently ignored; the <default> element is still processed.
    - A valid <manifest> root containing <default> applies the defaults
      correctly to projects.
    """

    def test_default_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <default> child is never reached.

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
    def test_default_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <default> under any non-manifest root causes ManifestParseError.

        The error must be non-empty because the parser rejects the file
        at root-element validation before any <default> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <default> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <default> inside <manifest> is silently ignored.

        Unknown elements inside a valid <manifest> root are skipped by the
        parser loop. The <default> element must still be processed and must
        apply its values to the parsed manifest.default object.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <unknown-element attr="ignored-value" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently "
                f"ignored but got ManifestParseError: {exc!r}"
            )

        assert manifest.default is not None, (
            "AC-TEST-003: expected manifest.default to be set when unknown sibling "
            "element is present alongside <default> but got None"
        )
        assert manifest.default.revisionExpr == "refs/heads/main", (
            f"AC-TEST-003: expected default.revisionExpr='refs/heads/main' after "
            f"parse with unknown sibling but got: {manifest.default.revisionExpr!r}"
        )
        assert manifest.default.remote is not None, (
            "AC-TEST-003: expected default.remote to be set when unknown sibling element is present but got None"
        )
        assert manifest.default.remote.name == "origin", (
            f"AC-TEST-003: expected default.remote.name='origin' but got: {manifest.default.remote.name!r}"
        )

    def test_default_valid_in_manifest_root_applies_to_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default> inside a valid <manifest> root applies its values to projects.

        This positive test confirms that when the parent IS <manifest>,
        the <default> element is fully processed and its remote and revision
        are inherited by projects that do not declare their own.

        AC-TEST-003, AC-FUNC-001
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

        assert manifest.default.revisionExpr == "refs/heads/main", (
            f"AC-TEST-003: expected default.revisionExpr='refs/heads/main' in valid "
            f"manifest but got: {manifest.default.revisionExpr!r}"
        )
        assert len(manifest.projects) == 1, f"AC-TEST-003: expected 1 project but got: {len(manifest.projects)}"
        project = manifest.projects[0]
        assert project.remote is not None, (
            "AC-TEST-003: expected project.remote set via <default> in valid manifest but got None"
        )
        assert project.remote.name == "origin", (
            f"AC-TEST-003: expected project.remote.name='origin' (from default) but got: {project.remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.default or manifest.projects. Tests confirm that errors fire
    during Load() and that the manifest state is consistent after a successful
    parse.
    """

    def test_undeclared_default_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote reference in <default> raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before
        any caller accesses manifest.default.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="absent-remote" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_default_cross_references_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid <default> cross-element references are fully resolved by Load().

        After Load(), manifest.default.remote is populated with the declared
        remote. Projects that reference the default have their remote set.
        No deferred resolution occurs.

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

        assert manifest.default.remote is not None, (
            "AC-FUNC-001: expected manifest.default.remote set after Load() but got None"
        )
        assert manifest.default.remote.name == "origin", (
            f"AC-FUNC-001: expected default.remote.name='origin' after Load() but got: {manifest.default.remote.name!r}"
        )
        assert len(manifest.projects) == 1, (
            f"AC-FUNC-001: expected 1 project after Load() but got: {len(manifest.projects)}"
        )
        project = manifest.projects[0]
        assert project.remote is not None, (
            "AC-FUNC-001: expected project.remote set via default after Load() but got None"
        )
        assert project.remote.name == "origin", (
            f"AC-FUNC-001: expected project.remote.name='origin' after Load() but got: {project.remote.name!r}"
        )

    def test_valid_default_attributes_observable_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """All default attribute values set in <default> are observable after m.Load().

        The parser must apply all attribute values to the _Default object
        during m.Load() so they are immediately accessible to callers without
        further processing.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" revision="refs/heads/stable" sync-j="2" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        d = m.default
        assert d.remote is not None, "AC-FUNC-001: expected default.remote set after m.Load() but got None"
        assert d.remote.name == "origin", (
            f"AC-FUNC-001: expected default.remote.name='origin' after m.Load() but got: {d.remote.name!r}"
        )
        assert d.revisionExpr == "refs/heads/stable", (
            f"AC-FUNC-001: expected default.revisionExpr='refs/heads/stable' after m.Load() but got: {d.revisionExpr!r}"
        )
        assert d.sync_j == 2, f"AC-FUNC-001: expected default.sync_j=2 after m.Load() but got: {d.sync_j!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultCrossRefChannelDiscipline:
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
        """An undeclared remote reference in <default> raises ManifestParseError; stdout is empty.

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

    def test_duplicate_default_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate conflicting <default> raises ManifestParseError, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="stable" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate default error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_default_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <default> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
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

    def test_valid_default_crossref_does_not_raise_and_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A manifest with valid <default> cross-element references does not raise or write stdout.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors or output)
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
                f"AC-CHANNEL-001: expected valid <default> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid <default> parse but got: {captured.out!r}"
        )
        assert manifest.default.remote is not None, (
            "AC-CHANNEL-001: expected default.remote set after valid parse but got None"
        )
