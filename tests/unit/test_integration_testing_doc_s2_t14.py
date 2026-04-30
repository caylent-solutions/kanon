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

    def test_archive_accepted_env_failures_file_exists_in_repo(self) -> None:
        """The doc cross-references this file; assert it exists alongside the
        kanon-migration-backlog archive."""
        # DOC_PATH is .../kanon/docs/integration-testing.md
        # parents: 0=docs, 1=kanon, 2=rpm-migration (workspace root)
        workspace_root = DOC_PATH.resolve().parents[2]
        archive_path = (
            workspace_root
            / "kanon-migration-backlog"
            / "it-run-archives"
            / "20260430T135012Z"
            / "accepted-env-failures.md"
        )
        assert archive_path.is_file(), f"Expected archive file {archive_path} not found; T14 must produce it"
