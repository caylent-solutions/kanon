# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for BV-09: envsubst .bak preserves first-run content.

Covers the skip-if-exists semantics for the .bak backup file:
  - First run creates .bak from the original manifest bytes.
  - Second run leaves an existing .bak untouched.
  - A pre-existing .bak (user-copied before envsubst) is left untouched.
  - When .bak write fails, envsubst exits non-zero and does NOT apply substitution.

AC-TEST-001, AC-TEST-002, AC-TEST-003, AC-TEST-004
"""

import pathlib
import stat

import pytest

from kanon_cli.repo.subcmds.envsubst import BAK_SUFFIX
from kanon_cli.repo.subcmds.envsubst import Envsubst
from kanon_cli.repo.subcmds.envsubst import _ensure_backup_once


# ---------------------------------------------------------------------------
# Shared manifest XML templates
# ---------------------------------------------------------------------------

_ORIGINAL_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${TEST_FETCH_URL}" />
</manifest>
"""

_SUBSTITUTED_FETCH = "https://example.com/repos"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(path: pathlib.Path, content: str) -> None:
    """Write string content to path as UTF-8."""
    path.write_text(content, encoding="utf-8")


def _make_cmd() -> Envsubst:
    """Return an Envsubst command instance with resolve_variable stubbed."""
    cmd = Envsubst()
    cmd.resolve_variable = lambda v: v.replace("${TEST_FETCH_URL}", _SUBSTITUTED_FETCH)
    return cmd


# ---------------------------------------------------------------------------
# AC-CODE-002: BAK_SUFFIX constant exists in module scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bak_suffix_constant_exists() -> None:
    """BAK_SUFFIX is a module-level constant; no inline literals allowed.

    AC-CODE-002
    """
    assert BAK_SUFFIX == ".bak", f"Expected BAK_SUFFIX == '.bak', got {BAK_SUFFIX!r}"


# ---------------------------------------------------------------------------
# _ensure_backup_once helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ensure_backup_once_creates_bak_when_absent(tmp_path: pathlib.Path) -> None:
    """_ensure_backup_once copies manifest to .bak when .bak does not exist.

    The .bak file must contain the original content byte-for-byte.
    """
    manifest = tmp_path / "default.xml"
    bak = tmp_path / "default.xml.bak"
    _write_manifest(manifest, _ORIGINAL_XML)

    _ensure_backup_once(manifest)

    assert bak.exists(), f"Expected {bak} to be created by _ensure_backup_once()"
    assert bak.read_bytes() == manifest.read_bytes(), "Backup must contain byte-identical content to the manifest"


@pytest.mark.unit
def test_ensure_backup_once_skips_when_bak_exists(tmp_path: pathlib.Path) -> None:
    """_ensure_backup_once does nothing when .bak already exists.

    The pre-existing .bak content must be byte-identical after the call.
    """
    manifest = tmp_path / "default.xml"
    bak = tmp_path / "default.xml.bak"
    _write_manifest(manifest, _ORIGINAL_XML)
    pre_existing_content = b"pre-existing content from user"
    bak.write_bytes(pre_existing_content)

    _ensure_backup_once(manifest)

    assert bak.read_bytes() == pre_existing_content, (
        f"_ensure_backup_once must not overwrite an existing .bak. "
        f"Expected {pre_existing_content!r}, got {bak.read_bytes()!r}"
    )


# ---------------------------------------------------------------------------
# Parametrized: first-run, second-run, pre-existing .bak
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario",
    [
        "first_run_creates_bak",
        "second_run_preserves_bak",
        "pre_existing_bak_preserved",
    ],
)
def test_bak_preservation_scenarios(tmp_path: pathlib.Path, scenario: str) -> None:
    """Parametrized test covering AC-TEST-001, AC-TEST-002, AC-TEST-003.

    first_run_creates_bak (AC-TEST-001):
        EnvSubst writes .bak whose bytes equal the manifest bytes before substitution.

    second_run_preserves_bak (AC-TEST-002):
        After a second run on the already-substituted manifest, .bak bytes still
        equal the original pre-substitution content.

    pre_existing_bak_preserved (AC-TEST-003):
        If .bak exists BEFORE the first envsubst invocation, its content is
        unchanged after envsubst runs.
    """
    manifest = tmp_path / "default.xml"
    bak = tmp_path / ("default.xml" + BAK_SUFFIX)
    cmd = _make_cmd()

    if scenario == "first_run_creates_bak":
        # AC-TEST-001
        _write_manifest(manifest, _ORIGINAL_XML)
        original_bytes = manifest.read_bytes()

        cmd.EnvSubst(str(manifest))

        assert bak.exists(), f"Expected .bak to be created on first run; not found at {bak}"
        assert bak.read_bytes() == original_bytes, (
            f"AC-TEST-001: .bak must contain original pre-substitution bytes. "
            f"Expected {original_bytes!r}, got {bak.read_bytes()!r}"
        )

    elif scenario == "second_run_preserves_bak":
        # AC-TEST-002: run once to substitute, then run again
        _write_manifest(manifest, _ORIGINAL_XML)
        original_bytes = manifest.read_bytes()

        # First run: creates .bak
        cmd.EnvSubst(str(manifest))
        bak_after_first = bak.read_bytes()
        assert bak_after_first == original_bytes, "Precondition: after first run .bak should contain original bytes"

        # Second run on the now-substituted manifest
        cmd.EnvSubst(str(manifest))
        bak_after_second = bak.read_bytes()

        assert bak_after_second == original_bytes, (
            f"AC-TEST-002: second run must NOT overwrite .bak. "
            f"Expected .bak to still contain original bytes, "
            f"but got {bak_after_second!r} (original was {original_bytes!r})"
        )

    elif scenario == "pre_existing_bak_preserved":
        # AC-TEST-003: .bak exists BEFORE first envsubst
        _write_manifest(manifest, _ORIGINAL_XML)
        user_content = b"user-placed backup content -- must not be touched"
        bak.write_bytes(user_content)

        cmd.EnvSubst(str(manifest))

        assert bak.read_bytes() == user_content, (
            f"AC-TEST-003: pre-existing .bak must not be overwritten by envsubst. "
            f"Expected {user_content!r}, got {bak.read_bytes()!r}"
        )

    else:
        raise AssertionError(f"Unknown scenario: {scenario!r}")


# ---------------------------------------------------------------------------
# AC-TEST-004: backup write failure exits non-zero; substitution NOT applied
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backup_write_failure_exits_nonzero_and_no_substitution(tmp_path: pathlib.Path) -> None:
    """AC-TEST-004: When .bak creation fails, envsubst raises and does NOT substitute.

    Makes the parent directory read-only so the .bak file cannot be created.
    EnvSubst must raise an OSError (or subclass) with a message naming the
    manifest path. The original manifest must be unchanged.
    """
    manifest = tmp_path / "default.xml"
    _write_manifest(manifest, _ORIGINAL_XML)
    original_bytes = manifest.read_bytes()

    # Make the directory read-only so .bak cannot be created
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        cmd = _make_cmd()
        with pytest.raises(OSError) as exc_info:
            cmd.EnvSubst(str(manifest))

        assert str(manifest) in str(exc_info.value) or str(tmp_path) in str(exc_info.value), (
            f"Error message must name the manifest path. Got: {exc_info.value!r}"
        )

        # Substitution must NOT have been applied
        assert manifest.read_bytes() == original_bytes, (
            f"Manifest must be unchanged when .bak write fails. "
            f"Expected {original_bytes!r}, got {manifest.read_bytes()!r}"
        )
    finally:
        # Restore permissions so pytest can clean up tmp_path
        tmp_path.chmod(stat.S_IRWXU)


# ---------------------------------------------------------------------------
# AC-CODE-001: Old remove-then-recreate code path is gone
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_old_remove_recreate_code_path_absent() -> None:
    """AC-CODE-001: The old Bug-12 remove-then-recreate code path is absent.

    Inspect the source of EnvSubst.EnvSubst to confirm os.remove is not called
    on the .bak path (the old stale-bak removal idiom).
    """
    import inspect

    source = inspect.getsource(Envsubst.EnvSubst)
    assert "os.remove" not in source, (
        "AC-CODE-001: os.remove must not appear in EnvSubst.EnvSubst -- "
        "the old Bug-12 remove-then-recreate code path must be fully removed."
    )


# ---------------------------------------------------------------------------
# AC-CODE-003: Implementation uses .exists() check, not FileExistsError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bak_logic_uses_exists_check_not_exception() -> None:
    """AC-CODE-003: Backup step uses explicit .exists() check.

    Inspect _ensure_backup_once source to confirm it uses Path.exists() and
    does not rely on catching FileExistsError to decide whether to skip.
    """
    import inspect

    source = inspect.getsource(_ensure_backup_once)
    assert "exists()" in source, "AC-CODE-003: _ensure_backup_once must use an explicit .exists() check"
    assert "FileExistsError" not in source, (
        "AC-CODE-003: _ensure_backup_once must not use FileExistsError catch-and-continue"
    )
