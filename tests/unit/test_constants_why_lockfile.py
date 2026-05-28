"""Unit tests for WHY_SCOPE_TOP_LEVEL and WHY_SCOPE_TRANSITIVE constants.

Covers AC-FUNC-001: constants.py defines WHY_SCOPE_TOP_LEVEL and
WHY_SCOPE_TRANSITIVE; no inline string literals for these tokens appear in
commands/why.py.

These tests are expected to FAIL (RED) against code that has not yet defined
the constants, and PASS (GREEN) after the constants are added.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from kanon_cli import constants


@pytest.mark.unit
class TestWhyScopeConstants:
    """Verify that WHY_SCOPE_TOP_LEVEL and WHY_SCOPE_TRANSITIVE are defined
    in kanon_cli.constants with the correct string values."""

    def test_why_scope_top_level_is_defined(self) -> None:
        """WHY_SCOPE_TOP_LEVEL must exist on the constants module."""
        assert hasattr(constants, "WHY_SCOPE_TOP_LEVEL"), "WHY_SCOPE_TOP_LEVEL is not defined in kanon_cli.constants"

    def test_why_scope_transitive_is_defined(self) -> None:
        """WHY_SCOPE_TRANSITIVE must exist on the constants module."""
        assert hasattr(constants, "WHY_SCOPE_TRANSITIVE"), "WHY_SCOPE_TRANSITIVE is not defined in kanon_cli.constants"

    def test_why_scope_top_level_value(self) -> None:
        """WHY_SCOPE_TOP_LEVEL must equal 'top_level'."""
        assert constants.WHY_SCOPE_TOP_LEVEL == "top_level", (
            f"Expected WHY_SCOPE_TOP_LEVEL == 'top_level', got {constants.WHY_SCOPE_TOP_LEVEL!r}"
        )

    def test_why_scope_transitive_value(self) -> None:
        """WHY_SCOPE_TRANSITIVE must equal 'transitive'."""
        assert constants.WHY_SCOPE_TRANSITIVE == "transitive", (
            f"Expected WHY_SCOPE_TRANSITIVE == 'transitive', got {constants.WHY_SCOPE_TRANSITIVE!r}"
        )

    def test_scope_values_are_distinct(self) -> None:
        """WHY_SCOPE_TOP_LEVEL and WHY_SCOPE_TRANSITIVE must be different values."""
        assert constants.WHY_SCOPE_TOP_LEVEL != constants.WHY_SCOPE_TRANSITIVE, (
            "WHY_SCOPE_TOP_LEVEL and WHY_SCOPE_TRANSITIVE must have distinct values "
            "so that scope-tagging logic can distinguish the two classes of entries"
        )

    def test_scope_values_are_strings(self) -> None:
        """Both scope constants must be plain str instances."""
        assert isinstance(constants.WHY_SCOPE_TOP_LEVEL, str), (
            f"WHY_SCOPE_TOP_LEVEL must be str, got {type(constants.WHY_SCOPE_TOP_LEVEL)}"
        )
        assert isinstance(constants.WHY_SCOPE_TRANSITIVE, str), (
            f"WHY_SCOPE_TRANSITIVE must be str, got {type(constants.WHY_SCOPE_TRANSITIVE)}"
        )


@pytest.mark.unit
class TestWhyScopeConstantsNoInlineLiterals:
    """Verify that no inline string literals for the scope tokens appear in
    commands/why.py (AC-FUNC-001, CLAUDE.md NO HARD-CODED VALUES).

    The constants WHY_SCOPE_TOP_LEVEL ('top_level') and WHY_SCOPE_TRANSITIVE
    ('transitive') must be referenced exclusively through the constants module;
    they must not appear as bare string literals inside why.py.
    """

    @pytest.fixture
    def why_py_source(self) -> str:
        """Read the source of commands/why.py for inspection."""
        src_root = pathlib.Path(__file__).parent.parent.parent / "src" / "kanon_cli"
        why_path = src_root / "commands" / "why.py"
        assert why_path.exists(), f"commands/why.py not found at {why_path}"
        return why_path.read_text(encoding="utf-8")

    def test_no_inline_top_level_literal(self, why_py_source: str) -> None:
        """'top_level' must not appear as a bare string literal in commands/why.py.

        Bare string literals are detected as quoted occurrences: 'top_level' or
        "top_level" that are NOT part of an import statement or comment.
        """
        # Remove comment lines to avoid false negatives for documented constants.
        non_comment_lines = [line for line in why_py_source.splitlines() if not line.lstrip().startswith("#")]
        non_comment_source = "\n".join(non_comment_lines)
        # Pattern: quoted 'top_level' or "top_level" outside import statements.
        literal_pattern = re.compile(r"""(?<!\w)['"](top_level)['"]\s*(?!.*\bimport\b)""")
        matches = literal_pattern.findall(non_comment_source)
        assert not matches, (
            "Found bare 'top_level' string literal(s) in commands/why.py. "
            "Use WHY_SCOPE_TOP_LEVEL from constants instead. "
            f"Matched {len(matches)} occurrence(s)."
        )

    def test_no_inline_transitive_literal(self, why_py_source: str) -> None:
        """'transitive' must not appear as a bare string literal in commands/why.py.

        Same approach as test_no_inline_top_level_literal but for 'transitive'.
        """
        non_comment_lines = [line for line in why_py_source.splitlines() if not line.lstrip().startswith("#")]
        non_comment_source = "\n".join(non_comment_lines)
        literal_pattern = re.compile(r"""(?<!\w)['"](transitive)['"]\s*(?!.*\bimport\b)""")
        matches = literal_pattern.findall(non_comment_source)
        assert not matches, (
            "Found bare 'transitive' string literal(s) in commands/why.py. "
            "Use WHY_SCOPE_TRANSITIVE from constants instead. "
            f"Matched {len(matches)} occurrence(s)."
        )

    def test_why_imports_scope_constants(self, why_py_source: str) -> None:
        """commands/why.py must import WHY_SCOPE_TOP_LEVEL and WHY_SCOPE_TRANSITIVE."""
        assert "WHY_SCOPE_TOP_LEVEL" in why_py_source, (
            "commands/why.py does not import or reference WHY_SCOPE_TOP_LEVEL"
        )
        assert "WHY_SCOPE_TRANSITIVE" in why_py_source, (
            "commands/why.py does not import or reference WHY_SCOPE_TRANSITIVE"
        )
