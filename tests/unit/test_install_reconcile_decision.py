"""Unit tests for the npm-like reconcile decision helpers in ``core/install.py``.

Bug guard: ``install-orphan-rescue-crash-and-lock-corruption``.

Two pure decision functions are exercised:

- ``_strict_lock_drift_error`` -- on ``LOCKFILE_HASH_MISMATCH`` with ``--strict-lock``,
  returns ``OrphanedLockEntryError`` when the drift is *purely* orphan removals,
  otherwise ``KanonHashMismatchError`` (an addition and/or a changed spec is
  present).  Strict-lock NEVER mutates the lockfile, so this helper only decides
  which clean error to raise.

- ``_should_replay_source`` -- per-source replay-vs-resolve selection: replay
  (preserve the locked SHA) iff the source exists in the old lock AND the
  ``.kanon`` revision spec equals the locked entry's recorded ``revision_spec``;
  otherwise resolve fresh (new source or changed spec).
"""

from __future__ import annotations

import pytest

from kanon_cli.core.install import (
    KanonHashMismatchError,
    OrphanedLockEntryError,
    _should_replay_source,
    _strict_lock_drift_error,
)
from kanon_cli.core.lockfile import CatalogBlock, Lockfile, SourceEntry


_SHA = "a" * 40
_HASH_OLD = "sha256:" + "1" * 64
_HASH_NEW = "sha256:" + "2" * 64


def _entry(name: str, revision_spec: str, sha: str = _SHA) -> SourceEntry:
    return SourceEntry(
        name=name,
        url=f"https://git.example.com/{name}.git",
        revision_spec=revision_spec,
        resolved_ref=f"refs/tags/{revision_spec}",
        resolved_sha=sha,
        path="manifest.xml",
    )


def _lockfile(*entries: SourceEntry) -> Lockfile:
    return Lockfile(
        schema_version=1,
        generated_at="2026-01-01T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash=_HASH_OLD,
        catalog=CatalogBlock(
            source="https://git.example.com/catalog.git@main",
            url="https://git.example.com/catalog.git",
            revision_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha=_SHA,
        ),
        sources=list(entries),
    )


@pytest.mark.unit
class TestStrictLockDriftError:
    """``_strict_lock_drift_error`` picks the correct clean error for --strict-lock."""

    def test_pure_orphan_removal_returns_orphan_error(self) -> None:
        """Lock has alpha+beta; .kanon has only alpha -> orphan-only -> OrphanedLockEntryError."""
        lf = _lockfile(_entry("alpha", "==1.0.0"), _entry("beta", "==1.0.0"))
        err = _strict_lock_drift_error(lf, ["alpha"], computed_hash=_HASH_NEW)
        assert isinstance(err, OrphanedLockEntryError)
        assert "beta" in str(err)

    def test_addition_returns_hash_mismatch_error(self) -> None:
        """Lock has alpha; .kanon adds beta (no orphan) -> KanonHashMismatchError."""
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        err = _strict_lock_drift_error(lf, ["alpha", "beta"], computed_hash=_HASH_NEW)
        assert isinstance(err, KanonHashMismatchError)
        assert "--refresh-lock" in str(err)
        assert err.lockfile_hash == _HASH_OLD
        assert err.computed_hash == _HASH_NEW

    def test_orphan_plus_addition_returns_hash_mismatch_error(self) -> None:
        """Lock has alpha; .kanon removes alpha and adds beta -> orphan + addition -> hash mismatch."""
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        err = _strict_lock_drift_error(lf, ["beta"], computed_hash=_HASH_NEW)
        assert isinstance(err, KanonHashMismatchError)

    def test_changed_spec_only_returns_hash_mismatch_error(self) -> None:
        """Lock has alpha==1.0.0; .kanon changes alpha to ==2.0.0 (no orphan/add) -> hash mismatch.

        Spec-change drift cannot be expressed by the source-name set alone, so a
        same-name set is NOT enough to classify as orphan-only; the helper must
        treat any non-orphan drift as a hash mismatch.
        """
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        err = _strict_lock_drift_error(lf, ["alpha"], computed_hash=_HASH_NEW)
        assert isinstance(err, KanonHashMismatchError)


@pytest.mark.unit
class TestShouldReplaySource:
    """``_should_replay_source`` decides replay (preserve SHA) vs resolve fresh."""

    def test_unchanged_source_replays(self) -> None:
        """Source in lock with identical revision spec -> replay."""
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        assert _should_replay_source("alpha", "==1.0.0", lf) is True

    def test_new_source_resolves(self) -> None:
        """Source absent from lock (newly added) -> resolve fresh."""
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        assert _should_replay_source("beta", "==1.0.0", lf) is False

    def test_changed_spec_resolves(self) -> None:
        """Source in lock but .kanon revision spec differs -> resolve fresh."""
        lf = _lockfile(_entry("alpha", "==1.0.0"))
        assert _should_replay_source("alpha", "==2.0.0", lf) is False

    def test_no_lockfile_resolves(self) -> None:
        """No existing lockfile -> resolve fresh."""
        assert _should_replay_source("alpha", "==1.0.0", None) is False
