"""TDD RED tests for the repo_envsubst() public API function.

These tests define the contract for repo_envsubst() and must fail initially
because the function does not exist yet. The tests will pass once
repo_envsubst() is implemented in E0-F2-S2-T4.

Contract under test:
    repo_envsubst(repo_dir: str, env_vars: dict[str, str]) -> None

    - Substitutes ${VAR} placeholders in manifest XML files under
      <repo_dir>/.repo/manifests/**/*.xml using the supplied env_vars dict.
    - Creates a .bak backup of each modified file before writing.
    - Leaves undefined variables intact (does not expand them to empty string).
    - Does not mutate sys.argv.
    - Restores os.environ to its pre-call state after returning.
    - Raises an exception (not calls sys.exit) when the underlying command fails.
    - Never calls os.execv (process replacement forbidden in library mode).
    - Never reads from sys.stdin.
"""

import copy
import io
import os
import pathlib
import sys
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_manifest_dir(base: pathlib.Path) -> pathlib.Path:
    """Create the .repo/manifests/ directory structure under base.

    Returns the manifests directory path.
    """
    manifests_dir = base / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    return manifests_dir


def _write_manifest(manifests_dir: pathlib.Path, filename: str, content: str) -> pathlib.Path:
    """Write a manifest XML file and return its path."""
    manifest_path = manifests_dir / filename
    manifest_path.write_text(content, encoding="utf-8")
    return manifest_path


_SIMPLE_MANIFEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_ENTITY_MANIFEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <annotation name="desc" value="less &lt; greater &gt; ampersand &amp;" />
</manifest>
"""

_UNDEFINED_VAR_MANIFEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <remote name="secondary" fetch="${UNDEFINED_VAR_XYZ}" />
</manifest>
"""


# ---------------------------------------------------------------------------
# AC-TEST-001: repo_envsubst() expands environment variables in the manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_expands_environment_variables(tmp_path: pathlib.Path) -> None:
    """AC-TEST-001: repo_envsubst() substitutes ${VAR} placeholders with values.

    Sets up a manifest XML with ${GITBASE} placeholder, calls repo_envsubst()
    with env_vars={"GITBASE": "https://github.com/org/"}, and asserts the
    expanded value appears in the output manifest while the placeholder is gone.
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)

    gitbase_value = "https://github.com/org/"
    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={"GITBASE": gitbase_value},
    )

    result_content = manifest_path.read_text(encoding="utf-8")
    assert gitbase_value in result_content, (
        f"Expected expanded value {gitbase_value!r} in manifest after repo_envsubst(), "
        f"but it was not found.\nManifest content:\n{result_content}"
    )
    assert "${GITBASE}" not in result_content, (
        f"Expected placeholder ${{GITBASE}} to be removed from manifest after expansion, "
        f"but it is still present.\nManifest content:\n{result_content}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: repo_envsubst() preserves XML entities
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_preserves_xml_entities(tmp_path: pathlib.Path) -> None:
    """AC-TEST-002: repo_envsubst() must not corrupt XML entity references.

    A manifest containing &lt; &gt; &amp; entities must survive envsubst with
    those entities still present (or their decoded equivalents in attribute
    text), not mangled into unescaped characters that would break XML parsing.
    The output must be parseable as valid XML.
    """
    import xml.etree.ElementTree as ET

    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = _write_manifest(manifests_dir, "entities.xml", _ENTITY_MANIFEST_TEMPLATE)

    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={"GITBASE": "https://github.com/org/"},
    )

    result_content = manifest_path.read_text(encoding="utf-8")

    # Output must still be parseable as valid XML -- if entities were corrupted
    # the parser will raise. This assertion can fail if envsubst corrupts XML.
    try:
        ET.fromstring(result_content)
    except ET.ParseError as exc:
        raise AssertionError(
            f"Manifest XML is no longer valid after repo_envsubst() -- XML entities may be corrupted.\n"
            f"ParseError: {exc}\n"
            f"Manifest content:\n{result_content}"
        ) from exc


# ---------------------------------------------------------------------------
# AC-TEST-003: repo_envsubst() creates a backup of the original manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_creates_backup_of_original_manifest(tmp_path: pathlib.Path) -> None:
    """AC-TEST-003: repo_envsubst() must create a .bak backup before modifying.

    After calling repo_envsubst(), a file named <manifest>.bak must exist
    alongside the modified manifest. The backup must contain the original
    pre-substitution content.
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)
    original_content = _SIMPLE_MANIFEST_TEMPLATE

    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={"GITBASE": "https://github.com/org/"},
    )

    backup_path = pathlib.Path(str(manifest_path) + ".bak")
    assert backup_path.exists(), f"Expected backup file {backup_path} to exist after repo_envsubst(), but it does not."

    backup_content = backup_path.read_text(encoding="utf-8")
    assert "${GITBASE}" in backup_content, (
        f"Backup file must contain the original unmodified content with ${{GITBASE}} placeholder, "
        f"but it does not.\nOriginal content:\n{original_content}\nBackup content:\n{backup_content}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: repo_envsubst() preserves undefined variables
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_preserves_undefined_variables(tmp_path: pathlib.Path) -> None:
    """AC-TEST-004: repo_envsubst() must leave undefined ${VAR} placeholders intact.

    If a variable referenced in a manifest is not present in env_vars (and not
    in os.environ), the placeholder must remain literally in the output --
    it must not be expanded to an empty string or removed.
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = _write_manifest(manifests_dir, "with_undefined.xml", _UNDEFINED_VAR_MANIFEST_TEMPLATE)

    # Provide only GITBASE; UNDEFINED_VAR_XYZ is intentionally absent.
    # Also ensure UNDEFINED_VAR_XYZ is not in os.environ by removing it if present.
    env_without_undefined = {k: v for k, v in os.environ.items() if k != "UNDEFINED_VAR_XYZ"}
    env_without_undefined.pop("UNDEFINED_VAR_XYZ", None)

    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={"GITBASE": "https://github.com/org/"},
    )

    result_content = manifest_path.read_text(encoding="utf-8")
    assert "${UNDEFINED_VAR_XYZ}" in result_content, (
        f"Expected undefined variable ${{UNDEFINED_VAR_XYZ}} to be preserved literally in "
        f"the manifest, but it was removed or expanded.\nManifest content:\n{result_content}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: repo_envsubst() does not mutate sys.argv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_does_not_mutate_sys_argv(tmp_path: pathlib.Path) -> None:
    """AC-TEST-005: repo_envsubst() must not alter sys.argv.

    Snapshot sys.argv before calling repo_envsubst() and assert the list is
    identical after the call (same length, same elements, same order).
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)

    argv_before = list(sys.argv)

    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={"GITBASE": "https://github.com/org/"},
    )

    argv_after = list(sys.argv)
    assert argv_after == argv_before, (
        f"repo_envsubst() mutated sys.argv.\n  Before: {argv_before!r}\n  After:  {argv_after!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-006: repo_envsubst() restores os.environ after the call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_restores_os_environ_after_call(tmp_path: pathlib.Path) -> None:
    """AC-TEST-006: repo_envsubst() must restore os.environ to its pre-call state.

    repo_envsubst() needs to temporarily inject env_vars into os.environ for
    the underlying envsubst subcommand to see them. After the call, every key
    that was not present before must be removed, and any key that was present
    must be restored to its original value.
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)

    env_before = copy.deepcopy(dict(os.environ))
    # Use a key that is unlikely to be set in the actual environment.
    test_key = "KANON_TEST_ENVSUBST_SENTINEL_VAR_39275"
    assert test_key not in env_before, (
        f"Test sentinel key {test_key!r} is already in os.environ -- choose a different key."
    )

    repo_pkg.repo_envsubst(
        repo_dir=str(tmp_path),
        env_vars={
            "GITBASE": "https://github.com/org/",
            test_key: "sentinel-value",
        },
    )

    env_after = dict(os.environ)

    added = {k: env_after[k] for k in env_after if k not in env_before}
    removed = {k: env_before[k] for k in env_before if k not in env_after}
    changed = {k: (env_before[k], env_after[k]) for k in env_before if k in env_after and env_before[k] != env_after[k]}

    violations: list[str] = []
    if added:
        violations.append(f"Keys added to os.environ: {added!r}")
    if removed:
        violations.append(f"Keys removed from os.environ: {removed!r}")
    if changed:
        violations.append(f"Keys changed in os.environ: {changed!r}")

    assert not violations, "repo_envsubst() did not restore os.environ:\n" + "\n".join(f"  {v}" for v in violations)


# ---------------------------------------------------------------------------
# AC-TEST-007: repo_envsubst() raises on failure (does not call sys.exit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_raises_on_failure_not_sys_exit(tmp_path: pathlib.Path) -> None:
    """AC-TEST-007: repo_envsubst() must raise RepoCommandError on failure, not call sys.exit().

    Pass a repo_dir that points to a directory with no .repo/ subdirectory.
    The underlying envsubst command must fail. repo_envsubst() must surface the
    failure as a RepoCommandError (not SystemExit) so library callers can catch
    and handle it programmatically.
    """
    # tmp_path has no .repo/ directory -- the envsubst command will fail.
    empty_dir = tmp_path / "no_repo_dir"
    empty_dir.mkdir()

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_envsubst(
            repo_dir=str(empty_dir),
            env_vars={"GITBASE": "https://github.com/org/"},
        )

    assert exc_info.value.exit_code is not None, (
        f"RepoCommandError must carry the exit_code from the underlying failure. Got: {exc_info.value!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-008: repo_envsubst() does not call os.execv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_does_not_call_os_execv(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-008: repo_envsubst() must not call os.execv during execution.

    Monkeypatch os.execv with a sentinel that raises AssertionError if invoked.
    Any call to os.execv from within repo_envsubst() means the calling process
    would be replaced -- a critical isolation violation for library code.
    """
    manifests_dir = _make_manifest_dir(tmp_path)
    _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)

    execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv was called during repo_envsubst(): path={path!r}, argv={argv!r}")

    monkeypatch.setattr(os, "execv", _record_execv)

    # Allow the call to succeed or raise a library exception -- either is fine.
    try:
        repo_pkg.repo_envsubst(
            repo_dir=str(tmp_path),
            env_vars={"GITBASE": "https://github.com/org/"},
        )
    except SystemExit as exc:
        raise AssertionError(
            f"repo_envsubst() raised SystemExit({exc.code!r}) -- library code must not exit the process."
        ) from exc

    assert execv_calls == [], f"os.execv was called {len(execv_calls)} time(s) during repo_envsubst(): {execv_calls!r}"


# ---------------------------------------------------------------------------
# AC-TEST-009: repo_envsubst() does not read from stdin
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_does_not_read_from_stdin(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-009: repo_envsubst() must not read from sys.stdin.

    Replace sys.stdin with a sentinel stream that raises AssertionError on any
    read attempt. If repo_envsubst() attempts to read stdin (e.g., for an
    interactive prompt), the test will fail with a clear message.
    """

    class _NoReadStdin(io.RawIOBase):
        """Stdin replacement that raises on any read operation."""

        def read(self, n: int = -1) -> bytes:
            raise AssertionError("repo_envsubst() attempted to read from stdin -- interactive prompts are forbidden.")

        def readline(self, size: int = -1) -> bytes:
            raise AssertionError(
                "repo_envsubst() attempted to readline from stdin -- interactive prompts are forbidden."
            )

        def readinto(self, b: bytearray) -> int:
            raise AssertionError(
                "repo_envsubst() attempted to readinto from stdin -- interactive prompts are forbidden."
            )

        def readable(self) -> bool:
            return True

        def fileno(self) -> int:
            raise io.UnsupportedOperation("fileno not supported on sentinel stdin")

    manifests_dir = _make_manifest_dir(tmp_path)
    _write_manifest(manifests_dir, "default.xml", _SIMPLE_MANIFEST_TEMPLATE)

    sentinel_stdin = _NoReadStdin()
    monkeypatch.setattr(sys, "stdin", sentinel_stdin)

    # Allow the call to succeed or raise a library exception -- either is fine
    # as long as no stdin read is attempted.
    try:
        repo_pkg.repo_envsubst(
            repo_dir=str(tmp_path),
            env_vars={"GITBASE": "https://github.com/org/"},
        )
    except SystemExit as exc:
        raise AssertionError(
            f"repo_envsubst() raised SystemExit({exc.code!r}) -- library code must not exit the process."
        ) from exc
