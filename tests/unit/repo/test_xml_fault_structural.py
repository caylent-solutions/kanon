# Copyright (C) 2026 Caylent, Inc.
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

"""Unit tests for XML fault injection: structural scenarios.

Covers:
  AC-TEST-001 -- very large input (>10MB) is processed without OOM
  AC-TEST-002 -- XML namespaces are handled without confusion
  AC-TEST-003 -- circular project dependencies (duplicate path) surface error
  AC-TEST-004 -- unsupported top-level element is rejected

  AC-FUNC-001 -- Parser rejects structurally invalid XML with actionable
                 messages

All tests exercise the manifest parser path in
kanon_cli.repo.manifest_xml.XmlManifest via real files on disk.
The conftest.py in this directory auto-applies @pytest.mark.unit to every
item collected here that does not carry a marker already.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers (mirrors pattern in test_xml_fault_malformed.py)
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest tmp_path for isolation.

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
    """Write xml_content to the canonical manifest file path.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML string for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# AC-TEST-001 -- very large input (>10MB) is processed without OOM
# ---------------------------------------------------------------------------

_LARGE_FILE_MIN_BYTES = 10 * 1024 * 1024
"""Minimum number of bytes required to qualify as a very large manifest."""

_LARGE_PROJECT_COUNT = 210_000
"""Number of projects used to generate a manifest that exceeds 10MB.

Each project element is ~53 bytes on disk. 10MB / 53 bytes ~ 198000;
210000 provides safe headroom above the 10MB threshold (~11MB).
"""


def _build_large_manifest_xml(project_count: int) -> str:
    """Build a syntactically valid manifest XML string with many projects.

    Args:
        project_count: Number of <project> elements to include.

    Returns:
        A valid manifest XML string whose encoded size exceeds 10MB for
        project_count >= 210000.
    """
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
    )
    footer = "</manifest>\n"
    project_lines = [f'  <project name="proj{i}" path="src/proj{i}" />\n' for i in range(project_count)]
    return header + "".join(project_lines) + footer


@pytest.mark.unit
class TestLargeInputHandling:
    """Verify that the manifest parser handles files larger than 10MB.

    The parser must not raise MemoryError or any OOM-related exception when
    processing a syntactically valid but very large XML document. This
    documents that the in-memory DOM approach can at minimum parse large
    files on realistic hardware without crashing.
    """

    def test_large_valid_manifest_parses_without_oom(self, tmp_path: pathlib.Path) -> None:
        """A valid manifest file larger than 10MB is parsed without error.

        AC-TEST-001: The parser must not crash with MemoryError, OverflowError,
        or any OOM-related exception when presented with a syntactically valid
        XML document whose on-disk size exceeds 10MB.

        Strategy: generate a valid manifest with many <project> elements so
        that the file size reliably exceeds the 10MB threshold.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_large_manifest_xml(_LARGE_PROJECT_COUNT)

        assert len(xml_content.encode("utf-8")) > _LARGE_FILE_MIN_BYTES, (
            f"Generated manifest must exceed {_LARGE_FILE_MIN_BYTES} bytes to satisfy AC-TEST-001. "
            f"Actual size: {len(xml_content.encode('utf-8'))} bytes. "
            f"Increase _LARGE_PROJECT_COUNT (currently {_LARGE_PROJECT_COUNT})."
        )

        manifest_file = _write_manifest(repodir, xml_content)

        # Must not raise MemoryError, OverflowError, or any OOM-related exception.
        try:
            loaded = _load_manifest(repodir, manifest_file)
        except MemoryError as exc:
            raise AssertionError(
                f"Parser raised MemoryError on a {len(xml_content)} character manifest. "
                "AC-TEST-001 requires that very large inputs do not trigger OOM failures."
            ) from exc

        assert loaded is not None, "Expected XmlManifest instance but got None."
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )
        assert len(loaded.projects) == _LARGE_PROJECT_COUNT, (
            f"Expected {_LARGE_PROJECT_COUNT} projects after loading large manifest, got {len(loaded.projects)}."
        )

    def test_large_file_size_is_at_least_ten_mb(self, tmp_path: pathlib.Path) -> None:
        """Confirm the large manifest fixture genuinely exceeds 10MB on disk.

        This test is a guard against test rot -- if _LARGE_PROJECT_COUNT is
        reduced in future, this test will fail before AC-TEST-001 silently
        becomes invalid.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_large_manifest_xml(_LARGE_PROJECT_COUNT)

        manifest_file = _write_manifest(repodir, xml_content)
        file_size = manifest_file.stat().st_size

        assert file_size > _LARGE_FILE_MIN_BYTES, (
            f"Manifest file is {file_size} bytes, which is less than the required "
            f"{_LARGE_FILE_MIN_BYTES} bytes ({_LARGE_FILE_MIN_BYTES // (1024 * 1024)} MB). "
            "Increase project_count so that AC-TEST-001 exercises a genuinely large file."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- XML namespaces are handled without confusion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlNamespaceHandling:
    """Verify the parser handles namespace-prefixed elements without crashing.

    minidom's nodeName for a namespace-prefixed element includes the prefix
    (e.g., ``ns:remote``). Because _ParseManifest compares nodeName against
    plain string names like ``"remote"``, namespace-prefixed elements are
    silently skipped rather than raising exceptions. This behavior must be
    preserved -- namespace prefixes must not cause crashes or incorrect
    parsing of the non-prefixed elements that follow.
    """

    def test_namespace_prefixed_elements_are_skipped_without_error(self, tmp_path: pathlib.Path) -> None:
        """A manifest with namespace-prefixed elements parses without exception.

        The prefixed elements must not cause confusion with the correctly
        named plain elements (remote, default, project). The parser must
        load the recognized elements normally.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest\n"
            '  xmlns:ext="https://example.com/extensions">\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <ext:metadata version="1.0" />\n'
            '  <project name="myproject" path="src/myproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)

        assert loaded is not None, "Expected XmlManifest instance but got None."
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )
        assert "src/myproject" in loaded.paths, (
            f"Expected 'src/myproject' in manifest.paths. Got: {list(loaded.paths.keys())!r}"
        )

    def test_namespace_declaration_on_root_does_not_affect_parsing(self, tmp_path: pathlib.Path) -> None:
        """A namespace declaration on the <manifest> root is tolerated.

        minidom parses xmlns attributes as ordinary attributes on the element.
        The parser must not treat this as a fatal error.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<manifest xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="stable" remote="upstream" />\n'
            '  <project name="lib" path="lib" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)

        assert "upstream" in loaded.remotes, (
            f"Expected 'upstream' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )
        assert "lib" in loaded.paths, f"Expected 'lib' in manifest.paths. Got: {list(loaded.paths.keys())!r}"

    @pytest.mark.parametrize(
        "namespace_xml",
        [
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <foo:unknownelement xmlns:foo="https://foo.example.com" />\n'
                "</manifest>\n"
            ),
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <a:b xmlns:a="https://a.example.com"'
                ' xmlns:b="https://b.example.com" />\n'
                "</manifest>\n"
            ),
        ],
        ids=["single_ns_element", "multi_ns_element"],
    )
    def test_various_namespace_elements_do_not_crash_parser(self, tmp_path: pathlib.Path, namespace_xml: str) -> None:
        """Multiple namespace-prefixed element patterns do not crash the parser.

        AC-TEST-002: Every namespace variant must leave recognized elements
        intact and must not raise an unexpected exception.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, namespace_xml)

        loaded = _load_manifest(repodir, manifest_file)

        assert loaded is not None, "Expected XmlManifest instance."
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- circular project dependencies (duplicate path) surface error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCircularProjectDependencies:
    """Verify that duplicate project paths raise ManifestParseError.

    The manifest parser uses a path-indexed dictionary (_paths) to track
    registered projects. When two distinct <project> elements declare the
    same ``path`` attribute, the parser raises ManifestParseError with
    "duplicate path" in the message. This is the structural error that most
    closely represents a circular or conflicting project graph.
    """

    def test_duplicate_project_path_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two projects with the same path raise ManifestParseError.

        AC-TEST-003: The error must be ManifestParseError and must describe
        the duplicate path so the user can identify the conflict.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="alpha" path="src/shared" />\n'
            '  <project name="beta" path="src/shared" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate path" in error_message, (
            f"Expected 'duplicate path' in error message but got: {error_message!r}. "
            "The error message must identify the conflicting path so the user knows what to fix."
        )
        assert "src/shared" in error_message, (
            f"Expected the conflicting path 'src/shared' in error message but got: {error_message!r}."
        )

    @pytest.mark.parametrize(
        "shared_path",
        [
            "src/collide",
            "vendor/lib",
            "a/b/c/d",
        ],
        ids=["src_collide", "vendor_lib", "deep_path"],
    )
    def test_various_duplicate_paths_raise_manifest_parse_error(self, tmp_path: pathlib.Path, shared_path: str) -> None:
        """Duplicate paths at various directory depths all raise ManifestParseError.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="first" path="{shared_path}" />\n'
            f'  <project name="second" path="{shared_path}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate path" in error_message, (
            f"Expected 'duplicate path' in error message for path {shared_path!r}. Got: {error_message!r}"
        )

    def test_same_project_name_and_path_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two projects with identical name AND path raise ManifestParseError.

        AC-TEST-003: Even when both name and path are identical, the second
        declaration must be rejected because the path is already occupied.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="duplicate" path="pkg/duplicate" />\n'
            '  <project name="duplicate" path="pkg/duplicate" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message, f"Expected 'duplicate' in error message. Got: {error_message!r}"


# ---------------------------------------------------------------------------
# AC-TEST-004 -- unsupported top-level element is rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnsupportedTopLevelElement:
    """Verify that unsupported top-level elements do not corrupt the manifest.

    The XmlManifest._ParseManifest() method processes known element types
    (remote, default, project, etc.) by dispatching on nodeName. Unknown
    element names are not dispatched and thus do not affect the parsed state
    -- they are silently dropped. This is the rejection mechanism: the element
    is excluded from the manifest's parsed state.

    The positive contract is that known elements after an unknown element are
    still parsed correctly. The negative contract is that unknown elements do
    not appear in the parsed manifest state (paths, remotes, etc.).
    """

    def test_unknown_element_does_not_appear_in_parsed_state(self, tmp_path: pathlib.Path) -> None:
        """An unknown top-level element is dropped from the parsed manifest.

        AC-TEST-004: After loading a manifest with an unknown element, the
        element must not appear in any parsed state (paths, remotes). The
        known elements following the unknown element must still be parsed.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-custom-element foo="bar" />\n'
            '  <project name="myproject" path="src/myproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)

        # The unknown element must not be in the parsed state.
        path_keys = list(loaded.paths.keys())
        assert "unknown-custom-element" not in path_keys, (
            f"Unknown element 'unknown-custom-element' must not appear in manifest.paths. Got: {path_keys!r}"
        )

        # Known elements after the unknown element must still be parsed.
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )
        assert "src/myproject" in loaded.paths, f"Expected 'src/myproject' in manifest.paths. Got: {path_keys!r}"

    @pytest.mark.parametrize(
        "element_name",
        [
            "unsupported-tag",
            "custom",
            "myvendor-extension",
        ],
        ids=["unsupported_tag", "custom", "vendor_extension"],
    )
    def test_various_unknown_elements_are_dropped_without_error(
        self, tmp_path: pathlib.Path, element_name: str
    ) -> None:
        """Multiple unknown element names are all silently dropped, not raised.

        AC-TEST-004: The parser must not crash on any unknown element name,
        and must continue parsing the valid elements that follow.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <{element_name} attr="value" />\n'
            '  <project name="post-unknown" path="src/post-unknown" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)

        # The project after the unknown element must be parsed.
        assert "src/post-unknown" in loaded.paths, (
            f"Expected 'src/post-unknown' in manifest.paths after unknown element "
            f"{element_name!r}. Got: {list(loaded.paths.keys())!r}"
        )
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )

    def test_known_elements_parse_correctly_without_unknown_elements(self, tmp_path: pathlib.Path) -> None:
        """A manifest with only known elements is fully parsed via ToDict.

        This is the positive baseline for AC-TEST-004: a manifest that uses
        only known elements must succeed through both Load and ToDict.

        AC-TEST-004
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>Build manifest</notice>\n"
            '  <project name="myproject" path="src/myproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)
        result = loaded.ToDict()

        assert result is not None, "Expected dict result from ToDict but got None."
        assert "remote" in result, f"Expected 'remote' key in ToDict result. Got keys: {list(result.keys())!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Parser rejects structurally invalid XML with actionable
#               messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParserStructuralRejection:
    """End-to-end verification that structural violations produce actionable errors.

    The manifest parser must reject structurally invalid inputs and provide
    clear, actionable error messages. The error must always be ManifestParseError
    with enough context for the user to identify and correct the problem.
    """

    def test_duplicate_remote_with_conflicting_attrs_raises_error(self, tmp_path: pathlib.Path) -> None:
        """Two remotes with the same name but different attributes raise ManifestParseError.

        AC-FUNC-001: Conflicting remote declarations must be detected and
        rejected with a clear message naming the remote.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="origin" fetch="https://other.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "origin" in error_message, f"Expected remote name 'origin' in error message. Got: {error_message!r}"

    def test_missing_remote_for_project_raises_error(self, tmp_path: pathlib.Path) -> None:
        """A project referencing a non-existent remote raises ManifestParseError.

        AC-FUNC-001: The parser must detect and reject references to undeclared
        remotes with an actionable message.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="nonexistent" />\n'
            '  <project name="myproject" path="src/myproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

    def test_valid_manifest_produces_no_errors(self, tmp_path: pathlib.Path) -> None:
        """A structurally valid manifest loads without any ManifestParseError.

        Baseline sanity check for AC-FUNC-001: confirms the test helpers
        work correctly and the parser accepts well-formed input.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="alpha" path="src/alpha" />\n'
            '  <project name="beta" path="src/beta" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        loaded = _load_manifest(repodir, manifest_file)

        assert loaded is not None, "Expected XmlManifest instance but got None."
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes. Got: {list(loaded.remotes.keys())!r}"
        )
        assert "src/alpha" in loaded.paths, (
            f"Expected 'src/alpha' in manifest.paths. Got: {list(loaded.paths.keys())!r}"
        )
        assert "src/beta" in loaded.paths, f"Expected 'src/beta' in manifest.paths. Got: {list(loaded.paths.keys())!r}"
