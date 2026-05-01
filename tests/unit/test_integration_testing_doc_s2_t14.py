"""Regression-guard tests for E2-F3-S2-T14: env-dependent scenario notes.

Pins the `Environment dependency` annotations added next to RP-init-07
and the §25 RP-upload-* preamble. These scenarios fail in sandboxed CI
environments without git same-filesystem alternates support
(RP-init-07) or without a Gerrit review server / commits ahead of
upstream (RP-upload-01..15). Their failures are NOT kanon defects;
this Task documents that fact in the doc itself, with cross-reference
to the archive note.
"""

from __future__ import annotations

import pathlib
import re

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.mark.unit
class TestT14EnvDependencyNotes:
    def test_rp_init_07_has_environment_dependency_note(self) -> None:
        doc = _load_doc()
        # The block extends until the next `### ` so we capture the env note that
        # follows the Pass criteria.
        match = re.search(
            r"^### RP-init-07.*?(?=^### )",
            doc,
            re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "RP-init-07 block not found"
        block = match.group(0)
        assert "Environment dependency" in block, (
            "RP-init-07 must include an `Environment dependency` note explaining the alternates-file behaviour"
        )
        assert "accepted-env-failures.md" in block, (
            "RP-init-07 env note must reference the archive's accepted-env-failures.md"
        )

    def test_rp_upload_section_has_environment_dependency_note(self) -> None:
        doc = _load_doc()
        # The §25 preamble (between the section heading and the first scenario
        # heading) must contain the env-dependency block.
        match = re.search(
            r"^## 25\..*?Code-Review Workflows.*?(?=^### )",
            doc,
            re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "§25 preamble not found"
        preamble = match.group(0)
        assert "Environment dependency for RP-upload" in preamble, (
            "§25 preamble must include an `Environment dependency for RP-upload` note"
        )
        assert "accepted-env-failures.md" in preamble, (
            "§25 env note must reference the archive's accepted-env-failures.md"
        )

    # The third assertion that originally lived here checked for the archive
    # file `kanon-migration-backlog/it-run-archives/.../accepted-env-failures.md`.
    # That file lives in a *sibling* repo (`kanon-migration-backlog`), not in
    # the `kanon` repository checked out by CI. Asserting on a sibling-repo
    # path made the kanon test suite fail in any environment where the
    # sibling clone is absent. The integrity of that archive is the
    # responsibility of the `kanon-migration-backlog` repository's own CI;
    # the cross-reference in `docs/integration-testing.md` is verified by
    # the assertions above (presence of the `accepted-env-failures.md`
    # filename string in the env-dependency note).
