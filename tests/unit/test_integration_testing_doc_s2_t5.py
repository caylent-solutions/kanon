"""Regression-guard for E2-F3-S2-T5: XML escape in fixture heredocs.

Verifies that the `mk_rx_xml`, `mk_mfst_xml`, and `pk_xml` helpers in
`docs/integration-testing.md` escape `<`, `>`, and `&` in the revision
attribute value before writing the XML file. Without this escaping,
revisions like `<2.0.0`, `<=1.1.0`, or `>=1.0.0,<2.0.0` produce
ill-formed XML that the repo parser correctly rejects (RX-08, RX-09,
RX-12, RX-21, RX-22, RX-25, MK-05, MK-09, PK-04).

Each helper must do `sed -e 's/&/\\&amp;/g' -e 's/</\\&lt;/g' -e
's/>/\\&gt;/g'` (or equivalent) on the rev value before interpolating
into the XMLEOF heredoc.
"""

from __future__ import annotations

import pathlib
import re

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _helper_block(doc: str, helper_name: str) -> str:
    """Return the body of a bash function definition `<name>() { ... }`."""
    pattern = re.compile(
        r"^" + re.escape(helper_name) + r"\(\)\s*\{.*?^\}",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(doc)
    assert match is not None, f"Helper '{helper_name}()' not found in {DOC_PATH}"
    return match.group(0)


@pytest.mark.unit
class TestT5XmlEscapeHelpers:
    @pytest.mark.parametrize("helper", ["mk_rx_xml", "mk_mfst_xml", "pk_xml"])
    def test_helper_uses_sed_to_escape_xml_specials(self, helper: str) -> None:
        block = _helper_block(_load_doc(), helper)
        # The fix introduces a sed pipeline that escapes `&`, `<`, `>` in order.
        # Order matters (`&` must be escaped first) so the test pins the
        # ampersand-first sequence.
        assert "s/&/\\&amp;/g" in block, (
            f"Helper {helper}() must escape `&` -> `&amp;` (must be first to avoid double-escaping)"
        )
        assert "s/</\\&lt;/g" in block, f"Helper {helper}() must escape `<` -> `&lt;`"
        assert "s/>/\\&gt;/g" in block, f"Helper {helper}() must escape `>` -> `&gt;`"

    @pytest.mark.parametrize("helper", ["mk_rx_xml", "mk_mfst_xml", "pk_xml"])
    def test_helper_emits_escaped_revision(self, helper: str) -> None:
        """The XML attribute must use the escaped variable, not the raw input."""
        block = _helper_block(_load_doc(), helper)
        # Look for the revision="${rev_xml}" attribute (the escaped variant).
        assert 'revision="${rev_xml}"' in block, (
            f'Helper {helper}() must emit revision="${{rev_xml}}" (the escaped value), not the raw ${{rev}}'
        )

    @pytest.mark.parametrize(
        "helper,raw_attr",
        [
            ("mk_rx_xml", 'revision="${rev}"'),
            ("mk_mfst_xml", 'revision="${rev}"'),
            ("pk_xml", 'revision="${rev}"'),
        ],
    )
    def test_helper_does_not_emit_raw_revision(self, helper: str, raw_attr: str) -> None:
        """Pin the absence of the raw, un-escaped form."""
        block = _helper_block(_load_doc(), helper)
        assert raw_attr not in block, (
            f"Helper {helper}() must not emit {raw_attr!r}; use ${{rev_xml}} after sed escaping"
        )


@pytest.mark.unit
class TestT5DocGlobalNoRawXmlSpecialsInAttributes:
    """Belt-and-suspenders: the doc must not contain any literal XML attribute
    of the form `revision="<...>"` with a bare `<` inside the quotes (which
    would make the literal heredoc emit ill-formed XML)."""

    def test_no_raw_lt_in_revision_attribute_value(self) -> None:
        doc = _load_doc()
        # Match `revision="..."` where `...` contains a literal `<`. Be
        # tolerant of surrounding whitespace.
        bad = re.findall(r'revision="[^"]*<[^"]*"', doc)
        # Some Pass-criteria text may legitimately contain `revision="<...>"`
        # as a snippet of error output; we only flag the helper-emitted
        # template line itself if it contains a raw `<` inside quotes.
        # Filter for lines that look like XML being written to disk via
        # `<project ...>` (the actual emitted form).
        offenders = [m for m in bad if "<project " in m or "default remote" in m]
        assert not offenders, f"Doc contains XML emission lines with raw `<` in revision attribute: {offenders}"
