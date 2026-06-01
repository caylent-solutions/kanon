"""Unit tests for lockfile schema migration policy -- T2 (updated for schema v2).

Covers:
  - AC-FUNC-001: forward-incompatible read raises LockfileSchemaError with exact message.
  - AC-FUNC-002: missing-upgrader backward-incompatible read raises LockfileSchemaError.
  - AC-FUNC-003: successful backward-compatible read via registered upgrader chain.
  - AC-FUNC-004: current-schema read is unchanged; no upgrader invoked.
  - AC-FUNC-005: CURRENT_SCHEMA_VERSION exported and equals 2.
  - AC-FUNC-006: _register_upgrader rejects duplicate registrations.
  - AC-TEST-002: fake upgrader registered at setup and unregistered at teardown.
  - AC-CYCLE-001: end-to-end cycle with v0 fixture (v0 -> v1 -> v2 chain).
  - FAIL-FAST: _unregister_upgrader raises KeyError for unregistered (from, to) pairs.
"""

import pytest

from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    LockfileSchemaError,
    _dispatch_migration,
    _register_upgrader,
    _unregister_upgrader,
    read_lockfile,
)
from tests.unit.test_lockfile import _minimal_toml

# ---------------------------------------------------------------------------
# Module-level constant re-exported for test readability
# ---------------------------------------------------------------------------

_VALID_SHA40 = "a" * 40
# kanon_hash uses the sha256:-prefixed form (spec Rule 1a, 71 chars total).
_VALID_KANON_HASH = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# AC-FUNC-005: CURRENT_SCHEMA_VERSION exported and equals 2
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_current_schema_version_exported_and_equals_2():
    """CURRENT_SCHEMA_VERSION is exported from lockfile module and equals 2."""
    assert CURRENT_SCHEMA_VERSION == 2


# ---------------------------------------------------------------------------
# AC-FUNC-001: Forward-incompatible read (schema_version > current)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("future_version", [3, 99])
def test_forward_incompatible_raises_schema_error_exact_message(future_version, tmp_path):
    """schema_version > CURRENT_SCHEMA_VERSION raises LockfileSchemaError with exact message.

    Message format: "lockfile schema v<N> written by newer kanon; upgrade kanon-cli."
    """
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(future_version))
    with pytest.raises(LockfileSchemaError) as exc_info:
        read_lockfile(p)
    assert str(exc_info.value) == (f"lockfile schema v{future_version} written by newer kanon; upgrade kanon-cli.")


# ---------------------------------------------------------------------------
# AC-FUNC-002: Missing-upgrader backward-incompatible read
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backward_incompatible_no_upgrader_raises_schema_error(tmp_path):
    """schema_version < CURRENT_SCHEMA_VERSION with no registered upgrader raises LockfileSchemaError.

    Message: "no upgrade path from lockfile schema v<N> to v<current>; this is a kanon bug; please report."
    """
    # Version 0 has no registered upgrader -- verifying missing-upgrader path.
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(0))
    with pytest.raises(LockfileSchemaError) as exc_info:
        read_lockfile(p)
    assert str(exc_info.value) == (
        f"no upgrade path from lockfile schema v0 to v{CURRENT_SCHEMA_VERSION}; this is a kanon bug; please report."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-003 / AC-TEST-002: Successful backward-compatible read with fake upgrader
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuccessfulUpgradeViaFakeUpgrader:
    """Tests for backward-compatible read via a registered v0-to-v1 upgrader.

    The v1->v2 upgrader is already registered in production (for the real migration).
    The fake v0->v1 upgrader is registered at setup and unregistered at teardown
    so registry state does not leak across tests (AC-TEST-002).

    Since CURRENT_SCHEMA_VERSION is now 2, a v0 lockfile goes through the chain:
    v0 -> v1 (fake upgrader) -> v2 (real upgrader). The final schema_version is 2.
    """

    def setup_method(self):
        """Register a fake v0-to-v1 upgrader that promotes schema_version and adds required fields."""

        def _fake_v0_to_v1(data: dict) -> dict:
            """Upgrade a v0 dict to schema v1 by adding/updating required fields."""
            upgraded = dict(data)
            upgraded["schema_version"] = 1
            # v0 fixture omits generated_at; the upgrader fills it in.
            upgraded.setdefault("generated_at", "2026-01-01T00:00:00Z")
            upgraded.setdefault("generator", "kanon-cli/1.4.0")
            upgraded.setdefault("kanon_hash", _VALID_KANON_HASH)
            if "catalog" not in upgraded:
                upgraded["catalog"] = {
                    "source": "https://example.com/catalog.git@main",
                    "url": "https://example.com/catalog.git",
                    "revision_spec": "main",
                    "resolved_ref": "refs/heads/main",
                    "resolved_sha": _VALID_SHA40,
                }
            return upgraded

        _register_upgrader(0, 1, _fake_v0_to_v1)

    def teardown_method(self):
        """Unregister the fake upgrader so registry state does not leak."""
        _unregister_upgrader(0, 1)

    def test_successful_upgrade_returns_current_schema_lockfile(self, tmp_path):
        """read_lockfile upgrades a v0 fixture through v1 to CURRENT_SCHEMA_VERSION via upgrader chain."""
        p = tmp_path / "kanon.lock"
        p.write_text(_minimal_toml(0))
        lf = read_lockfile(p)
        assert lf.schema_version == CURRENT_SCHEMA_VERSION
        assert lf.schema_version == 2

    def test_upgrader_register_and_unregister_work_as_pair(self, tmp_path):
        """Registering and unregistering the upgrader leaves registry clean."""
        p = tmp_path / "kanon.lock"
        p.write_text(_minimal_toml(0))
        # Should succeed (upgrader registered in setup_method; v1->v2 is real upgrader)
        lf = read_lockfile(p)
        assert lf.schema_version == CURRENT_SCHEMA_VERSION
        # After teardown_method unregisters (0,1), a subsequent call should raise (no v0->v1 path).
        # We verify via a direct unregister + re-read to simulate teardown.
        _unregister_upgrader(0, 1)
        with pytest.raises(LockfileSchemaError):
            read_lockfile(p)
        # Re-register so teardown_method's _unregister_upgrader call does not raise.
        _register_upgrader(0, 1, lambda d: {**d, "schema_version": 1})

    def test_no_upgrader_invoked_for_current_schema(self, tmp_path):
        """No upgrader function is called when schema_version == CURRENT_SCHEMA_VERSION (AC-FUNC-004).

        Registers a spy upgrader for a hypothetical v2->v3 step (not used here),
        then reads a v2 lockfile and asserts the spy was never called.
        """
        invocations: list[int] = []

        def _spy_upgrader(data: dict) -> dict:
            invocations.append(1)
            return data

        # Register a spy at v2->v3 to detect any accidental upgrader dispatch.
        _register_upgrader(2, 3, _spy_upgrader)
        try:
            p = tmp_path / "kanon.lock"
            p.write_text(_minimal_toml(2))
            lf = read_lockfile(p)
            assert lf.schema_version == 2
            # Spy must not have been called -- current-schema read skips migration.
            assert invocations == []
        finally:
            _unregister_upgrader(2, 3)


# ---------------------------------------------------------------------------
# AC-FUNC-004: Current-schema read is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_current_schema_read_unchanged(tmp_path):
    """read_lockfile with schema_version == CURRENT_SCHEMA_VERSION works as expected."""
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(CURRENT_SCHEMA_VERSION))
    lf = read_lockfile(p)
    assert lf.schema_version == CURRENT_SCHEMA_VERSION
    assert lf.generated_at == "2026-01-01T00:00:00Z"
    assert lf.generator == "kanon-cli/1.4.0"
    assert lf.kanon_hash == _VALID_KANON_HASH


# ---------------------------------------------------------------------------
# AC-FUNC-006: _register_upgrader rejects duplicate registrations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterUpgraderDuplicateRejection:
    """_register_upgrader raises an error for duplicate (from, to) pairs."""

    def setup_method(self):
        """Register a fake upgrader for testing duplicate rejection."""
        _register_upgrader(0, 1, lambda d: d)

    def teardown_method(self):
        """Remove the test upgrader."""
        _unregister_upgrader(0, 1)

    def test_duplicate_registration_raises_value_error_naming_the_pair(self):
        """_register_upgrader raises ValueError naming both version numbers when (from, to) is already registered."""
        with pytest.raises(ValueError) as exc_info:
            _register_upgrader(0, 1, lambda d: d)
        err = str(exc_info.value)
        assert "0" in err
        assert "1" in err


# ---------------------------------------------------------------------------
# FAIL-FAST: non-advancing upgrader detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNonAdvancingUpgraderDetected:
    """_dispatch_migration raises LockfileSchemaError when an upgrader does not advance schema_version."""

    def setup_method(self):
        """Register a broken upgrader for (0, 1) that does not change schema_version."""

        def _non_advancing(data: dict) -> dict:
            # Intentionally returns the data unmodified -- schema_version stays at 0.
            return dict(data)

        _register_upgrader(0, 1, _non_advancing)

    def teardown_method(self):
        """Remove the broken upgrader to keep registry clean."""
        _unregister_upgrader(0, 1)

    def test_non_advancing_upgrader_raises_schema_error(self):
        """_dispatch_migration raises LockfileSchemaError with exact message when upgrader does not advance schema_version."""
        data = {"schema_version": 0}
        with pytest.raises(LockfileSchemaError) as exc_info:
            _dispatch_migration(data)
        err = str(exc_info.value)
        assert "upgrader for schema v0->v1 did not advance schema_version" in err
        assert "returned 0" in err
        assert "this is a kanon bug" in err
        assert "please report" in err


# ---------------------------------------------------------------------------
# AC-CYCLE-001: End-to-end cycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndToEndMigrationCycle:
    """AC-CYCLE-001: Full read-upgrade-assert-teardown cycle with a v0 fixture.

    The v0->v1 upgrader is registered by the test; the v1->v2 upgrader is the
    real one already in the registry.  The chain v0->v1->v2 produces a v2 Lockfile.
    """

    def test_full_cycle(self, tmp_path):
        """Write v0 fixture; register v0->v1 upgrader; read and assert v2; remove; assert raises."""
        # Step 1: Write a v0 TOML fixture to tmp_path.
        v0_fixture = tmp_path / "kanon.lock"
        v0_fixture.write_text(_minimal_toml(0))

        # Step 2: Register a fake v0-to-v1 upgrader.
        def _v0_to_v1(data: dict) -> dict:
            upgraded = dict(data)
            upgraded["schema_version"] = 1
            upgraded.setdefault("generated_at", "2026-01-01T00:00:00Z")
            upgraded.setdefault("generator", "kanon-cli/1.4.0")
            upgraded.setdefault("kanon_hash", _VALID_KANON_HASH)
            if "catalog" not in upgraded:
                upgraded["catalog"] = {
                    "source": "https://example.com/catalog.git@main",
                    "url": "https://example.com/catalog.git",
                    "revision_spec": "main",
                    "resolved_ref": "refs/heads/main",
                    "resolved_sha": _VALID_SHA40,
                }
            return upgraded

        _register_upgrader(0, 1, _v0_to_v1)

        try:
            # Step 3: Call read_lockfile; assert the returned object is a v2 Lockfile
            # (v0->v1 via fake upgrader, v1->v2 via the real upgrader).
            lf = read_lockfile(v0_fixture)
            assert lf.schema_version == CURRENT_SCHEMA_VERSION
            assert lf.schema_version == 2
            assert lf.kanon_hash == _VALID_KANON_HASH
            assert lf.catalog.revision_spec == "main"
            # v2 marketplace fields are defaulted by the real v1->v2 upgrader.
            assert lf.marketplace_registered is False
            assert lf.marketplace_dir == ""
        finally:
            # Step 4: Remove the upgrader.
            _unregister_upgrader(0, 1)

        # Step 5: A second read_lockfile on the same file raises LockfileSchemaError
        # (no v0->v1 path anymore).
        with pytest.raises(LockfileSchemaError) as exc_info:
            read_lockfile(v0_fixture)
        assert "no upgrade path from lockfile schema v0" in str(exc_info.value)


# ---------------------------------------------------------------------------
# FAIL-FAST: _unregister_upgrader raises KeyError for missing registrations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnregisterUpgraderFailFast:
    """_unregister_upgrader raises KeyError when the (from, to) pair is not registered."""

    def test_unregister_missing_pair_raises_key_error(self):
        """_unregister_upgrader raises KeyError for an unregistered (from, to) pair.

        Fail-fast: silently ignoring a missing key would hide teardown bugs
        in tests and misuse of the registry in production.
        """
        with pytest.raises(KeyError):
            _unregister_upgrader(99, 100)

    def test_unregister_missing_pair_key_error_names_versions(self):
        """KeyError message from _unregister_upgrader identifies the missing (from, to) pair."""
        with pytest.raises(KeyError) as exc_info:
            _unregister_upgrader(42, 43)
        err = str(exc_info.value)
        assert "42" in err
        assert "43" in err

    def test_unregister_registered_pair_does_not_raise(self):
        """_unregister_upgrader succeeds for a previously registered (from, to) pair."""
        _register_upgrader(88, 89, lambda d: d)
        # Must not raise
        _unregister_upgrader(88, 89)
