"""Unit tests for <annotation> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <annotation> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <annotation> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <annotation> element documented attributes:
  Required: name  -- the annotation key (string, required)
  Required: value -- the annotation value (string, required)
  Optional: keep  -- boolean string, "true" or "false" (default "true")

Documented constraints:
  - name absent or blank   -> ManifestParseError naming "name"
  - value absent or blank  -> ManifestParseError naming "value"
  - keep="true"            -> valid, stored as "true"
  - keep="false"           -> valid, stored as "false"
  - keep="TRUE"            -> valid, stored as "true" (lowercased)
  - keep="FALSE"           -> valid, stored as "false" (lowercased)
  - keep absent            -> defaults to "true"
  - keep=<other>           -> ManifestParseError with 'keep' in message
  - <annotation> may be a child of <project>, <remote>, or <submanifest>

Note: <annotation> has no path attributes; ManifestInvalidPathError is
not applicable to this element. All parse failures raise ManifestParseError.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.project import Annotation


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors pattern used in test_xml_copyfile_attributes.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.

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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content as the primary manifest file and load it.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.

    Raises:
        ManifestParseError: If the manifest is invalid.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _manifest_with_project_annotation(annotation_attrs: str) -> str:
    """Build a manifest XML string with a <project> containing one <annotation> child.

    Args:
        annotation_attrs: Raw attribute string for the <annotation> element.

    Returns:
        Full manifest XML string.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f"    <annotation {annotation_attrs} />\n"
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_with_remote_annotation(annotation_attrs: str) -> str:
    """Build a manifest XML string with a <remote> containing one <annotation> child.

    Args:
        annotation_attrs: Raw attribute string for the <annotation> element.

    Returns:
        Full manifest XML string.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com">\n'
        f"    <annotation {annotation_attrs} />\n"
        "  </remote>\n"
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )


def _manifest_without_name(value: str = "eng", keep: str = "true") -> str:
    """Build a manifest XML string with a <annotation> element missing the name attribute.

    Args:
        value: Value for the value attribute.
        keep: Value for the keep attribute.

    Returns:
        Full manifest XML string.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <annotation value="{value}" keep="{keep}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_without_value(name: str = "team", keep: str = "true") -> str:
    """Build a manifest XML string with a <annotation> element missing the value attribute.

    Args:
        name: Value for the name attribute.
        keep: Value for the keep attribute.

    Returns:
        Full manifest XML string.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <annotation name="{name}" keep="{keep}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _get_project_annotation(manifest: manifest_xml.XmlManifest, project_name: str) -> Annotation:
    """Return the first annotation from the named project.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name attribute of the target project.

    Returns:
        The first Annotation model object attached to the project.
    """
    by_name = {p.name: p for p in manifest.projects}
    project = by_name[project_name]
    return project.annotations[0]


def _get_remote_annotation(manifest: manifest_xml.XmlManifest, remote_name: str) -> Annotation:
    """Return the first annotation from the named remote.

    Args:
        manifest: A loaded XmlManifest instance.
        remote_name: The name attribute of the target remote.

    Returns:
        The first Annotation model object attached to the remote.
    """
    return manifest.remotes[remote_name].annotations[0]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every documented attribute of <annotation>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationNameValidValues:
    """AC-TEST-001 -- valid values accepted for the name attribute.

    The name attribute is a required string key. Any non-empty string is valid.
    """

    @pytest.mark.parametrize(
        "name_value",
        [
            "team",
            "owner",
            "env",
            "priority",
            "release-label",
            "build_config",
            "tier",
        ],
    )
    def test_name_valid_strings_accepted(self, tmp_path: pathlib.Path, name_value: str) -> None:
        """Valid non-empty name strings parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation(f'name="{name_value}" value="v"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.name == name_value, f"Expected annotation.name={name_value!r} but got: {annotation.name!r}"

    def test_name_is_stored_as_string(self, tmp_path: pathlib.Path) -> None:
        """The name attribute is stored as a string on the Annotation model.

        AC-TEST-001
        """
        xml_content = _manifest_with_project_annotation('name="my-key" value="my-val"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert isinstance(annotation.name, str), (
            f"Expected annotation.name to be a str but got: {type(annotation.name)!r}"
        )
        assert annotation.name == "my-key", f"Expected annotation.name='my-key' but got: {annotation.name!r}"


@pytest.mark.unit
class TestAnnotationValueValidValues:
    """AC-TEST-001 -- valid values accepted for the value attribute.

    The value attribute is a required string. Any non-empty string is valid.
    """

    @pytest.mark.parametrize(
        "val",
        [
            "platform-eng",
            "alice",
            "staging",
            "high",
            "prod",
            "us-east-1",
            "2024-01-01",
        ],
    )
    def test_value_valid_strings_accepted(self, tmp_path: pathlib.Path, val: str) -> None:
        """Valid non-empty value strings parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation(f'name="k" value="{val}"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.value == val, f"Expected annotation.value={val!r} but got: {annotation.value!r}"

    def test_value_is_stored_as_string(self, tmp_path: pathlib.Path) -> None:
        """The value attribute is stored as a string on the Annotation model.

        AC-TEST-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="my-val"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert isinstance(annotation.value, str), (
            f"Expected annotation.value to be a str but got: {type(annotation.value)!r}"
        )
        assert annotation.value == "my-val", f"Expected annotation.value='my-val' but got: {annotation.value!r}"


@pytest.mark.unit
class TestAnnotationKeepValidValues:
    """AC-TEST-001 -- valid values accepted for the keep attribute.

    keep is optional. When present, it must be 'true' or 'false' (case-insensitive).
    When absent it defaults to 'true'. The stored value is always lowercase.
    """

    def test_keep_true_accepted_and_stored(self, tmp_path: pathlib.Path) -> None:
        """keep='true' parses and is stored as 'true'.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v" keep="true"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.keep == "true", f"Expected annotation.keep='true' but got: {annotation.keep!r}"

    def test_keep_false_accepted_and_stored(self, tmp_path: pathlib.Path) -> None:
        """keep='false' parses and is stored as 'false'.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v" keep="false"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.keep == "false", f"Expected annotation.keep='false' but got: {annotation.keep!r}"

    def test_keep_absent_defaults_to_true(self, tmp_path: pathlib.Path) -> None:
        """When keep is absent, annotation.keep defaults to 'true'.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.keep == "true", f"Expected annotation.keep default='true' but got: {annotation.keep!r}"

    @pytest.mark.parametrize(
        "keep_input,expected_keep",
        [
            ("true", "true"),
            ("false", "false"),
            ("TRUE", "true"),
            ("FALSE", "false"),
            ("True", "true"),
            ("False", "false"),
        ],
    )
    def test_keep_values_normalized_to_lowercase(
        self, tmp_path: pathlib.Path, keep_input: str, expected_keep: str
    ) -> None:
        """Parameterized: keep values are lowercased before storage.

        AC-TEST-001: case variants 'TRUE' and 'FALSE' are accepted and stored lowercase.
        """
        xml_content = _manifest_with_project_annotation(f'name="k" value="v" keep="{keep_input}"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.keep == expected_keep, (
            f"Expected annotation.keep={expected_keep!r} for input {keep_input!r} but got: {annotation.keep!r}"
        )

    def test_keep_on_remote_annotation_accepted(self, tmp_path: pathlib.Path) -> None:
        """keep attribute is accepted on <annotation> children of <remote>.

        AC-TEST-001: the keep attribute is valid regardless of parent element.
        """
        xml_content = _manifest_with_remote_annotation('name="geo" value="us-east" keep="false"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_remote_annotation(manifest, "origin")
        assert annotation.keep == "false", (
            f"Expected annotation.keep='false' on remote annotation but got: {annotation.keep!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests for every documented attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationKeepInvalidValues:
    """AC-TEST-002 -- invalid values for the keep attribute raise ManifestParseError.

    The _ParseAnnotation method raises ManifestParseError when keep is present
    but not 'true' or 'false' (after lowercasing). The error message includes
    'keep' so the user can identify which attribute caused the failure.
    """

    @pytest.mark.parametrize(
        "bad_keep",
        [
            "maybe",
            "yes",
            "no",
            "1",
            "0",
            "on",
            "off",
            "enabled",
            "disabled",
        ],
    )
    def test_invalid_keep_raises_manifest_parse_error(self, tmp_path: pathlib.Path, bad_keep: str) -> None:
        """Invalid keep values raise ManifestParseError with 'keep' in the message.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation(f'name="k" value="v" keep="{bad_keep}"')
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert error_text, f"Expected non-empty ManifestParseError for keep={bad_keep!r} but got empty string"
        assert "keep" in error_text.lower(), (
            f"Expected 'keep' in error message for keep={bad_keep!r} but got: {error_text!r}"
        )

    def test_invalid_keep_on_remote_annotation_raises(self, tmp_path: pathlib.Path) -> None:
        """Invalid keep on a <remote> annotation also raises ManifestParseError.

        AC-TEST-002: keep validation applies regardless of the parent element.
        """
        xml_content = _manifest_with_remote_annotation('name="geo" value="east" keep="maybe"')
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert "keep" in error_text.lower(), (
            f"Expected 'keep' in error message for invalid remote annotation keep but got: {error_text!r}"
        )

    def test_invalid_keep_error_is_manifest_parse_error_not_other(self, tmp_path: pathlib.Path) -> None:
        """Invalid keep raises ManifestParseError specifically, not a generic Exception.

        AC-TEST-002: the error type must be ManifestParseError for type-safe catch blocks.
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v" keep="invalid"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationRequiredAttributeOmission:
    """AC-TEST-003 -- omitting a required attribute raises ManifestParseError
    with a message that names the missing attribute.

    The _reqatt helper raises:
      "no {attr} in <annotation> within {file}"
    when name or value is absent or blank.
    """

    def test_missing_name_raises_parse_error_naming_name(self, tmp_path: pathlib.Path) -> None:
        """Omitting the name attribute raises ManifestParseError mentioning 'name'.

        AC-TEST-003
        """
        xml_content = _manifest_without_name()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert "name" in error_text, f"Expected error message to name 'name' attribute but got: {error_text!r}"

    def test_missing_value_raises_parse_error_naming_value(self, tmp_path: pathlib.Path) -> None:
        """Omitting the value attribute raises ManifestParseError mentioning 'value'.

        AC-TEST-003
        """
        xml_content = _manifest_without_value()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert "value" in error_text, f"Expected error message to name 'value' attribute but got: {error_text!r}"

    @pytest.mark.parametrize(
        "attr_name,xml_builder",
        [
            ("name", _manifest_without_name),
            ("value", _manifest_without_value),
        ],
    )
    def test_missing_required_attribute_raises_manifest_parse_error(
        self, tmp_path: pathlib.Path, attr_name: str, xml_builder
    ) -> None:
        """Parameterized: each required attribute, when omitted, raises ManifestParseError.

        AC-TEST-003: both required attributes are enforced; omitting either raises.
        """
        xml_content = xml_builder()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert attr_name in error_text, (
            f"Expected error message to name attribute '{attr_name}' but got: {error_text!r}"
        )

    def test_missing_name_error_message_is_nonempty(self, tmp_path: pathlib.Path) -> None:
        """The ManifestParseError raised for missing name has a non-empty message.

        AC-TEST-003: error messages must be actionable -- not an empty string.
        """
        xml_content = _manifest_without_name()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing name"

    def test_missing_value_error_message_is_nonempty(self, tmp_path: pathlib.Path) -> None:
        """The ManifestParseError raised for missing value has a non-empty message.

        AC-TEST-003: error messages must be actionable -- not an empty string.
        """
        xml_content = _manifest_without_value()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing value"

    def test_missing_name_raises_manifest_parse_error_type(self, tmp_path: pathlib.Path) -> None:
        """Missing name raises ManifestParseError specifically, not a generic Exception.

        AC-TEST-003: callers catching ManifestParseError must receive the right type.
        """
        xml_content = _manifest_without_name()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_missing_value_raises_manifest_parse_error_type(self, tmp_path: pathlib.Path) -> None:
        """Missing value raises ManifestParseError specifically, not a generic Exception.

        AC-TEST-003: callers catching ManifestParseError must receive the right type.
        """
        xml_content = _manifest_without_value()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_missing_name_on_remote_annotation_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """name omission on a <remote> annotation also raises ManifestParseError.

        AC-TEST-003: required-attribute enforcement applies regardless of parent element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com">\n'
            '    <annotation value="eng" />\n'
            "  </remote>\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        error_text = str(exc_info.value)
        assert "name" in error_text, (
            f"Expected error naming 'name' for missing annotation name on remote but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Every documented attribute is validated at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationParseTimeValidation:
    """AC-FUNC-001 -- every documented attribute is validated during manifest load.

    Validation must occur at parse time (during m.Load()), not deferred.
    Tests confirm that both valid and invalid values are resolved immediately
    on Load.
    """

    def test_valid_name_and_value_produce_annotation_model(self, tmp_path: pathlib.Path) -> None:
        """Both valid name and value produce a populated Annotation on the project model.

        AC-FUNC-001: attributes are validated AND their values stored on the model.
        """
        xml_content = _manifest_with_project_annotation('name="team" value="platform-eng"')
        manifest = _write_and_load(tmp_path, xml_content)

        by_name = {p.name: p for p in manifest.projects}
        project = by_name["platform/core"]
        assert len(project.annotations) == 1, (
            f"Expected exactly 1 annotation after valid parse but got: {len(project.annotations)}"
        )
        annotation = project.annotations[0]
        assert annotation.name == "team", f"Expected name='team' but got: {annotation.name!r}"
        assert annotation.value == "platform-eng", f"Expected value='platform-eng' but got: {annotation.value!r}"
        assert annotation.keep == "true", f"Expected keep='true' (default) but got: {annotation.keep!r}"

    def test_invalid_keep_detected_at_parse_not_later(self, tmp_path: pathlib.Path) -> None:
        """Invalid keep value is detected and raised during manifest load, not later.

        AC-FUNC-001: parse-time validation means errors surface on Load().
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v" keep="bad"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_missing_name_detected_at_parse_not_later(self, tmp_path: pathlib.Path) -> None:
        """Missing name attribute is detected and raised during manifest load.

        AC-FUNC-001
        """
        xml_content = _manifest_without_name()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_missing_value_detected_at_parse_not_later(self, tmp_path: pathlib.Path) -> None:
        """Missing value attribute is detected and raised during manifest load.

        AC-FUNC-001
        """
        xml_content = _manifest_without_value()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    @pytest.mark.parametrize(
        "name,value,keep",
        [
            ("team", "alpha", "true"),
            ("tier", "gold", "false"),
            ("region", "us-west", "true"),
            ("owner", "alice", "false"),
        ],
    )
    def test_all_documented_attributes_accepted_for_various_combinations(
        self, tmp_path: pathlib.Path, name: str, value: str, keep: str
    ) -> None:
        """Parameterized: all documented attribute combinations are accepted at parse time.

        AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation(f'name="{name}" value="{value}" keep="{keep}"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert annotation.name == name, f"Expected name={name!r} but got: {annotation.name!r}"
        assert annotation.value == value, f"Expected value={value!r} but got: {annotation.value!r}"
        assert annotation.keep == keep, f"Expected keep={keep!r} but got: {annotation.keep!r}"

    def test_annotation_model_is_annotation_instance(self, tmp_path: pathlib.Path) -> None:
        """Parsed annotation model is an instance of the Annotation class.

        AC-FUNC-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v"')
        manifest = _write_and_load(tmp_path, xml_content)
        annotation = _get_project_annotation(manifest, "platform/core")
        assert isinstance(annotation, Annotation), f"Expected Annotation instance but got: {type(annotation)!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationChannelDiscipline:
    """AC-CHANNEL-001 -- parse errors must not write to stdout.

    Error information for invalid <annotation> attributes must be conveyed
    exclusively through raised exceptions. No error text must appear on
    stdout. Successful parses must not produce any output on stdout either.
    """

    def test_valid_annotation_produces_no_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing a valid <annotation> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_project_annotation('name="team" value="eng" keep="true"')
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout for valid parse but got: {captured.out!r}"

    def test_missing_name_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing name attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_name()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_missing_value_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing value attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_value()
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_invalid_keep_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Invalid keep attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_project_annotation('name="k" value="v" keep="invalid"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_valid_remote_annotation_produces_no_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing a valid <remote> annotation produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_remote_annotation('name="geo" value="us-east" keep="true"')
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout for valid remote annotation parse but got: {captured.out!r}"
