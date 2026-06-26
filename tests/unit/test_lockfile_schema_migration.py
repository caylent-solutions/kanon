"""Unit tests for lockfile schema migration policy -- updated for schema v5 (FLAG-C).

Schema v5 (spec Section 5.2, Section 13 FLAG-C) is the latest breaking major:
``read_lockfile`` fails fast on any older schema (v1, v2, v3, v4) with an actionable
regenerate error, and no silent upgrader to v5 is registered.  The migration registry
(``_register_upgrader`` / ``_unregister_upgrader`` / ``_dispatch_migration``) remains the
documented extension point for any future NON-breaking bump and is exercised here directly.

Covers:
  - CURRENT_SCHEMA_VERSION exported and equals 5.
  - Forward-incompatible read (schema_version > current) raises LockfileSchemaError.
  - Older-schema read (schema_version < current) is a hard fail-fast regenerate.
  - _dispatch_migration walks a registered upgrader chain to the current version.
  - _dispatch_migration raises when no upgrader exists for a required step.
  - _register_upgrader rejects duplicate registrations.
  - _dispatch_migration detects a non-advancing upgrader.
  - _unregister_upgrader raises KeyError for unregistered (from, to) pairs.
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


_VALID_SHA40 = "a" * 40

_VALID_KANON_HASH = "sha256:" + "a" * 64


@pytest.mark.unit
def test_current_schema_version_exported_and_equals_5():
    """CURRENT_SCHEMA_VERSION is exported from lockfile module and equals 5."""
    assert CURRENT_SCHEMA_VERSION == 5


@pytest.mark.unit
@pytest.mark.parametrize("future_version", [6, 99])
def test_forward_incompatible_raises_schema_error_exact_message(future_version, tmp_path):
    """schema_version > CURRENT_SCHEMA_VERSION raises LockfileSchemaError with exact message.

    Message format: "lockfile schema v<N> written by newer kanon; upgrade kanon-cli."
    """
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(future_version))
    with pytest.raises(LockfileSchemaError) as exc_info:
        read_lockfile(p)
    assert str(exc_info.value) == (f"lockfile schema v{future_version} written by newer kanon; upgrade kanon-cli.")


@pytest.mark.unit
@pytest.mark.parametrize("old_version", [1, 2, 3, 4])
def test_older_schema_hard_fails_regenerate(old_version, tmp_path):
    """schema_version < CURRENT_SCHEMA_VERSION fails fast with the actionable regenerate error.

    Schema v5 is the latest breaking major: there is no silent upgrader, so an older lock
    (v4 included) must raise LockfileSchemaError naming the offending version and
    instructing the operator to regenerate via 'kanon add' / 'kanon install'.
    """
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(old_version))
    with pytest.raises(LockfileSchemaError) as exc_info:
        read_lockfile(p)
    err = str(exc_info.value)
    assert f"v{old_version}" in err
    assert "kanon add" in err
    assert "kanon install" in err

    assert "kanon bug" not in err


@pytest.mark.unit
def test_v3_read_does_not_dispatch_migration(tmp_path, monkeypatch):
    """read_lockfile does not invoke _dispatch_migration for an older schema (no silent upgrade)."""
    import kanon_cli.core.lockfile as lockfile_module

    called: list[int] = []

    def _spy_dispatch(data):
        called.append(1)
        return data

    monkeypatch.setattr(lockfile_module, "_dispatch_migration", _spy_dispatch)
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(3))
    with pytest.raises(LockfileSchemaError):
        read_lockfile(p)
    assert called == [], "an older schema must fail fast before the migration walker is reached"


@pytest.mark.unit
class TestDispatchMigrationChain:
    """_dispatch_migration advances a raw dict through registered (N, N+1) upgraders."""

    def setup_method(self):
        """Register a fake chain that advances a v0 dict up to the current schema."""

        def _make_step(target: int):
            def _step(data: dict) -> dict:
                upgraded = dict(data)
                upgraded["schema_version"] = target
                return upgraded

            return _step

        for from_ver in range(0, CURRENT_SCHEMA_VERSION):
            _register_upgrader(from_ver, from_ver + 1, _make_step(from_ver + 1))

    def teardown_method(self):
        """Unregister the fake chain so registry state does not leak."""
        for from_ver in range(0, CURRENT_SCHEMA_VERSION):
            _unregister_upgrader(from_ver, from_ver + 1)

    def test_dispatch_advances_to_current_schema(self):
        """_dispatch_migration returns a dict whose schema_version equals CURRENT_SCHEMA_VERSION."""
        data = {"schema_version": 0}
        result = _dispatch_migration(data)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION


@pytest.mark.unit
def test_dispatch_missing_upgrader_raises_schema_error():
    """_dispatch_migration raises LockfileSchemaError when a required (N, N+1) step is unregistered.

    No upgrader is registered for (0, 1), so the walker cannot advance and must
    raise the missing-upgrade-path error.
    """
    data = {"schema_version": 0}
    with pytest.raises(LockfileSchemaError) as exc_info:
        _dispatch_migration(data)
    assert str(exc_info.value) == (
        f"no upgrade path from lockfile schema v0 to v{CURRENT_SCHEMA_VERSION}; this is a kanon bug; please report."
    )


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


@pytest.mark.unit
class TestNonAdvancingUpgraderDetected:
    """_dispatch_migration raises LockfileSchemaError when an upgrader does not advance schema_version."""

    def setup_method(self):
        """Register a broken upgrader for (0, 1) that does not change schema_version."""

        def _non_advancing(data: dict) -> dict:
            return dict(data)

        _register_upgrader(0, 1, _non_advancing)

    def teardown_method(self):
        """Remove the broken upgrader to keep registry clean."""
        _unregister_upgrader(0, 1)

    def test_non_advancing_upgrader_raises_schema_error(self):
        """_dispatch_migration raises LockfileSchemaError with exact message when upgrader does not advance."""
        data = {"schema_version": 0}
        with pytest.raises(LockfileSchemaError) as exc_info:
            _dispatch_migration(data)
        err = str(exc_info.value)
        assert "upgrader for schema v0->v1 did not advance schema_version" in err
        assert "returned 0" in err
        assert "this is a kanon bug" in err
        assert "please report" in err


@pytest.mark.unit
def test_current_schema_read_unchanged(tmp_path):
    """read_lockfile with schema_version == CURRENT_SCHEMA_VERSION works as expected."""
    p = tmp_path / "kanon.lock"
    p.write_text(_minimal_toml(CURRENT_SCHEMA_VERSION))
    lf = read_lockfile(p)
    assert lf.schema_version == CURRENT_SCHEMA_VERSION
    assert lf.generated_at == "2026-01-01T00:00:00Z"
    assert lf.generator == "kanon-cli/2.0.0"
    assert lf.kanon_hash == _VALID_KANON_HASH


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

        _unregister_upgrader(88, 89)
