"""Unit tests for derive_lock_file_path -- lock-file path precedence chain.

Tests the six precedence cases from AC-FUNC-001 through AC-FUNC-006:
  (a) CLI wins over env and derivation.
  (b) Env wins over derivation when CLI is absent.
  (c) Derivation applies when CLI and env are both absent.
  (d) Non-default --kanon-file derives sibling lockfile.
  (e) Explicit --lock-file with non-default --kanon-file still wins.
  (f) Empty-string env-var is treated as unset (falls through to derivation).
"""

from pathlib import Path

import pytest

from kanon_cli.utils.lock_file_path import derive_lock_file_path


@pytest.mark.unit
@pytest.mark.parametrize(
    "kanon_file, cli_lock_file, env_lock_file, expected",
    [
        # AC-FUNC-001: default .kanon, no CLI, no env -- derivation produces .kanon.lock
        (
            Path("./.kanon"),
            None,
            None,
            Path("./.kanon.lock"),
        ),
        # AC-FUNC-002: non-default alt.kanon, no CLI, no env -- derivation produces alt.kanon.lock
        (
            Path("./alt.kanon"),
            None,
            None,
            Path("./alt.kanon.lock"),
        ),
        # AC-FUNC-003: CLI wins -- returns the explicit CLI path
        (
            Path("./.kanon"),
            Path("./explicit.lock"),
            None,
            Path("./explicit.lock"),
        ),
        # AC-FUNC-004: env wins over derivation when CLI absent
        (
            Path("./.kanon"),
            None,
            "./env.lock",
            Path("./env.lock"),
        ),
        # AC-FUNC-005: CLI wins over both env and derivation
        (
            Path("./.kanon"),
            Path("./explicit.lock"),
            "./env.lock",
            Path("./explicit.lock"),
        ),
        # AC-FUNC-006: empty-string env-var is treated as unset -- falls through to derivation
        (
            Path("./.kanon"),
            None,
            "",
            Path("./.kanon.lock"),
        ),
    ],
)
def test_derive_lock_file_path_precedence(
    kanon_file: Path,
    cli_lock_file: Path | None,
    env_lock_file: str | None,
    expected: Path,
) -> None:
    """derive_lock_file_path respects the three-tier precedence chain for all six cases."""
    result = derive_lock_file_path(kanon_file, cli_lock_file, env_lock_file)
    assert result == expected, (
        f"derive_lock_file_path({kanon_file!r}, {cli_lock_file!r}, {env_lock_file!r}) "
        f"returned {result!r}; expected {expected!r}"
    )


@pytest.mark.unit
def test_derive_lock_file_path_non_default_kanon_file_with_explicit_cli() -> None:
    """AC-FUNC-003 extended: explicit --lock-file with non-default --kanon-file still wins."""
    result = derive_lock_file_path(
        Path("/some/path/myproject.kanon"),
        Path("/other/explicit.lock"),
        None,
    )
    assert result == Path("/other/explicit.lock"), f"CLI path must win over derivation; got {result!r}"


@pytest.mark.unit
def test_derive_lock_file_path_non_default_kanon_file_derives_sibling() -> None:
    """AC-FUNC-002 extended: absolute non-default kanon file derives sibling .lock."""
    result = derive_lock_file_path(
        Path("/workspace/project/.kanon-custom"),
        None,
        None,
    )
    assert result == Path("/workspace/project/.kanon-custom.lock"), (
        f"Sibling derivation must append .lock suffix; got {result!r}"
    )


@pytest.mark.unit
def test_derive_lock_file_path_env_wins_over_derivation_non_default_kanon() -> None:
    """AC-FUNC-004 extended: env wins over derivation with non-default kanon file."""
    result = derive_lock_file_path(
        Path("./alt.kanon"),
        None,
        "/tmp/from-env.lock",
    )
    assert result == Path("/tmp/from-env.lock"), f"Env path must win over derivation; got {result!r}"


@pytest.mark.unit
def test_derive_lock_file_path_whitespace_only_env_is_not_empty() -> None:
    """Whitespace-only env-var is NOT empty -- it is treated as a literal path."""
    result = derive_lock_file_path(Path("./.kanon"), None, "  ")
    assert result == Path("  "), "A whitespace-only env value is a non-empty string; it must be used as-is"
