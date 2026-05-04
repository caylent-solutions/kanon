"""Regression-guard for E2-F3-S2-T7: MK-17 plugin name fix.

The MK-17 scenario tests `<manifest>` files with multiple `<project>`
entries pointing at the same source plugin. Because the plugin name
in `marketplace.json` is single (`mk17`), `claude plugin list` shows
ONE entry, not two — the unique observable output of the multi-project
scenario is the two linkfiles in `${KANON_TEST_ROOT}/mk17-mpl/`.

The Pass criterion is updated to verify the linkfiles, not
`claude plugin list | grep -E "mk17-(a|b)"`.
"""

from __future__ import annotations

import pathlib
import re

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _scenario_block(doc: str, heading: str) -> str:
    pattern = re.compile(
        r"^### " + re.escape(heading) + r"(?:\b|:|$).*?(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(doc)
    assert match is not None, f"Scenario block '{heading}' not found in {DOC_PATH}"
    return match.group(0)


@pytest.mark.unit
class TestT7MK17:
    def test_uses_linkfile_assertion_not_plugin_list_grep(self) -> None:
        block = _scenario_block(_load_doc(), "MK-17")
        # The corrected scenario asserts BOTH linkfiles are present.
        assert 'test -L "${KANON_TEST_ROOT}/mk17-mpl/mk17-a"' in block, "MK-17 must assert mk17-a linkfile is present"
        assert 'test -L "${KANON_TEST_ROOT}/mk17-mpl/mk17-b"' in block, "MK-17 must assert mk17-b linkfile is present"

    def test_no_plugin_list_grep_for_path_suffixes(self) -> None:
        block = _scenario_block(_load_doc(), "MK-17")
        # The old, broken assertion used `claude plugin list ... | grep -E "mk17-(a|b)"`.
        # That expression should not appear in the corrected block.
        assert "mk17-(a|b)" not in block, (
            "MK-17 must not grep `claude plugin list` for path-suffix names like mk17-(a|b); "
            "those don't appear in plugin list (plugin name comes from marketplace.json)"
        )

    def test_clean_assertion_present(self) -> None:
        block = _scenario_block(_load_doc(), "MK-17")
        assert (
            'test ! -L "${KANON_TEST_ROOT}/mk17-mpl/mk17-a"' in block
            and 'test ! -L "${KANON_TEST_ROOT}/mk17-mpl/mk17-b"' in block
        ), "MK-17 must verify both linkfiles are removed after `kanon clean .kanon`"
