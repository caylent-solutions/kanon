"""Unit tests for OrphanedLockEntryError structured message format (DEFECT-011).

Covers spec Section 4 E26:
- AC-FUNC-001: StrictLockOrphanError (OrphanedLockEntryError) subclasses InstallError
  and carries orphan_names tuple attribute.
- AC-FUNC-003: Stderr rendering enumerates each orphan and the 3-option remediation.
- AC-FUNC-004: Singular/plural count prefix is grammatically correct.
- AC-FUNC-005: Format-string templates are module-level constants; no magic strings
  at the raise site.
"""

from __future__ import annotations

import pytest

from kanon_cli.core.install import (
    InstallError,
    OrphanedLockEntryError,
    _ORPHAN_CONTEXT,
    _ORPHAN_HEADER_PLURAL,
    _ORPHAN_HEADER_SINGULAR,
    _ORPHAN_REMEDIATION,
)


@pytest.mark.unit
class TestOrphanedLockEntryErrorStructure:
    """OrphanedLockEntryError subclasses InstallError and stores orphan_names."""

    def test_is_install_error_subclass(self) -> None:
        """OrphanedLockEntryError is an InstallError (and therefore an Exception)."""
        err = OrphanedLockEntryError(orphaned_names=["alpha"])
        assert isinstance(err, InstallError)
        assert isinstance(err, Exception)

    def test_orphaned_names_attribute_is_tuple(self) -> None:
        """orphaned_names attribute is a tuple of strings."""
        err = OrphanedLockEntryError(orphaned_names=["beta", "alpha"])
        assert isinstance(err.orphaned_names, tuple)

    def test_orphaned_names_sorted(self) -> None:
        """Names are stored sorted regardless of input order."""
        err = OrphanedLockEntryError(orphaned_names=["gamma", "alpha", "beta"])
        assert err.orphaned_names == ("alpha", "beta", "gamma")

    def test_orphaned_names_deduplicated(self) -> None:
        """Duplicate names are deduplicated before storage."""
        err = OrphanedLockEntryError(orphaned_names=["alpha", "alpha", "beta"])
        assert err.orphaned_names == ("alpha", "beta")

    def test_single_name(self) -> None:
        """A single orphan name is accepted and stored."""
        err = OrphanedLockEntryError(orphaned_names=["solo"])
        assert err.orphaned_names == ("solo",)

    def test_empty_raises_value_error(self) -> None:
        """Empty orphaned_names is a logic error: ValueError is raised."""
        with pytest.raises(ValueError, match="at least one orphan name"):
            OrphanedLockEntryError(orphaned_names=[])


@pytest.mark.unit
class TestOrphanedLockEntryErrorRemediation:
    """Error message enumerates each orphan name and the 3-option remediation."""

    def test_single_orphan_name_in_message(self) -> None:
        """The orphan source name appears in the rendered error string."""
        err = OrphanedLockEntryError(orphaned_names=["source_delta"])
        assert "source_delta" in str(err)

    def test_all_orphan_names_in_message(self) -> None:
        """Every orphan name appears in the rendered error string."""
        err = OrphanedLockEntryError(orphaned_names=["source_alpha", "source_bravo"])
        rendered = str(err)
        assert "source_alpha" in rendered
        assert "source_bravo" in rendered

    def test_remediation_option_auto_prune(self) -> None:
        """Remediation mentions running kanon install without --strict-lock."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert "--strict-lock" in str(err)

    def test_remediation_option_restore_triples(self) -> None:
        """Remediation mentions restoring KANON_SOURCE_<name>_* triples."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert "KANON_SOURCE_<name>_" in str(err)

    def test_remediation_option_kanon_remove(self) -> None:
        """Remediation mentions 'kanon remove <name>' as a cleanup path."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert "kanon remove" in str(err)

    def test_context_line_present(self) -> None:
        """The context line explaining the absence of matching triples is present."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert _ORPHAN_CONTEXT in str(err)

    def test_remediation_block_present(self) -> None:
        """The full remediation block text is present in the error string."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert "Remediation:" in str(err)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("orphan_names", "expected_phrase"),
    [
        (["one_source"], "1 orphaned lockfile entry:"),
        (["source_a", "source_b"], "2 orphaned lockfile entries:"),
        (["x", "y", "z"], "3 orphaned lockfile entries:"),
    ],
    ids=["singular", "two-plural", "three-plural"],
)
class TestOrphanedLockEntryErrorSingularPlural:
    """Singular/plural count prefix is grammatically correct in the error message."""

    def test_count_prefixed_noun_phrase(self, orphan_names: list[str], expected_phrase: str) -> None:
        """The count-prefixed noun phrase matches the number of orphans."""
        err = OrphanedLockEntryError(orphaned_names=orphan_names)
        assert expected_phrase in str(err)


@pytest.mark.unit
class TestOrphanedLockEntryErrorConstants:
    """Message templates are module-level constants, not inline string literals."""

    def test_singular_header_constant_used(self) -> None:
        """The singular header constant is used for a single orphan."""
        err = OrphanedLockEntryError(orphaned_names=["only_one"])
        rendered = str(err)
        expected_start = _ORPHAN_HEADER_SINGULAR.format(count=1, names="only_one")
        assert rendered.startswith(expected_start)

    def test_plural_header_constant_used(self) -> None:
        """The plural header constant is used for multiple orphans."""
        err = OrphanedLockEntryError(orphaned_names=["first", "second"])
        rendered = str(err)
        expected_start = _ORPHAN_HEADER_PLURAL.format(count=2, names="first, second")
        assert rendered.startswith(expected_start)

    def test_context_constant_present(self) -> None:
        """The _ORPHAN_CONTEXT constant appears verbatim in the error string."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert _ORPHAN_CONTEXT in str(err)

    def test_remediation_constant_present(self) -> None:
        """The _ORPHAN_REMEDIATION constant appears verbatim in the error string."""
        err = OrphanedLockEntryError(orphaned_names=["ghost"])
        assert _ORPHAN_REMEDIATION in str(err)
