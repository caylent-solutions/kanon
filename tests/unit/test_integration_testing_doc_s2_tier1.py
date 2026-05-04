"""Regression-guard tests for the E2-F3-S2 Tier 1 doc-only fixes.

Pins the corrected text in `docs/integration-testing.md` for the six
doc-only Tasks under Story E2-F3-S2:

- T8  RP-abandon-01: `--all` removed from the abandon command (mutually
  exclusive with the positional branch name).
- T9  RP-cherry-pick-01: `cd` into the rp-cherry-pick-01 workspace
  inserted before the cherry-pick command (kanon needs a `.git`
  ancestor in cwd).
- T10 RP-gc-02/03/04: replaced nonexistent flags (`--aggressive`,
  `-a`/`--all`, `--repack-full-clone`) with the real flags
  `--dry-run`, `--yes`, `--repack`.
- T11 RP-init-06: standalone-manifest fixture inlined (no `<include>`
  directive).
- T12 RP-rebase-07: `-s` replaced with `--auto-stash` (the actual
  long-form flag; no short alias exists).
- T13 TC-validate-02: `--repo-root` switched from `MK_MFST` (root-level
  XMLs) to `${KANON_TEST_ROOT}/fixtures/mk19-validate` (repo-specs/-
  prefixed layout the validator expects).

Each test extracts the affected scenario's bash block and asserts the
corrected form is present and the obsolete form is absent. The whole
file is the cheapest reliable validation that the doc was actually
edited as the Task specs required (no live re-run needed for these
purely-doc fixes).
"""

from __future__ import annotations

import pathlib
import re

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _scenario_block(doc: str, heading: str) -> str:
    """Return the body of a `### <heading>` block up to the next `### `."""
    pattern = re.compile(
        r"^### " + re.escape(heading) + r"(?:\b|:|$).*?(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(doc)
    assert match is not None, f"Scenario block '{heading}' not found in {DOC_PATH}"
    return match.group(0)


# ---------------------------------------------------------------------------
# E2-F3-S2-T8: RP-abandon-01 -- drop conflicting --all + branchname combo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT8RPAbandon01:
    def test_abandon_command_does_not_use_all_with_branchname(self) -> None:
        block = _scenario_block(_load_doc(), "RP-abandon-01")
        # The abandon line should be `kanon repo abandon tmp-a` (no --all).
        assert "kanon repo abandon tmp-a --all" not in block, (
            "RP-abandon-01 must not combine `--all` with the positional branch name"
        )
        assert "kanon repo abandon tmp-a\n" in block, "RP-abandon-01 must call `kanon repo abandon tmp-a` (no --all)"

    def test_start_command_keeps_all(self) -> None:
        """The repo-start setup line (separate from abandon) is allowed to use --all."""
        block = _scenario_block(_load_doc(), "RP-abandon-01")
        assert "kanon repo start tmp-a --all" in block


# ---------------------------------------------------------------------------
# E2-F3-S2-T9: RP-cherry-pick-01 -- cd into repo-init'd workspace
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT9RPCherryPick01:
    def test_block_contains_cd_into_workspace(self) -> None:
        block = _scenario_block(_load_doc(), "RP-cherry-pick-01")
        assert 'cd "${KANON_TEST_ROOT}/rp-cherry-pick-01"' in block, (
            "RP-cherry-pick-01 must `cd` into the repo-init'd workspace before cherry-pick"
        )

    def test_cd_appears_before_cherry_pick(self) -> None:
        block = _scenario_block(_load_doc(), "RP-cherry-pick-01")
        cd_idx = block.find('cd "${KANON_TEST_ROOT}/rp-cherry-pick-01"')
        cp_idx = block.find("kanon repo cherry-pick")
        assert cd_idx >= 0 and cp_idx >= 0
        assert cd_idx < cp_idx, "cd into workspace must precede the cherry-pick call"


# ---------------------------------------------------------------------------
# E2-F3-S2-T10: RP-gc-02/03/04 -- replace nonexistent flags
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT10RPGc:
    """Validate that the doc's bash COMMAND LINES (not its explanatory prose)
    no longer invoke the nonexistent gc flags. Prose/Pass-criteria text may
    legitimately mention the removed flag names to explain the change."""

    @staticmethod
    def _gc_command_lines(block: str) -> list[str]:
        """Return only the lines that are bash commands invoking `kanon repo gc`.

        Skips Pass-criteria/explanatory prose. Heuristic: a command line
        appears inside a fenced bash block and starts with the kanon
        invocation (no leading `**Pass`, etc.).
        """
        lines = block.splitlines()
        out: list[str] = []
        in_bash = False
        for line in lines:
            if line.strip().startswith("```bash"):
                in_bash = True
                continue
            if line.strip().startswith("```") and in_bash:
                in_bash = False
                continue
            if in_bash and "kanon repo gc" in line:
                out.append(line)
        return out

    def test_doc_command_lines_do_not_use_aggressive_flag(self) -> None:
        for scenario in ("RP-gc-02", "RP-gc-03", "RP-gc-04"):
            block = _scenario_block(_load_doc(), scenario)
            for cmd in self._gc_command_lines(block):
                assert "--aggressive" not in cmd, f"{scenario} command line uses forbidden flag --aggressive: {cmd!r}"

    def test_doc_command_lines_do_not_use_a_all_flag(self) -> None:
        for scenario in ("RP-gc-02", "RP-gc-03", "RP-gc-04"):
            block = _scenario_block(_load_doc(), scenario)
            for cmd in self._gc_command_lines(block):
                # Detect bare `-a` token (avoid matching `-auto-stash` etc.).
                tokens = cmd.split()
                assert "-a" not in tokens, f"{scenario} command line uses forbidden flag `-a`: {cmd!r}"

    def test_doc_command_lines_do_not_use_repack_full_clone_flag(self) -> None:
        for scenario in ("RP-gc-02", "RP-gc-03", "RP-gc-04"):
            block = _scenario_block(_load_doc(), scenario)
            for cmd in self._gc_command_lines(block):
                assert "--repack-full-clone" not in cmd, (
                    f"{scenario} command line uses forbidden flag --repack-full-clone: {cmd!r}"
                )

    @pytest.mark.parametrize("scenario", ["RP-gc-02", "RP-gc-03", "RP-gc-04"])
    def test_block_has_at_least_one_real_gc_command(self, scenario: str) -> None:
        """Every gc scenario must still exercise `kanon repo gc` with a real flag set."""
        block = _scenario_block(_load_doc(), scenario)
        cmd_lines = self._gc_command_lines(block)
        assert cmd_lines, f"{scenario} must contain at least one `kanon repo gc` command line"
        # At least one of the real flags must appear in the gc invocation.
        real_flags = ("--dry-run", "-n", "--yes", "-y", "--repack")
        for line in cmd_lines:
            assert any(flag in line.split() for flag in real_flags), (
                f"{scenario} gc command must use one of {real_flags}: {line!r}"
            )


# ---------------------------------------------------------------------------
# E2-F3-S2-T11: RP-init-06 standalone manifest -- no <include>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT11RPInit06:
    def test_standalone_manifest_has_no_include(self) -> None:
        block = _scenario_block(_load_doc(), "RP-init-06")
        # The block contains an inlined manifest heredoc; that heredoc must
        # not contain a `<include>` directive.
        assert "<include " not in block and "<include\n" not in block, (
            "RP-init-06 standalone manifest must be self-contained (no <include>)"
        )

    def test_uses_inline_heredoc_not_external_include(self) -> None:
        block = _scenario_block(_load_doc(), "RP-init-06")
        # The fix uses a here-doc-built standalone-manifest.xml.
        assert "STANDALONE" in block or "cat > /tmp/standalone-manifest.xml" in block, (
            "RP-init-06 must construct the standalone manifest inline via heredoc"
        )

    def test_does_not_copy_default_xml_from_manifest_primary(self) -> None:
        block = _scenario_block(_load_doc(), "RP-init-06")
        assert 'cp "${MANIFEST_PRIMARY_DIR}/default.xml"' not in block, (
            "RP-init-06 must not rely on cp of default.xml (file does not exist at MANIFEST_PRIMARY_DIR root)"
        )


# ---------------------------------------------------------------------------
# E2-F3-S2-T12: RP-rebase-07 -- replace -s with --auto-stash
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT12RPRebase07:
    def test_uses_auto_stash_long_flag(self) -> None:
        block = _scenario_block(_load_doc(), "RP-rebase-07")
        assert "kanon repo rebase --auto-stash" in block, "RP-rebase-07 must use the long-form --auto-stash flag"

    def test_does_not_use_short_s_alias(self) -> None:
        block = _scenario_block(_load_doc(), "RP-rebase-07")
        assert "kanon repo rebase -s\n" not in block, "RP-rebase-07 must not use `-s` (no short alias exists)"


# ---------------------------------------------------------------------------
# E2-F3-S2-T13: TC-validate-02 -- use mk19-validate fixture
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestT13TCValidate02:
    def test_repo_root_uses_mk19_validate_fixture(self) -> None:
        block = _scenario_block(_load_doc(), "TC-validate-02")
        assert "fixtures/mk19-validate" in block, (
            "TC-validate-02 must point --repo-root at fixtures/mk19-validate (which has repo-specs/mk19-marketplace.xml)"
        )

    def test_repo_root_does_not_use_mk_mfst(self) -> None:
        block = _scenario_block(_load_doc(), "TC-validate-02")
        # MK_MFST stores XMLs at root (kanon-source layout), not in repo-specs/.
        assert '--repo-root "${MK_MFST}"' not in block, (
            "TC-validate-02 must not point --repo-root at MK_MFST (wrong layout for validate-marketplace)"
        )
