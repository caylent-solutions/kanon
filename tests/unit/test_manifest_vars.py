"""Unit coverage for `kanon_cli.core.manifest_vars`.

Detection and the install-time guard share one walk, so whatever this module
misses is invisible to both: `kanon add` writes no line for the variable, the
guard finds nothing unresolved, and the install exits 0 having delivered nothing.
That is issue #95, and it recurred twice after the original fix -- once for the
unbraced `$VAR` spelling, once for every element other than `<project>`.

The module previously had no unit tests at all. Its only coverage was through
integration tests that spawn `kanon add` against a real git repository, which is
why the grammar surface went untested for so long.
"""

import xml.etree.ElementTree as ET

import pytest

from kanon_cli.core.manifest_vars import (
    MalformedManifestVarError,
    _vars_in_attributes,
    _vars_in_project,
)


def _element(xml: str) -> ET.Element:
    """Return the parsed root of an XML fragment."""
    return ET.fromstring(xml)


@pytest.mark.unit
class TestGrammarMatchesEnvsubst:
    """Detection must accept exactly what `os.path.expandvars` expands.

    A spelling the substituter expands but the detector misses is invisible to
    both halves of the contract; a spelling the detector reports but the
    substituter cannot resolve produces a `.kanon` key no value satisfies.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("${KITROOT}/x", {"KITROOT"}),
            ("$KITROOT/x", {"KITROOT"}),
            ("${A}${B}", {"A", "B"}),
            ("/a/${V}/b", {"V"}),
            ("$${V}", {"V"}),
            ("${V_1}", {"V_1"}),
            ("${V1}", {"V1"}),
        ],
        ids=["braced", "bare", "adjacent", "embedded", "escaped", "underscore", "digit"],
    )
    def test_expandable_forms_are_detected(self, value: str, expected: set[str]) -> None:
        assert _vars_in_attributes(_element(f'<linkfile src="s" dest="{value}" />')) == expected

    @pytest.mark.parametrize(
        "value",
        ["${V", "${}", "plain/path", "100% literal"],
        ids=["unclosed", "empty-body", "no-reference", "percent"],
    )
    def test_non_references_are_ignored(self, value: str) -> None:
        """Text `expandvars` leaves alone must not become a `.kanon` key."""
        assert _vars_in_attributes(_element(f'<linkfile src="s" dest="{value}" />')) == set()

    @pytest.mark.parametrize(
        "value",
        ["${VAR:-default}/x", "${ VAR }/x", "${A${B}}/x", "${MY-VAR}/x", "${A.B}/x"],
        ids=["default-expansion", "padded", "nested", "hyphen", "dot"],
    )
    def test_unresolvable_bodies_are_rejected(self, value: str) -> None:
        """A body `expandvars` can never resolve fails at detection.

        Left to pass, it becomes a `.kanon` key that no value can satisfy, so the
        source is permanently uninstallable however many times the operator
        follows the remediation.
        """
        with pytest.raises(MalformedManifestVarError) as excinfo:
            _vars_in_attributes(_element(f'<linkfile src="s" dest="{value}" />'))
        assert "not a variable reference" in str(excinfo.value)
        assert "linkfile" in str(excinfo.value), "the diagnostic must name the element"


@pytest.mark.unit
class TestAttributeSurface:
    """Every attribute of a scanned element is functional, not just `dest`."""

    def test_src_is_scanned_as_well_as_dest(self) -> None:
        assert _vars_in_attributes(_element('<linkfile src="${S}/a" dest="${D}/b" />')) == {"S", "D"}

    def test_exclude_is_scanned(self) -> None:
        assert "E" in _vars_in_attributes(_element('<linkfile src="s" dest="d" exclude="${E}" />'))

    def test_element_text_is_not_scanned(self) -> None:
        """Prose cannot make a variable functional.

        `Element.attrib` exposes only attribute values, never comments, CDATA or
        text, so the exclusion is structural rather than a heuristic. The
        production catalog relies on it: `${HOME}` appears in description prose
        throughout and must not become a per-source `.kanon` line.
        """
        assert _vars_in_attributes(_element("<notice>set ${HOME} before running</notice>")) == set()


@pytest.mark.unit
class TestProjectWalk:
    """A project's functional surface includes its children and sub-projects."""

    def test_delivery_children_are_scanned(self) -> None:
        found = _vars_in_project(
            _element(
                '<project name="p" path="p">'
                '<linkfile src="a" dest="${L}/x" />'
                '<copyfile src="b" dest="${C}/y" />'
                "</project>"
            )
        )
        assert found == {"L", "C"}

    def test_nested_projects_are_scanned(self) -> None:
        """The vendored parser resolves sub-projects, so their dests are live."""
        found = _vars_in_project(
            _element(
                '<project name="p" path="p">'
                '<project name="s" path="s"><linkfile src="a" dest="${SUB}/x" /></project>'
                "</project>"
            )
        )
        assert found == {"SUB"}

    def test_project_own_attributes_are_scanned(self) -> None:
        assert "REV" in _vars_in_project(_element('<project name="p" path="p" revision="${REV}" />'))
