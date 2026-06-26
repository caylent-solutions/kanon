"""End-to-end `kanon doctor` health-check journey (item 21, spec Section 4.6).

Builds a real installed workspace the way an operator would -- a real `kanon add`
authors the alias-keyed `.kanon` and a real `kanon install` resolves it and writes
the schema-v4 `.kanon.lock` -- then asserts that `kanon doctor` passes cleanly
against the freshly installed tree.

Each subsequent test mutates exactly one aspect of that installed workspace to
provoke one doctor defect and asserts the corresponding exit code and message:

- hand-edit / kanon_hash mismatch: editing a source's `_PATH` changes the
  hashed source triple, so the lockfile's recorded `kanon_hash` no longer
  matches -> ERROR `kanon_hash mismatch`, exit 1.
- orphaned lock entry: an extra `[[sources]]` block whose alias is absent from
  `.kanon` (the `kanon_hash` still matches the unchanged `.kanon`) -> ERROR
  `orphan lock entry`, exit 1.
- branch drift: advancing the branch tip past the locked SHA is an INFO notice
  by default (exit 0) and an ERROR under `--strict-drift` (exit 1).
- dangling SHA: re-pinning the source to an unreachable 40-hex SHA (with the
  lockfile and `kanon_hash` updated to stay consistent) -> ERROR
  `dangling SHA`, exit 1.
- unreachable remote: pointing the source URL at a non-existent `file://` repo
  is a WARN-only finding referencing `docs/git-auth-setup.md` -> exit 0.

The workspace uses `file://` source URLs, so each subprocess runs with
`KANON_ALLOW_INSECURE_REMOTES=1`. A per-test `KANON_HOME` isolates the shared
content-addressed store and caches. `KANON_GIT_RETRY_COUNT=1` keeps the
unreachable-remote `git ls-remote` from retrying.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess

import pytest

from kanon_cli.core.kanon_hash import kanon_hash
from tests.scenarios.conftest import (
    init_git_work_dir,
    run_git,
    run_kanon,
)


_CATALOG_ENTRY_NAME = "widget"
_CATALOG_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    "  <catalog-metadata>\n"
    "    <name>{name}</name>\n"
    "    <display-name>{name} Display</display-name>\n"
    "    <description>Scenario entry {name}.</description>\n"
    "    <version>1.0.0</version>\n"
    "    <type>plugin</type>\n"
    "    <owner-name>Scenario Owner</owner-name>\n"
    "    <owner-email>owner@kanon.example</owner-email>\n"
    "    <keywords>{name}</keywords>\n"
    "  </catalog-metadata>\n"
    "</manifest>\n"
)


def _build_catalog_repo(parent: pathlib.Path, entry_name: str) -> pathlib.Path:
    """Build a bare catalog repo carrying one marketplace manifest entry.

    The repo holds ``repo-specs/<entry_name>-marketplace.xml`` on ``main`` and a
    ``refs/tags/<entry_name>/1.0.0`` release tag, the per-manifest catalog tag
    scheme that ``kanon add`` resolves against.

    Args:
        parent: Temp parent directory for the work and bare repos.
        entry_name: The catalog entry (manifest) name.

    Returns:
        The resolved bare repo path.
    """
    work = parent / "catalog.work"
    bare = parent / "catalog.git"
    init_git_work_dir(work)
    spec_dir = work / "repo-specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / f"{entry_name}-marketplace.xml").write_text(_CATALOG_XML_TEMPLATE.format(name=entry_name))
    run_git(["add", "repo-specs"], work)
    run_git(["commit", "-m", f"seed catalog entry {entry_name}"], work)
    run_git(["tag", "-a", f"{entry_name}/1.0.0", "-m", "release"], work)
    run_git(["clone", "--bare", str(work), str(bare)], work.parent)
    return bare.resolve()


def _doctor_env(kanon_home: pathlib.Path) -> dict[str, str]:
    """Return the subprocess env for the doctor journey.

    Isolates KANON_HOME, permits ``file://`` remotes, and disables ls-remote
    retries so the unreachable-remote subcheck returns promptly. Strips any
    inherited KANON_CATALOG_SOURCES so install stays hermetic.

    Args:
        kanon_home: Per-test shared-store / cache root.

    Returns:
        A fully-populated environment dict for ``run_kanon(env=...)``.
    """
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    env["KANON_HOME"] = str(kanon_home)
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    env["KANON_GIT_RETRY_COUNT"] = "1"
    return env


def _branch_pin_kanon(kanon_file: pathlib.Path, alias: str) -> None:
    """Rewrite the source's ``_REF`` to the branch ``main`` in place.

    ``kanon add`` pins a tag ref (``refs/tags/<name>/<version>``); the doctor
    branch-drift subcheck only applies to branch-shaped refs, so the journey
    re-pins the source to ``main`` before installing.

    Args:
        kanon_file: Path to the ``.kanon`` file.
        alias: The source alias whose ``_REF`` line is rewritten.
    """
    text = kanon_file.read_text(encoding="utf-8")
    new_text, count = re.subn(
        rf"(?m)^KANON_SOURCE_{re.escape(alias)}_REF=.*$",
        f"KANON_SOURCE_{alias}_REF=main",
        text,
    )
    if count != 1:
        raise RuntimeError(f"expected exactly one _REF line for {alias!r}; rewrote {count}")
    kanon_file.write_text(new_text, encoding="utf-8")


def _set_kanon_field(kanon_file: pathlib.Path, alias: str, field: str, value: str) -> None:
    """Replace the value of ``KANON_SOURCE_<alias>_<field>`` in place.

    Args:
        kanon_file: Path to the ``.kanon`` file.
        alias: The source alias.
        field: The block field suffix (e.g. ``PATH`` or ``URL``).
        value: The new value.
    """
    text = kanon_file.read_text(encoding="utf-8")
    new_text, count = re.subn(
        rf"(?m)^KANON_SOURCE_{re.escape(alias)}_{re.escape(field)}=.*$",
        f"KANON_SOURCE_{alias}_{field}={value}",
        text,
    )
    if count != 1:
        raise RuntimeError(f"expected exactly one _{field} line for {alias!r}; rewrote {count}")
    kanon_file.write_text(new_text, encoding="utf-8")


def _rewrite_lock_kanon_hash(lock_file: pathlib.Path, new_hash: str) -> None:
    """Overwrite the lockfile's ``kanon_hash`` field with ``new_hash``.

    Args:
        lock_file: Path to the ``.kanon.lock`` file.
        new_hash: The replacement ``kanon_hash`` value.
    """
    text = lock_file.read_text(encoding="utf-8")
    new_text, count = re.subn(r'(?m)^kanon_hash = "[^"]*"$', f'kanon_hash = "{new_hash}"', text)
    if count != 1:
        raise RuntimeError(f"expected exactly one kanon_hash line; rewrote {count}")
    lock_file.write_text(new_text, encoding="utf-8")


def _install_workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
    """Build a real installed workspace via real ``kanon add`` + ``kanon install``.

    Args:
        tmp_path: Per-test temp directory.

    Returns:
        A tuple ``(workspace, kanon_home, env)`` where ``workspace`` holds the
        installed ``.kanon`` + ``.kanon.lock`` and ``env`` is the subprocess
        environment to reuse for the doctor invocations.
    """
    repos = tmp_path / "repos"
    repos.mkdir()
    catalog_bare = _build_catalog_repo(repos, _CATALOG_ENTRY_NAME)

    kanon_home = tmp_path / "kanon-home"
    kanon_home.mkdir()
    env = _doctor_env(kanon_home)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    add = run_kanon(
        "add",
        _CATALOG_ENTRY_NAME,
        "--catalog-source",
        f"file://{catalog_bare}@main",
        cwd=workspace,
        env=env,
    )
    assert add.returncode == 0, f"kanon add failed: stdout={add.stdout!r} stderr={add.stderr!r}"

    kanon_file = workspace / ".kanon"
    _branch_pin_kanon(kanon_file, _CATALOG_ENTRY_NAME)

    install = run_kanon("install", cwd=workspace, env=env)
    assert install.returncode == 0, f"kanon install failed: stdout={install.stdout!r} stderr={install.stderr!r}"

    lock_file = workspace / ".kanon.lock"
    assert lock_file.exists(), "kanon install did not write .kanon.lock"
    return workspace, kanon_home, env


def _doctor(workspace: pathlib.Path, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess:
    """Run ``kanon doctor`` against the installed workspace.

    Args:
        workspace: The installed workspace directory.
        env: The subprocess environment.
        extra: Extra doctor arguments (e.g. ``--strict-drift``).

    Returns:
        The completed subprocess.
    """
    return run_kanon(
        "doctor",
        "--kanon-file",
        str(workspace / ".kanon"),
        "--lock-file",
        str(workspace / ".kanon.lock"),
        *extra,
        cwd=workspace,
        env=env,
    )


@pytest.mark.scenario
class TestDoctorJourney:
    """Real installed-workspace journey through every ``kanon doctor`` defect."""

    def test_clean_workspace_passes(self, tmp_path: pathlib.Path) -> None:
        """A freshly installed workspace passes ``kanon doctor`` cleanly."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)

        result = _doctor(workspace, env)

        assert result.returncode == 0, f"clean doctor must exit 0: stderr={result.stderr!r}"
        assert "[ok] kanon_hash consistency" in result.stdout
        assert "[ok] no orphaned lock entries" in result.stdout
        assert "[ok] no branch drift" in result.stdout
        assert "ERROR:" not in result.stderr

    def test_hand_edit_triggers_hash_mismatch(self, tmp_path: pathlib.Path) -> None:
        """Hand-editing a hashed source field flips the kanon_hash -> ERROR + exit 1."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)
        kanon_file = workspace / ".kanon"

        _set_kanon_field(kanon_file, _CATALOG_ENTRY_NAME, "PATH", "repo-specs/hand-edited.xml")

        result = _doctor(workspace, env)

        assert result.returncode != 0, f"hand-edited .kanon must exit non-zero: stderr={result.stderr!r}"
        assert "kanon_hash mismatch" in result.stderr
        assert "hand-edited" in result.stderr

    def test_orphan_lock_entry_detected(self, tmp_path: pathlib.Path) -> None:
        """An extra lock [[sources]] block absent from .kanon -> ERROR orphan + exit 1."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)
        lock_file = workspace / ".kanon.lock"

        orphan_block = (
            "\n"
            "[[sources]]\n"
            'alias = "ghost"\n'
            'name = "ghost"\n'
            'url = "https://example.com/org/ghost.git"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "main"\n'
            'resolved_sha = "' + "a" * 40 + '"\n'
            'path = "repo-specs/ghost-marketplace.xml"\n'
        )
        lock_file.write_text(lock_file.read_text(encoding="utf-8").rstrip() + "\n" + orphan_block, encoding="utf-8")

        result = _doctor(workspace, env)

        assert result.returncode != 0, f"orphan lock entry must exit non-zero: stderr={result.stderr!r}"
        assert "orphan lock entry" in result.stderr
        assert "ghost" in result.stderr

    def test_branch_drift_is_info_by_default(self, tmp_path: pathlib.Path) -> None:
        """Advancing the branch tip past the locked SHA is an INFO notice (exit 0)."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)

        catalog_work = tmp_path / "repos" / "catalog.work"
        catalog_bare = tmp_path / "repos" / "catalog.git"
        run_git(["commit", "--allow-empty", "-m", "advance main"], catalog_work)
        run_git(["push", str(catalog_bare), "main"], catalog_work)

        result = _doctor(workspace, env)

        assert result.returncode == 0, f"branch drift without --strict-drift must exit 0: stderr={result.stderr!r}"
        assert "branch drift" in result.stderr.lower()
        assert f"source '{_CATALOG_ENTRY_NAME}'" in result.stderr

    def test_branch_drift_errors_under_strict_drift(self, tmp_path: pathlib.Path) -> None:
        """The same drift is an ERROR (exit 1) under --strict-drift."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)

        catalog_work = tmp_path / "repos" / "catalog.work"
        catalog_bare = tmp_path / "repos" / "catalog.git"
        run_git(["commit", "--allow-empty", "-m", "advance main"], catalog_work)
        run_git(["push", str(catalog_bare), "main"], catalog_work)

        result = _doctor(workspace, env, "--strict-drift")

        assert result.returncode != 0, f"--strict-drift on drifted source must exit non-zero: stderr={result.stderr!r}"
        error_drift_lines = [
            line for line in result.stderr.splitlines() if line.startswith("ERROR:") and "branch drift" in line
        ]
        assert len(error_drift_lines) == 1, f"expected one ERROR drift finding: stderr={result.stderr!r}"
        assert f"source '{_CATALOG_ENTRY_NAME}'" in error_drift_lines[0]

    def test_dangling_sha_detected(self, tmp_path: pathlib.Path) -> None:
        """A SHA-pinned source whose locked SHA is unreachable -> ERROR dangling SHA + exit 1."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)
        kanon_file = workspace / ".kanon"
        lock_file = workspace / ".kanon.lock"

        fake_sha = "d" * 40
        _set_kanon_field(kanon_file, _CATALOG_ENTRY_NAME, "REF", fake_sha)

        lock_text = lock_file.read_text(encoding="utf-8")
        lock_text = re.sub(r'(?m)^ref_spec = "main"$', f'ref_spec = "{fake_sha}"', lock_text)
        lock_text = re.sub(r'(?m)^resolved_ref = "main"$', f'resolved_ref = "{fake_sha}"', lock_text)
        lock_text = re.sub(r'(?m)^resolved_sha = "[0-9a-f]{40}"$', f'resolved_sha = "{fake_sha}"', lock_text)
        lock_file.write_text(lock_text, encoding="utf-8")

        _rewrite_lock_kanon_hash(lock_file, kanon_hash(kanon_file))

        result = _doctor(workspace, env)

        assert result.returncode != 0, f"dangling SHA must exit non-zero: stderr={result.stderr!r}"
        assert "dangling SHA" in result.stderr
        assert fake_sha in result.stderr

    def test_unreachable_remote_warns_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """Pointing a source at a non-existent remote is a WARN-only finding (exit 0)."""
        workspace, _kanon_home, env = _install_workspace(tmp_path)
        kanon_file = workspace / ".kanon"
        lock_file = workspace / ".kanon.lock"

        gone_url = f"file://{tmp_path / 'repos' / 'gone.git'}"
        _set_kanon_field(kanon_file, _CATALOG_ENTRY_NAME, "URL", gone_url)

        lock_text = lock_file.read_text(encoding="utf-8")
        lock_text = re.sub(r'(?m)^url = ".*"$', f'url = "{gone_url}"', lock_text)
        lock_file.write_text(lock_text, encoding="utf-8")

        _rewrite_lock_kanon_hash(lock_file, kanon_hash(kanon_file))

        result = _doctor(workspace, env)

        assert result.returncode == 0, f"unreachable remote is warn-only and must exit 0: stderr={result.stderr!r}"
        warn_lines = [
            line for line in result.stderr.splitlines() if line.startswith("WARN:") and "unreachable" in line.lower()
        ]
        assert len(warn_lines) == 1, f"expected exactly one unreachable-remote WARN: stderr={result.stderr!r}"
        assert "docs/git-auth-setup.md" in result.stderr
        assert "gone" in result.stderr
