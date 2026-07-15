"""Unit tests for reconcile_declared_installed and SourceReconciliation.

Covers the non-raising declared-vs-installed partition that ``kanon list``
consumes and that ``check_lockfile_consistency`` raises on: installed (the
intersection), not-installed (declared minus lock), orphaned (lock minus
declared), duplicate-alias detection, and per-alias ref-spec mismatch detection.
Also pins that the refactored ``check_lockfile_consistency`` still raises
identically so the shared helper did not regress the install/validate gate.
"""

from __future__ import annotations

import pytest

from kanon_cli.core.lockfile import (
    Lockfile,
    LockfileConsistencyError,
    SourceEntry,
    SourceReconciliation,
    check_lockfile_consistency,
    reconcile_declared_installed,
)


def _lock(*aliases_refs: tuple[str, str]) -> Lockfile:
    """Build a Lockfile whose sources are the given (alias, ref_spec) pairs."""
    sources = [
        SourceEntry(
            alias=alias,
            name=alias,
            url=f"https://example.com/{alias}",
            ref_spec=ref,
            resolved_ref=ref,
            resolved_sha="a" * 40,
            path=alias,
        )
        for alias, ref in aliases_refs
    ]
    return Lockfile(
        schema_version=5,
        generated_at="t",
        generator="g",
        kanon_hash="sha256:" + "0" * 64,
        sources=sources,
    )


@pytest.mark.unit
class TestReconcileDeclaredInstalled:
    """The pure partition returned by reconcile_declared_installed."""

    def test_all_installed(self) -> None:
        """Aliases in both files land in installed, nothing else."""
        rec = reconcile_declared_installed(["a", "b"], {"a": "1", "b": "2"}, _lock(("a", "1"), ("b", "2")))
        assert rec.installed == ["a", "b"]
        assert rec.not_installed == []
        assert rec.orphaned == []
        assert rec.duplicates == []
        assert rec.ref_mismatches == []

    def test_not_installed(self) -> None:
        """A declared alias absent from the lock is not-installed."""
        rec = reconcile_declared_installed(["a", "b"], {"a": "1", "b": "2"}, _lock(("a", "1")))
        assert rec.installed == ["a"]
        assert rec.not_installed == ["b"]
        assert rec.orphaned == []

    def test_orphaned(self) -> None:
        """A lock alias no longer declared is orphaned."""
        rec = reconcile_declared_installed(["a"], {"a": "1"}, _lock(("a", "1"), ("z", "9")))
        assert rec.installed == ["a"]
        assert rec.orphaned == ["z"]
        assert rec.not_installed == []

    def test_mixed(self) -> None:
        """All three partitions populate simultaneously."""
        rec = reconcile_declared_installed(["a", "b"], {"a": "1", "b": "2"}, _lock(("a", "1"), ("z", "9")))
        assert rec.installed == ["a"]
        assert rec.not_installed == ["b"]
        assert rec.orphaned == ["z"]

    def test_outputs_sorted(self) -> None:
        """Each partition list is sorted regardless of declaration order."""
        rec = reconcile_declared_installed(["c", "a", "b"], {"c": "1", "a": "1", "b": "1"}, _lock())
        assert rec.not_installed == ["a", "b", "c"]

    def test_duplicates_detected(self) -> None:
        """A repeated declared alias is reported in duplicates (first-seen order)."""
        rec = reconcile_declared_installed(["a", "a", "b"], {"a": "1", "b": "2"}, _lock(("a", "1"), ("b", "2")))
        assert rec.duplicates == ["a"]

    def test_ref_mismatch_detected(self) -> None:
        """A shared alias whose declared ref differs from the lock is a mismatch."""
        rec = reconcile_declared_installed(["a"], {"a": "2"}, _lock(("a", "1")))
        assert rec.ref_mismatches == ["a"]
        assert rec.installed == ["a"]

    def test_empty_declared_all_orphan(self) -> None:
        """With nothing declared, every lock entry is orphaned."""
        rec = reconcile_declared_installed([], {}, _lock(("a", "1")))
        assert rec.orphaned == ["a"]
        assert rec.installed == []
        assert rec.not_installed == []

    def test_returns_dataclass(self) -> None:
        """The result is a SourceReconciliation instance."""
        rec = reconcile_declared_installed([], {}, _lock())
        assert isinstance(rec, SourceReconciliation)


@pytest.mark.unit
class TestConsistencyStillRaisesIdentically:
    """The refactored check_lockfile_consistency must behave as before."""

    def test_consistent_pair_does_not_raise(self) -> None:
        """A consistent pair passes silently."""
        check_lockfile_consistency(["a"], {"a": "1"}, _lock(("a", "1")))

    def test_duplicate_raises(self) -> None:
        """A duplicate alias raises the duplicate-alias error."""
        with pytest.raises(LockfileConsistencyError, match="duplicate source alias"):
            check_lockfile_consistency(["a", "a"], {"a": "1"}, _lock(("a", "1")))

    def test_alias_drift_raises(self) -> None:
        """An alias-set difference raises the alias-set error."""
        with pytest.raises(LockfileConsistencyError, match="alias sets differ"):
            check_lockfile_consistency(["a", "b"], {"a": "1", "b": "2"}, _lock(("a", "1")))

    def test_ref_spec_drift_raises(self) -> None:
        """A per-alias ref-spec difference raises the ref-spec error."""
        with pytest.raises(LockfileConsistencyError, match="ref-specs differ"):
            check_lockfile_consistency(["a"], {"a": "2"}, _lock(("a", "1")))
