"""Integration tests for --lock-file derivation through the CLI entry point.

Exercises AC-FUNC-007, AC-FUNC-008, and AC-FUNC-009 through the real CLI
entry point (kanon_cli.commands.install._run) against a fixture .kanon file
with mocked repo operations.

Precedence chain under test:
  1. Explicit --lock-file CLI flag wins (AC-FUNC-008).
  2. KANON_LOCK_FILE env var wins when CLI flag absent (AC-FUNC-009).
  3. <kanon-file-path>.lock derivation applies when both are absent (AC-FUNC-007).

Each test verifies both:
  a. The correct lock_file_path kwarg is passed to install().
  b. The lock file actually lands on disk at the expected path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_KANON_CONTENT = (
    "KANON_SOURCE_primary_URL=https://example.com/repo.git\n"
    "KANON_SOURCE_primary_REVISION=main\n"
    "KANON_SOURCE_primary_PATH=meta.xml\n"
)


def _write_kanon(directory: Path, filename: str = ".kanon") -> Path:
    """Write a minimal .kanon file and return its path."""
    kanon_path = directory / filename
    kanon_path.write_text(_KANON_CONTENT)
    return kanon_path


def _make_sentinel_side_effect(captured: list[tuple]):
    """Return a side_effect for the install() mock.

    The returned function:
    1. Records the positional/keyword arguments in ``captured``.
    2. Writes a sentinel file at the received lock_file_path so tests can
       assert the file lands on disk (AC-FUNC-007/008/009 on-disk requirement).
    """

    def _side_effect(*a, **kw):
        captured.append((a, kw))
        lock_path = kw.get("lock_file_path") or (a[1] if len(a) > 1 else None)
        if lock_path is not None:
            Path(lock_path).write_text("sentinel")

    return _side_effect


@pytest.mark.integration
class TestLockFileDerivation:
    """AC-FUNC-007: kanon install --kanon-file ./alt.kanon with no --lock-file or env
    writes the lockfile at ./alt.kanon.lock.
    """

    def test_derivation_from_non_default_kanon_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-007: lockfile path derived from non-default --kanon-file lands on disk."""
        monkeypatch.delenv("KANON_LOCK_FILE", raising=False)

        alt_kanon = _write_kanon(tmp_path, "alt.kanon")
        expected_lock = tmp_path / "alt.kanon.lock"

        args = MagicMock()
        args.kanonenv_path = alt_kanon
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        args.lock_file = None

        from kanon_cli.commands.install import _run

        captured: list[tuple] = []

        with patch("kanon_cli.commands.install.install", side_effect=_make_sentinel_side_effect(captured)):
            _run(args)

        assert len(captured) == 1, f"install() must be called exactly once; got {len(captured)}"
        call_args, call_kwargs = captured[0]
        # lock_file_path is the second positional arg or keyword arg
        lock_file_path = call_kwargs.get("lock_file_path") or (call_args[1] if len(call_args) > 1 else None)
        assert lock_file_path == expected_lock, f"Expected lock_file_path={expected_lock!r}, got {lock_file_path!r}"
        assert expected_lock.exists(), f"AC-FUNC-007: lock file must land on disk at {expected_lock!r}"

    def test_derivation_from_default_kanon_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-001 via CLI: default .kanon file derives .kanon.lock and lands on disk."""
        monkeypatch.delenv("KANON_LOCK_FILE", raising=False)

        kanon = _write_kanon(tmp_path, ".kanon")
        expected_lock = tmp_path / ".kanon.lock"

        args = MagicMock()
        args.kanonenv_path = kanon
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        args.lock_file = None

        from kanon_cli.commands.install import _run

        captured: list[tuple] = []

        with patch("kanon_cli.commands.install.install", side_effect=_make_sentinel_side_effect(captured)):
            _run(args)

        assert len(captured) == 1
        call_args, call_kwargs = captured[0]
        lock_file_path = call_kwargs.get("lock_file_path") or (call_args[1] if len(call_args) > 1 else None)
        assert lock_file_path == expected_lock, f"Expected lock_file_path={expected_lock!r}, got {lock_file_path!r}"
        assert expected_lock.exists(), f"AC-FUNC-001: lock file must land on disk at {expected_lock!r}"


@pytest.mark.integration
class TestExplicitLockFileFlag:
    """AC-FUNC-008: --lock-file explicit CLI flag wins over derivation."""

    def test_explicit_lock_file_wins_over_derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-008: --lock-file ./other.lock overrides alt.kanon.lock and lands on disk."""
        monkeypatch.delenv("KANON_LOCK_FILE", raising=False)

        alt_kanon = _write_kanon(tmp_path, "alt.kanon")
        explicit_lock = tmp_path / "other.lock"

        args = MagicMock()
        args.kanonenv_path = alt_kanon
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        args.lock_file = explicit_lock

        from kanon_cli.commands.install import _run

        captured: list[tuple] = []

        with patch("kanon_cli.commands.install.install", side_effect=_make_sentinel_side_effect(captured)):
            _run(args)

        assert len(captured) == 1
        call_args, call_kwargs = captured[0]
        lock_file_path = call_kwargs.get("lock_file_path") or (call_args[1] if len(call_args) > 1 else None)
        assert lock_file_path == explicit_lock, (
            f"CLI --lock-file must win; expected {explicit_lock!r}, got {lock_file_path!r}"
        )
        assert explicit_lock.exists(), f"AC-FUNC-008: lock file must land on disk at {explicit_lock!r}"


@pytest.mark.integration
class TestEnvVarLockFilePrecedence:
    """AC-FUNC-009: KANON_LOCK_FILE env var wins over derivation when CLI flag absent."""

    def test_env_var_wins_over_derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-009: KANON_LOCK_FILE env var path is used and lands on disk."""
        env_lock = str(tmp_path / "env-derived.lock")
        monkeypatch.setenv("KANON_LOCK_FILE", env_lock)

        alt_kanon = _write_kanon(tmp_path, "alt.kanon")

        args = MagicMock()
        args.kanonenv_path = alt_kanon
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        args.lock_file = None

        from kanon_cli.commands.install import _run

        captured: list[tuple] = []

        with patch("kanon_cli.commands.install.install", side_effect=_make_sentinel_side_effect(captured)):
            _run(args)

        assert len(captured) == 1
        call_args, call_kwargs = captured[0]
        lock_file_path = call_kwargs.get("lock_file_path") or (call_args[1] if len(call_args) > 1 else None)
        assert lock_file_path == Path(env_lock), (
            f"KANON_LOCK_FILE env var must win; expected {env_lock!r}, got {lock_file_path!r}"
        )
        assert Path(env_lock).exists(), f"AC-FUNC-009: lock file must land on disk at {env_lock!r}"

    def test_cli_flag_wins_over_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-005 via CLI: --lock-file wins even when KANON_LOCK_FILE is set; lands on disk."""
        env_lock = str(tmp_path / "env.lock")
        monkeypatch.setenv("KANON_LOCK_FILE", env_lock)

        alt_kanon = _write_kanon(tmp_path, "alt.kanon")
        explicit_lock = tmp_path / "explicit.lock"

        args = MagicMock()
        args.kanonenv_path = alt_kanon
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        args.lock_file = explicit_lock

        from kanon_cli.commands.install import _run

        captured: list[tuple] = []

        with patch("kanon_cli.commands.install.install", side_effect=_make_sentinel_side_effect(captured)):
            _run(args)

        assert len(captured) == 1
        call_args, call_kwargs = captured[0]
        lock_file_path = call_kwargs.get("lock_file_path") or (call_args[1] if len(call_args) > 1 else None)
        assert lock_file_path == explicit_lock, (
            f"CLI --lock-file must win over env var; expected {explicit_lock!r}, got {lock_file_path!r}"
        )
        assert explicit_lock.exists(), f"AC-FUNC-005/AC-FUNC-008: lock file must land on disk at {explicit_lock!r}"
        assert not Path(env_lock).exists(), (
            f"env-var lock path must NOT be written when CLI flag wins; found file at {env_lock!r}"
        )
