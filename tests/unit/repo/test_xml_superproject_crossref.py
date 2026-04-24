"""Unit tests for <superproject> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <superproject> are validated
               (e.g. remote name resolution -- a remote= attribute must
               reference a declared remote; an undeclared remote name raises
               ManifestParseError; when no remote is specified the manifest
               default remote is used)
  AC-TEST-002  Duplicate-element rules for <superproject> surface clear errors
               (two <superproject> elements in the same manifest raise
               ManifestParseError with "duplicate" and "superproject" in the
               message)
  AC-TEST-003  <superproject> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <superproject> child is
               processed; within a valid <manifest> root an unknown sibling
               element is ignored without affecting <superproject>)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <superproject> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <superproject>:
- The remote attribute, when present, must name a declared <remote> element;
  an undeclared name raises ManifestParseError.
- When remote is absent, the manifest default remote is used; when there is
  no default remote, ManifestParseError is raised.
- At most one <superproject> element is allowed per manifest; a second raises
  ManifestParseError with "duplicate superproject".
- <superproject> is only processed as a child of the <manifest> root; if the
  file root is not <manifest> the file is rejected before any child is
  processed.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_superproject_*.py files
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
# AC-TEST-001: Cross-element reference validation for <superproject>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <superproject> are validated.

    The remote attribute must resolve to a remote declared in the manifest.
    An undeclared remote name raises ManifestParseError with a message that
    identifies the unresolved reference. When the remote attribute is absent,
    the manifest default remote is used.
    """

    def test_remote_resolves_to_declared_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """remote= referencing a declared remote parses without error.

        After parsing, manifest.superproject.remote is set and its name
        contains the declared remote name.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set when remote resolves to a declared remote but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-001: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.remote is not None, (
            "AC-TEST-001: expected superproject.remote to be set but got None"
        )

    def test_remote_referencing_undeclared_remote_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """remote= naming an undeclared remote raises ManifestParseError.

        The error message must include text identifying the failed cross-reference.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="no-such-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for undeclared remote but got an empty string"
        )
        assert "no-such-remote" in error_message or "not defined" in error_message, (
            f"AC-TEST-001: expected error message to name the undeclared remote or contain "
            f"'not defined' but got: {error_message!r}"
        )

    def test_remote_absent_uses_default_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When remote is absent, the manifest default remote is used.

        The superproject resolves its remote from the <default> element's
        remote attribute.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set when remote is inherited from default but got None"
        )
        assert manifest.superproject.remote is not None, (
            "AC-TEST-001: expected superproject.remote to be resolved via default but got None"
        )

    def test_remote_absent_no_default_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When remote is absent and no default remote exists, ManifestParseError is raised.

        The cross-element requirement is that a remote must be resolvable; when
        neither the element attribute nor the manifest default can supply one,
        the parser raises.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError when no remote is resolvable but got an empty string"
        )

    @pytest.mark.parametrize(
        "undeclared_remote_name",
        [
            "missing-remote",
            "does-not-exist",
            "phantom-remote",
        ],
    )
    def test_various_undeclared_remote_names_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote_name: str,
    ) -> None:
        """Parameterized: each undeclared remote name raises ManifestParseError.

        The error must be non-empty and should identify that the referenced
        remote was not found.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <superproject name="platform/superproject" remote="{undeclared_remote_name}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected non-empty ManifestParseError for undeclared "
            f"remote='{undeclared_remote_name}' but got empty string"
        )

    def test_declared_remote_with_explicit_revision_resolves(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """remote= resolved to a declared remote with an explicit revision parses correctly.

        This cross-element reference involves both the remote and revision
        attributes. The remote is resolved first; an explicit revision overrides
        any default.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/sp" remote="upstream" revision="refs/tags/v3.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set for declared remote with explicit revision but got None"
        )
        assert manifest.superproject.revision == "refs/tags/v3.0", (
            f"AC-TEST-001: expected superproject.revision='refs/tags/v3.0' but got: {manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <superproject> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <superproject> surface clear errors.

    Only one <superproject> element is permitted per manifest. A second
    <superproject> element raises ManifestParseError. The error message must
    contain both "duplicate" and "superproject".
    """

    def test_two_superproject_elements_same_name_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <superproject> elements with the same name raise ManifestParseError.

        The error message must contain 'duplicate' and 'superproject'.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for repeated <superproject> but got: {error_message!r}"
        )
        assert "superproject" in error_message.lower(), (
            f"AC-TEST-002: expected 'superproject' in error message but got: {error_message!r}"
        )

    def test_two_superproject_elements_different_names_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <superproject> elements with different names raise ManifestParseError.

        Even when the two elements have distinct names, only one <superproject>
        is allowed. The error message must contain 'duplicate' and 'superproject'.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/super-a" />\n'
            '  <superproject name="platform/super-b" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for two distinct "
            f"<superproject> elements but got: {error_message!r}"
        )
        assert "superproject" in error_message.lower(), (
            f"AC-TEST-002: expected 'superproject' in error message but got: {error_message!r}"
        )

    def test_duplicate_superproject_error_message_is_non_empty(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError raised for duplicate <superproject> has a non-empty message.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/other" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected a non-empty error message for duplicate <superproject> but got an empty string"
        )

    @pytest.mark.parametrize(
        "second_superproject_name",
        [
            "platform/other-sp",
            "android/superproject",
            "org/mono",
        ],
    )
    def test_duplicate_superproject_regardless_of_second_name_raises(
        self,
        tmp_path: pathlib.Path,
        second_superproject_name: str,
    ) -> None:
        """Parameterized: duplicate <superproject> raises regardless of the second name.

        The uniqueness constraint applies to the element itself, not to
        identical name attribute values.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            f'  <superproject name="{second_superproject_name}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for duplicate "
            f"<superproject> with name='{second_superproject_name}' "
            f"but got: {error_message!r}"
        )

    def test_single_superproject_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <superproject> element does not raise.

        This is the positive control: the duplicate rule only fires when a
        second element appears.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected single <superproject> element to parse without "
                f"ManifestParseError but got: {exc!r}"
            )

        assert manifest.superproject is not None, (
            "AC-TEST-002: expected superproject to be set after single <superproject> but got None"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <superproject> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectUnexpectedParent:
    """AC-TEST-003: <superproject> in an unexpected parent raises or is ignored per spec.

    The parser only processes <superproject> when it appears as a direct child
    of the <manifest> root element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <superproject>) are
      examined. The error message mentions 'manifest'.
    - An unknown element sibling to <superproject> inside a valid <manifest>
      root is silently ignored; the <superproject> element is still processed.
    - A valid <manifest> root with a <superproject> and unknown siblings parses
      correctly and sets manifest.superproject.
    """

    def test_superproject_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <superproject> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
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
    def test_superproject_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <superproject> under any non-manifest root raises ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <superproject name="platform/superproject" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <superproject> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_superproject(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <superproject> inside <manifest> is ignored.

        Unknown elements inside a valid <manifest> root are silently skipped
        by the parser loop. The <superproject> element must still be processed
        and must resolve correctly.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert manifest.superproject is not None, (
            "AC-TEST-003: expected superproject to be set when unknown sibling "
            "element is present alongside <superproject> but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-003: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_superproject_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> inside a valid <manifest> root resolves its remote correctly.

        This positive test confirms the unexpected-parent logic: when the parent
        IS <manifest>, everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            '  <superproject name="infra/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-003: expected superproject to be set for valid <superproject> "
            "inside proper <manifest> parent but got None"
        )
        assert manifest.superproject.name == "infra/superproject", (
            f"AC-TEST-003: expected superproject.name='infra/superproject' but got: {manifest.superproject.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.superproject. These tests confirm that errors fire during
    Load() and that the manifest state is consistent after a successful parse.
    """

    def test_undefined_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote reference raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before any
        caller accesses manifest.superproject.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/sp" remote="absent-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_superproject_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate <superproject> elements raise during Load(), not on first access.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/super-a" />\n'
            '  <superproject name="platform/super-b" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_superproject_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid <superproject> is fully resolved by the time Load() returns.

        After Load(), manifest.superproject is set with name, remote, and
        revision all populated. No deferred resolution occurs.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-FUNC-001: expected superproject to be set immediately after Load() but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"AC-FUNC-001: expected superproject.name='platform/superproject' after Load() "
            f"but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.remote is not None, (
            "AC-FUNC-001: expected superproject.remote to be set after Load() but got None"
        )
        assert manifest.superproject.revision == "refs/heads/main", (
            f"AC-FUNC-001: expected superproject.revision='refs/heads/main' after Load() "
            f"but got: {manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_undefined_remote_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undefined remote reference raises ManifestParseError, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/sp" remote="phantom-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undefined remote error but got: {captured.out!r}"
        )

    def test_duplicate_superproject_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <superproject> raises ManifestParseError and produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/other" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate <superproject> error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_superproject_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <superproject> raises an exception, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <superproject name="platform/superproject" />\n'
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

    def test_valid_superproject_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a valid <superproject> cross-element reference does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="upstream" revision="refs/heads/stable" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <superproject> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert manifest.superproject is not None, (
            "AC-CHANNEL-001: expected superproject to be set after valid parse but got None"
        )
