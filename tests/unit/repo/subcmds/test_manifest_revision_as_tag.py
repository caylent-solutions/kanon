"""Unit tests for the ``--revision-as-tag`` flag in subcmds/manifest.py.

Verifies:
- AC-TEST-001: The ``--revision-as-tag`` flag is registered in
  ``Manifest._Options()`` and accepted by the option parser without
  triggering exit code 2 ("no such option").
- AC-TEST-001: ``_lookup_exact_tag`` returns ``refs/tags/<name>`` when
  ``git describe --exact-match HEAD`` succeeds and raises ``GitCommandError``
  when no tag matches.
- AC-TEST-001: ``_apply_revision_as_tag`` rewrites ``revision`` attributes on
  ``<project>`` DOM elements using tag names supplied by the lookup callable.

All tests are decorated with ``@pytest.mark.unit``.
"""

import optparse
import xml.dom.minidom
from unittest.mock import MagicMock

import pytest

from kanon_cli.repo.subcmds.manifest import (
    Manifest,
    _apply_revision_as_tag,
    _lookup_exact_tag,
)


# ---------------------------------------------------------------------------
# Constants -- no literals embedded in assertions.
# ---------------------------------------------------------------------------

_TAG_NAME = "v1.2.3"
_TAG_REFS_PATH = f"refs/tags/{_TAG_NAME}"
_PROJECT_NAME_A = "platform/art"
_PROJECT_REVISION_SHA = "abc1234def5678901234567890abcdef01234567"

_MINIMAL_XML_WITH_REVISION = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    f'  <project name="{_PROJECT_NAME_A}" revision="{_PROJECT_REVISION_SHA}" />\n'
    "</manifest>\n"
)

_MINIMAL_XML_NO_REVISION = (
    f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <project name="{_PROJECT_NAME_A}" />\n</manifest>\n'
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_manifest_cmd() -> Manifest:
    """Return a minimal Manifest instance with all heavy dependencies mocked."""
    cmd = Manifest.__new__(Manifest)
    cmd.manifest = MagicMock()
    cmd.ManifestList = MagicMock()
    cmd.Usage = MagicMock()
    return cmd


def _make_project_mock(relpath: str, tag: str | None) -> MagicMock:
    """Return a mock Project whose ``git describe --exact-match HEAD`` output is controlled.

    Args:
        relpath: Relative path of the project in the manifest.
        tag: The tag name returned by ``describe``. ``None`` simulates no exact tag.

    Returns:
        A MagicMock that mimics a minimal ``Project`` instance.
    """
    from kanon_cli.repo.git_command import GitCommandError

    project = MagicMock()
    project.relpath = relpath
    if tag is None:
        project.work_git.describe.side_effect = GitCommandError("git describe --exact-match failed", git_rc=128)
    else:
        project.work_git.describe.return_value = tag
    return project


# ---------------------------------------------------------------------------
# AC-TEST-001 (part 1): ``--revision-as-tag`` is registered in _Options().
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRevisionAsTagFlagRegistered:
    """``--revision-as-tag`` must be a registered option in Manifest._Options().

    The flag was previously absent, causing exit 2 ("no such option").  After
    the fix it must be accepted by the option parser without raising an error.
    """

    def test_revision_as_tag_flag_in_options(self) -> None:
        """``_Options()`` must register ``--revision-as-tag`` with the parser.

        Uses the real ``optparse.OptionParser`` so that option-string conflicts
        are detected and unrecognised flags would raise ``BadOptionError``.
        """
        cmd = _make_manifest_cmd()
        parser = optparse.OptionParser()
        cmd._Options(parser)

        option_strings = {
            opt_str for option in parser.option_list for opt_str in option._long_opts + option._short_opts
        }
        assert "--revision-as-tag" in option_strings, (
            f"Expected '--revision-as-tag' in registered option strings, got: {sorted(option_strings)}"
        )

    def test_revision_as_tag_default_is_false(self) -> None:
        """``--revision-as-tag`` must default to False (store_true semantics).

        When the flag is absent from the command line, ``opt.revision_as_tag``
        must be ``False`` so that normal manifest output is unchanged.
        """
        cmd = _make_manifest_cmd()
        parser = optparse.OptionParser()
        cmd._Options(parser)

        opts, _ = parser.parse_args([])
        assert opts.revision_as_tag is False, (
            f"Expected opt.revision_as_tag to be False when flag is absent, got {opts.revision_as_tag!r}"
        )

    def test_revision_as_tag_set_when_flag_passed(self) -> None:
        """``opt.revision_as_tag`` must be True when ``--revision-as-tag`` is supplied.

        Confirms the flag uses ``store_true`` semantics: present means True.
        """
        cmd = _make_manifest_cmd()
        parser = optparse.OptionParser()
        cmd._Options(parser)

        opts, _ = parser.parse_args(["--revision-as-tag"])
        assert opts.revision_as_tag is True, (
            f"Expected opt.revision_as_tag to be True when flag is passed, got {opts.revision_as_tag!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-001 (part 2): ``_lookup_exact_tag`` helper.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLookupExactTag:
    """``_lookup_exact_tag`` must resolve project commit to ``refs/tags/<name>``.

    When ``git describe --exact-match HEAD`` exits 0 it returns the tag name.
    When it exits non-zero (no exact match), it raises ``GitCommandError``.
    The helper must wrap the tag in ``refs/tags/<name>`` on success.
    """

    def test_returns_refs_tags_prefix_on_exact_match(self) -> None:
        """``_lookup_exact_tag`` returns ``refs/tags/<tag>`` when git describe succeeds."""
        project = _make_project_mock(relpath=_PROJECT_NAME_A, tag=_TAG_NAME)

        result = _lookup_exact_tag(project)

        assert result == _TAG_REFS_PATH, f"Expected _lookup_exact_tag to return {_TAG_REFS_PATH!r}, got {result!r}"

    def test_raises_git_command_error_when_no_exact_tag(self) -> None:
        """``_lookup_exact_tag`` re-raises GitCommandError when no exact tag matches.

        When the project HEAD has no exact tag, ``git describe --exact-match``
        exits non-zero. The helper must propagate the exception so callers can
        decide how to handle untagged commits.
        """
        from kanon_cli.repo.git_command import GitCommandError

        project = _make_project_mock(relpath=_PROJECT_NAME_A, tag=None)

        with pytest.raises(GitCommandError):
            _lookup_exact_tag(project)

    @pytest.mark.parametrize(
        "raw_tag,expected",
        [
            ("1.0.0", "refs/tags/1.0.0"),
            ("v2.3.4", "refs/tags/v2.3.4"),
            ("release/2024-01-01", "refs/tags/release/2024-01-01"),
        ],
        ids=["plain-semver", "v-prefixed", "slash-tag"],
    )
    def test_tag_name_variants(self, raw_tag: str, expected: str) -> None:
        """``_lookup_exact_tag`` constructs ``refs/tags/<name>`` for any tag name format."""
        project = _make_project_mock(relpath=_PROJECT_NAME_A, tag=raw_tag)

        result = _lookup_exact_tag(project)

        assert result == expected, f"Expected {expected!r} for tag {raw_tag!r}, got {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-001 (part 3): ``_apply_revision_as_tag`` helper.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyRevisionAsTag:
    """``_apply_revision_as_tag`` must replace ``revision`` DOM attributes with tags.

    Exercises the DOM-mutation function that iterates ``<project>`` elements
    and calls a lookup callable to obtain the tag for each project.
    """

    def test_replaces_revision_with_tag_for_single_project(self) -> None:
        """``_apply_revision_as_tag`` replaces the revision attribute for a single project.

        The DOM ``<project revision="...">`` element must have its ``revision``
        attribute updated to ``refs/tags/<tag>`` when the lookup callable
        returns a tag for the project's path.
        """
        doc = xml.dom.minidom.parseString(_MINIMAL_XML_WITH_REVISION.encode("utf-8"))
        # lookup_fn returns the tag refs path for the project relpath.
        lookup_fn = MagicMock(return_value=_TAG_REFS_PATH)

        _apply_revision_as_tag(doc, _PROJECT_NAME_A, lookup_fn)

        project_elements = doc.getElementsByTagName("project")
        assert len(project_elements) == 1
        revision_attr = project_elements[0].getAttribute("revision")
        assert revision_attr == _TAG_REFS_PATH, (
            f"Expected revision attribute to be {_TAG_REFS_PATH!r}, got {revision_attr!r}"
        )

    def test_leaves_revision_unchanged_when_lookup_raises(self, capsys) -> None:
        """``_apply_revision_as_tag`` leaves revision unchanged and warns to stderr when lookup raises.

        When ``_lookup_exact_tag`` raises (no exact tag for the commit),
        the ``<project revision="...">`` attribute must keep its original value,
        and a structured warning identifying the project must be emitted to stderr
        so the skip is not silent.
        """
        from kanon_cli.repo.git_command import GitCommandError

        doc = xml.dom.minidom.parseString(_MINIMAL_XML_WITH_REVISION.encode("utf-8"))
        lookup_fn = MagicMock(side_effect=GitCommandError("git describe --exact-match failed", git_rc=128))

        _apply_revision_as_tag(doc, _PROJECT_NAME_A, lookup_fn)

        project_elements = doc.getElementsByTagName("project")
        revision_attr = project_elements[0].getAttribute("revision")
        assert revision_attr == _PROJECT_REVISION_SHA, (
            f"Expected revision to be unchanged ({_PROJECT_REVISION_SHA!r}), but got {revision_attr!r}"
        )

        captured = capsys.readouterr()
        assert _PROJECT_NAME_A in captured.err, (
            f"Expected a warning containing project path {_PROJECT_NAME_A!r} on stderr, got: {captured.err!r}"
        )
        assert "warning" in captured.err.lower(), f"Expected stderr to contain 'warning', got: {captured.err!r}"

    def test_project_without_revision_attribute_gets_tag_set(self) -> None:
        """``_apply_revision_as_tag`` sets revision attribute even when initially absent.

        A ``<project>`` without an explicit ``revision`` attribute (i.e. it
        inherits the default revision) must have its ``revision`` attribute
        set to the tag reference when the lookup callable returns a tag.
        This is the AC-FUNC-001 requirement: every project's revision must
        be replaced by the nearest git tag, regardless of whether a ``revision``
        attribute was explicitly present in the original manifest.
        """
        doc = xml.dom.minidom.parseString(_MINIMAL_XML_NO_REVISION.encode("utf-8"))
        lookup_fn = MagicMock(return_value=_TAG_REFS_PATH)

        _apply_revision_as_tag(doc, _PROJECT_NAME_A, lookup_fn)

        project_elements = doc.getElementsByTagName("project")
        assert project_elements[0].hasAttribute("revision"), (
            "Expected 'revision' attribute to be added to a project when a tag is found."
        )
        revision_attr = project_elements[0].getAttribute("revision")
        assert revision_attr == _TAG_REFS_PATH, (
            f"Expected revision to be set to {_TAG_REFS_PATH!r}, got {revision_attr!r}"
        )

    def test_lookup_called_once_per_project_with_revision(self) -> None:
        """``_apply_revision_as_tag`` calls the lookup callable once per project that has a revision.

        Ensures the lookup function is invoked for every relevant project and
        not called for projects without a revision attribute.
        """
        doc = xml.dom.minidom.parseString(_MINIMAL_XML_WITH_REVISION.encode("utf-8"))
        lookup_fn = MagicMock(return_value=_TAG_REFS_PATH)

        _apply_revision_as_tag(doc, _PROJECT_NAME_A, lookup_fn)

        lookup_fn.assert_called_once()
